# BUILD PROMPT — Phase 3: Autonomy (per-user scheduling, watchers, skills)

> Paste this entire file into a fresh AI coding session, opened in the repo root.

You are a senior engineer building **Phase 3 of 7** of the project below — the phase where each user's agent starts acting **on its own** for them: scheduled jobs, change-watching watchers, and a personal library of reusable skills the agent writes for itself — with none of it crossing into another user's jobs or skills. Work autonomously; ask only if truly blocked. Where the spec leaves a choice open, pick the simplest option satisfying every stated rule, implement it, record it in `BUILD_NOTES.md`.

---

## 1. Shared project context (true for every phase)

```
PROJECT: A hosted, multi-user personal AI agent. Anyone can sign up for an
account. Each account has its own isolated conversation history, memory,
scheduled jobs, skills, connected logins, connected payment method (if
opted in), and usage/billing. Users message their agent via a linked
Telegram chat and/or a web dashboard; it plans and executes tasks using
general-purpose tools (code sandbox, web, browser, memory, scheduler),
writes and saves its own reusable per-user skills, runs scheduled jobs and
watchers proactively, and asks the user for approval before risky actions
(spending, messaging people, deleting).

STACK: Python 3.11+, asyncio throughout, Claude Agent SDK as the agent loop,
Anthropic API, Postgres via asyncpg or SQLAlchemy async, FastAPI dashboard,
Playwright, Docker, python-telegram-bot, pydantic v2, Stripe SDK.

MULTI-TENANCY MODEL — every piece of state belongs to exactly one user_id.
Every query, container, vault entry, memory, and scheduled job is scoped to
a user_id; it is a bug — not a config choice — for any code path to return
or act on another user's data. Enforced at the data-access layer. Treat "the
wrong user saw another user's task result" with the same severity as a
payment bug.

CORE SAFETY MODEL — AUTONOMOUS (task.source == "job"): narrower default
tool set, lower step cap, anything above "safe" risk requires approval
regardless of what the task seems to justify. No self-granted exceptions.
Apply the stricter rule when in doubt.

TWO KINDS OF MONEY: PLATFORM BILLING (Phase 5, not built yet — keep metering
accurate per user). AGENT-DIRECTED SPENDING (Phase 6, not built yet).
Jobs must NEVER be able to self-approve anything risky — that hard rule
arrives fully in Phase 6 but your design here must not undermine it.

CONVENTIONS: fully async; type hints everywhere; pydantic v2; config only
via core.config.settings; logging only via core.logging.get_logger
(__name__) with task_id + user_id on every line and no secrets ever;
DB only via core.db with user_id as first argument; tools via @tool from
tools.base returning ToolResult(ok, data, error), never raising to the
agent, risk level declared on every tool; secrets never in model context;
external content wrapped in <untrusted_content> tags; components talk via
core.events.
```

## 2. Read before writing any code

1. `agent-build-spec-multiuser.md` — the **Phase 3** section, Part 0a for context, folder tree. Spec wins on conflict; report conflicts.
2. `BUILD_NOTES.md` — all prior decisions.
3. Existing code, ground truth: `core/db.py` (`create_job/update_job/get_job/list_jobs/due_jobs` — note `due_jobs` is the **one deliberate cross-tenant function**, documented as such), `core/orchestrator.py` (how `task.requested` tasks run; `task.source` plumbing), `core/approvals.py` (job-mode floor), `tools/base.py` (contextvars, registry), `tools/sandbox.py` (per-user containers — you will reuse it), `core/scheduler_service.py` does **not** exist yet.

## 3. Process rules — follow exactly

1. Build **only** Phase 3: `tools/scheduler.py`, `core/scheduler_service.py`, `core/skills.py`, `tools/skills_tools.py`, plus migrations/tests/prompt updates they require. No browser, no vault, no Stripe, no payments.
2. Order: scheduler service → scheduler tools → skills core → skills tools → tests. Each acceptance check passes before moving on.
3. New tools must register via the existing `@tool` decorator and inherit **all** wrapper behavior (approvals, logging, truncation, error capture). Do not bypass the wrapper.
4. Migrations continue the numbering (`0004_...` etc.). Money = Decimal. Never log secrets.
5. Test as you go; mocks for Anthropic/Telegram; real test DB; Docker-dependent tests skip cleanly.
6. End-of-session report → stdout + `BUILD_NOTES.md`.

