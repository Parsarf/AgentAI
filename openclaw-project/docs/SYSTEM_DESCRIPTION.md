# Lumina as it is now: complete description, and everything that changed

Written 26 Oct 2026, after the move to native OpenClaw execution. Part A describes the system as it stands. Part B lists every change in depth. Part C says what is and is not verified.
Details of the runtime contract and the request path are in `architecture/native-execution.md`; this page is the whole picture.

---

# Part A. What we have now

## A1. What the product is
Lumina is a private account product. A customer signs in to a web app (React, `lumina/`) or Telegram and chats with an assistant. Each customer has their own isolated *cell*: a
container running OpenClaw 2026.9.6 (gVisor, own workspace, own model key, no route to other customers or to the host except two doors). The assistant answers, searches, writes
files, uses a sandboxed browser, drafts and runs multi-phase plans, and can keep working on a goal over many turns. Lumina is the layer that decides who may run what, pays for
it, shows it, and tells the customer honestly how it ended.

## A2. Components and who runs them

| Component | Runs as | Job |
|---|---|---|
| Account app (`accounts/`, Django, gunicorn) | app user | sign-in, MFA, CSRF, the `/v1/...` API, the chat/task/browse/goal endpoints, billing and sign-up pages |
| Request worker (`manage.py request_worker`) | app user | claims one request at a time, drives it with `ChatDriver`, parks/unparks requests that wait for a person, admits the next turn of a goal, advances plan phases |
| Lifecycle worker + supervisor | root / app user | start, stop, hand over and back up customer cells; one running cell at a time in the trial profile; sleeps a cell only when no work is running, queued or waiting on a person |
| Cell bridge (`lifecycle/cell_bridge.py`) | root | the only path from the app to a cell's gateway: a private unix socket, an allow-list of methods, one `docker exec` Node relay per cell, calls multiplexed so a long wait never holds up Stop; also `usage.snapshot`, `workspace.collect`, `cell.identify` |
| Model proxy | root | the cell's only door to the model (completions and model list only), authenticated by the cell's own virtual key |
| **Tool relay** (`tool_relay.py`, `manage.py tool_relay`) — new | app user | the cell's second door: serves the `lumina_browser` tool over MCP on the bridge address; checks the cell by its own model key through the bridge |
| Browse service (`browse/`) | root | the sandboxed Chromium stage, one job at a time: the code rules (no payment, no password typing, human-check hand-off), saved-login consent, Live view, takeover, JEV first and, when JEV cannot take a step, the customer's own assistant (`lumina_browser_step`); hands are the host stage or the cell's own browser (engine per account) |
| Frame gateway (`live/`) | separate | serves the Live view frames with signed tickets |
| LiteLLM + Postgres | owner stack | per-cell virtual keys, spend, model allow-list |
| Owner dashboard, ops monitor, backup/restore | owner | switches, health, backups, restore with neutralization |
| Cells | per customer | OpenClaw gateway + the assistant's workspace |

Two doors only lead out of a cell: the model proxy (port 4000) and the tool relay (port 4100). Both are authenticated by the cell's own model key; everything else to the host or
private ranges is dropped by the firewall.

