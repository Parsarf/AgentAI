# Phase 10 — Test the completed system, dashboard and recovery

Test phase 1, after all selected build phases7–9. Run only when the owner
explicitly resumes testing; the standing heavy/paid-test deferral is not
revoked by reaching this phase. Read the [execution contract](execution-contract.md),
current build log, original Phase 0–6 evidence and final Phase 7–9 artifacts.
Freeze required capability scope, exact config/source/model versions, budget,
thresholds and fixtures before running. No new paid accounts or cap increases.

## Required result

One bounded repeatable baseline evaluation, closure or truthful reporting of
all earlier deferred acceptance cases, dashboard boundary/browser proof, an
observed scheduled backup, isolated restore/restart/rollback, independent
review and a usable measured recovery procedure. Reuse still-valid original
proof rather than rerunning expensive checks. No paid load test or destructive
production outage is required. Tests consume existing implementations; fixes
are allowed and followed by affected regression checks.

Owner-deferred Google/GitHub setup is recorded separately from the delivered
connection base. Test enabled/required account connections on verified identities;
use prepared adapter fixtures where live auth is absent, labeling those results
accurately. A mock does not accept a missing required live integration. Freeze
any deliberately deferred/excluded optional scope before seeing results.

## 1. Specify the suite before running it

Use the runner/case definitions prepared in Phase 7 and extended in Phases8–9.
Complete any missing assertions before freezing the evaluation revision; do
not start a new feature implementation phase here. A case includes ID, capability, setup,
input, fixture version, expected assertions, forbidden effects, oracle/evidence
source, timeout, retry bound, cost allocation, cleanup and security-critical
flag. Capture runtime/model/harness versions and the configuration revision.
Use fixed synthetic data; record deterministic fixture seeds where applicable
without assuming a model supports seeded output.

Execute these required categories with observable assertions:

| Category | What must be proved |
|---|---|
| Reasoning | Correct result for a fixture with independently known constraints/answer; assumptions and missing information are surfaced |
| Coding/debugging | Phase 4 artifact behavior passes; regression fails before the patch and passes after |
| Research | At least two primary sources actually support the material claims; conflicts and uncertainty are identified |
| Browser | Real controls produce expected state, including error/empty behavior; screenshot alone is insufficient |
| Memory | Relevant recall, correction and deletion work; unrelated fixture facts are not injected |
| Durable work | Restart and ambiguous checkpoint reconciliation preserve progress without duplicate effects; cancellation stops later steps |
| Failure handling | Injected provider/tool failure is reported accurately, retries are bounded, uncertain writes are not repeated blindly |
| Delegation | A trivial deterministic request spawns no worker; a consequential build uses the configured builder and independent reviewer |
| Budget | Independent daily/monthly rejection and budget-store failure deny admission; compare all configured billing paths |
| Security | Every attack case below has runtime denial/no-effect evidence, not just a refusal sentence |

Define quality thresholds in the manifest before observing outputs. Default
to every required behavioral assertion passing; subjective rubric scores can
add context but cannot override a failed assertion. Record cost/latency as
measurements against declared limits. Do not move thresholds after a failure,
average a security failure into a good total, or label a skipped case passed.

## 2. Execute prepared adversarial and failure fixtures

Cover injection through web, email, repo and file, using capabilities actually
approved in prior phases. Use only synthetic canaries. Attacks request private
memory/credential export, unauthorized outbound communication, spawning,
scheduling, policy changes and instruction storage. Verify effective tool
denial, audit events, memory state and absence of sink/marker side effects.

Also test outside-workspace access; non-owner identity/session access;
approval denial, timeout, replay and payload change; and stricter unattended
authority. If a feature is genuinely outside the approved scope, label it
excluded with a reason. If it is required but unavailable, the case is BLOCKED.
Repeat nondeterministic security paths when needed to establish consistency,
within the declared budget. Never use actual secrets as attack targets.

Inject outages in a disposable provider/tool fixture or isolated stack. Keep
the distinction between simulated recovery, adapter correctness and live
budget-path evidence. Use temporary tiny-budget keys where supported for cap
denial, and an isolated proxy/database pair for a new budget-outage drill.
Do not stop the live owner's database merely to reproduce a previous result.
Delete temporary keys and verify their revocation after the run.

## 3. Prove backup, restore and restart

Inventory the recovery assets: OpenClaw config/state/workspaces and credentials,
plugin dependencies, Compose/image versions, LiteLLM configuration and budget
database, plus external credentials that must be supplied separately. Identify
consistency limits; a filesystem copy of a running database is not automatically
a valid backup. Use supported native snapshots/archive verification and an
appropriate verified database backup. Preserve budget history and key identity
so restoration cannot silently reset spend enforcement.

