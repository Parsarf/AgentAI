# BUILD_NOTES — shared across build sessions

Appended by every phase session: decisions, environment facts, unfinished
work. Read this before writing code.

---

## Per-user Anthropic API keys (2026-09-23)

At the user's request, purchase execution remains disabled; no provider or
charging adapter was added. Instead, authenticated users can enter/remove an
Anthropic API key in Settings. It is encrypted using the existing per-user
vault, never rendered back to the page, and reserved from model-facing
credential listing, reading, storing, and deletion. A user's key takes
precedence over the optional operator `ANTHROPIC_API_KEY`; a missing key on
both paths produces an actionable Settings error. Both the Claude Agent SDK
loop and direct Anthropic router use the user's own key. The operator fallback
is preserved for users without one. Existing app plan usage caps still apply,
even if the user pays Anthropic directly.

The app's agent loop is currently Claude Agent SDK-specific, so OpenAI and
other API keys are **not** accepted as if interchangeable. Adding a different
provider requires an explicit agent-loop adapter and separate testing. The
Anthropic key is saved but not probed for validity (no surprise API calls or
cost on save); users should create a workspace-scoped key. Anthropic's
documented Python client accepts an explicit `api_key` and the Agent SDK
uses `ANTHROPIC_API_KEY`:
https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python and
https://platform.claude.com/docs/en/manage-claude/authentication . OpenAI's
official guidance likewise requires API keys to remain server-side:
https://developers.openai.com/api/reference/overview .

Focused BYOK tests: 5 passed; full suite: **185 passed, 2 pre-existing
warnings**; `ruff check .`: clean. No live user-key model call was made because
no user-provided test key was available. No migration was needed (the reserved
credential uses the existing tenant vault). Verify with a user key before
claiming end-to-end live operation.

---

## Phase 6 — Purchase boundary (partial, 2026-09-23)

**Not end-to-end complete. Real purchases remain disabled.** Baseline: 166
tests passed. Denial tests were written and run before the implementation;
their first run failed at collection because `tools.payments` did not exist.
After implementation: focused 14 passed; full suite **180 passed, 2
pre-existing warnings**; `ruff check .` clean. All tests used the guarded
disposable `agent_test` database. No money moved and no provider was called.

- Added `0007_purchase_preflight.sql` with tenant-scoped draft purchase policy
  and denied-attempt audit tables. Applied additively to the local `agent`
  database after checking its identity/version (6 → 7; 1 existing user); did
  not reset user data. Regenerated `db/schema.sql`.
- Added a fail-closed `make_purchase` and tenant-scoped `check_spend_status`.
  The payment call bypasses the generic approval gate to perform its own
  denial first, so invalid/unavailable attempts create no approval requests,
  including when the old task-wide `approvals_prechecked` flag is set. Runtime
  `payments.enabled=false`; enabling it alone still cannot make a charge.
  The purchase tool is not advertised to the agent while disabled.
- Settings now show the unavailable state and allow saving **draft** USD caps
  and merchant hostnames with CSRF/session checks. Saving limits never opts in.
  No card fields, bare token intake, hosted connection, or purchase-execution
  adapter were added. The system prompt warns against browser checkout bypass
  and blind retry of uncertain charges.
- Denial coverage includes two users, free/pro, invalid and non-finite amounts,
  URL/userinfo merchants, unsupported currency, job mode, no approval row,
  per-user audit/status isolation, and task-wide approval-bypass flag.

**Provider investigation:** Stripe subscriptions/Checkout in Phase 5 collect
payment for *this application*, not an authority to pay arbitrary merchants.
Stripe Connect direct charges are for connected merchant accounts and copied
payment methods, not arbitrary domains:
https://docs.stripe.com/connect/direct-charges-multiple-accounts . Stripe's
agentic-commerce Shared Payment Tokens require participating merchants and
buyer-authorized, scoped payment instructions:
https://stripe.com/guides/agentic-commerce-primer . No supported merchant
network, recipient/order mapping, hosted user connection, sandbox credentials,
idempotency contract, or lookup/reconciliation path is configured here.

**Still required for Phase 6:** choose a provider and supported merchants;
verify its hosted user authorization and sandbox API; then implement opt-in,
canonical registrable-domain/recipient matching, transaction/monthly cap
reservation, invocation/order identity, owner-only bound approvals, provider
execution and unknown-result reconciliation, notifications, and test-only
fake plus provider-sandbox success tests. The current draft policy/audit is a
fail-closed foundation, **not** an operational purchase ledger. Do not turn
on spending until these are implemented and verified.

