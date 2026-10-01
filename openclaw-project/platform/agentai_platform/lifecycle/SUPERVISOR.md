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

## Native activation work remaining (Phase 4)

Verify a separately configured native Fleet CLI and exact installed schemas,
without loading or modifying owner configuration. Add independently enforced
capacity admission at dispatch, credential custody, subprocess lifetime/drain
proof and private native receipts. Implement stronger runtime/worker broker,
per-tenant effective identities, state/artifact disk quotas and network policy.
Implement pinned upgrade/rollback and quarantined restore/revocation/retention.
Integrate all-route provider budget admission before any paid or task effect.
Measure a usable sleeping/wake/task/stage profile on the existing VPS.

No native backend has been enabled or proven by these orchestration tests.
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
