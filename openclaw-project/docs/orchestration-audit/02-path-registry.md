# Orchestration path registry

Every orchestration path found, one record each. Identifiers (`P01` and so on) are used in all diagrams and tables.
Paths are relative to `openclaw-project/` unless they start with `~` or `../` (outside it). `wt` = working tree (uncommitted), `HEAD` = commit `5db9636`.

**Status vocabulary** (as requested): *Current and reachable*, *Reachable under specific configuration* (needs an owner switch or setting), *Implemented but disabled*, *Apparently unreachable*, *Legacy but still partially active*, *Superseded*, *Experimental or prototype*, *Test-only or mock*, *Documentation-only*, *Deleted but recoverable from history*, *External and not inspectable*, *Uncertain*.

**Production caveat.** "Reachable" describes the checked-out code. Deployment evidence exists only in `RELEASE_NOTES.md` (also modified in the working tree), which says releases live9 to live24 were deployed from the uncommitted working tree on 14 to 21 Oct 2026, with `jev_services` on, `browse_tasks` and `customer_execution` on, `pursuit` and `jev_display` off, and the browse service in `--jev-mode live`. The server itself was not inspected, so production state after 21 Oct is unknown.

## Summary by status

| Status | Count | Paths |
|---|---|---|
| Current and reachable | 6 | P16 P18 P19 P21 P22 P23 |
| Reachable under specific configuration | 13 | P01 P02 P03 P04 P05 P06 P09 P10 P11 P13 P14 P17 P20 |
| Implemented but disabled | 4 | P07 P15 P27 P28 |
| Apparently unreachable | 6 | P08 P29 P30 P31 P32 P33 |
| Legacy but still partially active | 2 | P12 P34 |
| Superseded | 1 | P35 |
| Deleted but recoverable from history | 2 | P36 P37 |
| Experimental or prototype | 2 | P38 P39 |
| Test-only or mock | 2 | P41 P42 |
| Documentation-only | 1 | P40 |
| External and not inspectable | 3 | P24 P43 P44 |
| Uncertain | 3 | P25 P26 P45 |
| **Total distinct paths** | **45** | |

The final report's counts are taken from this table. Each record's **Status** line is authoritative; update both if a record changes.

---

## A. The customer chat engine (current)

### P01 Auto-mode chat with the assistant-first tool protocol
- **Status:** Reachable under specific configuration. Needs `customer_execution` (execution on) and an active cell. On in production per release notes.
- **Purpose:** Answer an ordinary message with the customer's own assistant; let it ask Lumina for a browser or search step.
- **Entry:** `POST /v1/conversations/<id>/send` with `mode: auto` (`accounts/chat.py:chat_send` 162). The Composer's Tools menu and Home tiles only prefill text (`lumina/src/components/Composer.tsx:57`).
- **Chain:** `ChatService.send` (`agentai_platform/chat.py:224`) → `RequestQueue.submit` (`request_queue.py:42`) → `BudgetLedger.admit` → worker `claim` (126) → `ChatDriver.execute` (584) → `agent_protocol.preamble` (163) prepended when `_agentic` (873) → `gateway.send` → poll loop `_poll` (1300) → `lumina-step` handling `_answer_step` (897) → `_close` (559) → `queue.finish` (172).
- **Decision owner:** assistant model (what to answer, whether to ask for a step); app code (everything else).
- **Models and tools:** `litellm/claude-sonnet-5-5` in the cell (`lifecycle/cell_config.py:16`); OpenClaw built-in tools (not enumerable from Lumina); Lumina tools `browser`, `search`.
- **State:** `customer_requests`, `chat_messages`, `chat_deliveries`, `tasks`, `task_reservations`, `events`.
- **Completion:** agent replied and runtime idle twice (`SETTLE_POLLS`, `chat.py:41`); result is the last agent message.
- **Failure and recovery:** lease expiry → `uncertain` → reconcile or abandon (P18). Run limit 900 s.
- **Relations:** shares the engine with P02, P03, P09, P10, P11. Uses P05, P06, P16, P19, P20, P24.
- **Confidence:** high. **Unknown:** what the assistant does inside the cell.

