# Roadmap Phase 5 - the mail and calendar dashboard, read-only

**Status (2026-11-19): LIVE; GATE 1 WAITS FOR THE SECOND GOOGLE ACCOUNT.** Everything in this phase is merged and live: the server runs `b0a5dd7` (read back from
`/var/lib/agentai-deploy/last`, equal to `origin/main`), `mail_calendar_dashboard` is on for every account, and since 2026-11-19 attachments are read through the knowledge
pipeline (Phase 4 is installed and on). The policy describing the copy is published (gate 7). Gate 1 needs a second real Google account connected beside the owner's:
`deploy/phase5_live.py` runs it; on the owner's single account it already passes the draft and the meeting brief, and the rest only needs the second account.

Read on the server on 2026-11-19 (read only): one Google connection, 69,226 messages and 300 events copied; the sync service 57-62 MB, no restart.

## Exit gate

| Gate | State |
|---|---|
| 1. The read-only suite on a real Google test account with **two** connected Google accounts | **Waits for the owner's second account.** `deploy/phase5_live.py` (G1-ACCOUNTS, -INBOX, -CALENDAR, -READ, -SEARCH, -ATTACHMENT, -DRAFT, -BRIEF, -ANSWER). Trial on the owner's single account, 2026-11-19: G1-DRAFT and G1-BRIEF PASS (9 citations, 3 "could not find" statements); a real 4-page PDF attachment read into the index (28 passages); the rest need the second account |
| 2. The same suite with one Google account and the test-only second provider, with no provider name in any screen or tool condition | **Passes in tests**: `tests/hub_fixture.py` (two fake providers, `alpha` and `postbox`, that differ in ids, labels, paging, change feeds and calendars), `tests/test_hub.py` (`test_no_provider_is_named_in_the_model_the_engine_the_service_or_the_schema`), `Inbox.test.tsx` |
| 3. No planted instruction in an email causes any action, including with that email open | **Passes in tests**: `test_reading_a_thread_fetches_its_text_and_an_instruction_inside_a_message_is_removed_not_obeyed`, `test_knowledge.py` `test_planted_instructions_in_mail_and_documents_stay_data`. Not run against a real model |
| 4. Removing a connection removes tokens and every copied record | **Passes in tests**: `test_removing_an_account_removes_every_copy_of_it`, `test_only_the_chosen_labels_are_copied_and_narrowing_removes_the_rest` |
| 5. Remote content is not loaded without the customer asking | **Passes in tests**: `test_a_message_is_shown_safely_and_remote_pictures_wait_for_the_customer` (`hub_html.py`) |
| 6. Sync holds the Phase 1 latency baseline; measurements in this file | **Measured (2026-11-16, production):** 68,915 messages and 300 events copied for one account; the hub tables take 111 MB (about 1.6 KB a message, threads and indexes included) of a 149 MB database. Interactive messages while the sync ran all day (last 60 requests, `deploy/latency_report.py --summary`): warm wait for a turn 0.68 s median, 2.24 s at the 90th percentile, against the Phase 0 baseline of 1.5 s: **holds**. The first fill ran at about 8,000 messages an hour (Gmail's per-user limit with 4 reads in flight). Before #60 the service grew about 10 MB a minute and was killed at its 1 GB cap every hour or so. **After #60 (read on the server): 76.7 MB three minutes after start, 76.9 MB after 15 minutes and 353 passes (its own report: `{"passes": 353, "rss_mb": 75}`), no restart.** The memory growth is gone; the clean restart at 600 MB stays as a safety net. **Inbox, 2026-11-19:** the first call (`/v1/hub`) took 294 ms on the server because the app ran ONE worker held to a quarter of a CPU and the unread badge scanned every thread; with three workers, 200% CPU and an index of unread threads it takes **46 ms** (thread list 8 ms), measured on a copy of the production database on the host |
| 7. The privacy policy names the new data, where it comes from, the window and how long it is kept | **PASS.** Published 2026-11-19 (`https://getlumina.pro/privacy`): Google as a source and recipient of our requests, what is copied, message text kept 90 days after it was last opened, everything else until the account is removed; `privacy/facts.json` and the review log match; the policy test blocks merges |
| 8. The whole earlier evaluation suite still passes with these features on | **PASS.** Tier A (the acceptance cases) in CI on every pull request (#62, #63, #64); Tier B live after the `b0a5dd7` deploy (22:04 UTC on 2026-11-19), when `customer_uploads` and `customer_knowledge` were already on for every account: a real answer charged once, the version stamp, isolation |

## Feature table

| # | Feature | State | Where |
|---|---|---|---|
| D1 | Provider-neutral model | **Live.** Canonical accounts, threads, messages, calendars, events; deduplication by (account, provider id); a capability table per provider; pure conversion functions with fixtures | `hub_model.py`, `google_hub.py`, `tests/test_google_hub.py` |
| D2 | Connected accounts and sync | **Live, with the open memory fault.** Several accounts per person; background service with checkpoints and provider cursors; faults as the six Phase 3 kinds; removal deletes every copy. Owner's choice (2026-11-16): everything in the chosen labels is copied, calendars from the past to two years ahead, kept until the account is removed | `hub_sync.py`, `agentai-hub-sync.service` |
| 49, 50 | Calendar connection, several calendars | **Live.** Link flow with a picker, nothing selected by default; several accounts. Two real accounts at once not proven live | `hub.py`, `components/hub/Connect.tsx` |
| 51 | Recurring events | **Live.** Expanded instances from the provider; series id, exception and cancelled marks kept. Not exercised on real recurring events yet | `google_hub.to_event`, `test_recurring_instances_keep_their_series_their_exception_and_their_cancellation` |
| D4, 52-54 | Unified calendar, viewing, event search, questions | **Live.** Calendar page with every selected calendar; assistant tools to list, get and search events, each naming its account. A citation selects the event in the page (D5) | `CalendarPage.tsx`, `hub_tools.py` |
| D3, 55, 56 | Unified inbox, reading, search | **Live.** Inbox across accounts, safe HTML, remote pictures on request, local search then provider search for older mail with counts and completeness; read only. First call 46 ms on the server (was 294 ms) | `Inbox.tsx`, `hub_html.py`, `hub_tools.py` |
| D5 | The assistant in the dashboard | **Live** (#60). One assistant panel on every page (`POST /v1/assistant/ask`) that knows the open thread or event (ids only), with one-click questions; its chats are kept in an "Assistant panel" project; a citation in an answer is an in-app link that selects the thread or event in the page (`AgentResponse.tsx` `appLink`; Inbox and Calendar follow every new address) | `components/frame/Assistant.tsx`, `components/response/AgentResponse.tsx`, `agentai_platform/chat.py` |
| 57 | Email drafting | **Live** (#60). Drafts are Lumina records, never put in the mailbox: the editor beside the thread ("Write a reply", the assistant's drafts, changed in place when the assistant revises them), a "Written in Lumina" list across accounts, Copy, Open in your mail service (the provider's compose screen), Discard after asking. The mail and calendar tool results carry `open` links | `components/hub/DraftEditor.tsx`, `pages/Inbox.tsx`, `hub.py`, `DraftEditor.test.tsx`, `Inbox.test.tsx` |
| 58 | Meeting preparation | **Live** (#60). The brief tool gathers the event, people, recent threads, documents, open commitments and the last meeting, says what is missing, and cites each item with a link that selects it in the dashboard; "Prepare me for this" on an event asks for it. Documents join once the knowledge index is installed | `knowledge_tools._meeting_brief`, `test_the_meeting_brief_gathers_...` |
| - | Attachments through the Phase 4 pipeline | **Live** (2026-11-19). An attachment opened from mail is read into the knowledge index with the email as its source; a real 4-page PDF gave 28 passages | `knowledge_tools._mail_attachment`, `test_an_attachment_is_read_through_the_pipeline_and_becomes_searchable` |

## Needs the owner

- A second Google account connected beside the owner's (test user on the consent screen, then Inbox > Add account), and one question in the assistant panel about a thread of it: then `deploy/phase5_live.py` closes gate 1.
- The consent screen shows the Google project of the owner's other app: use a Lumina client or rename the app before inviting anyone else (`PENDING_DEPLOY.md`).
- Gmail read access is a restricted scope: Google's verification is needed before a public launch.

## Rollback

Turn `mail_calendar_dashboard` off: the pages and tools disappear and the sync goes idle. The copied data stays under its retention rows until the account is removed.
