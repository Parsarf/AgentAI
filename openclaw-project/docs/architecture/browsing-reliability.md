# Browsing reliability: what was wrong, what changed, what is still open

November 2026, branch `browsing-reliability`. Everything here was measured on a developer machine with the lab in `browser-opt/lab/` (the real browse service, the real
runner in real Chrome, the live JEV model, and a Sonnet stand-in for the customer's assistant). **Nothing has been deployed.** The lab's limits are in its README; the ones
that matter most are repeated under "Not proven" below.

## The browsing capabilities and how they fit together

| Capability | What it is | Where it lives |
|---|---|---|
| `web_search` | The runtime's own search (Brave) | The customer's cell (OpenClaw) |
| `web_fetch` | The runtime's own page reader: one HTTP request, readable text, no scripts, 20,000 characters, cached 15 minutes | The customer's cell (OpenClaw) |
| `lumina_browser` | One website task in a browser the customer can watch: JEV chooses each step from the page's controls and a picture of the window; the assistant takes a step (`lumina_browser_step`) when JEV cannot | `platform/agentai_platform/browse/` (service, loop, ladder), `browse/runner.mjs` |
| Take-over | The customer pauses the task or is asked to do their part (a sign-in, a human check), acts in the same browser from the Live page, and gives it back | `browse/service.py` (`pause`, `control`, `resume`, hand gate), `lumina/src/pages/Live.tsx` |
| Questions to the customer | The browser stops and asks (a size, "use your saved login?", form details, and now "may I press this button?") | `browse/loop.py`, `browse/service.py` (`_ask_gate`, `answer`), `lumina/src/components/BrowserQuestion.tsx` |
| Three sets of hands | The host's Docker stage (production default), the cell's own browser, the customer's own Chrome through the extension. One page script for all three | `browse/runner.mjs`, `native_scripts.py`, `browse/extension/src/page.js` (generated: `browse/sync-page-scripts.py`) |

## What the evidence said before any change

**Production records** (read-only, 32 days to 20 November): 46 browser runs, **6 ended `done`**, none after 28 October. The rest: 12 "the browser run failed" (one timeout, one
crashed browser, or a failed first open ended the whole task), 11 stopped by the owner part-way, 5 where the *request* ran out of its spending limit while the assistant was
taking every step, 3 "no answer to the question", 8 records left at `running`.

**The lab, unchanged code** (23 everyday tasks): 19 passed. Every failure had a cause that could be read in the trace and reproduced:

| Cause | Seen as | Fix |
|---|---|---|
| A control the page gave no name was dropped (an unlabelled `<select>`, checkbox, icon button) | "The dropdown is not in the page's list of controls" | Named by its first option, the words beside it, or what the code calls it |
| Controls inside open shadow roots were invisible (Open Library's and MDN's search box, cookie banners, cart drawers) | JEV clicked "Search" three times; the field never appeared in the list | The page script walks open shadow roots: listing, focus, hit-testing, fingerprint, words |
| Size and colour pickers (a hidden radio button under a styled label) were not listed, and an existing test asserted that such a box is "covered" | The assistant read "Small Medium Large" in the text, could not choose, added the default size, then tried "Remove" | Listed where the label is; a step on it goes to the label |
| Custom dropdowns, their options, menu items and switches (ARIA `combobox`, `option`, `menuitem`, `switch`) were not controls | A flight search stayed on "Round trip": "One way" could only be reached by pointing at a picture, and the assistant has no picture | Listed like any other control, with their open/chosen state |
| The page's words were always the first 6,000 characters of the document, whatever the scroll position | Scrolling showed JEV and the assistant nothing new; cut-off names ("The Road to Little ...") | Words start with the window; cut-off names are read from their title; the assistant gets the whole page in page order and a `read` step for long pages |
| A click was judged "nothing changed" before the page had changed | JEV repeated a click that had worked, then "stale", then a loop | The runner waits up to 0.9 s for a change; the loop credits a change it sees at the next look |
| A page was read between two pages (blank) | JEV called for the customer on an empty page | The snapshot waits up to 3 s for something to be drawn |
| A wait for a page still loading counted as "repeating the same step" | A 5-second spinner ended the task as `stuck` | Waits have their own count (assistant at 5, end at 10) |
| The assistant was shown names only: no ticked/selected state, no field contents, no dropdown options | "The page text doesn't show whether each box is checked" | Every control line carries its state and a dropdown its options |
| JEV said "click", "none of the listed", and could not point; a text field was chosen firmly in the same answer | Three misses, then the assistant filled the whole form (7 calls) | Read as typing into that field; a miss is not asked again on the same page |
| JEV's low-confidence steps were acted on like any other | Every wrong step in the first run sat under 0.5: a dead scroll, leaving the page it needed, asking the customer something settled | Under 0.5 for the step itself, the assistant takes that one step (scrolls and waits are exempt) |
| JEV scrolled through long lists "to see them" | 6 to 12 scrolls, then a take-over | JEV is told the whole page is read for it when it chooses `done`; dead scrolls are not offered |
| One stumble gave the assistant every remaining step | Each step is a paid call carrying the whole conversation: the production "spending limit" endings | The assistant takes the stuck step and JEV carries on; the third time it keeps the task; it gets a slim view while it works; at most 12 assistant steps a task |
| JEV's pick of a consequential button ended the task | "Remove" in a cart the task had just filled | The assistant is asked first; only what it also chooses goes to the customer |
| A non-payment "consequential" button could only end the task ("Remove", "Confirm", "Submit" also match chips and search forms) | Hand-off, task over | The customer is asked about that one button and, with their yes, it is pressed. Anything that pays or orders is never asked about and never pressed |
| A link or button whose name mentions "credit card" made any page a payment step | A sports shop's search page ended as "reached a payment step" | Only a card *field* counts; the words rule reads the window, not the footer |
| "The same step a fourth time ends the task" counted JEV's repeats against the assistant | The task ended on the assistant's second step after it took over | The assistant starts with a clean count; its own repeats still end the task |
| The browser's own error page was called "a site that is not allowed" | `blocked` after a dropped connection | Loaded again twice, then "the site stopped answering" |
| A site that refuses the browser (403 "Access Denied", eBay's "Something went wrong, go back") looked like a page to act on or a human check | JEV went back and searched again for a minute; the customer was asked to "verify" a page with nothing to verify | Recognised from the HTTP status; asked once more, then ended at once with what to do instead |
| A human check under a long menu was not recognised | DuckDuckGo's challenge page | A challenge's own wording counts anywhere on the page |
| One slow read or one dead browser ended the task | "the browser run failed (TimeoutError / RunnerError / BrokenPipeError)" | A read is asked once more; the host stage is started again once on the same address and the deciders are told; every runner command has its own limit; pictures no longer wait for web fonts |
| A failed first open was final | "could not open the page" | Opened once more after 2 s |
| The Live page showed nothing for a waiting question | Every question ran out after five minutes ("no answer to the question") | `BrowserQuestion` on the Live page: choices, form details, saved login or card, permission for one button |
| The three engines' page scripts were three hand-kept copies | Drift held back only by tests | Generated from `runner.mjs`; a test fails when they differ |

## Speed

The runner waited for the network to go silent after every page and many steps; most real sites never do, so that was a fixed 2.5 s. It now waits until the page itself has
stopped changing (two looks 150 ms apart, loaded) and never longer. JEV itself answers in about 200 ms (median over several hundred calls; p90 about 300 ms): the time is in
pages loading and in the assistant's calls, not in JEV.

## Which tool the assistant reaches for

The only routing guidance the assistant has is the browser tool's own description. It now says what each of the three is for and tells the assistant to read with
`web_fetch` when that can read the page, and to bring a page `web_fetch` returned empty, cut off or "enable JavaScript" to the browser. When the browser ends without a
result (an error, a refusal, a human check) its answer names `web_search` and `web_fetch` as the next thing to try. Measured with `browser-opt/lab/route.py` (18 requests, twice
each, first tool call only): 34 of 36 fitting before, 36 of 36 after. This is a small test of wording, not of the runtime.

## Results (same tasks, old and new code back to back; cost at list price with nothing cached)

**Everyday tasks** (`tasks.json`, 23 tasks: reading, site search, forms, dropdowns, waits, popups, a sign-in wall, comparing, one shop cart).

| | Passed | Ended `done` | Seconds, all tasks | Seconds, without the cart task | Cost | Assistant calls |
|---|---|---|---|---|---|---|
| Before (`main`) | 19 of 23 | 18 | 359 | 302 | $0.37 | 35 |
| After, run 1 (before the last four fixes) | 22 of 23 | 20 | 336 | 239 | $0.40 | 30 |
| After, run 2 (before the last three fixes) | 22 of 23 | 20 | 405 | 237 | $0.50 | 36 |
| After, final code | 23 of 23 | 21 | 456 | 313 | $0.45 | 33 |

The two tasks that pass without `done` are the sign-in wall and DuckDuckGo's human check, where asking the customer is the right ending. The task that failed in runs 1 and 2 is
the shop cart (size Medium on a real clothing shop): it failed on `main` in 4 of 5 runs and passed in 4 of the 5 runs made after the size-picker fix (the one failure ran
into the step limit), but it is slow (about 2.5 minutes) and costs $0.17 to $0.28, because the assistant takes most of its steps. That one task is why the "after" totals for time and cost are not lower.

**Speed, plainly:** not a clear win. On the 22 tasks other than the cart the changed code took about 20% less time in two runs and slightly more in the third, which ran
while everything was slower (JEV's own answers took 2.5 times as long that half-hour). Opening a page got faster (about 3.0 to 3.2 s against 4.2 s in two of three runs); a
step got slower on average (about 1.5 to 1.9 s against 1.1 s) because a click that seems to change nothing is now watched for up to 0.9 s. What changed reliably is the number
of wasted steps: tasks that looped before (a documentation search 34 s and 6 assistant calls; a news front page 30 s) now take 12 to 22 s and one call.

**Hard sites** (`tasks_hard.json`, 10 tasks modelled on production requests), one run each side by side, then the four tasks that actually run to an answer three more times each:

| | Right ending | Ended `done` | Seconds | Cost |
|---|---|---|---|---|
| Before | 7 of 10 | 3 | 276 | $0.15 |
| After, final code | 10 of 10 | 5 | 221 | $0.30 |

Five of the ten are sites that refuse or challenge the browser (Zara, eBay, DoorDash, Stack Overflow, Allrecipes): the "right ending" there is saying so. Before, eBay looped
for 70 s on its error page and Zara's refusal was shown to the customer as a human check to pass; now both end in 6 to 30 s with the refusal as the reason.

| Task, three runs each | Before | After | Notes |
|---|---|---|---|
| Amazon: find a racket, add it to the cart | 2 of 3 | 3 of 3 (and 1 of 1 on the final code) | about 22 s, $0.014 |
| Clothing shop: joggers in size Medium into the cart | 1 of 3 | 3 of 3 (and 1 of 1) | about 2.5 min, $0.17 to $0.28 |
| Sports shop: find a sleeveless tennis top, price and sizes | 1 of 3 | 3 of 3 after the payment false alarm was fixed (and 1 of 1) | about 35 to 60 s, $0.13 to $0.20 |
| Google Flights: cheapest one-way flight on a date | 2 of 3 | 0 of 3, then 1 of 3 after the combobox fix, then 1 of 1 on the final code | see below |

**The flight search is not reliable, and for part of this work it was worse than before.** On `main`, JEV worked the form mostly from the picture and got there twice in three
runs. With the new rules the assistant is brought in earlier, and the assistant has no picture: until custom dropdowns were listed as controls it could not switch the trip to
one way and went round in circles (0 of 3). After that fix the form is filled in correctly each time; two of the next three runs ended on Google's own "No results returned.
Oops, something went wrong" page (possibly a reaction to the amount of automated traffic these tests produced), and one run on the final code returned the right answer. Four
runs is too few to call it fixed.

**Take-over** (`takeover.py`, live): the customer signs in through the Live page's own control calls and the task carries on by itself and reads the signed-in page; the customer
takes the wheel mid-task, scrolls, tries a private address (refused) and gives it back, and the task finishes. Both passed on every run (3 of 3).

**Cost, plainly:** an everyday task costs about one to two cents either way, nearly all of it the assistant's single call that confirms the result and writes the answer; JEV's
own steps are a small fraction of a cent a task. The cost that matters is the assistant working through a task step by step: 8 to 13 calls and $0.13 to $0.28 on the three
heavy tasks, at list price with nothing cached. Before, such a take-over had no bound short of the task's own limits (one unchanged-code run cost $1.08 and failed); now it is
capped at 12 assistant steps and each step carries less. It is still the expensive path, and the heavy tasks still depend on it.

## What the first production runs showed (2026-11-22), and what was changed for them

Four attempts at one task on the evening the work above went live (an order on a clothing shop), read from the service traces, the event stream, the
server log and the assistant's own session record. None of the causes was in the page-reading or decision code above; each was one layer out.

| Seen as | Cause (with the evidence) | Change |
|---|---|---|
| "The assistant could not finish this request", 3 seconds after sending, no tool used | The runtime's self-learning (`skills.workshop`, on by default) ran a background model turn 35 s after the task before it ended. No task was running, so Lumina's gateway refused the call with **403**; the runtime reads a 403 from its provider as a bad key and disables the key for about a minute; the customer's next message arrived 10 s later | Cells are configured with `skills.workshop.autonomous.mode: off` (a background review is a model call no task pays for, or one charged unseen to whichever task is running). The gateway refuses "not allowed right now" with **409** (`model_keys.RELAY_REFUSAL`). Proven on the real runtime: after a 403 the next message fails, after a 409 it does not (`tests/e2e`) |
| "The browser task could not be read (site ...)" as the first step of every browser task | The runtime keeps tool schemas out of the prompt, so the assistant called the tool with the names it guessed: `url` and `done_when`, where the tool says `site` and `steps` | The tool takes the names assistants send (`url`, `website`, a link written in the task, steps as one text, `c12` or `"12"` for a control, `text` for a value, `scroll_down`), still bounded and checked; the schema requires only `task`, because the runtime refuses a call that breaks the schema before Lumina sees it; a refusal now lists the exact arguments |
| "Tool web_fetch not found", "Tool web_search not found" | In the runtime's default tool mode a tool is reached through `tool_call` with an id; Lumina's own messages say "use web_fetch and web_search" | Cells use `tools.toolSearch.mode: directory`, where a tool's plain name runs as that tool; the browsing skill names the tools and their arguments |
| "could not open the page (navigation_failed)" after 30 s on a shop whose server answers in under a second | The stage had one processor, and the runner waited for "content loaded" within 20 s. Measured on the server: the shop's home page took 43.6 s to open, read once and close with one processor, 25.2 s with two | Two processors and 2 GiB; a page is open once the site has answered (30 s), and a page that is still loading 25 s later is used as it is (`still_loading`), never failed |
| A second try at opening a page could never work | After a failed navigation the tab is on its way to the browser's own error page, and the next `goto` is "interrupted by another navigation". So since the first release, one failed open failed every open after it | The task carries on in a fresh tab of the same browser |
| The server ran last week's runner under this week's service | The runner in `/opt/agentai-browse/runner` was a copy made by hand | Each release carries its own copy (`hosted_runner.mjs`), mounted over the installed one |
| "2 at the same time" over two page reads | True: the assistant read two different pages in one turn | None needed |

The record of all browser runs before these changes (60 since 13 October): 9 `done`, 12 `error`, 16 `stopped`, 11 `cancelled`, 8 left at `running`, 2 `blocked`, 2 `budget`.

Still open after this round: no browser task has been watched end to end on the hosted browser with all of the above; the task that prompted it ended correctly only in the
customer's own Chrome (the products were out of stock); a marketing pop-up that covers a page is still clicked rather than closed on purpose; after a refusal for an
exhausted allowance (402) the runtime disables the key for ten minutes, so a customer who then switches to their own model waits that long.

## Not proven, and known limits

- **Nothing is deployed, and nothing was run on the server or in a cell.** The runner changes were run in desktop Chrome, not in the Docker stage (no Docker on the machine): its
  1.5 GiB memory limit, the restart of a dead stage, and the stage's Chromium build are untested there.
- **The assistant in the lab is a stand-in.** The real one works inside OpenClaw, which cuts a tool result at about 20,000 characters and may or may not cache earlier
  results. Costs here are list price with no caching; production may pay less. The assistant never sees a picture (the runtime turns the tool result into text), which is why it
  does badly on pages that are mostly a widget.
- **Sites that refuse or challenge the browser are not solved, and were not meant to be.** The hosted browser says it is `HeadlessChrome` and that it is automated; from this
  machine Zara, eBay, Allrecipes and DoorDash answered 403, and DuckDuckGo, Stack Overflow and Open Library showed a human check or cut the connection. The change is that
  this is now recognised in seconds and said plainly. Whether the browser should present itself differently is the owner's decision and was not tried. The customer's own
  Chrome (the extension) is the existing way to use such sites.
- **Heavy, widget-driven sites are still unreliable and expensive** (a flight search above all). See the heavy-task table: no claim of reliability is made for them, and none
  of competitive performance against other browsing agents: nothing here was run on a public benchmark.
- **The cell's own browser and the extension** got the shared page script and the whole-page text, and were tested in real Chrome through their own test suites. They did not
  get the runner's waits (for a late change, for a blank page), the HTTP status, or the restart. No live run was made on either.
- **Cross-origin frames** (payment frames, some consent banners) are still reached only by pointing at the picture; closed shadow roots are not reached at all.
- **The 0.5 floor, the three-stumbles rule and the 12-step cap** rest on a few hundred lab steps on about thirty tasks. They are constants at the top of `ladder.py` and
  `loop.py`, with the reason beside each; they should be re-read against production traces once there are some.
- **A pre-existing test problem, not caused here:** `browse/test/extension-executor.test.mjs` passes its 13 tests and then does not exit (the same on `main`).

## Before deploying

It is one release: the app (the question panel, the tool wording, `adapter.py`), the browse service, and the runner bundle in `/opt/agentai-browse/runner` must move together
(the loop relies on fields only the new runner sends, and falls back to the old behaviour without them, but the fixes are in the pair). The extension's page script changed,
so the extension needs a new package for the customer's-own-Chrome engine to get it. After the deploy, the first things to read are the traces of real tasks
(`python -m agentai_platform.browse.trace <request id>`): `late_change`, `site_refused`, `browser_restart`, `second_opinion`, `agent_step_limit` and `jev_followup` rows say
how often each new rule fired.
