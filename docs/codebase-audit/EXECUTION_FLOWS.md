# Execution Flows

Production status for every flow: **UNVERIFIED** (repo reading only; nothing was run). Paths are relative to `openclaw-project/platform/` unless stated. `file:line` is taken from the findings or from a read-only check; where only a function is known it is cited as `file::function`. Master IDs (M-xx) are in `_findings/00_RECONCILIATION.md`.

## (a) Sign-in

| # | Hop | Where |
|---|---|---|
| 1 | SPA posts credentials | `lumina/src/state/data.tsx:71` (`/auth/login`), form in `pages/Login.tsx` |
| 2 | Edge forwards, Caddy sets `X-AgentAI-Client-IP` | `deploy/caddy/Caddyfile.getlumina:24-25` |
| 3 | Boundary: size caps, override denial, request id | `accounts/middleware.py:14-23` |
| 4 | `signin`: rate `login.ip` 30/900 s, `auth.pair` 5/900 s, `authenticate()` | `accounts/views.py:124-128` |
| 5 | Identity must be verified; `customer_scope` checks epoch + active membership; pending/declined signup get honest 403 | `accounts/views.py::signin`, `accounts/services.py::customer_scope` |
| 6 | Session cycled, epoch stored, audit pending then completed in one transaction | `accounts/views.py::signin` |
| 7 | Later requests: `AccountMiddleware` re-checks epoch, resolves tenant, meters `rate()` | `accounts/middleware.py:60-70` |
| 8 | SPA fetches CSRF then `/v1/app`, `/v1/requests`, `/v1/conversations` | `lumina/src/lib/api.ts:12-30`, `state/data.tsx:31-43` |

Variants: signup (`accounts/signup.py:107-150`, honeypot `website`, owner approval, switch `open_signups`), recovery/activate (uniform replies), operator login needs TOTP.
Leaks/gaps: per-IP limits are global behind Vercel (M-04: BE-003, IS-009); `signin` returns hard-coded `execution_enabled:false` (BE-016); owner signup notice goes to the no-reply address (BE-018); `auth/activate`, `auth/revoke-sessions` have no SPA caller (FE-020).

## (b) Chat send to reply (full loop in ARCHITECTURE section 6)

| # | Hop | Where |
|---|---|---|
| 1 | Composer posts message | `lumina/src/components/Composer.tsx:84`, `pages/Chat.tsx:83` |
| 2 | View, per-scope limits | `accounts/chat.py:166` (task.create cap missing here, BE-017) |
| 3 | `ChatService.send`: steer if run open (`chat.py:222-228` to `steer()` `chat.py:265`) else submit | `agentai_platform/chat.py:203` |
| 4 | `RequestQueue.submit` state waiting (claimable immediately) | `request_queue.py:61` |
| 5 | `BudgetLedger.admit`: reservation + `tasks` row queued | `chat.py:243-250`, `budget.py:70-91` |
| 6 | Worker tick every 3 s; reconcile uncertain, unpark parked, claim oldest overall, lease 120 s | `accounts/management/commands/request_worker.py:62-80`, `request_worker.py:32,46-52`, `request_queue.py:147-175` |
| 7 | Optional JEV shadow classify (record only) | `request_worker.py:65`, `routing/shadow.py:44` |
| 8 | `ChatDriver.execute`: `_admit`, `_begin` (abort unowned turns), `_plan_first_delivery`, delivery row keyed by run id | `chat_driver.py:141,120,165-221,192-197,223-260` |
| 9 | `_supervise` loop (RUN_TIMEOUT 900 s): `_deliver` to `NativeGateway.send` | `chat_driver.py:329,304`, `gateway.py:119` |
| 10 | Bridge validate/dispatch, docker exec Node relay to OpenClaw `chat.send` | `lifecycle/cell_bridge.py:279,458` |
| 11 | Wait 3 s + history, mirror rows to `chat_messages`; Stop/budget/deadline/park checks | `chat_driver.py:348,362,364-371,424-455`, `gateway.py:134,160` |
| 12 | `agent.wait ok` closes gate | `chat_driver.py:375,340`, `request_queue.py:286` |
| 13 | `_finish`: capture files, genui cards, optional JEV display, `outcome.judge` | `chat_driver.py:598-633`, `outcome.py:62` |
| 14 | `_close`: `_reconcile_usage` (LiteLLM key delta, up to 45 s), `ledger.settle`, task state | `chat_driver.py:785,749-777` |
| 15 | `queue.finish` frees slot; `GoalChain.tick` may chain next goal turn | `request_queue.py:195`, `goals.py:35` |
| 16 | SPA polls messages/blocks/events | `lib/conversations.ts:9`, `Chat.tsx` (2.5 s), `AgentThinking.tsx:23` |