## A3. Who owns what
OpenClaw owns execution: the run, model calls, native tool calls, tool-result continuation, steering of an active run, abort, the session goal, and the verdict that a run ended
(`agent.wait`). Lumina owns admission (queue, budget, the single running slot), customer isolation, capacity, billing, the product UI, transcript, files and cards, the browser's
safety rules, and the customer-facing verdict. There is **one execution owner per request** (the runtime's run) and no competing loop in Lumina.

## A4. The life of a request

1. **Send** (`ChatService.send`). Validated (≤16,000 chars, key). If a task of the same chat is running and the message is a plain one, it becomes a **steer** of that run (own
   `steer` delivery, same request, same reservation); a refused steer (the task is closing) falls through to a new task. Otherwise a durable request is queued (`intent`: chat,
   plan, execute, phase, browse, goal_continue, goal_resume; `goal_mode` if "Keep working until complete"), the customer message is stored, and the budget is admitted: a reservation
   is made against the entitlement. A refusal cancels the queued row and returns 402 with a category; nothing is sent to any cell.
2. **Claim** (`RequestQueue.claim`). One request runs at a time across all customers (`request_slot`). The head of the line must belong to the account that holds the active cell.
   An account with a parked request is fenced (one execution and one session lane per account). Revoked authors' requests are cancelled. A stopped cell is woken by the lifecycle
   worker for any waiting request, including Browse mode.
3. **Admit and hand over** (`ChatDriver.execute`). Membership, active reservation and task state are rechecked. The session is opened if new. **Ownership first:** a run nobody owns
   (for example one the runtime resumed after a restart for a request that is over) is aborted; a run a live request owns defers this request (it goes back to waiting, same place).
   The input is recorded in `chat_deliveries` and sent with `chat.send`. The delivery key (`<request>-a<n>`) *is* the native run id. The outgoing text is the customer's message (or the
   plan/phase prompt) plus a short context block: what the customer asked Lumina to remember (names only), Browse/Text mode notes, and a retry note ("check what was already done").
   For a goal, the message alone is sent with the goal-start intent so the objective stays clean.
4. **Supervise.** `agent.wait` in 3 s slices. Between slices: Stop (aborts and waits for confirmation), the lease heartbeat, the spending limit (a run that has spent its
   reservation is stopped and reported partial), the 900 s per-run limit (plus a 1200 s backstop inside the cell), a person the run waits for, a cell that is briefly unreachable
   (waits up to 90 s), and an input that has been quiet (presented again by its key on a 20/40/80/120 s backoff). Replies are copied into the transcript as they land, attributed by the input they follow.
5. **Park** (when the browser asks the customer a question or the customer takes the wheel). The request keeps its reservation and its cell, gives up `request_slot`, and its task shows
   `waiting_for_approval` so the cell is not slept under it. The worker re-checks parked requests every tick: still waiting, ready (takes the slot back), or ended (closed without
   the slot). Waiting time does not count against the run; 30 minutes parked stops it.
6. **Close.** When no run is owed, `close_gate` shuts the door on late steers. The driver mirrors final replies, saves files the assistant wrote (the runtime's own seeded files are
   skipped) as versioned downloads, attaches cards, optionally asks JEV for a layout, judges the outcome, appends one fixed-vocabulary line if the task did not simply succeed,
   reconciles the spend from the provider key (waiting for the reading to settle), settles the reservation, sets `tasks.state`, and releases the slot with a receipt carrying
   `state`, `outcome`, `outcome_note`, `verification` and whether the goal continues.
7. **Afterwards.** The goal chain admits the next turn if the goal is still active; the plan runner advances phases; Telegram and the UI read the result.

## A5. Tools the assistant has
- Its own: web search and fetch (Brave plugin), files, commands, memory, the goal tools.
- **`lumina_browser`**: one tool, one website task (task, site, steps, search words, done-when, choices). It runs in the host's sandbox, stops before any payment, asks the customer when a
  choice is theirs, hands over at payment, sign-in or a human check, and uses a saved login or card only after the customer approves each use. It is served only inside the calling
  account's own running, funded request; it spends at most 60% of that request's reservation across all its calls; a stopped request or a dropped caller stops the job; several calls
  in one run are several jobs of the same request. Its result is Lumina's own wording of how the job ended.
- Denied in every cell: `ask_user` (fails in this connection model: "requires a verified user profile") and the runtime's own `browser`. Questions to the customer are ordinary replies or `choice` cards.

## A6. Modes and features the customer sees
- **Auto / Text / Plan / Browse** modes. Text = plain answer, browser not offered. Plan = the assistant drafts a JSON plan (one repair attempt), the customer edits and approves it,
  each enabled phase runs as its own request and its own native run, approval-gated phases wait as states. Browse = the assistant is told to use the browser.
