# Browser checkout approval, and the browser-reliability items around it (plan, 2026-11-01)

Status: PLAN. Nothing in sections 2 to 4 is built. Section 1 (Claude takeover) is built and is described in the PR that carries this file.

## 0. Decisions already taken (owner, 2026-11-01)

1. The agent places the order itself after approval when the order total is **$50 or less**. Above $50 (or when the total cannot be read, or is not in USD) it stops right before the order click, as today.
2. Card security code: **both ways**. (a) A masked box in the approval card, typed straight into the page and wiped; (b) typed by the customer in the browser, and the agent must notice that it was entered and carry on by itself.
3. Approval style: **both**. A card at each checkout, and a pre-approval in the task plan with a cap. Both have an "ask me again later" button.

Open interpretation, to confirm: "ask me again later" = pause the run with the cart kept, and ask again when the customer returns. Purchases only may be pre-approved; delete, send and sign-out clicks always get the per-click card.

## 1. Claude takeover (BUILT, branch `claude-takeover`)

What exists: the assistant (Haiku/Sonnet) already receives the picture of the window on every step it takes (tests/test_browse_sight.py).

What changed:
* A JEV step that cannot be completed hands just that step to the assistant at once, instead of a wasted "look again" step: JEV's service not answering (HTTP error such as the 503 "Image processing is unavailable", or a timeout) and "found something but not where" (no spot). JEV is asked again on the next step. An unusable answer (garbage, a target that does not fit) is still tried once more, and a second miss in a row still hands the task over for good.
* The assistant is told why (`Handover.hint`), so it does not just repeat JEV's attempt.
* `modes.NOTHING_AFTER` 3 to 2: two JEV steps in a row that changed nothing or failed hand the page to the assistant (it was three).
* Picture-only test mode is unchanged: nobody else takes a step there.
Not done on purpose: handing over when a popup covers many controls. JEV already switches to the picture in that case, and sending those steps to the assistant would cost more without evidence it helps. Revisit with run data.

## 2. Checkout approval (design)

Today (loop.py): a payment page offers the saved card, fills number/name/expiry, then ENDS the run ("you take it from here"). A sensitive click (pay, buy, delete, send, confirm, sign out) also ends the run with `pending_action`. The service already supports a mid-run question (state `asking`; options or a `fields` form with prefill) and saved choices (`prefs`).

New flow, behind a new owner-only, timed Safety switch `checkout_approval` (default OFF = today's behaviour):
1. Detect the checkout page or sensitive click exactly as now, before any click.
2. Approval card (new question kind): the real control, the site, the order total read by CODE from the final review page (tax and shipping included, never the cart subtotal, never the model's reading; several different totals = stop), and which saved details will be used (card ending 1234, home address). Buttons: Approve, I will do it, Ask me again later, Cancel.
3. Known values (saved card, address, contact) are typed in automatically. Unknown values come as one form card with only the missing fields and a "Remember for next time" switch.
4. Order click: only when the total is $50 or less (limit adjustable in Settings), USD, readable. The approval is bound to the control, the page fingerprint and the total; any change re-asks. After the click it is never retried; an unclear result stops the run and tells the customer to check their email or orders.
5. Pre-approval: a checkbox in the plan card, "Allow checkout up to $X" (never above the limit), for that task and one order only. It must come from the customer's own click in the app, never from chat text or page content.

Security code:
* (a) Card box: typed straight into the page, then wiped. Never stored, logged, traced or shown to a model. Limit: many sites put the field in a payment iframe the runner cannot reach (the card fill already hits this); then the card falls back to (b).
* (b) Typed in the browser: the runner checks only whether the field is filled with 3 to 4 characters, never its value; where the iframe is unreadable it watches for "Place order" becoming enabled; there is an "I have entered it" button as the last resort. No pictures go to any model or to storage while the customer types.

Storage and privacy: saved addresses and contact details go in the encrypted vault (not the plain saved choices). The Safety help text for `payment_stop` and `sensitive_approval`, `platform/privacy/facts.json`, the policy page and `OPERATIONS.md` change together (the privacy test fails on purpose until they do). The promise "nothing is bought unless you do it yourself" is replaced by "nothing is bought without your approval, and never above your limit".

Build order: (1) approval card, known values, unknown-values form, remember into the vault, order click still the customer's; (2) auto-place at or under the limit with total parsing, binding and the duplicate guard; (3) security code, both ways; (4) pre-approval in the plan and "ask again later".

Tests: unit tests with a fake ask gate (approve continues, decline falls back to hand-over, changed total re-asks, security code never in traces, steps, events, prompts or logs), UI tests, an end-to-end run on the local test shop and a payment provider's test mode with a test card. No real money in any test.

## 3. Other items, in order

1. Finish the paused deploy; make the deploy guard accept any committed version of a hand-released file (record the hashes of each file's history in the manifest), so "overwrite manual changes" is no longer needed.
2. JEV 503 fallback: retry once, then ask without the picture (controls and text only) instead of handing over. Add a size check before sending a picture and report the real captured size from the extension (it reports a fixed 1280 by 800 today).
3. Laptop extension stalls: `scroll`, `type` and `open` time out at 30 s on the local engine (device_transport). Find out whether it is Chrome throttling a background tab or the service worker sleeping.
4. Rename the Safety switch label "Use the standard Lumina browser" to "Use the standard decider" (it chooses the decider, not the browser).
5. Picture-only comparison runs (standard and ultrafast, picture-only and not) once TypeSafe's image service answers again.
6. Housekeeping from the handoff: the privacy server check after the 03:40 UTC backup, then remove `server.known_gap` from `platform/privacy/facts.json` (deadline 2026-11-11); budget correctness G11:P1-1 / M-01.
7. Later: a Claude computer-use decider (screenshot in, click out, same sandboxed stage); the UI redesign brief and guardrails (DESIGN.md is tied to one reference image).
