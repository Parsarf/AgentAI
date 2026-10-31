# JEV Browser (the bare loop)

```
goal -> open the page -> send a screenshot to JEV -> JEV says what to do and where -> do it -> send the next screenshot -> ... -> JEV says "done"
```

That is the whole app. JEV sees only the goal, what it already did, and a picture of the window (never the page's text or code). No planner, no second model. Features get added back one at a time.

## Run it

```bash
cd jev-browser
.venv/bin/python -m jevbrowse "Order me underwear from youngla.com"
```

A Chrome window opens and every step prints here: what JEV chose and how sure it was, what was done, and whether the page changed.
Put `TYPESAFE_API_KEY=...` in `.env`. Needs Python 3.10+, Node 22+ and Google Chrome. **Nothing to install**: there are no Python or Node packages at all (the browser side talks straight to Chrome over its DevTools protocol, using only what Node ships with).

Options: `--url` (start page; otherwise taken from the goal, or asked), `--text "boxer briefs"` (a text JEV may type; repeat it; default is the useful words of the goal),
`--steps 25`, `--headless`.

## Files

| File | Does |
|---|---|
| `runner/runner.mjs` | Starts Chrome (a fresh empty profile every run) and talks to it over the DevTools protocol, with no libraries. `open`, `look` (read the page as it is right now, for the log), `shot` (a picture sized for JEV), `probe` (what is under a point), `act` (click or type at a point, scroll, Enter). Lists up to 150 visible controls in page order; waits until the page goes quiet; follows new tabs; carries on in another tab if one closes; saves each picture it takes. No judgment. |
| `jevbrowse/browser.py` | Talks to the runner: `open`, `look`, `shot`, `probe`, `act`. |
| `jevbrowse/jev.py` | Sends JEV the screenshot (model `jev-1.14.0`, with the images header) and three kinds of question, and checks every answer: a choice from a list, a `box` (where on the picture), and a yes/no (is there something to use). |
| `jevbrowse/loop.py` | The loop, the questions, turning a box into a click point, and the two safety stops. |
| `jevbrowse/log.py` | The run log (below) and a reader for it. |
| `jevbrowse/goal.py` | The goal -> start page and search words, and reading `.env`. |
| `jevbrowse/dashboard.py`, `web/index.html` | The dashboard (below). |
| `jevbrowse/__main__.py` | The command line. |
| `tests/test_loop.py`, `tests/test_dashboard.py` | The loop, and the dashboard end to end, on a tiny local shop in headless Chrome with a stand-in for JEV. Run: `.venv/bin/python -m unittest tests.test_loop tests.test_dashboard` |

## What it does and does not do

- JEV can click, type one of the given texts, scroll down, press Enter, say "done", or say it needs you. To click or type it also points at the spot with a box; the middle of the box is where the browser clicks. Dropdowns are not supported yet. Every answer is checked.
- A pointing answer is used only if JEV is at least 50% sure something fits (yes/no) and at least 20% sure of the spot (the `box` number is not a calibrated probability: tune `MIN_FOUND` / `MIN_BOX` in `loop.py` from the logs).
- Before every click or typing, the browser looks at what is really under that point. A password field, or a button like "Place order", stops the run, because JEV never sees labels.
- After every action a fresh screenshot goes to JEV, whether or not the action worked. The page itself is still read after each step, only to log what changed.
- It stops and hands you the Chrome window on a password field, or before pressing a button like "Place order", "Pay", "Remove" or "Send".
- JEV gets no page text. The goal and the list of earlier steps are scrubbed of emails, long digit runs and long tokens.
- It stops after 3 answers in a row that point at nothing, or after `--steps` steps.

## The dashboard

```bash
.venv/bin/python -m jevbrowse.dashboard        # opens http://127.0.0.1:8766/  (--port, --no-open)
```

A local page (this computer only) that reads the same logs the loop writes:

- **Request**: write a goal, optionally a start page and a step limit, press Run (or Stop). "Show the Chrome window" keeps a visible Chrome next to the dashboard.
- **The page JEV was last shown**: a picture of every page JEV was sent, updated as the run goes. If the run stops for you (password page, risky button, "needs you"), the Chrome window stays open and is yours until you press "Close the browser".
- **What happened**: every step as it happens. For each page, a thumbnail and the list of controls it had; for each JEV call, what it was sent and its raw answer; its choice for every question with a probability bar; the action and whether the page changed; tab events. Filters: everything, key events, problems (red). A strip on top counts steps, JEV calls and errors, failed actions, actions that changed nothing, and tab closes.
- **Earlier runs**: every log in `logs/`, click one to read it. Runs saved before pictures existed show their steps without pictures.

One run at a time. It starts runs itself (same code as the command line), so the terminal command and the dashboard share every log. Not in the dashboard (yet): take over the browser, paste keys (the key comes from `.env`), a spending cap.

## The log

Every run writes `logs/<date-time>.jsonl` (and points `logs/latest.jsonl` at it) and a folder `logs/<date-time>/` with a small picture of each page JEV was shown (`--no-shots` turns the pictures off): one JSON line per event with timings. It is the full detail of what happened:

| Event | What it holds |
|---|---|
| `run_start`, `end` | The goal, start page, limits; how it ended and why |
| `page` | Each page JEV is shown: address, title, every control (number, kind, label, value) |
| `jev_call` | **Exactly what JEV was sent** (the scrubbed state and every question with its options) and **its raw answer**, with timing or the error |
| `jev_answer`, `decision` | What JEV chose and how sure it was; the action that resulted, or why nothing could be done |
| `runner`, `act` | Each command sent to the browser, how long it took, whether it worked, where the page is now, and whether the page changed |
| `runner_event` | Tab opened, tab CLOSED, navigations, dialogs, crashes, Chrome exiting (this is how a tab that vanishes shows up) |
| `runner_stderr`, `runner_error`, `crash` | Anything the browser process said, and any Python error with its traceback |
| `safety_stop` | A password page, or a button like "Place order" |

Read it as a timeline with problems marked `!` and a summary of what worked and what did not:

```bash
.venv/bin/python -m jevbrowse.log                       # the latest run
.venv/bin/python -m jevbrowse.log logs/<file>.jsonl --problems
```

`logs/` is git-ignored. It holds page text and what was typed, so look at a log before sharing it.

## Not here (yet)

Claude as a helper, a goal-making step, popup and cookie-banner handling, ranking of controls, taking over the browser from the dashboard, a spending cap,
confirming "done", loop guards. The earlier versions are saved next to this folder: `jev-browser-pre-remodel.tar.gz` (first), `jev-browser-v2-complex.tar.gz`
(the big design) and `jev-browser-v3-before-reset.tar.gz` (the version before this reset, with its screen and saved runs).