### P02 Text-mode chat
- **Status:** Reachable under specific configuration.
- **Entry:** `mode: text`. `ChatService.send` submits `context={'mode':'text'}`; `_agentic` returns false so no preamble, no `lumina-step`, no JEV (`chat.py:224,873`).
- **Chain:** as P01 without the tool protocol; `genui.runtime.outgoing` returns the plain message (plus quoted history only for a new session, `genui/runtime.py:74`).
- **Relations:** The assistant still has its own tools inside the cell (P24).

### P03 Plan mode and the plan runner
- **Status:** Reachable under specific configuration (`customer_execution`).
- **Entry:** `mode: plan` → intent `plan`. Block routes `/v1/blocks/<id>/{state,submit,launch,live,phase,stop}` (`accounts/genui.py`).
- **Chain:** `ChatDriver.execute` builds `gen_prompts.plan_prompt` (`genui/prompts.py:11`) → reply validated `GenUiRuntime.validate_reply` (`runtime.py:76`) with one repair prompt (`chat.py` plan branch) → `attach_plan` (86) → customer edits (`block_state`) → `ChatService.launch_plan` (322) stores approved revision → `PlanRunner.start/advance/tick` (`genui/runner.py:61,72`) creates **one request per enabled phase** via `queue.submit` (intent `phase`).
- **Decision owner:** assistant drafts; customer edits and approves; code enforces `requiresApproval` (`runner.py:91-95`) and dependency order.
- **State:** `ui_blocks`, `plan_revisions`, `plan_launches`, `plan_phase_runs` (states in `0018_plan_runs.sql:8`).
- **Completion:** all phases `completed` or `skipped` (`runner.py:82,131`). A failed phase waits for retry or skip (`runner.py:164-175`).
- **Relations:** each phase re-enters P01's engine. Forms feeding it are P08.

### P04 Browse-mode request (browser only)
- **Status:** Reachable under specific configuration (`customer_execution` and `browse_tasks`; the Browse option is hidden otherwise, and the server downgrades it to chat, `chat.py:send`).
- **Chain:** intent `browse` → `execute` → `_execute_browse` (742) → `_run_browse` (776) → `BrowseRpc` → browse service → result mirrored; if the cell is available and the run met a verification wall, the assistant takes over with `_with_service_note` (1172) and continues as P01.
- **Needs no cell:** `queue.claim` skips the cell check for intent `browse` (`request_queue.py:145`).
- **Relations:** P05 is the same browser engine. P13 controls it.

### P05 Assistant-requested browser step
- **Status:** Reachable under specific configuration (`browse_tasks`; `jev_services` optional; browse service `--jev-mode live` in production per release notes).
- **Chain:** `lumina-step` → `agent_protocol.clean` (44) → `ToolDecider.choose` (`routing/tools.py:68`) → `_browse_for_assistant` (1138) → `_run_browse` → `BrowseService._run` (`browse/service.py:443`) → `BrowseRunner.run` (`browse/loop.py:105`) with `Ladder` (JEV, Haiku, Sonnet) → result back via `agent_protocol.result_message` (201).
- **Limits:** one browser session per message unless P07; 25 steps and 600 s per job (`loop.py:79`), capped at 40 and 900 s (`service.py:179`); one job at a time host-wide (`service.py:166`, `Semaphore(1)`).
- **Controls:** code rules before models (payment, sign-in, human check, denied domains), `Policy.read_only`.
- **Recovery:** jobs live in service memory; a restart makes `poll` raise `BrowseJobUnknown` and the request ends at once (`chat.py:_run_browse`).

### P06 Assistant-requested search step
- **Status:** Reachable under specific configuration.
- **Chain:** `lumina-step` → `ToolDecider.choose` returns `search` → message to the assistant telling it to use `web_search` and `web_fetch` itself (`chat.py:_answer_step`, `_pursue_step`). No Lumina-side search call exists; the assistant's search runs in the cell with the Brave plugin (`cell_config.py:setup_search` 200).

