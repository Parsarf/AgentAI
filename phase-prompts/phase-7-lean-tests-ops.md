# BUILD PROMPT — Phase 7: Lean verification, recovery, and deployment

> Paste this entire file into a coding session at the workspace root.

Prove the implemented service works under concurrent use, can recover its
state, and can run as one small deployment. Reuse the existing test suite and
runtime. Fix demonstrated defects; do not turn this into a platform rewrite.

## 1. Read and scope

Read the latest `BUILD_NOTES.md`, the spec's Phase 7, and acceptance outcomes
from Phases 5–6 actually used. Inspect `agent/main.py`, event bus, scheduler,
orchestrator lifecycle, test fixtures, sandbox/browser lifecycle, migrations,
requirements, and existing ops files. Inspect additional code when tests point
to it. All implementation paths below are relative to `agent/`.

Use pytest plus small scenario manifests instead of a custom YAML action
language and two-backend eval engine. Run app and bot in one process, and make
restore verification strictly disposable. Tenant/safety requirements remain.
Use evidence in the repo rather than old completion counts as proof of health.

Scope is tests, narrowly necessary bug fixes, backup/restore, container files,
load/smoke scripts, and a short runbook. Keep the stack and dependencies already
chosen. No Redis, Celery, Kubernetes, distributed event bus, tracing platform,
general benchmark framework, or speculative performance rewrite.

If Phase 6 lacks a verified provider, test that purchases are disabled and all
denial paths hold. Report core-service readiness separately from full seven-
phase completion; do not manufacture a passing payment success test.

## 2. Make test execution safe and cheap first

The current `tests/conftest.py` drops/recreates a schema and truncates users.
Before running it, add/verify a guard requiring an explicitly disposable test
database, checked against the application database after DSN normalization.
Use a dedicated test role restricted to test databases. Cover rejection of the
app database, URI aliases where identifiable, and missing/ambiguous targets.
Neither a `_test` substring nor a confirmation bypass alone is sufficient.
Restore/load/compose smoke scripts need equivalent target guards.

Use existing pytest fixtures, a real disposable Postgres, deterministic clocks,
and local HTTP/browser fixtures. Mock external model/provider calls at their
boundary; do not mock the identity, transaction, approval, or gate under test.
Tests must not inject context that production forgot to set. Avoid importing
torch in normal tests, per the documented fixture limitation. No pytest-xdist
against a shared schema that fixtures truncate.

Separate explicit test profiles:

- Fast/local: Python logic, real test Postgres, fake external APIs, no paid calls.
- Container: real Docker sandbox/browser isolation and compose/restart checks.
- Provider smoke: explicitly enabled, test-mode billing/payments and a tiny
  model task with a fixed budget. Never real purchases or surprise paid load.

Missing prerequisites are skips with reasons in local runs and release blockers
when the selected release profile requires them. Never report all-green while
mandatory checks were skipped. Run focused checks during fixes and the complete
relevant suite once at the end; repeat only after meaningful changes/failures.

## 3. Reuse pytest as the evaluation harness

Keep `tests/test_tasks.yaml` and `tests/trap_tests.yaml` as small validated
manifests mapping scenario IDs to explicit existing/new pytest node IDs,
severity, category, and required profile. No embedded Python, arbitrary shell,
dynamic predicates, or second fixture system. Example:

```yaml
- id: simultaneous-tenant-tasks
  test: tests/test_e2e_two_users.py::test_example  # replace with a real node
  severity: critical
  category: cross-tenant
  profile: local
```

`tests/run_evals.py` validates manifests, selects the profile, invokes pytest
once using an argument list, and derives a concise table from structured test
results (JUnit XML is sufficient). Unknown tests, malformed manifests, zero
collection, collection failures, and required skips cannot count as passes.
Exit `0` when all required scenarios passed; `1` for critical failures or
missing critical evidence; `2` for other failures/incomplete required checks.
Keep optional-profile skips visible. Unit-test selection/reporting/exit codes.

