# Prompt: let JEV drive the browser agent (act / hand off / too complex / escalate to Claude)

Status: analysis brief, nothing built. Written 2026-10-15 against branch `product-phases-6-11`, HEAD `b2115cb`
(code identical to release `live6` = `f8658ee`). Paths are relative to `openclaw-project/`.

---------------------------------------------------------------------------------------------------

## 1. The goal (owner's words, tidied)

Today JEV (TypeSafe, model `jev-1.13.0`) only decides *which service* to use for a web-related message
(browser / web search / direct answer). The owner wants JEV to decide **every step inside the browser** so Claude
spends far fewer tokens:

- JEV receives the page information and chooses between:
  1. an **action** (click / type target / select / scroll / ...),
  2. a **hand-off to the user** for passwords, logins and captchas,
  3. **"too complex"**, which sends the task to Claude,
- and when JEV is **looping, failing or lost**, JEV (or code watching it) **hands the task to Claude**.
- Claude should be the exception, not the default decider.

## 2. How it works today (verified by reading the code)

### 2.1 Where the pieces live

| Piece | File | Notes |
|---|---|---|
| Run loop (observe, decide, gate, act) | `platform/agentai_platform/browse/loop.py` (143 lines) | `BrowseRunner.run`, `Policy.gate` |
| Who decides each step | `platform/agentai_platform/browse/ladder.py` (192 lines) | `Ladder.decide`, `JevChooser`, `validate_choice`, `_shadow`, `_value_for` |
| Candidate builder + hand-off regexes | `platform/agentai_platform/browse/candidates.py` | `build` (max 20), `SENSITIVE`, `CARD_FIELD`, `page_is_payment`, `page_is_bot_check` |
| Job service, ladder wiring, events, stats | `platform/agentai_platform/browse/service.py` (~l.282-300) | `Ladder(tracked, admit=..., jev=jev, shadow=(jev_mode=='shadow'))` |
| Process entry, JEV client, flags | `platform/agentai_platform/browse/service_main.py` | `--jev-mode off\|shadow\|live` (default `shadow`), `--jev-key-file`, endpoint `https://api.typesafe.ai/v1/systemone` |
| Scrubber for third-party calls | `platform/agentai_platform/privacy.py` | `scrub()` removes emails, phones, card/account/ID numbers, addresses, IPs, URL creds, token-like strings |
| Page-text hardening | `platform/agentai_platform/browse/untrusted.py` | `neutralize()` |
| Goal text | `platform/agentai_platform/browse/goals.py` | `instruction_text()` |
| Chat side (starts browse, polls, stores `jev_asked/jev_agree`) | `platform/agentai_platform/chat.py` ~l.762-870 | |
| Chat-level service choice (the thing that works today) | `platform/agentai_platform/routing/services.py` | not part of this change |
| Unit/integration tests | `platform/tests/test_browse.py` (16), `test_browse_service.py` (20), `test_browse_goals.py`, `test_browse_untrusted.py`, `test_service_handoff.py` | |
| Systemd unit | `platform/deploy/agentai-browse.service` | has **no** `--jev-mode` flag, so it runs the `shadow` default (not confirmed on the server) |
| DB columns | `platform/migrations/0019_browse_runs.sql` | `jev_asked`, `jev_agree` |
| Switches | `platform/agentai_platform/switches.py` | `browse_tasks`, `jev_services`, `jev_routing`, `browser_optimization` |

### 2.2 The step loop (`loop.py:62-138`)

Per step, in this order:
1. cancel / pause / deadline checks (default `max_steps=25`, `max_seconds=600`; the service passes per-job values).
2. snapshot the page; reject if the URL left the allowed set (`Policy.url_ok`, `DEFAULT_DENY` banks and payment sites).
3. **Bot-check wall**: wait 4 s up to 3 times; if still a wall, end with status `handoff` (`WALL_REASON`).
4. build up to 20 candidates (`candidates.build`) and a `page` dict (`neutralize`d title and text).
5. **Payment page** (`page_is_payment`) ends with `handoff` before any model is asked.
6. `ladder.decide(goal, history, page, candidates, force_escalate=forced, failures=failures)`.
7. `Policy.gate`: hand off if payment page or the chosen label matches `SENSITIVE`.
8. repeat detection: the same `(url, action, ref, label)` seen more than 2 times sets `forced=True` (next step goes to Sonnet),
   more than 3 times ends as `stuck`.
9. act; a failed act increments `failures`; 4 consecutive failures end as `stuck`.

### 2.3 Who decides, by mode (`ladder.py:128-192`)

