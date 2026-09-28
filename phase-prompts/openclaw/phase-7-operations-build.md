# Phase 7 — Build operations, recovery and remaining runtime support

Build phase 1 of the remaining sequence. Finish the required implementation
before running the combined acceptance suite. Read the
[execution contract](execution-contract.md), [phase index](README.md), current
`openclaw-project/BUILD_LOG.md`, architecture, runbook and Phase 4–6 evidence.
Earlier gates remain unpassed; owner explicitly authorized build-first work.
Do not demand those deferred suites before independent implementation.

## Required result

A maintainable operations/recovery setup, a runnable but unexecuted evaluation
harness, and an accurate inventory of remaining implementation gaps. Keep
OpenClaw as the sole runtime on the existing VPS. Account connections remain
owner-deferred; preserve the Phase 6 connection base and native tool manager.
Do not repeat onboarding, rebuild the old Python application or connect new
accounts merely to make the implementation appear complete.

## 1. Resolve actual build gaps

Inventory installed versions, private deployment paths, existing jobs, resource
headroom, tools, authorization and credential presence without printing values.
Separate missing implementation from checks that simply have not run.

Create `plans/remaining-build-items.md` with requirement, existing evidence,
implementation gap, chosen supported native mechanism, dependencies, status
and later test case. In particular inspect:

- Native coding/browser worker setup and the independent ACP reviewer path;
  implement missing supported configuration/isolation and review procedure.
  Existing build/debugging evidence can be reused; do not run a paid review.
- Memory, native goals/tasks, cancellation and recovery conventions. Configure
  supported durable workflow/controller support where required and available;
  persist receipts/checkpoints without creating a second scheduler/agent loop.
  Clearly distinguish owner-driven goal resume from autonomous execution.
- Scheduler limitations and intended admission boundaries. Do not invent a
  concurrency setting, patch the runtime or claim exactly-once effects.
- Disabled integration definitions, connector manager and protected sign-in
  instructions. Live account setup is deferred by the owner; no new tokens,
  broad scopes, provider drafts or account-content reads for this phase.

Finish independent supported work. Missing credentials or an unsupported
native feature block only the dependent activation; deliver its concrete
config/code/connection instructions and continue other build items. Record
material capability gaps honestly instead of labeling them testing gaps.

## 2. Implement backup and recovery operations

Check current installed-version official docs for
[backup/restore](https://docs.openclaw.ai/cli/backup),
[upgrades](https://docs.openclaw.ai/install/updating),
[security](https://docs.openclaw.ai/gateway/security) and native diagnostics.
Inventory config/state/workspaces, protected auth, plugin dependencies,
Compose/image versions, LiteLLM config/budget database and external secrets.
Use supported consistency-aware native archives and database backup commands;
a running-database filesystem copy is not automatically a valid backup.
Preserve spend history/key identity so recovery cannot silently reset caps.

Implement:

1. A versioned operator backup entry point using native commands, with private
   permissions, bounded retention, failure exit codes and archive verification.
2. A supported timer/schedule, separate from ordinary agent authority. Preserve
   existing jobs. Enable only a bounded operator backup whose paths, retention,
   permissions and commands pass lightweight setup checks; leave destructive
   pruning or uncertain jobs disabled. No model calls or outbound notifications.
3. Freshness/health reporting using observed timestamps and truthful unknown/
   stale/error states. Prepare alerts through already-authorized destinations
   only; absent delivery authority means a local status/report, not new messages.
4. Isolated restore/rollback entry points and a runbook. A restored clone must
   disable channel polling, delivery, schedules and queued effects before start,
   and use distinct paths/ports/database. Never overwrite live state for a drill.
5. Private encrypted off-host retention only when an approved destination and
   key-custody mechanism exist. Otherwise prepare that connection and report
   off-host retention pending; do not add a new paid storage account.

Record RPO 24 hours/RTO 30 minutes as proposed initial targets unless the owner
already chose others. Measuring recovery, running the isolated restore and
observing a scheduled backup belong to Phase 10, not this build phase.
A bounded initial native backup/archive verification may be a free deployment
safeguard; it does not prove restoration. Preserve existing recovery archives.
Legacy AgentAI code was already retired by owner direction; do not recreate it
or delete any database as part of operations setup.

## 3. Build the evaluation harness without running the suite

Create a small versioned `evals/` runner around supported native interfaces,
with exact setup/run/cleanup commands and disabled-by-default paid execution.
Define fixtures/assertions before evaluation. Each case records ID, capability,
setup/input/seed where supported, expected assertions, forbidden effects,
evidence oracle, timeout/retry bound, cost allocation and cleanup.

Prepare cases for all earlier deferred gates: owner access, approvals,
research/injection, native coding/browser/independent review, selective memory,
correction/deletion, durable resume/cancellation, scheduling, integration auth
and fail-closed budgets. Also prepare operations/restore/rollback cases.
Dashboard cases are added in Phase 8; browser optimization cases in Phase 9.
Keep fixtures synthetic and isolated. Required-but-unavailable services are
BLOCKED when tested; deliberately owner-deferred connections remain explicitly
disconnected. Do not silently shrink acceptance scope after a failure.

No reasoning/model probes, attack runs, provider reads, restore drill, load
suite or autonomous objective is launched here. An executable test runner is
an implementation artifact; actual results are produced after all build phases.

## 4. Lightweight setup checks and delivery

Check source syntax, dependencies/lockfiles, config schema/dry-run and exact
readback, changed listeners/health and secret-safe artifacts. Use inexpensive
static secrets/security checks for changed boundaries. General Doctor may
migrate/lock state: defer a heavy or disruptive run and record why.
Never count skipped checks as passes or spend on agent demonstrations.

Produce `plans/phase-7.md`, remaining-build-items inventory, operations scripts/
timer config, `evals/README.md`, runner/case definitions, updated architecture/
runbook and `evidence/phase-7/<UTC-run-id>/` manifest/summary.
Build status: READY if the required build artifacts are delivered; PARTIAL or
BLOCKED for actual missing implementation. Acceptance status: DEFERRED to
Phase 10. A READY build is not a claim of verified autonomous recovery.
Stop after this phase unless later phases are already authorized. Next build:
[Phase 8 dashboard](phase-8-dashboard-build.md).
