# Browsing lab

Runs Lumina's real browsing code on a developer machine against real websites, so a browsing failure can be reproduced, a change can be compared on the same tasks,
and speed, cost and completion can be read together. Nothing here is deployed, and nothing here touches the server.

| Real | Stand-in |
|---|---|
| `BrowseService`, the loop, the ladder, `JevChooser`, `Session`, `browse/runner.mjs`, Chrome, TypeSafe's JEV, the task wording (`adapter.build_goal`), what the assistant is shown (`adapter.asking_text`) | The assistant: the same model family through the `claude` command, given the `lumina_browser_step` tool description and the observations, keeping the conversation as the runtime would. The customer: answers from the task's `customer` entry, or the job is stopped and the question recorded. |

Not covered: the OpenClaw runtime itself (its 20,000-character cut of tool results, its own `web_fetch` and `web_search`), the Docker stage and its 1.5 GiB memory limit,
the server's network address (sites treat a data-centre address more harshly than a home one), the cell's own browser, and the customer's own Chrome through the extension.

## Running it

```sh
PY=platform/.venv/bin/python
$PY browser-opt/lab/lab.py run --out /tmp/run1 --jev-key-js <a JS file holding the TypeSafe key in a quoted string>     # or TYPESAFE_API_KEY in the environment
$PY browser-opt/lab/lab.py run --out /tmp/hard1 --tasks browser-opt/lab/tasks_hard.json --only amazon-add-to-cart
$PY browser-opt/lab/lab.py report -v /tmp/run1 /tmp/hard1
LAB_PROJECT=/path/to/another/checkout/openclaw-project $PY browser-opt/lab/lab.py run --out /tmp/before      # the same lab against the code before a change
$PY browser-opt/lab/takeover.py --out /tmp/takeover --jev-key-js <file>     # the customer signs in / takes the wheel through the control calls the Live view sends
$PY browser-opt/lab/route.py --old old-description.txt                       # which web tool the assistant reaches for first, per request
```

The key is read in the lab's own process and is never printed or written anywhere. Each run keeps, under `--out`: `results.jsonl` (one row a task), `jobs/<id>/trace.jsonl`
(the service's own step-by-step record), the run's pictures, and `transcripts/` (what the assistant was shown and answered).

## Reading the numbers

- **PASS/FAIL** is judged by the task's `expect` (the ending state and patterns the answer must contain). `needs_ok` and `refusal_ok` mark tasks where a site's human check or
  outright refusal makes "the customer was asked" or "the site refuses this browser" a right ending. Check the answers yourself before trusting a pass on a task whose facts change daily.
- **Cost** is the assistant's tokens at list price with nothing cached (`list_price`), plus JEV at $0.042 per million input tokens. The dollars the `claude` command reports
  depend on what happened to be cached and differ between two runs of the same task; the list-price figure does not. Production may cache and then pays less.
- **Seconds** include the stand-in's own start-up for each assistant call (about a second), which production does not pay, and exclude the runtime's own turn around a tool call, which it does.
- Sites change, rate-limit and block. One run is one sample: compare before and after back to back, and repeat.

## Tasks

`tasks.json` (23): reading, searching a site, forms, dropdowns, checkboxes, waits, popups, a sign-in wall, comparing, a cart. `tasks_hard.json` (10): the kinds of request
production records show (shop carts, flights, food delivery, big retail sites). Each task is the arguments the assistant would give `lumina_browser`.