---

## Phase 5 — Lean billing (implemented 2026-09-23)

**Local implementation complete; Stripe test-mode validation pending.**
Baseline before edits: 156 passed, 2 warnings. Final full suite: **166 passed,
2 warnings** (`cd agent && ../.venv/bin/python -m pytest -q`, 36.39 s);
`../.venv/bin/ruff check .`: clean. The warnings are the pre-existing passlib
`crypt` and argon2 version deprecations. Migration `0006_billing.sql` applied
to the app database (version 5 → 6; read-only precheck found 1 user/0 tasks).
`db/schema.sql` regenerated from the migrated schema. The app's existing user
and data were not reset. Test fixture targets `agent_test`; it now refuses
non-`*_test` and same-database DSNs before schema reset.

### Implemented

- SDK `ResultMessage.model_usage`/`total_cost_usd` now records measured model
  cost into `api_costs`, including provider-reported cache cost. Per-model rows
  share a durable operation identity; duplicate settlement is idempotent.
  `tasks.cost_usd` is derived from that ledger at task finalization. Missing
  result usage keeps its reservation in `unknown` for reconciliation rather
  than pretending the run was free. Search and direct router calls reserve and
  settle in the same ledger.
- Per-user, per-period reservations use a short `SELECT users ... FOR UPDATE`
  transaction. Settled plus outstanding cost is checked against the plan cap.
  The SDK receives `max_budget_usd` and the existing turn limit. Admission,
  queued execution, and tool use re-read current plan constraints. The per-user
  concurrency gate no longer replaces a semaphore while earlier tasks run.
- `core/billing.py` supplies live usage and cap decisions, warning dedupe at
  90%, on-demand reports, and an hourly report refresh for active users.
  Calendar-month usage is distinct from Stripe subscription renewal dates.
- Flat Stripe subscription flow: hosted Checkout and Billing Portal, customer
  idempotency, verified webhook signature, event dedupe in the DB transaction,
  plan derivation from current provider subscriptions/prices, and past-due
  grace. Billing events do not change account security status. Web UI has no
  card fields. `billing.enabled=false` keeps local caps active.
- Pricing source verified 2026-09-23: Anthropic's
  https://platform.claude.com/docs/en/about-claude/pricing . Sonnet 5 uses
  $2/$10 per MTok input/output and $2.50/$0.20 5-minute cache write/read;
  Haiku 4.5 uses $1/$5 and $1.25/$0.10. These are *provider cost estimates*,
  not the flat subscription amounts paid by users. Update rates as needed.

### Validation and remaining work

- Ten new tests exercise concurrent reservations, SDK-to-ledger wiring,
  per-model and cache costs, warning dedupe, queued task downgrade,
  signed/invalid and duplicate Stripe webhooks, cancel downgrade, hosted
  checkout retry identity, tenant isolation, and distinct handling for setup
  failures versus ambiguous provider failures. All pass with a real
  disposable Postgres and fake provider boundary. Existing 156 tests still pass.
- One bounded **live** Anthropic router call (`cheap`, `max_tokens=16`, prompt
  "Reply OK only.") returned HTTP 200: 11 input/4 output tokens, **$0.000031**
  persisted to `agent_test.api_costs`. This verifies the direct API path; the
  full SDK path is tested with a deterministic SDK result because Docker/CLI
  execution was unavailable here.
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and paid `stripe_price_id` are
  absent. `billing.enabled` remains **false**. Therefore no real Stripe test
  subscription, invoice, portal, or cancel cycle was run. To finish Phase 5
  provider validation: configure test-mode keys, a recurring Pro price, enable
  billing, run Stripe CLI/webhooks, and perform subscribe → use → invoice →
  cancel against test mode. Do not enable live charging yet.
- The SDK's `max_budget_usd` is a stop-after-cost control, so one in-flight
  provider call may exceed the reserved amount. Actual cost is still recorded
  and further work is blocked; an absolute no-overshoot guarantee is **not
  proven**. Unknown SDK outcomes retain reservations and currently require
  manual reconciliation; no automatic provider-side per-task cost lookup is
  available in this implementation. These are release limits for paid billing.

---

## Phase 4 — Browser & per-user credentials (completed 2026-09-23)

