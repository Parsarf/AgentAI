# Browsing redesign: what is built, what is next

Started 12 November 2026. The owner's confirmed decisions are in `docs/codebase-audit/BROWSER_REDESIGN_DECISIONS_AND_REFERENCE.md` (repository root). The reference for
decision behaviour is the standalone JEV extension at `/Users/parsa/jev-browser-extension/` (outside this repository; preserved, never modified).
The owner chose to port its behaviour on their experience of it, without a comparative benchmark. Nothing here has been deployed or run against a paid model.

## Built so far (in the working tree, tested locally)

### Stage 1: one page-script contract for the engines
- `describe` (the list of controls) is the same function in `browse/runner.mjs`, `browse/extension/src/page.js` and `platform/agentai_platform/browse/native_scripts.py`.
  It now lists a secret field always, then what a person can see and reach, then what is in the window but covered, then the rest, up to 80. Numbers still follow
  page order. Each control carries where a click on it lands (`x`, `y`), and the reply says what has the keyboard (`focus`: editable, label, value, the control's number;
  never a secret value).
- `browse/test/native-scripts.test.mjs` runs the native engine's script strings in real Chrome and holds them to the runner's answers. Before it, nothing executed
  the native scripts in a browser.
- The native engine scrolls the area under the pointer (a popup or panel before the page behind it) and says whether anything moved and whether the end was reached.

### Stage 2: decision behaviour from the reference (`browse/ladder.py`, `loop.py`, `modes.py`, `candidates.py`)
| Behaviour | Where |
|---|---|
| JEV is offered the controls a person could click right now (up to 80), not the first 20 in the page's code. Since 13 Nov 2026 the assistant, when a page is handed to it, is offered the same controls in the window together with the list it always had (`candidates.for_assistant`). | `candidates.reachable`, `Look.jev_candidates` |
| JEV is told what has the keyboard, what a click did to focus, and what a field reads after typing. | `JevChooser.focus_words`, feedback notes in `loop._run` |
| A click on a text field that already has focus is refused and JEV is told why. | `loop._run` (`already_focused`) |
| A picture click that lands on nothing clickable is moved to the listed control beside it (within 6% of the window), never onto a sensitive one. | `candidates.nearest` |
| A panel scrolling inside the page counts as progress, and JEV is told when it ends. | `loop._run` (`moved`, `inner`, `at_end`) |
| Escape is offered (engines that report focus). | `ladder.RUNNER_V3` |
| A stumble gets a second look: hand-over to the assistant after three dead steps or misses in a row instead of two; one failed step is retried with the reason. | `modes.py` thresholds, `ladder.MISS_LIMIT` |
| After two dead clicks JEV gets a nudge. | `modes.hint` |
| JEV's picture request may take 20 s (was 12 s) before it counts as a miss. | `ladder.PICTURE_DEADLINE_S` |

Kept on purpose: every code rule (payment, sign-in, sensitive buttons, denied sites), page-text neutralising, real browser input (not the reference's synthetic page
events), dropdown handling, asking the customer, saved logins, the assistant confirming "done", and the assistant taking over when JEV cannot go on.

Not ported: the reference's one-key-at-a-time keyboard (62 keys), its 600-character goal limit, and dropping page text from the request. The first needs engine and
bridge key lists widened; the other two would change what the assistant's task format relies on. They are candidates if results still disappoint.

An engine that does not report focus (an older runner) keeps the previous behaviour: every new behaviour is switched on by what the snapshot contains.

### Stage 3, first part: job states and records
- `browse/job_states.py` is the one definition of browser job states (`LIVE`, `WAITING`, `FINAL`, `OVER`). The service, the tool adapter, the web routes, the chat driver
  and the web client read it; the client's list had lacked `asking`.
- `interrupted` is a new ending: the service restarted (or lost the job) while it was unfinished. The record keeps every step and ends with the interruption; nothing is
  resumed. It does not count toward "the last two attempts failed". It is written by the tool call when it notices, and by the web app when a customer opens the task.
- When a customer opens a task whose job has ended and nothing was following it, the web app writes the ending and the whole step history into the record
  (this closes the "row stays `running` forever" gap the 28 October audit found).
- The browse service drops a finished job's step list and working data from memory after an hour (state, result and cost stay answerable).

### Stage 4, native engine: a tab per task, five active, two loaded (owner's choice C after the probe)
- `browse/tabs.py`: per account, up to 5 browser tasks run at once (`ACTIVE_LIMIT`), at most 2 keep a tab loaded (`LOADED_LIMIT`). One lock per account covers a whole
  command, so tasks take their steps in turn.