### P07 Pursuit (stored plan, multiple browser sessions, verification)
- **Status:** Implemented but disabled. Owner switch `pursuit`; `live18` notes say it is off.
- **Chain:** `_pursue_step` (963) → `pursuit.from_block/apply_revision/select_step` → `_run_browse` per session with `browse/sessions.py` job ids → `browse/review.py` progress reviews inside the browser loop → `_settle_pursuit` (1039) → `pursuit.verify` and `next_action` (592) → `_result_for_assistant` (1074) → `_close_pursuit` (1102).
- **Limits:** `PURSUIT_MAX_ROUNDS = 12` (`chat.py:43`), browsing share 60% of the task budget, `STOP_NO_PROGRESS`.
- **State:** `pursuit_state`, `browse_sessions` (0026), statuses in `pursuit.py:14`.
- **Decision owner:** assistant writes every step; code decides whether another is allowed and how results are described.

### P08 Form block submit
- **Status:** Apparently unreachable for new forms. The route and UI exist (`accounts/genui.py:block_submit`, `ChatService.submit_block` 297, `lumina/src/components/genui/FormBlock.tsx`), but no non-test code creates a form block: `create_form` has no callers outside tests, and the keyword detector that did (`gen_intent.detect` + `_local_form`) is gone from the working tree (still in HEAD). Only forms already stored can be submitted.
- **Evidence:** `genui/store.py:61`; `genui/intent.py` (only `website_form`, used by `accounts/test_chat.py:330`); `git show HEAD:…/chat.py` lines 207 to 237.

### P09 Retry and resume
- **Status:** Reachable under specific configuration.
- **Chain:** `POST /v1/requests/<id>/retry` → `chat_retry` (rate-limited, `accounts/chat.py:233`) → `ChatService.retry` (405) → `_spawn` (271) with key `retry-<id>-<n>` → new request with `retry_of` (`request_queue.py:110-123`). With `pursuit` on, `_resume_state` (928) seeds the new run from the old plan (looks back at most 3 requests).
- **Completion:** same as P01. Idempotent: a repeat press returns the existing retry.

### P10 Telegram inbound
- **Status:** Reachable under specific configuration (`TELEGRAM_ENABLED`, webhook secret, linked chat). Activation on the server is unverified.
- **Chain:** `POST /v1/telegram/webhook` → `accounts/telegram.py` → `TelegramService` (`agentai_platform/telegram.py`) → slash commands handled locally; other text → `ChatService.send(provenance='telegram', key='tg'+update_id)` (`telegram.py:298`) → engine of P01, **but** `_agentic` returns false for telegram provenance (`chat.py:873`), so no `lumina-step` loop.
- **Outbound:** only replies to commands go through `telegram_outbox` and `manage.py telegram_worker` (`telegram.py:117-153`). No path was found that sends a finished task's result to Telegram.

### P11 Classic chat page
- **Status:** Reachable under specific configuration (same switch as P01).
- **Chain:** `/account/chat/` (`ch.chat_page`) posts form-encoded to the same `chat_send` handler (`accounts/views.py:endpoint` redirect logic) → P01.

### P12 Classic Requests page (`POST /v1/requests`)
- **Status:** Legacy but still partially active.
- **Chain:** `accounts/requests.py:requests` → `RequestQueue.submit` directly: **no conversation, no chat message, no budget reservation**. The worker claims it, finds no active reservation and fails it as unfunded (`request_worker.py:_tick`). `ChatDriver.execute` would also refuse (`conversation_id is None`, `chat.py:585`).
- **Effect:** an item that consumes one of the three waiting slots and then fails with "could not be funded or started". Rate limit: `task.create` 30 per hour (`requests.py:25`).
- **Evidence:** `accounts/requests.py:16-28`; `agentai_platform/request_worker.py` unfunded branch.

