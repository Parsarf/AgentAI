# Customer chat: conversations, transcript and native delivery

Implemented in Phase 6: projects/conversations creation, the chat page, and the
server-side Gateway adapter contract with durable transcript and delivery
metadata. Native execution stays disabled until the host connects a probed
gateway and a measured provider route; every send is still admitted through
the Phase 5 fence and the global serial slot.

## Objects and ownership

- `projects` (Phase 2 schema) — create/list enabled: `POST /v1/projects` caps
  at `plan.json` `max_projects` (10) with 1–120-character names.
- `conversations` — account+project-scoped, bound to the account's active
  deployment. `POST /v1/conversations` caps at 10 per project (documented
  default). `native_session_ref` stays NULL until the trusted driver resolves
  it at first dispatch; the browser never supplies a session key.
- `chat_messages` — durable app transcript with provenance
  (`customer`/`agent`/`system`), bounded to 16,000 characters per message.
  Unique `(account, conversation, native_message_id)` makes native
  reconciliation idempotent; the customer row is linked to its native identity
  by update, not duplicated.
- `chat_deliveries` — one append-per-attempt record around each native send:
  attempt number, payload hash, `pending/acknowledged/uncertain/aborted/failed`,
  native operation/run ids and the acknowledged message sequence.

## Send flow

1. Validate message (1–16,000 characters, no NUL) and idempotency key.
2. Enqueue a durable request (`customer_requests.conversation_id`), reusing the
   serial queue's FIFO, cancellation and global-slot machinery.
3. Record the customer transcript row (idempotent on key reuse).
4. Admit via `BudgetLedger.admit` with a verified per-message upper bound from
   the configured route pricer. Same-key replays are admitted idempotently and
   never start a second task. With the production `UnmeasuredRoute` the send
   stays waiting unfunded (`execution_enabled:false`) exactly like the request
   page. A budget refusal (`queue_full`, allowance exhausted) cancels the
   waiting request and returns `402 budget_denied` with a category; nothing is
   charged and no native call is made.

## Native adapter contract (`agentai_platform/gateway.py`)

Recorded from the official session-control documentation for the chat
execution family (`chat.send`, `chat.history`, `chat.abort`), protocol
version 3. Reconfirm against the installed Gateway at activation:

- `chat.send` acknowledges admission separately from transcript persistence:
  `runStarted:true` does not prove a transcript row and `messageSeq` may be
  absent while input is in pending custody. Reconcile by submission identity,
  never by predicted positions.
- `chat.history` paginates with the opaque `deltaCursor`; `{kind:"delta"}`
  catch-up replays like live events, `{kind:"reset"}` requires a fresh tail
  fetch. `sessionInfo.hasActiveRun` is the activity fact used to detect
  quiescence.
- `chat.abort` takes the session key plus the scoped `runId`; abort stops
  generation without undoing external effects, so a customer-visible
  cancellation still requires the driver's terminal receipt and settlement.
- Compatibility negotiation (`negotiate`) fails closed on any other protocol
  version or an unprobed adapter. `HttpGateway` requires a host-resolved
  `GatewayBinding`; request data can never supply origin, token, RPC name or
  session key. `SyntheticGateway` is a deterministic fixture and is never
  installed in a worker entry point.

## Driver sequence (`ChatDriver`, trusted host path)

Preflight probes capabilities. After the serial claim it rechecks membership,
requires the active reservation and task state before any native effect,
records the delivery attempt, resolves or creates the native session, sends,
and records the acknowledgement. Transcript pages absorb by native message
identity. Cancellation intent aborts the scoped run (unsupported abort stays
recorded as intent and leaves the task uncertain rather than pretending).
Settlement (`effects_quiesced`, all routes reconciled) happens before the
global slot hands over. Unknown outcomes reconcile by receipts and never
resend; `reconcile` completes only from a terminal, cursor-free history read.

## Conversation resume

Refresh, process restart and gateway disconnect resume from durable
`chat_messages` with `GET /v1/conversations/{id}/messages?after=<cursor>`
(≤100 rows, ascending id). The native session remains authoritative for
execution; live event streaming (≤3 streams/account) remains Phase 9 scope.

## Honest state

`execution_enabled` is `false` in every customer response while native
execution is disconnected; the chat page says so verbatim. Pause is never
shown (no native pause contract yet). Cancel is offered only for
waiting/starting/running/uncertain tasks.

Checks: `PYTHONPATH=. python -m unittest tests.test_chat tests.test_gateway`
and the `accounts.test_chat` HTTP flow inside `manage.py test accounts`.
