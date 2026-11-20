# Roadmap Phase 6 - controlled communication and scheduling

**Status (2026-11-20): IN PROGRESS.** Audit done, owner's answers recorded. First group built and tested (this release): the foundation, #59, #60, #61 and the cancel part of
#63 for Google calendars, behind `mail_calendar_writes` (off). Next: the live write cycle on the owner's test account (needs the `calendar.events` scope on the consent
screen), then #62, #64, #65 and mail. (Not a final state: see the completion contract.)

## Live write cycle on the real provider (2026-11-20)

`deploy/phase6_live.py` on the owner's test account (`parsaaraouf@…`, calendar permission given through "Allow changes" from the Calendar, in place): W-FREE, W-CREATE, W-RETRY
(running again sends nothing, a second approval refused, the same request again makes no second event), W-UNKNOWN (an unknown outcome read back), W-UNDO (cancel with its
version, then put back), W-CONFLICT (an event changed at Google is not cancelled) and CLEANUP (0 of 4 events left): **all PASS** for `event.create`, `event.delete`,
`event.recreate`. Nobody was invited or told (no attendees). Google console: the five Gmail and Calendar scopes and `openid`/`email` are declared on the consent screen
(Data Access), done 2026-11-20.

## Built (PR #67, deployed `48a0dde`)

