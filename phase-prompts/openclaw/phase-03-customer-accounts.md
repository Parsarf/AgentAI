# Phase 3 — Customer accounts, recovery, roles and audit

**Stage:** Build. **Dependencies:** 2.

## Paste this prompt

Execute only Phase 3 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Replace the single-owner dashboard login assumption with an account layer suited to the agreed product.

1. Use a maintained identity/session component. Implement sign-in, verified account onboarding, recovery, logout, session rotation/expiry/revocation and abuse limits. Define customer, account administrator if required, internal operator and service identities; internal operator access must be explicit, limited and audited. Use secure/httpOnly/sameSite cookies, CSRF/origin checks and internal operator MFA.
2. Store customer/account records and internal account→deployment assignments. Resolve the effective account and allowed object server-side on every request. Reject client-provided tenant/session routing overrides. Membership changes and account suspension revoke relevant sessions and stream access.
3. Apply authorization to API routes, streams, exports, memory, schedules, integrations, cost records, task controls and artifacts. Constrain account/project/task foreign-key relationships. Recovery tokens must be hashed, short-lived, single-use, purpose-bound and safely consumed under concurrency; avoid account enumeration.
4. Persist append-only application audit events with actor/account/object/action/time/request/native operation/result and retention controls. Record pending/completed/failed/uncertain mutations; audit-store failure denies audit-required mutations. Do not claim host administrators cannot tamper with storage.
5. Implement account pages and truthful onboarding states. Gateway/provider/Telegram/SSH credentials remain server-side. Scope any support impersonation or export privilege and require a visible audit trail.
6. Add targeted direct-API fixtures using two synthetic accounts and enabled roles; bypass the UI to exercise cross-account IDs, stream subscriptions, role changes, revocation, recovery replay, CSRF, rate limits, unsafe rendering and audit failure. Run inexpensive local boundary checks now; carry real provider/complete browser scenarios into Phase 15.

Deliver identity integration, account/role/audit migrations, ownership middleware and endpoint assertions. Done when two authenticated synthetic accounts can access their own records and direct requests for each other's records fail without side effects. A page hiding another account's data is insufficient.

## Required close-out

Update `openclaw-project/plans/product/phase-03.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-03/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