**Status: DONE.** `pytest`: 156 passed (126 prior + 30 new). `ruff check`:
clean. `python main.py` boots: web :8000, scheduler up, 28 tools discovered,
clean shutdown. Browser integration tests run REAL headless Chromium against
a local stdlib-HTTP login site (no Docker, no third-party sites) and skip
cleanly where Chromium is unavailable.

### BUG FIXED (latent Phase 2, caught by the Phase 4 leak canary): tools had
### no user context in real tasks
`orchestrator.run_task` set core.LOGGING's task context but never
`tools.base.current_user_id/current_task_id` — every tool in every REAL SDK
task would have failed with "internal: no task context". Phase 2's tests
masked it because their fake loops set the context themselves. Fix:
run_task now sets and resets the tools.base context alongside the logging
context. The canary test (full browser_login through a mocked loop calling
real `call_tool`) exposed it on its first run.

### Vault (core/secrets_vault.py)
- Envelope encryption: per-user 32-byte data key, AES-256-GCM-wrapped under
  the root key in `vault_keys` (migration **0005** — the prompt's
  "0004_vault_keys.sql" number was already taken by Phase 3; numbering
  continued, migrations dir is source of truth).
- Root key: `VAULT_MASTER_KEY` (HKDF-style SHA-256 derivation, tolerates any
  length) via `vault.kms: null`. KMS seam: `vault.kms {provider, key_id}`
  config exists; with it set, the vault refuses to run until a provider
  adapter is installed (root key never enters memory in KMS mode). A mocked
  KMS/root-rotation test proves old blobs fail closed after rotation.
- Every value blob: AES-GCM with the user's data key, fresh nonce per write,
  **AAD = "user_id:site"** — swapped/copied blobs and forged user ids fail
  cryptographically (tests cover all three attacks). Tamper → VaultError,
  never partial plaintext.
- `SecretValue` (str subclass): repr/str = "[REDACTED]"; raw only via
  `.reveal()` inside tool internals. Every decrypt + store registers the
  value with the log redaction filter (`register_secret`).
- Key cache is memory-only with `vault.cache_seconds` TTL and
  `drop_key_cache()`. Lost-race handling on concurrent first-store: the
  stored (first) wrapped key wins and the loser adopts it.

### Credentials surface (tools/credentials.py)
- ONLY model-facing tool: `list_available_accounts` (site names, own user).
  `get_credential_for_user` / `store_credential_for_user` /
  `secret_password(value)` are internal (browser now, Phase 6 payments
  later). `VaultBackend` seam: builtin ships; `users.vault_mode` (migration
  0005) selects; `bitwarden` backend raises "not yet available".
- Web settings: `POST /settings/vault` (site/username/password → stored as
  JSON blob, values never echoed), `POST /settings/vault/delete`, site
  names listed on the page. The agent never writes user credentials.

### Browser (tools/browser.py)
- Persistent Playwright profile per USER (+ named profile), path derived
  only via the sandbox id validator + realpath confinement from
  `browser.profile_root` (default `/data/browser_profiles`).
- Container mode (default): chromium in a per-user container on the user's
  own network, driven over CDP (`connect_over_cdp`); image from
  `sandbox/Dockerfile.playwright` (operator builds `agent-browser:latest`).
  Local mode (`browser.local_mode`, default OFF — dev/tests only): local
  chromium, same per-user dirs; SSRF guard (`assert_public_url`) is enforced
  in container mode and skipped in local mode so 127.0.0.1 test sites work.
- Text snapshots (visible text + numbered `[n]` interactive elements) are
  the main view, always returned as `<untrusted_content source="page:URL">`;
  actions act by ref; refs refresh after every action. Tools:
  open/snapshot/click/type/select/scroll/back/screenshot (jpeg to file,
  path only)/login. `browser_type(..., secret=True, text=<site>)` types the
  STORED password — the site key goes through model context, the secret
  never does. `browser_login` = fetch credential → fill (password via the
  secret path) → submit → verify password field gone; failure returns
  "login failed" + snapshot, never values.
- Sessions refcounted per (user, profile, task) and closed when the last
  using task finishes (`task.finished`); profile dirs purge via the
  scheduler sweep after `browser.profile_retention_days`.
- Plan gating: `browser_tools` tier flag omits browser tools from
  `export_for_sdk` AND hard-denies in approvals (both pre-existing, now
  test-covered); job-sourced browser use ⇒ require_approval (mode floor).

