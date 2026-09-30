# Customer platform foundation — ADR 001–005

2026-09-29, v0.1.0. Phase 2 foundation, customer activation disabled.

## ADR 001 — Native runtime with a separate product control plane

```
customer browser / one customer Telegram ingress
  → production identity + application API (Phase 3/6/7)
  → authenticated account/project/task ownership + entitlement/reservation
  → internally mapped private Gateway in that customer's VM
  → restricted native researcher/browser/critic/builder/reviewer

application lifecycle request → authenticated fixed control API
  → durable operation/receipt (Phase 4)
  → trusted VM/node supervisor → private customer deployment
```

Neither browser nor app receives raw Gateway credentials, cloud lifecycle
credentials, Docker socket or arbitrary shell/native RPC. A tenant VM trust
boundary includes its Gateway operator authority: a Gateway compromise must
not obtain other tenants' state. Provisioning/admin credentials reside only
in a narrow future supervisor, not the current skeleton. Fixed request schema
selects server-owned deployment IDs/generations, never paths/commands/URLs.

OpenClaw continues native loop/sessions/approvals/memory/schedules. Product
services own accounts/mappings/projects/events/artifact metadata/usage/entitlements/
billing inbox/outbox. A durable operation worker is lifecycle orchestration,
not a second agent scheduler. Existing owner runtime/dashboard remains separate.

## ADR 002 — Dedicated customer VM boundary (superseded target by ADR007)

Mutually untrusted hosted customers are placed on separate VMs/private node
identities, networks, state, workspaces, secrets and provider keys/budgets.
The current owner host admits no customer nodes. This chooses a stronger
boundary than merely two containers on the owner's Docker daemon. Native
Fleet is advertised by the installed CLI but experimental and host-local;
we will evaluate it as a supervisor implementation within a tenant VM, not
assume it supplies remote fleet provisioning or hostile shared-host isolation.

Control-plane compromise remains a high-impact trusted-operator threat. Use
narrow service identities, fixed operations, audit, key rotation, separated
recovery custody and deny broad customer-provided mounts/environment/image/
commands. Provider budgets backstop a tenant compromise. Customer code never
receives Gateway/provider auth stores or Docker management endpoints. Native
Codex/ACP must have actually enforced project-only execution, including any
host-side harness. Owner saved subscriptions are not provisioned to customers.

## ADR 003 — Small dedicated metadata database

Use dedicated SQLite WAL with synchronous FULL, bounded writer wait and
composite `(account_id, related_id...)` foreign keys in foundation v0.1.0.
One metadata node, small beta only; the existing proxy PostgreSQL/spend DB
is untouched. This reuses Python/SQLite operational experience and avoids
new package/infrastructure setup on the current memory-constrained host.
Repository methods require a verified Principal and recheck active membership/
account on each read. Customer read scope is fixed SQL; admin/support will
need explicit methods/scopes later, never a bypass flag.

Transactions/checksummed immutable migrations apply explicitly before startup.
Unknown newer schema or edited migration blocks readiness. Audit/usage tables
have append-only triggers. These are not immune to a host administrator with
file access; retention/archive jobs need a reviewed administrative migration.
Future reservations/operations use short atomic claims; external network calls
stay outside locks. Lifecycle generation/idempotency uniqueness is scaffolded,
not a completed reservation/provisioning implementation. No application keys
or native agent transcript/state blobs are stored in this database.

SQLite has no per-request row-level security: repository scoping and composite
FKs are required. Shared file access means a compromised trusted app could
read all metadata; it cannot be represented as hostile-tenant execution
isolation. No customer code runs in that process. Before horizontal writers or
measured bottleneck, migrate metadata to a dedicated PostgreSQL database with
least-privilege app/control roles and tenant policies; do not share proxy tables.

## ADR 004 — Private transport and identity seam

Two bounded stdlib HTTP skeletons on 127.0.0.1:18800/18801, no external Python
packages. Dependency manifest explicitly records zero external dependencies
and observed Python/SQLite versions; OS security patch policy remains necessary.
This transport is for private foundation checks only. Phase 3 selects a
maintained production HTTP/identity component before any public customer route.
There is no custom login implementation, header-based identity, debug token or
“trust proxy user” fallback. Default verifier denies all `/v1/*` requests.
Test-only fixture verifier is injected in disposable tests, not configurable
through HTTP/environment/config. Existing owner login code is not reused as
customer identity. Internal control authentication is separately required in
Phase 4; until then control mutations cannot execute.

Health = process alive, readiness = metadata schema/integrity present. Response
always distinguishes foundation_ready and customer_ready:false. Bounded
connections/socket timeouts, strict host/origin and request-size validation,
no-store/CSP/nosniff, server-generated request IDs and fixed-field redacted
metadata logs. No request headers/body/query/native error content is logged.
This does not claim production auth, TLS, billing or chat readiness.

## ADR 005 — Gates, API/version contracts and recoverable release

Config rejects all customer activation gates in this build, even if set true.
Every future capability requires explicit supported adapter, correct authority,
resource admission and phase proof before its gate is enabled. Native protocol
candidate is v3; CLI/source advertisement is separate from an authenticated
live adapter probe. Capability fixture starts all send/history/events/abort
fields false/live_probed false. A client cannot set that fixture or native URLs.