Ordinary scenarios: chat/research/code, persistent memory, scheduled job,
unchanged watcher with zero model calls, changed watcher escalation, skill
reuse, approval round-trip, billing warning/cap, hosted plan change, and
supported test-mode purchase or an explicit unavailable status.

Critical scenarios must cover:

1. Two users executing concurrently: tasks, notifications, memory, tool output,
   costs, browser sessions, vault, skills, approvals, and purchase records stay
   isolated. Forged IDs reveal neither data nor resource existence.
2. Job-mode approval floors under permissive user rules; timeout/denial, forged
   mode, replayed approval, and plan downgrade at the execution boundary.
3. Real SDK dispatch context, plan checks, and cost recording; concurrent
   reservations near cap; another user's work unaffected; duplicate metering;
   unknown billed outcomes and recovery. Include task cancellation/timeouts.
4. Real container escape probes: path traversal, symlinks, host/other-tenant
   network access, private-address/redirect browser probes, and inaccessible
   Docker control APIs. Unit-only mocks cannot prove container isolation.
5. Phase 6 denial matrix plus duplicate-charge and crash-recovery cases when
   enabled. Browser/external content cannot authorize spending or bypass caps.
6. Secret canaries across logs, model messages, tool results, task/approval rows,
   SDK transcripts, and API responses. Session profiles/backups contain
   sensitive state and must be protected, not assumed secret-free.

Fix real failures in the smallest owning module. Do not weaken assertions to
make the report green. If a scenario itself is wrong, document the evidence
and correct its expectation explicitly.

## 4. Deploy the existing process model

Create `Dockerfile`, `.dockerignore`, and `docker-compose.yml` with build context
`agent/`. Start the existing `main.py`: web, Telegram, orchestrator, and scheduler
in one process/one replica. The event bus, approvals, and concurrency controls
are in-memory today; do not split gateways or add Uvicorn workers. Document
this scale boundary instead of adding a broker. PostgreSQL is the other core
service; Stripe CLI is an optional development profile.

- Select the Python/runtime version supported by the existing pins; verify the
  SDK's CLI/runtime needs in its installed package instead of assuming Python
  alone is sufficient. Cache dependency layers, use a non-root app user, and
  build sandbox/browser images separately. No unreviewed dependency upgrades.
- Exclude `.env*` secrets, virtualenvs, logs, skills, profiles, workspaces, and
  backups from the build context. Use an explicit safe `.env.example` exception
  if needed. Inject runtime secrets; no secrets in layers or compose literals.
- Persist Postgres, skills, browser profiles, and required task state. For
  sibling containers, verify host-side bind paths and UID permissions; paths
  inside the app container are not automatically paths on the Docker host.
- Restrict resource use: global task concurrency, DB pool, sandbox/browser
  CPU/memory/PIDs, bounded logs, timeouts, and existing cleanup sweeps. Measure
  before changing defaults. Never sacrifice tenant isolation to pool browsers.
- Keep Postgres and Docker management private. Use a restricted Docker API
  access path; a proxy allowing container creation still has powerful host
  authority unless dangerous mounts/privileged options are constrained. Prove
  tenant containers cannot reach that endpoint. Never describe a read-only
  socket mount as read-only Docker API access. Record residual operator trust.
- Add inexpensive liveness/readiness checks (DB and required runtime services,
  not paid API pings), restart policy, and a documented TLS/reverse-proxy setup.
  Use a least-privilege runtime database role; reserve elevated access for
  initialization/migrations, not a permanently superuser app connection.
- Verify startup failure and bounded graceful shutdown. Stop admission, stop
  bot/scheduler, drain/cancel tasks within a deadline, reconcile interrupted
  money operations, and close resources. Inspect the current shutdown order:
  awaiting a running bot before stopping it must not hang shutdown.
- On restart, mark interrupted ordinary tasks honestly and notify as needed;
  do not replay actions that may have side effects. Recover durable purchase
  and billing state using their idempotent paths. Preserve scheduler semantics.