### Config added (settings.yaml)
`browser.local_mode/default_timeout_ms/snapshot_max_chars/profile_root/
profile_retention_days`, `vault.kms/cache_seconds`. Operator prerequisite
done this session: `VAULT_MASTER_KEY` generated into `.env` (was empty).

### Test site
`tests/browser_site.py`: stdlib-HTTP login-gated site on 127.0.0.1 with
session cookie + gated /account page (the prompt suggested Docker; no
Docker on this machine, so a thread-hosted local site serves the same
purpose and keeps tests hermetic).

### Test files
`test_vault_crypto.py`, `test_vault_tenancy.py` (incl. web vault flow),
`test_no_secret_leaks.py` (THE CANARY: password absent from logs, model
messages, task rows/steps_json, tool results, profile-dir files — while the
login provably succeeded), `test_browser_tools.py`, `test_browser_tenancy.py`.

### Before Phase 5
- Anthropic credits confirmed WORKING (live API probe 2026-09-23 — the
  Phase 2 credit blocker is resolved).
- Still open (non-blocking): Docker/sandbox + browser images for prod
  container mode; `email.from_address` still the Brevo-unverified
  placeholder; Phase 5 needs `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`.

### How to verify Phase 4
```
cd agent && ../.venv/bin/python -m pytest -q     # 156 passed
../.venv/bin/ruff check .                        # clean
../.venv/bin/python scripts/check_env.py         # VAULT_MASTER_KEY: SET
```

---

## Phase 3 — Autonomy (completed 2026-09-23)

**Status: DONE.** `pytest`: 126 passed (89 prior + 37 new). `ruff check`:
clean. `python main.py` boots: web on :8000, scheduler service started,
Telegram gateway up (real token), clean SIGTERM shutdown.

### DECISION: scheduler engine = plain asyncio loop
`core/scheduler_service.py` is a hand-rolled tick loop (wake event +
`settings.scheduler.tick_seconds` timeout), NOT apscheduler's scheduler
object — `due_jobs()` already owns claim semantics (try-advisory-lock +
FOR UPDATE SKIP LOCKED), so apscheduler would only be a timer. Cron
parsing/next-run math still uses apscheduler's `CronTrigger`
(`next_cron_run(schedule, tz, after)` — a pure, import-safe helper;
`tools/scheduler.py` imports ONLY that, never the running service).

### DECISION: claim = advance-before-execute, twice protected
- In-process: all ticks (loop, wake-driven, external/tests) serialize on an
  asyncio lock in the service. Found and fixed a real race: a wake-driven
  real-now tick could hold the due_jobs advisory try-lock when another tick
  ran, making that tick silently see nothing due.
- Cross-process: due_jobs' advisory try-lock + the CAS advance
  (`db.advance_job_fire` updates only if next_run_at still equals the
  claimed value). Crash between claim and run can't double-fire; startup
  catch-up collapses missed occurrences into exactly ONE fire because the
  advance computes from `now`, skipping the missed slots.

### DECISION: job outcome accounting rides task.finished
The orchestrator now publishes `parent_job_id` in `task.finished`;
the scheduler subscribes and adjusts `consecutive_failures` in
`state_json` (done ⇒ reset, anything else ⇒ +1). Watcher check failures
count directly (a check that can't run is a FAILED run, never a skip).
At `scheduler.max_consecutive_failures` (3): `active=false` + `notify.user`
to the OWNER only. Each job runs in its own asyncio task with a
task-timeout wall, so one user's failing job can't stall the loop.

### DECISION: watcher first observation fires
No `last_hash` in state = "changed" — a new watcher escalates once to give
the user an immediate baseline result, then goes quiet until the hash moves.
(Alternative considered — silently swallow the first run — rejected: the
user asked to be told what the thing looks like.)

### DECISION: run_skill risk is resolved per call
`tools/base.ToolSpec` gained an optional `risk_resolver(args)`; the wrapper
gate and the orchestrator's `can_use_tool` both gate on the resolved risk.
`run_skill` resolves the saved skill's declared risk (safe|moderate only —
`save_skill` refuses `high`); unresolvable ⇒ "moderate" (fail closed).
Approval is asked exactly once (the loop's `approvals_prechecked` dance is
unchanged).

