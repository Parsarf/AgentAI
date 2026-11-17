# Roadmap Phase 5 - the mail and calendar dashboard, read-only

**Status (2026-11-16): PARTLY SHIPPED, EXIT GATE NOT PASSED.** The dashboard (#D1 to #D4, #49 to #56) and most of the assistant beside it (#D5) are merged (pull requests #50 to #59)
and live: the server runs `9b01cf1`, and the owner turned `mail_calendar_dashboard` **on** for every account. Google is the only real provider. The rest (#57 drafts, #58
the meeting brief, attachments read through the Phase 4 pipeline, the panel's chats kept in their own project) is built on branch `phase-4-5-complete`, **not committed, not
merged**. Exit gates 1, 6 and 7 are open (table below).

Read on the server on 2026-11-16 (read only): one account has connected an account (one Google connection; 68,900 messages and 300 events copied). `agentai-hub-sync.service`
is active but is killed at its 1 GB memory cap during the first fill and restarts with its progress kept (64 restarts, 30 out-of-memory lines in the journal in three hours).

## Exit gate

| Gate | State |
|---|---|
| 1. The read-only suite on a real Google test account with **two** connected Google accounts | **Not run.** Proven read only with the owner's own single account on 2026-11-16 (sign-in, picker, mail fill, opening a message, history, one-label limit, older-mail search, calendar list, sync token, token renewal). Not exercised by real data: real calendar events, a message with attachments or markup. Drafts, the brief and attachments are not deployed |
| 2. The same suite with one Google account and the test-only second provider, with no provider name in any screen or tool condition | **Passes in tests**: `tests/hub_fixture.py` (two fake providers, `alpha` and `postbox`, that differ in ids, labels, paging, change feeds and calendars), `tests/test_hub.py` (`test_no_provider_is_named_in_the_model_the_engine_the_service_or_the_schema`), `Inbox.test.tsx` |
| 3. No planted instruction in an email causes any action, including with that email open | **Passes in tests**: `test_reading_a_thread_fetches_its_text_and_an_instruction_inside_a_message_is_removed_not_obeyed`, `test_knowledge.py` `test_planted_instructions_in_mail_and_documents_stay_data`. Not run against a real model |
| 4. Removing a connection removes tokens and every copied record | **Passes in tests**: `test_removing_an_account_removes_every_copy_of_it`, `test_only_the_chosen_labels_are_copied_and_narrowing_removes_the_rest` |
| 5. Remote content is not loaded without the customer asking | **Passes in tests**: `test_a_message_is_shown_safely_and_remote_pictures_wait_for_the_customer` (`hub_html.py`) |
| 6. Sync holds the Phase 1 latency baseline; measurements in this file | **Measured (2026-11-16, production):** 68,915 messages and 300 events copied for one account; the hub tables take 111 MB (about 1.6 KB a message, threads and indexes included) of a 149 MB database. Interactive messages while the sync ran all day (last 60 requests, `deploy/latency_report.py --summary`): warm wait for a turn 0.68 s median, 2.24 s at the 90th percentile, against the Phase 0 baseline of 1.5 s: **holds**. The first fill ran at about 8,000 messages an hour (Gmail's per-user limit with 4 reads in flight). Open until the release that fixes it is live: the service grew about 10 MB a minute and was killed at its 1 GB cap; it now builds its services once, reuses one TLS context and kept-alive connections, and starts afresh at 600 MB before the kernel has to kill it |
| 7. The privacy policy names the new data, where it comes from, the window and how long it is kept | **Open.** The live policy (dated 15 Nov) does not mention Gmail, Calendar or the copy; `privacy/facts.json` still calls Google switched off; `tests/test_privacy_policy.py` fails three checks on `main`. The switch's `policy_published` confirmation was recorded anyway |

## Feature table

| # | Feature | State | Where |
|---|---|---|---|
| D1 | Provider-neutral model | **Live.** Canonical accounts, threads, messages, calendars, events; deduplication by (account, provider id); a capability table per provider; pure conversion functions with fixtures | `hub_model.py`, `google_hub.py`, `tests/test_google_hub.py` |
| D2 | Connected accounts and sync | **Live, with the open memory fault.** Several accounts per person; background service with checkpoints and provider cursors; faults as the six Phase 3 kinds; removal deletes every copy. Owner's choice (2026-11-16): everything in the chosen labels is copied, calendars from the past to two years ahead, kept until the account is removed | `hub_sync.py`, `agentai-hub-sync.service` |
| 49, 50 | Calendar connection, several calendars | **Live.** Link flow with a picker, nothing selected by default; several accounts. Two real accounts at once not proven live | `hub.py`, `components/hub/Connect.tsx` |
| 51 | Recurring events | **Live.** Expanded instances from the provider; series id, exception and cancelled marks kept. Not exercised on real recurring events yet | `google_hub.to_event`, `test_recurring_instances_keep_their_series_their_exception_and_their_cancellation` |
| D4, 52-54 | Unified calendar, viewing, event search, questions | **Live.** Calendar page with every selected calendar; assistant tools to list, get and search events, each naming its account. Not built: a citation that selects the event in the page | `CalendarPage.tsx`, `hub_tools.py` |
| D3, 55, 56 | Unified inbox, reading, search | **Live.** Inbox across accounts, safe HTML, remote pictures on request, local search then provider search for older mail with counts and completeness; read only. First page over its 300 ms target | `Inbox.tsx`, `hub_html.py`, `hub_tools.py` |
| D5 | The assistant in the dashboard | **Mostly live.** One assistant panel on every page (`POST /v1/assistant/ask`) that knows the open thread or event (ids only), with one-click questions ("Prepare me for this"). On the branch: the panel's chats kept in an "Assistant panel" project. Not built: answers that select the cited thread or event in the page | `components/frame/Assistant.tsx`, `agentai_platform/chat.py` |
| 57 | Email drafting | **On the branch, server side only.** Drafts are Lumina records with a compose link, never put in the mailbox (`/v1/hub/drafts`, the assistant's draft tool). Not built: the editor in the Inbox and the Drafts filter | `hub.py`, `knowledge_tools.py`, `test_drafts_are_lumina_records_with_a_compose_link_and_never_reach_the_mailbox` |
| 58 | Meeting preparation | **On the branch.** The brief tool gathers the event, people, recent threads, documents, open commitments and the last meeting, and says what is missing; the Calendar page's "Prepare me for this" is live and asks for it | `knowledge_tools._meeting_brief`, `test_the_meeting_brief_gathers_...` |
| - | Attachments through the Phase 4 pipeline | **On the branch.** An attachment opened from mail is read into the knowledge index with the email as its source | `knowledge_tools._mail_attachment`, `test_an_attachment_is_read_through_the_pipeline_and_becomes_searchable` |

## Needs the owner

- The privacy policy text for the mail and calendar copy (gate 7), then `privacy/facts.json` and a review-log line. The switch is already on.
- A second Google account (or a Lumina test account) to run gate 1 with two accounts, and an account that has recurring events and mail with attachments.
- The consent screen shows the Google project of the owner's other app: use a Lumina client or rename the app before inviting anyone else (`PENDING_DEPLOY.md`).
- Gmail read access is a restricted scope: Google's verification is needed before a public launch.

## Rollback

Turn `mail_calendar_dashboard` off: the pages and tools disappear and the sync goes idle. The copied data stays under its retention rows until the account is removed.
