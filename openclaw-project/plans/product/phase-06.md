# Phase 6 — projects, conversations and dashboard chat

Status: **build READY for the local contract flow; live native chat remains
gated** (acceptance NOT_RUN, deferred to Phase 15/17 by plan). Owner Gateway
and owner runtime untouched; no customer invitation, live deployment change,
or paid provider call occurred.

Deployed 2026-10-05: release `20261005T185900Z-chat` is live on the existing
VPS behind getlumina.pro (`/account/chat/` returns the execution-disabled chat
page; sends wait). See `plans/product/chat-release-deployment.json` and
`evidence/product/phase-06/20261005T185900Z-deployment/`.

## Implemented this phase

- Migration SQL0005 + Django0009: `chat_messages` (durable transcript,
  provenance customer/agent/system, native-identity uniqueness),
  `chat_deliveries` (per-attempt native delivery state) and
  `customer_requests.conversation_id`. Fresh bootstrap applies 0001–0005; the
  adopt pattern applies only new files to existing databases.
- Gateway adapter `agentai_platform/gateway.py`: recorded session-control
  contract for `chat.send`/`chat.history`/`chat.abort` (protocol version 3),
  ack-versus-transcript-persistence semantics, `deltaCursor` reconnect,
  `runId`-scoped abort, `negotiate()` fail-closed on unprobed/unsupported
  versions, host-resolved `GatewayBinding` (no browser-supplied URL/token/RPC/
  session key), `HttpGateway` transport seam and `SyntheticGateway` fixture.
- Chat service `agentai_platform/chat.py`: project create (plan cap 10),
  conversation create (10/project, own deployment), admission-gated send
  through the Phase 5 ledger and serial queue (idempotent by key, budget
  refusal cancels the waiting request and answers `402 budget_denied`),
  transcript cursor reads, scoped task state, cancel (immediate while
  waiting; intent while running), and the trusted `ChatDriver` sequence:
  recheck authorization/reservation post-claim, record delivery attempt,
  resolve/create native session, send/ack, absorb transcript by native
  message identity, abort on intent (unsupported abort stays recorded intent,
  task uncertain), settle budget before the global slot handoff, reconcile
  unknown outcomes by receipts without resend.
- HTTP surface `accounts/chat.py` + `account/chat/` page: conversations,
  messages, send, task read/cancel APIs and a script-free escaped page with
  the execution-disabled banner, budget-denial banner and honest cancel
  availability. `POST /v1/projects` implemented. Middleware now allows the
  16 KB chat body (`*/send`), matching the message contract. Task list/create
  and streams stay disabled (Phase 9). Regression tests updated for the newly
  enabled conversation listing; cross-account 404 expectations unchanged.

## Verification (2026-10-05, local macOS operator workspace)

- Core checks: `tests.test_request_queue test_lifecycle test_supervisor
  test_budget test_capacity test_foundation test_fleet_driver test_chat
  test_gateway` — 110 tests OK (2 pre-existing Linux CI skips).
- Django checks: `manage.py test accounts` — 47 tests OK (identity, queue,
  usage, lifecycle, chat HTTP flows incl. cross-account denial, budget denial
  without native call, form redirect flow, escaping).
- Scripts: `tests/check_account_concurrency.py` PASS;
  `tests/check_account_http.py` PASS (loopback Gunicorn, guards, no secret
  logs). `node deploy/vercel/check.mjs` PASS.
- Fresh `manage.py bootstrap_accounts` applies SQL0001–0005 + Django0009 and
  `request_worker --check` reports `execution_ready:false` honestly.
- CI workflow extended with the two new chat test modules.

## Not claimed / remaining gates

- No live installed-Gateway probe: `HttpGateway` framing must be reconfirmed
  against the actual runtime version at activation (CHAT-05 blocker).
- No native dispatch end-to-end on the host: isolated cell proof, capacity
  profile and budget fences (Phase 4/5 gates) precede any real chat task.
- No measured provider route: production sends wait unfunded by design until
  a verified route pricer exists. No paid model call was made.
- Transcript export/retention projection (RETENTION-CHAT) and live event
  streams (≤3/account, Phase 9) remain later-phase work.

Rollback: remove/stop only the new chat routes and tables' consumers; the
migration is additive (no schema downgrade needed for rollback of this
phase's code). Keep private SQLite snapshot discipline before any future
deployment cutover.

Evidence: `openclaw-project/evidence/product/phase-06/20261005T170833Z/`.