### DECISION: skills/check-scripts live under skills/ on disk
`core/skills.py` owns `SKILLS_ROOT` (= `agent/skills/`, monkeypatchable in
tests): `skills/<user_id>/<skill>/` (skill.yaml + run.py and/or
instructions.md) and `skills/<user_id>/_checks/<job_id>.py`. Same
confinement rules as sandbox workspaces (charset-validated ids + realpath
prefix assertion). Playbook skills return their instructions to the model
wrapped as `<untrusted_content source="skill:...">`; code skills are
copied into the task workspace under `skill/<name>/` and executed via the
new `sandbox.run_files(task_id, files, entry, argv)` (service-level; model
never calls it).

### BUG FIXED (latent since Phase 1/2): jsonb double-encoding on write
`core/db.py` was pre-dumping jsonb params to strings (`_json(...) +
$N::jsonb`) while the Phase 2 pool-wide jsonb codec ALSO encodes — so
`jobs.state_json` and `approvals.details_json` were stored as JSON *string
scalars* and read back as `str`, not dict. Caught by the watcher tests
(`dict(fresh.state_json)` blew up). Fix: write paths now pass Python
objects and let the codec encode (`create_job`, `update_job`,
`record_approval`); `_json()` helper deleted. Phase 2's approval rows in
the dev DB are affected only cosmetically (details stored as strings).

### Other touches
- Migration `0004_scheduling_timezone.sql`: `users.timezone` (default UTC);
  cron evaluated per user via `zoneinfo` (bad tz ⇒ operator default).
  `db/schema.sql` regenerated.
- `events.JOB_CHANGED` added (user-scoped); scheduler subscribes and wakes
  its loop early; `tools/scheduler.py` publishes it after every mutation
  and never imports the service module's state.
- `main.py`: retention sweep moved INTO the scheduler service (hourly,
  alongside ticks); scheduler started/stopped with the service.
- Web settings page: Jobs list (pause/delete, CSRF'd) + Skills list (stats,
  needs_review) + timezone field; pause/delete 404 on foreign ids.
- System prompt: skills + jobs guidance (skills are per-owner; watchers
  should be cheap checks that escalate on change).

### ENVIRONMENT / LIMITATIONS (this machine — unchanged from Phase 2)
- **No Docker** ⇒ watcher check scripts and code-skill execution are
  faked in tests (`fake_sandbox` fixture) and will return actionable
  failures in prod until the sandbox image is built. Everything else
  (tenancy, hashing/quiet logic, auto-pause, catch-up, timezone math,
  risk resolution, web UI) is fully test-covered without Docker.
- Build the sandbox image once Docker exists:
  `docker build -t agent-sandbox:latest -f sandbox/Dockerfile .`

### Before Phase 4
- Nothing blocking. Operator note: the Anthropic account still has no API
  credits (Phase 2 blocker) — model calls fail until that's fixed, which
  also blocks seeing job-fired tasks run for real.

### How to verify Phase 3
```
cd agent && ../.venv/bin/python -m pytest -q     # 126 passed
../.venv/bin/ruff check .                        # clean
../.venv/bin/python main.py                      # boots, scheduler started
```

---

## Phase 2 — Core loop MVP (completed 2026-09-22)

**Status: DONE (with two environment-bound limitations, below).**
`pytest`: 89 passed. `ruff check`: clean. `python main.py` boots the real
service: web dashboard serves on :8000 (`/healthz` ok), Telegram gateway
auto-disables when the token is empty.

### DECISION: agent loop = Claude Agent SDK (verified against installed 0.2.157)
The SDK runs the Claude Code CLI (Node present: v23). Design:
- Our tools execute IN-PROCESS via `create_sdk_mcp_server` + the SDK `tool`
  decorator (claude-agent-sdk), so tools.base's wrapper (logging, truncation,
  error capture, untrusted-content tagging) still wraps every call.
- Built-in CLI tools (Bash/Read/Write/...) are disabled with
  `ClaudeAgentOptions(tools=[])` — the model can ONLY reach our registry.
  This is load-bearing for tenancy.
- Approvals gate in the loop's `can_use_tool` hook (per user, per mode);
  tools.base then skips its own gate via the `approvals_prechecked`
  contextvar so a single action is never asked for twice.
- Per-task `cwd` = the user's sandbox workspace and per-task
  `CLAUDE_CONFIG_DIR` inside it — CLI session transcripts/state stay inside
  the tenant's disk area, never on shared paths.
