# Phase 7 — One Telegram ingress with secure account linking

**Stage:** Build. **Dependencies:** 6.

## Paste this prompt

Execute only Phase 7 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Add one customer-facing bot ingress that routes through the same task admission and Gateway adapter as dashboard chat.

1. Use a signed-in account to create a cryptographically random, short-lived, single-use link code, store its hash and bind it to account/purpose/expiry. Use Telegram start links within the provider's payload constraints. Verify numeric sender identity from authenticated Bot API updates, not usernames, claimed IDs or forwarded text.
2. Consume the code atomically; enforce a unique active account mapping per numeric identity, rate limits, attempt limits and clear conflict behavior. Treat the code as a bearer credential and minimize leak risk. Provide account-visible confirmation, unlink/revoke and explicit authenticated re-link; linking never grants platform operator or host-exec authority.
3. Pick webhook or polling from the real deployment constraints. Verify webhook secret/TLS if used; keep the bot token only at ingress. Deduplicate update IDs durably before routing, handle retries/out-of-order updates, bound attachments and provide an outbox with receipt reconciliation for replies. Gate real outbound replies on bot/use authorization.
4. Provide `/projects` and a scoped selection command or buttons with server-bound project IDs. Display active project/conversation and define whether switching starts or selects a conversation. Persist provenance so the dashboard shows the same messages and outputs. Serialise conflicting chat/Telegram requests as supported without bypassing budget admission.
5. Unlinked, suspended and deleted accounts cannot invoke any agent. Revocation takes effect on queued updates. Do not add customers to owner channel allowlists or embed credentials into deep links. Keep groups disabled unless explicitly included in the contract.
6. Prepare cases for expired/reused/swapped codes, simultaneous consumption, numeric identity spoofing, linking conflict, duplicate updates, project guessing, reply failure and unlinked denial. Retain owner/non-owner Telegram checks from the old suite as separate historical acceptance obligations.

Deliver ingress, linking/account UI, project selection, shared history routing and tests. Done when synthetic A/B updates route to their correct account/project exactly as defined, unlinked updates cannot start tasks, and code consumption is single-use. Real bot linking/reply and cross-surface history proof belong to Phase 15/17 with controlled users.

## Required close-out

Update `openclaw-project/plans/product/phase-07.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-07/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
