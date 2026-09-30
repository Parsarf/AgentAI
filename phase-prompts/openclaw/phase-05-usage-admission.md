# Phase 5 — Usage ledger, entitlements and task budget admission

**Stage:** Build. **Dependencies:** 4.

## Paste this prompt

Execute only Phase 5 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Build enforceable usage before enabling chat or any customer model execution. Reuse the working proxy caps as a backstop; they currently do not establish complete per-task accounting.

Apply the existing-VPS trial profile: one atomic global execution lease, one
running task/account and three queued tasks/account. Hold resource reservations
through starting/uncertain/maintenance states. Queue expiry/cancellation must
release only reconciled unused liabilities. Separate account onboarding from
execution admission; keep every feature in scope without requiring an upgrade.

1. Inventory every billable route: orchestrator/workers, retries/fallbacks, Codex/native harness, ACP reviewers, search, embeddings if selected, and optional TypeSafe. Record actual usage support, price versions, currency, cached/uncached input, output and non-token fees. Subscription quotas are distinct from metered costs. Missing attribution or enforcement blocks that paid route for customers.
2. Create an append-only idempotent usage ledger keyed by account/project/task/run/provider/request. Record reserved, estimated, reported, reconciled and adjusted values separately. Preserve source receipts and distinguish service cost from customer price/credits; never translate missing cost into zero.
3. Implement atomic budget admission/reservations covering task/plan/daily/monthly/service limits, inflight calls, concurrent tasks and retry/fallback/verification reserves. Commit authorization, reservation and task creation consistently. Release only demonstrably unused reservations; retain uncertain charges for reconciliation. Reject duplicate admission with the same operation ID.
4. Use the execution-contract formulas and Phase 1 worksheet to compute each task allocation. Require a verified upper bound before calls and bounded output/time/actions. Stop additional admission before exhaustion, cancel work where natively supported, retain partial outputs, reconcile late usage and explain the stop. Unknown price/usage or unavailable budget store fails closed. Do not reset lifetime/rolling spend by restoring a backup or changing a key.
5. Seed versioned plan entitlements for private test accounts and enforce them in APIs/control services. Billing later changes access through the same entitlement model. Keep the owner's existing $2/24h and $25/30d limits unless explicitly changed; customer limits require a separate approved product allocation.
6. Show current reservation/estimated spend separately from reconciled usage. Test simultaneous final-budget admissions, daily/monthly denials, store outage, late/duplicate receipts, refunds/adjustments, cancellation, fallback accounting and incompatible price currency using deterministic fixtures.

Deliver ledger/schema, reservation/reconciliation service, route matrix, entitlements, usage UI and budget denial cases. Done when concurrent synthetic tasks cannot spend the same remaining allocation twice, denial creates no model call, and the displayed accounting matches the enforcement ledger. Live paid proof waits for authorized Phase 15 execution.

## Required close-out

Update `openclaw-project/plans/product/phase-05.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-05/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
