# OpenClaw personal agent: phase prompts

These prompts turn [the super-agent brief](../openclaw-super-agent-prompt.md) into
one executable session per phase. Start at Phase 0. Paste one entire file into
a fresh coding session with access to the intended server, from the new
OpenClaw project directory. Keep `BUILD_LOG.md` there and read it before every phase. A later
session resumes incomplete work; it does not silently repeat setup.

An isolated Mac bootstrap and its current evidence are in
[openclaw-project](../../openclaw-project/README.md). Production must run on
an always-on server and stay available while the owner's Mac is off. The
staging setup has not passed the sandbox or final acceptance gates.

| Phase | Prompt | Gate |
|---|---|---|
| 0 | [Research and migration](phase-0-research-migration.md) | Verified architecture and migration decisions |
| 1 | [Secure single agent](phase-1-secure-agent.md) | Owner-only chat, health, usage and budget evidence |
| 2 | [Sandbox and approvals](phase-2-sandbox-approvals.md) | Isolation and approval denials demonstrated |
| 3 | [Trust-separated workers](phase-3-trust-workers.md) | Sourced research and injection test |
| 4 | [Codex and review](phase-4-codex-review.md) | Build, tests, independent review, debugging |
| 5 | [Memory and durable work](phase-5-memory-scheduling.md) | Selective recall and restart recovery |
| 6 | [Personal integrations](phase-6-integrations.md) | Read, draft, approval, malicious-content checks |
| 7 | [Evaluation and operations](phase-7-evals-operations.md) | Repeatable evals, recovery, security gate |
| 8 | [Acceptance and handoff](phase-8-acceptance.md) | Full owner workflow and runbook |

## Relationship to the older prompts

The root `phase-1` through `phase-7` files describe the existing **multi-user
Python AgentAI** service. They remain available for history and are **not**
instructions for the new OpenClaw build. Its Phase 6 purchase path is partial
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
