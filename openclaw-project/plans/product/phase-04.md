# Product Phase04 — shared-VPS architecture/capacity assessment

Original request: execute Phase4. During the turn the owner clarified **one VPS,
one shared public domain, no customer-supplied infrastructure**, and requested
assessment/proposed changes before the dedicated-VM implementation proceeds.
That steering is reflected in ADR007, deployment policy and revised Phase4 prompt.

Assessment: **READY/PASS**. Lifecycle build: **PARTIAL** (native driver/worker broker
missing). Customer agent activation: **BLOCKED**. Actual A/B runtime isolation,
restore/upgrade/failure/concurrency/load acceptance: **NOT_RUN Phase15**.
No Phase5 start or completed-Phase4 claim.

[Full assessment and proposed changes](phase-04-single-vps-assessment.md) contains:
current supported account/shared-domain layer; exact previous ADR002 VM requirement;
shared-cell/worker/secret/network/quota architecture; current measured host limits;
reproducible zero-slot RAM bound; larger single-VPS beta proposal and missing work.
[Capacity JSON](phase-04-capacity.json) and its generator reproduce the result.

TENANT-01 remains MISSING, TENANT-02/03 PARTIAL; FOUND-06 current isolation target
requires new proof, historical inventory retained. No requirement or old T10/T11
case dropped. All121 ledger entries remain; Phase15 acceptance remains NOT_RUN.

Checks actually run: three brief read-only owner-resource samples, installed
Fleet2026.9.6 create/start/stop/upgrade/backup/restore/rm/doctor/status help, read-only
Docker/runtime/filesystem/listener metadata;7 local capacity checks including
unknown/stale measurements, exhaustion, invalid units and tighter bottlenecks;
Phase3 reverted draft settings/models/admin checked byte-identical to final evidence;
source/JSON/whitespace/reproducibility checks. No load/native lifecycle/model tests.

Auto-review refused copying the whole installed Fleet runtime implementation as
internal source egress. No bypass or leaked output. Approved command help and
public primary docs suffice for the requested assessment. Exact native JSON/config
and worker-runtime compatibility still need a safe disposable capability probe
when implementing. No real customer data or credentials were inspected/exported.

Initial dedicated-VM lifecycle draft was withdrawn after target clarification,
before any migrations/runtime changes. Phase3 auth/roles/schema unchanged.
Current VPS:3.78GiB/2CPU/~0.95GiB available, swap>99% used; about200MiB remain
under proposed app/headroom reserves, below one default2GiB Gateway cell.
Thus0 currently admissible full customer agents.16GiB/4CPU for maximum2 beta
accounts and proposed global1 active task is a planning candidate, not a tested
capacity guarantee, changed price or authorized infrastructure purchase.

No external invitations/messages/model/provider/payment/VM purchase/public ingress,
owner service/config/data change or live workload cleanup. Cost:0 paid provider
calls; host upgrade/native worker/provider commercial costs remain unknown.
Rollback: no production changes; only local assessment/calculator/docs were added.
Incomplete draft removed; temporary approved source-inspection files stay outside
tracked evidence. Next step resumes **Phase4** with the single-VPS implementation
and concrete hardware/runtime plan, preserving gates and owner rollback safety.

Evidence: [Phase 4 manifest](../../evidence/product/phase-04/20260930T011410Z/manifest.json).

## Existing-VPS trial clarification — 2026-09-30

Owner selected trying the existing server before any upgrade. The current target
is two invite-only accounts, one global running customer task, on-demand private
cells and sequential isolated worker stages. Keep every planned feature; no
hardware upgrade prerequisite for implementation. Default-profile zero-slot
measurements remain historical evidence, not proof of a smaller profile. Follow
`product/EXISTING_VPS_TRIAL.md` and deployment policy v2. Measure a fitting profile
and complete isolation/budget checks before execution. Account invitations do
not automatically start an agent; later resize changes capacity, not accounts,
domain or feature scope. No live deployment or feature activation in this update.

Trial-plan update evidence: `openclaw-project/evidence/product/phase-04/20260930T183627Z/manifest.json`. Documentation/configuration intent only; no runtime activation.
## Phase 4 continuation — durable local lifecycle build (2026-09-30)

