# Proposed policy change, 2026-11-16: mail and calendars, files and the document index

**Not published.** `deploy/vercel/public/privacy.html` is unchanged. A change to the public policy, and the reviewed record `../facts.json`, need the owner (`../README.md`:
"edited by a person, never generated"). This folder holds the prepared text so the review is one step.

## Why now

- The owner switch `mail_calendar_dashboard` has been **on for every account since 2026-11-16** (read on the server). The live policy (dated 15 November) does not mention
  Google, the mail and calendar copy or how long it is kept. `tests/test_privacy_policy.py` fails three checks on `main` for that reason.
- Roadmap Phase 4 adds uploads, the document index (passages and search vectors on our own server) and pages with no text read by the model provider. Their switches
  (`customer_uploads`, `customer_knowledge`) refuse to turn on until the policy describing them is published.

## What the proposed page changes

`2026-11-16-mail-calendar-documents.html` is the whole page. Compared with the live one:

| Section | Change |
|---|---|
| Date | Last updated 16 November 2026 |
| The short version | Two lines: connecting a Google account (read only, what is copied); files and attachments read into the customer's own index, pages with no text read by the model provider |
| What we collect | New "Mail and calendars you connect" (Google sign-in, read-only access, what is copied, message text only when opened and kept 90 days after it was last opened, pictures held back, drafts kept in Lumina and opened in Gmail's compose screen by the customer's own browser, attachments read into the index, mail content is not an instruction) and "Files and documents" (uploads up to 10 MB, the index, vectors made on our server, pages with no text sent to the model provider, the Sources page, sharing with chosen people) |
| Your content | Commitments (suggested ones need confirming); what the assistant checked (ids and fixed words); corrected memory notes keep their history |
| Who receives it | Google (only if connected); Anthropic also reads the parts of mail, calendars and documents the assistant reads, and the pages with no text; our document index (our own server, no other company) |
| How long we keep it | Mail headers and previews, events and drafts: until removed; message text: 90 days after it was last opened; uploads and the index: until removed; commitments; what the assistant checked: 90 days |
| Your choices | Removing an account deletes its tokens and every copy; the Sources page; Commitments |
| Connecting other services | "Google Mail and Calendar, read only, is the one built-in service connector that is on" |

Every statement was checked against the code: the retention rules (`agentai_platform/retention.py` rows `mail_headers`, `mail_bodies`, `calendar_events`, `mail_drafts`,
`uploads`, `document_passages`, `commitments`, `task_checks`), the scopes in `google_hub.py` (`gmail.readonly`, `calendar.readonly`, `openid email`), and the tests
(`tests/test_hub.py`, `tests/test_google_hub.py`, `tests/test_knowledge.py`).

## The record changes that go with it (for the person applying it)

`python3 platform/privacy/derive.py` prints the code's values. They differ from `facts.json` in:

- `derived.retention.retention_table`: `task_checks` 90 days and `mail_bodies` 90 days, both swept.
- `derived.hosts`: `accounts.google.com`, `gmail.googleapis.com`, `oauth2.googleapis.com`, `mail.google.com` are new; each needs a `hosts_explained` entry (who: Google,
  customer_data: true, in_policy: "Google"), and `www.googleapis.com` now carries customer data (Mail and Calendar).
- `derived.schema_sha256` and `schema_columns`: migrations 0048 to 0050 (the hub tables, file folders and places, the knowledge tables, commitments, organization groups,
  memory history, mail drafts).
- `policy_must_not_say`: drop "Gmail" and "Google account" (the policy now names them, truthfully). `policy_must_say`: add phrases of the new sections.
- `server.features_off_so_policy_is_silent_on_them`: drop `file_uploads` once the page is published; `check_server.py` then needs to accept uploads being on.
- `policy_updated` and a `review_log` line.
