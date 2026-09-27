# Phase 6 — Scoped personal integrations with verified authorization

Connect the owner's approved accounts so the agent can perform useful reads
and prepare drafts while preserving control over external changes. Prove
account identity, permission boundaries, failure behavior and hostile-content
handling for each integration. Purchases, payments and AgentAI billing remain
outside this phase.

Read [the execution contract](execution-contract.md), accepted Gate 5 evidence
and the current trust/memory/scheduling policy. Check current OpenClaw and
provider documentation for every chosen connector, OAuth scope, tool and
approval path. Prefer native support, then an inspected plugin/MCP connector
only for a documented gap. Useful entry points are
[MCP connections](https://docs.openclaw.ai/tools/mcp),
[secrets](https://docs.openclaw.ai/gateway/secrets) and
[tool policy](https://docs.openclaw.ai/tools).

## Required result and scope

The candidate integrations are Gmail, Calendar, Drive and GitHub. Inventory
existing authorized accounts and the owner's requested operations first.
Reuse explicit session authorization; do not connect a new account merely
because it is listed here. If a choice is missing, ask for the account and
capabilities needed, then continue independent connector design/tests.

Define the required integration set before implementation. Deliberately
excluded optional services are reported as excluded; an approved required
service with missing auth or support is BLOCKED. Avoid claiming completion by
silently shrinking scope after a failed connection.

## 1. Produce an integration permission matrix

For each approved account, record the connector/version, identity, owner,
requested operations, exact minimum credential scopes, allowed worker, tool
policy, action authorization, credential storage, expiry/refresh and revocation
path. Distinguish read/search, draft/create, send/share, modify/delete,
commit/branch and push/merge. Explain any scope that also grants unused powers.

Separate read-only credentials from write credentials where practical. Keep
provider credentials behind the supported secret/auth boundary, not in model
context, memory or repo files. A SecretRef name may be recorded; its resolved
value must not be logged. Scope GitHub access to selected repositories rather
than an entire account when supported.

Specify how every restricted operation is actually prevented without current
owner authorization. Exec approvals do not automatically govern arbitrary
connector/API writes; OAuth scope is not an approval system. If the installed
native path cannot enforce the required rule, omit the write tool/credential
authority and report the gap. Do not implement a second approval engine.

## 2. Connect and verify one account at a time

Use the supported protected login/OAuth flow. Validate account identity through
an authenticated provider response and show the owner a sanitized identity
summary. Do not trust a display name, prompt text or connector label as proof.
Verify token refresh and the effective scopes/tool set before proceeding to
the next integration. No live credential may be copied to an untrusted worker.

Route raw email, documents, event text, issues and repo content through the
restricted workers established in Phase 3. The orchestrator receives relevant,
attributed summaries and links. Readers cannot gain messaging, scheduling,
spawning, policy or credential authority from content they retrieve. Drafts
are proposals; reminders inferred from an email are not new standing orders.

## 3. Demonstrate useful behavior

Use bounded reads and the owner's verified timezone. For services in scope:

| Integration | Minimal live demonstration |
|---|---|
| Calendar | Summarize today's events with correct local times, including an empty-day case |
| Gmail | Summarize a small explicitly selected inbox window; prepare one test draft and verify provider state is still draft |
| Drive | Find/read one owner-selected non-sensitive item and cite its stable item reference |
| GitHub | Inspect one selected repo/issue/diff and return findings without changing branches or pushing |

Keep personal message/document bodies out of retained public evidence. Record
redacted identifiers, counts and assertions. Do not send mail, invite another
person, delete owner data, create a public share link or push a real branch to
satisfy a test. Use controlled test accounts/provider sandboxes for writes
where available. Record mock adapter tests separately from live provider proof.

For an approved action, bind authorization to the exact account, operation,
recipient/target, payload/version and expiry. A changed draft or target requires
a fresh decision. After any external write, obtain provider readback/receipt.
After timeout or uncertain success, reconcile before retrying. Replayed or
expired authorization cannot cause another effect.

## 4. Probe boundaries and failure handling

Test the effective path rather than asking a model whether it would comply:

- An unauthorized identity cannot access the account or another agent's data.
- A send/delete/push request without approval is blocked before the provider
  effect; denial and expiry leave provider state unchanged.
- A controlled email, document or repo fixture asks for credential exfiltration,
  policy changes and outbound messages. Tool/audit evidence shows no such
  effect and no promotion to an instruction or schedule.
- An expired or revoked test credential produces a clear reconnect-required
  result, without secret leakage or fallback to a broader account.
- Rate limit/provider outage uses bounded retry and truthful incomplete status;
  uncertain writes are reconciled rather than blindly repeated.

Use separate disposable credentials for revocation tests; do not revoke the
owner's only working credential or log out production solely for a probe.
If a provider lacks a safe live negative-test surface, combine enforced tool
denial with bounded adapter tests and explicitly record what remains unproven.
It does not count as proof that an untested connector action is protected.

## Artifacts and Gate 6

Produce `plans/phase-6.md`, the permission matrix, connector/config diff,
sanitized live-read/draft readbacks, injection/denial/auth-failure evidence and
execution-contract manifest. Add exact reconnect/revoke/scope-reduction steps
to the runbook. Run config validation, connector health, doctor and
secrets/security audits after each connection. Cleanup test drafts/fixtures
only through authorized safe procedures; record retained test items.

PASS requires all approved required reads to work on the verified accounts,
drafts to remain unsent, every enabled restricted action to have an enforced
and tested authorization path, hostile content to have no privileged effect,
and auth failures to fail safely. An unsafe connector stays disabled. Report
working operations, limitations, costs and precise blockers, then stop after
Phase 6.