### P13 Browser job control and answers
- **Status:** Reachable under specific configuration.
- **Endpoints:** `/v1/browse/<id>/{control,release,pause,resume,answer,live,shot/<name>}` (`accounts/browse.py`, rate limits 240/min control, 60/min answer) → `BrowseRpc` → `BrowseService.control/pause/resume/answer/release` (`browse/service.py:232-379`).
- **Frontend:** Live page exists; the question box (answer UI) was removed from `lumina/` on 25 Oct (see [06-history](06-history-and-legacy.md)).

### P14 Shadow routing
- **Status:** Reachable under specific configuration (`jev_routing`).
- **Chain:** `RequestWorker._tick` calls `ShadowRouter.before/after` (`routing/shadow.py`) → `classifier.classify` (external JEV) → `policy.evaluate` → `RouteLog` (`route_decisions`, 0015). Never changes execution; every error swallowed. Route names include `codex`, `jev_executor`, `specialist_worker` that no executor implements (`routing/config.py:6`).

### P15 JEV display chooser
- **Status:** Implemented but disabled (`jev_display` off per live21).
- **Chain:** after a plain-text reply with no cards, `ChatDriver._choose_display` (1090) → `routing/display.py:DisplayDecider` → layout hint stored as a data block.

### P16 Cards and files at finish
- **Status:** Current and reachable.
- **Chain:** `_capture_files` (1242) → `ArtifactService.capture_or_version`; `genui.blocks.attach_cards` (`chat.py:730`) validates card JSON from the reply (`genui/data.py:validate_data`) and strips repeated bullets (`trim_repeats`).

### P17 Cell wake, hand-over and sleep
- **Status:** Reachable under specific configuration (`wake` switch on, supervisor wired with a real backend).
- **Chain:** `LifecycleWorker.tick` (`lifecycle/worker.py:127`) → `enqueue_wakes` (98) → `Coordinator.request_system` → supervisor (`supervisor.py`) → Fleet driver (`fleet_driver.py`) → cell. `sleep.wake_plan` (33) and `can_sleep` (25; idle 900 s, or `handover_idle=60` when another account waits, `worker.py:152`).
- **Unknown:** whether production runs the verified native driver or `DisabledDriver` (`supervisor_main.py:34`).

### P18 Reconcile and abandon
- **Status:** Current and reachable.
- **Chain:** `RequestWorker._tick` → `RequestQueue.reconcile` → `ChatDriver.reconcile` (1361); abandon after 1800 s (`request_worker.py`), `ChatDriver.abandon` (1347) charges the reserved bound.

### P19 Accounting
- **Status:** Current and reachable.
- **Chain:** `BudgetLedger.admit` (`budget.py:74-91`) → `_reconcile_usage` (521) reads `gateway.usage_snapshot` (LiteLLM key spend via bridge) → `ledger.receipt` → `ledger.settle` (116). Falls back to the reserved upper bound when spend is unreadable.

### P20 Progress, events and frontend updates
- **Status:** Reachable under specific configuration (events exist while tasks run).
- **Chain:** `ChatDriver._emit` → `EventService.append` (`events.py`, allow-listed kinds, redaction) → `GET /v1/tasks/<id>/events` polled every 2.5 s by `AgentThinking.tsx`; messages and tasks polled by `Chat.tsx:56`. SSE route `st.stream` exists and is unused by the app.

## B. Owner and operator entry points

### P21 Owner dashboard controls
- **Status:** Current and reachable (loopback only, via SSH tunnel).
- **Chain:** `dashboard/app.py` POST `/switch`, `/switch-confirm`, `/toggle`, `/jev-toggle`, `/customer-action` (runs `manage.py signup_admin`), `/customer-limit`, `/routing-save`, `/routing-rollback`. Writes the switches file read by P01, P04, P05, P07 and others.

