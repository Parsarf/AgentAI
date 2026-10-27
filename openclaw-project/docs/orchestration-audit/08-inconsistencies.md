# Inconsistencies, defects, risks and unknowns

Findings are separated by confidence. **Confirmed** means the behaviour is visible in the code or a committed document and needs no execution to establish. **Risk** means a plausible consequence of confirmed facts that was not exercised. **Hypothesis** needs a run, a server check or external information to settle. **Unknown** cannot be established from available evidence. Nothing here was repaired. Paths refer to [02-path-registry.md](02-path-registry.md).

## A. Confirmed

### Competing sources of truth
| ID | Finding | Evidence | Effect |
|---|---|---|---|
| I-01 | **Four independent flag systems** select behaviour: owner switches (JSON file with facts and confirmations), per-account safety overrides (DB), the stdlib server's `FEATURES` set, and environment settings. `GET /v1/app` merges some of them. | `switches.py:CATALOG`, `safety.py:FEATURES`, `config.py:6`, `accounts/settings.py`, `accounts/api.py` | The same capability (for example uploads, execution) can be on in one system and off in another; the owner dashboard shows only the switch catalog. |
| I-02 | **Switches that change nothing:** `browser_optimization` and `claude_code_for_customers` have no reader; `credentialed_browsing` and `customer_schedules` are only displayed. 30 of 32 safety features are `wired=False`. | importer and string search across `platform/`, `dashboard/`, `bin/` | An owner can record "on" for a feature that no code consults. |
| I-03 | **Two JEV model versions** are in use at once: `jev-1.13.0` (routing, tool choice, display, optimization, research) and `jev-1.14.0` (browser). | `routing/config.py:14`, `browse/service_main.py:20` | Different models answer different questions; configuration lives in two places (`routing.json` and a constant). |
| I-04 | **Two parallel state machines** describe one unit of work: `customer_requests.state` and `tasks.state`, plus `browse_runs.status` (free text) and the browser job's in-memory state. They are written in different places and can disagree (see I-12, I-13). | `0001:6`, `0004:5`, `0019:6` | Reports that read only `tasks.state` miss waiting or cancelled-while-waiting requests. |

### UI and capability claims versus execution
| ID | Finding | Evidence |
|---|---|---|
| I-05 | **UI controls that only modify text:** the Tools menu and the four Home tiles type a sentence starter; the chosen tool (`mode` state) is never sent. | `lumina/src/components/Composer.tsx:8,57,67`; `lumina/src/pages/Home.tsx:38` |
| I-06 | **Advertised capabilities without connected execution:** Automations, Calendar, "Automate" (no scheduler, no importer for `schedules.py`, switch locked and unread); attach files (disabled; uploads route returns `uploads_not_enabled` and nothing feeds files to the assistant); connectors (never called from the agent loop; writes raise `WriteDisabled`); credentialed browsing (switch needs an unbuilt login flow). | `lumina/src/pages/Info.tsx:16-26`; `accounts/urls.py:24-27`; `accounts/files.py:73-80`; `connectors.py:46`; `switches.py` |
| I-07 | **Form blocks are orphaned.** Submitting a form is implemented end to end, but no production code creates a form block any more (the keyword detector was removed). Only rows that already exist can be submitted. | `genui/store.py:61` callers; `genui/intent.py` (only `website_form`, used by `accounts/test_chat.py:330`) |
| I-08 | **Telegram is a different engine in practice.** Inbound messages skip the tool protocol (`_agentic` requires customer provenance), and finished results are not sent back (the outbox is written only by `TelegramService._reply`). | `chat.py:873`; `telegram.py:117-153,298` |
| I-09 | **Approval events cannot occur.** `approval_request` and `approval_decision` are declared (and mapped to an orb state "Waiting for your approval") but never emitted; five other declared kinds (`search`, `file_change`, `command_result`, `test_result`, `budget`) are also never emitted. | `events.py:27-45`; `lumina/src/lib/orbs.ts:59`; search of emitters |

### Entry points and engines
| ID | Finding | Evidence |
|---|---|---|
| I-10 | **A legacy entry point can only fail.** `POST /v1/requests` queues a request with no conversation and no budget reservation. The worker fails it as unfunded; `ChatDriver.execute` would also refuse it. It consumes one of an account's three waiting slots until then. | `accounts/requests.py:16-28`; `request_worker.py` unfunded branch; `chat.py:585` |
| I-11 | **The documented 30-tasks-per-hour limit is not applied to chat sends**, only to Retry and `POST /v1/requests`. | `platform/UI_CONTRACT.md` limits; `accounts/chat.py:162-185` vs `:241`; `accounts/requests.py:25` |
| I-12 | **A request cancelled while waiting is never settled.** `RequestQueue.cancel` updates only `customer_requests`; the reservation and `tasks` row are closed only by `ChatDriver._close`. No other release path exists. (Effects: see R-04.) | `request_queue.py:86-93`; `chat.py:559-575`; `budget.py` (no cancel writer); search for `task_reservations SET` |
| I-13 | **Four `tasks.state` values and `reservation.cancelled` and `delivery.failed` have no writer.** | `0001:6`, `0003:4`, `0005:27` vs `chat.py:569,612,620`, `budget.py:84,111,122,126` |
| I-14 | **A pre-cancelled request records two aborted delivery attempts.** Both the `elif pre_cancelled` and the following `if pre_cancelled` branch call `_start_delivery` and `_set_delivery(…, 'aborted')`. Harmless to outcome; evidence of duplicated logic. | `chat.py:610-621` |

