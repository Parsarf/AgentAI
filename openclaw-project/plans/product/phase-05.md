# Phase 5 — offline usage admission/accounting continuation

Owner authorized continuing the phases; independent offline Phase5 work proceeded
while live Phase4 integration is incomplete. Outcome: local admission/accounting
component READY; full Phase5 PARTIAL; live provider/customer execution BLOCKED.
No Phase6 execution/activation. Scope: USAGE-01/02 and applicable plan/trial limits.

Built immutable reservation/receipt schema, atomic account-owned task creation and
budget hold, exact idempotency, task/period/rolling-day/service limits and queued
limit. Unknown service allocation/upper bound or ambiguous/expired entitlement
denies without a task or provider call. Reported spend consumes the hold without
double counting; unknown effects keep liability reserved. Receipts are append-only,
price/hash/time/identity-bound. Actual overruns are retained; late usage reopens
reconciliation and appends settlement/release corrections. Only trusted quiescence
and all-route proof release unused allocation. No user-facing trust-flag write API.

Added host-only seed_trial command (seven-day/$1, refuses existing entitlement
reset) and scoped /v1/costs + /account/usage/ read views. Estimates remain unknown;
no live provider accounting claimed. Expired accounts can read usage, not admit.

Checks:10 budget checks including racing final allowance, receipt replay/change,
late/uncertain usage, currency/price/service denial, cross-account boundaries,
queue/expiry and immutable/audit atomicity.2 final usage API checks;7 lifecycle API
checks and fresh private schema bootstrap/migration consistency.31 combined core
checks passed. Source/JSON/whitespace checks also performed. No paid calls.

Missing: real route prices/upper bounds, all-provider task attribution, virtual
key/provider backstops, per-call admission and stop fences, runtime/worker task
leases, step/output/time/search/model-count enforcement, running estimates and
restore/key/spend reconciliation. Billing remains Phase13. Owner keys/OAuth and
$2/day+$25/30-day caps unchanged. Service allocation unknown, default None denies.

Rollback: no production changes. Prior binaries reject the extended schema;
restore a compatible private snapshot into a fresh root and reconcile liabilities
before any authorized cutover. No spend/identity reset, live migrations, mail,
customer invite, payment, provider or native task occurred in this turn.

Evidence: `openclaw-project/evidence/product/phase-05/20260930T195312Z/manifest.json`.