- `NativeRunner` owns its tabs: it opens a tab of its own, brings it to the front and names it (`targetId`) on every command, adopts only popups that appeared during its
  own step, and on close shuts only its own tabs. The browser stops when the customer's last task ends. Tabs the profile restored at start are closed and never adopted.
- A task whose turn comes without a tab gets its page opened again at the address it was on; the task idle longest makes room. The decider is told the page was reopened
  and that anything typed before may be gone. Sign-ins survive (shared profile); form contents and scroll position do not.
- While tasks share the browser, a watched task's live picture is taken from its own tab after each of its steps, because the one stream would show whichever task is stepping.
- The cell bridge passes a validated tab id on `act`, `navigate` and the picture call.

Limits of this part, stated plainly:
- **The customer's own Chrome (extension) still runs one task at a time.** Its link carries one command stream per account.
- **A task waiting for the customer still holds one of the five places** (but not a tab, once it has been idle longest). Waiting indefinitely needs the saved-task work below.
- **How five tasks get started at once is unchanged**: the host still runs one customer request at a time, so several browser tasks coexist only when one assistant run
  starts several, or earlier ones are still held open for the customer.
- Tabs share cookies and storage: two tasks on one shop share its cart and sign-in. That is the owner's decision, not isolation.

## Not built yet (in plan order)

| Stage | What | Why it is not done |
|---|---|---|
| 3, rest | Browser tasks as their own saved records with a job id of their own; tasks that wait for the customer indefinitely and release their tab and run | Touches the request lifecycle (run limit 900 s, park limit 1,800 s, reservations) and needs a schema migration |
| 4, rest | The same tab ownership for the customer's own Chrome; a run-time check on a real cell that commands with a tab id act on that tab; true parallel steps if that holds | Needs the new bridge deployed to a cell (not done: no deploy was authorised) and changes to the extension's single command stream |
| 5 | Task execution split from Live view and extension connections | A process and deployment change |
| 6 | Platform-paid JEV spend ledger, and the "continue on my budget?" pause at the limit | Money path; no limit has been chosen yet |
| 7 | Delete the Docker runner | Only after the native engine is verified on real cells; `browse/test/extension-parity.test.mjs` and the new native test both use `runner.mjs` as the reference copy and must be re-based first |

## Probe of the real cell, 12 November 2026 (owner's own cell, idle, no model calls, nothing deployed)

**Tab ids (read from the browser plugin's code inside the cell image, OpenClaw 2026.9.6, `routes-*.mjs`):** `POST /act`, `/screenshot`, `/navigate` and `/screencast`
each read an optional `targetId` from the body. So a command can name its tab; the plugin does not force "the current tab". This is what the code says. It was not
exercised at run time, because the deployed cell bridge strips every field it does not know (`cell_bridge._browser`), `targetId` included: the bridge must pass it
through (validated) before a run-time check is possible. The plugin also has act kinds Lumina does not use yet: `type`, `insertText`, `click`, `fill`, `select`, `hover`.

**Memory (measured with `docker stats` on the 2 GiB cell, pages were five Wikipedia articles):**

| State | Cell memory |
|---|---|
| Idle, no browser | 0.98 GiB |
| Browser started, no page | 1.33 GiB |
| 1 tab | 1.64 GiB |
| 2 tabs | 1.83 GiB |
| 3 tabs | 1.81 GiB |
| 4 tabs | 1.95 GiB |
| 5 tabs | 1.97 GiB of 2.00 GiB |
| Browser stopped again | 1.10 GiB |

Opening a tab took 3 to 9 seconds; a picture of the current tab took 2.4 seconds. Five light pages already sit at the cell's limit, and shop pages are heavier than
encyclopedia articles. **Five active tabs do not fit in a 2 GiB cell.** The host had about 10 GiB available at the time.
Caveats: one run, one cell, `docker stats` includes some reclaimable cache, and the profile restored a few tabs of its own (the probe closed every tab and stopped the
browser afterwards; the cell stayed healthy).

## Unproven

- That browsing is better. No model was called. The tests prove the new rules do what they say, not that tasks succeed more often.
- The native engine's new scroll and listing on a real cell. They are tested in desktop Chrome through the same script text, not through the bridge.
- JEV's behaviour with up to 80 options per question and the longer state text.
- Nothing was deployed. A deploy must be a full release: the changes span the app, the browse service, the extension and the runner image.