- **Keep working until complete** (a switch next to the mode menu, hidden in Plan). Each turn is its own funded request; Resume and Clear on a held goal.
- **Steering**: keep typing while a task runs.
- **Honest status**: Working, Working towards your goal, Waiting for you, Completed, Partly done, Blocked, Failed, Cancelled, plus a one-sentence reason from a fixed vocabulary.
- Cards, follow-up actions, product/place pictures, layouts, files and downloads, Live view with takeover, saved choices and a vault of saved logins/cards, Telegram, usage and billing.

## A7. Outcomes
`state` says whether the run is over. `outcome` is **completed**, **partial** (browser stopped where the customer must act, goal held, spending limit reached), **blocked**
(runtime-reported blocker, a site that would not let the browser in), **failed**, or **cancelled**. `verification` is **verified** (a cart page plus a click that added to it, or a saved
file), **unverified** (a claim nothing Lumina holds supports, including a goal the assistant says is complete), or **not_applicable** (just an answer or a lookup). The assistant's
own words are never evidence.

## A8. Data model (SQLite, migrations through `0028`)
- `customer_requests`: state, intent, context, plus **outcome, outcome_note, verification, parked_reason, parked_epoch, continues, goal_mode, continue_goal, closing**.
- `chat_deliveries`: one row per input handed to the runtime — attempt, **kind** (turn, steer, goal_start, goal_resume, goal_continue), idempotency key = native run id, state
  (pending, acknowledged, uncertain, completed, failed, aborted), deadline, end, native status, tools used, the payload, usage-before.
- Unchanged: `request_slot`, `lifecycle_slot`, `tasks`, `task_reservations`, `provider_receipts`, `chat_messages`, `conversations`, `events`, `artifacts`, `browse_runs`,
  `browse_steps`, `browse_sessions`, plan/UI-block tables, vault, saved choices, billing and sign-up tables. `pursuit_state` is gone.

## A9. Security and isolation
Per-account scoping on every query; membership rechecked after the claim and on every heartbeat; the bridge allow-lists methods and parameters (queue modes, goal actions and intents are
validated to exact shapes; a refused call returns under `__error__` so a run's own `error` is never mistaken for one); the cell proves itself to the tool relay with its own key,
compared in constant time by the root bridge against running bindings; the relay throttles guessing per source, caps bodies, serves one tool, one call per account at a time; the
browser's code rules and the vault stay outside the cell; restore neutralizes anything that could act by itself (in-flight requests cancelled, deliveries aborted, goals stopped, parked
state cleared). Customers' privacy rules from the owner's guidance stand: no new task guardrails, security focused on data leakage and isolation.

## A10. Operations
Units: `agentai-platform-app`, `agentai-request-worker`, `agentai-lifecycle-worker`, `agentai-cell-bridge`, `agentai-browse`, **`agentai-tool-relay`** (new; in the monitor's required units
and on the owner dashboard), `agentai-model-proxy`, billing/mail/backup/monitor timers. Owner switches that remain: `customer_execution`, `browse_tasks`, `jev_routing` (shadow only),
`jev_display`, `budget_caps`, `open_access`, and the others in `switches.py`. Cell config is written by `lifecycle/cell_config.py` at create and at every start.

---

# Part B. What we really changed

