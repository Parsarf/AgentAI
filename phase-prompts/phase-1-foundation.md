# BUILD PROMPT — Phase 1: Foundation & accounts

> Paste this entire file into a fresh AI coding session, opened in the repo root.

You are a senior engineer building **Phase 1 of 7** of the project below. This prompt is self-contained. Work autonomously; ask the user only if truly blocked (missing credentials, spec conflict). Where the spec leaves a choice open, pick the simplest option that satisfies every stated rule, implement it, and record the decision in `BUILD_NOTES.md`.

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
  - PLATFORM BILLING (Phase 5): what the operator charges the user for the
    service itself. Metered from shared operator-held API keys, rolled up
    per user, billed via Stripe. Lives in core/billing.py.
  - AGENT-DIRECTED SPENDING (Phase 6): the agent buying something in the
    real world on a specific user's behalf, using that user's own connected
    payment method, only after that user opted in. Lives in
    tools/payments.py. Never uses the operator's own card, ever.
    (Phase 6 builds NONE of this yet — but never design anything that
    makes it harder later.)

CONVENTIONS:
- Fully async. Type hints everywhere. Pydantic models for structured data.
- Config only via core.config.settings, never hard-coded values or
  os.environ reads outside core/config.py.
- Logging only via core.logging.get_logger(__name__). Never log secrets,
  and every log line carries both task_id and user_id for traceability.
- Database access only via functions in core.db, and every function takes
  a user_id (or an already-scoped session object) as its first argument.
- Secrets (passwords, card numbers, API keys, per-user vault contents)
  must NEVER enter the model's context. Tools that need secrets fetch them
  internally, scoped to the acting user, and use them directly.
- Components communicate through core.events (a simple async event bus)
  instead of importing each other directly. Every event payload that
  concerns a specific user carries that user_id.
