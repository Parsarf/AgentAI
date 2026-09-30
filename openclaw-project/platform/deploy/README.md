# Private foundation deployment and rollback

The current owner services/state/Compose/credentials are untouched. This bundle
uses a new `/opt/agentai-platform` release and private metadata root. Customer
capabilities are hard-disabled by config validation. No cloud/identity/billing/
Gateway keys are needed. Phase 2 smoke may use temporary unprivileged systemd
units with the same limits, stopped after observation; that is not production
customer activation.

## Prepare an immutable release

1. Hash the source, migration, runtime manifest/config and test report. Copy only
   `agentai_platform/`, `migrations/`, config and versioned non-secret manifests.
   Exclude data/tests fixtures/caches/local `.env`/owner state.
2. Use a dedicated unprivileged `agentai-platform` user (no sudo/Docker group),
   root-owned immutable code, state owned by that user mode0700/files0600.
   The disabled control skeleton currently shares metadata identity but has no
   privileged driver/secret. Before Phase 4 activation separate control/supervisor
   service identities/credentials; app metadata write access cannot be treated
   as authorization for a privileged operation.
3. Copy server config with absolute private state path and loopback ports18800/
   18801. Verify ports unused and sufficient headroom. Back up an existing app
   DB with SQLite's supported backup API, not a live WAL-file copy.
4. As the unprivileged user, run `python3 -m agentai_platform.server --config
   /etc/agentai-platform/config.json --service app --migrate --check` from the
   release directory. Explicit migrations; no implicit destructive bootstrap.
5. Only for an authorized private deployment, install the two reviewed systemd
   units, start without public ingress, check health/readiness and `/v1/projects`
   denial, resource properties and listener addresses. Resource ceilings per
   service:128MiB/no swap/25% CPU/16 tasks. Do not alter owner units or cron jobs.
6. Observations must show foundation_ready true and customer_ready false; then
   record tested release hash/runtime/SQLite version. No paid smoke is required.

The stdlib HTTP preview is not a public production edge. Phase 3 must select
production HTTP/identity, Phase 4 privileged driver and Phase 5 budget admission.
Future TLS terminates at the approved customer edge and routes only the app.
Control/Gateway/proxy/database never receive public listener/DNS paths.

## Rollback

Stop only the two platform units. If schema matches previous release's immutable
migration hashes, restore the previous code pointer/config, check then restart.
If schema is newer/incompatible, refuse binary downgrade; restore a verified
backup into a fresh isolated state root, reconcile current access/tombstones/
usage and approve cutover. Never overwrite proxy budget DB or native state.
For a temporary Phase2 smoke, stop/remove only the temporary units/directories
created by that run; retain evidence. No customer data exists in this foundation.

## Phase 3 application replacement (prepared, not deployed)

The app unit now runs the pinned Gunicorn WSGI account application. Control stays
on the disabled stdlib skeleton. Package also `accounts/`, `manage.py`, immutable
Django migrations, `requirements.lock` and `deploy/gunicorn.conf.py`. Create the
release venv and install with `pip install --require-hashes -r requirements.lock`.
Supply `accounts.env` privately from the reviewed example; never copy local
owner `.env` or a filled secrets file into an archive/evidence. Root-owned code,
static unprivileged state identity and the128MiB/no-swap/25%CPU/16-task unit caps
are retained. New Django/Gunicorn limits have passed local startup only; server
memory envelope/reverse-proxy isolation must be measured before installation.

Run `.venv/bin/python manage.py bootstrap_accounts` as the state identity with
private settings. Existing foundation migrations remain immutable. Back up an
existing DB through SQLite backup before migrating. WSGI startup refuses missing
or newer Django migrations; old Phase2 code is not an approved customer auth
rollback because it lacks this boundary. Stop the app, restore a consistent
pre-change snapshot into an isolated root and reconcile sessions/epochs/tombstones
before any authorized cutover. Never mix restored identities with newer access
state; force reauthentication after recovery/key rotation.

Host-only `manage.py account_admin create-account --account <opaque-id>` creates
an audited account. `operator --email <internal-email>` requires a private terminal
for password/TOTP confirmation and grants **no** customer access. `grant --account
<id> --email <operator-email> --permission <invite|suspend|revoke|audit>` issues a
one-hour scoped grant. `invite --account <id> --email <customer-email>` generates
verified onboarding instructions; do not run real invites/messages without
explicit authorization. No real identity was created during Phase3.

Enable SMTP only after authorized sender/provider setup; configure credentials
server-side, verify TLS/domain and send a designated test inbox before enabling
mail jobs. `deliver_account_mail` sends ≤10 pending jobs per invocation, never
retries running/uncertain jobs. Run under a separate restricted mail worker when
activated; inspect only sanitized states. Customer content/code is never logged.
Schedule `retention_accounts` every15min under restricted host custody and alert
on failures; schedule actual native/artifact erasure only once respective adapters
and restore tombstone checks exist. No schedule/worker was installed this phase.

The commented Caddy example overwrites scheme/client-IP headers. Gunicorn must
remain loopback-only; no public route is authorized by installing these files.
Check cookies/CSRF/origin/login/MFA/receipt delivery against actual TLS proxy in
Phase15, and verify app plus worker RAM before beta. Customer execution remains
disabled despite a successful sign-in. No Gateway/provider/SSH secrets enter app.

## Phase4/5 local continuation — 2026-09-30

Durable lifecycle metadata/coordinator and offline budget reservation/receipt core
are implemented, with scoped operation/usage read views and fixed MFA operator
queue routes. See platform/agentai_platform/lifecycle/README.md and platform/BUDGET.md
(paths relative to openclaw-project). Native lifecycle/worker dispatch, secrets,
stronger-runtime/quotas/network isolation, real route accounting and a fitting
existing-host profile remain incomplete; runtime/customer/payment/mail gates stay
off. No live migration or listener installed. Package new immutable SQL002/003
and Django004–007 with the release; explicit private bootstrap is required and
old releases reject the newer schema. Host-only lifecycle_status reads counts;
seed_trial prepares one seven-day/$1 entitlement without resetting one already
present. No account or invitation was created. Continue Phase4 native integration
and Phase5 provider enforcement before dependent chat activation.
