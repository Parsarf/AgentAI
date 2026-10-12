# Phase 7 — one Telegram ingress with secure account linking

Status: **build READY; real bot linking/replies explicitly deferred to
Phase 15/17 acceptance** (no customer bot token exists; the feature is
fail-closed on production and no invitation was sent). Deployed
2026-10-06 as release `20261006T073000Z-telegram`.

## Implemented

- Migration SQL0006 + Django0010: `telegram_links` (chat↔account binding,
  one chat maps to at most one account), `telegram_link_codes` (SHA-256
  hashes only, single use, 10-minute expiry, actor bound),
  `telegram_updates` (durable update dedup before routing),
  `telegram_outbox` (replies with receipt states
  pending/sent/uncertain/failed). `chat_messages` rebuilt with the
  `telegram` provenance (rows copied; production table was empty).
- Ingress decision: **webhook over polling** — the owner's personal bot
  already holds a poller (409 precedent), the customer bot is a separate
  token, and the webhook verifies the `X-Telegram-Bot-Api-Secret-Token`
  header (constant-time), needs no new long-running unit, and rides the
  existing TLS edge. Endpoint: `POST /v1/telegram/webhook`
  (`@csrf_exempt`; provider-authenticated). Token exists only in the
  ingress settings; never in links, logs or replies.
- Linking: `POST /v1/account/telegram/link` (rate-limited 5/15min,
  invalidates previous codes, deep link within Telegram payload limits),
  atomic consume bound to the numeric sender id from the authenticated
  update, unique chat→account mapping, clear conflict/expiry replies,
  unlink (per chat or all) + authenticated re-link; groups rejected;
  attachments bounded away (Phase 8).
- Routing: linked text DMs become sends through the same Phase 5
  admission and serial queue (key `tg<update_id>`, provenance `telegram`,
  same conversation model — latest conversation with messages in the
  selected or first project, else created). Commands: `/projects`,
  `/use <id>` (server-validated prefix), `/status`, `/unlink`.
  Suspended/revoked/unlinked chats can never start work; denial is
  rechecked on every update.
- Replies: every customer-visible outcome enqueues an outbox entry; the
  webhook attempts one bounded inline send (receipt recorded
  sent/uncertain/failed; network failures stay reconcilable, never
  auto-resent) and `manage.py telegram_worker --check/--drain` covers the
  host-side bounded drain. Acknowledgements state plainly that execution
  is offline and nothing is charged.

## Checks actually run (2026-10-06)

- 14 service tests: code hashing/invalidation, expiry/reuse/invalid,
  swapped codes (bearer binds the code owner; conflict guard), threaded
  simultaneous consumption (single winner), dedup (duplicate update ids
  route once), unlinked denial, provenance+conversation placement,
  project commands incl. foreign-id denial, suspension/revocation/unlink
  denials, budget-denial cancellation, outbox receipts/drain,
  group/attachment/non-numeric ignoring.
- 5 Django HTTP tests: fail-closed routes (503 unconfigured, 401/403
  identity), webhook secret enforcement (403 wrong/missing, 200 valid),
  linked-update routing to the correct account with cross-account 404,
  disabled-link form notice, overview Telegram section.
- Full suites: 124 core tests OK, 53 Django tests OK, concurrency +
  loopback HTTP scripts PASS, Vercel routing PASS. CI workflow extended
  with `tests.test_telegram`.

## Deployment 2026-10-06

Release `20261006T073000Z-telegram` deployed (75+ files hash-verified);
SQL0006/Django0010 applied during a stopped-services window; readiness
honest; verified through the origin (webhook 405 GET, link 401 anon,
chat 302, internal 404). **Process lapse recorded:** the pre-migration
private backup was not taken before this deploy (previous backup
20261005T180607Z predated it); a post-migration backup
(`backup-20261006T073500Z-postmigrate.sqlite3`, integrity ok) was taken
immediately and the checklist corrected for future deploys.

## Not claimed / gates

- No real bot, token or webhook registration exists; enabling requires a
  dedicated customer bot + `AGENTAI_TELEGRAM_BOT_TOKEN`,
  `AGENTAI_TELEGRAM_WEBHOOK_SECRET`, `AGENTAI_TELEGRAM_BOT_USERNAME` and
  a `setWebhook` call (host operator action).
- Real linking/reply proof and cross-surface history on live Telegram:
  Phase 15/17 with controlled users. Owner/personal Telegram checks
  remain historical acceptance obligations.
- Attachments (Phase 8) are rejected at the ingress.

Rollback: code-only to `20261005T200500Z-ui` refuses the newer schema —
schema-compatible rollback is to none; restore the verified backup into
a fresh state root per runbook if ever required.

Evidence: `evidence/product/phase-07/20261006T073000Z/`.
