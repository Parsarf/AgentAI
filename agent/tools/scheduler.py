"""The user's agent manages its own scheduled jobs.

Tenancy: the acting user comes from task context only — every query in here
is scoped to them, and pause/delete resolve the job via ``get_job(user_id,
job_id)`` FIRST, so a job id belonging to someone else reads exactly like a
job id that doesn't exist ("job not found"; existence is never leaked).

The running scheduler service is never imported and driven directly: after
any mutation we publish ``job.changed`` and the service subscribes + refreshes
itself. Only the pure cron helper (``next_cron_run``) is imported — it holds
the shared cron semantics used to seed a new job's next_run_at.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from core import db, events, skills
from core.config import settings
from core.logging import get_logger
from core.scheduler_service import next_cron_run
from tools.base import ToolResult, current_task_id, current_user_id, tool

logger = get_logger(__name__)

_MAX_INSTRUCTION_CHARS = 4000
_MAX_SCRIPT_CHARS = 50_000


def _context_ids() -> tuple[UUID, str | None]:
    uid = UUID(str(current_user_id.get()))
    tid = current_task_id.get()
    return uid, tid


@tool(
    "create_job",
    "Create one of this user's scheduled jobs. kind='recurring' runs the "
    "instruction on a 5-field cron schedule (in the user's timezone). "
    "kind='watcher' polls with a cheap check script and only escalates to a "
    "full task when the check output changes.",
    risk="moderate",
)
async def create_job(
    kind: Literal["recurring", "watcher"],
    schedule: str,
    instruction: str,
    check_mode: Literal["always", "on_change"] = "always",
    check_script: str | None = None,
) -> ToolResult:
    """Create a job scoped to the acting user, under their plan's job cap."""
    uid, tid = _context_ids()
    user = await db.get_user(uid)
    if user is None:
        return ToolResult(ok=False, error="unknown user")
    from core import billing
    plan = settings.plan_for(billing._effective_plan(user))

    instruction = (instruction or "").strip()
    schedule = (schedule or "").strip()

    if kind == "watcher":
        if check_mode != "on_change":
            return ToolResult(ok=False, error="watcher jobs require check_mode='on_change'")
        if not check_script or not check_script.strip():
            return ToolResult(ok=False, error="watcher jobs require a check_script (python source)")
    else:
        if check_mode != "always":
            return ToolResult(ok=False, error="recurring jobs always use check_mode='always'")
        if check_script:
            return ToolResult(ok=False, error="recurring jobs do not take a check_script")
    if not instruction:
        return ToolResult(ok=False, error="instruction is required")
    if len(instruction) > _MAX_INSTRUCTION_CHARS:
        return ToolResult(ok=False, error=f"instruction too long (max {_MAX_INSTRUCTION_CHARS} chars)")
    if check_script and len(check_script) > _MAX_SCRIPT_CHARS:
        return ToolResult(ok=False, error=f"check_script too long (max {_MAX_SCRIPT_CHARS} chars)")

    if not plan.autonomous_jobs or plan.max_active_jobs <= 0:
        return ToolResult(
            ok=False,
            error=f"scheduled jobs are not enabled on the '{user.plan_tier}' plan",
        )

    active = await db.count_active_jobs(uid)
    if active >= plan.max_active_jobs:
        return ToolResult(
            ok=False,
            error=f"active job limit reached ({active}/{plan.max_active_jobs} on the "
                  f"'{user.plan_tier}' plan) — pause or delete a job first",
        )

    now = datetime.now(UTC)
    try:
        next_run = next_cron_run(schedule, user.timezone, now)
    except ValueError as exc:
        return ToolResult(
            ok=False,
            error=f"schedule is not a valid 5-field cron expression ({exc}); "
                  "example: '*/15 * * * *'",
        )

    job = await db.create_job(
        uid,
        kind,
        schedule,
        check_mode,
        instruction,
        next_run_at=next_run,
        created_by_task=_optional_uuid(tid),
    )

    script_path: str | None = None
    if kind == "watcher":
        try:
            path = skills.write_check_script(str(uid), str(job.id), check_script or "")
        except skills.SkillError as exc:
            await db.delete_job(uid, job.id)  # leave no half-created job
            return ToolResult(ok=False, error=str(exc))
        script_path = str(path)
        await db.update_job(uid, job.id, check_script_path=script_path)

    await events.publish(
        events.JOB_CHANGED,
        {"user_id": str(uid), "job_id": str(job.id), "change": "created"},
    )
    logger.info(
        "job created",
        extra={"user_id": str(uid), "task_id": tid, "job_id": str(job.id), "kind": kind},
    )
    return ToolResult(
        ok=True,
        data={
            "job_id": str(job.id),
            "kind": kind,
            "schedule": schedule,
            "next_run_at": next_run.isoformat() if next_run else None,
            "check_script_path": script_path,
        },
    )


@tool(
    "list_jobs",
    "List this user's scheduled jobs (id, kind, schedule, next run, active, last status).",
    risk="safe",
)
async def list_jobs() -> list[dict]:
    """Only the acting user's jobs — other users' are unreachable."""
    uid, tid = _context_ids()
    out = []
    for job in await db.list_jobs(uid):
        state = job.state_json or {}
        out.append(
            {
                "job_id": str(job.id),
                "kind": job.kind,
                "schedule": job.schedule,
                "check_mode": job.check_mode,
                "instruction": job.instruction[:120],
                "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
                "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
                "active": job.active,
                "last_status": state.get("last_status"),
                "consecutive_failures": int(state.get("consecutive_failures", 0)),
            }
        )
    return out


@tool(
    "pause_job",
    "Pause one of this user's jobs by id (it stops firing until resumed).",
    risk="moderate",
)
async def pause_job(job_id: str) -> ToolResult:
    """Ownership first: someone else's id reads as 'job not found'."""
    uid, tid = _context_ids()
    job = await _own_job(uid, job_id)
    if job is None:
        return ToolResult(ok=False, error="job not found")
    await db.update_job(uid, job.id, active=False)
    await events.publish(
        events.JOB_CHANGED, {"user_id": str(uid), "job_id": str(job.id), "change": "paused"}
    )
    logger.info("job paused", extra={"user_id": str(uid), "task_id": tid, "job_id": str(job.id)})
    return ToolResult(ok=True, data={"job_id": str(job.id), "active": False})


@tool(
    "delete_job",
    "Delete one of this user's job by id (removes its check script too).",
    risk="moderate",
)
async def delete_job(job_id: str) -> ToolResult:
    """Ownership first: someone else's id reads as 'job not found'."""
    uid, tid = _context_ids()
    job = await _own_job(uid, job_id)
    if job is None:
        return ToolResult(ok=False, error="job not found")
    if job.check_script_path:
        # Only ever unlink inside this user's own prefix (path is re-validated).
        job_id_str = str(job.id)
        skills.delete_check_script(str(uid), job_id_str)
    deleted = await db.delete_job(uid, job.id)
    if not deleted:
        return ToolResult(ok=False, error="job not found")
    await events.publish(
        events.JOB_CHANGED, {"user_id": str(uid), "job_id": str(job.id), "change": "deleted"}
    )
    logger.info("job deleted", extra={"user_id": str(uid), "task_id": tid, "job_id": str(job.id)})
    return ToolResult(ok=True, data={"deleted": str(job.id)})


async def _own_job(uid: UUID, job_id: str) -> db.Job | None:
    """Resolve a job the acting user owns; anything else (bad id, someone
    else's job) is None — identical to 'not found'."""
    jid = _optional_uuid(job_id)
    if jid is None:
        return None
    return await db.get_job(uid, jid)


def _optional_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None