```

## 2. Read before writing any code

1. `agent-build-spec-multiuser.md` (repo root) — the authoritative spec. Read the Shared context block, **Part 0a**, the **Phase 1** section, the folder tree, and the summary table. Where this prompt and the spec disagree, the spec wins — report the conflict instead of silently choosing.
2. `BUILD_NOTES.md` if it exists — decisions and state from earlier sessions.
3. If any Phase 1 files already exist (partial earlier session), inventory them and **continue**, don't restart.

## 3. Process rules — follow exactly

1. Build **only** what Phase 1 lists. No agent loop, no tools, no gateways, no billing logic, no vault encryption — tables for later phases are defined now, but their logic is not.
2. Work in the order given in §6. Finish each file's acceptance check before starting the next.
3. Write the test for each component when you finish that component. Tests use pytest + pytest-asyncio and must actually run and pass.
4. Never fabricate external services. If a required credential is missing from `.env`, stop and tell the operator exactly which key is missing. Mocks are allowed **only** inside unit tests and must be clearly labeled as mocks.
5. Money is `Decimal`/`NUMERIC` — never float. Timestamps are `TIMESTAMPTZ` — never naive `TIMESTAMP`.
6. Never log or print secret values. Never write real secrets to any file except `.env` (which must be gitignored from the very first commit). Keep `.env.example` in sync with every key you introduce.
7. Every choice the spec leaves open gets one line in `BUILD_NOTES.md` (`DECISION:` ...).
8. At session end, print a report: files created/changed, test commands run + results, anything unfinished and why, open questions. Append the same to `BUILD_NOTES.md`.

## 4. Prerequisites (operator items, spec Part 0a #1–5)

Required in `.env` before anything runs end-to-end: `DATABASE_URL` (Postgres 16 with pgvector — dev can use the `pgvector/pgvector:pg16` Docker image), `SESSION_SECRET`, `EMAIL_API_KEY` (a transactional provider: Postmark/SES/Resend — verification + reset emails must actually send). `ANTHROPIC_API_KEY` and `TELEGRAM_BOT_TOKEN` should exist but are not exercised until Phase 2; they must still appear in `.env.example`. Domain/host/TLS are deployment concerns — not needed for Phase 1 tests.

## 5. Work order and file specs

Build in this order. `agent/` is the package root exactly as the spec's folder tree shows.

### 5.1 `requirements.txt`, `.env.example`, `.gitignore`

- `requirements.txt` pins exact versions of: claude-agent-sdk, anthropic, fastapi, uvicorn, asyncpg (or sqlalchemy[asyncio] — pick one, note it), pgvector (python side), pydantic, pydantic-settings, pyyaml, python-telegram-bot, playwright, httpx, trafilatura, apscheduler, docker, python-dotenv, passlib, pyjwt, stripe, cryptography, pytest, pytest-asyncio, ruff. Add sentence-transformers (pinned) — needed in Phase 2 for memory embeddings, and its model download is the slow install; installing it now avoids a surprise later.
- `.env.example`: every key from §4 with a one-line comment explaining what it is and which Part 0a item provides it.
- `.gitignore`: `.env`, `logs/`, `data/`, `skills/`, `__pycache__/`, `.pytest_cache/`, `dist/`.
- **Accept:** `python -m venv .venv && .venv/bin/pip install -r requirements.txt` succeeds clean.

### 5.2 `config/settings.yaml`, `config/limits.yaml`, `config/plans.yaml`, `config/mcp_servers.yaml`

Every value commented. Valid YAML. Schemas:

- `settings.yaml`:
  - `models: {planner: <id>, worker: <id>, cheap: <id>}` (e.g. planner/worker = a Sonnet-class model, cheap = a Haiku-class model — check current Anthropic model IDs).
  - `model_prices`: per model `{input_per_mtok_usd, output_per_mtok_usd}` (Decimal-friendly strings), plus `search_per_query_usd`.
  - `limits: {max_steps_interactive: 40, max_steps_job: 15, task_timeout_seconds: 900, context_token_budget: 160000, approval_timeout_seconds: 600}`.
  - `sandbox: {cpu_quota: 1.0, memory_mb: 1024, pids_limit: 128, network_enabled: true, workspace_retention_hours: 24}`.
  - `timezone_default: "UTC"`, `quiet_hours: {start: "22:00", end: "08:00"}`, `browser: {headless: true}`.
  - `embeddings: {provider: "local", model: "all-MiniLM-L6-v2", dimensions: 384}`.
- `limits.yaml` — default approval-tier rules new users start with. A list of rules, evaluated top-down, first match wins; each rule: `match:` (any of `tools: [names]`, `risk: safe|moderate|high`, `amount_above_usd`, `merchants: [domains]`, `source: user|job|any`) → `action: auto|auto_and_log|require_approval|deny`. Ship a sane default set: safe→auto; moderate from user→auto_and_log; moderate from job→require_approval; high from user→require_approval; high from job→deny; final `fallback: require_approval`.
- `plans.yaml` — tiers `free` and `pro`, each: `{monthly_included_usage_usd, hard_cap_usd, concurrent_tasks, max_active_jobs, autonomous_jobs: bool, browser_tools: bool, payments_enabled: bool, stripe_price_id: null|"<price_id>"}`. Free: autonomous_jobs false, browser_tools false, payments_enabled false, hard_cap small. Pro: more generous, stripe_price_id set later in Phase 5.
- `mcp_servers.yaml` — `{servers: [{name: gmail|gcal..., enabled: false, oauth: {client_id_env, scopes: [...], auth_url, token_url}}]}`. All disabled by default.
- **Accept:** `python -c "import yaml; [yaml.safe_load(open(f'config/{f}')) for f in ...]"` parses all four; every file's values are commented.

### 5.3 `core/config.py`

- pydantic-settings `BaseSettings` loads `.env` secrets (`ANTHROPIC_API_KEY`, `SEARCH_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `EMAIL_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `VAULT_MASTER_KEY`, `SESSION_SECRET`, `BASE_URL`).
- Merge the four YAML files into typed nested pydantic models. Expose one module-level `settings` object and `reload()` (re-reads YAML; secrets are not reloaded).
- Validation at import/startup must fail **loudly** with the exact bad key and file named. Provide `settings.require(key)` that raises a clear error naming the Part 0a item to fix, and `settings.masked()` / a `__repr__` that replaces any secret with `"[SET]"`/`"[MISSING]"`.
- **Accept:** a test loads everything, prints masked settings (no secret value appears), and a deliberately corrupted YAML raises an error naming the file and key.

### 5.4 `core/logging.py`

- JSON log lines: timestamp, level, logger name, message, plus `task_id` and `user_id` auto-attached from contextvars.
- `set_task_context(task_id, user_id)` sets both contextvars and returns a reset token; `get_logger(name)` returns a stdlib logger wired to the JSON formatter.
- `RedactionFilter`: (a) exact-match replacement of any value registered via `register_secret(value)` (settings secrets register at startup), (b) regex patterns for card numbers (Luhn-checked 13–19 digits), `sk-...` API keys, JWTs, and `password=` query params. Replacements become `[REDACTED]`. Applies to message and to any str in extra/kwargs.
- Handlers: stdout + `RotatingFileHandler("logs/agent.log", 10 MB, backupCount=5)`.
- **Accept:** logging a string containing a registered secret outputs `[REDACTED]`; after `set_task_context("t1","u1")`, every emitted line carries `"task_id":"t1","user_id":"u1"`.

### 5.5 `db/migrations/0001_init.sql` + `core/db.py`

Migration runner: `schema_migrations(version int pk, applied_at)`; `init_db()` applies numbered files in order, each exactly once, inside a transaction. **`db/schema.sql` may exist only as a convenience dump of the final state — migrations are the source of truth.**

Tables (exact columns; all FKs `ON DELETE CASCADE`, all ids uuid pk default `gen_random_uuid()`):

- `users`: email citext unique not null, password_hash, oauth_subject (nullable, unique where present), created_at, plan_tier text default 'free', stripe_customer_id, status text default 'active' check in (active,suspended,deleted).
- `sessions`: user_id fk, token_hash text unique not null, expires_at timestamptz, created_at.
- `telegram_links`: telegram_chat_id text unique, user_id fk, linked_at.
- `tasks`: **user_id fk**, request text, status text default 'pending' check in (pending,running,awaiting_approval,done,failed,cancelled), source text check in (user,job), parent_job_id, steps_json jsonb default '[]', result text, cost_usd numeric(12,4) default 0, created_at, started_at, finished_at.
- `memories`: **user_id fk**, content text, category text, embedding vector(384), importance real default 0.5, created_at, last_used_at.
- `jobs`: **user_id fk**, kind text check in (recurring,watcher), schedule text (cron), check_mode text check in (always,on_change), check_script_path, instruction text, state_json jsonb default '{}', last_run_at, next_run_at, active boolean default true, created_by_task, created_at.
- `approvals`: **user_id fk**, task_id, action_summary text, details_json jsonb, status text default 'pending' check in (pending,approved,denied,expired), created_at, decided_at.
- `spend_log`: **user_id fk**, merchant text, amount numeric(12,2), currency text default 'usd', approved_by text, status text, task_id, created_at. (Agent-directed spending only — Phase 6 fills it.)
- `skills_meta`: **user_id fk**, name text, created_at, uses int default 0, successes int default 0, failures int default 0, reviewed boolean default true, last_used_at; unique(user_id, name).
- `api_costs`: **user_id fk**, task_id, model text, input_tokens int, output_tokens int, cost_usd numeric(12,6), created_at.
- `usage_periods`: **user_id fk**, period_start date, period_end date, total_cost numeric(12,4) default 0, included_allowance numeric(12,4), overage numeric(12,4) default 0, updated_at; unique(user_id, period_start).
- `vault_entries`: **user_id fk**, site text, encrypted_blob bytea, created_at, updated_at; unique(user_id, site).

`CREATE EXTENSION IF NOT EXISTS vector;` first. Indexes: every tenant table indexed with `user_id` as leading column; `tasks(user_id, status)`, `jobs(active, next_run_at)`, `memories` ivf/hnsw index on embedding, `sessions(token_hash)`, `approvals(user_id, status)`.

`core/db.py` — asyncpg pool (or async SQLAlchemy; your pick, record it) sized for concurrent multi-user load (`min 2, max 20`, from settings). **Ironclad rule: every function touching a tenant table takes `user_id` as its required first argument and puts it in the WHERE clause. The one deliberate exception is `due_jobs(now)`, which must carry a docstring saying exactly that and why.** Signatures:

```python
init_db() -> None
create_user(email, password_hash: str | None, oauth_subject: str | None, plan_tier="free") -> User
get_user(user_id) -> User | None
get_user_by_email(email) -> User | None
update_user(user_id, **fields) -> User
create_session(user_id, token_hash, expires_at) -> Session
get_session_by_token_hash(token_hash) -> (Session, User) | None   # joins users; rejects expired
delete_session(token_hash) -> None
create_task(user_id, request, source, parent_job_id=None) -> Task
update_task(user_id, task_id, **fields) -> Task | None            # None if not owned
get_task(user_id, task_id) -> Task | None
list_tasks(user_id, limit=50, offset=0) -> list[Task]
add_memory(user_id, content, category, embedding: list[float], importance) -> Memory
search_memories(user_id, embedding: list[float], limit=10) -> list[Memory]  # cosine distance, per user only
create_job(user_id, kind, schedule, check_mode, instruction, check_script_path=None, created_by_task=None) -> Job
update_job(user_id, job_id, **fields) -> Job | None
get_job(user_id, job_id) -> Job | None
list_jobs(user_id) -> list[Job]
due_jobs(now) -> list[Job]           # THE one cross-tenant function; documented exception
record_approval(user_id, task_id, action_summary, details_json) -> Approval
update_approval(user_id, approval_id, status) -> Approval | None     # scoped to user_id
log_spend(user_id, merchant, amount, currency, approved_by, status, task_id=None) -> None
spend_this_month(user_id) -> Decimal
log_api_cost(user_id, task_id, model, input_tokens, output_tokens, cost_usd) -> None
cost_today(user_id) -> Decimal
usage_this_period(user_id) -> UsageSummary          # pydantic model
upsert_usage_period(user_id, period_start, period_end, total_cost, included_allowance, overage) -> UsagePeriod
create_vault_entry(user_id, site, encrypted_blob: bytes) -> VaultEntry
get_vault_entry(user_id, site) -> VaultEntry | None
list_vault_sites(user_id) -> list[str]
```

Rows map to pydantic models (typed, frozen where sensible). `due_jobs` must also advance `next_run_at` atomically (or be documented as called under an advisory lock) so two scheduler ticks can't double-fire a job — implement the advisory-lock version now; Phase 3 thanks you.

- **Accept:** `init_db()` runs clean twice (idempotent migrations).

### 5.6 `core/events.py`

Tiny async pub/sub. `subscribe(event_name, handler)`, `publish(event_name, payload: dict)`, `wait_for(event_name, predicate, timeout) -> dict | None`. Event-name constants: `task.requested`, `task.progress`, `task.finished`, `approval.requested`, `approval.decided`, `job.fired`, `notify.user`, `usage.updated`, `system.stop`. Rules: handler exceptions are caught and logged (one broken subscriber never crashes others); every user-scoped payload carries `user_id` (assert it in publish when the event name is one of the user-scoped ones); `wait_for` resolves with the first matching payload and cleans up its subscription.

### 5.7 `core/auth.py`

- Password auth by default (OAuth optional later; note the decision). passlib `CryptContext` with argon2id (fallback bcrypt).
- `signup(email, password)`: validate strength (min 10 chars), create user `status='email_unverified'` (add that state to the check constraint in the migration), email a verification link `{BASE_URL}/verify?token=...`. Token: HMAC-signed (itsdangerous-style, `SESSION_SECRET`), single-purpose, 24 h expiry. Login blocked until verified.
- `login(email, password)`: constant-time compare; on success issue an **opaque** session token (`secrets.token_urlsafe(32)`), store only its SHA-256 hash in `sessions`, 30-day expiry. Returning the raw token is the caller's job (cookie in Phase 2). Rate-limit failed logins in-process (10/hour per email+IP; note Redis for production).
- `verify_session(token) -> user_id | None` (rejects expired/unknown).
- `request_password_reset(email)` / `reset_password(token, new_password)`: single-use signed token, 30 min expiry, invalidates all existing sessions for that user.
- Simple provider-agnostic email sender inside this module (JSON POST to Postmark/Resend-compatible API via httpx, provider/base URL from settings); unit tests mock it.
- **Accept:** full signup → verify → login → authenticated roundtrip in a test; expired and forged tokens rejected; password reset works and kills old sessions.

## 6. Tests to write (`tests/`)

- `tests/conftest.py`: pytest-asyncio; a disposable test database (`TEST_DATABASE_URL`, schema created/dropped per session via `init_db()` on an empty DB); event-bus and logging fixtures; explicit mocks for email/Anthropic.
- `test_tenancy.py` — the headline test: create users A and B; write tasks, memories, jobs for each; then assert, for **every** getter/updater in `core.db`, that calling as A never returns or mutates B's rows — including `update_task(B_user_id, A_task_id, ...)` returning None and `get_task` likewise. A parametrized test over the function list keeps this honest.
- `test_events.py`: concurrent publishes for two users; predicate-filtered subscribers each react only to their own; one raising handler doesn't break the other; `wait_for` times out returning None.
- `test_logging.py`: redaction of registered secrets and card-number regex; context vars attached.
- `test_auth.py`: the full flow from §5.7's acceptance.
- `test_config.py`: loads, masks, fails loudly on bad YAML.

## 7. Smoke script

`scripts/smoke_phase1.py` (async main): runs migrations, creates two users, runs the §6 tenancy scenario with printed PASS/FAIL per assertion, exercises signup/verify/login against a mocked emailer. Prints a final summary line. `python scripts/smoke_phase1.py` must exit 0.

## 8. Out of scope (do NOT build)

Anything agent-like: tools, orchestrator, router, context builder, gateways, sandbox, scheduler service, skills, vault encryption, Stripe logic, payments, Docker deploy. Their tables exist; their code does not.

## 9. Phase done when

- [ ] `pip install -r requirements.txt` succeeds in a clean venv.
- [ ] All four YAML configs load, commented, into typed settings; bad values fail loudly.
- [ ] Logging redacts registered secrets and stamps task_id/user_id on every line.
- [ ] `init_db()` applies migrations idempotently; all 12 tables + indexes exist.
- [ ] `test_tenancy.py` proves **every** `core.db` function tenant-scoped (the `due_jobs` exception documented in its docstring).
- [ ] Events bus isolates subscriber failures; user_id present on user-scoped events.
- [ ] Signup → verify → login → session verify works; expired/forged tokens rejected; password reset revokes sessions.
- [ ] `pytest` green; `python scripts/smoke_phase1.py` exits 0.
- [ ] `BUILD_NOTES.md` records every open decision.

Two test users can be created, each can log in and get a session, and every table/query in `core.db` is proven tenant-isolated by test. Still nothing an end user would call "the agent" — that's Phase 2.