## B1. Removed (and why it was redundant)
| Removed | What it did | Replaced by |
|---|---|---|
| `agent_protocol.py` / the `lumina-step` fenced block | the assistant asked Lumina for tools by writing JSON at the end of a reply; Lumina parsed it, hid it, ran the tool and sent the result back as another message | native tool calls and tool-result continuation inside the runtime |
| `ChatDriver._answer_step`, `_pursue_step`, the 6/12-round loop | the outer agent loop and synthetic follow-up messages | none needed: the runtime's loop |
| `_poll` idle inference (two idle reads after a reply) | guessed that a run was over | `agent.wait` |
| `routing/tools.py` (`ToolDecider`), the search nudge, the `jev_services` switch | JEV/keyword choice of browser versus search | the assistant picks its tool |
| `pursuit.py`, `pursuit_state`, `ops/pursuit_report.py`, the `pursuit` switch, ~10 test files | a second planning/supervising/verifying/replanning loop beside the assistant's | the runtime's own loop and goals; the useful checks live on as `outcome.py` |
| `browse/review.py` and its hooks in `loop.py`/`service.py` (reviewer, `replan` state, `checks`, `summary`, review stats) | JEV progress review of browser runs for Pursuit | nothing: the browser job ends on its own limits |
| `HttpGateway`, `GatewayBinding`, `DisabledGateway`-style unused client protocol | an unwired alternative gateway client | `NativeGateway` over the bridge |
| browse-only execution path in the driver (`_execute_browse`, `_run_browse`, wall hand-back) | Browse mode ran a browser job with no assistant | Browse mode is a native run that is told to use the tool |
| the "browse needs no cell" exceptions in the queue and the wake logic | that path | browse requests need the cell like any request |
| `plans/pursuit-*.md` | Pursuit design | archived in `backups/removed-by-native-migration-2026-10-26/` |

Note: `agent_protocol.py`, `pursuit.py`, `routing/tools.py`, `browse/review.py`, `ops/pursuit_report.py` and about a dozen tests had never been committed, so git cannot restore them.

## B2. Added
- **`chat_driver.py`** (the new `ChatDriver`): hand-over, ownership check, supervision loop, parking, Stop, time and spend limits, outage tolerance, re-presenting inputs (including under a fresh key after a restart), closing, settlement, recovery, abandon.
- **`gateway.py` rewritten**: `NativeGateway` (send/wait/abort/history/goals/usage/files) and a faithful `SyntheticGateway` for tests.
- **`cell_bridge.py`**: multiplexed connections; new allow-listed methods (`agent.wait`, `sessions.describe`, `sessions.goal.update/clear`, `cell.identify`) with exact parameter validation; `__error__` marker.
- **`request_queue.py` / `request_worker.py`**: park, unpark, defer, recover, close gate, steer door, per-account fence, outcome-carrying receipts.
- **`goals.py`** (`GoalChain`), **`outcome.py`** (verdicts), **`browse/adapter.py`** (the browser tool), **`tool_relay.py`** + `manage.py tool_relay` + `agentai-tool-relay.service`.
- **`ChatService`**: `steer`, `goal` flag on send, `goal_action` (resume/clear), Stop pausing a goal, richer task fields. `POST /v1/conversations/{id}/goal`; `goal` field on send (documented in `openapi.json`).
- **Cell provisioning**: `tools.deny = [ask_user, browser]`, `browser.enabled = false`, `agents.defaults.timeoutSeconds = 1200`, the `lumina` MCP server with the cell's own key, rewritten workspace rules (browser use, asking by reply, no step blocks).
- **Network/deploy**: `tool_relay_port` in the wiring file, firewall rule and ufw routes, `NetPolicy.tool_relay_port`, monitor and dashboard entries.
- **UI**: the goal switch, honest status labels and reason line, Resume/Clear goal on a held goal.
- **Tests**: `test_native_run`, `test_browser_tool`, rewritten `test_gateway`, `test_cell_bridge`, `test_chat`, `test_request_worker`, and `tests/e2e/` (16 scenarios on real gateways).
- **Docs**: `architecture/native-execution.md`, this page, updated `CHAT.md`, `OPERATIONS.md`, `WORKFLOW.md`, release notes, historical banners on pages describing the old flow.

## B3. Changed
- Browse mode now goes through the assistant (wakes the cell, spends assistant model calls) instead of a standalone browser job.
- A plain message during a running task steers it instead of queueing a second task.
- Replies are attributed by the input they follow, not by position or run id alone.
- Workspace capture skips the runtime's own seeded files (`SOUL.md`, `USER.md`, `IDENTITY.md`, `BOOTSTRAP.md`, `TOOLS.md`, `HEARTBEAT.md`, `MEMORY.md`, `memory/`).
- Restore also neutralizes native-run state: live deliveries aborted, parked state cleared, goals stopped.
- The `browse_tasks` switch text describes the browser as a tool; turning it off still stops running jobs.
- `customer_requests` and `chat_deliveries` schemas (migration `0028`); existing rows keep their meaning (old outcomes map one to one).