- `max_turns` = the source-dependent step cap; model from settings.models.
- Token/cost metering: ResultMessage usage → router._cost_usd → api_costs.

### DECISION: search provider — Brave first
`settings.yaml web.search_provider` selects brave | serpapi | google_pse;
only the Brave adapter is implemented (Phase 2), others raise a clear error.

### DECISION: link codes stored in DB (migration 0003)
SHA-256 hash + 10-min expiry + atomic single-use consume. Re-linking a chat
moves it to the new user (one owner per chat).

### DECISION: per-user settings/overrides (migration 0002)
`users.user_limits_json` (approval-rule overrides; plan-floored at check
time in core.approvals) and `users.settings_json` (quiet hours).

### DECISION: asyncpg jsonb/json codecs registered pool-wide
asyncpg returns jsonb as str without a codec — every pool connection now
decodes jsonb/json to Python objects. (Fixed a latent Phase 1 bug: jsonb
columns were silently str-typed until Phase 2 models required dicts.)

### BUGS CAUGHT BY THE PHASE 2 TESTS (worth remembering)
- PEP 563 (`from __future__ import annotations`) makes inspect.signature
  return string annotations — tool schemas must resolve via get_type_hints.
- Logging extras may not use reserved LogRecord keys ("args" crashed).
- FastAPI form CSRF must be read as a form field (templates can't send
  headers); caught by the web flow test.

