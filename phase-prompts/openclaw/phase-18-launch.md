# Phase 18 — Launch readiness, controlled paid signup and handoff

**Stage:** Launch. **Dependencies:** 17 PASS; launch approval for the concrete release.

## Paste this prompt

Execute only Phase 18 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Complete the launch checklist against the final tested release, then perform only the rollout already authorized or obtain the missing approval for a concrete prepared release.

1. Verify the coverage ledger: every launch-required feature implemented and accepted, all earlier unresolved gates dispositioned with evidence, selected optimization accepted or explicitly disabled, deferred services disclosed, and no unresolved critical security/isolation/budget or required recovery/payment blocker.
2. Check real beta identities/payments/task/artifact evidence, enforced plan limits, complete provider-route accounting, tenant restore without affecting another customer, off-host encryption/key custody, monitoring/alert ownership, capacity/load admission, support/incident readiness, secret rotation, dependency/release pins and rollback. Re-run only gates affected by release changes.
3. Finish customer-facing offer/limits/pricing/retention/support/refund/cancellation terms and required provider disclosures from Phase 1. Confirm marketing claims match measured scope; no universal autonomy, savings, uptime or deletion promises unsupported by evidence.
4. Prepare release hash/config/migration/backup/rollback, TLS/domain/ingress details, capacity-limited signup gate, payment live-mode plan, operator on-call ownership, smoke assertions and stop conditions. Keep Gateways private. Public DNS/publication/live charging is not authorized merely by creating these prompts.
5. If launch is authorized, roll out the exact reviewed release gradually, verify real signup→checkout→webhook→entitlement→provisioning→task→artifact→invoice/cancel, observe errors/cost/queue/capacity and use stop/rollback when thresholds trigger. If approval is missing, finish all independent work and present the concrete release package with the exact action pending.
6. Hand over release evidence, runbooks, alerts, recovery custody and support responsibilities. Preserve a future-work ledger with requirement IDs/dependencies for optional integrations, optimizations and later features; one canonical phase set remains. No new planned feature build after final acceptance without a new scoped release plan.

Deliver `product/LAUNCH_CHECKLIST.md`, reviewed release/rollback package, launch evidence when authorized, and a clear final report. Done when every required checklist item has actual final-revision evidence and the authorized rollout passes. A ready-to-launch package awaiting approval is READY/PENDING_APPROVAL, not a launched service.

## Required close-out

Update `openclaw-project/plans/product/phase-18.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-18/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