Leaks/gaps:
- **M-01** cancel of a WAITING request (also revoked-author, unfunded) leaves reservation `active` and task `queued` (`request_queue.py:107-115`, `chat_driver.py:785-799`); consumes allowance, fills `max_queued_tasks`, blocks cell sleep.
- BE-006: admit is a separate transaction after submit.
- AG-007: spend guard fails open (`chat_driver.py:478-490`); no cap on model calls or tool rounds.
- AG-005: `PARK_LIMIT` expiry re-parks (`chat_driver.py:817-819`, `request_worker.py:101-108`); effective bound is browse `ASK_SECONDS` 300 / takeover 600.
- AG-004: single lane, possible stall for a second account.
- BE-009: uncertain abandon measured from creation, not from uncertainty (`request_worker.py:84-92`).
- AG-013: slot held up to 45 s for usage reconcile.
- AG-018: completion = runtime "ok" plus last reply; only cart/file verified (`outcome.py:36-93`).

## (c) Browser tool call

| # | Hop | Where |
|---|---|---|
| 1 | Assistant calls `lumina_browser` / `lumina_browser_step` (MCP over HTTP, bearer = cell model key) | `lifecycle/cell_config.py:68-71`; tool schemas `browse/adapter.py` |
| 2 | OpenClaw `before_tool_call` hook writes one-use proof (IN PROGRESS) | `lifecycle/tool_origin_plugin/index.mjs:23-50` |
| 3 | `Relay.handle`; `Identity` via bridge `cell.identify`; origin via bridge `tools.origin` | `tool_relay.py:80,36-60`, `accounts/management/commands/tool_relay.py:21-24`, `lifecycle/tool_origin.py:62`, `cell_bridge.py:478-489` |
| 4 | `_owner()`: session + run map to an admitted, funded request | `tool_relay.py:136` |
| 5 | Refusal text is one fixed sentence; reason only in server log | `tool_relay.py:119-122` (AG-008) |
| 6 | `BrowserTool.call/step`: `clean_task`, 60% reservation share, 2-failure guard | `browse/adapter.py:261,307,261-289` |
| 7 | `BrowseRpc('start')` over unix socket | `adapter.py:291-305` to `browse/service.py:158` |
| 8 | Poll every 1.5 s, mirror `browse_runs/steps` into SQLite | `adapter.py:329-380` (AG-022) |
| 9 | `BrowseService._run` under global stage `Semaphore(1)`; engine `runner` or `native` | `service.py:503,155,171`, `service_main.py:92-101` |
| 10 | `BrowseRunner.run`: observe, floor rules, ladder, gate, act | `browse/loop.py:124-330` |
| 11 | Floor in code: bot check, payment page, sign-in page, sensitive control, denied sites | `loop.py:162-196,310-316` |
| 12 | `Ladder.decide`: one JEV call per step (text + screenshot), else hand-over to assistant | `ladder.py:663,598,333,397` |
| 13 | Assistant step: observation returned via `lumina_browser_step` to `service.agent_step` | `service.py:240,342` |
| 14 | Hands: `browse/runner.mjs` in Docker stage (default) or `native_runner.py` via bridge `browser.*` | `service.py:647`, `native_runner.py` |
| 15 | Result text goes back up the MCP call | `tool_relay.py:221` |