| Part | What | Tests |
|---|---|---|
| Grants and re-consent | Named grants (`calendar_write`, `send`, `organize`) asked on first use; `POST /v1/hub/link {connection, add}`; finishing upgrades the SAME connection in place (`ConnectorService._upgrade`): before, signing in again to an account revoked it and deleted its copy | `tests/test_google_hub.py` (in place, wrong account, someone else's) |
| Per-connection capabilities | `HubCaps.effective(scopes)`: a write control exists only where the provider can and the connection holds the grant; `missing` names what to ask | `test_nothing_but_reading_is_ever_asked_of_google` |
| Write access for mail and calendar providers | `ConnectorClient._may_write`: read grant + grant behind the write kind + a calendar the account may change (owner or writer) | `test_nothing_can_be_prepared_without_the_permission...` |
| Owner switch | `mail_calendar_writes` (off), separate from `connector_writes`; `writes_on(account, service)` | `tests/test_switches.py` |
| Direct actions | The customer's own press is the approval (`ActionService.direct`, `actions.direct_screen`), Undo from the dashboard, a held change that can be stopped (for Undo send); an assistant's change is never "direct" | `test_the_customers_own_press_is_the_approval...` |
| #59 availability | Live `freeBusy`, the copy where a calendar cannot answer (said), working hours per weekday, notice, buffer, which calendars count, all-day events busy | `Availability.test_free_time...` |
| #60 conflicts | Against expanded instances; a weekly proposal across a clock change lists the dates that clash; tentative, busy-only, buffer-only, all-day | `Availability.test_a_weekly_proposal...` |
| #61 event creation | `event.create`: event id from the idempotency key (a retry answers 409 and is read back), invitations said in the preview, read-back verification, undo = cancel | `test_the_write_cycle_one_event_under_retry_double_approval_and_a_lost_answer_then_undo` |
| #63 cancellation (organizer, single event) | `event.delete` with `If-Match` (412 = conflict, nothing cancelled over someone's change), "N people are told", undo = `event.recreate` | same, and `test_an_event_changed_elsewhere...` |
| Assistant tools | `lumina_calendar_free`, `lumina_calendar_conflicts`; `lumina_calendar_create` and `lumina_calendar_cancel` only PREPARE (listed only while writes are on) | `test_the_assistant_only_prepares...`, `tests/test_hub.py` |
| #64 invitation responses (next release) | `event.respond`: only the account's own attendee entry changes (the list is read just now under the same ETag), optional note, undo = the previous answer; the Calendar shows Going / Maybe / Not going for an invitation from someone else instead of Cancel | `test_answering_an_invitation...`, `CalendarPage.test.tsx` |
| Calendar page | "New event" (only calendars that can be changed), "Cancel event" for events the customer organizes with who is told, Undo, "Allow changes" where the permission is missing | `CalendarPage.test.tsx`, `EventEditor.test.tsx`, `AllowChanges.test.tsx` |


## Starting point (checked on the live stack, 2026-11-20)

- Phase 3 exit gate: PASS (`roadmap/phase-03.md`). The action pipeline (`actions.py`, `workflows.py`, `handoff.py`) is live; only the test-only synthetic connector has write kinds.
- Phase 5 exit gate: PASS (`roadmap/phase-05.md`): all 9 gate-1 checks with two real Google accounts on 2026-11-20, G1-ANSWER after the tool-origin fixes #66, #70, #71 and #72.

## Audit (one line per feature; label from the inventory)

| # | Feature | Label right? | What exists | What is missing |
|---|---|---|---|---|
| 59 | Availability checking | M: yes | Synced events (`hub_events`, expanded instances), the customer's timezone | Free/busy query (`freeBusy`), availability settings (working hours, notice, buffer, which calendars count), a tool |
| 60 | Conflict detection | M: yes | Expanded instances with all-day and cancelled marks | The check itself (DST, timezones, partial series conflicts, buffers, tentative), "busy" for hidden events |
| 61 | Event creation | M: yes | Phase 3 pipeline; `HubCaps.event_write` (False) | Google `calendar.events` scope and re-consent, the write kind, client-generated event id as idempotency key, read-back, undo |
| 62 | Event modification | M: yes | Version token column on events (`hub_events.version`) | `events.patch` with `If-Match`, series scope (this, following, all), notified-people count, undo |
| 63 | Event cancellation | M: yes | - | Delete for the organizer, decline otherwise; re-create as undo |
| 64 | Invitation responses | M: yes | `my_response` synced | `attendees[self].responseStatus` write, verify, undo |
| 65 | Meeting scheduling | M: yes | Durable objectives, handoff (waits without a slot), drafts | The workflow over #59 to #61 |
| 66 | Email sending | M: yes | Drafts kept in Lumina (`hub_drafts`), compose link | `gmail.send` scope, send of an approved draft, Sent-folder reconciliation by marker, first-time/unusual recipient warnings, limits (50 recipients, 30 an hour), correction email as compensation |
| 67 | Inbox organization | M: yes | Common label set, `HubCaps.organize` (False) | `gmail.modify` scope, label/archive/read/star/trash write kinds, batch preview and batch undo |
| D6 | Mail from the dashboard | M: yes | Inbox page, draft editor | Send, reply, reply all, forward, undo send (10 s), organize with undo, pending/final/failed states |
| D7 | Events from the dashboard | M: yes | Calendar page | Create, change, drag, cancel, answer; scope question for series; "N people will be told" |
| D8 | Microsoft | M: yes | Provider-neutral model, capability table, a second fake provider in tests | Graph adapter (delta links, folders and categories), Entra app (owner), publisher verification (owner), admin-consent sentence |
| D9 | Calendar feeds; password accounts | M: yes | `ssrf.py` destination guard | ICS feed connection (read only), the IMAP/SMTP/CalDAV note in `CONNECTORS.md` (owner: later) |
| 68 | Messaging integration | P: yes | Telegram ingress, linking, outbox, record-only (`intake_chat_service`) | Telegram runs tasks (owner: yes); Slack connector (read, events, post) |
| 69 | Messages to others | M: yes | - | A post write kind with an allow-list of destinations and audience size |

## Owner's answers used (2026-11-20)

Google scopes `gmail.send`, `gmail.modify`, `calendar.events`, each asked on first use; writes on for **every account** once each write kind passes its live write cycle; at most 50 recipients a message and 30 messages an hour per account; Telegram may run tasks (approvals as links to the web app); Microsoft personal and work accounts, a plain admin-consent sentence; Slack yes (the owner creates the app); opening a message does not mark it read; "Undo send" waits 10 s; $25 for the proofs; IMAP/SMTP/CalDAV later; GitHub Issues as the second board (Phase 7). Still to be shown to the owner before publishing: the switch wording and the privacy policy change for writes.

## Plan

1. **Foundation:** a separate owner switch for writes (`mail_calendar_writes`), write scopes as named grants with incremental re-consent (`include_granted_scopes`), `HubCaps` set from the scopes a connection holds, direct actions (the customer's own press is the approval, recorded with the screen), the send limits.
2. **Calendar:** #59, #60, then #61 completely (declaration row, adapter, tool, Calendar page control, tests, live write cycle), then #62 to #64, #65.
3. **Mail:** #66, #67, #D6 (undo send as a 10-second delay on the approved action).
4. **Microsoft (#D8)** once the owner's Entra app exists; ICS feeds (#D9).
5. **Messaging:** Telegram tasks, Slack (#68, #69).
6. Privacy text and switch wording shown to the owner; write cycle on the real providers; exit gate.

## Needs the owner (real-world steps, can start now)

- **Google:** in the Cloud console, OAuth consent screen > Data access: add `.../auth/gmail.send`, `.../auth/gmail.modify`, `.../auth/calendar.events`. Keep the app in Testing (test users only) until Google's verification; start the verification (restricted scopes: OAuth verification plus the CASA assessment, yearly).
- **Microsoft:** Entra admin center > App registrations > New: name "Lumina", supported accounts "Any organizational directory and personal Microsoft accounts", redirect `https://getlumina.pro/v1/hub/link/callback` (Web). API permissions (delegated): `offline_access`, `openid`, `email`, `User.Read`, `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`. Certificates & secrets: a client secret (give it to me as a file on the server, not in chat). Then publisher verification (Branding & properties, a verified Microsoft AI Cloud Partner Program ID). Test accounts: one outlook.com and one work account (a Microsoft 365 developer tenant).
- **Slack:** api.slack.com/apps > Create New App > From scratch, in a test workspace you control; OAuth redirect `https://getlumina.pro/v1/hub/link/callback`; user scopes `channels:history`, `channels:read`, `im:history`, `im:read`, `chat:write`, `users:read`; Event Subscriptions on (the request address is given when #76 exists). Give the client id, secret and signing secret as files on the server.
