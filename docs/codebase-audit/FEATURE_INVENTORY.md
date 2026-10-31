# Lumina feature inventory (merged, deduplicated)

Audit date 2026-10-29. Branch `product-phases-6-11`, HEAD `03662de`, plus uncommitted tool_origin / tool_relay / cell_bridge / cell_config work (IN-PROGRESS, not judged).
Sources: `_findings/{backend,orchestration,frontend,infra_security,structure,history,outside_project}.md` and `_findings/00_RECONCILIATION.md`.

## How to read this file

- Canonical IDs `F-001..F-074`. The "source FEAT" column lists the original `FEAT-*` ids merged into the row. Rows with no FEAT id say which finding they came from.
- Primary status vocabulary: ACTIVE / INCOMPLETE / ORPHANED / LEGACY / DUPLICATED / BROKEN / EXPERIMENTAL / UNKNOWN. Extra flags are secondary.
- "Prod verified" is `unknown` for every row. No SSH or network access succeeded during the audit (L-01..L-03 in the reconciliation notes: the repo runbooks target IONOS 69.48.206.62, the owner's `~/.ssh/config` names a different host, and neither was reachable or accepted `ssk-key`). The only dated repo evidence of a deployment is `evidence/deployments/20261027T114539Z-cancel-e700e33/` (release/verification logs, commit e700e33, 27 Oct 2026). Rows touched by it say "repo evidence 27 Oct (not re-verified)". An untracked doc `docs/browser-tool-ownership.md` claims release `20261028T212308Z-tool-origin-v2` is live; that is a claim, not evidence (AG-006).
- Class letters A-G are the findings' recommendation labels (inferred from usage): A = safe cleanup after verification, B = consolidate / refactor, C = product decision, D = targeted repair, E = architecture change, F = fix / harden, G = preserve / document.
- No deletion is recommended anywhere on static evidence alone.

## 1. Customer chat and execution core

| ID | feature | primary status | extra flags | frontend | backend | entry / flow evidence | prod verified | notes / finding IDs | source FEAT |
|---|---|---|---|---|---|---|---|---|---|
| F-001 | Auth: login, logout, recovery, activate, revoke-sessions, epoch invalidation | ACTIVE | operators need TOTP | `pages/Login.tsx`, `state/data.tsx:70-76` | `views.py`, `services.py` | `views.py:132-149`, `middleware.py:60-70` | unknown | `auth/activate`, `auth/revoke-sessions` have no frontend caller (FE-020) | FEAT-BE-01, FEAT-FE-01 |
| F-002 | Self-signup with owner approval | ACTIVE | switch `open_signups`; honeypot | `Login.tsx:32` | `signup.py`, `signup_admin` | `signup.py:107-150` | unknown | owner notice goes to the no-reply sender (BE-018) | FEAT-BE-02, FEAT-FE-01 |
| F-003 | Chat: conversations, send, history, rename, archive/restore | ACTIVE | switch `customer_execution` gates execution | `Chat.tsx`, `Composer.tsx:84`, `History.tsx`, `ChatActions.tsx` | `agentai_platform/chat.py`, `accounts/chat.py` | `accounts/chat.py:166` -> `chat.py:203` -> `request_queue.py:61` | unknown | polling not SSE (FE-007/008); `chat_send` lacks `task.create` cap (BE-017) | FEAT-BE-03, FEAT-AG-01, FEAT-FE-02 |
| F-004 | Steering a running task | ACTIVE | | send box | `chat.py:265` | `chat.py:222-228` | unknown | | FEAT-AG-04 |
| F-005 | Goal mode ("keep working", 20-turn cap) | ACTIVE | `goal` flag | goal toggle (`Tasks.tsx:39`) | `goals.py`, `chat_driver.py:225-236,622-633` | `request_worker.py:36-43` | unknown | `GoalChain.limit` dead (AG-015) | FEAT-AG-05 |
| F-006 | Plan mode + PlanRunner | ACTIVE | | plan card | `genui/runner.py`, `chat_driver.py:686` | `request_worker.py:34-43` | unknown | swallowed exceptions (BE-010) | FEAT-AG-06 |
| F-007 | Serial request queue + request worker (one global running slot) | ACTIVE | design limit | `/v1/requests` | `request_queue.py`, `request_worker.py` | `agentai-request-worker.service:11`; `commands/request_worker.py:62-80` | unknown | BE-001/AG-001 (M-01), BE-006, BE-009, BE-013, AG-004 | FEAT-BE-04, FEAT-AG-01 |
| F-008 | Budget ledger and plan limits | ACTIVE | | `/v1/costs`, Settings | `budget.py` | `chat.py:339`, `request_worker.py:55` | unknown | M-01, BE-006; plan constants duplicated (OP-008) | FEAT-BE-05 |
| F-009 | Native run supervision (driver) | ACTIVE | owner switch `customer_execution` | | `chat_driver.py` (907 lines) | `commands/request_worker.py:62-77` -> `chat_driver.py:141` | unknown | AG-005, AG-007, AG-013, AG-014, AG-020 | FEAT-AG-02 |
| F-010 | Gateway / cell bridge to customer cell | ACTIVE | root bridge, allowlisted methods | | `gateway.py`, `lifecycle/cell_bridge.py` (uncommitted edits) | `commands/request_worker.py:24` | unknown | `SyntheticGateway` is a test double only | FEAT-AG-03 |
| F-011 | Park on customer + hand-over | ACTIVE | | Live view | `chat_driver.py:457,802`, `request_queue.py:230` | `chat_driver.py:363-366` | unknown | `PARK_LIMIT` does not end the run (AG-005) | FEAT-AG-07 |
| F-012 | Stop / cancel | ACTIVE | gap for waiting requests | stop button | `chat_driver.py:558`, `chat.py:465` | `chat_driver.py:334` | unknown | HIGH leak M-01 (BE-001/AG-001) | FEAT-AG-08 |
| F-013 | Outcome verdict | ACTIVE | weak verification | outcome note | `outcome.py` | `chat_driver.py:626` | unknown | only cart/file verified (AG-018) | FEAT-AG-09 |
| F-014 | Tasks screen: pause / resume / cancel / retry / goal | ACTIVE | | `pages/Tasks.tsx:22-44` | `/v1/requests/<id>/*`, `/v1/tasks/<id>`, `/v1/conversations/<id>/goal` | `Tasks.tsx` | unknown | `task.create` cap on retry but not send (BE-017) | FEAT-FE-03 |
| F-042 | `lumina_task_update` progress tool (checklist widget) | ACTIVE | | task widget | `task_progress.py` | `commands/tool_relay.py:22` | unknown | | FEAT-AG-21 |
| F-043 | Cell wake / sleep, one running cell per host | ACTIVE | capacity default 2 | | `lifecycle/worker.py`, `sleep.py` | `worker.py:158` | unknown | stall risk with two accounts (AG-004) | FEAT-AG-22 |

## 2. Browser stack (JEV ladder, engines, tool relay)

| ID | feature | primary status | extra flags | frontend | backend | entry / flow evidence | prod verified | notes / finding IDs | source FEAT |
|---|---|---|---|---|---|---|---|---|---|
| F-021 | Browse run control + Live view (HTTP layer and page) | ACTIVE | switch `browse_tasks`; takeover | `pages/Live.tsx`, `LiveScreen.tsx:30-33` | `accounts/browse.py`, `live/gateway.py` | route `live/:id`; `/v1/browse/<id>/{live,control,pause,resume,release,shot}` | unknown | `answer`, `/v1/saved*` and `/v1/browse/<id>/{pause,resume,release,answer}` callers: only release/pause/resume are used by `lumina` (FE-020); frames are repeated long fetch (FE-007) | FEAT-BE-10, FEAT-FE-04, FEAT-GH-05 |
| F-037 | Browse service: JEV chooser + hand-over to assistant | ACTIVE | owner switch `browse_tasks`; sends text + screenshot to TypeSafe | Live view | `browse/ladder.py`, `loop.py`, `service.py` | `adapter.py:301` -> `service.py:158` -> `loop.py:124` | unknown | HIGH privacy M-02 (AG-002/IS-014/AG-003); god files AG-014 | FEAT-AG-11, FEAT-GH-04 |
| F-038 | `lumina_browser` / `lumina_browser_step` MCP tool + tool relay | ACTIVE | IN-PROGRESS uncommitted diff; doc claims deployed 28 Oct | | `tool_relay.py`, `browse/adapter.py` | `agentai-tool-relay.service:11`; `cell_config.py:68-71` | unknown (untracked `docs/browser-tool-ownership.md` claims live; AG-006) | AG-006, AG-008, IS-020, IS-021 | FEAT-AG-10, FEAT-IS-03 |
| F-039 | Host Docker browser engine (`browse/runner.mjs`, Playwright stage) | ACTIVE | default engine (`service_main.py:92-101`); LEGACY-planned; DUPLICATED with F-040 | | `runner.mjs`, `service.py:647` | `stage_argv` | unknown | planned for deletion after native gate (`native-browser-plan.md:131`); hand-copied to `/opt/agentai-browse/runner` (IS-006) | FEAT-AG-12, FEAT-GH-04 |
| F-040 | Native browser engine (cell's own OpenClaw browser) | INCOMPLETE | rollout-gated per account (`browse-engine.json`, default `runner`); EXPERIMENTAL | | `native_runner.py`, bridge `browser.*` | `service.py:171`, `service_main.py:92-101` | unknown; repo evidence 27 Oct: an OOM canary reverted an account to the runner (`evidence/deployments/20261027T114539Z-cancel-e700e33/deployment.json`) | M-08; AG-010 duplicates SSRF logic | FEAT-AG-13, FEAT-IS-12, FEAT-GH-04 |
| F-041 | Tool-origin protocol 2 (one-use ownership proofs) | EXPERIMENTAL | IN-PROGRESS, UNCOMMITTED | | `lifecycle/tool_origin*.py`, `tool_origin_plugin/` | `cell_config.py:62-64,137-153` | unknown (claimed deployed, AG-006) | AG-006, AG-008, AG-019; new test `tool_origin_plugin.test.mjs` not in CI | FEAT-AG-20 |
| F-044 | Browser safety floor (bot, payment, sign-in, sensitive control, denied sites) | ACTIVE | per-account safety switches | | `browse/loop.py:162-196` | `loop.py:310` | unknown | `_run` is 220 lines (AG-014); guarantee scope is only inside `lumina_browser` (AG-021) | FEAT-AG-23 |
| F-035 | JEV shadow routing (classify, record only) | EXPERIMENTAL | switch `jev_routing` default off | | `routing/shadow.py` | `request_worker.py:65` | unknown | repeated classification on re-claim (AG-012); docs disagree on state (OP-015) | FEAT-BE-19, FEAT-AG-14 |
| F-036 | JEV display layout chooser | EXPERIMENTAL | switch `jev_display` default off | cards | `routing/display.py` | `chat_driver.py:620-621` | unknown | sends reply text to TypeSafe | FEAT-BE-19, FEAT-AG-15 |
| F-060 | Live frame gateway (HMAC ticket, 120 s) | ACTIVE | secret-file gated; thread in root browse service | `LiveScreen.tsx` | `live/gateway.py`, `live/ticket.py` | Caddy `@liveframe` -> 18801 | unknown | port 18801 clash with F-066 (IS-004); IS-022 | FEAT-IS-02 |
| F-045 | ServiceRouter-first JEV service choice | LEGACY | code deleted; docs stale | none | `routing/services.py` removed | deleted in `5db9636` with `test_services.py`, `test_service_handoff.py` | n/a | M-11 (AG-016/GH-003) | FEAT-AG-24, FEAT-GH-06 |

## 3. Money, billing, plans

| ID | feature | primary status | extra flags | frontend | backend | entry / flow evidence | prod verified | notes / finding IDs | source FEAT |
|---|---|---|---|---|---|---|---|---|---|
| F-015 | Stripe billing backend (checkout, portal, webhook inbox, sweep) | ACTIVE | test mode; switch `billing_checkout`; Stripe account/keys not created per LAUNCH.md | none in `lumina/src` (server-rendered `/account/billing/`) | `billing.py`, `billing_worker` | `agentai-billing-worker.timer` 30 s | unknown | BE-004 (webhook 8 KB cap), BE-005 (no `--reconcile`); phase 13 acceptance NOT_RUN (OP-014) | FEAT-BE-06, FEAT-GH-14 |
| F-016 | Billing / subscription UI | INCOMPLETE | `billing_mode` label only | label in Sidebar/Settings | `/v1/account/billing*` | no checkout/portal call in `lumina/src` | unknown | decision needed (C) | FEAT-FE-14 |
| F-017 | Open (free) access entitlement sync | ACTIVE | switch `open_access` | | `billing.sync_open_access` | billing_worker | unknown | | FEAT-BE-07 |
| F-071 | `product/plan.json` consumed by billing | ACTIVE | constants partly duplicated | | `billing_install.py:140`, `billing.py:190-193` | tests `test_billing.py:17` | unknown | OP-008: only prices, daily, task, queue wired; task duration 1800 vs 3600 drift | FEAT-OP-04 |
| F-073 | Cost model `product/calculate_costs.py` | ACTIVE | scenario docs only; `actual_*` null | | | never an admission guard | n/a | OP-007 | FEAT-OP-06 |
| F-072 | `lumina-cost-audit/` production usage analysis | LEGACY | UNTRACKED; owner request logs | | none | no code consumer | n/a | OP-003, OP-007 | FEAT-OP-05 |

## 4. Files, generative UI, look and feel

| ID | feature | primary status | extra flags | frontend | backend | entry / flow evidence | prod verified | notes / finding IDs | source FEAT |
|---|---|---|---|---|---|---|---|---|---|
| F-018 | Files, artifacts, signed downloads, zip bundle | ACTIVE | needs `AGENTAI_STORAGE_DIR`; uploads need `UPLOADS_ENABLED` | `pages/Files.tsx` | `files.py` | `urls.py` | unknown | N+1 (FE-009); BE-019 | FEAT-BE-08, FEAT-FE-10 |
| F-019 | Generative UI document blocks / artifacts (registry generation) | ACTIVE | answer-style `ui` field sent on send | `BlockView.tsx:12-13` -> `gen/ChatBridge.tsx` | `accounts/genui.py`, `genui/*` | `/v1/conversations/<id>/blocks`, `/v1/genui/artifacts/*` | unknown; commit a2bb53b says deployed | not deep-audited by backend; M-07; FE-005 | FEAT-BE-09, FEAT-FE-08, FEAT-GH-03 |
| F-020 | Old block system (form, task_plan, table, chart, comparison) | DUPLICATED | form and task_plan still live; history rendering | `components/genui/*`, `lib/genui/*` | `/v1/blocks/<id>/{state,live,submit,launch,phase,stop}` | `BlockView.tsx:15-27` | unknown | M-07 FE-004/GH-007; `gen/legacy.tsx` adapter must be kept | FEAT-FE-09, FEAT-GH-03 |
| F-055 | Comparison-card product images | ACTIVE | superseded branch `worktree-product-images` | `Cards.tsx` | `genui/images.py`, `0025_card_images.sql` | b956e68 re-landed in d95b796 | unknown | GH-006 | FEAT-GH-11 |
| F-024 | Safety console / menu | ACTIVE | owner/granted accounts only change switches | `SafetyButton` in `Sidebar.tsx:4` | `safety.py` (`/v1/safety*`) | `lib/safety.ts:58-70` | unknown | | FEAT-BE-12, FEAT-FE-07 |
| F-048 | Home dashboard | ACTIVE | index `/` renders Chat (FE-012) | `pages/Home.tsx` | `/v1/requests` | nav `/home` | unknown | | FEAT-FE-17 |
| F-049 | Settings, usage, answer style | ACTIVE | | `Info.tsx:Settings` | `/v1/costs` | | unknown | | FEAT-FE-11 |
| F-050 | Component gallery `/app/gen-gallery` | EXPERIMENTAL | reachable by any signed-in customer | `gen/Gallery.tsx` | none | `App.tsx:28` | unknown | FE-011 | FEAT-FE-16 |
| F-052 | Theme: dark default, parchment switchable | ACTIVE | | `settings.tsx`, `tokens.css` | | 5596eda -> 5db9636 | unknown | settings test deleted (GH-015) | FEAT-GH-08 |
| F-054 | Thinking indicator: orbs (replaced TaskStrip) | ACTIVE | vendored `thinking-orbs` | `AgentThinking.tsx`, `Orb.tsx` | | 1bc28ab, ff92478 | unknown | | FEAT-GH-10 |
| F-051 | Scene film background / parchment film | LEGACY | only in `lumina-character/`; Caddy may still serve `/var/www/lumina-scenes` | `lumina-character/SceneBackground.tsx` | `/v1/assistant/presence` | moved in d95b796 | unknown | GH-018 verify deploy refs | FEAT-FE-18, FEAT-GH-07 |
| F-074 | `lumina-character/` full frontend fork | DUPLICATED | tracked; 4,697 files; unreferenced by deploy/CI; intent disputed (archive vs in-progress UI) | whole app | | tag `lumina-character-final` | unknown | M-06 (FE-001/ST-002/GH-012, GH-002) | no FEAT (finding-level) |
| F-053 | `platform/ui-reference/` plain-JS client | LEGACY | referenced only by `platform/UI_CONTRACT.md:10` | `app.js` | `/v1/csrf` etc. | none | unknown | FE-018 | FEAT-FE-19 |

## 5. Browser question UI, vault, channels, integrations

| ID | feature | primary status | extra flags | frontend | backend | entry / flow evidence | prod verified | notes / finding IDs | source FEAT |
|---|---|---|---|---|---|---|---|---|---|
| F-022 | Browser "asking" question UI (answer a question raised by a browser run) | INCOMPLETE | REGRESSION: UI removed from `lumina` in d95b796; exists only in the fork; customer impact conditional | `lumina-character/useBrowseQuestion.ts:23`, `Live.tsx:84` only | `/v1/browse/<id>/answer`, `ASK_SECONDS=300` | no `answer` caller in `lumina/src` | unknown | FE-002 (High, conditional); AG-005 | FEAT-FE-05, FEAT-GH-09 |
| F-023 | Vault / saved form values | INCOMPLETE | needs key file; `credentialed_browsing` needs `login_flow` fact; UI ORPHANED (fork only) | `lumina-character/SavedInfo.tsx` | `vault.py` (AES-GCM, HKDF, AAD), `0023_saved_choices.sql` | no `vault`/`saved` in `lumina/src` | unknown | FE-002; BE-023 | FEAT-BE-11, FEAT-FE-06, FEAT-GH-09 |
| F-025 | Telegram link + ingress/outbox | INCOMPLETE | BROKEN wiring suspected (no pricer/gateway in factory, no result relay, no drain unit) | none (type only, `lib/api.ts:44`) | `telegram.py`, `telegram_worker` | `accounts/telegram.py:26-31` | unknown | BE-007 (MEDIUM-HIGH) | FEAT-BE-13, FEAT-FE-15 |
| F-026 | Connectors / OAuth (Gmail, Calendar, Drive, GitHub) | INCOMPLETE | switch `connectors_linking` unmet facts; link returns 503 | read-only list `Info.tsx:Integrations` | `connectors.py`, `connections.py` | `connections.py:29-30,47-73` | unknown | BE-008 | FEAT-BE-14, FEAT-FE-12 |
| F-027 | Operator HTTP API `/internal/accounts/*` | ORPHANED | by config: Caddy forwards only `/account /auth /v1 /app`; loopback only; MFA + grants | none | `views.py`, `lifecycle.py` | `Caddyfile.getlumina:20` | unknown | host CLI `account_admin` is the working path | FEAT-BE-15 |
| F-028 | Disabled stubs `/v1/streams|exports|memory|schedules|integrations|controls`, `/v1/tasks` list | INCOMPLETE | all return 503 `capability_not_enabled` | copy only | `views.disabled` | `urls.py:27-29` | n/a | in openapi; preserve (G) | FEAT-BE-16 |
| F-029 | Calendar and Automations pages ("Soon") | INCOMPLETE | | `Info.tsx` | none called | | unknown | FE-013 | FEAT-FE-13 |

## 6. Orphaned product modules and standalone tracks

| ID | feature | primary status | extra flags | frontend | backend | entry / flow evidence | prod verified | notes / finding IDs | source FEAT |
|---|---|---|---|---|---|---|---|---|---|
| F-030 | Objectives, memory, schedules, watchers, skills | ORPHANED | tables + tests + locked switches exist | "coming soon" | `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py` | no non-test importer | n/a | M-05 (BE-014/AG-009); class C/G | FEAT-BE-17, FEAT-AG-17 |
| F-031 | Phase 12 optimisation gate + billing | ORPHANED | header says DISABLED; consent switch `browser_optimization` not wired to the live path | | `optimization.py` | no importer | n/a | AG-003 (HIGH, M-02); GH-013 (22db0e7) | FEAT-AG-16, FEAT-GH-13 |
| F-032 | Policy check CLI | ORPHANED | | | `policy_check.py:83` | none found | n/a | M-05 | FEAT-AG-18, FEAT-BE-17 |
| F-033 | Worker broker (execution envelopes) | ORPHANED | operator check only | | `lifecycle/broker.py` | `platform/deploy/p4_broker_check.py:10` | n/a | AG-009 | FEAT-AG-19 |
| F-034 | SSE task stream `/v1/tasks/<id>/stream` | ORPHANED | unused by React; DoS risk on single sync worker | none (polling) | `streams.stream` | no `EventSource` in either frontend | unknown | BE-002 (High) | FEAT-BE-18 |
| F-046 | `browser-opt/`, `research-opt/`, `experiments/`, `evals/` | EXPERIMENTAL | `experiments/` untracked; first two run in CI | | standalone adapters | tests only | n/a | OP-017, GH-013 | FEAT-AG-25 |
| F-047 | `config/skills`, workspace templates, phase fixtures | UNKNOWN | may be hand-installed on owner host | | | `test_phase10_assets.py:26`, `bin/phase6/*` | n/a | AG-009, ST-009 | FEAT-AG-26 |
| F-068 | `jev-browser/` bare-loop prototype (+4 tarballs) | EXPERIMENTAL | UNTRACKED; SUPERSEDED; no link to platform | `web/index.html` | `jevbrowse/*.py` | no references in `openclaw-project/{platform,browse,lumina,bin}` | n/a | OP-004, OP-005, ST-005 | FEAT-OP-01 |
| F-069 | `jev-window-core/` macOS window loop | EXPERIMENTAL | UNTRACKED | | `loop.py`, `Window.swift` | `README.md:3` | n/a | | FEAT-OP-02 |

## 7. Infra, ops, process

| ID | feature | primary status | extra flags | frontend | backend | entry / flow evidence | prod verified | notes / finding IDs | source FEAT |
|---|---|---|---|---|---|---|---|---|---|
| F-058 | Owner dashboard (`dashboard/app.py`, 1718 LOC) | ACTIVE | owner-only, SSH tunnel; unit file not in repo | `dashboard/static` | `dashboard/app.py` | `bin/update-ops-dashboard.py` | unknown | IS-011, IS-006, ST-008 | FEAT-GH-02, FEAT-IS-09 |
| F-059 | Customer HTTPS edge (Vercel -> Caddy -> gunicorn) | ACTIVE | prod-unverified | `vercel/routing.mjs` | `Caddyfile.getlumina` | `evidence/deployments/*/verification.log` probes 200/200/200/401 | repo evidence 27 Oct (not re-verified) | M-04 shared client IP; L-01 target drift | FEAT-IS-01 |
| F-061 | Model relay for cells (10.77.0.1:4000) | ACTIVE | | | `model-proxy/agentai_model_proxy.py` | unit, ufw rule, `test_model_proxy.py` | unknown | IS-005 | FEAT-IS-04 |
| F-062 | Cell isolation (gVisor, separate Docker engine, nft drop-only) | ACTIVE | prod-unverified | | `cells-docker/`, `lifecycle/netpolicy.py` | daemon.json, firewall unit | unknown | IS-005, IS-013 | FEAT-IS-05 |
| F-063 | Encrypted backup + scoped restore | ACTIVE | local only; offsite open | | `ops/*`, `bin/pull-backups.py` | `agentai-ops-backup.timer` | unknown | IS-016 | FEAT-IS-06 |
| F-064 | Monitor + alerts | ACTIVE | gaps (no `agentai-browse` in REQUIRED_UNITS) | | `ops/monitor.py`, `alerts.py` | `agentai-ops-monitor.timer` | unknown | IS-003 | FEAT-IS-07 |
| F-065 | Canary release with schema-compatible rollback | ACTIVE | | | `deploy/release.py` | `evidence/deployments/*/release.log` | yes, repo evidence 27 Oct (e700e33 release recorded; not re-verified) | | FEAT-IS-08 |
| F-066 | Legacy stdlib control server `:18801` | LEGACY | port clash with F-060; whether enabled UNKNOWN | | `server.py`, `agentai-platform-control.service` | no caller in monitor/Caddy | unknown | IS-004; ST-015 | FEAT-IS-10 |
| F-067 | `agentai-supervisor.service` (custody-only) | LEGACY | superseded by `-native`; same `RuntimeDirectory` | | `supervisor_main` | | unknown | IS-023 | FEAT-IS-11 |
| F-070 | CI workflow `.github/workflows/platform.yml` | ACTIVE | partial coverage: about 20 of 73 platform test modules (ST-001 says 20, OP-009 says 21) and nothing of the frontend | | | explicit allow-list | unknown whether runs are green | M-10 | FEAT-OP-03 |
| F-056 | Release / deploy marking (tags) | INCOMPLETE | tags stop at live8; no tags for native1-4, safety1 | | `RELEASE_NOTES.md` | | unknown | GH-005 | FEAT-GH-12 |
| F-057 | Legacy AgentAI multi-user agent | LEGACY | deleted in 8298602, recoverable via git | Jinja templates | `agent/core/*` | 4cb60d0, 5e6f3fa | n/a | none | FEAT-GH-01 |

## 8. Count by primary status

| status | count | IDs |
|---|---|---|
| ACTIVE | 42 | F-001..F-015 (15), F-017, F-018, F-019, F-021, F-024, F-037, F-038, F-039, F-042, F-043, F-044, F-048, F-049, F-052, F-054, F-055, F-058..F-065, F-070, F-071, F-073 |
| INCOMPLETE | 9 | F-016, F-022, F-023, F-025, F-026, F-028, F-029, F-040, F-056 |
| EXPERIMENTAL | 7 | F-035, F-036, F-041, F-046, F-050, F-068, F-069 |
| LEGACY | 7 | F-045, F-051, F-053, F-057, F-066, F-067, F-072 |
| ORPHANED | 6 | F-027, F-030, F-031, F-032, F-033, F-034 |
| DUPLICATED | 2 | F-020, F-074 |
| UNKNOWN | 1 | F-047 |
| BROKEN | 0 | none assigned as primary; F-025 (Telegram) carries a BROKEN-wiring flag |
| total | 74 | |

Counts are tallied from this file's tables; ACTIVE counts F-001 to F-015 as 15 rows.

## 9. Status disagreements between investigators, and resolution

| feature | investigator views | resolution |
|---|---|---|
| F-022 browser question UI | FE: ORPHANED in `lumina`, ACTIVE in fork; GH: LEGACY (deleted d95b796); backend/orchestration: routes + `ASK_SECONDS` exist | INCOMPLETE (regression). Customer impact UNKNOWN: depends on whether the `asking` state is reachable in prod (reconciliation: HIGH impact, MEDIUM confidence) |
| F-023 vault / saved info | BE: INCOMPLETE; FE: ORPHANED (fork only); GH: LEGACY | INCOMPLETE: backend complete (`vault.py` both layers), no UI in the shipping app, switch gated |
| F-025 Telegram | BE: INCOMPLETE / BROKEN in prod wiring; FE: INCOMPLETE | INCOMPLETE with BROKEN flag (code evidence BE-007; production state UNKNOWN) |
| F-039 vs F-040 browser engines | AG: runner ACTIVE default / LEGACY-planned, native INCOMPLETE; GH: INCOMPLETE + DUPLICATED; IS: native INCOMPLETE/EXPERIMENTAL | runner ACTIVE-by-code-default, native INCOMPLETE. Which engine prod uses is UNKNOWN (`browse-engine.json` unread). Repo evidence shows at least one account was on native on 27 Oct |
| F-041 tool-origin v2 and F-038 relay | AG-10: ACTIVE, ownership in progress; AG-20: EXPERIMENTAL; untracked doc claims deployed 28 Oct | relay ACTIVE (committed baseline), tool-origin v2 EXPERIMENTAL / IN-PROGRESS. Deployment of uncommitted code UNKNOWN (AG-006) |
| F-019 vs F-020 generative UI | FE-09: LEGACY / DUPLICATED; GH-03: DUPLICATED (three generations) | new stack ACTIVE, old stack DUPLICATED (not purely legacy: form and task_plan still use it) |
| F-030 product modules | BE: ORPHANED; AG: ORPHANED / INCOMPLETE; FE: Calendar/Automations INCOMPLETE | backend modules ORPHANED (no importer); product features INCOMPLETE (F-028/F-029). Both true at different layers |
| F-034 SSE stream | BE: BROKEN-by-config / unused; FE: no `EventSource`; docs: built but unused | ORPHANED (unused); BROKEN-risk only as attack surface (BE-002) |
| F-045 ServiceRouter | AG: LEGACY (deleted); GH: ORPHANED (deleted code, stale docs) | LEGACY. Code verified absent by lead (M-11) |
| F-074 / F-051 `lumina-character` | FE: frozen snapshot; GH: archive with tag `lumina-character-final`; ST: "looks like an in-progress alternative UI" | DUPLICATED / LEGACY; owner intent UNKNOWN (class C decision) |
| F-066 control server | IS: LEGACY/UNKNOWN; ST-015: "hard-disabled (not verified)" | LEGACY by repo evidence; enabled-or-not UNKNOWN (needs VPS check) |
| F-035/F-036 JEV state | AG: default off; OP-015: LAUNCH.md says routing ON record-only, F4 says OFF, code says browser JEV decides | EXPERIMENTAL for routing/display; actual prod switch states UNKNOWN |
| F-047 `config/skills` etc. | AG: UNKNOWN; BE/ST: historical fixtures | UNKNOWN (may be hand-installed on owner host) |
| F-070 CI coverage | ST-001: 20 of 73; OP-009: 21 | "about 20 of 73"; exact count not reconciled |
| F-015 Stripe billing | BE: ACTIVE in test mode; OP-014: acceptance NOT_RUN, no Stripe keys per LAUNCH.md | ACTIVE as code in test mode; live payments not operational (UNKNOWN in prod) |

## 10. Phase prompts 1-19 (OP-014; `phase-prompts/openclaw/`, status from `plans/product/phase-NN.md`, `BUILD_LOG.md`, `LAUNCH.md`; production unverified)

| phase | state | evidence |
|---|---|---|
| 1 product contract | implemented (design READY) | BUILD_LOG "Product Phases 1-2"; `product/CONTRACT.md` |
| 2 platform foundation | implemented (private foundation READY) | same |
| 3 customer accounts | implemented; "activation blocked" at the time, later live per LAUNCH.md | BUILD_LOG Phase 3 entry |
| 4 tenant provisioning | PARTIAL (native acceptance NOT_RUN); later driver work | BUILD_LOG top entries |
| 5 usage / admission | implemented core (`budget.py`, `billing.py`); PARTIAL | BUILD_LOG 09-30 entry |
| 6 dashboard chat | build READY; live native chat dependent | `phase-06.md` |
| 7 Telegram linking | build READY; real bot linking deferred (F5) | `phase-07.md`, `final_phase.md` |
| 8 files / artifacts | build READY; uploads disabled by default (scan not wired) | `phase-08.md` |
| 9 live work | build READY; fail-closed | `phase-09.md`; `live/*` |
| 10 native capabilities | build complete offline; activation BLOCKED | `phase-10.md`; F2 Claude Code agent |
| 11 integrations | build complete offline; all services DISCONNECTED | `phase-11.md` |
| 12 optional optimization build | optional build complete; adapters DISABLED (but JEV switches described ON in LAUNCH.md) | `phase-12.md` |
| 13 billing | implementation READY; acceptance NOT_RUN; Stripe account/keys not created | `phase-13.md`, LAUNCH.md item 2 |
| 14 operations | READY, deployed; off-server backup (F1) still a launch blocker | `phase-14.md`, LAUNCH.md item 4 |
| 15 system acceptance | PARTIAL: 21 PASS, 2 BLOCKED, 7 NOT_RUN | `phase-15.md:status` |
| 16 optional optimization evaluation | NOT started (paid benchmark needs owner go) | LAUNCH.md |
| 17 private beta | NOT started | LAUNCH.md |
| 18 launch | NOT started | LAUNCH.md |
| 19 optional purchases | NOT started; browser purchasing locked (`credentialed_browsing`, F3) | `final_phase.md` |

Notes: `final_phase.md` records deferred items F1-F13. No `plans/product/phase-16..19.md` exists; those prompts live only in `phase-prompts/`. "Phase N" has at least four meanings in the repo (GH-008), so check which numbering a document uses.