Keep ephemeral authentication throttling's reset-on-restart limitation visible;
use an existing DB-backed guard if a release test shows it is necessary. Do not
add Redis solely because an old note suggested it for multiple processes.

## 5. Back up and prove restoration without touching live data

Implement `scripts/backup.sh` and `scripts/restore.sh` with strict error handling,
quoted paths, restrictive permissions, and explicit validated target arguments.
Reuse `pg_dump`/`pg_restore`; no custom database dump format.

Back up a custom-format DB dump plus durable skills and browser profiles.
Workspaces are optional and excluded by default. Include checksums, schema/app
version, paths, and row-count metadata without secrets. Ensure the DB dump and
files describe a consistent recoverable point: for v1 use a brief documented
maintenance window that drains/stops writes, including in-flight purchases,
then takes the snapshot. Do not assert consistent row counts sampled during
concurrent writes. Failed backups must not be published as complete.

Browser profiles contain session credentials; backups are sensitive even when
vault records are encrypted. Encrypt backup bundles using an established tool
with separately managed recovery credentials before off-host storage. Exclude
`.env`, root vault keys, and backup decryption keys. Record the required vault
key/KMS identity; encrypted vault data is useless without its recovery key.
Provide a simple operator-scheduled invocation and bounded retention that
deletes only validated backup outputs after a new backup is verified.

Restore only into a newly created, explicitly disposable database and temporary
state directories. Refuse the application database, existing nonempty targets,
unsafe paths, and archive traversal/symlinks outside the restore root. Verify
checksums before restore. Compare metadata, load two users through real scoped
DB functions, exercise a restored skill and known vault canary with the
separately supplied key, and prove cross-user denial. Missing keys mean an
incomplete restore proof. Never wipe the operator's working database to test.

Execute one real disposable round-trip and automate its assertions. Record
backup size, duration, restore duration, and actual results. Include a short
restore/rollback runbook; rolling back code across a schema change is not
automatically safe.

## 6. Small load and compose smoke tests

`scripts/load_test.py` runs seeded disposable users (default 8, bounded count
and duration) through real app/DB/tool orchestration with deterministic model
and provider boundary doubles. Keep doubles test-only; never enable them via
a public production route. Default to an in-process benchmark; the compose
smoke separately verifies container wiring. Do not build two general harnesses.

Measure task throughput, p50/p95 latency, errors/refusals, DB pool pressure,
container/resource cleanup, and cross-talk. Exercise a short task mix and
scheduled jobs, including one slow user and near-cap concurrency. Clearly
label fake-provider timings as application overhead, not real model latency.
Report the baseline and fix measured regressions; no invented speedup targets.

`scripts/compose_smoke.sh` uses an isolated compose project, temporary config,
ports, and volumes: build/up → readiness → seed two users → task/isolation
checks → restart → persisted jobs/memories/usage/skills/vault → clean shutdown.
Exercise real sandbox/browser images in the container profile. Clean up only
resources the script created; never run volume deletion on the normal project.
Use one explicitly enabled budgeted model smoke if necessary for real SDK
wiring; don't multiply API spend by the load-user count.

## 7. Handoff criteria

Deliver a short runbook with exact start, test-profile, backup, restore, and
smoke commands; required environment variable names; TLS/host setup; single-
process capacity boundary; and payment availability. Append changed files,
fixes, evidence, metrics, skips/blockers, and release status to `BUILD_NOTES.md`.

Core release readiness requires all applicable critical checks, real container
isolation, a real restore, restart persistence, bounded shutdown, and load
isolation to pass. Full seven-phase completion additionally requires the
provider validations from Phases 5 and 6. If Docker, credentials, or a provider
are unavailable, deliver the finished artifacts and local checks, list the
exact outstanding commands, and mark readiness incomplete. Do not deploy to a
live host or enable live charges merely to prove the scripts work.
