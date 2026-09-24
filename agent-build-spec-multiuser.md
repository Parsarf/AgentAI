# Personal AI Agent — Multi-User Service — Phased Build Spec

This is the same agent, redesigned as a **hosted, multi-user service**
instead of a single personal deployment. Anyone signs up, gets their own
account, and from that point everything is scoped to them: their own
conversation history and memory, their own scheduled jobs and skills, their
own connected logins and payment methods, their own usage meter, and — if
the service is paid — their own subscription. One deployment serves many
users; no user can see another's data, sandbox, or spend.

Two kinds of "money" show up in this spec and they are kept strictly
separate, because conflating them is exactly how a bug turns into a real
loss:

- **Platform billing** (Phase 5): what *you*, the operator, charge *users*
  for using the service. Metered off your one shared Anthropic/search
  usage.
- **Agent-directed spending** (Phase 6): the agent making a real-world
  purchase *for* a user, using *that user's own* connected card, only when
  that user has opted in.

7 phases, each ending in something usable. Setup work is split into two
tables in Part 0: things **you** do once as the operator, and things **each
user** does themselves after signing up (you don't do this part for them).

---

# Part 0: Setup

## 0a — Operator setup (you, once, to stand the service up)

| # | Service | Needed from | Why | What you do | Config / secret | Rough cost |
|---|---|---|---|---|---|---|
| 1 | **Anthropic API** | Phase 1 | One shared key powers every user's agent; usage is metered per user internally for billing | Create account, add payment method, generate API key, **set a hard spend limit in the console** as a backstop above your own per-user caps | `ANTHROPIC_API_KEY` | Usage-based, scales with total users |
| 2 | **Telegram bot** | Phase 1 | One bot serves everyone; each chat gets linked to a platform account | Message **@BotFather**, run `/newbot` | `TELEGRAM_BOT_TOKEN` | Free |
| 3 | **Domain + hosting** | Phase 1 | Users need a real web app to sign up, log in, see usage/billing, and approve actions from a browser, not just Telegram | Register a domain, provision a server or cloud host sized for concurrent users (not a spare laptop) | N/A | Domain ~$10–15/yr, hosting scales with load |
| 4 | **TLS / SSL** | Phase 1 | The signup/login flow handles passwords and payment data | Use your host's managed TLS or Let's Encrypt | N/A | Usually free |
| 5 | **Transactional email** | Phase 1 | Signup verification, password reset, security alerts | Sign up for a provider (Postmark, SES, Resend, etc.), verify your sending domain | `EMAIL_API_KEY` | Free tier, then per-email |
| 6 | **Docker host** | Phase 2 | Sandbox containers, now with per-tenant isolation | Install Docker Engine on the host from #3; plan for enough headroom to run many users' containers concurrently | N/A | Included in hosting cost |
| 7 | **Web search API** | Phase 2 | Shared, metered per user like the Anthropic key | Sign up for Brave Search API, SerpAPI, or Google Programmable Search | `SEARCH_API_KEY` | Free tier, then per-query, scales with users |
| 8 | **Secrets encryption / KMS** | Phase 4 | Encrypts each user's stored site logins at rest, with per-user key separation | Use a cloud KMS (AWS KMS, GCP KMS) or generate and securely store a root key yourself | `VAULT_MASTER_KEY` (or KMS key ARN) | Cloud KMS: a few dollars/mo |
| 9 | **Stripe account** (or similar) | Phase 5 | Bills users for using the service itself | Create a Stripe account, set up products/prices for your plan tiers, get API keys | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Free to set up, % + flat fee per transaction |
| 10 | **MCP OAuth app registrations** (optional) | Phase 4+ | If you want to offer Gmail/Calendar/etc. as connectable integrations, you (the operator) register the OAuth app once; each user then consents individually | Register an OAuth app with each provider you want to support | Listed in `config/mcp_servers.yaml` | Free |

## 0b — Per-user setup (each person does this themselves, in the app — not your job)

| # | What | When | Notes |
|---|---|---|---|
| 1 | Create an account (email/password or OAuth login) | Signing up | Free tier or paid plan depending on how you price it |
| 2 | Link their Telegram | Optional, anytime | Generates a short-lived linking code in the web app, sent to the bot to connect that chat to their account |
| 3 | Connect a password vault, or use the built-in one | Only if they want browser/login tools (Phase 4) | Built-in encrypted vault works with no extra signup; linking an external vault (e.g. their own Bitwarden) is optional |
| 4 | Connect a payment method for the agent to spend from | Only if they want it to ever buy things on their behalf (Phase 6) | Their own card via a supported provider — never yours, never shared across users |
| 5 | Connect optional integrations (Gmail, Calendar, etc.) | Anytime, if enabled | Standard OAuth consent screen for that provider |
| 6 | Pick a plan / enter billing details | If the service is paid | Handled by Stripe Checkout/Billing Portal, not built by hand |

---

# Shared context block (paste into every build session)

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
isolation) via asyncpg or SQLAlchemy async, a lightweight web framework
(FastAPI) for the dashboard/API, Playwright, Docker, python-telegram-bot,
pydantic v2, Stripe SDK.