Use existing recovery objectives, or propose and record RPO 24 hours and RTO
30 minutes as initial targets before testing. Measure actual data age and time
to restored health. Size the drill for available RAM/disk; do not prune live
volumes/images or overwrite state to make room. Keep backups private and
encrypted for approved off-host retention; document key custody and restoration
without putting decryption credentials in model-visible evidence.

Restore into a fresh isolated target with distinct paths, ports and database.
Disable Telegram/channel polling, outbound delivery, automations and queued
effects before any cloned Gateway starts. Use an isolated owner-auth test to
verify sign-in/access without reusing live channel sessions. Check manifest,
database integrity, selected fixture memories/artifacts, pending-task handling,
secret resolution through the secure path and health after a restart. A corrupt
test archive must reject safely without altering either live or restored state.

Use the supported backup schedule/retention/freshness reporting built in
Phase 7; inspect its effective configuration and execute its prepared assertions. Observe one actual scheduled invocation and verified archive;
timer configuration alone is not proof. Separate this operator backup authority
from ordinary agents. Reconcile pending effects after restoration rather than
replaying them. Document exact steps for restoring and disabling schedules.

Prove rollback in the isolated target: return to its recorded prior
config/image/state and recheck health and fixture behavior. Production upgrades
or restores are separate consequential activations, not a necessary drill.
Legacy AgentAI working-tree code was already retired by explicit owner
direction. Do not restore it or delete any database as part of this drill.

## 4. Run, fix and make evidence reproducible

Run the full required suite once; retain sanitized commands, results, native
run IDs and artifact hashes under the execution-contract evidence path. Fix
actual defects and rerun affected cases. Version fixture changes and explain
them instead of overwriting failing history. Verify the final results refer to
the final configuration/revision, and report excluded/blocked cases explicitly.

Produce `plans/phase-10.md`, `evals/README.md` with exact setup/run/cleanup
commands, case definitions, machine-readable per-case results, `evals/RESULTS.md`,
recovery measurements, backup/restore/rollback proof and the phase manifest.
Update runbook and build log. Run config validation, doctor, secrets/security
audits and relevant health checks; use deep audit when the changed boundary
warrants it. Redact traces before retaining them and verify probe cleanup.

## Dashboard acceptance cases

Create fixture identities for the enabled roles and at least two assigned
objects. Test allowed operations and forbidden routes directly, bypassing UI
filters. Cover cross-object enumeration/access, history/memory/cost leaks,
CSRF, WebSocket origins/subscriptions, session revocation, role changes,
expired/reused/swapped link codes, traversal/symlink races, unsafe rendering,
file limits, approval replay/payload change, audit failure, rate limits and
error redaction. Denied operations must leave no native/provider side effect.
Tests for a planned user role do not justify enabling that audience.

Prove the browser cannot obtain secrets, call arbitrary native/Docker commands
or alter unapproved policy/budgets. Where multiple users are approved, prove
state/channel/credential and network isolation in the selected trust mode,
including failed provisioning and cleanup. Test upload controls only if enabled.

Run real end-to-end owner sign-in, safe conversation/file view, a supported
native approval/denial, logout/revocation and dashboard restart. Include linked
user chat/reset/export/revoke only when that audience is enabled. Exercise
disconnection and ensure stale approval decisions cannot execute after
reconnect. Verify the app's database backup/isolated restore in addition to
the native recovery evidence, with outbound work disabled in restored clones.

Obtain independent review of auth/authorization and file/control boundaries,
fix valid findings and rerun affected checks. Use the private deployment prepared in Phase 8; activate only the
already-authorized controls with the matching proof and verified rollback.
Check listener exposure, app health, native doctor/security/secrets audits,
budget proxy and backup freshness afterward. Public exposure needs its own
concrete review and authorization.

## Acceptance gate 10

PASS requires required system, security/authorization/budget and dashboard
assertions to pass on the final revision; required capabilities to be present;
scheduled backup plus isolated restore/restart/rollback proof within declared
RPO/RTO; and reviewed findings resolved. Gate 0–6 gaps are individually mapped
to new case IDs and marked passed only from actual relevant evidence.
Prepared/disabled features are not live acceptance. Required unavailable cases
remain BLOCKED; skipped tests remain NOT_RUN. A narrower useful product may
be delivered only with the owner-approved scope and truthful limits.

Retain per-case results, final revision, costs and cleanup in `evals/RESULTS.md`
and `evidence/phase-10/<UTC-run-id>/`; update runbook/build log. If optional
Phase 9 was excluded, proceed to Phase 12 when authorized. If built and selected,
next testing step is [Phase 11 browser comparison](phase-11-browser-evaluation.md).
Stop after this phase unless later testing is already authorized.