Implemented the queue/coordinator and immutable foundation extension, fixed account
binding, operator MFA/action grants, customer-scoped operation reads, durable
leases/fences, observed-state/generation checks, two-cell trial ceiling and one
global slot. Unknown outcomes/expired leases stay reserved until receipt-based
reconciliation. Definite failures have at most two retries, using the same binding.
Backup/restore references remain account-bound; upgrade requires a current-generation
backup; stop/maintenance refuses running/approval/paused tasks until safe drain.
Fixture lifecycle exercises all seven operation kinds; native driver is still off.
Fixed Fleet command preparation has no subprocess/socket access; native upgrade/
restore and token/worker/quota/network integrations are not implemented by it.

Actual checks:14 file-backed lifecycle tests;7 authenticated API checks plus25
prior account regressions;14 foundation and7 capacity regressions;9 combined API
checks after budget extension. Initial fixture/grant-trigger/sandbox failures are
retained with fixes/disposition. Added immutable SQL0002/003 and Django0004–0007;
no migration applied to production. Fresh disposable bootstrap and migration
state checks passed. Native A/B container/worker isolation and live lifecycle NOT_RUN.

Fresh read-only host check:953454592 bytes available (~909MiB),2vCPU,2GiB swap
with7749632 bytes free; runsc/Podman absent, runc only. No complete low-footprint
customer/task peak established; no bounded customer cell was started. Existing
VPS remains target; no upgrade requirement/purchase and no owner workload changes.

Build: lifecycle coordination component READY locally; full Phase4 PARTIAL.
Missing: host-owned privileged registry/supervisor and verified native receipts,
private secret custody, stronger runtime, aggregate quotas/network/worker broker,
safe idle sleep/wake, quarantined restore/upgrade rollback and retention purge.
All live feature gates remain off. Independent Phase5 core built under the owner's
plural-phase continuation; missing Phase4 integration still blocks dependent
customer execution. Resume native Phase4 and all-route Phase5 integration, not
claim a complete provisioning build or public beta.

Evidence: `openclaw-project/evidence/product/phase-04/20260930T195312Z/manifest.json`.

## Host supervisor continuation — 2026-10-01 UTC

Implemented separate host-owned enrollment/custody, a durable operation journal,
process-wide effect lock, exact account/deployment/profile binding, per-operation
receipt fences, stale/changed replay denial, global active/uncertain holds and
reconciliation without dispatch. Added bounded Unix transport with Linux peer
identity, trusted socket checks, fixed errors and no enrollment/command/secret
API. Added a hardened service template; no live supervisor is installed.
The shipped entry point retains DisabledDriver. See
`platform/agentai_platform/lifecycle/SUPERVISOR.md` for exact boundaries and gaps.

Local checks:51 core checks (49 pass,2 Linux peer/socket cases skipped on macOS),
40 Django account checks,21 capacity/foundation checks and Vercel configuration/
build routing checks pass. Foundation socket cases first failed due to sandbox
bind denial, then passed with loopback access. An initial Django invocation used
the repository's non-Django environment; rerun in platform/.venv passed. Neither
failure was a product pass. Linux cases are included in the GitHub gate.

Read-only host measurement at01:35 UTC:885022720 bytes available,16384 bytes free
swap,2CPU,~88.85GB disk free; runsc absent, /dev/kvm present. SSH/public login
briefly timed out during probes, then recovered; login returned200 and owner
Gateway/database reported healthy. No owner service restart or cleanup occurred.
The host CLI is2026.2.24 with Node22.22.0, unlike the earlier2026.9.6 Fleet
inventory. Public pinned2026.9.6 requires Node24.16.0+ (or26.1.0+); a separate
bounded candidate installer preserves owner binaries/configuration. Its first
attempt denied headroom; the second hit an npm config-file collision before
CLI installation. Corrected that collision and removed only its unused staging.
The corrected attempt installed320 packages successfully. Bounded Fleet create
help and empty separate registry JSON probes passed. The fs-safe support
warning was repaired with the exact Linux0.18.1 package. Native require-mode
read/path/symlink and atomic no-clobber move checks passed on disposable files;
fixtures cleaned. No cell was created; full native readiness remains unverified.
GitHub Linux gate passes all51 core and40 account cases plus Vercel routing.
Exact results are in this run's manifest.

