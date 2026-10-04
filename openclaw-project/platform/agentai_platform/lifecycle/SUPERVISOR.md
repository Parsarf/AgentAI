# Private lifecycle supervisor

## Implemented boundary

`HostSupervisor` keeps a private database separate from Django's customer
database. A host operator enrolls an immutable `FleetBinding` using `enroll`;
the socket protocol cannot enroll or replace bindings. Account, deployment,
tenant, profile, port and pinned image come from host custody. Application
claims cannot supply commands, paths, images, environments or credentials.
Enrollment is not implemented as an automatic onboarding hook yet.

`SocketDriver` implements the coordinator Driver interface. The Unix protocol
accepts only `check`, `execute` and `reconcile`, with exact bounded schemas.
Linux peer UID authenticates a separate unprivileged controller. Socket and
parent ownership/mode checks plus peer UID authenticate the server. The
customer web user must not join the controller group. No public proxy route
or TCP listener is added.

Each effect has a committed intent and private receipt. A process lock
serializes effects across supervisor instances. Running or uncertain intents
hold the global slot after a crash; reconciliation never calls execute.
Only a matching native receipt can complete them. A definitive drained
rejection can retry the same payload with a higher attempt fence. Generations
are per deployment; fences are per operation, matching the coordinator.
Completed replay returns the original receipt without another effect.
App and supervisor both reject receipts for another account/operation/fence.

Host state checks enforce one active customer cell and require a current
host-held backup before upgrade. Restore references are account/revision
bound. Complete safe upgrade/restore orchestration is still a native backend
responsibility; these metadata checks alone do not implement it.

## Installation template

`deploy/agentai-supervisor.service` is a template, not installed on the VPS.
It expects a separate system user/group named `agentai-lifecycle-control`,
root-owned release code, private root-owned state and a root-owned socket
directory readable by that controller group. Do not give this user Docker
group membership, an owner credential, or access to the custody directory.
The web application retains its existing identity and database.

The entry point uses `DisabledDriver` deliberately. `--check` reports custody
availability separately from native execution. No configuration flag replaces
the backend with a fixture or enables native effects. The service's current
hardening permits only Unix transport and custody, not host network/worker
orchestration. Extend authority only with a verified native backend and its
boundary tests; don't broadly remove the service restrictions.

## Implemented native backend (not enabled)

`fleet_driver.FleetCliDriver` executes only the fixed `FleetPlanner` plans for a
host-enrolled binding under a pinned candidate CLI. Custody comes from a
host-authored manifest (`FleetCustody`, example `deploy/fleet-custody.example.json`):
both binaries digest-pinned, an exact subprocess environment (never inherited;
the executor's own CPython runtime may add locale keys, pinned by the boundary
test), a bounded working directory, output and wall-time bounds, the verified
`fleet list --json` state vocabulary and the operator-verified kinds.

Every receipt is proven from the registry, not the command's own text: after a
zero exit the driver runs the bounded `fleet list --json` probe (strict schema,
duplicate keys rejected) and maps `cells[].state` through the custody
vocabulary — create requires `created`→stopped, start `running`, stop/backup a
stopped state, delete requires absence. A non-zero exit, missing/mismatched
state, malformed registry output, timeout or oversized output is an uncertain
outcome, never a guess. Backup additionally verifies the archive as a bounded,
regular, non-symlink gzip file under the binding's private root; reconciliation
uses the same absence probe for create/delete only. Executor drain is the
whole-process-group kill plus a proven reaped group.

This mapping was verified against the installed 2026.9.6 candidate by an
owner-authorized disposable cell exercise (create → list `created` → start →
`running` (245 MiB measured under a 512 MiB cap) → stop → `exited` → backup
(gzip archive) → rm → registry empty). Two facts are load-bearing: start/stop/
rm emit text only, so the registry is the only state source; and `fleet create`
prints the cell Gateway token in plaintext on stdout, so captured stdout stays
in a private temp file deleted with the process and is never parsed or stored.

`HeadroomAdmission` gives `HostSupervisor` an independent host-side dispatch
bound: runnable kinds (start/upgrade/restore) require `MemAvailable` to cover
the binding memory plus a custody reserve, or dispatch is denied
(`supervisor_busy`) before any intent is written. `Coordinator.rescind`
returns such effect-free denials to `pending` (lease cleared, audit
`capacity_wait/denied`, attempt count standing) instead of poisoning the
operation as uncertain. `supervisor_main` still constructs `DisabledDriver`
and has no flag to change that: enabling the native backend means the host
operator deposits a custody manifest matching the installed candidate and
wires `FleetCliDriver` with `HeadroomAdmission` in its own reviewed change.

## Native activation work remaining (Phase 4)

The registry vocabulary and command behaviors are verified and captured in the
example custody manifest; the remaining work is provisioning the runtime
identity (home/state dirs it owns, docker-group access, the `/` ownership fix
already applied), depositing the signed custody manifest, and wiring
`FleetCliDriver` plus `HeadroomAdmission` into the installed service in a
reviewed change. Then: credential/token custody for cells (create prints the
Gateway token to stdout), task-stage wake/drain measurement, the stronger
runtime/worker broker, per-tenant effective identities, state/artifact disk
quotas and network policy, pinned upgrade/rollback, quarantined
restore/revocation/retention, and all-route provider budget admission before
any paid or task effect.

No native backend has been enabled by these tests: the disposable cell lived
entirely in the isolated candidate registry and was deleted with its artifacts.
Fixture receipts, container status and socket transport are not OS isolation
or effect-quiescence proof. Phase 4 remains PARTIAL; Phase 15 acceptance remains
NOT_RUN. Do not advance the canonical phase order on this component alone.

## Recovery and rollback

Never delete an unresolved journal row, unlock by resetting app state, or
retry a timeout as a new operation. Fence the old executor and obtain a bound
receipt proving its effects/quiescence. A restarted supervisor treats a
crash-left running intent as uncertain and blocks all new effects. If that
proof is unavailable, retain the hold and investigate privately.

Back up custody and app metadata separately with SQLite consistency and
private secret handling; off-host encrypted backup acceptance is Phase 14/15.
An unknown newer custody schema is rejected. If a stale socket survives a
crash, confirm the old server/executor has stopped before removing that socket;
startup does not silently unlink it. Rolling back this build is a source
rollback only: no live supervisor, migration or native cell was installed.