## 4. Prerequisites

Nothing new to sign up for. Docker + the Phase 2 stack must be runnable.

## 5. Work order and file specs

### 5.1 `core/scheduler_service.py` — fires every user's due jobs

The **one system-level (cross-tenant) service** in the codebase. State that in the module docstring, verbatim, with the reason: its whole job is spanning users to find what's due; it never *returns* one user's data to another — it only launches per-user tasks.

- apscheduler `AsyncIOScheduler` (or a plain asyncio loop — pick one, record it) ticking every ~30s (settings: `scheduler.tick_seconds`).
- Each tick: under a Postgres advisory lock (`pg_advisory_xact_lock` or the mechanism Phase 1 built into `due_jobs`) fetch `due_jobs(now)`; for each due job **atomically advance `next_run_at`** (compute from cron in the **user's timezone** — add `users.timezone` if missing via migration) **before** executing, so a crash between fetch and run can't double-fire; then publish `job.fired {user_id, job_id, instruction, kind, check_mode, check_script_path}`. The orchestrator treats these as tasks with `source="job"`, `parent_job_id` set.
- **Watcher jobs** (`kind="watcher"`, `check_mode="on_change"`): run the job's `check_script` **inside that user's own sandbox container** (reuse `tools/sandbox.py` machinery at the service level, not via the model). Hash the output; compare to `state_json.last_hash`. Only on change (or `check_mode="always"`) escalate to a full task — pass the check output into the task context. No change → log `watcher.quiet`, update `last_run_at`, done. This is what keeps idle polling from burning users' usage.
- `check_script` storage: save to `skills/<user_id>/_checks/<job_id>.py` at job creation (path validated with the same rules as sandbox workspace paths); scripts run in the user's sandbox with the same limits; a script that can't run counts as a failure, not a silent skip.
- **Failure policy:** track `consecutive_failures` in `state_json`. On ≥3 consecutive failed runs (settings: `scheduler.max_consecutive_failures`): set `active=false`, publish `notify.user {user_id, message="job '<x>' auto-paused after repeated failures", urgent=false}` — **to its owner only**. A user's failing job must never affect another user's job loop (isolate per-job execution in its own asyncio task with timeout).
- Startup catch-up: jobs whose `next_run_at` is in the past (service was down) fire **once** on startup, then resume normal cadence. Document the behavior in the docstring.
- Wire startup/shutdown into `main.py`; also absorb the Phase 2 sandbox-workspace purge sweep into this service (one periodic home).
- **Accept (spec's own test):** jobs belonging to different users fire independently and on schedule; one user's failing job never affects another's; catch-up fires once.

### 5.2 `tools/scheduler.py` — the user's agent manages its own jobs

Tools (all registered via `@tool`, wrapper-enforced):

- `create_job(kind: Literal["recurring","watcher"], schedule: str, instruction: str, check_mode: Literal["always","on_change"]="always", check_script: str | None=None)` — risk `moderate` (per the user's tiers it may require approval even from an interactive task). Validates: cron parses (apscheduler/croniter), instruction non-empty, watcher ⇒ `on_change` + script present, and the user is **under their plan's `max_active_jobs`** (active jobs counted). Writes the row scoped to the acting user; saves any check script under the user's own path; then tells the running service to pick it up (publish `job.changed {user_id, job_id}` — the scheduler service subscribes and refreshes; don't import it directly).
- `list_jobs()` — risk `safe`. Only the acting user's jobs (id, kind, schedule, next_run, active, last status).
- `pause_job(job_id)` / `delete_job(job_id)` — risk `moderate`. **Ownership check first**: resolve via `get_job(user_id, job_id)`; if None → `ToolResult(ok=False, error="job not found")` — same message whether the id belongs to someone else or doesn't exist (don't leak existence). Deleting also removes the check script path.

**Accept (spec's own test):** a job created by user A cannot be listed, paused, or deleted by user B even when B supplies A's real job id.

### 5.3 `core/skills.py` + `tools/skills_tools.py` — per-user skill library

Each skill is a folder **under the owning user's prefix**: `skills/<user_id>/<skill_name>/` containing:

- `skill.yaml`: `name` (slug), `description`, `args_schema` (JSON schema), `risk` (`safe|moderate` — skills may never declare `high`), `entrypoint` (`run.py` function name or `instructions.md` path).
- Either `run.py` (executable code) or `instructions.md` (a prompt-playbook the agent follows) — support both kinds.
- Layout rules identical to sandbox workspaces: id/name validated (`^[a-z0-9][a-z0-9_-]{0,63}$`), path confinement asserted, cross-user access structurally impossible.

`core/skills.py` responsibilities:

- `save_skill(user_id, name, description, args_schema, risk, files)`: validate schema compiles / playbook parses; write folder; upsert `skills_meta` row (scoped). Called by the tool below.
- `run_skill(user_id, skill_name, args)`: load meta → increment `uses` → execute **inside that user's own sandbox container** (code skills: run entrypoint with args; playbook skills: return the instructions for the orchestrator to follow inline) → record `successes`/`failures` from the outcome → failure-rate guard: if failures ≥3 and failure rate >50% → set `reviewed=false` and flag `needs_review` in meta (surface in `list_skills`; **flag, never delete**).
- `list_skills(user_id)`: own skills only, with stats.
- Note in the module docstring: a shared/opt-in skill marketplace is a deliberate non-goal of this phase — sharing, if ever built, would be an explicit user action, never automatic.

Tools:

- `save_skill(name, description, args_schema, risk, files: dict[path, content])` — risk `moderate`.
- `list_skills()` — risk `safe`.
- `run_skill(skill_name, args)` — risk = the skill's declared risk (the wrapper's approval gate reads it).

**Accept (spec's own test):** a skill saved by one user cannot be listed or run by another — including by guessing the name; `run_skill` executes in the runner's own sandbox (assert the executing user's container is the one used).

### 5.4 Prompt + UI touch-ups

- `core/prompts/system.md`: add a short section on creating/maintaining skills (prefer turning repeated successful patterns into skills; skills run only for their owner) and on jobs (watchers should be cheap checks that escalate only on change).
- `gateway/web_app.py`: extend the settings page with a Jobs list (pause/delete) and Skills list (name, stats, needs_review flag) — read-only views over the user's own data are enough this phase.
- `main.py`: start/stop the scheduler service.

## 6. Tests to write

- `test_scheduler_tenancy.py` — B cannot list/pause/delete A's job by id; A's and B's jobs fire independently (drive ticks manually with injected `now`); B's pathologically failing job never blocks A's firing; auto-pause after 3 failures notifies **only** the owner (fake `notify.user` subscriber).
- `test_watcher.py` — check script runs in the user's sandbox; unchanged hash ⇒ no task fired; changed hash ⇒ task fired with `source="job"` and check output in context (mocked Anthropic).
- `test_skills_tenancy.py` — cross-user list/run refused; stats increment; needs_review flag flips after repeated failures; skill code cannot escape its folder (path traversal names rejected).
- `test_job_timezone.py` — cron evaluated in the user's timezone (two users, different tz, same cron string, assert different next_run_at).
- E2E: two users each create a recurring job + a watcher; simulated clock advances a day; each gets exactly their own firings.

## 7. Out of scope

Browser/vault (P4), Stripe/billing (P5), payments (P6), any skill sharing/marketplace (explicit non-goal), OAuth/MCP integrations.

## 8. Phase done when

- [ ] Each test user can create a recurring job and a watcher; both fire correctly, only for their own account.
- [ ] A repeatedly failing job auto-pauses and notifies only its owner.
- [ ] Watchers run a cheap sandboxed check first and escalate only on change.
- [ ] A skill saved by one user is invisible to another (list, run, and even existence).
- [ ] All scheduler tools respect per-user approval tiers; job-sourced tasks still hit the stricter autonomous floor.
- [ ] Scheduler survives restart: catch-up fires each missed job exactly once; no double-fires under concurrent ticks (advisory lock test).
- [ ] Full pytest suite green; `BUILD_NOTES.md` updated.
