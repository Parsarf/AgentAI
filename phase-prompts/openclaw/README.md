# OpenClaw personal agent: remaining phase plan

The current implementation is at the Phase 6 connection base. Account setup
and heavy/paid tests remain deferred by the owner. **Build the remaining
features first; test the completed system afterward.** Prompt files describe
future work, not completed implementation or accepted gates. Read the
[build log](../../openclaw-project/BUILD_LOG.md) for actual status.

## Remaining building phases — start here

| Order | Prompt | Build deliverable |
|---|---|---|
| 7 | [Operations and recovery](phase-7-operations-build.md) | Close remaining runtime implementation gaps; backup/schedule/restore tooling; runnable evaluation harness and fixtures |
| 8 | [Private control dashboard](phase-8-dashboard-build.md) | Owner dashboard, scoped native controls, auth/file boundaries and prepared acceptance cases |
| 9 | [Browser optimization](phase-9-browser-optimization-build.md) — optional | Disabled typed-action adapter, baseline fallback, billing boundaries and comparison fixtures; skip unless selected |

Build phases use lightweight checks relevant to their changes. They do not run
the full behavioral suite, paid benchmarks, recovery drills or final product
workflow. Record build readiness separately from acceptance. A missing prior
test does not block independent implementation; missing authorization,
isolation or budget protection still blocks activating the dependent feature.
Account sign-in remains the owner's later setup task.

## Testing phases — after all selected builds

| Order | Prompt | Acceptance evidence |
|---|---|---|
| 10 | [System, dashboard and recovery evaluation](phase-10-system-evaluation.md) | Earlier deferred cases, security/budgets, dashboard/browser flows, scheduled backup, isolated restore/restart/rollback and independent review |
| 11 | [Browser comparison](phase-11-browser-evaluation.md) — optional | Paired reliability/cost comparison, calibrated thresholds, fallback/kill-switch and rollout proof for the Phase 9 adapter |
| 12 | [Final acceptance and handoff](phase-12-acceptance-handoff.md) | Real owner-channel product workflow, private dashboard use, correlated evidence and usable runbook |

Reaching Phase 10 does **not** resume deferred tests. Run testing only when the
owner explicitly resumes it, within existing approved budgets. If Phase 9 is
excluded, skip Phase 11 and use the baseline browser route. Tests may fix defects
and rerun affected cases; do not add another planned feature-build phase after
final acceptance. Required missing capabilities remain blocked, and skipped
checks never become passes.

## How to execute a prompt

Read the [execution contract](execution-contract.md),
[super-agent brief](../openclaw-super-agent-prompt.md), project architecture,
runbook and build log before implementation. Paste one complete selected prompt
into a session with repository access. Include those records if copying it
elsewhere. Resume from actual evidence; do not repeat onboarding or assume a
file's existence proves deployment. Production remains on the always-on server.

Prefer native OpenClaw mechanisms, verify installed commands/config/API paths,
keep secrets private, preserve hard caps and require effective authorization.
Record changed artifacts, lightweight checks, costs, limitations, rollback and
later test case IDs. Follow the stage-specific contract instead of running
expensive acceptance checks during a build phase. Continue additional phases
only when already authorized; otherwise report the completed stage.

## Earlier phases — implementation and evidence history

These phase files retain their original requirements. Outstanding acceptance
checks carry into Phase 10; this reordering does not pass earlier gates.

| Phase | Prompt |
|---|---|
| 0 | [Research and migration](phase-0-research-migration.md) |
| 1 | [Secure single agent](phase-1-secure-agent.md) |
| 2 | [Sandbox and approvals](phase-2-sandbox-approvals.md) |
| 3 | [Trust-separated workers](phase-3-trust-workers.md) |
| 4 | [Codex and review](phase-4-codex-review.md) |
| 5 | [Memory and durable work](phase-5-memory-scheduling.md) |
| 6 | [Personal integrations](phase-6-integrations.md) |

## Renumbering of remaining prompts

| Former prompt | New location |
|---|---|
| Phase 7 evaluation/operations | Operations build7; system testing10 |
| Optional Phase 7A Jev | Adapter build9; browser comparison11 |
| Phase 8 acceptance | Final acceptance12 |
| Phase 9 dashboard | Dashboard build8; dashboard testing10 |

Historical evidence keeps its original phase labels. Use this mapping when
reading older records. The superseded Python AgentAI code, original root
prompts and spec were already deleted at the owner's request; tracked history
remains in Git. Do not restore or port that runtime, purchase code or scheduler.
Personal integrations are the current Phase 6; payments and multi-tenant flows
are outside the approved plan.
