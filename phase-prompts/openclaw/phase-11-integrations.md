# Phase 11 — Scoped customer integrations and account setup

**Stage:** Build. **Dependencies:** 10.

## Paste this prompt

Execute only Phase 11 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Carry forward Gmail, Calendar, Drive and GitHub work as customer-owned connectors. Preserve the existing disabled connector base and live researcher-only Brave search.

1. Inventory connector versions, exact tool exposure and selected launch/release scope. For each service record account identity, exact scopes, allowed worker, read/draft/send/share/write/delete distinctions, token storage/refresh/revocation and billing. Decide required versus optional before testing; selected required authentication gaps remain blocked.
2. Build protected customer OAuth/credential flows with state/PKCE where supported, strict redirect validation and account-bound token storage. Provider credentials never enter browser responses, model text, memory or project execution. Prevent cross-account credential refresh/selection and redact errors.
3. Keep read-only by default: selected Gmail window, today's Calendar events in customer timezone, selected Drive item and chosen GitHub repo/issue/diff. Preserve local draft proposals. A Gmail compose scope may also allow send; scope names are not approval enforcement. Enable provider writes only with proven exact payload/target/expiry authorization and native enforcement; otherwise omit the write capability.
4. Give raw email/doc/event/repo content only to restricted readers; return attributed summaries/references. Retrieved text cannot create standing orders, access new credentials, mutate memory rules or install tools. Scope GitHub to selected repositories and disclose broad Drive read scopes honestly.
5. Handle refresh/expiry/revocation/429/outage with bounded retries. Reconcile uncertain writes through provider receipts before retry, fail closed on identity/budget/audit failure and revoke queued access when a connector is disconnected.
6. Preserve owner-deferred sign-ins: build UI/config/instructions and synthetic adapters without connecting new accounts. Track the Brave key exposure/rotation note in BUILD_LOG as a secret-custody obligation without reproducing the key. Do not rotate or read provider account content just to produce a demo without account authorization.
7. Preserve the legacy credentialed-browser requirement as selected launch or
later scope: account-scoped encrypted credential/profile custody, protected
login/auth callbacks, per-account persistent cookies/session profiles, revoke/
logout and browser isolation. Native secret mechanisms replace the retired
vault. No tool returns secret values to the model. Backups of browser profiles
are credential-bearing and encrypted; recovery requires separately held keys.
Prevent private-address/metadata/redirect SSRF and cross-tenant browser sessions;
recheck destination allowlists at redirects and isolate login content from
privileged policy. Missing approved login scopes/auth remain blocked, not fake
success. Prepare actual browser-session/revocation/SSRF and swapped-secret-canary
proofs without signing into new accounts during build.
8. Prepare actual identity/scope/read proofs, disabled/revoked denial, unauthorized target, injection, draft-only and replay/uncertain-write cases. Live account demonstrations occur only for selected connected services during authorized Phase 15/17.

Deliver connector permission matrix, account settings, protected linking/revoke, failure handling and fixtures. Done when independent build work is complete and selected credentials/scopes are safely account-bound. Report disconnected owner-deferred services separately; do not claim provider acceptance from mocked reads.

## Required close-out

Update `openclaw-project/plans/product/phase-11.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-11/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
