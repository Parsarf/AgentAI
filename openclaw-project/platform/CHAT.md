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

OpenClaw owns the run. The contract below was checked against the installed runtime (2026.9.6, protocol 4), not against newer documentation; `docs/architecture/native-execution.md`
has the full table and the end-to-end evidence.

- `chat.send` is idempotent per `idempotencyKey`, and the key IS the run id. A repeat answers `in_flight` or `ok` and starts nothing. `queueMode: "steer"` injects the message into
  the active run; the steered input's own `agent.wait` reads `ok` with no reply, and its answer arrives in the active run's transcript under a run id the runtime makes up.
- `agent.wait` reports the end of one run (`ok` with `terminalReply` and the tools that ran, or `error`, `error: "aborted"` after `chat.abort`). `timeout`/`pending` mean "not over";
  an unknown run id reads the same, which is why a lost input is presented again by its key.
- `chat.history` rows carry the key of the input they follow (`after`), which is how a reply is tied to its request (never by position or run id alone).
- A goal is session state started with `chat.send` + `intent: session-goal-start` and controlled with `sessions.goal.update` / `clear` (operation ids make retries safe). The runtime
  does not start the next turn by itself.
- After a hard restart an accepted-but-unstarted input is `interrupted` in `pendingInputs`: inert, and refused under its old key. The same text under a new key runs once.
- `ask_user` fails in this deployment's connection model, so cells deny it (and the runtime's own `browser`); see `lifecycle/cell_config.py`.
- `negotiate` fails closed on any other protocol version or an unprobed adapter. The cell bridge multiplexes calls, so a long `agent.wait` never holds up Stop. A refused call
  comes back under `__error__`; payload fields such as a run's own `error` are results, not refusals.

## Driver sequence (`ChatDriver` in `chat_driver.py`, trusted host path)

Preflight probes capabilities. After the claim it rechecks membership, requires the active reservation and task state, and resolves who owns the session's run (a run nobody owns is
stopped; one a live request owns defers this request). It records a delivery (`chat_deliveries`: one row per input, with its kind, key and deadline) and hands the message over. It then
asks the runtime when the run ended in short slices, looking after Stop, the lease, the spending limit, the per-run time limit and people the run waits for. A run waiting on a person
parks the request (it gives up `request_slot`, not its cell or reservation). A cell that goes away for a moment is waited for, then every live input is presented again by its key.
When no run is owed (`close_gate`, which also refuses late steers) the driver mirrors the replies of its runs, saves files and cards, judges the outcome (`outcome.py`) and settles
the spend before the slot hands over. `reconcile` after a crash is a recovery, not a guess: supervision carries on from the stored deliveries.

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

## The assistant reads every message first (native tools)

Nothing guesses what a message means. `ChatService.send` makes a message plain chat unless the customer picked Plan or Browse mode. The assistant gets the message (plus a short
context block with what the customer asked Lumina to remember: names only, never a secret) and decides for itself, with the runtime's own tools: web search and fetch, files,
commands, and `lumina_browser`. There is no step block, no JEV tool choice and no follow-up message carrying a tool result; the runtime does tool-result continuation.

## The browser as a native tool

`lumina_browser` is served to a cell over MCP by `tool_relay.py` (app user, bound to the cells' bridge address, one firewall port). The cell proves who it is with its own model key,
checked by the root bridge (`cell.identify`). A call is only served inside the calling account's running, funded request (`browse/adapter.py`), spends only the browsing share
(60%) of that request's reservation, is stopped when the request is stopped or the caller goes away, and returns Lumina's own wording of how the job ended. Several calls in one
run are several jobs of the same request (`browse_sessions`). The browse service, its code rules (no payment, no password typing, human-check hand-off), the saved-login consent
and the Live view stay in Lumina's hands. Who decides each browser step is JEV first and then the assistant itself: when JEV cannot take a step (it calls the page too complex, misses twice,
the run loops, or a choice is open) the job hands the page to the assistant, which answers with the second tool, `lumina_browser_step` (see `docs/architecture/native-execution.md`). There are no
Haiku or Sonnet tiers any more. With the cell's native browser enabled (`browse-engine.json`) the hands are the cell's own browser; otherwise the host's Docker stage.

## Steering, Stop, goals and outcomes

- **Steer.** A plain message sent while a task of the conversation runs joins that run (`ChatService.steer`): same request, same reservation, a `steer` delivery the worker waits for.
- **Stop.** Aborts every run of the session, waits for the runtime to confirm, pauses the goal so nothing resumes it, and closes the request as cancelled.
- **Keep working until complete.** The message becomes a native goal. `goals.GoalChain` admits each next turn as its own request while the goal is `active`, within the allowance,
  the account's membership and `GOAL_CHAIN_LIMIT`. Paused, blocked, budget-limited and complete goals are never continued. Resume and Clear are `POST /v1/conversations/{id}/goal`.
- **Outcomes.** `customer_requests.state` says the run is over. `outcome` (completed, partial, blocked, failed, cancelled), `outcome_note` and `verification` (verified,
  unverified, not_applicable) say what that means, from evidence Lumina holds itself (`outcome.py`): the browser's end state and steps, saved files, the goal state. The assistant's
  own words are never evidence.

## Registry-driven answers

Composed answers use one versioned `lumina-doc` document protocol. The generated registry covers content, cards, tables, charts, inputs, navigation, media, location, execution monitoring, decisions, scheduling and specialized results. Detailed schemas/examples and a local validator are deployed to `lumina-ui/` inside the cell workspace; the compact capability index is supplied only when the chosen answer style permits structured UI.

Server extraction validates documents and stores them as anchored `document` blocks. User events carry artifact/node/action identities, document version, submitted values and an idempotency key; the server resolves the stored binding, validates values, and resumes the correct conversation through normal budget admission. Continuations can update the same artifact by version while preserving compatible input and local state. Approval/retry controls use the actual native phase/request authority.

The former `lumina` card producer, renderer and automatic remote picture fetching have been retired. Historical cards migrate through the registry renderer or remain readable text/code. Stored conversations, artifacts and account-owned pictures are preserved. New media references resolve only authorized project files, using scanned uploads and generated-artifact tickets.

JEV remains an optional advisory fallback for structured prose; its hints can affect presentation but never provide facts, execute actions or grant approval. Partial-document parsing mounts complete validated blocks. Live token streaming requires drafts/deltas from the upstream gateway; the application does not simulate them.

See `docs/generative-ui/protocol.md`, `component-catalog.md`, `selection-policy.md`, `security.md`, and `testing.md` for the current contracts and verification workflow.
