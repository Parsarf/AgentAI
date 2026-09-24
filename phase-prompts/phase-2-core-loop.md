# BUILD PROMPT — Phase 2: Core loop MVP (first usable multi-user agent)

> Paste this entire file into a fresh AI coding session, opened in the repo root.

You are a senior engineer building **Phase 2 of 7** of the project below — the phase where this becomes a real product: a signed-up user chats with their own agent over Telegram and/or the web dashboard, and it researches the web, writes and runs code in a sandbox, and remembers things — all scoped to them alone. Work autonomously; ask only if truly blocked. Where the spec leaves a choice open, pick the simplest option satisfying every stated rule, implement it, record it in `BUILD_NOTES.md`.

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

STACK: Python 3.11+, asyncio throughout, Claude Agent SDK as the agent loop
(check current SDK docs for exact API names), Anthropic API, Postgres (not
SQLite — a real multi-tenant service needs concurrent writers and row-level
isolation) via asyncpg or SQLAlchemy async, FastAPI for the dashboard/API,
Playwright, Docker, python-telegram-bot, pydantic v2, Stripe SDK.

MULTI-TENANCY MODEL — the one idea that shapes everything else:
Every piece of state belongs to exactly one user_id. Every database query,
every sandbox container, every vault entry, every memory, every scheduled
job is scoped to a user_id and it is a bug — not a config choice — for any
code path to return or act on another user's data. This is enforced at the
data-access layer (core.db never exposes a query without a user_id
parameter), not left to callers to remember. Treat "the wrong user saw
another user's task result" with the same severity as a payment bug.

CORE SAFETY MODEL — layered on top of tenancy, per user:
  - INTERACTIVE (user present): tools fairly free, subject to that user's
    approval tiers.
  - AUTONOMOUS (source="job", no human present): narrower default tool set,
    lower step cap, and anything above "safe" risk requires approval
    regardless of what the task seems to justify — no self-granted
    exceptions. Apply the stricter rule when in doubt.

TWO KINDS OF MONEY — never conflate these:
  - PLATFORM BILLING (Phase 5): what the operator charges users for the
    service. Phase 2's job is only to METER accurately per user (api_costs,
    usage_periods) and to enforce each user's plan hard cap.
  - AGENT-DIRECTED SPENDING (Phase 6): not built here; never design
    anything that makes it harder later.

CONVENTIONS:
- Fully async. Type hints everywhere. Pydantic models for structured data.
- Config only via core.config.settings; never hard-coded values.
- Logging only via core.logging.get_logger(__name__); never log secrets;
  every log line carries task_id and user_id.
- Database access only via functions in core.db; every function takes
  user_id as its first argument.
- Tools registered with the @tool decorator from tools.base. Every tool
  returns ToolResult(ok, data, error). Tools never raise to the agent.
  Every tool call carries the acting user_id through to any resource it
  touches. Every tool declares a risk level: safe|moderate|high.
- Secrets never enter the model's context.
- All external content (web pages, emails, files) returned to the model is
  wrapped in <untrusted_content source="..."> tags.
- Components communicate through core.events instead of importing each
  other directly.
```

## 2. Read before writing any code

1. `agent-build-spec-multiuser.md` — Part 0a, the **Phase 2** section in full, and the folder tree. Spec wins over this prompt on conflict; report conflicts.
2. `BUILD_NOTES.md` — decisions from Phase 1 (DB driver choice, embedding model, etc.).
3. The existing Phase 1 code — `core/config.py`, `core/logging.py`, `core/db.py`, `core/events.py`, `core/auth.py`, `db/migrations/`. The code is ground truth for what exists.
4. **Current Claude Agent SDK docs** (via WebSearch/fetch) for the exact tool-registration and loop APIs — the spec demands this. Do not guess SDK names.

## 3. Process rules — follow exactly

1. Build **only** Phase 2. No scheduler/skills (Phase 3), no browser/vault (4), no Stripe (5), no payments (6).
2. Build in §5's order — `tools/base.py` first, everything hangs off it. Each file's acceptance check passes before the next file starts.
3. Test as you go (pytest + pytest-asyncio). Unit tests mock Anthropic/Telegram/Docker where possible; a small number of integration tests run against real Docker and are skipped automatically when Docker isn't available (`pytest.importorskip`/skip markers).
4. Money = Decimal. Never log secrets. `user_id` is **never** a parameter the model can supply — it comes from task context only.
5. If `ANTHROPIC_API_KEY` / `SEARCH_API_KEY` / `TELEGRAM_BOT_TOKEN` are missing from `.env`, tell the operator which key and stop that portion — mocked unit tests may still run.
6. End-of-session report: files, test results, unfinished items, open questions → stdout + `BUILD_NOTES.md`.

## 4. Prerequisites

Operator items #6–7 on top of Phase 1: Docker Engine reachable from this machine (`docker info` works), and `SEARCH_API_KEY` (Brave/SerpAPI/Google PSE — pick per what's in `.env`, adapter pattern). Also `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `BASE_URL` set.

