# Phase 6 — multi-user request intake and serial queue

Status: PARTIAL. Vercel selected for the public customer origin; existing VPS
hosts account state and workers. Host-only onboard_trial creates up to two
separate seven-day/$1 trial accounts and mail jobs. Existing verified sign-in,
recovery, revocation and ownership checks remain in use. No real invitations
were created because email/SMTP are missing.

Built account-scoped request page/API, persisted FIFO queue, idempotency, three
waiting requests/account, waiting cancellation and active cancellation intent.
A durable global slot prevents simultaneous customer dispatch. Lease expiration
holds uncertainty for reconciliation without repeating native effects. Terminal
receipts require account/fence binding, confirmed quiescence, stopped lifecycle
slot and settled known reservations before the next user can start. Revocation
sets cancellation intent at heartbeat. Native driver remains disabled.

Private backend installed on VPS: fresh metadata schema, separate Linux account,
root-owned release, mode-0700 state/mode-0600 settings, loopback18800 only,
MemoryMax=128 MiB, MemorySwapMax=0, CPUQuota=25%. Missing python3.12-venv
was installed with its two wheel support packages; no packages upgraded or
removed. No customer agent, public ingress, SMTP or Vercel deployment activated.

Verification:32 core queue/lifecycle/budget tests and28 account/API regression
tests pass. Two synthetic accounts test login and direct cross-account access.
These are protocol/database tests; no real provider or isolated agent execution
is claimed. See deployment readback for private service checks.

Update 2026-10-01 UTC: Vercel project is connected at https://getlumina.pro;
backend.getlumina.pro has trusted automatic HTTPS on the existing VPS. Public
login/cookie/CSRF/no-store/anonymous denial checks pass. Routing fix625fc3e
and its GitHub workflow pass. Owner Gateway remains private and available.
See custom-domain-deployment.json and custom-domain-public-checks.json.

Update: Gmail SMTP and bounded delivery timer configured; one owner invitation
accepted by SMTP. User activation remains pending at send time.

Remaining: native agent integration and acceptance below. Native agent
adapter must prove isolation/capacity, budget admission, send/history/events,
confirmed abort/drain and public result projection. Full dashboard chat and
end-to-end serial tasks are not ready.

Rollback: stop/disable only agentai-platform-app; keep private settings and
metadata. Do not downgrade schema or reset identities/reservations. Snapshot
private SQLite before any future migration. Owner services remain separate.
