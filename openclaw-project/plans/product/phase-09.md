# Phase 9 — durable live work timeline and task controls

Status: **build READY; fail-closed** — no real task events exist until
Phase 4/5 connect execution, and browser live-streaming (SSE consumption in
the page) awaits a UI/JS decision, so the customer page updates on refresh
while the stream API is fully available. Deployed 2026-10-08 as release
`20261008T115500Z-events`.

## Implemented

- `agentai_platform/events.py`: durable normalized event store on the
  foundation `events` table. Typed payload allowlist per kind (plan,
  progress, search, file_change, command_result, test_result,
  approval_request/decision, error, budget, artifact, result,
  task_started/queued); recursive secret redaction (token formats +
  key-name patterns); 32KiB payload bound with truncation marker; per-task
  sequence, stable ids, source tag; 2000-event ceiling per task.
- Cursor reads: gap-free by sequence with `after` pagination (≤200);
  expired/absent data is simply absent — the API exposes only what exists.
- Authenticated SSE stream (`GET /v1/tasks/{id}/stream`): bounded 45s
  window with explicit reopen payload, heartbeats, per-event ids, open
  stream cap of three per account (429 + Retry-After), liveness/revocation
  recheck between batches (suspension/revocation end the stream), CSRF
  exempt as a GET-only read endpoint, atomic stream close on disconnect.
  `GET /v1/tasks/{id}/events` is the cursor-polling fallback the page uses.
- Execution driver wiring: task_started → progress (runtime accepted,
  transcript updates) → cancellation confirmation → result, best-effort
  (timeline write failure degrades the timeline, never the task).
- Retention: 30-day detailed-event pruning added to the host retention
  command, matching product/CONTRACT.md.
- Chat page: per-task timeline entries (time · kind · summary) under each
  work card, with the honest note that the page updates on refresh and
  live streaming activates with execution. No pause control is rendered:
  native pause is unverified; timeline viewing pause is trivially "don't
  refresh" and is labeled as such in docs.

## Checks actually run (2026-10-08)

- 10 service tests: redaction (recursive token/key patterns, JWT), payload
  allowlist + truncation, sequence/scoped reads, gap-free cursor replay,
  unknown-kind/missing-task denials, stream cap + expiry + revocation,
  30-day prune, and the synthetic running task's timeline surviving
  departure/return/restart with exactly one execution and no repeated
  transcript rows.
- 3 HTTP tests: cursor endpoint scoping/validation (cross-account 404),
  SSE authentication + 429 cap + open/task-event frames + heartbeat +
  generator cleanup, timeline rendering on the chat page.
- Full suites: 143 core tests OK, 62 Django tests OK, concurrency +
  loopback HTTP scripts PASS, Vercel routing PASS. CI extended with
  `tests.test_events`.

## Deployment 2026-10-08

Release `20261008T115500Z-events` deployed; **pre-migration backup taken
before the stop step** (`backup-20261008T115800Z-premigrate.sqlite3`,
integrity ok — checklist correction from Phase 7/8 applied); SQL0008/
Django0012 applied; origin verification: events/stream 401 anonymous, chat
302, internal 404, readiness honest.

## Not claimed / gates

- No real task events exist (execution disabled); the synthetic flow proves
  the durable store, not agent behavior.
- Browser-side SSE consumption requires allowing scripts in the UI CSP —
  a deliberate product decision left for Phase 15/17 acceptance; the
  server transport is complete and tested.
- Approval bridging is NOT implemented: native approvals are unverified,
  so approval_request events render read-only and no decision surface
  exists. Owner credentials are never broadened to approximate delegation.
- Session/worker tree and search/source filters arrive with real events
  (Phase 15/17); the payload schema already reserves them.

Rollback: code-only to `20261008T091500Z-files` refuses the newer schema;
restore the pre-migrate backup into a fresh state root per runbook if
required.

Evidence: `evidence/product/phase-09/20261008T120000Z/`.
