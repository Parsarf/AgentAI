# Connected services: the contract, and how to add to it

Roadmap Phase 3 (#22 to #29, #83) with the permission pieces of Phase 2 that belong to it (#13, #16, #17). Everything Lumina reads from, or changes in, an outside
system goes through this. Nothing later gets its own permission check, approval, retry or undo.

**Where things are**

| File (`platform/agentai_platform/`) | What it is |
|---|---|
| `connector_kit.py` | The contract: `Declaration`, `WriteKind`, the six error kinds, `paginate`, freshness, and `ConnectorClient` (the one client every outside call goes through). `McpAdapter` wraps a remote MCP server |
| `connectors.py` | Connections, resource grants (`connector_grants`), revocation with a receipt, operation receipts |
| `connector_custody.py` | Sealed custody for tokens (the key is in a root-only file, `AGENTAI_CONNECTOR_KEY_FILE`) |
| `connector_refresh.py` | The refresh job (`manage.py connector_refresh`, timer `agentai-connector-refresh`) |
| `actions.py` | The action record: preview, approval bound to the payload hash, at-most-once execution, verification, undo, compensation |
| `workflows.py` | Several actions approved together, run in order, walked back on failure |
| `handoff.py`, `action_runner.py` | Waiting for a person without holding anything, and resuming the chat that waited |
| `connector_tools.py` | The assistant's six tools (one per kind of operation, not one per provider endpoint) |
| `synthetic_connector.py` | The worked example below: a fake provider with everything a real one has |

## The contract in one page

A connector is a **declaration** (data) plus an **adapter** (code).

The declaration says: provider and label; how it authenticates and with which scopes; the **resource kinds** a grant can name (calendar, folder, label, repository,
project); the read operations it has (`list`, `read`, `search`); its **write kinds**; whether records carry a version token and whether a write can carry one as a
precondition; whether writes take an idempotency key; its paging style; its error map; how fresh each resource kind should be; its caps (pages, items, bytes, seconds);
and **how it is implemented and why** (`first_party`, or `mcp` when the provider's official remote MCP server is generally available and gives what the contract needs).

Every provider error becomes exactly one of six kinds, and nothing else reaches a caller:

| Kind | Means | What happens |
|---|---|---|
| `retry_later` | busy or rate limited (with a time when the provider gave one) | waited for once, briefly, together with other calls of the account; a change goes back to "approved" and is sent again then |
| `needs_customer` | reconnect, re-consent, a missing scope | the connection is marked "needs you", the customer is told once |
| `refused` | permission or policy (the provider's, the customer's choices, their organization's) | nothing is changed |
| `not_found` | it does not exist, or this connection may not reach it (one answer for both) | |
| `conflict` | the record changed since it was read | nothing is overwritten; the customer sees their version, the current one and the proposed change |
| `invalid` | our request was wrong | |

`ConnectorClient` applies, on every call and in this order: the connection's state read from the database **now** (a removed connection stops at its next call); the
person's role and their organization's policy; the grants; the provider's rate limit (the Phase 1 limiter, one per account and provider); the paging caps; then the
call. Results are filtered by the grants again on the way back. What was read is recorded for freshness.

## How to add a connector

1. Write the declaration and the adapter in one module (copy `synthetic_connector.py`). The adapter needs: `resources`, `list`, `read`, `search` (the ones the
   declaration lists), and for writes `check`, `container_of`, `target_of`, `preview`, `write`, `find_effect`, `undo_payload`, `undo_after`, `compensation_payload`, `verify`.
2. Register it in `accounts/wiring.py` `connector_registry()`. Registration refuses a declaration with an unknown error kind or paging style, without a recorded
   implementation choice, or with a write kind that has neither an inverse nor a stated reason it cannot be undone.
3. If its tokens expire, add a refresher (`connector_refresher()` in wiring): `tokens -> {'tokens', 'expires_in'}`, raising `RefreshFault('temporary' | 'needs_customer' | 'revoked')`.
4. Add its rows to the privacy record and the policy **before** its switch is turned on (`privacy/README.md`): it is a new recipient of customer data.
5. Prove it with the same tests the synthetic one passes (`tests/test_connector_layer.py`, `tests/test_actions.py`).

An adapter raises `ProviderError(status, code, retry_after)` (never the provider's text) or `Unanswered` when a write was sent and no answer came back.

## How to add a write kind

Add a `WriteKind` to the declaration:

```python
WriteKind('note.update', 'Change a note', policy_kind='write', undo='note.update', needs_version=True)
WriteKind('message.send', 'Send a message', policy_kind='send', irreversible_reason='A message that has been sent cannot be taken back.', compensations=('message.correction',))
```

- `undo` names the write kind that reverses it; or `irreversible_reason` says, in a sentence the customer reads, why it cannot be undone. One of the two is required.
- `compensations` are follow-ups defined in code for a kind that cannot be undone. The assistant may propose one; it never writes one.
- `policy_kind` is the word an organization's policy uses (`send`, `share`, `write`, `delete`, `invite`).
- `needs_version=True` for a write that changes an existing record: it carries the version it was based on.

Then in the adapter: `check` (is the payload well formed), `preview` (built **only** from the stored payload and the record as it is now: destination, each change with
before and after, how many records), `undo_payload` (what the inverse needs, taken **before** the forward write), `undo_after` (adds what is only known afterwards, such
as a created id), `compensation_payload` (the follow-up's payload, with fixed wording), `verify` (does what the provider holds now match what was sent).

## What happens to one change (the synthetic connector, end to end)

1. The assistant calls `lumina_connector_propose`. `ActionService.propose` checks role, policy, grant and shape, reads the record as it is, stores the exact payload and
   its hash, and renders the preview. **Nothing is sent.** The assistant is told to end its turn. A handoff row records that an approval is awaited; no running slot and no
   cell is held.
2. The customer sees the preview on the task (and in Activity under "Needs you") and approves **that hash** (`POST /v1/actions/<id>/approve`). A changed payload, a second
   click or an expired approval approves nothing. An organization may ask for an admin as well.
3. The request worker's action pass (`ActionRunner.tick`) moves it from "approved" to "executing" in one guarded update, so it is sent **at most once**, with the
   idempotency key `<request id>-<step>`. The inverse's data and every registered compensation are stored before the send.
4. A write whose answer never came is `uncertain`: it is read back (`find_effect`), never sent again blindly. A worker that died mid-send leaves it "executing"; after two
   minutes it is treated the same way.
5. After a success the result is read back and compared (`verify`). A mismatch is recorded and shown.
6. The chat that waited is resumed with a turn that tells the assistant what was decided and what happened.
7. Undo is offered for the time the write kind states. It is itself an action: previewed, approved, sent once, with the version the forward write left, so it does not
   overwrite a later change by somebody else.

A **workflow** is several of these with one approval over a hash of every step's hash. Steps that can be undone come before steps that cannot (a proposal in another
order is refused). If a step fails, the finished steps are walked back in reverse order (the inverse, or the registered compensation) and the report says exactly what was
reversed and what could not be.

## Switches

| Switch | What it opens |
|---|---|
| `connectors_linking` | connecting real services (none is registered yet: Phase 5 adds the first) |
| `connector_writes` | the assistant may prepare changes; needs the connector key file |
| `synthetic_connector` | the fake service, for the live proof only |

Removing a connection is always possible, whatever the switches say.

## Mail and calendar providers (the dashboard, roadmap #D1)

A mail or calendar provider is a connector (the declaration above, with `hub=HubCaps(...)` and `several_accounts=True`) whose adapter ALSO speaks the "hub interface"
below. Everything a provider sends is converted to the canonical shapes **in its adapter, by pure functions** (`agentai_platform/hub_model.py`); nothing in the sync
engine (`hub_sync.py`), the service (`hub.py`), the assistant's tools (`hub_tools.py`) or the web app may name a provider (`tests/test_hub.py`
`test_no_provider_is_named_...` searches them). Google (`google_hub.py`) is the worked example; `tests/hub_fixture.py` holds two fake providers that differ in everything a
provider can differ in, and every dashboard test runs with one account of each.

### The canonical shapes (`hub_model.py`)

| Shape | Fields | Notes |
|---|---|---|
| `message(...)` | `id`, `thread_id`, `subject`, `sender` and `to`, `cc` (people: `{name, address}`), `sent_epoch`, `snippet`, `labels` (the common set: inbox, sent, drafts, archive, spam, trash, starred, unread), `provider_labels` (`[{id, name}]`, the provider's own), `unread`, `starred`, `has_attachments` | Headers only: what the list shows. Cut to length, control characters removed |
| `body(...)` | `text`, `html`, `attachments` (`[{id, name, type, size}]`) | Fetched only when the message is opened or read; kept 90 days after it was last opened |
| `calendar(...)` | `id`, `name`, `colour`, `timezone`, `access` (busy, read, write, owner), `primary` | `access='busy'` means free/busy only: events show as "busy" |
| `event(...)` | `id`, `calendar_id`, `series_id`, `title`, `start_epoch`, `end_epoch`, `all_day` with `start_date`/`end_date` (dates, no timezone), `timezone`, `place`, `conference_url` (https only), `organizer`, `attendees` (`{name, address, response, self, optional}`), `my_response`, `exception`, `cancelled`, `visibility`, `version`, `description`, `provider_url`, `updated_epoch` | One OCCURRENCE as the provider expanded it (never expand recurrence rules locally, #51) |
| `Changes` | `items`, `removed` (ids), `cursor` (opaque to all but its adapter), `more` | One page of "what changed since". Raise `ResyncRequired` when the provider rejects a cursor: the engine refills cleanly |

Deduplication is a uniqueness rule on (account, connection, provider id): a sync that runs twice changes nothing.

### The hub interface (what the adapter adds)

    calendars(credential) -> [calendar(...)]
    mail_changes(credential, cursor, since_epoch, labels, limit) -> Changes           labels: None = all mail, else the label ids the customer chose
    event_changes(credential, calendar_id, cursor, start_epoch, end_epoch, limit) -> Changes
    mail_body(credential, message_id) -> body(...)
    mail_search(credential, query, labels, position, limit) -> connector_kit.Page of message(...)     live search beyond the copy (only if mail_search)
    mail_attachment(credential, message_id, attachment_id) -> bytes                  only if attachments
    compose_link(to, cc, subject, body) -> https address of the provider's compose screen   only if compose_link
    resources(credential) -> [{kind: mailbox|label|calendar, id, name}]               the picker; nothing is chosen by default

### The capability table (`HubCaps`): the only place providers differ

| Capability | Meaning | Google |
|---|---|---|
| `mail`, `calendar` | has mail, has calendars | yes, yes |
| `mail_search` | can search mail beyond the copy, live | yes |
| `incremental` | has a "what changed since" cursor (else every sync re-reads and compares) | yes (history id, sync token) |
| `push` | can notify Lumina of a change (Phase 7) | no |
| `labels` | `labels` (several per message), `folders` (one), or `none` | labels |
| `subjects` | threads have subjects | yes |
| `attachments` | an attachment's bytes can be read (#55) | yes |
| `compose_link` | a Lumina draft can open in the provider's compose screen (#57) | yes |
| `free_busy` | answers a live free/busy question across calendars (#59); without it the synced copy is used, and the answer says so | yes (`freeBusy`) |
| `send`, `organize`, `mark_read`, `event_write`, `respond` | managing from the dashboard (Phase 6); each needs registered write kinds with previews, approval and undo, AND the connection must hold the grant behind it (`HubCaps.effective(scopes)`) | `event_write` yes (grant `calendar_write`); the others not yet |

### Grants: permissions to change things, asked on first use (Phase 6)

A sign-in only ever asks to read. Each kind of change has a named grant (`hub_model.Grant`: the same names for every provider, the provider's own scope beside it), asked for only
when the customer first uses what it allows, on the account already connected: `POST /v1/hub/link {provider, connection, add: [grant]}` sends them to the provider with
`include_granted_scopes` and the account's address; finishing changes **that** connection in place (`ConnectorService._upgrade`: same identity or `WrongAccount`, tokens
replaced in custody, grants and the synced copy kept). `HubCaps.effective(scopes)` gives each connection's real capabilities and, under `missing`, the grant to ask for.

| Grant | Google scope | Unlocks |
|---|---|---|
| `calendar_write` | `calendar.events` (sensitive) | `event_write`, `respond` |
| `send` | `gmail.send` (sensitive) | `send` |
| `organize` | `gmail.modify` (restricted) | `organize`, `mark_read` |

A write to a mail or calendar provider needs, in `ConnectorClient._may_write`: the customer's read grant on the resource, the grant behind the write kind's `capability`,
and for a calendar an access role that allows changing it (`owner` or `write`; a shared or subscribed calendar it may only read gets no write). The owner switch is
`mail_calendar_writes` (`accounts/wiring.py writes_on(account, service)`); every other connector stays under `connector_writes`.

### The write-kind registry (mail and calendars)

| Write kind | Provider | Capability | Undo | Idempotency | Version | Verified by |
|---|---|---|---|---|---|---|
| `event.create` | Google | `event_write` | `event.delete` (7 days) | event id derived from the key (`google_calendar_writes.event_id_for`); a repeat answers 409 and is read back | n/a | read back: title, start, end, attendees |
| `event.delete` | Google | `event_write` | `event.recreate` from the event as it was | the event being gone | `If-Match` ETag (412: `conflict`) | read back: gone or cancelled |
| `event.recreate` | Google | `event_write` | `event.delete` | as `event.create` | n/a | as `event.create` |

A change the customer makes with their own hand (`ActionService.direct`, routes `/v1/hub/events/create`, `/v1/hub/events/cancel`, `/v1/hub/actions/<id>/undo`) is the same write
kind through the same pipeline; their press is the approval and the screen is recorded (`actions.direct_screen`). A change the assistant prepared (`lumina_calendar_create`,
`lumina_calendar_cancel`) is never recorded as direct, whatever screen approves it.

The web app and the tools read these values; a control appears only where its capability is true. Adding Microsoft (Phase 6, #D8) is: a declaration, an adapter with the
hub interface and its pure conversion functions with a fixture per case (a plain message, a long thread, HTML only, inline images, an invitation, all-day, a recurring
series with a moved and a cancelled occurrence, an event across a daylight-saving change), and its sign-in entry in `accounts/wiring.py` `sign_in_providers()`.
Nothing else changes.