- `off`: Haiku, then Sonnet. JEV not created.
- `shadow` (current default): Haiku, then Sonnet decide. Afterwards JEV is asked the same question and the agreement is
  recorded in `Decision.meta` and counted in `job.stats` (`jev_asked`, `jev_agree`). JEV never changes anything.
  Cost about $0.00003 per step.
- `live` (built, never used in production): in `Ladder.decide`, **only if** `jev and not shadow and candidates and not
  force_escalate and failures == 0`:
  - `JevChooser.choose` sends the subgoal plus 1,500 chars of scrubbed page text plus the candidate labels (each label
    scrubbed to 120 chars). It must return `answers.action` of `type: choice` with a probability per option.
  - Options are the candidate ids plus `escalate`, `stop`, `no_valid_action` (`SPECIAL`).
  - `validate_choice` rejects: wrong model string, choice not offered, probabilities not summing to 1 (tol 0.05),
    non-finite values, choice not the argmax.
  - A special choice or probability < `automatic` (0.85, "provisional, calibrate on real outcomes") or any exception falls
    through to Haiku (then Sonnet). A `Refused` (budget) ends the run.
  - A `type` choice: Haiku supplies only the text (`_value_for`), JEV chose the field.
  - If there are **no candidates**, JEV is skipped and Haiku decides.
- Sonnet is used only when `force_escalate` or `failures >= 2`, at most `max_sonnet=2` times per run, or after Haiku returns an invalid answer.

## 3. Gaps against the goal

| # | Goal | Today | Gap |
|---|---|---|---|
| G1 | JEV sees all the info | 1,500 chars of page text, labels only, no step history, no URL/title | too little context; JEV is asked a single question with no history |
| G2 | JEV chooses "hand off for password / captcha" | Hand-offs are regexes in code (`page_is_bot_check`, `page_is_payment`, `SENSITIVE`). JEV has no such option | add options; keep regexes as a floor |
| G3 | JEV chooses "too complex" | only `escalate` (and `stop`); `escalate` falls to **Haiku**, not Claude Sonnet | add a distinct route; define "Claude" (Haiku vs Sonnet) |
| G4 | JEV in a loop or problem hands to Claude | code detects repeats (`seen`), failures; effects: 3rd repeat sets `forced` (Sonnet); 4th repeat or 4 failures ends the run as `stuck`. JEV itself is skipped whenever `failures != 0` or `force_escalate` | partly there; "JEV errors / low confidence streak" is not a trigger; `stuck` never goes to Claude |
| G5 | Claude spends few tokens | every `type` step still costs a Haiku call; any JEV fallback is Haiku first | measure how often JEV acts at >= 0.85 vs falls back; that number is unknown |
| G6 | live mode is safe to enable | never run in production; threshold uncalibrated | needs the benchmark (section 6) |

### Finding to check (possible existing gap, not caused by this change)

`candidates.build` computes `'sensitive': bool(SENSITIVE.search(label)) or input_type == 'password'` (`candidates.py:40`), but
a grep shows **nothing reads `sensitive`**. `Policy.gate` (`loop.py:38`) tests only the *label* against `SENSITIVE`, and
`SENSITIVE` does not contain "password" or "log in / sign in". So a password input (`type` on `input type=password`) is **not**
handed off today; only the models' instructions stop it, and the product has no saved logins to type. Decide whether the gate
should also hand off on `input_type == 'password'` and on login-form pages. This is independent of JEV but becomes load-bearing
once JEV (which cannot write text) is the first decider.

Corrections to what I said earlier in the chat: (a) the loop does escalate a repeated step to Sonnet on the 3rd repeat
(`forced = True`), it only ends as `stuck` on the 4th; (b) the `escalate` answer from JEV goes to Haiku first, not to Sonnet.

## 4. Proposed design (for you to accept, cut or change)

1. **More JEV options.** Extend the `criteria` in `JevChooser.choose` and `validate_choice`/`SPECIAL` with:
   `needs_user_login`, `needs_user_captcha`, `too_complex` (keep `escalate`, `stop`, `no_valid_action`).
   - `needs_user_login` / `needs_user_captcha` -> loop ends `handoff` with a plain reason (reuse `WALL_REASON` style).
   - `too_complex` / `escalate` -> go straight to Sonnet (skip Haiku), still capped by `max_sonnet` and `admit`.
   - JEV may only **add** hand-offs. The code rules (`page_is_bot_check`, `page_is_payment`, `SENSITIVE`, deny-list) stay
     as an unconditional floor that JEV can never override.