### Repository and history
| ID | Finding | Evidence |
|---|---|---|
| I-15 | **The running orchestration is uncommitted.** `agent_protocol.py`, `pursuit.py`, `routing/tools.py`, `routing/display.py`, `browse/review.py`, `browse/sessions.py`, `genui/images.py`, `safety.py`, `vault.py`, `saved.py`, migrations 0023 to 0027 and about 20 test files exist only in the working tree. `RELEASE_NOTES.md` states live9 to live24 were deployed "from the working tree (not committed or tagged)". | `git status`; `RELEASE_NOTES.md` live18 to live24 |
| I-16 | **HEAD is internally inconsistent.** Commit `5db9636` deleted `routing/services.py` and two test files while the committed `ChatDriver` still takes `services=` and calls `self.services.choose`. It runs only because the parameter defaults to `None`. | `git show 5db9636 --stat`; `git show HEAD:…/chat.py` lines 418-420, 799-809 |
| I-17 | **Migration numbering collides across lines of work.** Branch `worktree-product-images` adds `0023_card_images.sql`; the working tree uses `0023_saved_choices.sql` and `0025_card_images.sql`. Two migration systems coexist (`platform/migrations/*.sql` for the store, `accounts/migrations` for Django). | `git diff product-phases-6-11...worktree-product-images`; `platform/migrations/` |
| I-18 | **Documentation disagrees with the code.** Root `README.md` says execution is pending and the native adapter disabled; `RELEASE_NOTES.md` header says "Latest: live8" above sections up to live24; `plans/pursuit-architecture.md` opens with "Nothing here is implemented"; `CLAUDE.local.md` names `ServiceRouter.choose` and `test_service_handoff.py`, both gone; `UI_CONTRACT.md` claims a task rate limit that chat send lacks. | files named |
| I-19 | **Legacy naming still shapes prompts.** `_with_service_note` (parameter `plan` unused) and `NO_BUILTIN_BROWSER` carry the router-era vocabulary; the latter tells the assistant not to use its built-in `browser` tool because it fails in cells (`rename without replacement`). | `chat.py:870,1172-1179`; `RELEASE_NOTES.md` router section |
| I-20 | **Shadow routing recommends routes nothing implements.** `routes` includes `deterministic`, `jev_executor`, `specialist_worker`, `claude`, `codex`, `abstain`; only the existing path runs, so the recorded "route" can never be acted on. | `routing/config.py:6,17`; `routing/shadow.py` |

### Completion and verification
| ID | Finding | Evidence |
|---|---|---|
| I-21 | **Chat completion is a text fact, not a verified outcome.** In Auto and Text mode a request is `completed` when the assistant has replied and the runtime is idle twice; the result is the last agent message, or the string "Completed without an agent transcript row". | `chat.py:41,736-741` |
| I-22 | **Browse mode `completed` includes handoff.** `_finish_browse_reply` marks the request `completed` when the browser state is `done` or `handoff`, and `failed` for every other end. A handoff at a payment step is "completed". | `chat.py:775` |
| I-23 | **Cards are validated for shape, not truth.** `validate_data` checks schema and bounds; nothing checks that the numbers or links came from the work done. | `genui/data.py:validate_data` |
| I-24 | **Pursuit verification is advisory.** `verify` compares plan criteria to step rows and checks; it can mark `verified`, but the final wording is still assistant-written and the whole mechanism is off by default. | `pursuit.py:538`; `plans/pursuit-validation.md` |