MULTI-TENANCY MODEL — the one idea that shapes everything else:
Every piece of state belongs to exactly one user_id. Every database query,
every sandbox container, every vault entry, every memory, every scheduled
job is scoped to a user_id and it is a bug — not a config choice — for any
code path to return or act on another user's data. This is enforced at the
data-access layer (core.db never exposes a query without a user_id
parameter), not left to callers to remember. Treat "the wrong user saw
another user's task result" with the same severity as a payment bug.

CORE SAFETY MODEL — layered on top of tenancy, per user:
The agent operates in two modes with very different amounts of trust:
  - INTERACTIVE: the user messaged it directly and is present. Tools/
    resources fairly free, subject to that user's approval tiers.
  - AUTONOMOUS (that user's jobs/watchers firing on a schedule, no human
    present): a narrower default tool set, a lower per-task step cap, and
    anything above "safe" risk requires approval regardless of what the
    task seems to justify — no self-granted exceptions.
Every component that makes a resource/spend/risk decision must know both
which user it's acting for and which mode the current task is in
(task.source: "user" or "job"), and apply the stricter rule when in doubt.

TWO KINDS OF MONEY — never conflate these:
  - PLATFORM BILLING: what the operator charges the user for the service
    itself. Metered from shared operator-held API keys, rolled up per user,
    billed via Stripe. Lives in core/billing.py.
  - AGENT-DIRECTED SPENDING: the agent buying something in the real world
    on a specific user's behalf, using that user's own connected payment
    method, only after that user opted in and only within that user's own
    approval tiers. Lives in tools/payments.py. Never uses the operator's
    own card, ever.

CONVENTIONS:
- Fully async. Type hints everywhere. Pydantic models for structured data.
- Config only via core.config.settings, never hard-coded values or os.environ.
- Logging only via core.logging.get_logger(__name__). Never log secrets,
  and every log line carries both task_id and user_id for traceability.
- Database access only via functions in core.db, and every function takes
  a user_id (or an already-scoped session object) as its first argument.
- Tools are registered with the @tool decorator from tools.base. Every tool
  returns a ToolResult (ok: bool, data: any, error: str | None). Tools never
  raise to the agent; they catch errors and return ok=False with a clear,
  actionable error message. Every tool call carries the acting user_id
  through to any resource it touches (sandbox, vault, memory, payments).
- Every tool declares a risk level: "safe", "moderate", or "high".
- Secrets (passwords, card numbers, API keys, per-user vault contents)
  must NEVER enter the model's context. Tools that need secrets fetch them
  internally, scoped to the acting user, and use them directly.
- All external content (web pages, emails, files) returned to the model is
  wrapped in <untrusted_content source="..."> tags.
- Components communicate through core.events (a simple async event bus)
  instead of importing each other directly. Every event payload that
  concerns a specific user carries that user_id.
```

Full folder tree (built up across all 7 phases):
```
agent/
  main.py
  core/ config.py, logging.py, db.py, events.py, context.py, router.py,
        orchestrator.py, approvals.py, skills.py, scheduler_service.py,
        auth.py, billing.py, secrets_vault.py, prompts/system.md
  tools/ base.py, web.py, sandbox.py, browser.py, memory.py, notify.py,
         scheduler.py, credentials.py, payments.py, skills_tools.py
  gateway/ telegram_bot.py, web_app.py, account_linking.py
  skills/            (per-user, agent-written skill folders)
  config/ settings.yaml, limits.yaml, mcp_servers.yaml, plans.yaml
  db/ schema.sql, migrations/   (Postgres, not SQLite)
  sandbox/ Dockerfile
  tests/ test_tasks.yaml, trap_tests.yaml, run_evals.py
  scripts/ backup.sh
  Dockerfile, docker-compose.yml, requirements.txt, .env.example