### P22 Operator endpoints and command-line tools
- **Status:** Current and reachable.
- **Entry:** `internal/accounts/<id>/{invite,revoke,suspend,audit}` and `…/deployment/operations[/<op>/retry]` (operator role plus MFA, `accounts/views.py`, `accounts/lifecycle.py`); `manage.py` commands (`request_worker`, `billing_worker`, `telegram_worker`, `signup_admin`, `onboard_trial`, …); `lifecycle/{worker_main,supervisor_main,cell_bridge_main,enroll_cli,provision_cli}`; `ops.cli {backup,monitor,watchdog,…}`; `bin/*` scripts; deployment tooling `platform/deploy/release.py` (canary release with schema-compatible rollback) and the disposable checks `p4_*_check.py`, `p15_acceptance.py`, `signup_live_check.py` (host-run harnesses, not part of any request path).
- **Relation:** lifecycle operations feed P17.

### P23 Billing and sign-up background jobs
- **Status:** Current and reachable (not agent orchestration; they gate access that P01 checks through `entitlements` and `BudgetLedger.admit`).

## C. Owner runtime and related systems

### P24 OpenClaw assistant loop inside the customer cell
- **Status:** External and not inspectable as running code; documentation and the installed package were inspected, the loop source was not traced. Reachable whenever P01 to P03 run.
- **What the installed docs establish** (`~/.npm-global/lib/node_modules/openclaw`, version 2026.9.6, `docs/concepts/agent-loop.md`): one serialised run per session lane; `agent` RPC then `agent.wait`; compaction and retries; default agent runtime budget 172 800 s; tool-loop detection **off by default**; model idle timeout 120 s; fallback and queue modes. Representative tools: `exec`, `process`, `read`, `write`, `edit`, `apply_patch`, `web_search`, `web_fetch`, `browser`, `ask_user`, `message`, `sessions_*`, `subagents`, `cron`, `tool_search`.
- **What Lumina sets for cells:** model `litellm/claude-sonnet-5-5`; `sandbox.mode off`; heartbeat off; Brave search plugin; rules file `AGENTS.md` (`cell_config.py:20-31,38-139`). Nothing else about tool policy is set, so OpenClaw's defaults apply (unverified for cells).
- **Boundary Lumina uses:** bridge methods `hello, sessions.create, chat.send, chat.history, chat.abort, usage.snapshot, cell.status, workspace.collect` (`cell_bridge.py:26`).

### P25 Owner's main orchestrator with workers
- **Status:** Uncertain (owner runtime on the VPS; configuration in repo, not exercised here).
- **Chain:** `config/openclaw.example.json` agent `main` (profile minimal; denies `browser`, `cron`, `gateway`, `automations`; exec allowlist with ask always; Telegram channel) delegates with `sessions_spawn` to `researcher`, `browser-worker`, `critic`, `codex-builder`, `codex-debugger` (`ARCHITECTURE.md` Authority table; `config/skills/orchestration/SKILL.md`: max 3 concurrent, 900 s, workers sandboxed; critic verdict loop with one retry). Workers use `litellm/claude-sonnet-4-6` and `openai/gpt-6-sol` for Codex (`config/phase4-native-workers.batch.json`).
- **Relation to customers:** separate from customer cells. The dashboard reads its gateway sessions (`dashboard/app.py:514`).

### P26 Jev research-fetch plugin
- **Status:** Uncertain. `research-opt/plugin` is an OpenClaw tool-result middleware that is fail-open and toggled by `research-opt` config via the dashboard (`dashboard/app.py` toggle). The adapter itself warns it must not be attached to arbitrary sessions (`research-opt/adapter.py:1-6`). Whether it is installed on the server is unknown.

### P27 Optimized browser route (`browser-opt`)
- **Status:** Implemented but disabled. `browser-opt/config.json` has `enabled: false`; nothing in the platform imports `route.py` or `jev_adapter.py`; the owner switch `browser_optimization` has no reader anywhere.

### P28 Native Claude Code and Codex worker activation
- **Status:** Implemented but disabled / experimental. Configuration batches (`config/phase4-*`, `config/phase10-claude-code-*`), images (`deploy/Dockerfile.claude-code`, `Dockerfile.sdk-peer`), fixtures. Switch `claude_code_for_customers` is `locked` and has no reader.

