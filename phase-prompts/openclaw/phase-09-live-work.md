# Phase 9 — Durable live work timeline and task controls

**Stage:** Build. **Dependencies:** 8.

## Paste this prompt

Execute only Phase 9 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Upgrade the current audit-based viewer into a scoped durable product timeline.

1. Verify installed session events/bootstrap/subscriptions and correlate account/project/task/run/worker IDs. Prefer scoped session events; any audit fallback must filter safely server-side before persistence/delivery and state what it cannot observe. Do not expose the global audit stream to customer clients.
2. Persist normalized events with stable IDs, timestamps, sequence/cursor, source and redacted typed payloads. Include public plan/progress summary, search queries/sources, files changed, command/test results, approval requests/decisions, errors, budget state and final result/artifact links. Do not emit private model reasoning, prompts, credentials, unrelated transcripts or raw sensitive tool output.
3. Stream with authenticated SSE/WebSocket, bounded buffers/backpressure, heartbeat, cursor replay, deduplication and reconnect. Define replay retention and cursor-expired resync. Recheck access on connection and during revocation; a stale stream must not keep receiving events.
4. Add filters, session/worker tree, now-running indicator, clear timestamps and short useful progress explanations. Missing data is unknown; a command start is not a passing test. Timeline viewing pause stops display only; execution pause requires a verified native mechanism. Label them separately and use native abort/cancel/pause only where verified.
5. Bridge native approvals only if exact customer scope/payload/expiry can be enforced. Changed, replayed, expired or cross-tenant decisions execute nothing. Otherwise provide the supported surface and show the required feature gap. Never broaden an owner credential to approximate delegated approval.
6. Prepare cases for disconnect/reconnect during events, server restart, duplicate/gap/out-of-order events, expired cursors, cancellation races, cross-account subscriptions, revocation, redaction and audit-write failure. Preserve existing T10-DASH2 cases and verify final-revision applicability.

Deliver event storage/adapter, scoped transport, timeline/control UI and replay fixtures. Done when a synthetic running task's timeline survives departure/return/app restart without lost durable events or repeated execution, and unauthorized subscribers receive no customer data.

## Required close-out

Update `openclaw-project/plans/product/phase-09.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-09/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
