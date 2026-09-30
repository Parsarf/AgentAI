# Product Phase 02 — secure platform foundation

Build status: READY. Foundation gate: PASS (targeted local + actual private
server smoke). Full customer security/native/provider acceptance: NOT_RUN,
assigned to Phase15. Customer activation blocked by Phases3–5 prerequisites.

Delivered platform/ source, migrations, machine-readable metadata/OpenAPI
schemas, disabled native interfaces/fixture, locked zero-external-dependency
manifest, architecture/role/API/threat/capability matrices, config examples,
resource-bounded service units and deployment/rollback/TLS design.

Architecture: separate product app/control and account-scoped metadata;
OpenClaw sole agent runtime. Dedicated customer VMs/private identities prevent
customers sharing the owner trust boundary. Current owner deployment/proxy DB
is untouched. Dedicated SQLite WAL app metadata for one small-beta control node;
composite FK tenant/project chains and membership-required repositories; measured
horizontal-writer need triggers a separate PostgreSQL migration. App has no
Docker/cloud/native credential/command execution path. Control is hard-disabled.
Production identity/HTTP transport selection remains Phase3.

14 focused boundary checks PASS: schema/readiness/repeat/checksum/new-version,
readiness without implicit DB creation, atomic DDL rollback, cross-account/wrong-project FK denial, scoped repository/
revocation, append-only audit, real local HTTP direct ownership/forged identity
header denial, defaults/disabled mutations, origin/size denial, secret-free
request logs and unverified adapter no-dispatch. Initial local socket checks
were denied by sandbox; rerun with reviewed loopback-only permission passed.
No tests were marked passed from zero collection; final run collected14.

Actual server transient smoke PASS on Python3.12.3/SQLite3.45.1: app18800 and
control18801 loopback only, DynamicUser unprivileged, MemoryMax128MiB each/no
swap/CPU25%/TasksMax16. Both returned foundation_ready:true/customer_ready:false
and unauthenticated API401. Observed memory~14MiB/app and13MiB/control. Units,
source and empty state from the smoke were stopped/removed; no persistent
preview or public route remains. This proves startup within bounds, not tenant
load/native/task performance or permanent production activation.

Initial server smoke was a safe failed setup: private-state guard rejected the
systemd DynamicUser StateDirectory symlink, no readiness. Preserved failure
record; changed the disposable smoke to direct RuntimeDirectory state and
reran successfully. Static-user deployment instructions retain direct private
state. Migration files/source were not weakened to accept a symlinked root.

Live inventory validates existing config/version/images/listeners, installed
CLI helpers and source RPC-name presence. Presence is not a live Gateway-client
contract proof; all adapter fixture capabilities remain false until Phase6.
Historical owner caps/worker proofs are preserved, not repassed for tenants.

No paid/provider/agent/restore/load tests, owner service changes, customer
connections/messages or charges. Rollback: revert only platform/new product
records; smoke rollback already complete. Further prerequisites: maintained
identity/account layer, actual VM provisioning/boundary and all-route admission.
Next requested phase would be 3; this session stops after authorized1+2.