## B4. Kept deliberately
Billing and sign-up, Telegram, the plan UI and phase gating, cards/layout/pictures, the vault and Live view, the browse service and its code rules and JEV inside the browser
job, the JEV shadow router (it records, never executes), JEV display layout, the lifecycle rules (one running cell, sleep only when idle), the global serial slot.

## B5. The browser: JEV, then the assistant; the cell's own browser as the hands (2026-10-26)

- **Removed:** the Haiku and Sonnet tiers of the browse ladder, the browse service's own model client (`browse/llm.py`), the start-page guess by a model, shadow mode, and the model-cost
  estimates that went with them. The browse service now calls one model only: JEV.
- **Added:** the second tool `lumina_browser_step` (the assistant answers a page JEV handed over), a hand-over inside the loop (`ladder.Ladder.agent`, `service._agent_gate`, the `agent_step`
  operation), the page picture delivered to the assistant as an MCP image, and the `native` browser engine: `browse/native_runner.py` (the runner's commands over `browser.request`),
  `browse/native_scripts.py` (the page-side logic, run by name), the admin-scoped browser connection and `browser.*` methods in `lifecycle/cell_bridge.py` (root callers only), the cell config switch
  `native_browser` (`native-wiring.json`) and the per-account engine file (`browse-engine.json`).
- **Behavior:** JEV decides first; a first JEV miss looks at the page again, a second in a row, "too complex", a loop, or no JEV hands the task to the assistant for good; "done", "text for a field"
  and "an open choice" hand over one step. A cell with a live browser job or an open hand-off window is not put to sleep.
- **Gated, not switched on:** the native engine is off for every account until `browse-engine.json` lists it; the host stage stays the default until real-model, real-cell measurements are done
  (see `platform/OPERATIONS.md`, "Browser engine"). `browse/runner.mjs` and the stage code stay until then and are removed when the native engine is the default and has run a full release.
- **Verified:** unit and integration tests for every piece; the bridge, relay program, native hands, Live view frames and a whole browse job (including the sign-in stop) against a real OpenClaw 2026.9.6
  gateway and a real Chrome; the assistant's hand-over and step through a real gateway's MCP client. **Not verified:** the real cell image, gVisor, memory, real models, production.

## B5. Defects found by running the real runtime and fixed
1. A run's own `error` field (aborted/failed runs) was mistaken for a bridge failure, which would have broken Stop.
2. The reply to a steered message carries a runtime-made run id; attribution by run id alone dropped it.
3. The runtime's seeded files were offered to customers as downloads.
4. After a cell restart an unstarted input is `interrupted` and refused under its old key; recovery now hands it over under a fresh key (and a running turn is simply waited for).
5. A stopped cell was not woken for Browse mode.
6. Saved choices disappeared from the assistant's context when the vault module was unavailable.

---

# Part C. Verification status

**Verified** (903 platform tests including 16 end-to-end scenarios on real OpenClaw 2026.9.6 gateways; 176 frontend tests; browse runner tests): ordinary answer and charge; repeated
send; browser tool (handoff and done) with the real MCP client; files; plan and phases; steering; Stop with nothing arriving afterwards; worker crash recovery; cell kill and restart;
browser-question parking; goal chain; customer isolation; credential refusal; the exact cell config Lumina provisions (deny list, MCP server, backstop).

**Not verified:** a real model (tool choice, cost, quality); real cells (gVisor, `docker exec` relay, the 4100 firewall rule); the real LiteLLM spend feed; real Chromium and sites;
Telegram end to end; `deploy/*_check.py` scripts that may reference the old driver; the two failing Django tests are pre-existing (undocumented presence/safety routes; `safety_overrides`
restore rule). **Not deployed.**
