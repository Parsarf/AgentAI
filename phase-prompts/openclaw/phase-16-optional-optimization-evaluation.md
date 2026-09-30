# Phase 16 — Optional paired optimization evaluation and rollout

**Stage:** Optional evaluation. **Dependencies:** 15 baseline PASS; selected 12 track; explicit paid-test resumption.

## Paste this prompt

Execute only Phase 16 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Measure each selected optional optimization independently; a disabled build is not proof of reliability or savings.

1. Freeze model/adapter/browser versions, success rubric, thresholds, budgets and paired scenarios before execution. Calibrate only on separate development fixtures; confidence is not guaranteed accuracy or an authorization boundary.
2. Preserve the existing browser gate: at least 30 held-out scenarios × 3 paired repetitions × 2 routes = 180 task runs, plus separately budgeted calibration/adversarial/canary checks. Reset starting state, alternate route order and use actual native browser execution. Repetitions on one scenario are not independent new scenarios.
3. Report complete-task successes/failures, wrong/duplicate actions, fallback reasons, confidence errors, total billable cost including planner/retries/output/failures/fallback, cost per successful task, p50/p95 whole-task latency, cancellation and denied effects. Separate provider receipts from estimates and include failed-run costs.
4. Keep frozen browser targets: hybrid success at least 95% (at least 86 of 90 hybrid runs), no more failures than baseline, each required scenario passing at least once, zero forbidden effects/duplicate submissions, all failure cases correct, cost per success at least 50% lower and p95 latency at most 20% worse. Changes require an owner-approved reason before results, never afterward.
5. For selected research middleware, separately verify actual registration/interception/decision logs, source support/citation retention, injected-content no effects and lossless baseline bypass. Freeze an independently justified paired sample and quality/savings thresholds before running. Do not apply browser success figures to research accuracy or invent a previously measured research benchmark.
6. Test forged/malformed/stale/confidently wrong responses, outage/fallback outage, budget-store failure, cancel and uncertain-effect reconciliation. Prove kill switch mid-task stops new optimization admission without duplicate effects, then canary only proven task categories. Prepare a concrete activation diff; use existing authorization or obtain the exact missing activation authorization.

Deliver frozen per-track results, confidence/error/cost/latency analysis, activation decision, canary/rollback proof and final-revision regressions. Done when all selected frozen criteria pass and authorized rollout is observed. Insufficient budget is BLOCKED; optional failure retains baseline and FAIL status without blocking a baseline product launch. Do not silently reduce the 180-run browser gate.

## Required close-out

Update `openclaw-project/plans/product/phase-16.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-16/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