```

---

# Phase 1 — Foundation & accounts

**Goal:** the multi-tenant substrate. No agent behavior yet, but by the end
of this phase a real person can sign up, log in, and the system already
refuses to let one user's request touch another user's data — because the
data layer makes that structurally impossible, not just discouraged.

**You need:** operator items #1–5.

**Files in this phase:**

### `requirements.txt` and `.env.example`
**Purpose:** Declare dependencies and every operator-level secret.
**Contents:** `requirements.txt` pins versions for: claude-agent-sdk, anthropic, fastapi, uvicorn, asyncpg (or sqlalchemy[asyncio]), pydantic, pydantic-settings, pyyaml, python-telegram-bot, playwright, httpx, trafilatura, apscheduler, docker, sqlite-vec or pgvector, python-dotenv, passlib (password hashing), pyjwt (sessions), stripe. `.env.example` lists, with a comment explaining each: `ANTHROPIC_API_KEY`, `SEARCH_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `EMAIL_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `VAULT_MASTER_KEY`, `SESSION_SECRET`, `BASE_URL`.
**Done when:** `pip install -r requirements.txt` succeeds in a clean environment.

### `config/settings.yaml`, `config/limits.yaml`, `config/plans.yaml`, `config/mcp_servers.yaml`
**Purpose:** Every tunable behavior lives here.
**settings.yaml:** model names per role, max steps per task for interactive vs job/watcher tasks, sandbox resource limits, timezone default, quiet hours default, browser headless on/off.
**limits.yaml:** the *default* approval-tier rules new users get (users can loosen/tighten their own within what their plan tier allows) — match conditions (tool name, risk level, amount threshold, merchant allowlist, task source: user vs job) mapped to an action (`auto`, `auto_and_log`, `require_approval`, `deny`).
**plans.yaml:** the plan tiers (e.g. `free`, `pro`) — monthly included usage, hard cost cap per user, concurrent task limit, whether autonomous jobs/browser/payments tools are enabled at that tier, Stripe price ID for each paid tier.
**mcp_servers.yaml:** available integrations (Gmail, Calendar, etc.), each with OAuth app config and enabled flag.
**Done when:** the files load as valid YAML and every value is commented.

### `core/config.py`
**Purpose:** The single source of truth for configuration.
**How it works:** Uses pydantic-settings to load `.env`, then merges the YAML files into typed pydantic models. Exposes one global `settings` object. Validates on startup so a typo fails loudly. Includes `reload()`.
**Interface:** `settings` (`.models`, `.limits`, `.plans`, `.mcp_servers`, `.secrets`, etc.), `reload()`.
**Done when:** a test script prints the loaded settings with secrets masked.

### `core/logging.py`
**Purpose:** Structured, per-tenant-traceable logs.
**How it works:** JSON-formatted log lines with timestamp, level, module, and both `task_id` and `user_id` auto-attached via context variables. A redaction filter scans every message for known secret values/patterns (including per-user vault contents pulled at request time) and replaces them with `[REDACTED]`. Logs to stdout and a rotating file.
**Interface:** `get_logger(name)`, `set_task_context(task_id, user_id)`.
**Done when:** logging a string containing a real secret value outputs `[REDACTED]`, and every log line from a test task carries the right user_id.

### `db/schema.sql` and `core/db.py`
**Purpose:** All persistent state, tenant-scoped from the ground up.
**Tables:** `users` (id, email, password_hash or oauth_subject, created_at, plan_tier, stripe_customer_id, status), `sessions` (id, user_id, token_hash, expires_at), `telegram_links` (telegram_chat_id, user_id, linked_at), `tasks` (id, **user_id**, request, status, source [user/job], parent_job_id, steps_json, result, cost_usd, created/finished timestamps), `memories` (id, **user_id**, content, category, embedding, importance, created, last_used), `jobs` (id, **user_id**, kind, schedule, check_mode, check_script_path, instruction, state_json, last_run, next_run, active, created_by_task), `approvals` (id, **user_id**, task_id, action_summary, details_json, status, decided_at), `spend_log` (id, **user_id**, merchant, amount, approved_by, timestamp) — agent-directed spending only, `skills_meta` (id, **user_id**, name, created, uses, successes, failures, reviewed, last_used), `api_costs` (id, **user_id**, task_id, model, input/output tokens, cost, timestamp), `usage_periods` (**user_id**, period_start, period_end, total_cost, included_allowance, overage) — feeds billing, `vault_entries` (id, **user_id**, site, encrypted_blob, created_at) — feeds Phase 4.
**How it works:** Postgres via asyncpg (or SQLAlchemy async), migrations tracked with a numbered `migrations/` folder rather than one static schema file. Every read/write function in `core.db` takes `user_id` as a required first argument (not optional, not inferred) and includes it in the `WHERE` clause — there is no code path that queries `tasks` or any other tenant table without it. A connection pool sized for concurrent multi-user load.
**Interface:** `init_db()`, `create_user()`, `get_user_by_email()`, `create_task(user_id, ...)`, `update_task(user_id, task_id, ...)`, `get_task(user_id, task_id)`, `add_memory(user_id, ...)`, `search_memories(user_id, query)`, `create_job(user_id, ...)`, `due_jobs(now)` (system-level, spans users, used only by the scheduler service — the one deliberate exception, documented as such), `record_approval(user_id, ...)`, `log_spend(user_id, ...)`, `spend_this_month(user_id)`, `log_api_cost(user_id, ...)`, `cost_today(user_id)`, `usage_this_period(user_id)`.
**Done when:** a test creates two users, writes a task/memory/job for each, and confirms querying as user A never returns user B's rows even when both call the same function with different `user_id` values.

### `core/events.py`
**Purpose:** Lets components talk without importing each other; every user-scoped event carries `user_id`.
**How it works:** A tiny async pub/sub bus. Components `subscribe(event_name, handler)` and `publish(event_name, payload)`. Events include `task.requested`, `task.progress`, `task.finished`, `approval.requested`, `approval.decided`, `job.fired`, `notify.user`, `usage.updated`, `system.stop`. Handler errors are caught and logged so one broken subscriber can't crash others or leak across users.
**Interface:** `subscribe()`, `publish()`, `wait_for(event_name, predicate, timeout)`.
**Done when:** a test publishes two events for two different users concurrently and each subscriber only reacts to the one meant for it (predicate checks `user_id`).

### `core/auth.py`
**Purpose:** Signup, login, sessions — the front door.
**How it works:** Email/password with passlib (bcrypt/argon2) hashing, or OAuth login (Google/GitHub) if you want fewer passwords to manage — either is fine, pick one to start. Issues a signed session token (JWT or opaque token in `sessions` table) on login, verified on every web/API request via middleware that resolves it to a `user_id` and rejects anything invalid or expired. Handles email verification and password reset via the email provider from Part 0.
**Interface:** `signup(email, password)`, `login(email, password) -> session`, `verify_session(token) -> user_id`, `send_verification_email()`, `request_password_reset()`.
**Done when:** a new account can sign up, verify email, log in, and every authenticated request resolves to the correct `user_id`; an expired or forged session token is rejected.

**Phase 1 done when:** two test users can be created, each can log in and
get a session, and every table/query in `core.db` is proven tenant-isolated
by test. Still nothing an end user would call "the agent" yet.

---

# Phase 2 — Core loop MVP (first usable multi-user agent)

**Goal:** a signed-up user can chat with their own agent — over a linked
Telegram chat and/or the web dashboard — and it researches, writes/runs
code, and remembers things, all scoped to them alone. **You can stop here**
and have a working multi-tenant product, before autonomy, browsing, or
payments.

**You need:** operator items #6–7, on top of Phase 1.

**Depends on:** all of Phase 1.

**Files in this phase:**

### `tools/base.py`
**Purpose:** The plug-in mechanism that makes the agent extensible, tenant-aware from the start.
**How it works:** A `@tool(name, description, risk)` decorator reads type hints/docstring to auto-generate a JSON schema. Registered tools go into a global registry, exportable per the Agent SDK's format. Every call goes through a wrapper that: logs the call with `user_id` and `task_id`, times it, checks the approval system (scoped to that user) before running anything not marked `safe`, catches all exceptions into `ToolResult(ok=False, error=...)`, truncates oversized outputs, and wraps external content in `<untrusted_content>` tags. The wrapper receives the acting `user_id` from the orchestrator's task context and threads it into every tool call — a tool implementation never accepts a `user_id` argument from the model itself, since the model could then be tricked into supplying someone else's.
**Interface:** `@tool`, `ToolResult`, `registry.all()`, `registry.get(name)`, `registry.export_for_sdk()`, `auto_discover()`.
**Done when:** a dummy tool registers, appears in the exported schema, and a call that raises returns a clean error result carrying the right `user_id` in its log line.

### `tools/web.py`
**Purpose:** Research without a browser, shared infra metered per user.
**Tools:** `web_search(query, num_results)` — risk `safe`. `fetch_page(url, focus)` — downloads with httpx, extracts text with trafilatura, caches for an hour (cache can be shared across users since page content isn't tenant-specific), routes focused extraction through the cheap model. Risk `safe`. `http_request(method, url, headers, body)` — risk `moderate`.
**Done when:** searching and fetching works, and the per-call cost is logged against the calling user's `api_costs`.

### `sandbox/Dockerfile` and `tools/sandbox.py`
**Purpose:** Where the agent writes and runs code — isolated per user, not just per task.
**How it works:** Docker SDK, one long-lived container per task, CPU/memory/time limits from settings (interactive vs autonomous). **Tenant isolation specifics:** each user's containers run on a per-user Docker network with no route to other users' containers or to the host's internal services; each user's workspace volume lives under a per-user path (`/data/sandboxes/<user_id>/<task_id>/`) and the mount logic refuses to construct a path outside that prefix regardless of what a task_id looks like; containers get network access but no env vars, no secrets, no host filesystem access outside their own mounted workspace. Containers destroyed at task end; workspaces kept briefly for debugging, purged on a schedule.
**Tools:** `run_code(language, code)`, `install_package(name)`, `read_file(path)` / `write_file(path, content)` — same risk levels as before, all scoped to the acting user's workspace only.
**Done when:** the agent can fetch and parse a page inside its sandbox, and a task run as user A cannot read, write, or reach anything under user B's workspace path or container network, verified by test.

### `tools/memory.py`
**Purpose:** Long-term knowledge, per user.
**How it works:** Stores short text memories with category and embedding (pgvector, now that the DB is Postgres), all scoped by `user_id`, with importance decaying over time unless reused. The orchestrator pulls the top-N relevant memories for the *current user* into context automatically each task.
**Tools:** `remember(content, category, importance)` — risk `safe`. `recall(query, limit)` — risk `safe`. `forget(memory_id)` — risk `moderate`.
**Done when:** a memory stored by user A never surfaces in a `recall` call made by user B, even with an identical query.

### `tools/notify.py`
**Purpose:** Lets the agent reach a specific user outside a task they started.
**How it works:** Publishes `notify.user` with the target `user_id`; the gateway(s) linked to that user (Telegram, and/or a web push/in-app notification) deliver it. Respects that user's own quiet-hours setting.
**Tools:** `notify_user(message, urgent)` — risk `safe`, always scoped to the calling task's own user.
**Done when:** a notification for user A is delivered only to user A's linked channels.

### `core/context.py`
**Purpose:** Builds the model's context window per task, scoped to the acting user.
**How it works:** Assembles system prompt, task description, that user's relevant memories, that task's recent history (summarized via the cheap model once long), and tool schemas. Enforces a token budget, dropping/summarizing least-relevant history first.
**Interface:** `build_context(user_id, task_id, step_history)`.
**Done when:** context for a long task stays under budget and never includes another user's memories or history, even under concurrent load.

### `core/router.py`
**Purpose:** Picks which model handles which call and meters the cost to the right user.
**How it works:** Named roles (`planner`, `worker`, `cheap`) mapped to model IDs. Every call logs token/cost via `core.db.log_api_cost(user_id, ...)`, which also feeds `usage_periods` for billing.
**Interface:** `call(user_id, role, messages, **kwargs)`.
**Done when:** a call logs cost against the right user, and a user who has hit their plan's cost cap gets a clear error instead of the call proceeding.

### `core/approvals.py`
**Purpose:** The gate every non-safe tool call passes through, per user's own tier rules.
**How it works:** Each user has their own effective `limits.yaml`-derived rules (defaults from Phase 1's config, optionally tightened/loosened by the user within what their plan allows — never loosened past what their plan tier permits, e.g. free tier can't enable payments at all regardless of what rules they set). Given a tool call, its risk level, the acting `user_id`, and `task.source`, returns `auto`, `auto_and_log`, or `require_approval`/`deny`. For `require_approval`, records a row scoped to that user, publishes `approval.requested` with their `user_id`, and awaits their decision via `core.events.wait_for` with a timeout — default deny on timeout.
**Interface:** `check(user_id, tool_call, risk, task) -> Decision`, `decide(user_id, approval_id, approved)`.
**Done when:** the same tool call is auto-approved under one user's looser rules and requires approval under another's stricter rules, and a decision made by one user can never resolve another user's pending approval.

### `core/orchestrator.py`
**Purpose:** The agent loop, run per task, always aware of whose task it is.
**How it works:** On `task.requested` (carrying `user_id`), creates a task row for that user, builds context via `core.context`, runs the Agent SDK loop with tools from the registry, routes model calls through `core.router` with that `user_id`, checks every non-safe tool call through `core.approvals` for that user, enforces that user's step cap for the task's source. Publishes `task.progress`/`task.finished` with `user_id`. Runs multiple users' tasks concurrently, each isolated by its own context, sandbox containers, and DB rows — no shared mutable state between concurrent tasks belonging to different users.
**Interface:** subscribes to `task.requested`; `run_task(user_id, task_id)`.
**Done when:** two different users can run tasks at the same time and neither's task, cost, or tool output leaks into the other's.

### `core/prompts/system.md`
**Purpose:** The agent's system prompt.
**Contents:** Its role, the tools it has, that it should prefer saving reusable skills, that it must not route around approvals, that it should state uncertainty on risky actions, and a line making explicit that it is acting for exactly one user at a time and has no visibility into any other user's data — not because it's told to hide it, but because none of its tools can reach it.
**Done when:** accurately describes the system as built so far.

### `gateway/telegram_bot.py`
**Purpose:** One bot, many linked users.
**How it works:** python-telegram-bot polling loop. Every incoming message's `chat_id` is looked up in `telegram_links` to resolve a `user_id`; unlinked chats get instructions to link via the web app instead of being rejected outright. Linked messages publish `task.requested` with the resolved `user_id` and `source="user"`. Subscribes to `notify.user`/`approval.requested`, filtering to only the chat(s) linked to the relevant `user_id`.
**Done when:** two people with two different linked Telegram accounts each get only their own task results and approval prompts.

### `gateway/account_linking.py`
**Purpose:** Connects a Telegram chat to a web account.
**How it works:** The web dashboard generates a short-lived, single-use linking code for a logged-in user; the user sends that code to the bot; the bot resolves it and writes the `telegram_links` row. Codes expire quickly and are single-use to prevent someone else linking your account by guessing.
**Interface:** `generate_link_code(user_id)`, `redeem_link_code(code, chat_id)`.
**Done when:** a code can only be redeemed once and expires if unused.

### `gateway/web_app.py`
**Purpose:** The dashboard — signup, login, chat, usage, approvals, settings.
**How it works:** FastAPI app using `core.auth` for session handling. Routes: signup/login/logout, a chat view that publishes `task.requested` the same way Telegram does, a usage/billing view (Phase 5 fills this in), an approvals inbox mirroring what Telegram shows, and a settings page for the user's own limits (within plan bounds), quiet hours, and linked Telegram code generator.
**Done when:** a full signup-to-first-task flow works entirely in the browser, with no Telegram required.

### `main.py`
**Purpose:** Process entrypoint.
**How it works:** Loads settings, initializes the DB, calls `tools.base.auto_discover()`, starts `gateway.telegram_bot` and `gateway.web_app` (as separate async services or processes), subscribes `core.orchestrator` to the event bus, runs until `system.stop` or an OS signal.
**Done when:** `python main.py` (or your process manager's equivalent) brings up a working multi-user service from a clean checkout plus a filled `.env`.

**Phase 2 done when:** two independently-created test accounts can each
sign up, link Telegram (or just use the web chat), run a task that
searches the web, runs code, and stores a memory — and neither account can
observe anything about the other's usage, tasks, cost, or memory. **This is
a legitimate stopping point** for a real, if limited, multi-user product.

---

# Phase 3 — Autonomy (per-user scheduling, watchers, skills)

**Goal:** each user's agent can act on its own for them — scheduled jobs,
watchers, and a personal library of reusable skills — without any of it
crossing into another user's jobs or skills.

**You need:** nothing new to sign up for.

**Depends on:** all of Phase 2.

**Files in this phase:**

### `tools/scheduler.py`
**Purpose:** Lets a user's agent create and manage that user's own jobs.
**Tools:** `create_job(kind, schedule, instruction, check_mode, check_script)` — writes a job row scoped to the acting user. Risk `moderate` — logged, and per that user's approval tiers may require approval even from an interactive task. `list_jobs()`, `pause_job(id)`, `delete_job(id)` — scoped the same way, with an ownership check on the job id before any mutation (so a job id from one user can never be paused/deleted by another, even if guessed).
**Done when:** a job created by user A cannot be listed, paused, or deleted by user B even when B supplies A's job id directly.

### `core/scheduler_service.py`
**Purpose:** Fires every user's due jobs — the one system-level (cross-tenant) service in the codebase, and documented clearly as such.
**How it works:** Uses apscheduler against `core.db.due_jobs(now)` (which spans users by design, since this is the scheduler's whole job). For each due job, publishes `job.fired` with that job's `user_id` → orchestrator runs it as a task with `source="job"` for that user only. Watcher jobs run a cheap check first, escalating to a full task only on change, to avoid burning every user's usage on idle polling. A job that errors repeatedly auto-pauses and notifies only its owning user.
**Interface:** background task from `main.py`.
**Done when:** jobs belonging to different users fire independently and on schedule, and one user's failing job never affects another's.

### `tools/skills_tools.py` and `core/skills.py`
**Purpose:** A per-user library of reusable skills the agent writes for itself.
**How it works:** Each skill is a folder under `skills/<user_id>/<skill_name>/` with its code and metadata, registered in `skills_meta` scoped to that user. Tracks uses/successes/failures; flags poor performers as `needs_review` rather than deleting. (A future, optional idea — not built here — would be an opt-in shared skill marketplace where a user can publish a skill for others to copy; that's a deliberate, explicit sharing action, never automatic, and out of scope for this phase.)
**Tools:** `save_skill(...)`, `list_skills()`, `run_skill(name, args)` — risk `moderate` / `safe` / inherited, all scoped to the acting user.
**Done when:** a skill saved by one user cannot be listed or run by another.

**Phase 3 done when:** each test user can create a recurring job and a
watcher, both fire correctly and only for their own account, a repeatedly
failing job auto-pauses and notifies only its owner, and a skill saved by
one user is invisible to another.

---

# Phase 4 — Browser & per-user credentials

**Goal:** each user's agent can operate real websites, including ones
needing their own login — with their secrets encrypted per-user and never
touching the model's context or another user's data.

**You need:** operator item #8 (KMS/encryption key), optionally #10 (MCP
OAuth registrations).

**Depends on:** all of Phase 2; Phase 3 recommended first.

**Files in this phase:**

### `core/secrets_vault.py`
**Purpose:** Built-in, per-user encrypted secrets storage — the default, since you can't require every signup to already have their own Bitwarden account.
**How it works:** Envelope encryption: a root key (from KMS or your generated `VAULT_MASTER_KEY`) encrypts a unique data key per user; that per-user data key encrypts each stored credential. Writes/reads go through `vault_entries`, scoped by `user_id`. Decrypted values are only ever materialized inside the process for the instant a tool needs them (e.g. to fill a login form) and are never written to logs, never returned to the model, and never persisted decrypted anywhere.
**Interface:** `store_credential(user_id, site, value)`, `get_credential(user_id, site) -> value` (internal use by other tools only, never model-facing), `list_sites(user_id)`.
**Done when:** two users can each store a credential for the same site name, and reading "as user A" never returns user B's value even under a deliberately-malformed request.

### `tools/credentials.py`
**Purpose:** Model-facing surface over the vault, plus optional support for a user linking their own external vault instead.
**How it works:** For most users, calls `core.secrets_vault` directly. If a user has opted to link an external vault (e.g. their own Bitwarden), wraps that provider's CLI/API instead, still scoped to that user and still never exposing the raw secret to the model. The only model-facing tool is `list_available_accounts()`, returning site names only, scoped to the acting user.
**Done when:** the browser tool can log into a test site for a specific user, using only that user's stored credential, with no log line or model message ever containing the password.

### `tools/browser.py`
**Purpose:** For sites that need clicking, logging in, or JavaScript.
**How it works:** Playwright with a persistent browser profile per **user** (not shared), so one user's logged-in sessions never appear in another's browser context. Main view is a text snapshot (visible text plus numbered interactive elements) rather than screenshots, for cost and reliability; screenshots available as fallback.
**Tools:** `browser_open(url, profile)`, `browser_snapshot()`, `browser_click(ref)`, `browser_type(ref, text)`, `browser_select(ref, option)`, `browser_scroll(direction)`, `browser_screenshot()`, `browser_back()` — risk `moderate`. `browser_login(site)` — calls `tools.credentials` for the acting user, fills the form itself. Risk `moderate`.
**Done when:** it completes a real login-gated task for one test user, and that user's browser profile/session is confirmed inaccessible to a task run for another user.

**Phase 4 done when:** each of two test users can independently store a
credential, log into a real site with it, and complete a multi-step task
there — with zero cross-user leakage of sessions, credentials, or browser
profiles, and no secret ever visible in logs or model context.

---

# Phase 5 — Platform billing & usage metering

**Goal:** the service can actually charge users for what they use. This is
new relative to a single-user personal deployment, which doesn't need to
bill itself.

**You need:** operator item #9 (Stripe).

**Depends on:** all of Phase 2 (usage/cost logging must already be
accurate per user before you bill off of it).

**Files in this phase:**

### `core/billing.py`
**Purpose:** Turns metered usage into a bill, and enforces plan limits in real time.
**How it works:** Rolls up each user's `api_costs` into `usage_periods` on a schedule (e.g. hourly) and on-demand when checked. Compares running usage against that user's `plans.yaml` allowance; once a user is within a configurable margin of their cap, `core.router`/`core.orchestrator` start refusing new tasks with a clear "usage cap reached" error rather than silently degrading. For paid tiers, reports overage usage to Stripe for metered billing, or simply gates access for flat-rate tiers once the cap is hit. Handles Stripe webhooks for subscription created/updated/cancelled/payment failed, updating `users.plan_tier` and `status` accordingly.
**Interface:** `usage_this_period(user_id)`, `check_within_limit(user_id) -> bool`, `report_usage_to_stripe(user_id)`, `handle_stripe_webhook(event)`.
**Done when:** a test user artificially pushed past their plan's cap is blocked from starting new tasks with a clear message, and a simulated Stripe subscription-cancelled webhook correctly downgrades that user's access.

### `gateway/web_app.py` (update)
**Update:** add a real billing view — current usage vs. plan allowance, a Stripe-hosted billing portal link for managing payment method/plan, and an in-app upgrade flow using Stripe Checkout.
**Done when:** a user can view usage, upgrade their plan, and manage payment details entirely through Stripe-hosted flows (never handling card numbers directly yourselves).

**Phase 5 done when:** usage accurately rolls up per user, plan caps are
enforced in real time (not just reported after the fact), and a full
subscribe → use → get billed → cancel cycle works end-to-end against
Stripe's test mode.

---

# Phase 6 — Agent-directed spending (per user, opt-in, built last on purpose)

**Goal:** a user who explicitly opts in can let their agent make real
purchases on their behalf, using *their own* connected payment method —
never the operator's, never shared, and never available to a user who
hasn't opted in.

**You need:** each opted-in user connects their own payment method (Part
0b, item 4) — nothing new for you as operator beyond what Phase 5 already
set up.

**Depends on:** all of Phase 2 (approvals proven reliable) and Phase 5
(billing/plan-gating already working, since payments should be gated
behind a plan tier too). Phase 3 recommended first so job-vs-interactive
handling is already battle-tested before money is on the line.

**Files in this phase:**

### `tools/payments.py`
**Purpose:** Lets a specific, opted-in user's agent spend that user's own money — the most restricted tool in the system.
**How it works:** Before this tool does anything for a given user, it checks that user has (a) a connected payment method on file and (b) explicitly enabled agent-directed spending in settings; if either is false, every call returns `ok=False` immediately, no exceptions. Wraps the payment provider's API using that user's own stored connection (via `core.secrets_vault`, same pattern as site credentials) — never the operator's own card, never another user's. Every call is checked against that user's own `limits.yaml`-derived tiers (merchant allowlist, per-transaction and monthly caps) before being attempted; anything not clearly `auto` goes to `core.approvals` and blocks until that user answers or it times out. **Jobs can never auto-approve payments for any user, regardless of that user's own configured rules** — enforced in code as a hard second layer beneath the per-user config, so neither a user's mistake nor an operator config bug can silently open this up.
**Tools:** `make_purchase(merchant, amount, description)` — risk `high`. `check_spend_status()` — risk `safe`.
**Done when:** a purchase within one opted-in user's allowlist/cap goes through automatically for an interactive task; the identical call from a job-triggered task still requires approval; a call made for a user who hasn't opted in is refused outright with no approval prompt at all (there's nothing to approve); and one user's spending never touches another user's connected payment method even under a deliberately-crafted request.

**Phase 6 done when:** you've tested every deny path (no payment method
connected, opted-out, over cap, off-allowlist, job-sourced, wrong-user)
before ever testing a real successful purchase, for at least two separate
test users with different configurations.

---

# Phase 7 — Tests & ops

**Goal:** confidence that tenant isolation and the safety model both hold
under real, concurrent, multi-user load — and that the service survives
being unattended, at scale, for real.

**You need:** nothing new to sign up for.

**Depends on:** whichever phases you've built.

**Files in this phase:**

### `tests/test_tasks.yaml`, `tests/trap_tests.yaml`, `tests/run_evals.py`
**Purpose:** Catch regressions and, specifically, catch cross-tenant leaks and safety-model violations.
**How it works:** `test_tasks.yaml` — ordinary tasks with expected-behavior checks. `trap_tests.yaml` — adversarial cases, now including: two users running tasks concurrently and checking neither sees the other's data; a task supplying another user's job/skill/approval id directly and confirming it's refused; a job-sourced task attempting a high-risk action (approval required, every time); a request exceeding a plan's usage cap (blocked); a sandbox escape attempt (fails); a payments call for a non-opted-in user (refused outright). `run_evals.py` runs both sets and reports pass/fail, weighting cross-tenant and safety-model failures as the most serious category.
**Done when:** running it against the finished system shows all trap tests passing, including every cross-tenant case.

### `scripts/backup.sh`
**Purpose:** Backs up the Postgres database and per-user skills/workspace data on a schedule, outside the app itself.
**Done when:** run manually, it produces a timestamped backup you can restore from, and a restore test confirms per-user data comes back correctly scoped.

### `Dockerfile` and `docker-compose.yml`
**Purpose:** Run the whole stack — web app, Telegram gateway, orchestrator, scheduler, Postgres, and the sandbox layer — ready for real deployment on the hosting from Part 0, sized for multiple concurrent users rather than one household.
**Done when:** `docker compose up` brings up the full stack against a fresh database, survives a restart with all users' jobs/memories/usage intact, and can handle several simulated concurrent users without cross-talk.

**Phase 7 done when:** all trap tests pass including every cross-tenant
case, a backup/restore cycle has been tested for real, and the whole stack
comes up cleanly and holds under a simulated multi-user load test.

---

# Summary: what you get after each phase

| Phase | What becomes true |
|---|---|
| 1 | Accounts exist; the data layer is provably tenant-isolated. Nothing agent-like yet |
| 2 | **Usable multi-user product**: sign up, chat, it researches/codes/remembers — per user |
| 3 | Each user's agent acts on its own: schedules, watchers, a personal skill library |
| 4 | Each user's agent can operate real, login-gated websites with their own secrets |
| 5 | You can actually bill users for the service, with real-time plan enforcement |
| 6 | Opted-in users can let their agent spend their own money, tightly capped two ways |
| 7 | Tenant isolation and the safety model are proven under real, concurrent load |