## 5. Work order and file specs

### 5.1 `tools/base.py` — the plug-in system (build first)

- `ToolResult(ok: bool, data: Any = None, error: str | None = None)` — pydantic model, the only thing tools ever return.
- `@tool(name, description=None, risk="safe")` decorator: description falls back to docstring; JSON schema auto-generated from **type hints** (reject untyped params with a clear error); registered into a global `registry`.
- `registry`: `get(name)`, `all()`, `export_for_sdk(user, task_source)` (maps to the Claude Agent SDK's tool format — follow current docs), `auto_discover()` (imports every `tools/*.py` and collects decorated tools).
- The wrapper every tool call passes through, in this order:
  1. Resolve acting `user_id` + `task_id` from the orchestrator-set contextvars. If absent → refuse (`ok=False`). Defense in depth: no context, no execution.
  2. **Reject a model-supplied `user_id` argument explicitly** if the model tries to pass one — log a warning, strip it, and note it in the result data. A tool implementation never accepts user_id from the model.
  3. Log `tool.call.start` (name, user_id, task_id, risk).
  4. If `risk != "safe"`: `core.approvals.check(user_id, ...)` → `auto`/`auto_and_log` proceed (log the decision), `require_approval` awaits the user's decision, `deny` returns `ok=False, error="denied by your approval settings"` — never a raw exception.
  5. Execute in try/except: any exception → `ToolResult(ok=False, error="<clear, actionable message>")`. Tools never raise to the agent.
  6. Truncate oversized outputs (settings threshold) with a `"[truncated]"` note.
  7. If the tool flagged its output as external content, wrap in `<untrusted_content source="...">...</untrusted_content>`.
  8. Log duration + ok/err.
- Contextvars `current_user_id`, `current_task_id`, `current_task_source` live here (or in a tiny `tools/context.py`) and are set **only** by the orchestrator.
- **Accept:** dummy tool registers, appears in exported schema with correct JSON schema; a raising tool returns a clean `ok=False`; a `moderate` tool without approval context refuses to run; log lines carry user_id/task_id.

### 5.2 `core/router.py` — model calls, metered per user

```python
async def call(user_id, task_id, role: Literal["planner","worker","cheap"],
               messages, **kwargs) -> ModelReply   # (text, usage, model)
```
- Maps roles → model ids from settings; counts tokens from the API response; computes cost from `settings.model_prices` with Decimal; writes via `core.db.log_api_cost(user_id, task_id, model, in, out, cost)`; publishes `usage.updated {user_id}`.
- **Cap enforcement (Phase 5 formalizes billing; you enforce the plan floor):** before calling, if `cost_today + projected > plan.hard_cap_usd` or period usage exceeds cap → raise `UsageCapExceeded` (orchestrator converts to a clear user-facing message: "usage cap reached — see /usage"). Projected = rough estimate from message char count; keep it simple.
- Retries: 2× on transient API errors with backoff; no retry on cap rejection.

### 5.3 `core/context.py` — per-user context assembly

`build_context(user_id, task_id, step_history) -> (system_text, messages)`:
- System prompt from `core/prompts/system.md` + current date/time in the user's timezone + top-N relevant memories for **this user** (embed the task request with the settings-configured local model, `search_memories`).
- Recent history for this task only; when long, summarize older turns via `router.call(role="cheap")` and store the summary on the task row so it's reused, not recomputed.
- Enforce `context_token_budget` with headroom for tool schemas; drop/summarize least-relevant first. Everything pulled is user-scoped by construction — assert it.

### 5.4 `core/approvals.py` — the per-user gate

- Effective rules = compile(`limits.yaml` defaults + user overrides). **Add migration `0002_user_overrides.sql`:** `ALTER TABLE users ADD COLUMN user_limits_json jsonb;` (user's own rule overrides) and widen the `users.status` check to include `'email_unverified'` if Phase 1 didn't.
- Plan-tier floor: users may tighten freely; they may loosen **only within what their plan allows** — free tier can never enable payments/browser/autonomy regardless of its rules (enforce here, not in the UI).
- `check(user_id, tool_call, risk, task) -> Decision(action, approval_id | None)`:
  - Mode floor: `task.source == "job"` ⇒ anything above `safe` is at least `require_approval`, regardless of rules.
  - First matching rule wins; `auto_and_log` writes a decision log row/line.
  - `require_approval`: insert `approvals` row, publish `approval.requested {user_id, approval_id, action_summary, details}`, then `events.wait_for("approval.decided", predicate=approval_id & user_id, timeout=settings.approval_timeout_seconds)`. Timeout ⇒ `update_approval(..., "expired")` ⇒ **deny**.
- `decide(user_id, approval_id, approved)`: resolves only the owning user's pending approval — a decision referencing another user's approval_id is rejected (log it; this is a trap-test target). Publishes `approval.decided {user_id, approval_id, approved}`.
- **Accept (spec's own test):** the same tool call is `auto` under user A's looser rules and `require_approval` under B's stricter defaults; B cannot decide A's approval; timeout denies.

### 5.5 `tools/web.py` — research tools

- `web_search(query, num_results=5)` — risk `safe`. Provider adapter (Brave/SerpAPI/Google PSE from settings). Log the per-query cost against the user (`log_api_cost(..., model="search", cost=...)`).
- `fetch_page(url, focus=None)` — risk `safe`. httpx (timeout, 2 MB response cap, content-type allowlist), trafilatura extraction, 1-hour cache that is **deliberately shared across users** (page content isn't tenant-specific — a module-level TTL dict is fine; document the exception). If `focus` is set, route focused extraction through `router.call(role="cheap")`. Output flagged as external content.
- `http_request(method, url, headers=None, body=None)` — risk `moderate`. **SSRF guard:** resolve the host and refuse private/loopback/link-local ranges (127/8, 10/8, 172.16/12, 192.168/16, 169.254/16, ::1, fc00::/7, cloud-metadata 169.254.169.254) and the service's own internal hosts. Size/time caps. Response body truncated hard.
- **Accept:** search+fetch return clean results wrapped as untrusted content; per-call cost lands in the **calling user's** `api_costs`.

### 5.6 `sandbox/Dockerfile` + `tools/sandbox.py` — per-user code execution

- Dockerfile: `python:3.11-slim`, non-root user, `/workspace` workdir, minimal useful packages (git, curl, build-essential; pip layer with common data libs), **no secrets baked in**.
- Tenancy specifics (spec-mandated, test-covered):
  - One **long-lived container per task**, created on demand, named `sbx_<task_id>`, docker labels `user_id`, `task_id`.
  - Each user gets a per-user Docker network (`agent_net_<user_id>`); containers join only their owner's network — no route to other users' containers or host-internal services.
  - Workspace volumes under `/data/sandboxes/<user_id>/<task_id>/`. Path construction goes through a validator that enforces `^[A-Za-z0-9_-]+$` on both ids and refuses any normalized path escaping the user's prefix (also verify `realpath` containment post-creation — symlink defense).
  - Containers: CPU/memory/pids/time limits from settings (tighter for `source="job"`), **no env vars, no secrets, no host paths** beyond their own workspace; network access allowed.
  - Destroy container on task end (`task.finished` subscriber); workspaces kept for `workspace_retention_hours`, purged by a small periodic asyncio sweep in `main.py` (Phase 3's scheduler will absorb this).
- Tools (all scoped to the acting user's workspace): `run_code(language, code)` risk `safe`; `install_package(name)` risk `moderate`; `read_file(path)` / `write_file(path, content)` risk `safe`. Output: stdout/stderr/exit code, truncated; timeouts enforced via exec timeout + container clock caps.
- **Accept (spec's own test):** the agent fetches+parses a page inside its sandbox; a task run as user A cannot read/write/reach anything under user B's workspace path or container network — verified by test (path-validator unit tests + a real two-container integration test asserting cross-curl fails).

### 5.7 `tools/memory.py` — per-user long-term memory

- Local embeddings per settings (`sentence-transformers` `all-MiniLM-L6-v2` unless BUILD_NOTES says otherwise); pgvector storage via `core.db`.
- Tools: `remember(content, category="general", importance=0.5)` risk `safe`; `recall(query, limit=10)` risk `safe` (updates `last_used_at`); `forget(memory_id)` risk `moderate` (ownership-checked — `forget` on another user's id must simply fail).
- Importance decay applied at recall time (`importance * exp(-days_since_use / tau)`), feeding ranking. The orchestrator pulls top-N memories into context automatically each task.

### 5.8 `tools/notify.py`

`notify_user(message, urgent=False)` risk `safe` — publishes `notify.user {user_id, message, urgent}` for the calling task's own user only. Gateways deliver it, respecting that user's quiet-hours unless `urgent`. **Accept:** a notification for A reaches only A's channels (test with two fake gateway subscribers).

### 5.9 `core/orchestrator.py` — the agent loop

- Subscribes to `task.requested {user_id, request, source, parent_job_id?}`; `run_task(user_id, task_id)` is the callable core.
- Flow: create task row → acquire per-user concurrency slot (semaphore sized by `plan.concurrent_tasks`, plus a global cap) → set contextvars (`user_id`, `task_id`, `source`) → `context.build_context` → run the Agent SDK loop with tools from `registry.export_for_sdk(user, source)` → every model call through `router.call` (cap-checked) → every non-safe tool through approvals (inside the base wrapper) → enforce step cap (`max_steps_interactive` vs `max_steps_job`) and task timeout → publish `task.progress` per step → finalize: update row (`status`, `result`, `cost_usd`), publish `task.finished {user_id, task_id, status, summary}`.
- `UsageCapExceeded` → task `status='failed'`, clear user-facing message. Unexpected errors → `failed` + polite notify to the user. Container cleanup subscribed to `task.finished`.
- **Concurrent users:** multiple users' tasks run simultaneously, each fully isolated by contextvars, own container, own rows — no shared mutable state (the registry is read-only). **Accept:** two users run tasks at once; neither's task, cost, or tool output leaks into the other's (asserted in the e2e test).

### 5.10 `core/prompts/system.md`

Covers: role and capabilities; current tool inventory note (orchestrator injects the list); preference for saving reusable patterns as future skills; never routing around approvals; stating uncertainty on risky actions; and explicitly: *it acts for exactly one user at a time and has no visibility into any other user's data — not because it's told to hide it, but because none of its tools can reach it.* Must accurately describe the system as built in this phase — update it if your build differs.

### 5.11 `gateway/account_linking.py`

`generate_link_code(user_id)` → 8-char code, stores SHA-256 hash + 10-min expiry, single-use. `redeem_link_code(code, chat_id)` → validates unused+unexpired, writes `telegram_links` (unique chat_id; re-linking a chat moves it to the new user), returns user_id. Migration `0003` if you need a link-codes table (or keep codes in-memory + documented — pick one, record it). **Accept:** code redeemed once; expired code rejected; guessing is useless (hashed).

### 5.12 `gateway/telegram_bot.py`

python-telegram-bot v21+ async. `/start` or any message from an unlinked chat → friendly linking instructions (point to the web app's code generator) — never a bare rejection. Linked message → `task.requested {user_id, request, source:"user"}` + immediate "working on it…" ack. Subscribes to `notify.user`, `task.progress` (optional throttled updates), `task.finished`, `approval.requested` — delivering **only** to chats linked to that user_id. Approval messages carry inline Approve/Deny buttons wired to `core.approvals.decide`. Chunk >4096-char outputs. **Accept (spec's own test):** two linked users each receive only their own results and approval prompts (integration test with mocked Telegram API calls).

### 5.13 `gateway/web_app.py` — FastAPI dashboard

- Session auth via `core.auth` + `SESSION_SECRET`: HttpOnly/Secure/SameSite=Lax cookie; `current_user` dependency; CSRF token on forms; security headers; rate-limited auth routes.
- Routes: signup/login/logout/verify/reset; `POST /tasks` (chat message → `task.requested`, same as Telegram), `GET /tasks` (list, per user), `GET /tasks/{id}`, `GET /tasks/{id}/events` (SSE fed by subscribing to the event bus filtered to this user+task); approvals inbox (`GET /approvals`, `POST /approvals/{id}/decide`); `GET/POST /settings` (quiet hours, per-user approval-rule overrides — validated server-side against plan bounds; Telegram link-code generator); `GET /usage` (placeholder page; Phase 5 fills it).
- Keep server-rendered Jinja2 + a little vanilla JS/SSE. No frontend framework.
- **Accept (spec's own test):** a full signup → verify → first-task flow works entirely in the browser, no Telegram required.

### 5.14 `main.py`

Startup order: load settings (fail loud) → `init_db()` → `auto_discover()` → subscribe orchestrator to `task.requested` → start Telegram polling (async task) → start uvicorn (in-process) → start sandbox workspace purge sweep → run until `system.stop` or SIGINT/SIGTERM; graceful shutdown: stop gateways, cancel tasks, close pool.

## 6. Tests to write

- `test_tools_base.py` — schema gen; error capture; truncation; untrusted-content wrapping; model-supplied `user_id` rejected; no-context refusal.
- `test_approvals.py` — the A-vs-B matrix from §5.4; wrong-user decide rejected; timeout ⇒ deny; job-source floor overrides looser rules.
- `test_web.py` — mocked search provider; fetch cache; **SSRF guard table test** over the blocked ranges.
- `test_sandbox_tenancy.py` — path-validator unit tests (evil task_ids: `../../u2`, absolute paths, symlink escape) + integration (two users, cross-access fails; skipped without Docker).
- `test_memory_tenancy.py` — identical `recall` query for A and B returns only each one's own rows.
- `test_router_costs.py` — cost logged to right user; capped user gets `UsageCapExceeded`, not a silent call.
- `test_e2e_two_users.py` — the spec's headline: two accounts each run a task doing web search + `run_code` + `remember`; assert zero cross-visibility of tasks, costs, memories, notifications (mocked Anthropic + real event bus + real test DB).
- Telegram flow covered by an integration test with python-telegram-bot's API mocked; document the 2-minute manual Telegram check in `BUILD_NOTES.md`.

## 7. Out of scope

Scheduler/jobs/skills (P3), browser/vault (P4), Stripe/billing views (P5), payments (P6), docker-compose deploy (P7). No MCP integrations yet beyond the disabled config.

## 8. Phase done when

- [ ] Two independently-created test accounts each: sign up, link Telegram (or use web chat), run a task that searches the web, runs code in their own sandbox, and stores a memory.
- [ ] Neither account can observe anything about the other's usage, tasks, cost, or memory — proven by tests, including concurrent execution.
- [ ] Approvals: same call auto-approves for one user, requires approval for another; decisions and timeouts behave; job-source floor enforced.
- [ ] Every non-safe tool call passes the gate; tools never raise; `user_id` can't be injected by the model.
- [ ] Plan hard cap blocks new model calls with a clear message.
- [ ] `python main.py` brings the service up from a clean checkout + filled `.env`.
- [ ] Full pytest suite green (integration tests skipped cleanly without Docker).
- [ ] `BUILD_NOTES.md` updated.

This is a legitimate stopping point: a real, if limited, multi-user product.