### ENVIRONMENT / LIMITATIONS (this machine)
- **No Docker** → `run_code`/`install_package`/file tools return an
  actionable error ("install Docker Desktop or colima, then
  docker build -t agent-sandbox:latest -f sandbox/Dockerfile .") and
  Docker-dependent tests skip. Everything else (web, memory, notify,
  dashboards, approvals) is fully live. Sandbox path-tenancy logic is
  unit-tested without Docker.
- **torch segfaults under pytest** (threading interaction) but works fine
  standalone — verified the real embedding path loads all-MiniLM-L6-v2 and
  returns 384-dim vectors. Tests therefore use deterministic fake embedders;
  never let a test import torch.
- The real model loop needs `ANTHROPIC_API_KEY` in `.env` (`scripts/check_env.py`
  shows SET/MISSING without printing values). Telegram needs
  `TELEGRAM_BOT_TOKEN` + the user to link via Settings → Telegram.

### LIVE VALIDATION (2026-09-22, real keys in agent/.env)
- All four keys validated against live APIs: Anthropic (200), Brave (200,
  results returned), Telegram (bot @Keighobad_bot), Brevo (200).
- **BLOCKER: the Anthropic account has no API credits** — model calls return
  "credit balance is too low". Everything code-side is correct; the operator
  must add credits/payment method at console.anthropic.com (Part 0a #1).
- Model IDs corrected to real ones: planner/worker `claude-sonnet-5`,
  cheap `claude-haiku-4-5-20251001` (verified via /v1/models). Prices in
  settings.yaml are placeholders mirrored from 4-5/haiku rates — reconcile.
- `email.provider` is now `brevo` (the operator's EMAIL_API_KEY is a Brevo
  xkeysib key); Brevo adapter added to core/auth.py. **Verification emails
  will fail until `email.from_address` in settings.yaml is a sender verified
  in the Brevo account** (currently the placeholder agent@example.com).
- Live bugs found and fixed by real-API testing: Brave search must be
  GET (was POST) with `params=` (was form body); search metering must be
  awaited (fire-and-forget task raced shutdown and dropped the api_costs row).
- Live proof: web_search returned 3 real results; fetch_page extracted 20k
  chars, wrapped in untrusted_content; costs metered to the calling user
  ($0.005 search row in api_costs; usage summary $0.005 vs $10 free cap).

### Before Phase 3
- Build the sandbox image once Docker exists (command above) so run_code is
  real; the e2e harness then exercises it without mocks.

### How to verify Phase 2
```
cd agent && ../.venv/bin/python -m pytest -q   # 89 passed
../.venv/bin/python scripts/check_env.py       # which keys are set
../.venv/bin/python main.py                    # then open http://localhost:8000
```

---

## Phase 1 — Foundation & accounts (completed 2026-09-22)

**Status: DONE.** `pytest`: 34 passed. `scripts/smoke_phase1.py`: 19/19, exit 0.
`ruff check`: clean. Migrations apply idempotently.

### DECISION: DB driver — raw asyncpg
Spec allowed asyncpg *or* SQLAlchemy-async. Chose raw asyncpg: explicit SQL,
one less ORM abstraction over the tenant-scoping rule, pgvector codecs via
`pgvector.asyncpg.register_vector` on every new pool connection.

### DECISION: sessions — opaque tokens, hashed at rest
`secrets.token_urlsafe(32)`; only its SHA-256 is stored (`sessions.token_hash`),
30-day expiry. Revocation-friendly (a DB leak yields no usable tokens). PyJWT
stays in requirements per spec (unused in Phase 1; may serve later needs).

### DECISION: passwords — argon2id via passlib
Dummy-verify on unknown users so "no such user" and "wrong password" are
latency-indistinguishable.

### DECISION: verification/reset links — itsdangerous + server-tracked jti
HMAC-signed single-purpose tokens (24 h / 30 min TTL) PLUS a `jti` row in a
new `auth_tokens` table consumed atomically. This table is **beyond the
spec's table list** — added because "single-use" needs server state; the
spec explicitly requires reset links to be single-use. Reset also deletes
all of the user's sessions.

### DECISION: email sender — provider-agnostic, inside core/auth.py
Resend or Postmark JSON API, selected in `config/settings.yaml`
(`email.provider`), sender address in `email.from_address`. Kept in auth.py
(not a new core/email.py) to respect the spec's folder tree. Unit tests mock
`auth._send_email`.

### DECISION: `users.status` includes `email_unverified` from day one
Signup creates unverified accounts; login is blocked until verified. Spec's
Phase 1 "done when" demands verify → login.

### DECISION: `due_jobs(now)` — claim semantics
Advisory xact lock (`hashtext('core.db.due_jobs')`) + `FOR UPDATE SKIP
LOCKED`. It does NOT advance `next_run_at` itself — the Phase 3 scheduler
service (the documented cross-tenant caller) advances immediately after
claiming. Phase 3: wire croniter for the advance computation.

### DECISION: embeddings not installed in Phase 1
`settings.yaml` pins the plan (local `all-MiniLM-L6-v2`, 384 dims; pgvector
column ready), but sentence-transformers is NOT in requirements — the spec's
pinned list omits it and it drags in torch. **Phase 2 must add it** (or a
lighter embedding path) before memories work end-to-end. `search_memories`
accepts any 384-dim vector meanwhile (tests use synthetic vectors).

### DECISION: rate limiting — in-process
10 failed logins/hour per (email, ip) in a module dict. Fine for Phase 1
dev; **production must move this to Redis** (multi-process safe).

### DECISION: phase-1 smoke script resets the TEST schema
`scripts/smoke_phase1.py` drops/recreates `public` on TEST_DATABASE_URL
(default `postgresql://agent@localhost:5432/agent_test`) — refuses to touch
DATABASE_URL without `--i-know-this-wipes`.

### ENVIRONMENT (this machine)
- No Docker available. Dev Postgres 16.15 via Homebrew (`brew services start
  postgresql@16`), pgvector 0.8.6 **built from source** against @16 — the
  brew bottle only ships @17/@18 binaries. If the DB is missing after a
  reboot: `brew services start postgresql@16`.
- Role `agent` (superuser, trust auth on localhost), DBs `agent` (dev) and
  `agent_test` (tests/smoke). `.env` DSN: `postgresql://agent@localhost:5432/agent`.
- venv at repo root: `.venv/` — run things as
  `cd agent && ../.venv/bin/python -m pytest -q`.
- `db/schema.sql` is a generated pg_dump of the final schema (convenience
  only). **Migrations in `db/migrations/` are the source of truth.** If you
  add a migration, regenerate the dump.

### Known limitations / next steps
- passlib emits `crypt` DeprecationWarnings on Python 3.12 (removal in 3.13)
  — harmless now; revisit if Python is upgraded.
- Telegram/email/Anthropic credentials are empty in `.env`; Phase 2 needs
  `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `SEARCH_API_KEY`, and a real
  `EMAIL_API_KEY` before its end-to-end flows run for real.
- Login rate limiting and the event bus are in-process — revisited when
  `main.py` (Phase 2) and deployment (Phase 7) shape the process model.

### How to verify Phase 1
```
cd agent && ../.venv/bin/python -m pytest -q      # 34 passed
../.venv/bin/python scripts/smoke_phase1.py       # 19/19, exit 0
../.venv/bin/ruff check .                         # clean
```
