# Reliability plan - one failure contract, one state picture, and the browsing fixes

**Status (2026-11-24): Parts 1 and 2 (server side) are LIVE (PRs #90, #91), with the false "partly done" label of Part 3 fixed (#92) and the browser records left at "running" ended by the worker (Part 3, C, #97). Part 3 is LIVE (#98 tools, #99 browser) except the runtime's loop detection. Parts 4 and 5 are LIVE (#100, #101; the push gateway had not been restarted by any deploy and is since #102). Parts 6 to 9 are not started. Deploying Part 1 exposed three defects that were fixed on the way: the live acceptance could not make its test chat in a full project (#93, #94), a failed release that migrated the database was rolled back onto code that cannot start (#95), and file uploads cut every file at its line breaks (#96).**
`docs/architecture/`, and the documentation and code of the installed runtime (OpenClaw 2026.9.6). Every number was read from the server, read only. Nothing on
the server or in the code was changed.

## 0. What the second pass changed

Each part of the first version was checked against the code path it touches. Six things it planned are already done, and five findings change the design.

**Already done (the first version planned them as new work)**

| First version said | What the code shows |
|---|---|
| Fix the race between a workspace stop and a new request (runs 369, 371) | Fixed by `9616d4a` (deployed 2026-11-20): `request_queue.claim` holds an account's requests while a cell operation runs, and a stop refuses while a request waits. The two failures were the deploy's own acceptance probes, which found it |
| Browser timeouts, crashes and failed opens have unknown causes | PR #88 and #89 fixed the known ones (a read asked again, a dead stage restarted once, a failed open continued in a fresh tab, two processors). Measured in `browser-opt/lab` (23 everyday tasks, 10 hard ones). Not yet proven in production: two browser runs since |
| Build a tool that asks the customer | `lumina_ask_customer` exists (it ends the turn and resumes later) and `lumina_show` shows cards, forms and buttons. Neither appears once in 30 days of tool records |
| Approval for a connected-app call must be shown in the chat | Done 2026-11-13 (`8b33588`): the call is shown and the assistant is told to stop. Still open: it is returned as an error, and the turn ends |
| Pre-warm the workspace | `prewarm()` exists, but only the old server page and the side panel call it. The web app never does |
| Find the cause of run 390 (key disabled) | Known: the runtime's background self-learning turn got a 403, and the runtime disables a key for about a minute after a 401 or 403 (ten minutes after a 402). Self-learning is off since PR #89 |

**Findings that change the design**

1. **The runtime already gives a structured cause, and Lumina throws it away.** A failed run carries `errorDetail` (provider, model, `failoverReason`,
   `providerErrorType`, `httpStatus`), and the runtime keeps an audit ledger with closed result codes (`run_failed`, `tool_failed`, `tool_timed_out`,
   `tool_outcome_unknown`, `run_stalled`). `gateway.wait` keeps one string of 200 characters. Lumina's own model relay (`model_keys.ModelRelay`) sees every
   model call and its status code and records nothing. So chat failures can be classified from facts, not from text.
2. **A tool call may wait 20 minutes, and a waiting run is already parked** (`requestTimeoutMs` 1,200,000; `chat_driver._human_wait`; this is how the browser's
   question and the location permission work). Asking in place needs no new mechanism, only a third kind of wait.
3. **Cold starts are 23% of requests and take 76 to 100 seconds after the container is up** (10 of 43 requests in 7 days). The workspace has one processor and
   no compile cache. In run 395 the wake took 86 s and the first model turn 65 s.
4. **The numbers mix probes with real use.** 53 of 336 requests are the deploy's acceptance probes. Real requests: 283, of which 45 ended badly (16%) and 22
   were stopped by the customer. All of them belong to one account (the owner's), about 8 a day.
5. **At 8 requests a day a percentage alert means nothing.** The published guidance for low traffic is to alert on each failure that matters and to run probes,
   kept out of the real rate.

## 1. Where things stand

| Measure | Value |
|---|---|
| Real requests that ended failed, partly done or blocked | 45 of 283 (16%) |
| Tool calls that failed inside runs (30 days) | 194 of 990 (20%) |
| Requests with a failed tool call that ended as a plain "Done" | 49 |
| Browser records that end as "finished" | 9 of 61 |
| Browser records still "running" after the task ended | 8 (the oldest 23 days) |
| Bad endings whose sentence names no cause (last 150 requests) | 10 of 15 |
| Calendar and mail changes that failed | 7 of 162 (4%), all one named cause |
| Requests that met a cold start (7 days) | 10 of 43; 76 to 100 s each |

The calendar and mail row is the model. `connector_kit.py` maps every provider error to one of six kinds and treats "sent, no answer" as unknown. Nothing else
has a contract: tools answer `(text, is_error)`, browser reasons carry Python exception names, chat failures are matched by substring, there are 35 error
classes without a common base, 74 error strings in the web API, and about 70 catch-all handlers that drop the error.

## 2. Open causes

| # | Cause | Count | State |
|---|---|---|---|
| A | The real cause of a chat failure is replaced by a generic sentence, worded in up to four places | 4 provider failures, 2 container stops | Open |
| B | A browser job the assistant left open makes the task "partly done" | Run 395 and every run of that shape | Open (`_release_waiting_browser_jobs`, then `outcome.judge`) |
| C | A browser record stays "running" after its request ended | 8 | Open (`mark_interrupted` runs only when that run's view is polled) |
| D | The task spending limit ends a browser task with no answer written (the limit is the customer's own setting, $1 here) | 11 | Open |
| E | Expected stops are recorded as failures (approval 26, limit 11, stopped with the task 12) | all rates | Open |
| F | The assistant sends wrong arguments | 25: file delivery 13, browser 5, memory 3, connected apps 3, mail 1 | Open; the browser ones were fixed by PR #89 |
| G | An outside site answers with an error status and the row says only "did not work" | 20 | Open |
| H | The customer cannot tell what is happening: a tool category or "Thinking" in the status line, unnamed waits of 86 s and 65 s | every run | Open |
| I | State words and timelines exist several times (7 word lists, 2 timelines, 2 phase types, browser state polled apart) | - | Open |
| J | The ask and show tools are never used; the browser task did not ask (run 395) | - | Open |
| K | Cold starts | 10 of 43 | Open |
| L | Nothing watches task outcomes; no error-level log lines; tracebacks for client disconnects | - | Open |
| M | **No off-server backup copy** (warned for a week; known since 2026-10-29 in `findings.md`) | - | Open, owner decision |
| N | Monitor noise: 2 quarantined restores kept past the limit; 5 loopback ports missing from its expected list (5433, 8888, 8890, 18802, 18803) | - | Open |
| O | Browser trace files are not kept (one job folder on the server) | - | Open |
| P | Browser reliability after PR #88 and #89 | 2 runs since | Unproven |

Verify only (already fixed in the deployed code): the plain-name tool refusal (56 calls, PR #89), "could not be started" (7, the driver now waits for the
cell), "not part of a live task" (9, the tool-proof work of 20 Nov, inferred from the dates), the stop race (2, `9616d4a`), the embeddings memory kills (17,
#60), the earlier browser path (6, replaced), run 390's trigger (self-learning off).

## 3. The contract

One module, `agentai_platform/faults.py`, generalised from `connector_kit.py` (which keeps working unchanged and becomes its first user).

**A fault** is made where the failure is caught and is never rebuilt from text later.

| Field | Values |
|---|---|
| `kind` | The six connector kinds `retry_later`, `needs_customer`, `refused`, `not_found`, `conflict`, `invalid`, plus `needs_owner`, `limit`, `unknown_outcome`, `internal` |
| `reason` | A registered code `feature.cause`: `model.rate_limited`, `model.not_offered`, `model.key_refused`, `cell.stopped_under_task`, `browser.page_timeout`, `tool.bad_arguments`, `site.refused` |
| `actor` | `assistant`, `customer`, `owner`, `nobody` |
| `retry` | `now`, `after:<epoch>`, `never`; derived from the kind |
| `effect` | `nothing_changed`, `partly_done`, `unknown` |
| `detail` | Status code, provider, exception type: facts only, never page text, message text, addresses with a query, or a name. Owner-only |

**An ending** is one of `completed`, `failed`, `stopped_by_customer`, `waiting`, `limit_reached`, `released` (a child job its parent no longer needed). Only
`failed` counts in an error rate. The existing columns stay (`outcome`, `verification`, `outcome_note`); what changes is that they are filled from the fault.
Lumina's phases already line up with the public agent protocols, so no renaming is needed:

| Lumina | A2A task state | AG-UI event |
|---|---|---|
| queued, starting | submitted | RUN_STARTED |
| working | working | STEP_STARTED, TOOL_CALL_START |
| needs_you | input-required, auth-required | - |
| ended: completed / failed / cancelled / blocked | completed / failed / canceled / rejected | RUN_FINISHED / RUN_ERROR (code and message) |

**The registry** (`faults_registry.py`) holds per reason code: kind, actor, one sentence for the customer (what happened, who acts, the next step), one for the
assistant (naming the fix), and whether the owner is alerted. Every screen reads that sentence. A code that is not registered cannot be raised (a blocking
test in the manner of `EveryRelayToolCanBeProven`).

**Rules**

1. Classify from facts: a status code, an exception type, the runtime's `errorDetail`. Text matching is allowed in one table only, for runtime messages that
   carry no structure, with a test per message pinned to the installed runtime version. Anything unmatched is `internal.unclassified`, counted, and alerted.
2. A tool reply to the assistant has `isError` true only for a fault; a wait or a refusal by design is a normal reply that says what happens next.
3. A wrong-argument reply names the field and gives a valid example. The runtime checks `required` and `enum` before Lumina sees a call, so schemas stay loose
   and Lumina's own message does the teaching.
4. A catch-all handler exists only at a service boundary and records a fault. No silent `pass`.
5. Errors are logged at error level with the reason code and the request id. A client that went away is not an error.
6. Retry follows the kind: `retry_later` backs off with a cap, `unknown_outcome` is read back, nothing else is retried.
7. Closing a request closes every child job.
8. A feature is done when its reason codes are registered, each has a test that forces it, and it appears in the daily count.

**What a new table must also get** (found in the code, easy to miss): a row in the restore policy (`ops/restore.py` classifies every table), in account
deletion and export (`data_lifecycle.py`), and the 30-day sweep. SQL migrations are immutable and checksummed; the next is `0055` (the Phase 7 notes also plan
to start there, whichever is built first takes it).

## 4. The work, in order

One pull request per part unless said otherwise, each deployed and read on the live stack before the next. Parts 1 to 3 answer "why did it fail", Parts 4 and
5 answer "what is happening", Parts 6 to 8 are behaviour.

### Part 1 - Record and count (no change for customers)

**Built 2026-11-23** (not yet merged). What is in it: `faults.py` and `faults_registry.py` (39 reasons), migration `0055` (`faults`, `model_calls`,
`customer_requests.probe` with the old probes marked), the model relay's record of every call (`model_calls.py`), a reason written at every close of a request
that is not clean (`chat_driver._close`), `ops/reliability_report.py` (`ops.cli reliability`), the monitor's `task_failures` and `stale_children` checks and
its corrected port list, retention rule `diagnostics` (30 days), and the policy's two new lines. `tests/test_faults.py` (31 tests) is in the blocking list.
The report, run read-only against production before the release, reproduces section 1 (337 requests, 48 ended badly, the same tool and browser counts).

Changed from the plan while building:

- **Browser traces stay at one day.** That limit is a published promise (retention rule `browser_pictures`, and the policy's table). The exception type of a
  browser failure is kept in the fault instead; where a crash happened goes into the fault in Part 3.
- **The runtime's `errorDetail` moved to Part 2**, where it is used. Part 1 records the relay's own facts, which need nothing from the runtime.
- **The five loopback ports were identified before being added** to the monitor's list: 5433 the knowledge index's database, 8888 long-term memory, 8890
  embeddings, 18802 the browser's device gateway, 18803 the push gateway.

The plan as written:

- `faults.py`, `faults_registry.py`, the `faults` table, seeded from what exists (connector kinds, `job_states.py`, `failure_message`, `BROWSER_WORDS`).
- **Model calls.** `ModelRelay` records one row per model call: account, request, route, status code, provider error type, seconds, attempt, and input,
  output and cache tokens. No content. This is the source for provider failures, for "waiting for the model", and for Phase 14's baseline (section 4b).
- **The runtime's own cause.** The bridge passes `errorDetail` through with the run's end, and `gateway.wait` keeps it. Proven first on the end-to-end
  harness (`platform/tests/e2e`, whose stub model can answer 401, 402, 403, 404, 429, 500, 529), because the runtime's documents have been wrong about this
  version before. If it does not hold, the relay's record alone is enough.
- **Probes apart.** A request made by the deploy acceptance carries a mark and is counted separately.
- `ops/reliability_report.py`: per feature and day: finished, failed by reason, expected stops, unclassified, cold starts, seconds to first step.
- Monitor: `task_outcomes` (see section 5 for the rule), `stale_children`, and the expected port list corrected (N).
- Browser trace files kept 30 days (O).
- Proves: the report reproduces section 1 from the live database.

### Part 2 - One reason for a chat failure (A, E)

**Server side built 2026-11-23** (branch `reliability-2-reason`, on top of Part 1; not merged). A run the runtime ended in an error now has one reason, taken
from facts before words: the request's last model call as the relay recorded it, then the status number the runtime puts in its own error message, then the
runtime's wording. The task's result, the status line's note, the timeline's error row and the notice in the chat all carry that reason's one sentence. The
runtime's own error text ("LLM request failed (..., HTTP 404).") is no longer copied into the chat as a reply. Proven on the real runtime
(`tests/e2e`, `test_a_model_call_the_provider_refuses_...`).

Found on the real runtime while building, and different from what its documents say: `agent.wait` returns only a text for a failed run, no structured detail.
The detail exists on the runtime's `chat` events, which the bridge does not carry. It is not needed: the relay's record and the status number cover it.

Still to do in this part: the app shows the sentence twice next to each other (status line and chat notice; removed with the client work of Part 5), and
"try again after ..." for a key the runtime has put on hold.

The plan as written:

- The driver builds the fault from the relay's record and `errorDetail`: 429 and 529 `retry_later`; 404 on the model `needs_customer` (their choice of
  model); 401, 402, 403 on Lumina's key `needs_owner`; on the customer's own key `needs_customer`; container stopped `internal`; the runtime's
  `agent_run_terminal_timeout` and `idle_timeout_circuit_breaker` `limit`.
- `outcome.judge` receives the fault and stops writing a second sentence. `outcome_note`, the `error` event and the result read the registry.
- The failure is shown once, in the status line: the sentence, who acts, the next step. The extra "This task stopped..." chat message and the "Stopped:" line
  appended to the reply go. The runtime's own error text is never forwarded as a reply (run 263).
- `needs_owner` and `internal` alert the owner at once with the request number.
- After a 401, 403 or 402 the runtime refuses the key for one to ten minutes. The fault carries that time, and the status line says "try again after ..."
  instead of letting the next message fail the same way.
- Proves: each provider status forced through the harness gives one sentence in every outlet, and the right actor.

### Part 3 - Tools and the browser follow the contract (B, C, E, F, G)

**B is live** (#92): a browser job that ended because the assistant answered and no step was coming is judged like a job that finished, whatever state the
loop ended in. Run 395's shape now ends "Done".

**C is built** (2026-11-24): the 8 records left at "running" are all from 1 to 14 November, before the changes that record a job when its request ends; none
has appeared since. The request worker now ends, every five minutes, any browser record still alive 15 minutes after its request ended
(`job_states.close_orphans`): the record becomes `cancelled` with the reason "the task had ended", its history kept. That closes the eight old ones at the
first pass and is the safety net for any path that leaves one behind; no migration is needed.

Seen in the first live numbers (2026-11-24): no model call reports its token counts (0 of 4), so the provider's reply does not carry them at its end. Phase 14's
baseline needs them; asking the provider for usage in a streamed reply changes what the runtime receives and must be tried on the harness first.

**Tools are built and live** (2026-11-24, PR #98). What was found first, on the server (30 days, read only): 194 failed steps, and for 134 of them the
timeline kept the runtime's notice to the model ("SECURITY NOTICE: The following content is from an EXTERNAL, UNTRUSTED source...") as the step's output, because
the runtime wraps every reply of a Lumina tool in it and the first 1,200 characters were stored. So a customer who opened a failed step read that notice and
nothing of why it failed. The tool relay recorded nothing about a call. All 22 failed file deliveries were on one day (15 November).

What is in it:

- **Every tool says why, where it refuses or fails.** A tool's answer is `(text, problem)`; `problem` is now a registered fault instead of `True`
  (`faults_registry.py`, 30 new reasons: `tool.*`, `file.not_converted`, `site.*`, `runtime.*`). Moved: file delivery, show, memory, connected services, mail and
  calendar, documents, task progress, location, the browser tool's own refusals, and connected apps (their 27 error codes map to reasons). A blocking test
  refuses a bare `True` in any of them.
- **The relay records it** (`tool_relay.Relay._noted`): one `faults` row with the request, the tool's name and a mark of the call. A connected service's own tool
  names are recorded as one word. The same facts travel to the caller in the result's `_meta` (`lumina/fault`: reason, kind, retry, effect), for Phase 14.
- **An expected stop is not an error** (E). Approval needed, stopped with the task, a limit, a switch that is off, a role that does not allow the tool, and "another
  call is still running" are recorded and are a normal reply (`isError` false) that says what happens next. Approval needed (26) and stopped with the task (12) were 38 of the 194.
- **The step says why.** The driver puts the recorded reason on the step it shows (`chat_driver._step`), found by the call's id; the timeline row carries the
  registry's one sentence (`why`), and the app shows it under the step. The stored output is the tool's own words, with the runtime's notice taken off.
- **The runtime's own tools** (`web_fetch`, `web_search`, `exec`): the reason is read from what the runtime said, the status number first ("Web fetch failed
  (403)" is `site.refused`), by one table pinned to the installed runtime by a test that holds every message seen in production.
- **F, file delivery.** A file that is not there is answered with the files the workspace does hold. A path given under the folder the assistant sees its
  workspace in (`/home/node/.openclaw/workspace/...`) is the same file and is taken.
- **The report** (`ops.cli reliability`) counts steps apart from tasks: by tool and reason, wrong arguments per tool, and steps with no reason of their own. A
  failed step no longer stands in for a task's missing reason. A call whose row was written twice is one call.
- **`tools.codeMode` is pinned off** in `cell_config.py` (a cell takes it at its next start).

Found on the real runtime while building (`tests/e2e`): a tool reached through the runtime's `tool_call` wrapper is given an id of its own
(`tool_search_code:<the model's call id>:<tool>:<n>`), not the id the session history has, so the step and the relay's record did not meet until the mark was
taken from the model's call id for both. Proven for both ways a tool is called.

Changed from the plan while building:

- **The relay writes the fault, not the step row.** The step row stays the driver's (read from the runtime's history) and carries the relay's reason. Two writers
  for one row would show a call twice whenever their ids differ, which the wrapper finding above shows they can. When Phase 14 puts calls inside a program, the
  relay's record is already complete; writing the row from it is then a small step.
- **No migration.** The call's mark and the tool's name are facts in the existing `detail` column.

Live since 2026-11-24 (PR #98, release `23a8220`). Read on the server after the deploy: no tool call had failed yet, so the steps section of the report was empty.

**The browser's endings are built and live** (2026-11-24, PR #99, release `d3443ba`):

- **The reason is given where the ending is decided.** The loop's result, the service's job and the job's last status carry a `code` (`browse/loop.py`,
  `browse/service.py`; `job_states.END_CODES` is the code of a state when nothing more exact is known). Nothing reads a reason back out of a sentence any more,
  except for records made before this release.
- **Seven new reasons**: `browser.page_timeout`, `browser.page_would_not_open`, `browser.runner_crashed`, `browser.site_refused`, `browser.question_unanswered`,
  `browser.server_busy`, `browser.no_start_page`. The human check keeps its name (`browser.human_check`, the plan called it `bot_check`).
- **An exception's name no longer reaches a sentence.** "the browser run failed (TimeoutError)" is now "the page did not answer in time, so the browser stopped"
  (`browser.page_timeout`) or "the browser run failed" (`browser.runner_crashed`); the exception's type and the file and line it was raised at travel beside it
  as facts for the owner and are kept in the fault's detail.
- **The tool's reply follows the reason.** Every ending but `done` reaches the assistant with its reason. Stuck, out of time, the step limit and a failure are
  now told as errors (they were normal replies, so the step showed as done); a stop that is the site's or the customer's is a normal reply.
- **One sentence.** The task's note and the "Stopped:" line are the reason's sentence, the same one the step shows. For every state the old words and the
  registry's are identical (a test holds that), so wording changes only where the browser now says something more exact.

Not done in Part 3, still open: the runtime's loop detection (needs the lab tasks on a real model to show no false stop), and `tool.bad_arguments` replies for
memory, connected apps and the mail draft beyond what they already say.

The plan as written:

Two pull requests: tools, then browser.

- **Tools.** `tool_relay` results become a fault or a normal reply. The relay writes the fault row and the step row itself (it knows the account and the
  request), so the record does not depend on how the call reached it (section 4b). The fault is structured data first and a sentence second. The timeline
  row of a failed call shows the registry sentence, not "did not work". `tools.codeMode` is set off explicitly in `cell_config.py`. For the runtime's own tools (`web_fetch`, `web_search`, `exec`) the cause comes from
  the runtime's result codes and the status in its message ("Web fetch failed (403)" becomes `site.refused`).
- **F.** `lumina_file_deliver` first: 7 calls had the wrong path form and 6 named a file that was "not found"; the reply will list the files the workspace
  actually holds. Then memory, connected apps, the mail draft. A per-tool count of `tool.bad_arguments` stays in the report as the measure of a tool's description.
- **E.** Approval needed, "stopped with the task" and "question unanswered" are endings, not faults.
- **Browser.** Endings become reason codes (`browser.page_timeout`, `browser.page_would_not_open`, `browser.runner_crashed`, `browser.site_refused`,
  `browser.bot_check`, `browser.site_not_allowed`); `type(exc).__name__` no longer reaches a reason.
- **B.** A job ended because the assistant answered is `released`: `job_states.OVER` gains it and `outcome.judge` treats it as no evidence, not as "partly done".
- **C.** `_close` ends every live `browse_runs` row of the request. A migration step ends the 8 stale rows as `interrupted`, history kept.
- The runtime's loop detection (`tools.loopDetection`, off by default) is tried on the harness: it stops repeated unknown-tool and no-progress calls, the
  pattern behind the 26 approval retries. Switched on in cells only if the harness shows no false stop on the lab tasks.
- Proves: a forced-fault test per tool family and per browser ending; `stale_children` reads 0; run 395's shape ends "Done".

### Part 4 - The state picture, server (H, part of I)

**Built and live 2026-11-24** (PR #100, release `c26f03f`), with the few lines the app needs to show it. Read first from a real browser task on the server: 114 s of
"Getting your assistant ready" with no figure, 60 s of "Thinking" on the first model turn, and every step the assistant took in the browser shown twice ("Used the
browser" beside "Clicked “Filters” · Assistant").

- **The status line while the browser works is its newest step** ("Clicked “Price: High to Low”"), not only "Using the browser".
- **A step is said the way a person would say it** (`browse/words.py`): what was done, or what could not be done and why ("Could not click “Expand Men”: something
  on the page was covering it"). "· JEV", "· Assistant" and "(failed: covered)" are gone, also from older records, which are reworded when read.
- **One row per browser call, its steps inside it** (`work.read_timeline`): the call's row carries `steps`; a call of exactly one step is that step. A step noted
  before its call's row exists waits for that row and is never shown under an earlier call.
- **Named waits** replace "Thinking" and the queue line, each from a fact Lumina holds, with `since_epoch` and, where there is one, `expect_seconds`:

  | Shown | Source |
  |---|---|
  | "Waking your workspace", "usually about N" | The lifecycle worker's note on the task that it asked for the start; N is the median of the last cold starts (over a minute), none with fewer than three |
  | "Waiting for the model", seconds so far | The run is live and no tool is running; the seconds count from the newest event |
  | "Waiting for the model provider", the pause it asked for | The model relay's note, which now carries `step: provider_wait` and the seconds; it stops being said once the pause is over |
  | "Writing the answer" | Said by the app, which is where the reply's text streams to |

- **A failed step is listed with its reason** (`evidence.failed`, each with `recovered`), and the task is marked (`trouble`) only when it is over and nothing of the
  same kind worked after the failure.
- **A limit that was reached is in the record** (the `budget` event is now a timeline row). **A parked run says what it waits for** from an explicit list; a reason
  that is not listed reads "Waiting for you", not "Waiting for you in the browser".

Changed from the plan while building:

- **"Waiting for the model" is not read from a model call in flight.** The relay records a call when it ends (Part 1); recording its start as well would add a
  write to every model call. A live run with no tool running is waiting for the model, which Lumina already knows from the timeline.
- **The browser's state already travels in the task picture** (`browser`, `needs`). The app's own poll of `/v1/browse/<id>` also carries the page's pictures, the
  question and the control state, so taking it out is client work and moves to Part 5.

The plan as written:

- **Status line** (`work.py`): the newest step note while a tool runs ("Clicked Price: High to Low"), not only the category.
- **Named waits** from facts Lumina holds, replacing "Thinking" and the queue line:

  | Shown | Source |
  |---|---|
  | "Waking your workspace, about 90 seconds" | The lifecycle start operation; the time is the median of the last starts |
  | "Waiting for the model" with seconds | A model call in flight (Part 1's record) |
  | "Writing the answer" | The draft stream the bridge already carries |
  | "Waiting for the model provider, retrying in N s" | `ModelRelay.waiting`, which exists |

  The rule behind it: a wait past 10 seconds loses the reader unless it is named, and a wait with a known length shows it (Nielsen's limits).
- One row per browser step (the activity row and the note merge); a failed row carries its sentence; internal paths, "JEV" and "failed: covered" are worded
  for a customer.
- A failed step inside a run that still succeeded is listed in Details with its reason. The status line is marked only when a failure was not recovered (no
  later success of the same kind). Marking all 49 such runs would be noise: most are the assistant correcting itself.
- Limit events reach the timeline; the parked-reason fallback ("Waiting for you in the browser" for any unknown wait) becomes an explicit list.
- The browser's state travels inside the task picture; the app stops polling `/v1/browse/<id>` for status.
- Looked at and not taken: the runtime's own status digest (`session.observer`) and `progress_card`. The first needs extra model calls per run, the second
  duplicates `lumina_task_update`; both would add a second source of truth.

### Part 5 - The state picture, clients (I)

**Built and live 2026-11-24** (PR #101, release `a995a95`).

**Found by looking at the live app afterwards, and fixed (PR #102):** a task's record showed the browser's steps inside their call and, beside it, the old
separate notes. The push gateway (the stream of the task picture) was only in the rollback's restart list, so no ordinary deploy had restarted it: it was still
running the release of 23 November, eleven releases back, and the app merged its old picture with the current one from its own reads. So wherever the stream was
on, the changes of Parts 2 to 5 to the status line and the timeline were partly overridden since they shipped. The deploy now restarts the gateway with every
release, and the monitor's new `releases` check names any service that is not working from the current release. Unit tests could not have shown this: every
test builds the picture from the code under test; only the running services disagreed.

- **The blocks inside an answer read the shared picture.** Their status is the server's one status line and tone (they had five words of their own, so a task
  waiting for the customer read "Working" and an unconfirmed result read "Done"), and their steps are the server's timeline rows, with each failed step's reason
  and the browser's steps inside their call. The app's own copy of the timeline (`lib/activity.ts`, built from raw events) is deleted.
- **A plan's phase that ran** says what the shared state says about its task; a phase with no task yet keeps the plan's words.
- **The second phase type is gone** (`lib/tasks.ts` keeps one question: is this request unfinished).
- **Whether the browser is live is one answer, the server's** (`/v1/browse/<id>` now carries `live`: the page is alive and its task is still going). The app's
  own list of live states and its overruling of a stale "running" are removed.
- **The reason is read once** (the item left over from Part 2): the chat's messages mark the platform's "This task stopped..." notice, and the chat leaves it out
  where the task's status, with the same reason, is shown under the message. Where there is no status to read it from, the notice stays.
- **The tab says "Needs you" and "Done"** in its title and by a dot on its icon: while a task waits for the person, and when a task that was going ended while
  the tab was not being looked at (until it is looked at).

Looked at and left as they are:

- **The Chrome side panel** already reads the server's status line.
- **Telegram**: no chat is linked on production, no message has ever come from it, and replies are not sent back to it. Its texts still say "Agent execution is
  offline", which is untrue; they belong to the Telegram work of Phase 7, not to a status vocabulary nobody reads.
- **Long jobs** (`LongJobs.tsx`) describe a job of many turns, not one task: there is no task status line to read.
- **The "Stopped:" line under a reply** stays: it is the only place a surface without a status of its own would read why.

Still open in this part: the app's poll of `/v1/browse/<id>` (it also carries the page's pictures, the question and the control state, so taking it out means
moving those into the task picture first).

The plan as written:

- One vocabulary: the in-answer components (`gen/components/agent.tsx`), `PlanBlock`, `LongJobs`, the Chrome side panel and Telegram's status text read the
  shared label and gain "waiting for you", "partly done", "not confirmed".
- Delete the client's copy of the timeline (`lib/activity.ts`) and the second phase type (`lib/tasks.ts`); `LIVE_STATES` comes from the server; `Live.tsx`
  loses its override.
- The tab title and favicon show "needs you" and "done".

### Part 6 - Ask in place (D, E, J)

- One wait kind `question` added to `_human_wait`: the tool call stays open (up to the 30 minutes a parked run may wait), the request is parked, the customer
  answers on a card, the call returns the answer and the run carries on. No chat message is sent. If nobody answers in time, the existing hand-off row takes
  over and the task resumes later, as `lumina_ask_customer` does today.
- The tool is `lumina_ask_customer` extended, not a new one: one to three questions, each with options that may carry a picture, a price and details, always
  a free-text answer and a skip (the shape of the runtime's own `ask_user`, which cannot work in a cell). The cards come from the `lumina_show` registry.
- **Why the tools are unused** is settled first, on the harness: whether the assistant sees them (the tool directory, the skill text) and what it is told
  about when to ask. The browsing skill is rewritten so anything the task leaves open (which one, size, colour, address) is asked with options before acting.
- Approval for a connected-app call (E) and reaching the task limit (D) use the same wait: the call or the run holds, the customer sees one card ("Allow?",
  "The limit you set is reached. Continue with another $1?"), and work carries on in the same run. At 80% of the limit the status line says so.
- Product data and pictures are captured from the page and served from Lumina's own address (`card_images` exists).
- Unchanged: pay, buy, order, book and subscribe buttons are never pressed; `browser_press_approval` stays off; self-learning stays off.
- Each of the three behaviours has an owner switch that falls back to today's behaviour.

### Part 7 - Browser proof and behaviour (P, J)

- Run `browser-opt/lab` (23 everyday tasks, 10 hard ones) against the hosted stage on the server, which has never been done: the lab ran on a developer
  machine. Read the kept traces for `late_change`, `site_refused`, `browser_restart`, `agent_step_limit`.
- Fix what the traces show. Known candidates from `browsing-reliability.md`: a pop-up covering the page is clicked instead of closed; the customer's-own-Chrome
  engine and the cell's browser lack the waits and the restart; the extension still carries the old page script.
- The helper model's repeat on an unchanged page (run 395: "Clicked Men" three times) is checked against the step rules of PR #88 before anything is added.
- Honest target. The hosted browser presents itself as automated, and many shops refuse it; published measurements put most browsing agents near 30% on live
  sites and the best near 61%. So the measure is the **right ending** (finished, or a named stop said within seconds), not "finished".

### Part 8 - Start-up (K, H)

Measure, then change one thing at a time, on the harness and then on the server:

1. The web app calls `prewarm` when it opens (today only the old page and the side panel do).
2. A compile cache on the workspace's volume (`NODE_COMPILE_CACHE`), which the runtime's own notes recommend for small machines.
3. Two processors while the runtime boots (the browser stage opened pages in 25 s instead of 44 s with two).
4. The first model turn (65 s in run 395): what it reads before its first step, from the relay's record.

Target: a cold start under 45 s, and under 10% of requests meeting one.

### Part 9 - Housekeeping the contract needs (L, M, N)

- Log levels and disconnects (rule 5); the web app's "Control server error: Permission denied" line at every start.
- The 74 web API error strings move into the registry; the four spellings of "unavailable" become one.
- The roughly 70 silent handlers: each gets a fault, a stated reason to stay silent, or is removed. A blocking test forbids new ones.
- The 35 error classes get the common base that carries a fault.
- **M.** An automatic off-server backup copy through the existing `CommandDestination` (owner question 3).
- **N.** The two quarantined restores are reviewed and removed.

## 4b. Fit with Phase 14 (Cloudflare Code Mode)

Phase 14 (`capability-roadmap.md`, not started) puts a code-writing layer in front of the same tool relay: the assistant writes a short program that calls
several tools, instead of one tool call per model turn. It touches the same code as Parts 1, 3 and 4. Checked against the Phase 14 prompt, Cloudflare's
documents and the installed runtime, the two fit if five things are built with it in mind.

| Where they meet | What Code Mode changes | What this plan does about it |
|---|---|---|
| Part 1, the model-call record | Phase 14 needs a baseline of the direct path (C1) and per-turn tokens, cache use, turns, latency and cost (C3, item 4) | The record carries input, output and cache tokens from the start, so it is built once and is Phase 14's baseline |
| Part 3, tool failures | In a program a failure is a value the code must branch on; a sentence is useless to code, and one program can fail half-way | The fault is structured data first (kind, reason, retry, effect) and a sentence second. `unknown_outcome` matches the runtime's own "bridge failure, not replay-safe" rule |
| Part 3, tool descriptions | Prose descriptions are replaced by generated typed signatures | Wrong-argument work goes into the validation replies and one schema per tool (input and output) in the registry, which both paths use. Polishing prose descriptions is kept small |
| Part 4, the step display | The runtime sees one "ran code" call; the tool steps happen inside the adapter | Steps and faults of Lumina's tools are recorded by the relay, where every call still passes, not read back from the runtime's tool events. Otherwise the status line goes blind exactly when Code Mode is on |
| Part 6, waits | A program run is short (Cloudflare's default limit is 30 s and a resumed run starts its code again; the runtime's own is 10 s) | The ask tool, approvals, the limit pause and the browser are marked direct-only and never offered inside a program. Phase 14 already keeps approvals, writes and the browser on the direct path |

Two more facts from the installed runtime:

- **It has its own Code Mode, and the default is "auto"**: it switches itself on for models its catalog marks as preferred. It is not on in production (the
  recorded `exec` calls are shell commands, and Lumina's model route is not in that catalog), but nothing in `cell_config.py` pins it. Part 3 sets
  `tools.codeMode` off explicitly, so the tool surface changes only when Phase 14 decides it. Two other runtime defaults (tool search, self-learning) already
  caused production failures this way.
- **It is a candidate for Phase 14's comparison that keeps everything on the server.** Cloudflare's version runs the generated program, with the intermediate
  data, on Cloudflare's machines, which needs the owner's approval as a new recipient of customer data.

Order: Parts 1 to 3 before Phase 14. C1 can start as soon as Part 1 is live. Parts 4 to 9 do not wait for Phase 14 and are not undone by it.

## 5. Proof and targets

**What exists and is reused:** `platform/tests/e2e` (the real runtime with a stub model), `browser-opt/lab` (33 browser tasks), `deploy/acceptance_live.py`
(the probe each deploy runs), `deploy/latency_report.py`. New: a forced-fault test per reason code, and six non-browser live tasks (a file as .md, .docx and
.xlsx, a mail draft, a calendar change, a connected-app write that needs approval). No purchase is ever made. Rough cost of one full pass: under $1 at the
lab's measured prices ($0.45 everyday, $0.30 hard).

**Alerting rule at this volume.** Every `internal`, `needs_owner` and unclassified fault alerts the owner once, with the request number. The acceptance probe
runs on a timer as well as on deploy and alerts when it fails. No percentage alert until there are at least 50 real requests a day.

| Target | Today | After |
|---|---|---|
| Bad endings that show a cause, who acts and the next step | 5 of 15 | all |
| Failures with no registered reason | not measurable | under 2%, each one alerted |
| Real requests that end failed | 6% | under 2% |
| Wrong-argument failures, per tool | up to 36% (file delivery) | under 3% |
| A failed step shown without a reason | all of them | none |
| Child jobs alive after their request ended | 8 | 0 |
| Browser lab on the hosted stage: right ending | not measured | 30 of 33, three passes in a row |
| A wait over 10 s with no named state | every cold start and every first turn | none |
| Cold start | 76 to 100 s, 23% of requests | under 45 s, under 10% |

Then a seven-day watch with the daily report. A part that moves a target the wrong way is fixed before the next part starts.

## 6. Risks

| Risk | Handling |
|---|---|
| The runtime's structured error is documented but may not arrive through the bridge | Proven on the harness in Part 1; the relay's own record is the fallback and needs nothing from the runtime |
| Changing how `outcome.judge` words things breaks its fixed-vocabulary tests and what clients read | Field names stay; the tests move to the registry; one release moves server and app together |
| A parked question holds a workspace for up to 30 minutes | The limit that exists for the browser's question applies; after it the hand-off row takes over and the workspace is free |
| Loop detection stops a legitimate repeat | Tried on the lab tasks first; switched on only with no false stop |
| A new table is forgotten by restore, deletion or export | Named in section 3; the restore classifier fails loudly on an unknown table |
| Workspace settings (compile cache, processors, loop detection) reach a cell only at its next start | Same as every cell setting; the report shows which cells run which settings |
| `detail` leaks customer content | Facts only by construction (rule in section 3) and a test that feeds it page text and message text |

## 7. Decisions taken (and what each rests on)

- **Extend the connector contract.** It is in the code, tested, and its feature has the lowest failure rate.
- **Classify from the relay and the runtime's `errorDetail`, not from text.** Both exist; text matching already failed on run 390's wording.
- **Keep Lumina's state words; map them to the public protocols.** They already line up, and renaming would touch every client for no gain.
- **Ask in place by extending the existing ask tool and the existing wait.** No second tool, no new mechanism.
- **The limit pauses instead of ending.** The owner's standing rule is no new task limits; a pause keeps the work, and the amount stays the customer's setting.
- **Record and count first, probes apart.** Everything after is judged by the report, and 16% of today's numbers are probes.
- **Alert per failure, not per percentage.** Eight requests a day.
- **Browser target is the right ending.** Rests on the lab's own results and the published state of browsing agents.
- **No outside service for tracing.** The runtime could export to OpenTelemetry, but that sends run metadata off the server.

## 8. Questions for the owner

1. **Order.** Do this before Phase 7? Recommended: **yes.** Phase 7 adds unattended schedules, where a failure has nobody watching, and its notification
   "a failed run the customer must act on" needs the `actor` field.
2. **Limit behaviour.** At the task limit, pause and ask "Continue?" instead of ending? Recommended: **yes**, behind a switch.
3. **Off-server backup.** Where should the automatic copy go? It sends encrypted backups to an outside storage provider. Nothing else waits on it.
4. **The 8 stale browser records.** End them in the Part 3 migration? Recommended: **yes**; history is kept.
5. **How the hosted browser presents itself.** It says it is automated, and many shops refuse it (run 395's page fetch was refused). Leave as is?
   Recommended: **yes**; the customer's own Chrome is the existing way to use such sites.

## 9. Not established

- Whether `errorDetail` reaches the bridge on this runtime version (Part 1 proves it).
- Why the ask and show tools are never called (Part 6 settles it first).
- Whether PR #88 and #89 hold on the hosted stage (Part 7).
- Why files the assistant had written were "not found" by file delivery on 15 Nov.
- Four finished calendar and mail actions carry the ended reason "refused".

## 10. Sources

Code and records: `connector_kit.py`, `outcome.py`, `chat_driver.py`, `gateway.py`, `request_queue.py`, `model_keys.py`, `handoff.py`, `work.py`,
`browse/service.py`, `lifecycle/cell_config.py`, `ops/monitor.py`; `docs/architecture/browsing-reliability.md`, `state-and-recovery.md`, `findings.md`; the
installed runtime's documents (`gateway/protocol/rpc-bootstrap-and-events.md`, `gateway/protocol/ledgers.md`, `concepts/model-failover.md`,
`tools/ask-user.md`, `tools/loop-detection.md`, `tools/mcp.md`, `vps.md`).

Published: Google AIP-193 (one machine-readable reason per error, retry guidance separate); Stripe's error object (type, code, a message that may be shown);
Temporal (non-retryable is marked where the failure is raised); the Model Context Protocol's tool error guidance (a recoverable failure goes back to the model
naming the fix); OpenTelemetry (`error.type` from a small fixed set); the Google SRE workbook, "Alerting on SLOs", including its section on low-traffic
services; the A2A task states and the AG-UI event list; Nielsen Norman Group on response-time limits and on error messages; "Why Do Multi-Agent LLM Systems
Fail?" (arXiv 2503.13657); "An Illusion of Progress? Assessing the Current State of Web Agents" (arXiv 2504.01382).
