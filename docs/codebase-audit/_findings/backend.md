# Backend services & API audit (scope prefix BE)

Branch `product-phases-6-11`. READ-ONLY audit. Production is UNVERIFIED everywhere below unless stated. Uncommitted work in `tool_relay`, `lifecycle/*`, `cell_bridge` was not judged (other investigator).

## 1. Scope & method

Covered: `platform/accounts/` (urls, views, middleware, services, models, settings, 13 management commands, 15 Django migrations, test_*.py), `platform/migrations/*.sql` (30 files), `platform/openapi.json`, and every `agentai_platform/` module except `browse/`, `lifecycle/`, `chat_driver.py`, `tool_relay.py`. Also read `platform/deploy/*.service|*.timer|gunicorn.conf.py|caddy/Caddyfile.getlumina|accounts.env.example|README.md` where they bind to my scope.

Method and tools actually run (all non-mutating):
- Read in full: `accounts/{urls,views,middleware,services,models,api,settings,chat,files,streams,safety,vault,media,uishell,browse,signup,telegram,connections,lifecycle,requests,usage,billing}.py`, `agentai_platform/{request_queue,request_worker,billing,budget,switches,security,store,capacity,ssrf}.py`, `vault.py` (head), most of `chat.py` and `connectors.py`.
- AST import graph over `platform/` (stdlib `ast`, `python -I`) to find modules with zero non-test importers; then grep of docs/entry points for each (BE-014).
- `manage.py makemigrations --check --dry-run` using the repo `.venv` and a throwaway 0700 state dir in the scratchpad: "No changes detected" (models and Django migrations consistent).
- openapi.json vs urls.py diff by script; env var inventory by regex (`AGENTAI_*`) vs `accounts.env.example` / README / OPERATIONS / RUNBOOK / service units.
- Route-to-test mapping by literal string search over `accounts/test_*.py`, `accounts/tests.py`, `tests/*.py` (nominal coverage only, not assertion quality).
- `ruff`, `vulture`, `mypy` are not installed; no linter output used. No test was run.

NOT checked: production state (gunicorn flags actually running, Vercel rewrite behaviour, enabled systemd timers, Stripe payload sizes); internals of `gateway.py`, `events.py`, `artifacts.py`, `files.py` (service), `storage.py`, `genui/*` (HTTP surface and a skim only), `routing/*`, `ops/*` (only restore.py SQL building and the import graph).

## 2. File/module map

| path | responsibility | consumers / entry | notes |
|---|---|---|---|
| `accounts/settings.py` (134) | Django settings, ~40 `AGENTAI_*` env reads, fail-fast on bad secrets/origin/state-dir perms | gunicorn, manage.py | `DATA_UPLOAD_MAX_MEMORY_SIZE` set twice (BE-021); `LOGGING` sends `django` to NullHandler (BE-010) |
| `accounts/urls.py` (81) | Route table (dense one-liners, 4 `urlpatterns +=` blocks, 5 `insert(0,...)`) | ROOT_URLCONF | section 3a |
| `accounts/middleware.py` | `BoundaryMiddleware` (size caps, routing-override denial, security headers, request-id log), `AccountMiddleware` (identity epoch check, tenant resolve, per-request rate limit) | settings.MIDDLEWARE | BE-003, BE-004, BE-013 |
| `accounts/views.py` (329) | `endpoint()` decorator (method / CSRF-form / JSON field allowlist / error mapping), auth flows, projects, operator routes, disabled stubs | urls | central authn primitive `customer()` |
| `accounts/services.py` | audit, `rate()`, token issue/consume, `customer_scope`, `operator_scope`, revoke | views, signup, commands | |
| `accounts/models.py` | 7 Django models (Identity, ActionToken, OperatorGrant, Audit, RateBucket, Tombstone, EmailJob) | | all other tables are raw SQL from `platform/migrations/*.sql` |
| `accounts/lifecycle.py` | `AccountStore`: adapts the sqlite3-style `Store` API onto Django's connection; operations/provision/retry routes | everywhere | `?`->`%s` replace in `Queries.execute` (a literal `?` or `%` in SQL would break) |
| `accounts/chat.py` (344) | chat HTTP surface + `service()` factory for `ChatService` | urls, genui, request_worker cmd | only factory that wires pricer/gateway (BE-007) |
| `accounts/{requests,usage,api,media,streams,uishell}.py` | legacy request page, usage, bootstrap/csrf/presence, card images, task events + SSE, SPA bundle server | urls | `streams.stream` BE-002 |
| `accounts/{files,genui,browse,vault,safety,signup,telegram,connections,billing}.py` | HTTP layers over the matching `agentai_platform` services | urls | |
| `accounts/management/commands/*` (13) | section 3c | systemd / host operators | |
| `accounts/migrations/0000..0015` | Django migrations; 0000/0004/0008-0012 are shims that re-run `adopt()` of the SQL dir | `bootstrap_accounts` | BE-012 |
| `migrations/0001..0030_*.sql` | authoritative platform schema, checksummed in `schema_migrations`, applied by `Store.initialize()` | `bootstrap_accounts`, `server.py --migrate`, tests | editing any file breaks `Store.ready()` and `/readyz` |
| `openapi.json` (111 paths, v0.8.0) | API description | docs only | drift small (BE-016) |
| `agentai_platform/chat.py` (505) | `ChatService`: conversations, send/steer/goal, admission, blocks | accounts.chat, telegram, files | no function over 61 lines |
| `agentai_platform/request_queue.py` (292) | durable serial queue, leases, fences, park/defer/recover | accounts.*, request_worker | BE-001, BE-006, BE-009 |
| `agentai_platform/request_worker.py` | single-slot tick loop, reconcile, parked handling | `manage.py request_worker` (systemd) | |
| `agentai_platform/budget.py` | `BudgetLedger`: entitlements, reservations, receipts, settle | chat, driver, usage | BE-001 |
| `agentai_platform/billing.py` (683) | Stripe client, webhook inbox, access state machine, open-access sync | accounts.billing, billing_worker | cohesive; signature + idempotency look right |
| `agentai_platform/switches.py` | owner feature-switch catalog + file store (fail-closed) | everywhere via `SwitchStore(...).is_on` | re-read from disk per call (BE-020) |
| `agentai_platform/safety.py` | per-account/global protection toggles | services.rate, chat, queue | |
| `agentai_platform/connectors.py` (544) | OAuth link/PKCE/custody/drafts for Gmail, Calendar, Drive, GitHub | accounts.connections only | inert in prod (BE-008) |
| `agentai_platform/telegram.py` (362) | Telegram ingress/outbox | accounts.telegram, telegram_worker | BE-007 |
| `agentai_platform/{vault,ssrf,security,store,capacity,config,adapters,privacy,storage,artifacts,files,events,gateway,bridge_client,live/*,genui/*,routing/*,ops/*}` | support services | various | not individually deep-audited |
| orphan candidates | `durable, memory, optimization, policy_check, schedules, skills, watchers, genui/intent, ops/rotation` | tests only | BE-014 |
| `agentai_platform/server.py` | stdlib control server (`--service control|app --migrate`) | `agentai-platform-control.service` | separate from Django |

