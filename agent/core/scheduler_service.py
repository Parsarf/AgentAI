"""THE one system-level (cross-tenant) service in the codebase.

Its whole job is spanning users to find what's due; it never *returns* one
user's data to another — it only launches per-user tasks. Everything else in
the system is tenant-scoped by construction; this module is the documented
exception, mirroring ``core.db.due_jobs`` (the one cross-tenant query, which
only this service may call).

Per tick:
1. ``due_jobs(now)`` claims due jobs under the advisory lock (SKIP LOCKED).
2. For each claimed job, ``next_run_at`` is advanced ATOMICALLY (CAS on the
   claimed value, computed from cron in the USER'S OWN TIMEZONE) before any
   execution — a crash between claim and run can therefore never double-fire
   a job, and a job whose service was down for many occurrences (startup
   catch-up) fires exactly ONCE: the advance skips straight past all missed
   runs to the next future slot.
3. Each job is then handled in its OWN asyncio task with a timeout, so one
   user's pathologically failing job can never block another user's firing.

Watcher jobs (kind="watcher", check_mode="on_change") run their check script
inside the OWNING user's sandbox container first (reusing tools/sandbox.py at
the service level — no model involved). The output is hashed and compared to
``state_json.last_hash``; only a change (or check_mode="always") escalates to
a full task, with the check output passed into the task context. A quiet
check just logs ``watcher.quiet`` — this is what keeps idle polling from
burning users' usage. A check script that cannot run counts as a FAILED run,
never a silent skip.

Failure policy: ``consecutive_failures`` lives in ``state_json``. After
``scheduler.max_consecutive_failures`` consecutive failed runs the job is
auto-paused (active=false) and ``notify.user`` is published — to its OWNER
ONLY. Job outcomes come from two places: the watcher check itself, and
``task.finished`` events for fired tasks (matched via parent_job_id).

Engine choice (recorded in BUILD_NOTES): a plain asyncio loop, not
apscheduler's scheduler object — due_jobs already owns claim semantics, so
apscheduler would only supply a timer. Cron parsing/next-run math still uses
apscheduler's CronTrigger. ``next_cron_run`` is a pure helper and is safe to
import from tools/scheduler.py; the running service object is never imported
by tools (they talk to it via the job.changed event).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger

from core import db, events, skills
from core.config import settings
from core.logging import get_logger
from tools import sandbox

logger = get_logger(__name__)

_SWEEP_EVERY_SECONDS = 3600.0
_CHECK_TIMEOUT_SECONDS = 120.0


class CheckScriptError(Exception):
    """A watcher's check script could not run — a FAILED run, not a skip."""


# --------------------------------------------------------------------------- #
# Pure cron helpers (import-safe; no service state)
# --------------------------------------------------------------------------- #


def user_timezone(timezone_name: str | None) -> ZoneInfo:
    """Resolve a user's timezone, falling back to the operator default."""
    for name in (timezone_name, settings.timezone_default):
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


def next_cron_run(schedule: str, timezone_name: str | None, after: datetime) -> datetime | None:
    """Next fire of a 5-field cron string, evaluated in the user's timezone.

    Returns an aware UTC datetime (or None if the schedule never fires again).
    Raises ValueError if the cron string does not parse.
    """
    tz = user_timezone(timezone_name)
    trigger = CronTrigger.from_crontab(schedule, timezone=tz)
    after_tz = after.astimezone(tz)
    nxt = trigger.get_next_fire_time(None, after_tz)
    return nxt.astimezone(UTC) if nxt is not None else None


# --------------------------------------------------------------------------- #
# The service
# --------------------------------------------------------------------------- #