### P29 Worker broker
- **Status:** Apparently unreachable. `lifecycle/broker.py` ("fixed, host-owned execution envelopes for coding, review and browser stages") has no importer; it is exercised only by `tests/test_broker.py` and `deploy/p4_broker_check.py`.

### P30 Durable objectives, memory, schedules, skills, watchers
- **Status:** Apparently unreachable on the customer path. Modules `durable.py`, `memory.py`, `schedules.py`, `skills.py`, `watchers.py` have no importers; `/v1/memory`, `/v1/schedules`, `/v1/integrations`, `/v1/controls`, `/v1/streams`, `/v1/exports`, `/v1/tasks` (list) resolve to the generic disabled view (`accounts/urls.py:24-27`); tables exist (0009, 0010). Switch `customer_schedules` is `locked` and has no reader. (Re-numbered here as P29-27 group; listed once.)

### P31 Optimization gate
- **Status:** Apparently unreachable (`optimization.py` no importer; `optimization_activations`, `optimization_calls` tables from 0012). Dashboard reads only.

### P32 Policy check
- **Status:** Apparently unreachable (`policy_check.py` tool-ceiling inspection; tests only).

### P33 Legacy stdlib HTTP server
- **Status:** Apparently unreachable for customers. `agentai_platform/server.py` serves only `/healthz`, `/readyz` and project reads, and answers `provisioning_disabled` or `capability_disabled` for every other `/v1` path. A systemd unit still exists (`deploy/agentai-platform-control.service`); whether it runs is unknown. (`server.py` has callers in `genui/store.py` and `live/gateway.py` only for helper classes.)

## D. Superseded, legacy and historical

### P34 Classic Django pages and the generic disabled-kind view
- **Status:** Legacy but still partially active.
- **What it is:** the server-rendered account pages under `/account/` (Overview, Requests, Usage, Billing, Connections, Chat, Telegram) and the `disabled` view (`accounts/views.py:274`) that answers the unrouted API kinds (`/v1/memory`, `/v1/schedules`, `/v1/integrations`, `/v1/controls`, `/v1/streams`, `/v1/exports`, `/v1/tasks` list).
- **Active parts:** Chat page (P11), Requests page (P12), Usage, Billing, Connections. **Inactive parts:** every `disabled` kind returns a fixed refusal after authentication.
- **Evidence:** `accounts/urls.py:24-27,68-79`; `accounts/templates/accounts/*.html`.

### P35 Keyword intent detection and local requirements forms
- **Status:** Superseded in the working tree; still present in HEAD and in history.
- **What it did:** `genui/intent.py:detect(message, mode, browse)` guessed from the message text whether it was a plan, a website-requirements form or a browse request, and `ChatService._local_form` created the form block at once (`HEAD:openclaw-project/platform/agentai_platform/chat.py:207-237`). Introduced `ac3cd9a` (12 Oct).
- **Replaced by:** intent decided only by the customer's Respond mode (`chat.py:send` comment "No keyword guessing"); the assistant reads every message first.
- **Surviving remnants:** `genui/intent.py:website_form` (used only by `accounts/test_chat.py:330`), the Form block UI and `ChatService.submit_block` (P08).

### P36 ServiceRouter-first routing (the "Router era")
- **Status:** Deleted but recoverable from history (also Superseded by P05/P06).
- **What it did:** per web-related message, JEV (TypeSafe) chose `browser`, `web` or `direct` **before** the assistant answered; the chosen service ran first and its output went to the assistant (`routing/services.py`: `ServiceRouter.choose`, `SERVICES = ('browser','web','direct')`, a cheap local check to keep JEV off non-web messages).
- **History:** introduced `7dcc3fe` (14 Oct, release live3), wording `d67d15e` (live4), "far fewer messages to TypeSafe" `65b15c7` (17 Oct), replaced by the assistant-first design around 20 Oct 09:39 UTC (per `lumina-cost-audit/LUMINA_COST_AUDIT.md` §A, which dates the era; no commit records the switch because the replacement is uncommitted), deleted by `5db9636` (25 Oct) together with `tests/test_services.py` and `tests/test_service_handoff.py`.
- **Surviving remnants:** the committed `ChatDriver` still takes `services=` and calls `self.services.choose` (HEAD `chat.py:418-420,799-809`); `ChatDriver._with_service_note` and `NO_BUILTIN_BROWSER` keep the "service" naming in the working tree; `CLAUDE.local.md` still lists `ServiceRouter.choose` as a blind spot.
- **Recover:** `git show 5db9636^:openclaw-project/platform/agentai_platform/routing/services.py`.

