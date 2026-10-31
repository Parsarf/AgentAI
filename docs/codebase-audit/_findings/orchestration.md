# Orchestration and browser automation audit (scope prefix AG)

Branch `product-phases-6-11`, HEAD `03662de`, plus the uncommitted working tree. Read-only audit; nothing was run, installed or deployed. All production statements are UNVERIFIED unless a line says otherwise.

## Scope & method

Covered: `platform/agentai_platform/{chat_driver,chat,gateway,request_queue,request_worker,goals,outcome,budget,safety,switches,privacy,tool_relay,task_progress}.py`, `browse/*`, `lifecycle/*`, `routing/*`, `genui/runner.py`, `accounts/management/commands/{request_worker,tool_relay}.py`, `browse/runner.mjs`, `config/*`, `browser-opt/`, `research-opt/`, `experiments/`, `evals/`, `docs/{orchestration-audit,architecture,browser-*.md}`, deploy units under `platform/deploy/`, and the tests that cover them.

Method: full reads of `chat_driver.py`, `gateway.py`, `request_queue.py`, `request_worker.py`, `outcome.py`, `goals.py`, `tool_relay.py`, `browse/adapter.py`, `lifecycle/tool_origin*.py`, `lifecycle/cell_config.py`; targeted reads of `browse/{service,loop,ladder,native_runner}.py`, `lifecycle/{worker,coordinator,sleep,cell_bridge}.py`, `chat.py`, `budget.py`. Importer checks used `rg` over `agentai_platform/` and `accounts/` (non-test), plus `urls.py`, `platform/deploy/*.service`, `bin/`, and `deploy/*.json` for dynamic or operator entry points. `git diff` was used for the uncommitted work. `ruff`, `vulture` and `mypy` are not installed, so no automated lint or dead-code run.

Could NOT check: anything on the VPS (switch file, `browse-engine.json`, TypeSafe key presence, deployed release, cell image); OpenClaw 2026.9.6 internals (its model-call count per run, tool registry, compaction); runtime behaviour (no test or server was executed); the `lumina/` frontend. Existing docs `docs/architecture/native-execution.md` and `docs/architecture/findings.md` were used as leads and re-verified against code where cited. `docs/orchestration-audit/` and most of `docs/architecture/` carry a "Historical" banner (pre 26 Oct 2026 native migration).

## The real agent loop (current code)

```
Browser (Lumina UI)                                   POST /v1/chat/<conv>/send  accounts/chat.py:166
  |
  v
ChatService.send                                      agentai_platform/chat.py:203
  |  steer if a run of this conversation is open      chat.py:222-228 -> steer() chat.py:265 (queueMode=steer, no new request)
  |  RequestQueue.submit  (state=waiting)             request_queue.py:61
  |  BudgetLedger.admit  (reservation + tasks row 'queued')   chat.py:243-250 -> budget.py:70-91
  v
[ SQLite: customer_requests / task_reservations / tasks ]    ONE global request_slot (request_queue.py:147-175)
  ^
  |  poll every 3 s (`manage.py request_worker`)      accounts/management/commands/request_worker.py:62-80
RequestWorker.tick -> _tick                           request_worker.py:32,46
  |  uncertain? -> reconcile/Recover                  request_worker.py:47-49,95
  |  parked?    -> check_parked/unpark                request_worker.py:50-52,108
  |  queue.claim (oldest waiting overall, lease 120s) request_queue.py:147
  |  shadow.before (optional JEV classify, record only)  request_worker.py:65 -> routing/shadow.py:44
  v
ChatDriver.execute                                    chat_driver.py:141
  |  _admit (re-check membership, reservation, task)  chat_driver.py:120
  |  _begin: abort unowned native turns, _quiesced    chat_driver.py:165-221   (gateway.active_sessions/abort)
  |  _plan_first_delivery -> _outgoing (context block, memory lines, ui tier)  chat_driver.py:223-260
  |  chat_deliveries row (idempotency key = run id)   chat_driver.py:192-197
  v
_supervise loop (<= RUN_TIMEOUT 900 s)                chat_driver.py:329
  |  _present -> _deliver -> NativeGateway.send       chat_driver.py:304 -> gateway.py:119
  |      -> BridgeRpc (unix socket) -> CellBridge.validate/dispatch  lifecycle/cell_bridge.py:279,458
  |      -> docker exec Node relay -> OpenClaw Gateway chat.send     cell_bridge.py RELAY_JS
  |  loop: gateway.wait(run, 3 s) + gateway.history   chat_driver.py:348,362  (gateway.py:134,160)
  |        mirror agent rows -> chat_messages         chat_driver.py:424-455
  |        Stop? budget? deadline? parked?            chat_driver.py:334,364-371
  v
OpenClaw run inside the customer cell (not in this repo): Sonnet 5.5 tool loop
  |  model calls -> LiteLLM relay 10.77.0.1:4000 -> provider      lifecycle/cell_config.py:17-18,43-52
  |  tools: web_search/web_fetch (Brave), exec/write, lumina_task_update, lumina_browser, lumina_browser_step
  |  before_tool_call hook writes one-use proof       lifecycle/tool_origin_plugin/index.mjs:23-50
  v
MCP over HTTP (bearer = cell's model key)             tool_relay.py:80 (Relay.handle), serve() tool_relay.py:221
  |  Identity -> bridge cell.identify                 tool_relay.py:36-60
  |  origin: bridge tools.origin -> inspect_origin    commands/tool_relay.py:21-24; tool_origin.py:62; cell_bridge.py:478-489
  |  _owner(): session+run -> admitted funded request tool_relay.py:136
  v
BrowserTool.call / step                               browse/adapter.py:261,307
  |  clean_task, 60% reservation share, 2-failure guard   adapter.py:261-289
  |  BrowseRpc('start') unix socket                   adapter.py:291-305 -> browse/service.py:158
  |  _await: poll 1.5 s, mirror browse_runs/steps     adapter.py:329
  v
BrowseService._run (root; ONE host stage Semaphore(1); engine runner|native)   browse/service.py:503,155,171
  |  BrowseRunner.run: observe -> floor rules -> ladder -> gate -> act     browse/loop.py:124-330
  |    floor (code): bot check, payment page, sign-in page, sensitive control, denied sites   loop.py:162-196,310-316
  |    Ladder.decide: JEV (1 TypeSafe call per step, text + screenshot) -> else assistant   browse/ladder.py:663,598
  |       assistant step = observation returned to Sonnet via lumina_browser_step -> service.agent_step   service.py:240,342
  |    hands: runner.mjs in a Docker stage (default)  |  native_runner.py via bridge browser.* (opt-in per account)
  v
result text back up the MCP call -> OpenClaw continues -> final reply
  v
_supervise sees agent.wait status ok -> close_gate    chat_driver.py:375,340 -> request_queue.py:286
  v
_finish: mirror, capture files, genui cards, JEV display (optional), outcome.judge   chat_driver.py:598-633; outcome.py:62
  v
_close: _reconcile_usage (LiteLLM key spend delta), ledger.settle, tasks.state    chat_driver.py:785,749
  v
queue.finish (release global slot) -> GoalChain.tick may spawn goal_continue turn   request_queue.py:195; goals.py:35
  v
Frontend polls /v1/tasks, /v1/messages (SSE built but unused: docs/architecture/findings.md F-15)
```

