# Phase 5 — memory, durable work and bounded scheduling

Owner requested Phase5 on 2026-09-27 with tests still explicitly deferred.
Proceed under that recorded exception; Gate4 remains unpassed. Gate5 cannot
pass until its memory, recovery, cancellation and scheduling fixtures run.

## Implementation plan

1. Preserve private state and capture the exact authored fields before changes.
2. Enable native Memory Core keyword retrieval for main only: provider `none`,
   no fallback, memory files only, no extra roots or private transcript recall.
   Keep dreaming off and disable silent compaction memory flush. Existing
   USER.md/AGENTS.md content is preserved; append bounded owner-attributed rules.
3. Expose memory_search/memory_get and native goal tools only to main. Add
   explicit denials to existing workers. Default Anthropic/Codex models and
   spending caps stay unchanged; no inference or embedding calls for setup.
4. Use native `/goal` for owner-controlled objective persistence, and native
   tasks/TaskFlow for delegated work tracking/cancellation. TaskFlow managed
   execution needs a supported controller (e.g. Lobster); do not create one
   just to claim autonomous restart recovery. Record receipts in an artifact.
5. Inventory existing jobs and preserve them. Prepare exactly one disabled
   native script job, `phase5-quiet-status-v1`, daily08:00 America/Los_Angeles,
   isolated under critic, one session_status call, five-second deadline,
   no delivery/model call/wake request or further tools. Inspect native concurrency.
6. Apply through native configuration/automation commands, check application
   readback for safe setup, and record deferred behavioral verification.

## Native mechanisms and limits

| Outcome | Native mechanism | Important limit |
|---|---|---|
| Stable preferences | USER.md, bounded startup context | Compact; do not append contradictory active preferences |
| Durable project facts | MEMORY.md and memory/*.md | Outside instructions/credentials excluded |
| Selective retrieval | memory_search/memory_get, builtin FTS5, provider none | Lexical ranking, not semantic embeddings; behavior unverified |
| Objective lifecycle | `/goal` on main's built-in runtime | Native Codex/external UI Goal start/resume unsupported |
| Detached work | tasks and mirrored TaskFlow | Records persist; a process/call stack does not automatically resume |
| Managed workflow | Native supported controller when needed | Not activated in this setup |
| Timed check | Disabled native script automation | No activation while fixtures deferred |
| Pausing/cancelling | Goal pause plus native tasks/flow cancellation and job disable | Clearing a goal does not stop children/schedules |

No custom memory DB, dispatcher, scheduler or blanket exactly-once guarantee.
No browser automation or sign-in required for this setup.

## State and recovery convention

Conceptual queued/running map to native task queued/running. Waiting for approval
is a managed-flow waiting checkpoint, not a made-up task pause. Goal paused
preserves the objective; stop/cancel active children separately. Blocked and
complete use native goal status rules; tasks instead finish as succeeded,
failed, timed_out, cancelled or lost. A lost task needs reconciliation.

The owner explicitly resumes a persisted goal. A managed controller explicitly
reloads its flow, checks sticky cancellation/revision, reconciles backing tasks,
then resumes. No controller or active objective is started during deferred tests.
For native goal mutations, retain operationId, issuedAtMs, goalId and exact
payload; receipts last24hours. Refresh after replay. External effects require
their own receipts; expired approval cannot authorize changed/retried work.

## Native documentation inspected (OpenClaw 2026.9.6 eb377ac)

- https://docs.openclaw.ai/concepts/memory
- https://docs.openclaw.ai/concepts/memory-builtin
- https://docs.openclaw.ai/reference/memory-config
- https://docs.openclaw.ai/concepts/memory-provenance
- https://docs.openclaw.ai/tools/goal
- https://docs.openclaw.ai/automation/tasks
- https://docs.openclaw.ai/automation/taskflow
- https://docs.openclaw.ai/automation/cron-jobs/payloads
- https://docs.openclaw.ai/tools/exec-approvals

Installed docs/help are authoritative for commands/fields. Native command
payloads execute as operator-admin on the Gateway and bypass agent exec policy;
this setup chooses a finite-tool script payload instead of host command execution.

## Verification and rollback

Owner-deferred: selective recall with12 unrelated facts, correction, active
deletion, hostile candidate, restart, ambiguous checkpoint, cancellation, actual
schedule/timezone, unattended approval denial/expiry, diagnostics/audits.
Do not run a fixture, paid probe, active objective or manual scheduled run.
Configuration schema checks and exact readback are application safeguards only,
not behavioral acceptance. Gate5 remains BLOCKED/deferred.

Rollback only the captured authored fields and Phase5-delimited note sections;
preserve newer unrelated profile/config edits. Disable/remove this phase's job
by its returned ID. Keep preexisting jobs and archives. Rebuild/invalidate the
main memory index after source correction/deletion; transcripts and backups
have separate retention. Exact backup/job IDs belong in execution evidence.

## Applied outcome — 2026-09-27

All15 config updates applied and validated, exact readback recorded. Existing
USER.md/AGENTS.md preserved, delimited sections appended, attributed project
note and objective template installed. One disabled job created:
`4435c5f6-ca9e-46a0-9f1e-24edb5202c27`. All12 original jobs preserved.

Installed scheduler capacity is fixed8; cron.maxConcurrentRuns is unsupported.
No global concurrency1 claimed or applied. No supported managed workflow
controller activated; goals provide owner-driven resume, not autonomous
multi-step recovery. These limits and deferred fixtures keep Gate5 BLOCKED.

Private field/source backup:
`/opt/openclaw-production/backups/phase5-config-20260927T180152Z`.
Evidence: [manifest](../evidence/phase-5/20260927T180152Z/manifest.json) and
[readback](../evidence/phase-5/20260927T180152Z/application-readback.json).
No inference or embeddings explicitly requested; provider charge not queried.