## 3. Features

### 3a. Complete route table (`accounts/urls.py`; every route passes `BoundaryMiddleware` then `AccountMiddleware`)

Auth key: **C** = `customer(request)` (login + verified identity + epoch + active account membership, else 401/404), **A** = anonymous, **O** = `operator_scope` (verified operator + confirmed TOTP device + unexpired per-account per-action grant), **O?** = owner account (`SAFETY_OWNER_ACCOUNT`) or granted by it. Tests = number of test files mentioning the path (string match only).

| route | view | auth | tests |
|---|---|---|---|
| `healthz`, `readyz` | views.health/ready | A | 3 / 5 |
| `/`, `account/`, `account/<page>/` | views.account_page (home needs C else redirect; other pages whitelisted) | A/C | via login tests |
| `account/ui[/]` | views.assets (static css) | A | 1 |
| `account/chat/` | chat.chat_page | C | 3 |
| `account/requests/` `account/usage/` `account/connections/` `account/billing/` | requests.page, usage(page), connections(page), billing(page) | C | 1-2 each |
| `auth/login` `auth/logout` `auth/mfa` `auth/revoke-sessions` | signin / signout / mfa / revoke_sessions | A / C / operator pre-MFA / C | 5 / - / 1 / 1 |
| `auth/recovery` `auth/reset` `auth/activate` | recovery, finish(recovery), finish(onboarding) | A, rate limited, uniform reply | 1 |
| `auth/signup` `auth/signup/verify` `v1/signup/config` | signup.signup/verify/config | A (switch `open_signups`, honeypot, rate) | 1 |
| `v1/me` `v1/csrf` `v1/app` `v1/assistant/presence` | views.me, api.csrf (A), api.app, api.presence | C | 5 / 1 / 1 / 1 |
| `v1/projects[/<id>]` | views.projects | C | 7 |
| `v1/projects/<id>/files` (GET list, POST upload), `/files/<id>/preview`, `/bundle` | files.files_route/preview/bundle (plain views, not `endpoint`) | C + storage ready (+ UPLOADS_ENABLED) | 2 / - / 1 |
| `v1/artifacts/<id>/versions/<v>/ticket` | files.ticket | C | 4 |
| `v1/artifacts/<id>/versions/<v>/download` | files.download (csrf_exempt GET) | single-use signed ticket only, no session | 2 |
| `v1/genui/artifacts/<id>/asset` | files.gen_asset | C; file must be referenced by the caller's own document | 1 |
| `v1/costs`, `v1/operations[/<id>]` | usage.usage, lifecycle.operations | C | 2 / 2 |
| `v1/requests[/<id>]`, `/cancel` | requests.requests / cancel | C (+ `task.create` 30/h) | 3 |
| `v1/requests/<id>/pause|resume|retry`, `v1/tasks/<id>`, `v1/tasks/<id>/cancel` | chat.chat_pause/resume/retry/task/cancel | C | 1-5 |
| `v1/tasks/<id>/events`, `/stream` | streams.events, streams.stream (SSE) | C | 2 |
| `v1/conversations[/<id>]` + `/messages /send /archive /restore /rename /goal /blocks` | chat.*, genui.blocks | C | 1-3 each |
| `v1/blocks/<id>/state|submit|launch|live|phase|stop` | genui.* | C (+ per-scope rate) | 1 |
| `v1/genui/registry`, `v1/genui/artifacts/<id>/state|events|update|diagnostics` | genui.* | C | 1 |
| `v1/media/<id>` | media.card_image | C, owner-scoped hash id | 1 |
| `v1/browse[/<id>]` + `/control /release /pause /resume /answer /live /shot/<name>`, `v1/saved`, `v1/saved/<field>/forget` | browse.* | C; each calls `_run()` (account-scoped lookup) | 1 |
| `v1/vault`, `v1/vault/add`, `v1/vault/<id>/delete` | vault.* | C (+ key file) | 2 |
| `v1/safety`, `/change`, `/access`, `/access/change` | safety.* | O?; changes need password re-entry | 1 |
| `v1/account/telegram[/link|/unlink]` | telegram.bindings/link/unlink | C | 1 |
| `v1/telegram/webhook` | telegram.webhook (csrf_exempt) | shared secret header, `hmac.compare_digest` | 1 |
| `v1/account/connections[/link|/callback|/disconnect]`, `v1/account/drafts` | connections.* | C (+ switch for link) | 2 / 1 |
| `v1/account/billing[/checkout|/portal]` | billing.* | C (+ switch `billing_checkout`) | 2 |
| `v1/billing/webhook` | billing.webhook (csrf_exempt) | Stripe signature over raw body, 300 s tolerance | 2 |
| `app/`, `app/<path>` | uishell.serve (static SPA bundle, own CSP, path containment checked) | A | 1 |
| `v1/streams|exports|memory|schedules|integrations|controls[/<id>[/<action>]]`, `v1/tasks` | views.disabled -> 503 `capability_not_enabled` (ownership check first for known kinds) | C | - |
| `internal/accounts/<a>/invite|revoke|suspend|audit` | views.invite/operator_revoke/suspend/operator_audit | O | 3 |
| `internal/accounts/<a>/deployment/operations[/<id>/retry]` | lifecycle.provision/retry | O (`lifecycle_<kind>` grant) | 1 |
| `internal/accounts/<a>/export|impersonate` | views.forbidden_support -> always 403 | - | - |