Leaks/gaps:
- **M-02** screenshots (base64 JPEG) go to `api.typesafe.ai` each step (`loop.py:208-216`, `ladder.py:333,397`); scrub is text-only; `browser_optimization` switch does not gate it (`switches.py:42-49`, `service_main.py:72-77`).
- M-08 which engine runs in prod is unknown; four SSRF/private-IP implementations (AG-010).
- AG-011 `BrowseService.jobs` never evicted; AG-020 job-stop failures swallowed.
- OP-011 #10 `os.chmod(out_dir, 0o777)` (`browse/service.py:519`) and #12 predictable `/tmp` staging name.
- AG-021 guarantee "never presses payment" holds only inside this tool.
- IN PROGRESS: transient bridge failure tells the model to stop using the browser (AG-008).

## (d) Live view, takeover, hand-over

| # | Hop | Where |
|---|---|---|
| 1 | `Live` page polls job `GET /v1/browse/<id>?since` | `lumina/src/pages/Live.tsx:29`, `accounts/browse.py` |
| 2 | `LiveScreen` posts `/v1/browse/<id>/live` to get ticket `{ticket,path,expires_in}` | `LiveScreen.tsx:30`, `accounts/browse.py::live` (line 164) |
| 3 | Ticket: HMAC-SHA256, 120 s, bound to account + task | `agentai_platform/live/ticket.py::mint` (28), `verify` (36) |
| 4 | Frame loop: long-poll `fetch` of JPEG with ticket; 200 + `X-Seq`, 204 none, 403 expired | `LiveScreen.tsx:33` |
| 5 | Caddy `@liveframe` regex `^/v1/live/<32hex>/frame$` to 127.0.0.1:18801 (before `/v1`) | `Caddyfile.getlumina:7` |
| 6 | Gateway thread inside browse service serves `live.jpg` written by the runner | `live/gateway.py`, `browse/service_main.py:26-37`, `browse/runner.mjs` |
| 7 | Takeover: `control` (click/type/goto), `pause`, `resume`, `release` | `accounts/browse.py:92,134,149,113`; `browse/service.py:395,221,437`; SPA `Live.tsx:56,65` |
| 8 | Hand-over to customer: browse job enters asking/paused; request parks | `chat_driver.py:363-366,457,802`, `request_queue.py:230-238`, `service.py:93,292,384-386` |
| 9 | Answer to a browser question: `POST /v1/browse/<id>/answer` | `accounts/browse.py:186`; **no caller in `lumina/src`** (FE-002) |

Leaks/gaps: FE-002 (conditional High) the shipping SPA cannot answer a browser question; FE-007 frames are repeated fetches, no SSE; FE-010 ticket in URL query; IS-004 port 18801 clash with legacy control unit (silent live-view failure if both enabled); AG-005 park limit; IS-022 ticket weaknesses are minor; GH-018 `/var/www/lumina-scenes` still referenced by Caddy but removed from `lumina/public`.

## (e) Billing and Stripe webhook

| # | Hop | Where |
|---|---|---|
| 1 | Checkout/portal: customer session, switch `billing_checkout`, Idempotency-Key | `accounts/billing.py:136` |
| 2 | Stripe posts to `/v1/billing/webhook` (csrf_exempt, public unmetered) | `accounts/billing.py:146`, `middleware.py:49` |
| 3 | Body cap: middleware 8192 bytes unless path allowed | `middleware.py:23` vs `billing.py:34` `MAX_BODY=262144` (BE-004) |
| 4 | Signature over raw body, 300 s tolerance, multi-secret overlap | `agentai_platform/billing.py:61` (`verify_signature`), `ingest` (378) |
| 5 | Inbox dedup, canonical re-fetch from Stripe, `apply_snapshot` | `billing.py:482` |
| 6 | `billing_worker` timer every 30 s runs sweep, retries to dead-letter | `agentai-billing-worker.service:11`, `billing.py:627` |
| 7 | Entitlement and limits read by ledger (`plan.json` via `billing.py:190-193`) | `budget.py:68-91` |
| 8 | Access sync for free mode (`open_access` switch) | `billing.sync_open_access` |

