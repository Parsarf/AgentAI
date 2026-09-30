# Phase 6 — Projects, conversations and dashboard chat

**Stage:** Build. **Dependencies:** 5.

## Paste this prompt

Execute only Phase 6 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Turn the observability dashboard into the customer work surface through a server-side Gateway adapter.

1. Verify installed support for send, streaming/events, history and abort; record exact protocol/auth scopes/request/response shapes. Start with the official session-control reference and installed source/help. The existing gateway-http viewer is unverified; its implementation is not proof of a working API. Add compatibility negotiation and fail safely on unsupported versions.
2. Implement project and conversation creation, stable app→tenant/native-session mapping, send/history/pagination, stream reconnect and supported task cancellation. Admit every send via Phase 5 and enforce ownership before resolving a native key. Never expose arbitrary RPC names or accept a browser-chosen Gateway URL/token/session key.
3. Define a task per actionable request and message provenance for dashboard/Telegram/system responses. Persist delivery/idempotency state around native requests. On timeout, reconcile native run/receipt before retry. A deliberate retry starts a recorded new attempt; refresh/reconnect must not rerun work.
4. Implement the full chat page: project selector, draft/send, transcript, task state, error/retry, budget denial and cancellation availability. Show unsupported controls honestly. Native abort may stop generation without undoing effects; document its exact semantics. If required abort is unsupported, record the launch requirement gap and concrete supported resolution; do not invent it.
5. Resume the same conversation after page refresh, app restart and Gateway disconnect. Decide transcript authority and cache behavior; keep native state authoritative for execution while durable app metadata maps access. Reconcile history/events without duplicate messages.
6. Prepare adapter fixtures and a complete browser flow for send→stream→refresh→history→retry/cancel and cross-account denial. Use synthetic transport locally; any live paid chat proof requires existing authorization and budget.

Deliver native version contract, scoped client, projects/conversations/tasks APIs and working customer chat UI. Done when the local contract flow preserves a conversation across refresh and prevents duplicate sends; live installed-Gateway completion is explicitly verified later rather than inferred from mocks.

## Required close-out

Update `openclaw-project/plans/product/phase-06.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-06/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
