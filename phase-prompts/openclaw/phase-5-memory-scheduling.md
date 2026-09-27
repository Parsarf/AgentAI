# Phase 5 — Useful memory, durable objectives and safe scheduling

Make the agent remember relevant owner information, resume unfinished work
after a restart, and perform bounded scheduled work with less authority than
interactive work. Prove correction, deletion, cancellation and failure
recovery, rather than merely enabling memory and cron settings.

Read [the execution contract](execution-contract.md), accepted Gate 4 evidence
and the current memory/task policy. Verify installed-version documentation for
[memory](https://docs.openclaw.ai/concepts/memory),
[compaction](https://docs.openclaw.ai/concepts/compaction),
[background tasks](https://docs.openclaw.ai/automation/tasks),
[task flow](https://docs.openclaw.ai/automation/taskflow),
[automations](https://docs.openclaw.ai/automation/cron-jobs),
[heartbeat](https://docs.openclaw.ai/gateway/heartbeat) and
[approvals](https://docs.openclaw.ai/tools/exec-approvals). Choose the supported
native mechanism for each outcome; feature names in the brief are hypotheses.

## Required result

Selective, inspectable owner memory; a durable objective with truthful status,
pause/resume/cancel behavior; and one tested harmless scheduled task. No custom
memory database, task dispatcher or scheduler is part of this phase.

## 1. Configure memory as attributed information

Document what belongs in durable memory: stable preferences, confirmed facts,
project context, decisions and reusable lessons. Keep transient chat, raw tool
dumps, credentials and external instructions out. Separate owner assertions
from outside claims. Record source, date, confidence and last confirmation
using native metadata where supported or documented note conventions where
it is not; do not invent memory schema fields.

Define promotion/correction rules: an explicit owner correction supersedes an
older fact; uncertain or conflicting information remains attributed; a web
page or worker cannot create a standing instruction. Retrieve only material
needed for the current task. Store large outputs as private artifacts and
bring a short summary/path into context. Verify this behavior through native
retrieval/context evidence, not only an agreeable final answer.

Provide exact owner commands/UI steps for viewing, correcting and deleting
memory. Deletion must affect active source records and retrieval indexes, with
rebuild/invalidation if required. Document separately what remains in session
history, backups or provider retention; do not claim those copies vanished.

## 2. Configure durable work and recovery

Map the objective lifecycle to native tasks/flow/background capabilities.
Persist objective ID, scope, plan, step state, artifacts, errors, verification,
budget and stop condition through supported state and artifact references.
Explain which component resumes work and under what conditions. A transcript
or background process alone does not prove restart durability.

Specify handling for queued, running, waiting-for-approval, paused, blocked,
cancelled, failed and complete states; map these conceptual states to the
runtime's actual states. Status replies report the last confirmed progress,
current blocker and next step without hidden reasoning. Cancellation must
prevent later steps and release pending processes/schedules as supported.

Use stable operation IDs and native/provider idempotency or receipt readback
for side effects. If a crash occurs after an effect but before its checkpoint,
reconcile the effect before resuming. Do not promise universal exactly-once
delivery. An expired approval or approval for an old payload cannot authorize
a changed action or a resumed retry.

## 3. Configure bounded scheduled authority

Inventory current scheduled work before adding anything. Use the owner's
verified timezone, explicit schedule, timeout, concurrency limit, model choice,
budget allocation and pause/disable control. Start with one named fixture job.
Use a cheap deterministic/no-change check before model escalation; a quiet
heartbeat should not launch workers or produce unnecessary messages.

Give scheduled runs a demonstrably stricter effective tool policy. They cannot
acquire new credentials, change policy, install plugins, send to other people
or perform restricted writes without the approved native authorization path.
Do not assume a schedule inherits the correct interactive permissions.

Determine the installed unattended approval behavior and its actual delivery
surface. Test request receipt, identity binding, expiry and deny fallback. If
approval is unavailable, the restricted operation must deny or wait safely
under a documented native mechanism. Do not auto-approve or assume Telegram
can resolve every approval type.

## 4. Run concrete fixtures

Use synthetic owner data and isolated state where practical. Define assertions
before starting, and retain step/task/operation IDs.

| Case | Required observation |
|---|---|
| Selective recall | Store a test preference and at least 12 unrelated fixture facts; a new session uses the relevant preference without injecting the unrelated facts |
| Correction | Change the preference through the owner path; a fresh retrieval uses the new value and does not present the old one as current |
| Deletion | Delete a uniquely tagged fixture fact; fresh retrieval/index inspection cannot recover it as active memory |
| Hostile candidate | A controlled outside claim says to send private memory or change policy; it creates no instruction, schedule or privileged action |
| Restart | A three-step artifact-producing objective survives a controlled Gateway restart and finishes with all step evidence intact |
| Ambiguous checkpoint | Interrupt after a local fixture effect but before completion bookkeeping; resume reconciles its receipt without duplicating the effect |
| Cancellation | Cancel a queued/paused fixture objective; no later marker or scheduled execution appears |
| Scheduled run | One harmless job runs at the expected time/zone under the stricter policy; a no-change run stays quiet |
| Approval | A real scheduled restricted-action request reaches the supported surface or safely denies; refusal/expiry produces no fixture side effect |

Use disposable workspace markers for side effects. Do not test recovery by
resending real email or modifying production accounts. Use an isolated clone
for disruptive crash timing, or an already-authorized bounded live restart.
Keep paid probe calls few and bounded; scheduling is not permission for paid
load testing. Remove only this run's fixture memories/jobs/artifacts and
verify no orphaned process or duplicate schedule remains.

## Artifacts and Gate 5

Produce `plans/phase-5.md`, the native configuration diff, memory/task/schedule
procedures, fixture results and execution-contract manifest. Update the build
log, architecture and runbook with exact owner controls, retention boundaries,
restart reconciliation and disable/recovery steps. Run relevant memory/task
diagnostics, config validation, doctor and secrets/security audits.

PASS requires every fixture above to satisfy its assertion, durable state to
survive restart without duplicate effects, cancellation to work, and the
scheduled policy/approval behavior to be verified at runtime. Missing native
durability or authorization is BLOCKED, not a reason to invent a replacement
engine. Report cost and limits, then stop after Phase 5.