Tenant isolation result: every customer route derives `account_id` from the session (`customer_scope`: verified identity + epoch + active membership + active account), never from the request. `BoundaryMiddleware` rejects `account`, `tenant`, `session`, `deployment_id` query keys and `X-Account-Id`-style headers (400). Services re-authorize via `Store._authorize` and scope every SQL by `account_id`. No IDOR found in the routes read. Denials are a uniform 404 and audited.

### 3b. Feature list

| ID | name | status | flags | frontend | backend | evidence | prod? | notes |
|---|---|---|---|---|---|---|---|---|
| FEAT-BE-01 | Auth: login/logout/recovery/activate/revoke, epoch session invalidation | ACTIVE | - | `/auth/login,/logout` used by lumina | views.py, services.py | `views.py:132-149`, `middleware.py:60-70` | unknown | solid; operators need TOTP |
| FEAT-BE-02 | Self-signup with owner approval | ACTIVE (switch `open_signups`) | owner-gated | `/auth/signup`, `/v1/signup/config` | signup.py, `signup_admin` | `signup.py:107-150` | unknown | owner mail goes to noreply (BE-018) |
| FEAT-BE-03 | Chat conversations / send / steer / goal | ACTIVE | switch `customer_execution` | Chat.tsx | chat.py (both layers), request_worker | `accounts/chat.py:131`, request-worker unit | unknown | |
| FEAT-BE-04 | Serial request queue + worker (one global running slot) | ACTIVE | design limit (BE-013) | `/v1/requests` | request_queue.py, request_worker.py | `agentai-request-worker.service:11` | unknown | leak BE-001 |
| FEAT-BE-05 | Budget ledger / plan limits | ACTIVE | - | `/v1/costs` | budget.py | `chat.py:339`, `request_worker.py:55` | unknown | BE-001, BE-006 |
| FEAT-BE-06 | Stripe billing (checkout, portal, webhook inbox, sweep) | ACTIVE in test mode behind `billing_checkout` | owner-gated; no React UI | none in `lumina/src` (server-rendered `/account/billing/`) | billing.py, billing_worker | `agentai-billing-worker.timer` 30 s | unknown | BE-004, BE-005 |
| FEAT-BE-07 | Open (free) access entitlement sync | ACTIVE | switch `open_access` | - | `billing.sync_open_access` | billing_worker `handle` | unknown | |
| FEAT-BE-08 | Files / artifacts / signed downloads | ACTIVE if `AGENTAI_STORAGE_DIR` set | uploads need `UPLOADS_ENABLED` | Files.tsx | files.py | urls | unknown | BE-019 |
| FEAT-BE-09 | Generative UI blocks/artifacts | ACTIVE | - | `/v1/blocks`, `/v1/genui/*` | accounts/genui.py, genui/* | urls | unknown | not deep-audited |
| FEAT-BE-10 | Browse run control / live view (HTTP layer) | ACTIVE | switch `browse_tasks` | `/v1/browse/*` | accounts/browse.py | urls | unknown | `answer/pause/resume/release` and `/v1/saved*` have no React caller found |
| FEAT-BE-11 | Vault (saved logins/cards) | INCOMPLETE | needs key file; `credentialed_browsing` switch needs `login_flow` fact ("not yet") | none in `lumina/src` | vault.py both layers | switch catalog | unknown | AES-GCM, per-account HKDF key, AAD-bound rows |
| FEAT-BE-12 | Safety menu | ACTIVE | owner/granted only | `/v1/safety*` | safety.py | | unknown | |
| FEAT-BE-13 | Telegram ingress/outbox | INCOMPLETE / BROKEN in prod wiring | `TELEGRAM_ENABLED` | no UI in React | telegram.py | BE-007 | unknown | |
| FEAT-BE-14 | Connectors (OAuth, custody, drafts) | INCOMPLETE | switch `connectors_linking` needs unmet facts | `/v1/account/connections` list only | connectors.py, connections.py | BE-008 | unknown | preserve (C) |
| FEAT-BE-15 | Operator HTTP API (`/internal/accounts/*`) | ORPHANED-by-config | MFA + grants | none | views.py, lifecycle.py | Caddy routes only `/account /auth /v1 /app` (`Caddyfile.getlumina:20`) | unknown | loopback only; host CLI `account_admin` is the working operator path (C) |
| FEAT-BE-16 | Disabled stubs `/v1/streams|exports|memory|schedules|integrations|controls`, `/v1/tasks` list | INCOMPLETE | all 503 | Automations page copy only | views.disabled | `urls.py:27-29` | n/a | in openapi; preserve (G) |
| FEAT-BE-17 | Durable objectives, memory, skills, watchers, schedules, optimization, policy_check | ORPHANED (tests only) | locked switches | none | modules + tables | BE-014 | n/a | preserve until decision (C) |
| FEAT-BE-18 | SSE task stream | BROKEN-by-config / unused | - | not used (React polls `/v1/tasks/:id/events`) | streams.stream | BE-002 | unknown | |
| FEAT-BE-19 | JEV routing shadow / display decider | ACTIVE behind switches `jev_routing`, `jev_display` (off by default) | owner-gated | - | routing/*, wired in request_worker cmd | `request_worker.py:36-45` | unknown | sends redacted text to TypeSafe when on |

### 3c. Management commands

| command | run by | notes |
|---|---|---|
| `request_worker` | `agentai-request-worker.service` | long-running loop |
| `billing_worker` | `agentai-billing-worker.timer` (30 s) | unit has no `--reconcile` (BE-005) |
| `deliver_account_mail` | `agentai-platform-mail.timer` (60 s) | |
| `tool_relay` | `agentai-tool-relay.service` | other investigator |
| `retention_accounts` | nothing in repo | `deploy/README.md:83-85`: "No schedule/worker was installed this phase" (BE-011) |
| `telegram_worker --drain/--check` | nothing in repo | BE-007 |
| `bootstrap_accounts` | `deploy/release.py:116` (canary + live migrate) | = `Store.initialize()` + `migrate` |
| `account_admin`, `signup_admin`, `onboard_trial`, `seed_trial`, `lifecycle_status` | host operators by hand (RUNBOOK, OPERATIONS, tests reference them) | manual, not orphaned |
| `verify_interactive_ui` | docs/generative-ui only | manual verification tool |

## 4. Findings

- **ID**: BE-001 | **Category**: money/budget correctness, availability | **Severity**: High | **Confidence**: MEDIUM-HIGH | **Effort**: M
  - A reservation (default $1 = `CUSTOMER_RESERVATION_MICROUSD`) is created at send time (`ChatService.send` -> `BudgetLedger.admit`, `chat.py:337-345`, `budget.py:68-91`) and settled only in `ChatDriver._close` (`chat_driver.py:788-792`), i.e. only for a request that was claimed and ran. `RequestQueue.cancel` of a `waiting` request (`request_queue.py:112`), the revoked-author path in `claim` (`:164`) and `request_worker._tick` "failed_unfunded" never touch `task_reservations` or `tasks`. The reservation stays `active` and `tasks.state` stays `queued` forever.
  - Runtime impact: `_holds()` (`budget.py:53-58`) counts it against the account's period/daily limits and the service-wide allocation (`SERVICE_ALLOCATION_MICROUSD` default $50, so 50 leaks exhaust it for everyone). `max_queued_tasks=3` counts `tasks.state='queued'` (`budget.py:79`), so three cancels of waiting tasks (easy: pause/stop while the cell wakes) leave the account at "queue full". Only `ops/restore.py:154-157` closes stale reservations.
  - Evidence: `rg "task_reservations|tasks SET"` shows no other writer; no SQL trigger touches these tables; `tests/test_request_queue.py:42-47` tests cancel of a waiting task but asserts nothing about the reservation.
  - Action: F. Release reservation and set task `cancelled` inside `RequestQueue.cancel`, the revoked path and unfunded failure, plus a sweep for `active` reservations whose request is terminal. Risk: money-critical, needs `_holds` tests.

- **ID**: BE-002 | **Category**: availability / DoS | **Severity**: High | **Confidence**: MEDIUM (repo config verified, prod flags unverified) | **Effort**: S-M
  - `deploy/gunicorn.conf.py`: `workers=1, worker_class='sync', threads=1, timeout=15, backlog=16`; Caddyfile comments call it "the web app's single worker". `streams.stream` (`accounts/streams.py:60-121`) is an authenticated SSE generator that sleeps in a loop for up to 45 s. One customer opening `/v1/tasks/<id>/stream` blocks the only worker and gunicorn kills it at 15 s, dropping in-flight requests; the "3 streams per account" cap never applies because requests are serialized.
  - The React app does not use the route (it polls `/v1/tasks/:id/events`), so it is pure attack surface. Independently, one sync worker plus SQLite serializes all customers' polling.
  - Action: F/E. Remove or isolate `/stream`; revisit worker model after checking SQLite write contention (BE-013).

- **ID**: BE-003 | **Category**: security / abuse controls | **Severity**: High | **Confidence**: MEDIUM (depends on Vercel rewrite behaviour; UNVERIFIED) | **Effort**: S
  - Customer path per `deploy/vercel/routing.mjs:21-23` and `Caddyfile.getlumina:1-5`: browser -> Vercel rewrite -> `backend.getlumina.pro` (Caddy) -> gunicorn. Caddy sets `X-AgentAI-Client-IP {remote_host}` and `X-Forwarded-For {remote_host}` (`Caddyfile.getlumina:24-25`), overwriting what Vercel sent. `BoundaryMiddleware` trusts that header (`middleware.py:14-19`). If Vercel is the peer, `request.client_ip` is a Vercel egress address shared by all visitors, so `login.ip` 30/15 min, `ingress.anonymous` 120/min, `signup.ip` 5/h, `recovery.ip`, `token.ip` are global buckets.
  - Impact: five signups per hour site-wide, or a few failed logins by anyone, lock everyone out; per-IP brute-force protection is meaningless (per-email `auth.pair` still works).
  - Action: F. Derive the real client IP at Caddy from Vercel's forwarded header (trust only Vercel ranges or a shared secret header) or document limits as per-email only.

- **ID**: BE-004 | **Category**: contract bug (webhook ingress) | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: S
  - `BoundaryMiddleware` answers 413 for any `Content-Length > 8192` unless the path is `/v1/requests` or ends in `/send` or `/files` (`middleware.py:23`). `/v1/billing/webhook` and `/v1/telegram/webhook` fall under 8192 while the billing code itself allows `MAX_BODY=262144` (`billing.py:34`, `accounts/billing.py:153`). Stripe subscription/invoice events with nested objects can exceed 8 KB (not measured). A 413 makes Stripe retry then disable the endpoint, and nothing is recorded.
  - Evidence: no test pushes a >8 KB webhook through the full middleware stack (searched `accounts/test_billing.py`).
  - Action: D. Exempt the two webhook paths from the 8192 cap (they validate size themselves). Risk: low.

- **ID**: BE-005 | **Category**: reliability | **Severity**: Medium | **Confidence**: HIGH (unit text); prod unverified | **Effort**: S
  - `billing_worker` supports `--reconcile` (compares each subscription with Stripe and repairs drift) but `agentai-billing-worker.service:11` runs it without the flag and no other timer exists. Dropped or dead-lettered events (including BE-004) are never repaired; `overview()` just reports a `dead_letters` count.
  - Action: D/F. Add a daily reconcile timer.

- **ID**: BE-006 | **Category**: race condition | **Severity**: Medium | **Confidence**: LOW-MEDIUM | **Effort**: M
  - `ChatService.send` commits `queue.submit` (state `waiting`, claimable at once), then inserts the chat message, then calls `ledger.admit` in a separate transaction (`chat.py:313-345`). If the 3 s worker tick claims the request in that window, `request_worker._tick` finds no active reservation and fails it as "could not be funded" (`request_worker.py:56-64`); `admit` then succeeds for a finished request and creates an orphan reservation and `queued` task (compounds BE-001). Window is milliseconds but widens under SQLite lock waits (`timeout: 5`).
  - Action: F. Insert the request paused (or `admitting`) and flip to `waiting` inside the admit transaction.

- **ID**: BE-007 | **Category**: broken integration / incomplete feature | **Severity**: Medium | **Confidence**: MEDIUM-HIGH | **Effort**: M
  - Telegram messages cannot complete in production: (1) `accounts/telegram.service()` and `telegram_worker` build `ChatService(...)` without `pricer`, `gateway_factory` or a service limit (`accounts/telegram.py:26-31`, `telegram_worker.py:20-21`), so `UnmeasuredRoute` raises `CapabilityUnavailable`, the request waits unfunded and the worker fails it; only tests inject `FixedRoute` (`tests/test_telegram.py:43`, `accounts/test_telegram.py:60`). Contrast `accounts/chat.service()`. (2) Nothing relays the assistant's result to Telegram (`rg telegram agentai_platform/chat_driver.py` = 0 hits). (3) `telegram_worker --drain` has no unit. `/v1/account/telegram*` has no React caller.
  - Root cause is duplication (see BE-024): the `ChatService` factory is re-implemented in `accounts/{chat,telegram,files,views.projects}` and `telegram_worker`.
  - Action: C (finish or hide Telegram), B (single factory), D.

- **ID**: BE-008 | **Category**: incomplete OAuth | **Severity**: Low | **Confidence**: HIGH | **Effort**: L
  - `ConnectorService(store)` is built with no providers and `DisabledCustody` (`accounts/connections.py:29-30`), so link always answers 503. Even with providers, `link()` discards `begin_link`'s `authorize_url` and returns `connector_not_configured` (`connections.py:47-61`), `callback` is a stub (`:67-73`), and the callback URL is hard-coded to `https://getlumina.pro` rather than `PUBLIC_ORIGIN`. `ssrf.check_url` resolves but does not pin the address (its docstring admits this); matters only once connectors go live. Switch `connectors_linking` needs unmet facts.
  - Action: C (preserve: tokens-in-custody design is good), D when the product commits.

- **ID**: BE-009 | **Category**: queue semantics | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: S
  - `request_worker._settle_uncertain` abandons a request when `now - created_epoch > abandon_after (1800 s)` (`request_worker.py:84-92`). `created_epoch` is when the request was created, not when it became uncertain. A request that waited 30 min behind the single slot and then hit one transient reconcile failure (`CapabilityUnavailable`/`Conflict` are swallowed) is abandoned on the first tick, declaring a possibly still-running native run finished.
  - Action: F. Track `uncertain_since`.

- **ID**: BE-010 | **Category**: observability / swallowed exceptions | **Severity**: Medium | **Confidence**: HIGH | **Effort**: M
  - `settings.LOGGING` routes the `django` logger to `NullHandler`; `failed()` returns a generic 503; `BoundaryMiddleware` logs only `{request_id,status}`. Unhandled view exceptions leave no trace of class or location. The worker loop prints only `{'error': type(exc).__name__}` (`management/commands/request_worker.py`). `RequestWorker.tick` swallows all plan-runner/goal exceptions with bare `pass` (`request_worker.py:42-43`), as do `ChatService._announce_queued` (`chat.py:360`), `_pause_goal` (`:482`), `PlanRunner._audit` and cancel loop (`genui/runner.py:157,225`). No structured logger exists; ~19 files use ad-hoc `print(json.dumps(...))`; `security.log_request` is used only by `server.py`. The privacy posture (no URL/body in logs) is intentional, but an allowlisted `{event, exception_class, module, request_id}` record fits it.
  - Action: C/F. Risk: must never include customer text.

- **ID**: BE-011 | **Category**: retention / privacy | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: S-M
  - `retention_accounts` is the only code deleting `RateBucket`, expired `Session`, `ActionToken`, 180-day audit rows and 30-day `events`, and nothing schedules it in the repo. Rate buckets are written on every authenticated request, so the table grows without bound unless a host cron exists (unverified). The command help promises "90-day product chat projection retention" but it only tombstones old conversations and deletes their `events`; `chat_messages`/`conversations` rows are never deleted, and the 90-day cutoff uses `conversations.created_at`, so events of a still-active old conversation are removed.
  - Action: F + C (decide the real retention contract; privacy is an owner priority).

- **ID**: BE-012 | **Category**: schema/migration architecture | **Severity**: Low | **Confidence**: HIGH | **Effort**: M
  - Two migration systems: 30 checksummed SQL files (`Store.initialize`) and Django migrations, where 0000/0004/0008-0012 are copies of a shim re-running the SQL adopter. `safety_overrides` and `safety_access` exist only in Django migrations 0014/0015, not in `migrations/*.sql`, so `Store(path).initialize()` (used by ~10 test modules and `server.py --migrate`) yields a DB without them, and `services._rate_limits_off` hides the resulting error behind `except Exception: return False`. `makemigrations --check` is clean (models match Django migrations).
  - Action: E. Pick one source of truth; at least move the two safety tables into SQL.

- **ID**: BE-013 | **Category**: scalability / design limit | **Severity**: Medium | **Confidence**: HIGH (design), impact unverified | **Effort**: L
  - Global single running slot (`request_slot` id=1, `RequestQueue.claim`) serializes every customer's runs (documented in `SERIAL_REQUESTS.md`). Separately `AccountMiddleware` calls `rate()` on every authenticated request (`middleware.py:63-69`): a `safety_overrides` SELECT plus `get_or_create` + `save` inside `atomic()` under `transaction_mode='IMMEDIATE'`, so each GET takes the SQLite write lock. With one sync worker (BE-002) this is the throughput ceiling. Product decision, not a bug.
  - Action: C/E. Count reads in memory or only meter mutations.

- **ID**: BE-014 | **Category**: dead/orphaned code | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S (decision)
  - Zero non-test importers by AST import graph: `durable.py`, `memory.py`, `optimization.py`, `policy_check.py`, `schedules.py`, `skills.py`, `watchers.py`, `genui/intent.py`, `ops/rotation.py` (I found no CLI hook for it). Checked and cleared: `ops/probe_models.py`, `routing/bench.py` (`python -m` CLIs), `routing/report_cli.py` (called by `dashboard/app.py:1305`), `ops/cli.py` and `server.py` (systemd entries). They have tables (SQL 0010/0012...), tests and locked switches (`customer_schedules`, `research/browser_optimization`); `docs/orchestration-audit/02-path-registry.md:184-190` reached the same conclusion. Not deletion candidates until the maintainer decides (C/G).

- **ID**: BE-015 | **Category**: config debt | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  - `accounts.env.example` documents 8 variables; code reads 42 `AGENTAI_*` names. 23 appear in none of the example env, service units, README, OPERATIONS or RUNBOOK (all seven `AGENTAI_BILLING_*`, `AGENTAI_TELEGRAM_BOT_TOKEN/WEBHOOK_SECRET/BOT_USERNAME`, `AGENTAI_CELL_BRIDGE_SOCKET`, `AGENTAI_BROWSE_SOCKET`, `AGENTAI_UI_BUNDLE_DIR`, `AGENTAI_GOAL_CHAIN_LIMIT`, `AGENTAI_TOOL_RELAY_BIND`, `AGENTAI_LIVE_*`, `AGENTAI_ROUTING_CONFIG_FILE`, `AGENTAI_TYPESAFE_KEY_FILE`, `AGENTAI_SIGNUP_SETTINGS_FILE`, ...), though some are in `platform/BILLING.md` or `docs/orchestration-audit/07-registries.md`. Reverse: `AGENTAI_CARD_IMAGES` and `AGENTAI_BRAVE_IMAGE_KEY_FILE` are documented (OPERATIONS.md:198, RELEASE_NOTES.md:193) but read by no code. The app's `AGENTAI_SWITCHES_FILE` / `AGENTAI_STORAGE_DIR` are absent from `accounts.env.example`.
  - Action: A/G. Generate the example from `settings.py`.

- **ID**: BE-016 | **Category**: doc/contract drift | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  - openapi.json vs urls.py (script): all 111 documented paths exist (the six disabled kinds come from a loop in urls.py); only `internal/.../export|impersonate` are routed but undocumented (always 403). No routed customer path is missing. Value drift: `readyz` hard-codes `customer_ready:false, execution_enabled:false` (`views.py:108-109`), `signin` returns `execution_enabled:false` (`:149`), `provision` returns `runtime_enabled:false`, though execution can be live; openapi `info.version` 0.8.0 vs `api.API_VERSION '2026-10-13'`. No test gates openapi against urls.
  - Action: B/D. Add a route-vs-openapi test; make the flags real.

- **ID**: BE-017 | **Category**: authz/limit consistency | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  - The `task.create` hourly cap is applied in `requests`, `chat_goal`, `chat_retry` but not `chat_send` (`accounts/chat.py:158-182`), the main path. Remaining guards: `api.mutate` 30/min, queue limit 3, daily budget. Steered sends (to a running task) skip queue and budget.
  - Action: F.

- **ID**: BE-018 | **Category**: bug (low) | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  - `signup.verify` sends the "new sign-up waiting for approval" notice to `settings.DEFAULT_FROM_EMAIL` (`signup.py:152`), the no-reply sender (default `noreply@localhost`; mail activation rejects `@localhost`). No owner-address setting exists, so the notice likely lands nowhere useful. Unverified in prod.
  - Action: D. Add an owner-address variable.

- **ID**: BE-019 | **Category**: input handling | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  - Uploads read the whole file (`item.read()`) before the size check, and the 10 MiB limit applies only while the `upload_limits` switch is on (`files.py:97-101`). `download` builds `Content-Disposition` by stripping only `"` (`files.py:155`) while `gen_asset` uses Django's `content_disposition_header`; non-ASCII names are mishandled and CR/LF would make Django raise (500). The ticket is consumed on GET, so link prefetchers can burn it.
  - Action: F.

- **ID**: BE-020 | **Category**: performance hygiene | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  - `SwitchStore(...).is_on` re-reads JSON file(s) on every call; handlers construct several (`api.features()`, `access_mode()`, `accounts/chat.service()` builds a full `ChatService` incl. two switch reads and a `Coordinator`, and some views call `service()` repeatedly, e.g. `chat_cancel` twice). Fail-closed re-read is deliberate; cost is small but on every poll.

- **ID**: BE-021 | **Category**: config hygiene | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  - `DATA_UPLOAD_MAX_MEMORY_SIZE` is assigned twice (200000 at `settings.py:61`, then 31457280 at `:101`); the first is dead. The real body cap is `BoundaryMiddleware`, which whitelists by path suffix (`/send`, `/files`), so any route ending in those segments gets a 30 MB limit.

- **ID**: BE-022 | **Category**: test coverage vs churn | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: M
  - Highest 6-week churn in scope: `agentai_platform/chat.py` (23 commits), `urls.py` (16), `openapi.json` (14), `accounts/chat.py` (13), `settings.py` (12), `switches.py` (10), `request_queue.py` (10), `request_worker` command (10). All have test files. Gaps: no middleware-level test of size caps vs webhooks (BE-004); no test of reservation release on waiting cancel (BE-001); `build_worker` wiring in the `request_worker` command is untested; Telegram tests inject a pricer production never uses (BE-007); `tests/test_genui.py:339-350` comments still say "0027" though migrations reach 0030 (cosmetic). Skips found are environment guards only (Chrome, age, OpenClaw, SO_PEERCRED).

- **ID**: BE-023 | **Category**: doc drift | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  - `agentai_platform/vault.py` header says the master key is in a "root-only file", but `Keyring.from_file` requires mode 0600 and the unprivileged app process must read it, so it has to be app-owned. `accounts/chat.py` docstring says execution "stays disabled until the host connects a probed gateway", but it is now switch-driven.

- **ID**: BE-024 | **Category**: duplication / god files | **Severity**: Low | **Confidence**: HIGH | **Effort**: M
  - The `AccountStore(connection.settings_dict['NAME'])` + service wiring is repeated in ~12 view modules; the `denied = customer(request); if denied: return denied` preamble and `rate('task.create',...)` calls are copy-pasted in 80+ views; a decorator would remove both and the class of omission in BE-017. God-file check: `billing.py` (683), `connectors.py` (544), `chat.py` (505) exceed 500 lines but are cohesive; longest function is 91 lines (`ops/restore.py:restore_account`). Not worth splitting now.
  - Action: B.

## 5. Looks bad but is fine

1. SQL built with f-strings (`views.py:281`, `memory.py:83`, `chat_driver.py:117`, `ops/restore.py`): table names come from a fixed dict or constant `SCOPE` lists; values are always parameterized. Grep for concatenated `execute()` found no user-controlled interpolation.
2. `AccountMiddleware.process_exception` and `endpoint()` both swallow `Denied` and answer 404: intentional uniform "unavailable" to prevent account enumeration; each denial is audited.
3. Many `*_on()` switch helpers and hard-coded 503s (`connections.callback`, `disabled`): fail-closed by design, features are gated off, not broken (BE-008's discarded `authorize_url` is the only latent defect).
4. `billing.py` reads the Stripe key from a file on every call and builds `BillingService` per request: deliberate so rotation needs no restart. Webhook verification (raw-body HMAC, multi-secret overlap, v0 ignored, 300 s tolerance, dedup inbox, canonical re-fetch, backoff to dead-letter) and checkout/portal `Idempotency-Key` use look correct.
5. The six near-identical Django migration shims (0000, 0004, 0008-0012): ugly but idempotent (checksum-verified, skip applied files).
6. `/internal/accounts/*` operator routes exist but Caddy does not forward them: not an exposure; they additionally require TOTP and per-account grants.
7. `_rate_limits_off` catches every exception and returns "limits stay on": fail closed; the Safety menu is unreachable unless `SAFETY_OWNER_ACCOUNT` is set.

## 6. Cross-scope links

- Deploy/Caddy/Vercel: BE-003 (client IP through `deploy/vercel/routing.mjs` rewrite then Caddy overwrite); BE-002 (gunicorn single sync worker); BE-005 (billing timer lacks `--reconcile`); BE-011 (no retention timer); no Telegram drain unit.
- Frontend (`lumina/src`): no callers found for `/v1/account/billing*`, `/v1/account/telegram*`, `/v1/vault*`, `/v1/saved*`, `/v1/media`, `/v1/assistant/presence`, `/v1/me`, `/v1/operations`, `/v1/genui/registry`, `/v1/tasks/:id/stream`, `/v1/browse/:id/{pause,resume,release,answer}`. `lumina/src/gen/safety.ts:44` default base `/v1/files/content?path=` is not a backend route (real: `/v1/genui/artifacts/:id/asset`); callers presumably pass `base` (not verified).
- `chat_driver.py` (other investigator) is the only reservation settler (`:788-792`); fixing BE-001 needs coordination with it. `lifecycle.coordinator` / `lifecycle.types.Conflict` are used throughout this scope.
- `browse/service` (other investigator): `/v1/browse/<id>/control` forwards customer-typed `goto` URLs (up to 2048 chars) over the socket; URL/SSRF policy is that service's responsibility.
- `dashboard/app.py` calls `routing.report_cli`; `bin/activate-telegram.py` registers the Telegram webhook only.

## 7. Open questions for the maintainer

1. Is the Vercel rewrite to Caddy the live customer path, and does the real client IP survive it (BE-003)? Which gunicorn flags run in production?
2. Is `/v1/tasks/<id>/stream` meant to ship (BE-002)? Does any client use it?
3. Does an out-of-repo cron run `retention_accounts`, and is `billing_worker --reconcile` scheduled? What is the intended retention for `chat_messages` (BE-011)?
4. Should Telegram ship (needs shared pricer wiring, result relay, drain unit) or be hidden (BE-007)? Same question for connector OAuth and the vault UI.
5. Is the single global running slot a permanent constraint or a stage-1 limit (BE-013)?
6. Should reservations of cancelled waiting tasks be released synchronously or swept (BE-001)? Has any production account shown "queue full" after cancelling?
7. Which of `durable/memory/skills/watchers/schedules/optimization/policy_check` are roadmap and which removable?
