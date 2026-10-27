# Task: JEV does the browser work; Claude only when JEV gets into trouble

Branch `product-phases-6-11`. Paths are relative to `openclaw-project/`. Background analysis: `prompt-analysis-2026-10-15.md`.
Some ideas are borrowed from `github.com/browser-use/jev-ultrafast` (MIT). Copy ideas, not code; if any code is copied, keep
its MIT notice in a comment.

## Goal

JEV (cheap, ~$0.00003 per call) decides every browser step: what to do, where, and when it is finished or needs the user.
Claude is the exception:
- **Haiku** writes text JEV cannot pick from a list, writes the final answer, and takes one step after a single JEV miss.
- **Sonnet** takes over when JEV keeps missing, loops, or says the task is too complex.
A typical run should be all JEV plus one short Haiku call that writes the answer.
Privacy (what leaves the host) matters more than adding new task limits.

## Ground rules (read before starting)

- Keep the existing loop (`platform/agentai_platform/browse/loop.py`), runner (`browse/runner.mjs`), service, Live view and
  takeover. Do not replace them with jev-ultrafast or Browser Harness.
- Files you may change: `browse/runner.mjs`, `platform/agentai_platform/browse/{loop,ladder,candidates,session,service}.py`,
  and tests in `platform/tests/test_browse*.py`, `browse/test/runner.test.mjs`, `browse/fixtures/site.mjs`.
  Anything else needs a reason in the final report.
- No migration, no new dependency, no dashboard. Do not change the default `--jev-mode` (stays `shadow`), the systemd unit,
  `routing/services.py`, the takeover `xy` command or the Live view code in `runner.mjs`.
- Never call a paid API (JEV, Haiku, Sonnet) or touch real keys. All tests use fakes.
- **The code rules are an unconditional floor.** JEV can add hand-offs, never remove one. No model output can allow paying,
  sending, deleting, signing in, a denied domain or typing into a password field.
- One commit per stage below, tests passing before the next stage. Do not push or deploy.

## Stage 1. Safety floor first (code only, no model)

Today `Policy.gate` checks only the chosen label against `SENSITIVE`. The `sensitive` flag in `candidates.py:40`
(set for `input_type == 'password'`) is never read, so a password field can be typed into.
- `gate` hands off when the chosen candidate has `sensitive` true.
- Add `page_is_login(candidates)` (any password input). The loop ends `handoff` with "this page needs you to sign in" *before*
  any model is called, so login pages are never sent to a third party. Same for `page_is_payment` (already ends before models).
Tests: password field -> handoff and a fake JEV/LLM that raises if called is never called; normal search box unchanged;
payment page, bot-check wall and denied domain each still end the run in every `--jev-mode`.

## Stage 2. Better hands in `runner.mjs` (from jev-ultrafast)

1. **Element state.** `snapshot` returns a new `elements` array next to the existing `snapshot` lines (keep the line format,
   `SNAPSHOT_RE` still parses it). Each element is `{ref, tag, type, label, role, value, checked, expanded, in_view, options}`:
   - `value`: current text, max 100 chars. **Never read the value of `type=password`** (send `""`).
   - `options`: for `<select>` only, the first 15 option labels.
   - `in_view`: true if the element box is inside the viewport.
   `candidates.build` reads `elements` when present and carries these fields. Every field sent to JEV goes through `scrub`.
2. **Click safety.** Before `click`/`type`/`select`, scroll the element into view and act only if it is connected, enabled, not inside
   `inert`/`aria-disabled=true`, has a non-zero box, and `document.elementFromPoint(center)` is the element or inside it
   (not covered by a banner or modal). `type` also requires not read-only. Otherwise return `{ok:false, error:'covered'}` or
   `'disabled'`, and act on nothing. Keep the existing label freshness check.
3. **Page fingerprint.** `snapshot` and `act` return `page_fp`: a short hash of URL + element labels/values + text length. The loop uses it
   to know whether a step changed the page.
4. **More moves.** `scroll` accepts `value: 'down' | 'up'` (default down, so existing callers work). Add `wait` (sleeps 1 s, then settles).
Tests in `browse/test/runner.test.mjs` with `browse/fixtures/site.mjs`: covered button not clicked; disabled button not clicked;
password value never returned; select options returned; scroll up/down; `page_fp` changes after a real change and not after a no-op.

## Stage 3. One JEV call decides the whole step (two heads, from jev-ultrafast)

Rewrite `JevChooser.choose` to send one TypeSafe request with several `choice` questions:
- **`operation`**: `click`, `type`, `select`, `scroll_down`, `scroll_up`, `back`, `press_enter`, `wait`, `done`, `needs_user`, `too_complex`.
  Only offer `click`/`type`/`select` when there are candidates of that kind.