Leaks/gaps: BE-004 large events may 413 and be dropped silently; BE-005 `--reconcile` never scheduled; Stripe not configured per LAUNCH.md (OP-014); no React checkout UI (FE-014); OP-008 plan.json constants duplicated, only price/daily/task/queue wired; payments off in test mode.

## (f) File and artifact download ticket

| # | Hop | Where |
|---|---|---|
| 1 | List files: `GET /v1/projects` then `/v1/projects/<id>/files` (N+1) | `lumina/src/pages/Files.tsx:18-19`, `Chat.tsx:71-72` (FE-009) |
| 2 | Mint ticket: `POST /v1/artifacts/<id>/versions/<v>/ticket` (session, tenant-checked) | `accounts/files.py:196`, `agentai_platform/artifacts.py::mint_ticket` (138) |
| 3 | Browser navigates to `/download` with ticket | `lumina/src/gen/ChatBridge.tsx:58` (`window.location.assign`) |
| 4 | Download: csrf_exempt GET, no session, single-use ticket consumed | `accounts/files.py:173`, `artifacts.py::consume_ticket` (153) |
| 5 | Bundle zip | `files.py` `bundle`, `artifacts.py::build_bundle` (178) |
| 6 | Generated-asset route (document images): session + must be referenced by caller's own document | `accounts/files.py::gen_asset` (231) |

Leaks/gaps: BE-019 upload reads whole file before size check, size limit only when switch on, `Content-Disposition` quoting differs between routes, ticket consumed on GET so prefetchers burn it; uploads off by default; `gen/safety.ts:44` default `/v1/files/content` is not a route (FE-010); `storage.py`/`artifacts.py` not deep-audited.

## (g) Generative UI block lifecycle

| # | Hop | Where |
|---|---|---|
| 1 | Prompt carries UI tier and catalog; assistant emits a document/envelope in its reply | `chat_driver.py:223-260`, `lumina/src/gen/protocol.ts`, `gen/registry.ts` |
| 2 | Driver `_finish` turns replies into genui cards; optional JEV display layout | `chat_driver.py:598-633`, `routing/display.py` |
| 3 | Server validation `validate_document/validate_block` | `agentai_platform/genui/document.py:299,227` |
| 4 | Persist: `genui/artifacts.py`, `genui/store.py`; migrations 0017/0020/0027/0029/0030 | `accounts/genui.py` |
| 5 | SPA lists blocks `GET /v1/conversations/<id>/blocks` | `accounts/genui.py:46`, `Chat.tsx:43`, `gen/ChatBridge.tsx:45` |
| 6 | Render: `BlockView` dispatch; kind `document` lazy-loads `gen/ChatBridge` and `gen/Renderer`; old kinds (form, task_plan) use `components/genui/*`; old cards go `Cards` to `gen/legacy` | `components/genui/BlockView.tsx:12-27`, `Cards.tsx:4` |
| 7 | Interaction: `POST /v1/genui/artifacts/<id>/{state,events,diagnostics}`; old `POST /v1/blocks/<id>/{state,live,submit,launch,phase,stop}` | `ChatBridge.tsx:52-55`, `useAutosave.ts:19`, `PlanBlock.tsx:114-122` |
| 8 | Plan phases launch as queued requests | `genui/runner.py`, `request_worker.py:34-43` |

Leaks/gaps: M-07 three generations coexist; FE-005 registry duplicated front/back and `/v1/genui/registry` never called; `gen/safety.ts` filters links, HTML, bidi chars (FE-010); mermaid `securityLevel` unverified; `/app/gen-gallery` reachable by customers (FE-011); `genui/*` not deep-audited for authz; `PlanRunner._audit` errors swallowed (BE-010).

