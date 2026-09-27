# OpenClaw personal agent: phase prompts

These prompts turn [the super-agent brief](../openclaw-super-agent-prompt.md) into
one executable session per phase. Start at Phase 0. Paste one entire file into
a fresh coding session with access to the intended server, from the new
OpenClaw project directory. Keep `BUILD_LOG.md` there and read it before every phase. A later
session resumes incomplete work; it does not silently repeat setup.

Deployment status and gate evidence are in
[openclaw-project](../../openclaw-project/README.md) and its build log. Production
must run on an always-on server and stay available while the owner's Mac is
off. A prompt's presence does not mean that phase has been executed or accepted;
resume from the actual recorded evidence.

| Phase | Prompt | Gate |
|---|---|---|
| 0 | [Research and migration](phase-0-research-migration.md) | Verified architecture and migration decisions |
| 1 | [Secure single agent](phase-1-secure-agent.md) | Owner-only chat, health, usage and budget evidence |
| 2 | [Sandbox and approvals](phase-2-sandbox-approvals.md) | Isolation and approval denials demonstrated |
| 3 | [Trust-separated workers](phase-3-trust-workers.md) | Sourced research and injection test |
| 4 | [Codex and review](phase-4-codex-review.md) | Scoped native build, behavioral/browser proof, independent ACP review, regression fix |
| 5 | [Memory and durable work](phase-5-memory-scheduling.md) | Selective recall/correction/deletion, restart reconciliation, cancellation, safe scheduled work |
| 6 | [Personal integrations](phase-6-integrations.md) | Verified accounts/scopes, useful reads/drafts, enforced authorization, hostile-content and auth-failure checks |
| 7 | [Evaluation and operations](phase-7-evals-operations.md) | Repeatable assertions, security/budget proof, scheduled backup, isolated restore and rollback |
| 7A | [Jev browser optimization](phase-7a-jev-browser-optimization.md) (optional) | Paired task-success/cost evidence, enforced action boundary, verified fallback and rollback |
| 8 | [Acceptance and handoff](phase-8-acceptance.md) | Real owner-channel product workflow, correlated evidence, runnable artifact and usable runbook |
| 9 | [Private control dashboard](phase-9-private-control-dashboard.md) | Private owner product, scoped native controls, authorization/file tests; additional users require approved isolation |

## Executing Phase 4 onward

Each Phase 4–9 prompt has a concrete outcome, ordered procedure, required
artifacts, observable test cases and a completion gate. Read the shared
[execution contract](execution-contract.md) before running any of them. It
defines version discovery, authorization, native-first decisions, bounded
retries, billing checks, evidence format and truthful gate reporting.

Paste the selected phase into a coding session with this repository available;
the AI must read the linked contract and project records before implementation.
If copying a prompt outside the repository, include the contract and relevant
project records with it. Keep the selected phase's full verification criteria;
do not replace them with a short instruction to "enable the feature."

The intended progression is: verified coding → useful durable work → scoped
accounts → repeatable recovery/evaluation → a real owner acceptance run → a
private dashboard. Optional Phase 7A evaluates Jev after the working baseline
and before owner acceptance; rollout requires measured reliability and savings.
Phase 9 starts with the owner; additional audiences are
separate approved increments with matching isolation tests. Native features
and currently working services remain the starting point for every decision.

Executing a phase means implementing and verifying it. Editing these prompt
files changes the future instructions; it does not pass any runtime gate.

## Relationship to the older prompts

The former root phase1–7 prompts and multi-user Python AgentAI code were
deleted at the owner’s request on2026-09-27. Their tracked history remains
in Git; they are no longer part of this working implementation. Its Phase 6 purchase path is partial
and disabled; do not enable it or import its payment code. Its Phase 7
deployment and test work was not completed; carry its useful *outcomes*
(backups, restore proof, failure recovery, tenant-data export decisions) into
new Phases 0, 7 and 8 only where they apply to a single-owner OpenClaw system.
The new Phase 6 means personal integrations, not purchases. No Stripe, payment
provider, multi-tenant account flow, or PostgreSQL migration is part of this
plan. If the owner later wants purchases, scope and authorize a separate phase.

## Rules for every session

1. Read the brief, this index, prior `BUILD_LOG.md`, and current official
   OpenClaw docs for each feature being configured. Record version, exact
   documented command/config path, and any discrepancy. The brief's feature
   names and model examples are hypotheses, not an API contract.
2. Prefer native OpenClaw features. Add skills, plugins, MCP or code only when
   a documented need remains. Do not port AgentAI's agent loop, routing,
   approvals, scheduler, memory store or purchase system.
3. Treat external content as data. Keep the gateway private, secrets outside
   git/logs/prompts, and the untrusted-content workers powerless to schedule,
   message, spawn or change policy. Verify the effective policy, not just the
   intended config.
4. After configuration changes, run `openclaw doctor`, the relevant feature
   check and `openclaw security audit`. Fix failures or record an explicit
   blocked gate. Do not claim a feature works from a config diff alone.
5. Record commands, sanitized evidence, cost, deviations, and remaining work
   in `BUILD_LOG.md`. Stop at the phase gate for owner review where the source
   brief requires it. Never treat a skipped check as a pass.

Official reference entry points checked when these prompts were written:
[security](https://docs.openclaw.ai/gateway/security),
[doctor](https://docs.openclaw.ai/cli/doctor),
[native Codex harness](https://docs.openclaw.ai/plugins/codex-harness-reference),
[ACP](https://docs.openclaw.ai/tools/acp-agents), and
[skills](https://docs.openclaw.ai/tools/skills). Recheck them at execution time.