Deploy non-secret release into an isolated path using unprivileged user/private
state and resource limits; never alter owner Compose or mounted credentials.
Keep all listener publication loopback-only. Future approved TLS edge routes
only customer app; neither control nor native Gateway gets a public route.
A binary rollback checks DB migration compatibility; schema changes prefer
expand/contract. Back up metadata/native state separately using consistency-aware
methods. New app DB does not replace proxy spend history or customer-native
backups. Recovery replays deletion tombstones/current entitlement and receipt
reconciliation before channels/jobs can act.

References: [OpenClaw tenant boundaries](https://docs.openclaw.ai/gateway/multi-tenant-hosting),
[session APIs](https://docs.openclaw.ai/gateway/protocol/rpc-session-control),
[Python SQLite](https://docs.python.org/3/library/sqlite3.html),
[composite SQLite foreign keys](https://www.sqlite.org/foreignkeys.html).

## ADR006 — maintained account transport and authentication (Phase3)

Django5.2.17 + database sessions/password/CSRF primitives, django-otp1.7.3 confirmed
TOTP for scoped operators, Gunicorn26.2.0 private WSGI. The app unit replaces the
stdlib fixture transport; control still denies all operations. All dependencies
have exact official wheel hashes. Foundation SQL migration is adopted unchanged;
Django migrations add identities/hashed action codes/audit/role grants/mail queue/
retention tombstones in the dedicated metadata DB. No owner dashboard change.

One customer binding per identity; active membership/epoch/account checked on
requests. Local effects and audits use SQLite IMMEDIATE transactions. Session
middleware must restore the pre-operation session after rollback; explicit
completion-audit failure tests exercise this boundary. Generic recovery queues
IDs/purpose only, generates raw codes in worker memory and never sends SMTP in
customer request timing. No raw token is stored in jobs, URLs or audit rows.
Operator grants last one hour, always MFA, no impersonation/export/content scope.

App/database custody is trusted, not database RLS or host-resistant immutability.
Only restricted maintenance can expire audit rows under180-day policy. Native
90-day erasure/7-day account deletion/export awaits native/file/index/restore
adapters; projection tombstones are prepared and affected routes remain off.

## ADR007 — one service-operated VPS and one public domain (Phase4 clarification)

Owner clarified the target: multiple hosted accounts on one VPS/shared domain;
customers supply no server/domain. ADR002's service-owned VM-per-customer target
is superseded. Current implementation still has a disabled lifecycle driver;
strong single-host execution isolation has not been built/accepted. See
[measured assessment](../plans/product/phase-04-single-vps-assessment.md) and
[deployment policy](../../product/deployment-policy.json).

Proposed boundary: complete private Fleet cell/account, distinct storage/secrets/
provider budgets/networks/host identities, isolated project-only worker execution,
aggregate account resource limits and separate narrow privileged supervisor.
Evaluate gVisor or equivalent for untrusted code; normal containers share a kernel
and host operator remains trusted. App owns authenticated routing and cannot
select arbitrary mounts/commands/credentials. One HTTPS app origin, one customer
Telegram ingress, no public Gateway endpoints. Per-account resource placement
must also reserve global/owner headroom and isolated restore targets.

Measured current4GiB/2CPU host admits0 added agents: ~0.95GiB available, swap>99%
used, no verified tenant peaks/stronger runtime/persistent disk quotas. Prepared
16GiB/4CPU/two-beta-account/one-global-running-task scenario is unmeasured, not a
purchase or promised capacity. No live owner change, customer cell or new ingress.

## ADR008 — existing-VPS trial before optional upgrade — 2026-09-30

Owner selected trying the existing server before any upgrade. The current target
is two invite-only accounts, one global running customer task, on-demand private
cells and sequential isolated worker stages. Keep every planned feature; no
hardware upgrade prerequisite for implementation. Default-profile zero-slot
measurements remain historical evidence, not proof of a smaller profile. Follow
`product/EXISTING_VPS_TRIAL.md` and deployment policy v2. Measure a fitting profile
and complete isolation/budget checks before execution. Account invitations do
not automatically start an agent; later resize changes capacity, not accounts,
domain or feature scope. No live deployment or feature activation in this update.

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

## ADR 008 — Vercel origin with durable VPS request queue

The owner selected Vercel for the customer website. Fixed external rewrites proxy
account HTML and APIs to an HTTPS edge on the existing VPS. Private SQLite,
identity, budget, request queue and execution workers stay on that VPS. Vercel
functions do not host SQLite or wait for tasks. Production origin, no-store
caching, forwarded Host/protocol and secure cookies require deployment checks.

A persisted FIFO request slot serializes customer work globally, including unknown
outcomes. Pending intake does not admit paid work. An execution adapter must admit
budget before any effects and confirm stopped execution plus settled reservations
before releasing the slot. Account-scoped queue/page/cancellation are implemented;
native execution remains disabled. See SERIAL_REQUESTS.md for the adapter contract.