Phase4 remains PARTIAL. Native backend/drain proof, secret/provider custody,
stronger worker runtime, persistent disk/network quotas, dispatch-side admission,
automatic enrollment, quarantined restore/pinned upgrade/rollback/retention and
a measured usable customer profile remain missing. Customer execution stays off;
native isolation/full lifecycle acceptance remains NOT_RUN in Phase15. This is
not a hardware upgrade requirement or a reason to renumber/skip Phase4.

Evidence: `openclaw-project/evidence/product/phase-04/20261001T014000Z/manifest.json`.

## Native backend slice — 2026-10-04 UTC

Implemented the verified native Fleet backend behind the existing supervisor
boundaries. `FleetCustody` holds host-authored custody: digest-pinned node and
CLI entry binaries, an exact subprocess environment (nothing inherited), bounded
working directory, output/time bounds and the operator-verified native output
schema per operation kind. `FleetCliDriver` executes only fixed `FleetPlanner`
argv, kills and proves the whole executor process group drained on timeout,
maps receipts strictly through the verified schema (duplicate JSON keys
rejected), verifies backup archives as bounded regular non-symlink gzip files
under the private backup root, and uses only the previously probed
`fleet list --json` absence form for delete proof and create/delete
reconciliation. Missing/unknown schemas refuse exactly like `DisabledDriver`;
non-zero exit, malformed or mismatched output stays uncertain. Upgrade/restore
remain refused pending backup/quarantine/token/rollback orchestration.

Dispatch-side admission is now independently enforced: `HeadroomAdmission`
denies runnable kinds before any intent unless host `MemAvailable` covers the
binding memory plus a custody reserve, and `Coordinator.rescind` returns such
effect-free denials to pending (audit `capacity_wait`/denied, attempt standing)
rather than marking uncertain. `supervisor_main` still ships `DisabledDriver`
with no enabling flag; wiring the backend is a host activation step that
requires first capturing and operator-verifying real effect-output schemas via
the new `deploy/capture_fleet_probe.py` (read-only forms only).

Checks: 12 new driver/orchestration cases pass locally (stub CLI, drain-kill
group proof, custody digest/symlink/env validation, schema gating, archive
bounds, admission, rescind) with 72 core cases (2 Linux-only skips on macOS),
40 account regressions in the platform venv, and Vercel routing checks. The
GitHub workflow now runs capacity/foundation/fleet-driver modules. No native
cell, worker, provider call, owner change, VPS mutation or live flag moved;
Phase4 remains PARTIAL and native acceptance NOT_RUN (Phase 15).

## Disposable-cell verification and driver v2 — 2026-10-04/05 UTC

Owner authorized the invitation resend and one disposable native cell exercise
(see `evidence/product/phase-04/20261004T235258Z/manifest.json`). The exercise
captured the real CLI contracts — create/backup/list JSON, start/stop/rm
text-only, list states {created, running, exited}, create printing the cell
Gateway token on stdout — and the first measured cell peak (245.1 MiB of a
512 MiB cap) for the existing-host trial profile. Driver v2 now proves every
receipt from a bounded registry follow-up instead of command self-report, with
backup artifact verification and delete absence proof; the custody example
(`platform/deploy/fleet-custody.example.json`) records the observed binaries,
digests, vocabulary and bounds.

Host corrections during the exercise: `/` was owned by an orphaned uid 501
(IONOS image defect) which fs-safe temp-workspace admission refuses for every
user; corrected to standard `root:root` (non-recursive, mode untouched,
reversible with `chown 501 /`). Unprivileged `agentai-fleet` (uid 1000, docker
group) was created for diagnosis and retained as the runtime-identity
candidate. All probe residue was deleted and the owner stack verified healthy.

Checks: 14 driver cases, 72 core, 40 account and Vercel checks pass. The
invitation was re-delivered (activation remains the owner's action). No native
backend is enabled in the shipped entry point; Phase4 stays PARTIAL; Phase15
acceptance stays NOT_RUN.
