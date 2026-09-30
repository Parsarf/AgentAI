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