## (h) Deploy and release path

| # | Hop | Where |
|---|---|---|
| 1 | Backend: operator copies release tree to server, runs canary `release.py` (live DB copied to 0700 scratch, `bootstrap_accounts` migrate, probes, schema-compatible rollback) | `platform/deploy/release.py:116,132` |
| 2 | Units from `platform/deploy/*.service`; supervisor and bridge releases under `/opt/agentai-*/releases`, `current` symlink | `deploy/README.md`, `evidence/deployments/*/deployment.json` |
| 3 | Frontend: build `lumina`, upload to `/var/lib/agentai-platform/ui` and refresh `/var/www/lumina-scenes` | `bin/deploy-lumina.py` (71 lines) |
| 4 | Vercel static + rewrites for `/account /auth /v1 /app` to `BACKEND_ORIGIN` | `platform/deploy/vercel/routing.mjs:21-23`, `deploy/vercel/check.mjs` (CI) |
| 5 | Browse runner hand-copied to `/opt/agentai-browse/runner/runner.mjs` | RELEASE_NOTES hand-made list (IS-006) |
| 6 | Host SSH via `bin/ssh-server`, `scp-server` (password from `.env`) | `bin/ssh-server:21-24` |
| 7 | Owner stack via `docker compose` in `/opt/openclaw-production` | `deploy/docker-compose.production.yml` |

Leaks/gaps: **L-01** documents target an IONOS IP, owner SSH config names another host; IS-002 root password SSH; IS-006 server-only files (dashboard unit, drop-ins, Caddyfile, runner copies); AG-006 uncommitted tool_origin work described as deployed; GH-005 no tags after `release/live8` for native1-4/safety1; ST-001 CI does not run frontend or most tests; OP-009 no deploy job; ST-013 seven units undocumented; IS-005 stale nft sample; GH-013 remote branch 47 commits behind, `main` stale.

## (i) Backup and restore

| # | Hop | Where |
|---|---|---|
| 1 | Timer 03:40 UTC runs `ops.cli backup` as root | `agentai-ops-backup.service:10` |
| 2 | Sources: sqlite snapshot, files, latest-file sources, pgdump/tar/json verifiers | `ops/backup.py:94-134` |
| 3 | Encrypt to age public recipient only; write set to `/var/backups/agentai`; retention 14 daily + 2 weekly, max 30 days | `ops/backup.py::select_keep` (134), `ops/crypto.py`, `ops/hostconfig.py` |
| 4 | Owner pulls off-server from Mac | `bin/pull-backups.py` |
| 5 | Monitor every 5 min checks units, queue, backup freshness, exposure | `ops/monitor.py:19-30` |
| 6 | Per-account restore: scoped, proves other accounts unchanged, refuses unclassified tables | `ops/restore.py:89` (`restore_account`) |
| 7 | Owner stack drill | `bin/ops-restore.sh` |

Leaks/gaps: IS-016 default destination local only; vault key file and `live.secret` not in backup set; no automated restore test of the customer DB beyond unit tests; IS-003 monitor does not require `agentai-browse`; `ops/restore.py:154-157` is the only sweeper of stale reservations (relates to M-01); `age` missing means backup tests skip on dev and CI (ST-017); BE-011 `retention_accounts` unscheduled; restoring leaves `vault_items` by design.

## Cross-flow gap summary

| Gap | Flows | IDs |
|---|---|---|
| Money/allowance leak | b, i | M-01 |
| Customer pixels leave host | c, d | M-02 |
| Global rate buckets | a, e | M-04 |
| Coverage not in CI | all | M-10 |
| Single lane/worker | b, c, d | AG-004, BE-002, BE-013 |
| Prod target unknown | h, i | L-01, L-02, L-03 |