Model/tier facts (verified in code): one assistant model per cell, `litellm/claude-sonnet-5-5` (`cell_config.py:18`); Haiku 4.5 and Sonnet 4.6 are allowed on the key (`cell_config.py:17`) but nothing selects them. There is no per-request model router. JEV (TypeSafe `jev-1.14.0`, `browse/service_main.py:19`) is used only as (a) the browser step chooser, (b) optional shadow route classifier (`routing/shadow.py`), (c) optional display-layout chooser (`routing/display.py`). `ServiceRouter` was deleted (commit `5db9636`, per `docs/architecture/findings.md` F-13); `rg ServiceRouter` over code finds nothing.

LLM calls per customer message (Lumina's view): Lumina itself makes 0 pre-run model calls. OpenClaw makes N Sonnet calls (N unknown to Lumina; bounded only by time, spend and the 1200 s runtime backstop, see AG-007). Add: +1 TypeSafe per claim when `jev_routing` is on (repeated per re-claim, AG-012); +1 TypeSafe per plain-text answer when `jev_display` is on; per browse job 1 TypeSafe call per step (cap 120 per job, `service.py:473`, loop default 25 steps/600 s) plus one extra Sonnet tool round (page text up to 9000 chars plus a JPEG) for each step the assistant takes (`adapter.py:asking_text`); Plan mode adds 1 plan turn, at most 1 repair turn (`chat_driver.py:690`), and one request per phase; Goal mode up to 20 turns (`chat_driver.py:38`).

Context/memory/recovery: conversation context lives in the OpenClaw session (`conversations.native_session_ref`); Lumina injects only saved choices and vault labels (<=30 lines, `chat_driver.py:262-278`) and the retry note. Lumina-side memory/summarisation (`memory.py`) is not wired (AG-009). Recovery is idempotent re-delivery by run id (`chat_driver.py:378-401`), uncertain-claim reconcile (`request_worker.py:95`), outage tolerance of 90 s (`OUTAGE_LIMIT`), and container-gone detection (`_cell_gone`, `_interrupted`). Browser job state is in memory in the browse service and is lost on restart (handled: `BrowseJobUnknown`, `adapter.py:343`).

Browse paths: `browse/runner.mjs` (Playwright in a Docker stage on the host, started by `stage_argv`, `service.py:647`) is the default engine; `native_runner.py` (cell's own OpenClaw browser through bridge `browser.request`) is built but rollout-gated per account by `/etc/agentai-supervisor/browse-engine.json`, default `runner` (`service_main.py:92-101`, `platform/deploy/browse-engine.example.json`, `docs/architecture/native-browser-plan.md:6-8`). Which engine production uses is UNVERIFIED.

## File/module map

| path | responsibility | consumers/entry | notes |
|---|---|---|---|
| `agentai_platform/chat.py` (505) | Customer chat service: send, steer, goal actions, plan launch, cancel, retry | `accounts/chat.py` views | ServiceRouter remnants gone |
| `agentai_platform/request_queue.py` (292) | Durable serial queue: submit, claim, lease, park, defer, recover, close gate | `chat.py`, `request_worker.py` | one global `request_slot` |
| `agentai_platform/request_worker.py` (113) | One tick = one request; uncertain/parked first; follows PlanRunner and GoalChain | `commands/request_worker.py` (systemd `agentai-request-worker.service`) | |
| `agentai_platform/chat_driver.py` (907) | Admission, delivery, supervision, stop, settle, outcome for a request | `request_worker` | god file (AG-014) |
| `agentai_platform/gateway.py` (404) | `NativeGateway` RPC client for the cell Gateway; `SyntheticGateway` test double | driver, chat | Synthetic never in request path |
| `agentai_platform/outcome.py` (93) | Fixed-vocabulary verdict from facts Lumina holds | driver | verification only for cart pages and files |
| `agentai_platform/goals.py` (53) | `GoalChain`: admit next turn of an active goal | worker | `limit` unused (AG-015) |
| `agentai_platform/tool_relay.py` (221) | MCP-over-HTTP door for cells to Lumina tools | `commands/tool_relay.py` (`agentai-tool-relay.service`) | in-progress diff (origin v2) |
| `agentai_platform/task_progress.py` (152) | `lumina_task_update` tool (checklist widget) | relay | |
| `browse/adapter.py` (427) | `lumina_browser` and `lumina_browser_step` tool schemas, input cleaning, job mirroring | relay | |
| `browse/service.py` (654), `service_main.py` (119) | Root browse service: job table, stage slot, agent gate, takeover, purge, kill switch | `agentai-browse.service` | |
| `browse/loop.py` (465) | Observe-decide-act loop and code-side safety floor | service | `_run` 220 lines |
| `browse/ladder.py` (701) | JEV chooser, validation, hand-over to the assistant | loop | |
| `browse/{modes,candidates,goals,trace,untrusted,session,sessions,client,native_scripts}.py` | page mode choice, candidate building, goal parsing, trace, neutraliser, transport, multi-session ids, RPC client, named page scripts | loop/service/adapter | small |
| `browse/native_runner.py` (435) | Browser hands over the cell bridge | `service_main.native_spawn` | opt-in engine |
| `browse/runner.mjs` (345), `browse/test/*.mjs` | Playwright hands inside Docker stage | `stage_argv` | default engine |
| `lifecycle/cell_config.py` (317) | Cell config patch, models, tools deny, workspace rules text, provisioner | supervisor wiring | uncommitted diff |
| `lifecycle/cell_bridge.py` (583) | Root bridge: allowlisted RPCs to cell Gateway and browser | app + browse service | embeds a JS relay |
| `lifecycle/tool_origin.py`, `tool_origin_install.py`, `tool_origin_plugin/` | One-use tool-call ownership proofs (protocol 2) | bridge, provisioner | UNCOMMITTED, in progress |
| `lifecycle/{coordinator,worker,sleep,capacity,profiles,supervisor*,fleet_*,native_wiring,volumes,netpolicy,secrets_custody,litellm_admin,maintenance,workspace,types,*_cli,*_main}.py` | Cell lifecycle: slot, wake/sleep, supervisor, fleet CLI driver, firewall text, volumes, keys | lifecycle worker, supervisor | one running cell per host |
| `lifecycle/broker.py` (199) | Fixed execution envelopes for coding/review/browser stages | only `platform/deploy/p4_broker_check.py` and tests | dormant (AG-009) |
| `routing/{classifier,decision,policy,shadow,store,config,display,bench,report_cli}.py` | JEV route classifier (shadow only) and display chooser | worker (shadow), driver (display) | switches default off |
| `genui/runner.py` + `genui/*` | Plan phases as queued requests; UI block schema | worker, driver | |
| `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py`, `optimization.py`, `policy_check.py` | Objectives, memory, schedules, watchers, skills, TypeSafe gate, policy CLI | no non-test importers | AG-009 |
| `config/skills`, `config/workspace-templates`, `config/phase*`, `config/*.batch.json` | OpenClaw skills/templates/fixtures for owner phases | `test_phase10_assets.py`, `bin/phase6/*` | no runtime consumer found |
| `config/openclaw.example.json`, `litellm.example.yaml` | example configs | docs/operators | |
| `browser-opt/`, `research-opt/`, `experiments/jev-full-page/`, `evals/` | Phase 9/12 adapters, JEV experiments, acceptance cases | tests only; `experiments/` untracked | standalone |
| `docs/orchestration-audit/`, `docs/architecture/` | Historical maps; `native-execution.md` is current | humans | banner says historical |
| `platform/tests/{test_native_run,test_browse*,test_browser_tool,test_tool_origin,test_request_*,test_gateway,test_fleet_driver}.py`, `tests/e2e/` | coverage | | e2e needs OpenClaw package |

## Features

| ID | name | primary status | flags | frontend | backend | entry/flow evidence | prod verified? | notes |
|---|---|---|---|---|---|---|---|---|
| FEAT-AG-01 | Chat admission + serial queue | ACTIVE | single-lane | chat UI | `chat.py`, `request_queue.py`, `budget.py` | `accounts/chat.py:166` -> `chat.py:203` -> `request_queue.py:61` | unknown | AG-001, AG-004 |
| FEAT-AG-02 | Native run supervision (driver) | ACTIVE | gated by owner switch `customer_execution` | | `request_worker.py`, `chat_driver.py` | `commands/request_worker.py:62-77` -> `request_worker.py:32` -> `chat_driver.py:141` | unknown | |
| FEAT-AG-03 | Gateway/bridge to cell | ACTIVE | | | `gateway.py`, `cell_bridge.py` | `commands/request_worker.py:24` builds `NativeGateway(BridgeRpc)` | unknown | |
| FEAT-AG-04 | Steering a running task | ACTIVE | | send box | `chat.py:265` | `chat.py:222-228` | unknown | |
| FEAT-AG-05 | Goal mode ("keep working") | ACTIVE | `goal` flag, 20-turn cap | goal toggle | `goals.py`, `chat_driver.py:225-236,622-633` | `request_worker.py:36-43` | unknown | limit via `continue_goal`, not `GoalChain.limit` |
| FEAT-AG-06 | Plan mode + PlanRunner | ACTIVE | | plan card | `genui/runner.py`, `chat_driver.py:686` | `request_worker.py:34-43` | unknown | |
| FEAT-AG-07 | Park on customer + hand-over | ACTIVE | | Live view | `chat_driver.py:457,802`, `request_queue.py:230` | `chat_driver.py:363-366` | unknown | AG-005 |
| FEAT-AG-08 | Stop / cancel | ACTIVE with gap | | stop button | `chat_driver.py:558`, `chat.py:465` | `chat_driver.py:334` | unknown | AG-001 for waiting requests |
| FEAT-AG-09 | Outcome verdict | ACTIVE | weak verification | outcome note | `outcome.py` | `chat_driver.py:626` | unknown | AG-018 |
| FEAT-AG-10 | `lumina_browser` MCP tool + relay | ACTIVE, ownership in progress | uncommitted diff | | `tool_relay.py`, `browse/adapter.py` | `agentai-tool-relay.service:11`; `cell_config.py:68-71` | unknown (doc claims deployed 2026-10-28) | AG-006, AG-008 |
| FEAT-AG-11 | Browse service JEV + assistant ladder | ACTIVE | owner switch `browse_tasks` | Live view | `browse/*` | `adapter.py:301` -> `service.py:158` -> `loop.py:124` | unknown | AG-002, AG-003 |
| FEAT-AG-12 | Host Docker engine (`runner.mjs`) | ACTIVE (default) / LEGACY-planned | per-account engine file | | `runner.mjs`, `service.py:647` | `service_main.py:92-101` default `runner` | unknown | planned for deletion once native rolls out |
| FEAT-AG-13 | Native browser engine | INCOMPLETE (built, rollout gated) | per-account | | `native_runner.py`, bridge `browser.*` | `service.py:171` | unknown | docs: no account switched by design |
| FEAT-AG-14 | JEV shadow routing | EXPERIMENTAL | switch `jev_routing` default off | | `routing/shadow.py` | `request_worker.py:65` | unknown | records only; AG-012 |
| FEAT-AG-15 | JEV display layout | EXPERIMENTAL | switch `jev_display` default off | cards | `routing/display.py` | `chat_driver.py:620-621` | unknown | sends reply text to TypeSafe |
| FEAT-AG-16 | Phase 12 optimisation gate + billing | ORPHANED | | | `optimization.py` | no importer (rg) | n/a | AG-003 |
| FEAT-AG-17 | Objectives, memory, schedules, watchers, skills | ORPHANED / INCOMPLETE | urls return `disabled` | "coming soon" | `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py` | `accounts/urls.py:24-25` | n/a | class C |
| FEAT-AG-18 | Policy check CLI | ORPHANED | | | `policy_check.py:83` | none found | n/a | |
| FEAT-AG-19 | Worker broker | ORPHANED (operator check only) | | | `lifecycle/broker.py` | `platform/deploy/p4_broker_check.py:10` | n/a | |
| FEAT-AG-20 | Tool-origin protocol 2 | EXPERIMENTAL / in-progress | UNCOMMITTED | | `tool_origin*.py`, plugin | `cell_config.py:62-64,137-153` | unknown | |
| FEAT-AG-21 | `lumina_task_update` progress tool | ACTIVE | | task widget | `task_progress.py` | `commands/tool_relay.py:22` | unknown | |
| FEAT-AG-22 | Cell wake/sleep, one cell per host | ACTIVE | capacity default 2 | | `lifecycle/worker.py`, `sleep.py` | `worker.py:158` | unknown | AG-004 |
| FEAT-AG-23 | Browser safety floor (code rules) | ACTIVE | per-account safety switches | | `browse/loop.py:162-196` | `loop.py:310` | unknown | owner/granted accounts only can switch off |
| FEAT-AG-24 | ServiceRouter-first routing | LEGACY (deleted) | | | none | commit `5db9636` | n/a | stale docs AG-016 |
| FEAT-AG-25 | `browser-opt/`, `research-opt/`, `experiments/`, `evals/` | EXPERIMENTAL | `experiments/` untracked | | standalone | tests only | n/a | |
| FEAT-AG-26 | `config/skills`, workspace templates, phase fixtures | UNKNOWN | | | | `test_phase10_assets.py:26`; `bin/phase6/*` | n/a | may be installed by hand on the owner host |

## Findings

**ID**: AG-001 | **Category**: budget/resource leak, correctness | **Severity**: High | **Confidence**: MEDIUM | **Effort**: S
A request cancelled while still `waiting` never gets its reservation settled or its `tasks` row closed. `RequestQueue.cancel` only updates `customer_requests` (`request_queue.py:107-115`); `ChatService.cancel` adds only a goal pause (`chat.py:465-470`). The only code that settles or closes tasks is `ChatDriver._close` (`chat_driver.py:785-799`), which a never-claimed request does not reach; `claim` skips cancelled rows. `rg "UPDATE tasks"` shows no writer for a cancelled waiting task (`chat_driver.py:138,796`, `request_queue.py:238,246,262`). Consequences by reading code: (1) the `active` reservation stays in `_holds` (`budget.py:52-58`) and counts against daily/period/service caps; (2) the `tasks.state='queued'` row counts toward `max_queued_tasks` (`budget.py:79`), so repeated cancels can produce "queue full"; (3) `lifecycle/worker.py:59` counts `queued` tasks, so `can_sleep` (`sleep.py:33`) stays false and that account's cell never idles down, blocking handover to other accounts (see AG-004). `tests/test_chat.py:134` asserts the waiting cancel only checks state, not the reservation. Same gap noted as F-06 in `docs/architecture/findings.md`; still present. Runtime impact: silent loss of the customer's allowance and a stuck cell; recovery only via `ops/restore.py:157`. Action: F (settle reservation and close task inside `cancel` for waiting requests; add test). Risk: low, but touches billing ledger; use `ledger.settle` semantics.

**ID**: AG-002 | **Category**: privacy / data egress | **Severity**: High | **Confidence**: HIGH (code) / prod UNVERIFIED | **Effort**: M
Every JEV browser step sends a JPEG screenshot of the customer's browser window to `api.typesafe.ai`, in addition to scrubbed text. `loop.py:210-216` sets `look.shot` on every step whenever the runner reports a window; `ladder.py:606` makes `sight = shot and candidates`, and `JevChooser.choose` attaches the base64 image with header `TypeSafe-Danger-Zone-Images` (`ladder.py:38,330-337`). `privacy.scrub` redacts text only (`privacy.py`); pixels cannot be scrubbed. The `personal_data_scrub` switch description says only "page text and labels" (`safety.py` Feature list). Sign-in and payment pages stop before any model (`loop.py:184-196`), which limits but does not remove exposure (cart pages, order summaries, addresses, account pages). Per the owner's privacy priority this is the main data-leak path in scope. Whether the TypeSafe key is installed in production is UNVERIFIED (`service_main.py:72-77` returns no JEV without the key file, then every step goes to the assistant). Action: C/F (decide: send images only when no controls are listed, or only on opt-in; document in the switch text and privacy notice). Risk: changes JEV accuracy on covered pages (`modes.choose_mode` already distinguishes picture-needed pages).

**ID**: AG-003 | **Category**: consent gate not wired, doc drift | **Severity**: High | **Confidence**: HIGH (code) | **Effort**: M
The owner switch `browser_optimization` ("Page text and element labels are sent to TypeSafe", `switches.py:42-49`, needs fact `browser_route_deployed` "not yet") and the four-layer `OptimizationGate` (`optimization.py`, header says DISABLED) have no importer outside tests (`rg` over `agentai_platform`, `accounts`: only `switches.py:254` adapter, itself unused). The live browse path gates TypeSafe only on the key file and `--jev-mode` (default `live`, `service_main.py:37,52`; `jev_for`, `service_main.py:72-77`). The only live kill switch is `browse_tasks` (`service_main.py:109`). So the consent/data-handling confirmation recorded by the owner switch does not control the live egress, and the documented "DISABLED" gate gives a false sense of control. `routing/shadow.py` and `routing/display.py` do honour their own switches (`jev_routing`, `jev_display`). Action: C (wire `browser_optimization` into `jev_for`, or retire the switch and gate; update docs). Risk: switching it on enforcement would disable JEV until owner confirms.

**ID**: AG-004 | **Category**: scalability / availability | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: M
The whole host is one lane: one `request_slot` for all accounts (`request_queue.py:147-175`), one active cell (`lifecycle_slot`, `coordinator.py:237-262`, `sleep.py:3-5`), one browser stage `Semaphore(1)` for the runner engine (`service.py:155,498-501`). `claim` only examines the oldest waiting request overall and returns None if its account is not the cell holder (`request_queue.py:157-168`); it does not skip to the holder's own newer request. Handover waits for the holder to be idle: 60 s when someone else waits, else 900 s (`worker.py:158`, `sleep.py:12`) and requires `queued_tasks==0` and no `waiting_for_approval/paused/browsing` (`worker.py:56-60`). Possible stall (by reading, not exercised): account X holds the cell and finishes; account Y (older) waits; X sends another message, which is newer than Y so cannot be claimed, yet its `tasks` row is `queued`, so X's cell cannot sleep, so Y's start waits (`coordinator.py:230-234` `capacity_wait`). Only X cancelling (and then AG-001 leaves a queued task) or an operator breaks it. A parked request (customer must answer a browser question) also keeps the cell and holds others out up to `PARK_LIMIT` (see AG-005). Matches `docs/architecture/findings.md` F-10 (private-beta limit). Action: C/E (decide whether private-beta single lane is intentional; at least let `claim` serve the holder's account when the head request belongs to a waiting account, or count only started tasks in `can_sleep`). Risk: touches the core scheduling invariant.

**ID**: AG-005 | **Category**: unbounded wait / dead limit | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: S
`PARK_LIMIT` (1800 s) does not stop a run. `check_parked` returns `'ended'` when the limit passes (`chat_driver.py:817-819`); the worker then `unpark(need_slot=False)` and calls `driver.execute` (`request_worker.py:101-108`), which goes to `_reassert` then `_supervise`. The run is still live, `_human_wait` is still true, so `_supervise` returns `Parked` again (`chat_driver.py:363-366`) and `queue.park` resets `parked_epoch` (`request_queue.py:230-238`). The docstring ("waited too long: close it") and the test (`test_native_run.py:198-201`, asserts only the string `'ended'`) hide this. In practice the browse service bounds a question to `ASK_SECONDS` 300 and a pause to `takeover_seconds` 600 (`service.py:93,384-386,292`), after which the job leaves asking/paused and the poll loop ends, so the effective hold is minutes, not unbounded. Action: D (on 'ended' by timeout call the stop path: abort run, stop browser job, close). Risk: low.

**ID**: AG-006 | **Category**: release provenance, in-progress work | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: S
Uncommitted work (tool_origin v2, relay busy-lanes, cell_config hook wiring, e2e harness) is described as deployed: `docs/browser-tool-ownership.md` (untracked) says release `20261028T212308Z-tool-origin-v2` is live and verified by manifest, while `git status` shows `tool_origin.py`, `tool_relay.py`, `cell_bridge.py`, `cell_config.py`, the plugin dir and `tool_origin_install.py` modified or untracked, with HEAD `03662de` not containing them. If true, production runs code that has no commit; rollback/forensics depend on a saved manifest outside git. The older doc `docs/browser-reliability.md` still describes the transcript/SQLite reader in "Trust boundary" (modified, adds only an update note). Production state UNVERIFIED. Action: G/E (commit the in-progress work; make that section match protocol 2). Risk: none to code.

**ID**: AG-007 | **Category**: resource/cost control | **Severity**: Medium | **Confidence**: HIGH | **Effort**: M
Lumina cannot cap or count the assistant's model calls or tool rounds. The limits are wall clock 900 s (`chat_driver.py:34`), a runtime backstop `timeoutSeconds` 1200 (`cell_config.py:21,53`), and a spend check every 20 s against the account's LiteLLM key delta. `_over_budget` fails open: it returns False if `usage_snapshot` raises, if no baseline was read, or if no reservation exists (`chat_driver.py:478-490`). `_usage_before` also returns None on any error (`chat_driver.py:464-471`). Because the key is per account and one request runs at a time this is accurate when it works, but a transient LiteLLM error removes the spend guard for the whole run; the remaining backstops are the time limit and provider-side caps (UNVERIFIED). No max-tool-rounds or max-turns setting is applied in `cell_config.patch`. Action: F (treat repeated snapshot failure as a stop or alert; consider a turn cap). Risk: could abort healthy runs if LiteLLM is flaky.

**ID**: AG-008 | **Category**: error handling (in-progress work) | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: S
UNCOMMITTED. When the origin proof cannot be verified for any reason, the assistant is told one fixed sentence: "does not belong to an admitted live task ... Do not retry this call in another task" (`tool_relay.py:120-122`); reasons (`proof_missing`, `proof_unavailable`, `origin_service_unavailable`, `admission_mismatch`) go only to the server log (`tool_relay.py:119`). A transient bridge error therefore tells the model to stop using the browser for the run. On the provisioning side, `before_start` wraps `ensure_tool_origin` in `except Exception: pass` (`cell_config.py:183-188`) while `finish` calls it unguarded (`cell_config.py:309`), so a failed hook install is silent on restart but fatal on creation. A cell without the hook fails closed (all `lumina_*` calls refused), which is safe but invisible to operators. Action: D/F (differentiate transient vs ownership refusals in the tool text; emit an event when install fails). Risk: low.

**ID**: AG-009 | **Category**: dead/orphaned code (product decision) | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
Modules with no importer outside tests, checked with `rg` for imports, class names (`ScheduleService`, `MemoryService`, `SkillService`, `WatcherService`, `ObjectiveService`, `OptimizationGate`), `urls.py`, `platform/deploy/*.service`, `bin/`, management commands and `importlib`/string registries: `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py`, `optimization.py`, `policy_check.py` (has `main()` at `:83`, no entry point or unit calls it). `accounts/urls.py:24-25` routes `memory`, `schedules`, `controls`, `integrations` to a generic `disabled` view; tables exist in migrations and `ops/restore.py:20` lists them. `lifecycle/broker.py` is imported only by tests and `platform/deploy/p4_broker_check.py:10`. `config/skills/*`, `config/workspace-templates/*`, `config/phase{4,10,11}-fixtures` have no runtime consumer (tests `test_phase10_assets.py`, `bin/phase6/*`); they may be hand-installed on the owner host (UNKNOWN). Action: C (preserve value; these are unfinished product features, not deletions). Risk: removing breaks tests and the restore table list.

**ID**: AG-010 | **Category**: duplication | **Severity**: Medium | **Confidence**: HIGH | **Effort**: M
The private-address / SSRF policy is implemented four times: `browse/runner.mjs` (`privateIp`, line ~18), `browse/native_runner.py:34-60` (`private_ip`, `url_allowed`), `ssrf.py`, and `lifecycle/netpolicy.py:18` (`PRIVATE_RANGES`). Page-side logic is also written twice: `runner.mjs` and the named scripts in `native_scripts.py` (182 lines), which must stay behaviour-equal for the two engines. Any rule change (for example the CGNAT 100.64/10 range) has to land in all places and tests are separate (`browse/test/runner.test.mjs:226`, `tests/test_native_runner.py:97`, `e2e/test_native_browser.py:235`). Action: B after the engine decision (AG-013 follow-up); until then add a shared test vector. Risk: medium (security-sensitive).

**ID**: AG-011 | **Category**: resource leak | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
`BrowseService.jobs` is only ever inserted into (`service.py:172`); no `pop`/`del` exists (`rg "self.jobs"` shows reads only), and `_account_slots` grows per account (`service.py:501`). Each `Job` keeps its event list. `purge` deletes screenshot folders but not job objects (`service.py:443-459`). The service is a root long-lived process with `MemoryMax=384M` (`agentai-browse.service`). Growth is slow (small objects) but unbounded; restart clears it. Action: D (evict finished jobs after the retention period). Risk: low; polls for old job ids would return `BrowseJobUnknown`, which the adapter already handles.

**ID**: AG-012 | **Category**: extra LLM calls / privacy | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
With switch `jev_routing` on, `ShadowRouter.before` runs on every claim (`request_worker.py:65`). A `Defer` (session still owned by another run, `chat_driver.py:181-188`) puts the request back to waiting (`request_worker.py:75-77`), is re-claimed on the next 3 s tick, and starts a new classification thread each time. Each call sends the sanitised customer message to TypeSafe and writes a route row. `_started`/`_threads` also leak for requests that never reach `after()` (Defer, Parked, exception) (`routing/shadow.py:47-48`). Switch default is off. Action: D (classify once per request id). Risk: none.

**ID**: AG-013 | **Category**: performance (slot held) | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
`_reconcile_usage` polls the LiteLLM spend up to `usage_wait=45` s with 0.25 s sleeps while the global slot is still held (`chat_driver.py:749-777`, slot freed in `queue.finish`). When spend does not rise (a failed or cancelled run with no model call) it waits the full 45 s. Action: D. Risk: low.

**ID**: AG-014 | **Category**: god files / functions | **Severity**: Low | **Confidence**: HIGH | **Effort**: L
`chat_driver.py` 907 lines (about 45 methods), `browse/ladder.py` 701, `browse/service.py` 654, `lifecycle/cell_bridge.py` 583 (includes an embedded JS relay string), `browse/loop.py` `_run` is a single 220-line function (`loop.py:124-343`) holding the whole safety floor. These are the highest-risk safety paths; the size makes review and unit isolation hard. Action: E (extract floor rules into a pure function). Risk: medium; do with the existing test suites.

**ID**: AG-015 | **Category**: dead symbols | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
`GoalChain.limit` is stored but never read (`goals.py:26`; the cap is enforced by the driver through `continue_goal`, `chat_driver.py:625`); the constructor argument at `commands/request_worker.py:48` is therefore decorative. `import hmac` in `tool_relay.py:14` is unused (`rg "hmac\."` finds no call). Action: A. Risk: none.

**ID**: AG-016 | **Category**: doc drift | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
(1) `CLAUDE.local.md` still lists `ServiceRouter.choose` as a blind-spot and `test_service_handoff.py`; neither exists (`ls platform/tests/test_service_handoff.py` fails; F-13 and `docs/orchestration-audit/08-inconsistencies.md` I-18). (2) the `native_runner.py` module docstring calls the Playwright runner "retired", but it is the default engine (`service_main.py:92-101`, `OPERATIONS.md` "Browser engine"). (3) `browse/__init__.py` says production wiring lives outside the package; it lives in `service_main.py`. (4) `docs/browser-reliability.md` trust-boundary section describes the superseded reader (AG-006). (5) The switch text for `browser_optimization` and the `OptimizationGate` docstring say the feature is disabled while the live path uses TypeSafe (AG-003). (6) `docs/orchestration-audit/` is bannered Historical but still diagrams ToolDecider/Pursuit. Action: G. Risk: none.

**ID**: AG-017 | **Category**: test gaps | **Severity**: Low | **Confidence**: HIGH | **Effort**: M
`tests/e2e/test_native_e2e.py:23` skips unless the pinned OpenClaw package exists; `test_native_browser.py:56` additionally needs Chrome; `test_browse.py:547` requires a macOS Chrome path (`/Applications/Google Chrome.app`), so on Linux CI these never run (the doc says 2 skips of 1011 tests locally). The real-gateway checks of the hook and the real-browser engine therefore have no automated CI coverage. No test asserts that a waiting cancel settles the reservation (AG-001) or that `PARK_LIMIT` expiry ends the run (AG-005). `tool_origin_plugin.test.mjs` is untracked. Action: D. Risk: none.

**ID**: AG-018 | **Category**: completion validation | **Severity**: Medium | **Confidence**: HIGH | **Effort**: M
Completion is the runtime's `agent.wait ok` plus a last reply; `outcome.judge` verifies only a cart URL plus a changing add-to-cart click, or a saved file (`outcome.py:36-60,74-93`). For every other task the verdict is `completed / not_applicable / 'Done.'` and the assistant's own claim is not checked (the module says so). The Pursuit/verification layer was removed in the native migration (F-11, `plans/pursuit-architecture.md`). Not a bug; a product-level gap against any "planning/supervision" expectation: supervision here is time, spend, Stop and goal state only. Action: C. Risk: n/a.

**ID**: AG-019 | **Category**: security hygiene (in-progress) | **Severity**: Low | **Confidence**: LOW | **Effort**: S
UNCOMMITTED. `inspect_origin` checks mode, link count, size and age of the proof file but not its owner (`tool_origin.py:62-90`), and the plugin directory is owned by the cell user. A prompt-injected assistant with `exec` (sandbox off) could write a well-formed proof for its own live run. This gains nothing across accounts (root is per tenant, binding is to the caller's own account) and the doc states the cell runtime is trusted for its own identity (`docs/browser-tool-ownership.md`), so the control defends against misattribution between runs, not against a hostile cell. Action: G (note only; optionally require uid 1000 and nonce freshness). Risk: none.

**ID**: AG-020 | **Category**: error handling | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
Twenty `except Exception` blocks in `chat_driver.py`, many `pass`. Most are deliberate and commented (event writes, file capture, display), but `_stop_browser_jobs` and `_release_waiting_browser_jobs` swallow every failure (`chat_driver.py:515-546`), including a failed cancel. Cover: the relay thread also stops the job when its connection drops or the request ends (`adapter.py:_await` via `_ended`), and `_interrupted` requires confirmed stop (`chat_driver.py:875`). Residual risk is a browser job staying in the single stage until its own limits (600 s). Action: F (log a counter on failure). Risk: none.

**ID**: AG-021 | **Category**: security claim scope | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: M
The assistant keeps OpenClaw's full local toolset in the cell: `sandbox.mode off` and `tools.deny` is only `ask_user` and `browser` (`cell_config.py:25,53-56`), plus the shared Brave search key. The workspace rules and tool text say the assistant "can never press a payment or order button" and "the customer places the order" (`cell_config.py` WORKSPACE_RULES, `adapter.py` tool description). That guarantee is enforced in code only inside `lumina_browser` (`loop.py:162-196`). Anything else in the cell (`exec`, `web_fetch` to an API) is bounded by container isolation and the egress firewall (`netpolicy.py`), whose production state is UNVERIFIED. Action: C/F (state the scope precisely; consider denying `exec`/network tools for accounts that need strong "no purchase" assurance). Risk: capability loss.

**ID**: AG-022 | **Category**: performance | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
`BrowserTool._await` runs a write transaction (`_mirror` UPDATE plus step inserts) and a read (`_ended`) every 1.5 s for the life of each tool call, up to 900 s (`adapter.py:329-380`, `_mirror` `:392`), on the same SQLite file as the queue and ledger. `_supervise` adds `agent.wait` + `chat.history` RPCs every 3 s (`chat_driver.py:348,427`). Fine at beta scale; a contention point if the lane is widened. Action: G. Risk: n/a.

## Looks bad but is fine

1. `SyntheticGateway` lives in `gateway.py` next to the real client. It is a deterministic test double (`gateway.py:238`); the worker entry point builds only `NativeGateway` (`commands/request_worker.py:24`), so no fake run can reach customers.
2. `_supervise` has a `while True` that can `continue` without sleeping (`chat_driver.py:340-342`). `close_gate` returns False only when a live delivery exists, so the next iteration owns a delivery and blocks in `gateway.wait` (3 s slices); there is no hot spin. All other waits are bounded (`RUN_TIMEOUT`, `OUTAGE_LIMIT`, `PARK_LIMIT` caveat in AG-005, `_abort_all` 30 x 1 s).
3. Cell `noSandbox: True` and `evaluateEnabled: True` (`cell_config.py:32-35`) look dangerous. The assistant cannot call the browser tool (denied), the bridge accepts only named scripts and fixed routes (`cell_bridge.py:34-37`, `native_scripts.py`), the address policy is reset at every start, and the browser is reachable only by root (`cell_bridge.py:458-461`).
4. `except Exception: pass` around `shadow.before/after`, event writes and file capture looks like swallowed errors. These are explicitly optional observers whose failure must not affect the customer task (`request_worker.py` class docs, `routing/shadow.py` header, `chat_driver.py:78-85`).
5. Two browse engines and two ownership mechanisms (`runner.mjs` and `native_runner.py`; old transcript matcher and proof hook). The first pair is a staged rollout with a per-account switch and documented plan; the second is in-progress uncommitted replacement work (see AG-006), not accidental duplication.
6. `RUN_TIMEOUT` 900 s vs `RUN_BACKSTOP_SECONDS` 1200 vs MCP `requestTimeoutMs` 1,200,000 vs browse job 600 s: layered on purpose, the outer values are backstops for a dead supervisor (`cell_config.py:19-21`).
7. The `_known_about` memory lines and vault labels injected into every prompt are neutralised and contain labels only, never secrets (`chat_driver.py:262-278`).

## Cross-scope links

- Frontend/API: `POST /v1/chat/<conv>/send` (`accounts/chat.py:166`), cancel `accounts/chat.py:224`, `v1/browse/<id>/{release,pause,resume,answer,live,shot}` and `v1/safety*`, `v1/vault*` (`accounts/urls.py:63`) drive the hand-over and safety floor; authz of these views belongs to the backend scope. Frontend polls tasks/messages (SSE unused).
- AG-001 needs backend (`budget.py`, `ops/restore.py`) and the lifecycle scope: the leaked `queued` task also blocks `lifecycle/worker.py:facts`.
- systemd: `agentai-request-worker.service:11`, `agentai-tool-relay.service:11` (binds `10.77.0.1:4100`, `settings.py:116-117`), `agentai-browse.service` (root, `MemoryMax=384M`), `agentai-cell-bridge.service`, `agentai-supervisor-native.service`. Cells reach the relay over the host bridge address; Caddy/live frames path is separate (`live/gateway.py`, `platform/deploy/LIVE_VIEW.md`).
- Config files read at runtime: `/etc/agentai-supervisor/browse-engine.json`, `native-wiring.json`, `/var/lib/agentai-platform/safety-switches.json`, `SWITCHES_FILE` (all UNVERIFIED), `ROUTING_CONFIG_FILE` (`settings.py:111`), TypeSafe key file.
- External: TypeSafe `api.typesafe.ai/v1/systemone` (JEV), LiteLLM relay `10.77.0.1:4000`, Brave search key, OpenClaw 2026.9.6 image pin.
- Deploy script `bin/deploy-lumina.py` deploys release trees; the uncommitted tool_origin files must be included or the cell hook is missing (AG-006).

## Open questions for the maintainer

1. Is the single global lane (one request, one cell, one stage) the intended beta design, and is the X/Y stall in AG-004 reproducible with two accounts?
2. Is the TypeSafe key installed in production, and was the owner's consent recorded for sending screenshots as well as text (AG-002, AG-003)? Should `browser_optimization` gate it?
3. Which engine does `/etc/agentai-supervisor/browse-engine.json` select in production; are any accounts on `native`?
4. Is tool-origin v2 really deployed from the uncommitted tree (AG-006), and will it be committed before the next release?
5. Should a cancelled-while-waiting request settle its reservation immediately (AG-001), or is a periodic reaper intended?
6. Are `config/skills`, workspace templates and phase fixtures installed into owner cells by hand, or are they dead assets?
7. Do you want an LLM-call or tool-round cap per run (AG-007), or is time plus provider-side cap sufficient?
8. Is Plan/Goal/Telegram behaviour enabled in production, and which owner switches are on (`customer_execution`, `browse_tasks`, `jev_routing`, `jev_display`)?
