# Findings: gaps, inconsistencies, unknowns

> **Historical.** This page describes the code before the move to native OpenClaw execution (26 Oct 2026): the `lumina-step` protocol, JEV tool choice, Pursuit, the
> round loop and transcript polling no longer exist. The current description is [native-execution.md](native-execution.md). Kept for the record.


Every item names its evidence. **Confidence** says how it was established: **Read** = clear from the code; **Likely** = the code points one way but a run or a missing file elsewhere could change it; **Unverified** = needs execution or the production environment. Nothing here was executed. Recommendations are kept in the last section, apart from the findings.

## A. UI claims that do not match backend behaviour

| ID | Finding | Evidence | Confidence |
|---|---|---|---|
| F-01 | **The Tools menu and the Home capability tiles only type a sentence starter.** The selected tool is kept in component state (`mode`) and is never part of the request. The request carries only `message`, `key` and the Respond choice. "Web search", "Build & code", "Analyze data" and "Automate" therefore select no tool, restrict nothing and start no workflow. | `lumina/src/components/Composer.tsx:8` (`TEMPLATES`), `:57` (`choose`), `:67` (POST body); `lumina/src/pages/Home.tsx:38` | Read |
| F-02 | **"Automate" and the Automations page promise recurring tasks that nothing can create.** The page is a "coming soon" panel; `/v1/schedules` and `/v1/memory` resolve to the generic `disabled` view; `ScheduleService`, `watchers.py`, `memory.py`, `skills.py` and `optimization.py` have no importers outside tests. The tables exist (`0009`, `0010`). | `lumina/src/pages/Info.tsx:16-17`; `accounts/urls.py:24-27`; importer search over `platform/agentai_platform` and `platform/accounts` | Read |
| F-03 | **Attachments are disabled, and the backend would not feed uploads to the assistant even if enabled.** The attach button is disabled and a pasted file is refused. The upload route exists but returns `uploads_not_enabled` unless `UPLOADS_ENABLED` and storage are set. No code in the chat driver reads uploaded files into the assistant's context; files appear only as outputs (`_capture_files`). So "Analyze Data" has no data-ingestion path. | `Composer.tsx:82,84`; `accounts/files.py:73-80`; no upload reads in `agentai_platform/chat.py` | Read |
| F-04 | **Integrations are connectable but unreachable from the agent.** Link, callback, disconnect and drafts routes exist behind `connectors`; `connectors.py` is imported only by `accounts/connections.py`; writes raise `WriteDisabled`. The Calendar page is a placeholder. Email and calendar actions cannot happen through Lumina's loop. | `accounts/connections.py`; `connectors.py:46`; `Info.tsx:16,24` | Read |
| F-05 | **Telegram is inbound only for results.** Inbound messages become chat sends with `provenance='telegram'`. `telegram_outbox` is written only for command and link replies (`TelegramService._reply`); no path was found that sends a finished task's result to Telegram. | `agentai_platform/telegram.py:117,298`; outbox writes only at `:120` | Likely (the assistant's own runtime might message Telegram; not visible) |

## B. Controls and safeguards

| ID | Finding | Evidence | Confidence |
|---|---|---|---|
| F-06 | **Cancelling a request while it is still `waiting` appears to leave its budget reservation and its `tasks` row open.** `RequestQueue.cancel` only updates `customer_requests`. The reservation is settled and the task row closed only in `ChatDriver._close`, which a never-claimed request does not reach. Consequences if confirmed: the held amount keeps counting against the account and service allowance (`budget.py:_holds`), and a `tasks.state='queued'` row makes the lifecycle worker count a queued task, which blocks the cell from sleeping (`lifecycle/worker.py:facts` passes `count('queued')` to `CellFacts`; `sleep.py:can_sleep` refuses when `queued_tasks` is non-zero) and counts as non-terminal for restore (`ops/restore.py:39`). Pausing keeps a reservation by design; cancelling should not. | `request_queue.py:86-93`; `chat.py:559-569`; `budget.py:84,126`; `lifecycle/worker.py:47-56`; `lifecycle/sleep.py:25` | Likely. Needs a test run or a look at production rows |
| F-07 | **No approval flow exists for the assistant's own tool use.** The event kind `approval_request` is declared and the orb maps it to "Waiting for your approval", but nothing emits it. Approvals that do exist are plan phases (`requiresApproval`), the browser's handoff and ask states, and saved-credential use. Whatever permission model OpenClaw applies to its `exec` and `write` tools is not visible. | `events.py:37`; `lumina/src/lib/orbs.ts:59`; no emitter found by search | Read |
| F-08 | **Four `tasks.state` values have no writer:** `waiting_for_approval`, `paused`, `budget_exhausted`, `blocked`. They are read by the lifecycle worker, diagnostics and restore code. A request paused by the customer is `customer_requests.paused=1`, while `tasks.state` stays `queued`. | `migrations/0001_foundation.sql:6`; `grep "UPDATE tasks SET state"` (three sites in `chat.py`) | Read |
| F-09 | **The documented 30-new-tasks-per-hour limit is not applied to chat sends.** It is applied to Retry and `POST /v1/requests`. A chat sender is limited by 30 write requests a minute, at most 3 waiting requests, and the budget reservation. | `platform/UI_CONTRACT.md` (Limits); `accounts/chat.py:162-185` versus `:241`; `accounts/requests.py:25`; `accounts/middleware.py:60-65` | Read |
| F-10 | **Single global slot and head-of-line effect.** One request runs across all customers. `claim` takes the oldest waiting request overall and returns nothing if that request's account does not hold the active cell, so one account waking up delays everyone behind it. The lifecycle worker hands over after 60 s of idleness when another account waits (`handover_idle`), so the typical delay is bounded, but a cell that fails to start holds the line until the operation fails. | `request_queue.py:126-146`; `lifecycle/worker.py:24,152` | Read; practical impact Unverified |
| F-11 | **Nothing independently checks the assistant's final answer.** The chat result is the last agent message. Browser runs have code rules and a reviewer; Pursuit records a verification level but it is advisory and assistant-driven. | `chat.py:736-738`; `browse/review.py`; `pursuit.py:17` | Read |
| F-12 | **A whole Plan has no overall deadline or spend ceiling beyond per-phase limits.** Each phase is a separate request with its own 900 s run limit and its own reservation. | `genui/runner.py` (creates one request per phase); `chat.py:431` | Read |