### P37 Legacy multi-user AgentAI orchestrator
- **Status:** Deleted but recoverable from history. `agent/core/orchestrator.py` ran tasks with the Claude Agent SDK and an in-process MCP tool registry, per-user and global concurrency (12 slots), `can_use_tool` approval checks, `core/approvals.py` tiers, `core/scheduler_service.py`, `tools/{browser,payments,web,sandbox,memory,notify,scheduler,skills_tools,credentials}.py`, `gateway/{telegram_bot,web_app}.py`. Introduced `4cb60d0` (23 Sep), extended `5e6f3fa` (24 Sep), retired `8298602` (27 Sep, 118 files removed). Nothing in the current tree imports it. Details in [06-history](06-history-and-legacy.md).

### P38 jev-browser (bare loop) and its four archived versions
- **Status:** Experimental or prototype (untracked directory `jev-browser/`; archives `jev-browser-{pre-remodel,v2-complex,v3-before-reset,v4-with-playwright}.tar.gz`). Standalone loop "goal → screenshot to JEV → one action → repeat". The `pre-remodel` archive contains an `engine/` package with files named like the current `platform/agentai_platform/browse/{trace,goals,untrusted,session,loop}.py`; the naming overlap is observed, derivation is not established.

### P39 jev-window-core
- **Status:** Experimental or prototype (untracked). Mac window control loop (`loop.py`, `model.py`, `native.py`, `Window.swift`, 655 lines). No link to the platform.

### P40 Phase-1-to-19 plan and product contract
- **Status:** Documentation-only: `../phase-prompts/openclaw/*`, `../product/*`, `plans/product/*` describe planned and historical phases (for example NATIVE-04 to NATIVE-07). Some are implemented (chat, billing, ops), some are not (see P30).

### P41 Mocks
- **Status:** Test-only or mock: `gateway.py:SyntheticGateway` and `chat.py:synthetic_gateway_factory`, `lumina/dev-mock.mjs`, `platform/dev_local_ui.py`, `browse/fixtures/site.mjs`.

### P42 Evaluation harness
- **Status:** Test-only: `evals/cases.yaml`, `evals/run.py` (list, validate, show; execution deliberately not implemented in build phases).

## E. Mocks, evaluation, external and uncertain

### P43 Model access path
- **Status:** External and not inspectable. Cell → relay `agentai_model_proxy.py` (completions and models only, `deploy/model-proxy/agentai_model_proxy.py`) → LiteLLM (`deploy/litellm.yaml`) → provider. Spend and per-key budgets enforced in LiteLLM (not visible here).

### P44 JEV (TypeSafe) service
- **Status:** External and not inspectable. Callers: `routing/classifier.py`, `routing/tools.py`, `routing/display.py`, `browse/ladder.py:JevChooser`, `browse/review.py`, `optimization.py`, `research-opt/adapter.py`. Models named: `jev-1.13.0` (routing, optimization, research), `jev-1.14.0` (browser; `browse/service_main.py:20`).

### P45 OpenClaw native cron, heartbeat and sub-agents in customer cells
- **Status:** Uncertain. Heartbeat is disabled by Lumina (`cell_config.py:31`). Whether `cron` and `sessions_spawn` are enabled in a customer cell depends on OpenClaw defaults and the cell's generated base config, which this repository does not contain.