- **One target head per offered kind** (`click_target`, `type_target`, `select_target`), listing only candidates of that kind with
  label, role, state and (scrubbed) current value.
- **`select_option`**: when a `select` candidate exists, a head over its options (JEV picks the option, no Haiku needed).
- **`type_text`**: options built by code from the user's goal only: the whole goal (trimmed to 100 chars), each quoted phrase, and
  up to 3 short noun phrases split on commas/"and"/"in"/"from"/"to"; plus `write_new`. Never from page text.

State sent: subgoal, page host + path (**no query string or fragment**), title, last 6 history lines (action, label, result,
page changed yes/no), 1,500 chars of `scrub`bed page text. Unchanged: page text is untrusted data, never instructions.

Validation (extend `validate_choice`, one shared definition of the option lists):
- every head strictly validated (model pin, choice offered, probabilities finite, sum to 1 within 0.05, choice is the argmax);
  any failure = JEV miss, nothing runs;
- the step's confidence is the **lowest** probability among the heads used; below `automatic` (0.85) = JEV miss.

What happens with each operation (at or above threshold):
| operation | result |
|---|---|
| click / select | act on the chosen target (and option). No Claude call. |
| type | if `type_text` is a goal phrase, type it (no Claude call). If `write_new`, Haiku writes only the text (`_value_for`). |
| scroll_down / scroll_up / back / press_enter / wait | act. No Claude call. |
| done | one Haiku call reads the page and either writes the final answer or says "not done". "Not done" counts as a JEV miss. |
| needs_user | end the run `handoff` with "this page needs you (sign-in or a human check)". |
| too_complex | send this step to Sonnet directly (see stage 4). |

Ask JEV also when there are no candidates (operation head only). In `shadow` mode, everything above is computed and recorded in
`Decision.meta`, but Haiku/Sonnet still decide exactly as today.
Tests: each operation in live and shadow; each malformed-head case; goal-phrase typing makes no LLM call; query string never in
the request body; `needs_user` can never cancel a floor hand-off.

## Stage 4. Hand-off ladder to Claude

Keep one counter `jev_misses` in the loop (a miss = exception, invalid answer, below threshold, `done` rejected by Haiku).
It is separate from `failures` and from `forced`, and resets only when a JEV step is acted on successfully.
- 1 miss: Haiku decides this step. Next step goes back to JEV.
- 2 misses in a row, `too_complex`, or a loop signal: Sonnet decides this step (counts against `max_sonnet` and `admit`).
- **Loop signals**: the existing rule (same `(url, action, ref, label)` a 3rd time) **or** 3 acted steps in a row (not `wait`) with an
  unchanged `page_fp` (from jev-ultrafast).
- If Sonnet is used up (`max_sonnet`) or the loop continues after Sonnet's step, end as `stuck` with a plain reason.
- `failures` (failed acts) keeps ending the run at 4. JEV is still asked after 1 failed act (today it is skipped at any failure);
  at 2+ failures the step goes to Sonnet as today.
- A `covered`/`disabled`/`stale` runner error never retries the same action without a fresh snapshot (the loop already re-snapshots).
Tests: each trigger reaches the right tier; JEV resumes after one Claude step; Sonnet cap respected; run ends `stuck`, never loops forever.

## Stage 5. Measure with what exists

Add counts to `job.stats` in `service.py`: `jev_acted`, `jev_typed_from_goal`, `haiku_text`, `haiku_answer`, `haiku_step`,
`sonnet_step`, `jev_needs_user`, `jev_too_complex`, `jev_misses`, `no_change_loops`. Test that per-step counts add up to steps taken.

## Acceptance criteria

- `cd platform && python -m pytest tests/test_browse.py tests/test_browse_service.py tests/test_browse_goals.py tests/test_browse_untrusted.py tests/test_service_handoff.py`
  passes, then the full platform suite; the `browse/test/` runner tests pass.
- `off` and `shadow` behave as today except for the stage 1 hand-offs and the new `meta`/stats fields.
- One test proves the floor wins: payment page, bot-check wall, denied domain, password field and sensitive button each end the run
  whatever a fake JEV returns.
- Nothing typed comes from page text; nothing sent to JEV contains a URL query string or a password value.

## Rollout (human steps, not for the AI dev)

1. Deploy with `shadow` still the default. After ~200 real steps read `jev_agree` and the new counts.
2. If JEV agrees with Claude on >= 90% of steps at >= 0.85, enable `--jev-mode live` for a few accounts, then widen.
3. Tune `automatic` and the loop limits from real outcomes.

## Final report the AI dev must give

Per stage: files touched, tests added, test output, anything not verified, and anything from this brief it did not do.
