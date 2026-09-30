# Lifecycle coordination — Phase 4 continuation

Implemented locally: immutable schema extension, one deployment binding per
account, two-cell trial ceiling, fixed create/start/stop/backup/restore/upgrade/
delete requests, scoped operator queue API and customer operation reads.
Requests contain operation kind, idempotency key, expected generation, allowed
profile revision and account-owned backup reference. No shell/path/URL/token/image
or client deployment choice. MFA/grant checks precede queueing; grant/account
status is rechecked inside the write transaction.

`Coordinator.run(driver, account, operation, capacity=...)` is the worker core.
Runtime effects happen after atomic lease/global-slot acquisition, outside the
metadata transaction. Current driver is `DisabledDriver`; no background worker
or privileged service was installed. `manage.py lifecycle_status` reads sanitized
counts only. Stop/maintenance needs drained task state; runtime receipts must also
prove quiescence. A current-generation backup precedes upgrade. Restore references
an account-bound backup/profile and ends stopped with a new generation.

Lost responses/expired leases keep the operation, observed cell and global slot
uncertain. Do not automatically clear a stale lease or retry an unknown effect.
Reconciliation requires a trusted target-bound receipt; otherwise the slot remains
held. Definite non-effects may be retried at most twice after the first attempt,
with the same deployment identity and idempotency record. Every local mutation
and audit commit together. Delete removes the runtime only; data purge/secret
revocation and retention/tombstone orchestration remain native integration work.

The file-backed driver exists only under tests. It demonstrates durable metadata
and receipt handling, not OS containers, real secrets or runtime isolation.
`FleetPlanner` prepares fixed commands from a host-owned binding registry; it
never executes them. It does not implement native output decoding, token custody,
stronger-runtime setup, filesystem quotas, egress or project-only worker dispatch.
Native upgrade/restore plans are refused pending backup/quarantine/token/rollback
orchestration. Do not run a plan directly from the web application.

## Prepared API

- `GET /v1/operations[/{operation_id}]`: current customer account only.
- `POST /internal/accounts/{account}/deployment/operations`: verified operator,
  confirmed MFA, unexpired `lifecycle_<kind>` grant for that exact account.
- `POST /internal/accounts/{account}/deployment/operations/{id}/retry`: same scope;
  only a definitively failed, retry-safe operation within the retry limit.

POST fields are strings under the existing strict JSON/form boundary. Generation
is required for every action except create; request fields selecting native
locations, credentials, commands or resources are rejected. Native execution and
customer task access remain false even after a successful 202 queue response.

## Remaining live implementation

A separate host-owned supervisor must independently validate its tenant/port/
image/profile registry rather than granting root authority to app DB rows. It
must serialize native mutations and prove an old executor is no longer able to
effect a target before producing a retry-safe receipt. Prepare supported Fleet
JSON/schema probes and private token handling; complete aggregate cgroup/volume/
network policy and the coding/browser/reviewer worker broker. Use verified stage
peaks and Phase 5 route admission before wake or dispatch. Safe idle sleep/wake,
restore quarantine, credential rotation/revocation and scoped rollback must be
wired to real native mechanisms. Current host measurement is insufficient for a
complete trial task; keep developing against the existing VPS target without
assuming an upgrade or an empty Gateway estimate fixes these missing pieces.