## C. Documentation and repository mismatches

| ID | Finding | Evidence | Confidence |
|---|---|---|---|
| F-13 | **`ServiceRouter` and its tests were deleted by an unrelated commit.** `agentai_platform/routing/services.py`, `tests/test_services.py` and `tests/test_service_handoff.py` were removed in commit `5db9636` ("Dark look is the default again..."). `CLAUDE.local.md` still describes `ServiceRouter.choose` and `test_service_handoff.py`. Nothing in the tree imports the module now. Whether the deletion was intended is not established. | `git log --diff-filter=D -- platform/agentai_platform/routing/services.py`; `CLAUDE.local.md` "Known blind spots" | Read |
| F-14 | **Older docs overstate execution status.** The top-level `README.md` says "agent execution is still pending" and that "the native agent adapter is still disabled". The code has a complete driver path gated by the `customer_execution` switch. Which is true in production depends on the switch file. | `/README.md` (root); `accounts/chat.py:30-55`; `switches.py:58` | Unverified for production |
| F-15 | **The SSE stream is built but unused.** `/v1/tasks/<id>/stream` exists with cursor replay and a cap of three streams per account; the app polls instead (2.5 s for events, 2.5 s for the chat). | `accounts/streams.py:69`; `lumina/src` has no `EventSource` | Read |
| F-16 | **`platform/WORKFLOW.md` (written earlier) is a simplified overview.** Where it differs from this folder, this folder is the more detailed and checked version. | `platform/WORKFLOW.md` | Read |
| F-17 | **The reverted Lumina app has no screen for the browser question, safety, vault and saved-info flows**, though the backend still serves them (`/v1/browse/<id>/answer`, `/v1/safety`, `/v1/vault`, `/v1/saved`). A browser run that reaches `asking` therefore has no place in the UI to be answered. The code is kept in `lumina-character/`. | `accounts/urls.py:60-61`; `lumina/src/components` (no AskBox or SafetyPanel); `lumina-character/src/components/AskBox.tsx` | Read |

## D. What static inspection cannot establish
1. **OpenClaw's behaviour:** its tool registry, tool permissions, its own cron or memory features, how it decides it is finished, and what it sends to the model.
2. **External services:** LiteLLM routing and keys, the model provider, JEV/TypeSafe decisions, Stripe, the Telegram Bot API, Brave or any search backend the assistant's search tool uses.
3. **Production state:** which owner switches are on (`SWITCHES_FILE`), whether the supervisor runs the real Fleet driver or `DisabledDriver` (`lifecycle/supervisor_main.py:34`), whether `UPLOADS_ENABLED`, `STORAGE_DIR` and `connectors` are configured, and the deployed commit.
4. **Runtime performance and failures:** nothing was run. Timeouts, poll intervals and recovery paths were read, not exercised.
5. **Whether any caller outside this repository** (operator scripts, cron, other hosts) imports the "unrouted" modules. The search covered this repository only.

## E. Recommendations (not part of the current implementation)
1. **Decide what the Tools menu is.** Either send the selection as a structured field (and let the backend add a tool hint to the preamble), or relabel it as "Prompt starters" so it does not look like tool selection. Remove the unused `mode` state if it stays a starter.
2. **Match the Automate/Calendar/Automations copy to reality** until the schedule engine is routed, or route it behind an owner switch with a clear "beta" state.
3. **Release the reservation and close the `tasks` row when a waiting request is cancelled** (and add a test that cancels a waiting request, then asserts the reservation is `settled` or `cancelled`, the task is terminal, and the cell can sleep). Confirm first with a test or a production query for stale `queued` rows.
4. **Apply `rate('task.create', ...)` to `chat_send`**, or update `UI_CONTRACT.md` to describe the real limits.
5. **Either emit `approval_request` for the assistant's consequential actions or remove the orb state**, and document what OpenClaw does for its own tool approvals.
6. **If SSE is the intended channel, move the app to it;** otherwise remove or document the stream endpoint and the three-stream cap.
7. **Restore or intentionally retire the service-router tests,** update `CLAUDE.local.md`, and consider a pre-commit check that flags deletions of modules unrelated to the commit message.
8. **Bring back a UI for browser questions, safety and saved info,** or disable the matching backend routes while they have no screen.
9. **Wire file uploads into context** (parse, store, reference in the preamble) before showing the attach control, or keep it hidden.
10. **Add a result-level check** (even a cheap rubric against the original request) before marking a run `completed` in Auto mode, and surface "partially done" when a plan is stopped.
