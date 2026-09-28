# Phase 9 build — summary (run 20260927T215500Z)

## Outcome

Build status **READY**; optimization acceptance **DEFERRED to Phase 11**.
The optional browser-optimization adapter is implemented, pinned, tested
offline, and **disabled at three layers**: config kill switch, runner flag,
and the fact that no transport or account exists to call the provider. The
existing browser route is untouched.

## What was built (`browser-opt/`)

- **Adapter** (`jev_adapter.py`): deterministic snapshot→candidate building
  (typed actions only), one Jev Choice over candidate ids plus
  escalate/stop/no_valid_action + one Noul, **fail-closed validation**
  (pinned `jev-1.13.0`, candidate membership, finite unit-sum probabilities,
  argmax consistency, Choice-only confidence), local-estimate action budget,
  5 s deadline with one bounded transient retry, explicit fallback flags on
  every non-execute outcome. Jev's entire possible authority is choosing
  among code-created candidates — no selectors, shell, JS or tool calls can
  be produced; owner approvals and native policy are unchanged.
- **Pinned config** (`config.json`): `enabled: false` (master kill switch),
  model/version pin with response-mismatch rejection, endpoint and price
  notes verified against docs.typesafe.ai (2026-09-27), provisional
  thresholds (0.5 floor / 0.7 act), per-task caps.
- **Offline tests**: 19/19 green — malformed/unknown/forged output,
  non-finite and non-summing probabilities, model-pin mismatch, argmax
  mismatch, missing confidence, low-confidence escalation, budget stop,
  429 no-retry fallback, transient-then-success retry, persistent-outage
  fallback, disabled-route refusal that never touches the network. (One
  test-assertion bug was found and fixed; the adapter was correct.)
- **Fixtures**: 10 development + 10 frozen held-out synthetic scenarios
  (navigation, search, filters, pagination, forms, duplicate labels,
  disabled controls, delayed render, stale targets, empty/error states,
  missing accessibility data).
- **Runner** (`compare_runner.py`): paired-route scaffold with usage/trace
  records; refuses optimized runs unless BOTH the config switch and
  `--enable-optimized` are on (verified: exit 3 both ways), and refuses the
  30-scenario benchmark entirely (Phase 11).

## Explicitly not done (recorded, not hidden)

- No provider call, calibration, benchmark or rollout (Phase 11, needs
  owner authorization).
- No TypeSafe account/credential exists — separate owner decision with its
  own billing and data-handling terms; proxy/ChatGPT caps do not cover it.
- Transport from the sandboxed worker path to the adapter is an open gap
  (`plans/remaining-build-items.md` #9) requiring its own isolation review.
- Jaggedness/confidence-routing doc pages still to read before calibration.

## Rollback

Delete `browser-opt/`. The runtime never loaded it; the VPS was not
modified in this phase.