class SchedulerService:
    """Wakes every tick to fire every user's due jobs. See module docstring."""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._tick_lock = asyncio.Lock()  # one tick at a time in-process
        self._loop_task: asyncio.Task | None = None
        self._inflight: set[asyncio.Task] = set()
        self._last_sweep = 0.0
        self._last_billing_rollup = 0.0

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Start the loop; wire job.changed (wake) and task.finished (job
        outcome accounting) on the event bus."""
        from core import events as ev

        self._stop.clear()
        ev._subscribers.setdefault(ev.JOB_CHANGED, []).append(self._on_job_changed)
        ev._subscribers.setdefault(ev.TASK_FINISHED, []).append(self._on_task_finished)
        self._loop_task = asyncio.get_running_loop().create_task(self._run())
        logger.info("scheduler service started", extra={"tick_seconds": settings.scheduler.tick_seconds})

    async def stop(self) -> None:
        from core import events as ev

        await ev.unsubscribe(ev.JOB_CHANGED, self._on_job_changed)
        await ev.unsubscribe(ev.TASK_FINISHED, self._on_task_finished)
        self._stop.set()
        self._wake.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._loop_task
            self._loop_task = None
        for task in list(self._inflight):
            task.cancel()
        if self._inflight:
            await asyncio.gather(*list(self._inflight), return_exceptions=True)
        logger.info("scheduler service stopped")

    async def _run(self) -> None:
        # Startup catch-up: any job whose next_run_at is in the past (the
        # service was down) is due right now and fires ONCE — _claim advances
        # past every missed occurrence — then normal cadence resumes.
        with contextlib.suppress(Exception):
            await self.tick()
        while not self._stop.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._wake.wait(), timeout=settings.scheduler.tick_seconds
                )
            self._wake.clear()
            if self._stop.is_set():
                return
            with contextlib.suppress(Exception):
                await self.tick()
            if time.monotonic() - self._last_billing_rollup >= 3600:
                self._last_billing_rollup = time.monotonic()
                try:
                    from core import billing

                    await billing.rollup_active_users()
                except Exception:
                    logger.exception("billing rollup failed")
            # Phase 2's sandbox workspace purge sweep lives here now — one
            # periodic home for all background maintenance (Phase 4 added
            # stale browser profile cleanup to it).
            if time.monotonic() - self._last_sweep >= _SWEEP_EVERY_SECONDS:
                self._last_sweep = time.monotonic()
                with contextlib.suppress(Exception):
                    removed = await sandbox.purge_expired_workspaces()
                    if removed:
                        logger.info("workspaces purged", extra={"removed": removed})
                with contextlib.suppress(Exception):
                    from tools.browser import purge_stale_profiles

                    await purge_stale_profiles()

    async def _on_job_changed(self, payload: dict) -> None:
        """A user's tool created/paused/deleted a job — refresh promptly."""
        self._wake.set()

    # ---- the tick --------------------------------------------------------

    async def tick(self, now: datetime | None = None) -> list[db.Job]:
        """One scheduler pass: claim due jobs, advance them, spawn handlers.

        Ticks are serialized in-process (asyncio lock) so a wake-driven or
        externally driven tick can never interleave with the loop's own and
        lose the due_jobs advisory lock. Cross-PROCESS double-claims are
        still prevented by due_jobs itself (try-lock + SKIP LOCKED) and the
        CAS advance.
        """
        async with self._tick_lock:
            now = now or datetime.now(UTC)
            jobs = await db.due_jobs(now)
            for job in jobs:
                if not await self._claim(job, now):
                    continue
                handler = asyncio.create_task(self._run_isolated(job))
                self._inflight.add(handler)
                handler.add_done_callback(self._inflight.discard)
            if jobs:
                logger.info("scheduler tick", extra={"due": len(jobs), "at": now.isoformat()})
            # Bounded purchase reconciliation rides every tick (loop, wake and
            # external ticks included). Provider-less — the runtime case — it
            # resolves nothing and rows stay flagged, never aged away.
            with contextlib.suppress(Exception):
                from core import purchases as purchases_core

                await purchases_core.reconcile_pending(limit=5)
            return jobs

    async def drain(self) -> None:
        """Await all in-flight per-job handlers (tests, shutdown)."""
        while self._inflight:
            await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _claim(self, job: db.Job, now: datetime) -> bool:
        """Advance next_run_at (user's timezone) BEFORE executing. False if
        another tick won the race or the schedule is exhausted."""
        user = await db.get_user(job.user_id)
        tz_name = user.timezone if user is not None else None
        try:
            nxt = next_cron_run(job.schedule, tz_name, now)
        except ValueError:
            logger.exception(
                "job schedule unparsable at claim time",
                extra={"user_id": str(job.user_id), "job_id": str(job.id)},
            )
            nxt = None
        if nxt is None:
            await db.update_job(job.user_id, job.id, active=False)
            await self._notify_owner(
                job, f"job '{job.instruction[:60]}' was paused: its schedule has no future runs"
            )
            return False
        return await db.advance_job_fire(
            job.user_id, job.id, job.next_run_at, nxt, fired_at=now
        )

    # ---- per-job handling (isolated; never blocks other users' jobs) -----

    async def _run_isolated(self, job: db.Job) -> None:
        uid, jid = str(job.user_id), str(job.id)
        try:
            await asyncio.wait_for(
                self._handle_job(job), timeout=settings.limits.task_timeout_seconds
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            logger.error(
                "job handling timed out",
                extra={"user_id": uid, "job_id": jid},
            )
            await self._record_failure(job, "job handling timed out")
        except CheckScriptError as exc:
            logger.warning(
                "watcher check failed",
                extra={"user_id": uid, "job_id": jid, "error": str(exc)[:200]},
            )
            await self._record_failure(job, f"check script failed: {exc}")
        except Exception as exc:
            logger.exception("job handling crashed", extra={"user_id": uid, "job_id": jid})
            await self._record_failure(job, f"job error: {exc}")

    async def _handle_job(self, job: db.Job) -> None:
        if job.kind == "watcher" and job.check_mode == "on_change":
            changed, output = await self._run_watcher_check(job)
            await self._record_success(job)  # the check itself ran cleanly
            if not changed:
                # Idle poll: no task, no usage — the whole point of watchers.
                logger.info(
                    "watcher.quiet",
                    extra={"user_id": str(job.user_id), "job_id": str(job.id)},
                )
                return
            await self._fire(job, check_output=output)
            return
        await self._fire(job, check_output=None)

    async def _run_watcher_check(self, job: db.Job) -> tuple[bool, str]:
        """Run the job's check script inside the OWNER's own sandbox.

        Returns (changed, output). Raises CheckScriptError when the script is
        missing or fails — a failed check is a failed run, never a skip.
        """
        uid, jid = str(job.user_id), str(job.id)
        source = skills.read_check_script(uid, jid)  # SkillError if absent
        container_id = f"check-{jid}"
        await sandbox.start_task_sandbox(uid, container_id)
        try:
            code, out, err = await sandbox.run_files(
                container_id,
                {"check_script.py": source},
                entry="check_script.py",
                timeout=_CHECK_TIMEOUT_SECONDS,
            )
        finally:
            await sandbox.stop_task_sandbox(container_id)
        if code != 0:
            raise CheckScriptError(
                f"exit code {code}: {(err or out).strip()[:300]}"
            )
        output = out

        fresh = await db.get_job(job.user_id, job.id)
        state: dict[str, Any] = dict(fresh.state_json or {}) if fresh else {}
        digest = hashlib.sha256(output.encode()).hexdigest()
        changed = state.get("last_hash") != digest
        state["last_hash"] = digest
        if fresh is not None:
            await db.update_job(job.user_id, job.id, state_json=state)
        return changed, output

    async def _fire(self, job: db.Job, check_output: str | None) -> None:
        """Escalate to a full task: the orchestrator subscribes to job.fired
        and runs it source="job" for this user only."""
        await events.publish(
            events.JOB_FIRED,
            {
                "user_id": str(job.user_id),
                "job_id": str(job.id),
                "instruction": job.instruction,
                "kind": job.kind,
                "check_mode": job.check_mode,
                "check_script_path": job.check_script_path,
                "check_output": check_output,
            },
        )

    # ---- job outcome accounting ------------------------------------------

    async def _on_task_finished(self, payload: dict) -> None:
        """Fired tasks report back: done resets the failure streak; any other
        status counts as a failed run of the parent job."""
        parent = payload.get("parent_job_id")
        if not parent:
            return
        try:
            job = await db.get_job(UUID(str(payload["user_id"])), UUID(str(parent)))
        except ValueError:
            return
        if job is None:
            return
        if payload.get("status") == "done":
            await self._record_success(job)
        else:
            await self._record_failure(
                job, str(payload.get("summary") or payload.get("status") or "task failed")
            )

    async def _record_success(self, job: db.Job) -> None:
        fresh = await db.get_job(job.user_id, job.id)
        if fresh is None:
            return
        state = dict(fresh.state_json or {})
        state["consecutive_failures"] = 0
        state["last_status"] = "ok"
        await db.update_job(fresh.user_id, fresh.id, state_json=state)

    async def _record_failure(self, job: db.Job, reason: str) -> None:
        fresh = await db.get_job(job.user_id, job.id)
        if fresh is None or not fresh.active:
            return
        uid, jid = str(fresh.user_id), str(fresh.id)
        state = dict(fresh.state_json or {})
        fails = int(state.get("consecutive_failures", 0)) + 1
        state["consecutive_failures"] = fails
        state["last_status"] = "failed"
        state["last_error"] = reason[:300]

        fields: dict[str, Any] = {"state_json": state}
        paused = False
        if fails >= settings.scheduler.max_consecutive_failures:
            fields["active"] = False
            paused = True
        await db.update_job(fresh.user_id, fresh.id, **fields)
        logger.warning(
            "job run failed",
            extra={"user_id": uid, "job_id": jid, "consecutive_failures": fails},
        )
        if paused:
            # Owner only — a failing job is that user's private business.
            await self._notify_owner(
                fresh, f"job '{fresh.instruction[:60]}' auto-paused after repeated failures"
            )

    async def _notify_owner(self, job: db.Job, message: str) -> None:
        await events.publish(
            events.NOTIFY_USER,
            {"user_id": str(job.user_id), "job_id": str(job.id), "message": message, "urgent": False},
        )


#: The process-wide service (started/stopped from main.py).
service = SchedulerService()


def start() -> None:
    service.start()


async def stop() -> None:
    await service.stop()
