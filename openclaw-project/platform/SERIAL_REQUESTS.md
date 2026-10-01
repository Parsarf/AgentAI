# Multi-user login and serial requests

Implemented: invite-only verified customer accounts and durable request intake,
account-scoped request page/API, cancellation, FIFO worker claim/heartbeat/
reconciliation/receipt handling and one persisted global task slot. Pending
requests are intake records, not funded/admitted native tasks. They can wait for
execution readiness without provider calls or borrowed owner credentials.

Host-only `manage.py onboard_trial --email <email>` creates a distinct account,
project, seven-day/$1 entitlement, pending identity/membership and onboarding email
job atomically. It accepts at most two trial accounts and never starts a cell or
sends mail from this command. Configure SMTP, then the separate approved mail
worker delivers the single-use code. Customer chooses a validated password.
Existing sign-in/recovery/MFA/revocation boundaries apply unchanged.

Signed-in users visit /account/requests/ or GET/POST /v1/requests. POST accepts
only message (1–16000 characters) and idempotency key. At most three waiting
requests/account; changed-payload reuse fails. GET /v1/requests/{id} and POST
/v1/requests/{id}/cancel always check account membership and object ownership.
Messages/results are escaped on the page; raw body/native secrets never enter
logs. FIFO sequence, other users' messages/account IDs and worker credentials
are not returned. Cancel waiting work immediately; running/starting/uncertain
work only records cancellation intent until an adapter confirms the outcome.

## Worker boundary

RequestQueue.run_once accepts a trusted host adapter. Preflight must verify its
host-owned registry, isolation, capacity/price/budget readiness. After the atomic
claim, it must repeat account authorization, create/admit the task with the same
ID as request_id, and reserve all provider-route costs BEFORE wake/model effects.
It uses the account/project-native binding, observes native acknowledgement and
calls heartbeat before every new step and frequently during long stages. Heartbeat
returns cancellation intent, including revocation/suspension. Native abort/drain
must be confirmed; no UI status change alone proves cancellation.

The global slot remains held across starting/running/unknown outcomes, restarts
and lease expiration. An expired lease is never auto-requeued. Reconciliation
reads the existing native receipt; it never repeats send/effects. Completion
requires a target/fence-bound terminal receipt, public result, native/worker
quiescence, stopped lifecycle slot and settled known task reservation. Only then
can the next account's request acquire the slot. Lifecycle claims for another
account also wait while a request owns the global slot.

The native execution adapter is still DisabledRequestDriver; no fixture driver
is shipped in the worker entry point. `manage.py request_worker --check` shows
aggregate counts only; --once refuses native dispatch. Protocol-level fixtures
prove scheduling/ownership/races, not container isolation or a real agent task.
Native budget/lifecycle/worker adapter remains required to actually process saved
requests. No price/service-capacity assertion is accepted from the browser.

## Vercel publication

See deploy/vercel/README.md. Vercel can publish a setup page without a backend
address. Set Production BACKEND_ORIGIN to connect the fixed customer routes.
Vercel serves the shared customer origin via fixed
external rewrites to HTTPS on the existing VPS. SQLite/agent/task worker stays
on the VPS. No Gateway/control socket is published. Set the exact Vercel production
origin for secure cookies, links and CSRF; verify actual cookie forwarding and
no-store caching before invitations. Vercel CLI was initially logged out;
project access and backend HTTPS were subsequently configured for getlumina.pro.
Live login/cookie/CSRF/routing checks pass through that origin. Verified SMTP
and first-invitation email are still missing. No temporary unclaimed deployment or live identity was created.

New migration: SQL0004 + Django0008. Explicit private bootstrap before code cutover;
back up existing metadata using SQLite backup, preserve reservations/queued work,
and refuse older binaries on the extended schema. The fresh VPS metadata database was initialized and the private account app
installed on loopback18800 under a separate identity with a 128 MiB cap. No
execution worker, customer mail or Vercel deployment was activated. Deployment
readback is recorded in plans/product/serial-backend-deployment.json and
serial-backend-verification.json. The owner Gateway was not modified.