2. **JEV-error / loop ladder to Claude.** Count consecutive JEV problems (exception, timeout, invalid response, special
   choice, below threshold). After N (suggest 2) set `forced`; also on the 3rd repeat (already there) and instead of
   ending `stuck` once, give Sonnet one chance (within `max_sonnet`). Only then end the run.
3. **More context to JEV.** Add URL, title, the last 6 history lines (the same text `render()` builds) and raise page text
   from 1,500 to a configurable size (3,000 or 6,000 chars; still `scrub`bed).
4. **Typing.** Keep Haiku writing field text (JEV cannot produce text, by design of the `choice` API). It is one short call
   per typed field, not per step.
5. **Do not call JEV on pages that must not leave the host** (login form / password field present): treat as a hand-off
   with no third-party call.
6. **Observability.** Record per run: steps decided by JEV / Haiku / Sonnet, escalation reason, JEV tokens and cost,
   agreement in shadow. Extend `browse_runs` (migration `0020_...`) or the events payload; show it on the owner dashboard.
7. **Rollout.** Ship behind the existing flag. Run `shadow` with the new options first, then the benchmark, then `live`
   for a small set of accounts, then default.

## 5. Privacy and safety (needs an explicit owner decision)

- Sending fuller page content to TypeSafe sends customer data on the page (order details, addresses, anything visible after
  login) to a third party. `plans/phase-4a.md` records that TypeSafe says requests are not used to train Jev, but public DPA /
  privacy terms **do not promise a fixed retention period**; enterprise zero-retention is separate.
- Existing mitigations to keep: `privacy.scrub` on everything sent, `neutralize` on page text (page text is untrusted data,
  never instructions), JEV picks only from code-built candidate ids, the browse sandbox has no saved logins, read-only policy
  stops before any payment, per-run budget via `admit`.
- Open question: allow full page text to JEV on all pages, or only pages with no login/personal data (item 5 above)?
  The standing project preference is to focus on data leakage and customer privacy over adding new task limits (owner
  memory note `feedback_privacy_over_task_guardrails.md`), so prefer privacy controls to new hard limits on tasks.
- A JEV answer must never be able to grant permission: confidence can never allow paying, sending, deleting or signing in
  (`candidates.py` comment). Keep that invariant and add a test for the new options.

## 6. Verification plan

Offline (no spend):
- unit tests in `platform/tests/test_browse.py` / `test_browse_service.py` for: each new JEV option, strict validation of
  malformed answers, escalation to Sonnet, error/loop streak, `admit` refusal mid-run, JEV skipped on login pages,
  floor rules still winning over JEV, no change in `off` and `shadow` behaviour.
- browse runner fixtures: `browse/fixtures/site.mjs`, `browse/test/`.
- run the platform test suite and `lumina` tests before any release (the deploy script already does the Lumina part).

Paid benchmark (needs owner approval; estimated tens of dollars per `plans/product/browse.md`):
- identical pages and goals, three arms: Haiku-first (today), JEV then Haiku then Sonnet (this change), Claude-first.
- measure: task success, steps, JEV-acted share at >= 0.85, fallbacks, hand-off correctness (captcha / login / payment),
  false hand-offs, loop rate, Claude tokens and dollars per task, total latency.
- tune `automatic` (0.85) and the repeat/streak limits from the data.

Server facts still unknown (reads were blocked by the permission check on 2026-10-15):
- the real `--jev-mode` of the running browse service, the `jev_asked` / `jev_agree` totals in `browse_runs`,
  and whether `/var/lib/agentai-supervisor-secrets/_shared/typesafe-key` exists. The agreement rate is the best
  early signal for whether live mode would work.

## 7. Questions for the owner

1. Is "Claude" in "hand off to Claude" Haiku, Sonnet, or both in sequence? (Today: Haiku first, Sonnet capped at 2.)
2. How much page text should JEV see (3,000 or 6,000 chars)? Include history and URL?
3. Privacy: full pages to TypeSafe on every site, or exclude login / personal-data pages?
4. Should a password field or login form always hand off (fix the unused `sensitive` flag), independent of JEV?
5. Is a paid benchmark approved (budget), and which sites/goals should it use?
6. Rollout: shadow first for how long, then which accounts for live?

## 8. Out of scope

- The chat-level service choice (`routing/services.py`) and shadow request routing (`routing/*`, `route_decisions`).
- The old OpenClaw-era adapters (`browser-opt/`, `research-opt/`) and their Phase 12 switches. `browser-opt/route.py` has a
  similar design (JEV picks only code-built candidates, threshold 0.7, floor 0.5, 40-action cap) and can be read for ideas but
  is not on the platform path.
- Payment completion: the read-only policy stays; the user finishes payment.
