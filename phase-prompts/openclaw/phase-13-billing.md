# Phase 13 — Hosted billing, invoices and access reconciliation

**Stage:** Build. **Dependencies:** 5; consumes the product built in 6–11.

## Paste this prompt

Execute only Phase 13 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Connect commercial access to the same entitlements and usage ledger that admit customer tasks.

1. Verify selected billing provider APIs/webhook signature/hosted checkout/customer portal and pinned SDK against official documentation. Build in test mode. Keep keys server-side and card details with the hosted provider. Separate platform subscription payments from agent purchasing authority.
2. Map application accounts to provider customer/subscription IDs and versioned plan/prices. Derive checkout account/price/quantity server-side; a client cannot assign another customer or arbitrary entitlement. Use durable idempotency keys and receipt reconciliation for provider mutations.
3. Verify webhook signatures over the raw body, enforce size/rate limits and persist an inbox before acknowledgment. Deduplicate provider event IDs, handle retries/out-of-order deliveries and fetch current canonical provider state where needed. Apply inbox processing, entitlement updates and audit consistently; dead-letter and reconciliation jobs are observable.
4. Implement active/trial/past-due/grace/cancel-at-period-end/expired/refunded/disputed states according to Phase 1's policy. Define precisely when new tasks stop, what happens to reserved/running tasks and when reactivation occurs. Browser redirects never grant paid access. Handle plan changes/proration, renewal, failed payment, duplicate checkout and cancellation races.
5. Show subscription, included limits, estimated versus reconciled task usage, invoice links, cancellation and payment recovery. Use the Phase 5 ledger for displayed/enforced usage; reconcile provider invoices/credits and retain required billing records separately from deleted agent data.
6. Prepare test-provider scenarios: successful checkout/renewal, duplicate/reordered/invalid webhook, lost acknowledgment, payment failure/recovery, upgrade/downgrade, cancellation, refund, task admission race and outage. No live payment/paid signup activation is authorized by this prompt rewrite; live proof belongs to explicit beta/launch execution.

Deliver test-mode hosted checkout/portal, webhook inbox/worker/reconciliation, entitlement transitions, invoices and billing UI. Done when replaying provider test events produces the correct access state once and no task starts without the required entitlement/reservation.

## Required close-out

Update `openclaw-project/plans/product/phase-13.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-13/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