## B. Risks (plausible consequences, not exercised)
| ID | Risk | Basis |
|---|---|---|
| R-01 | **One slow or stuck request delays every customer.** One request runs at a time across all accounts; an uncertain request holds the slot up to 1800 s; a normal run up to 900 s. | `request_queue.py:128-131`, `request_worker.py` `abandon_after` |
| R-02 | **Head-of-line blocking at claim time.** `claim` takes the oldest waiting request overall and returns nothing when that account's cell is not the active one, so a cell that fails to start (or waits for capacity) holds up everyone behind it. `handover_idle=60` shortens the normal case. | `request_queue.py:137-146`; `lifecycle/worker.py:152` |
| R-03 | **Browser jobs are in-memory.** A browse service restart loses every running job and its takeover state; the request then ends as an error. Stale `browse_runs` rows were already observed. | `browse/service.py:166`; `RELEASE_NOTES.md` known limits |
| R-04 | **Cancelled-while-waiting leak (follows from I-12).** A held reservation keeps counting against allowances (`BudgetLedger._holds`), and a `tasks` row left `queued` is counted by `LifecycleWorker.facts` (`queued_tasks`), which prevents idle sleep and counts as non-terminal for restore. | `budget.py:51`; `lifecycle/worker.py:47-56`; `sleep.py:25`; `ops/restore.py:39` |
| R-05 | **Cancellation stops the run, not necessarily its effects.** `chat.abort` ends the assistant's run; commands or messages already executed by its tools are not undone, and the bridge exposes no per-tool cancel. Browser cancel stops the loop; clicks already made stay made (the browser stops before payment by policy). | `cell_bridge.py:26`; `chat.py:_poll`; `browse/service.py:217` |
| R-06 | **Customer Retry re-runs the whole request.** A retry is a new assistant turn from the same text; any effect the assistant's own tools performed the first time can repeat. Lumina's duplicate-send protection covers delivery (uncertain outcomes are never resent) but not repeated task effects. | `chat.py:405-418` |
| R-07 | **Loop protection relies on Lumina's timers.** OpenClaw's default agent budget is 172 800 s and tool-loop detection is off by default; Lumina's 900 s `chat.abort` is the effective bound. If an abort fails silently the run may continue spending; spend is then reconciled by delta. | OpenClaw `docs/concepts/agent-loop.md` timeouts table; `docs/gateway/config-tools/built-in-tools.md` loop detection; `chat.py:_poll` timeout branch |
| R-08 | **Browsing share enforcement is per task, not per tool call.** The 60% browsing share and per-call admission limit browser money, but the assistant's own model calls in a long chat are bounded only by the flat reservation (default 1 000 000 microUSD per task) and the per-key LiteLLM budget. | `chat.py:_pursue_step`; `accounts/settings.py:121`; `FixedRoute` |
| R-09 | **Production code is not in version control.** GitHub is suspended per the release notes; releases are reproducible only from server release folders and local bundle backups. | `RELEASE_NOTES.md` "Where the code is kept" |
| R-10 | **Channel parity.** The same words get different behaviour in Telegram (no tool protocol), Text mode (no tool protocol) and Auto mode (tool protocol). | `chat.py:873` |
| R-11 | **Stale prose can steer people wrongly.** `CLAUDE.local.md` blind-spot notes and root `README.md` describe a system that no longer matches; an operator following them could disable the wrong switch or look for a deleted router. | I-18 |

## C. Hypotheses (need a run or server access to settle)
| ID | Hypothesis | How to settle |
|---|---|---|
| H-01 | R-04 is real in production: stale `tasks.state='queued'` rows keep a cell awake and holds reduce allowances. | Query `tasks` joined to `customer_requests` for `state='cancelled'` with `tasks.state='queued'`; read `LifecycleWorker.facts` output on the server. |
| H-02 | The classic Requests page produces visible failing rows in production. | Look for `failed` requests with no `conversation_id` and the unfunded result text. |
| H-03 | `agentai-platform-control.service` (legacy stdlib server) is installed and running. | `systemctl status` on the server. |
| H-04 | Customer cells expose `cron`, `sessions_spawn` and `exec` to the assistant (OpenClaw defaults), so the assistant can create its own recurring work or sub-agents without Lumina's knowledge. | Inspect a cell's generated OpenClaw config and tool policy. |
| H-05 | The OpenClaw tool-loop detector is off in cells, leaving Lumina's timeout as the only guard. | Same inspection as H-04. |
| H-06 | Browse-service `--jev-mode live` and the `jev_services` switch are still on after live24. | Server drop-ins and the switches file. |

## D. Unknowns (cannot be established here)
| ID | Unknown |
|---|---|
| U-01 | What the OpenClaw runtime does inside a cell beyond its documentation: model prompts, tool-call parsing, retries and fallbacks as actually bundled in `dist/` (version 2026.9.6 was inspected through its docs only). |
| U-02 | Production state after 21 Oct 2026 (switch file, facts file, systemd drop-ins, deployed release folders). |
| U-03 | Whether the supervisor runs the verified Fleet backend or `DisabledDriver` on the server (`supervisor_main.py:34`). |
| U-04 | TypeSafe/JEV behaviour, limits and data handling; LiteLLM per-key budget enforcement. |
| U-05 | Contents of the two worktree checkouts with uncommitted changes (`fastclick`, `live-view`) and of `~/.openclaw/migration`. |
| U-06 | Whether any host process outside this repository imports the unrouted modules (P29 to P32). |
| U-07 | The 149 files under `evidence/` (phase proof logs) were not read in detail; they may record behaviour of paths that are now disabled. |

## E. What these findings do not say
No finding asserts that the reason for a change was a mistake or an intention. Where a commit message or document gives no reason (notably the deletion of `routing/services.py` inside `5db9636`), the reason is unknown.
