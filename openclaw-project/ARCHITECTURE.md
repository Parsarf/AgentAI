# OpenClaw personal agent architecture

Status: server deployment in progress, 2026-09-24. The local installation is
only a disposable development staging area; no production service is running.

## Host and runtime

The final Gateway, sandbox, state, backups, and Telegram polling must run on an
always-on server. The owner's laptop must be able to turn off without affecting
the agent. Server address and access are pending. An isolated OpenClaw 2026.9.6
installation was used on this Mac for configuration checks only; it must not
become the production service. The owner selected Anthropic API-key billing,
not the Claude CLI login.

OpenClaw is the sole new agent runtime. Production state and secrets belong on
the server in private persistent storage. This repository holds only non-secret
templates and review artifacts. The local staging state is gitignored and
private; its temporary Gateway passed `/healthz` and was stopped. The existing
Python service and `~/.openclaw` are untouched.

## Authority and trust

| Role | Input and task | Allowed authority |
|---|---|---|
| Main orchestrator | Owner requests and attributed worker summaries | Plan, delegate, synthesize; no direct raw web/browser retrieval |
| Research/browser workers | Web, pages, email, repos and files | Read in sandbox; no messaging, credentials, gateway/config, cron or spawning |
| Native Codex worker | Software changes in project workspace | Scoped write/exec per approved policy; no ambient owner credentials |
| ACP reviewer | Independent review | Read/test within a scoped workspace; no separate outbound authority |

The actual effective tool policies must be tested after installation. External
content is data, not an instruction source. Native Codex and ACP are distinct
routes according to the [Codex harness](https://docs.openclaw.ai/plugins/codex-harness)
and [ACP](https://docs.openclaw.ai/tools/acp-agents) docs. Any tool or
credential added later needs explicit policy review.

## Budget and approvals

The owner chose a $2 daily and $25 monthly ceiling for Anthropic API use. An
independently enforced provider or gateway cap is still required before any paid
model call. OpenClaw's usage charts are observational and do not satisfy this
gate. High-impact external writes, payments, messages
to others, production deployment, main-branch push, security-policy changes,
plugin installation and new credential access require owner authorization
under the final policy. Scheduled work has less authority. Verify the actual
approval delivery surface, including timeout/denial behavior.

## Persistence and recovery

Use documented OpenClaw memory, tasks/cron and [backup/restore](https://docs.openclaw.ai/cli/backup)
interfaces. Restore only into a fresh disposable target for tests. A run
summary must record objective, artifacts, tool actions, verification, cost and
errors without storing secrets or hidden reasoning. The owner can inspect,
correct and delete memory. No old AgentAI data is imported by default.

## Acceptance

Follow the [Phase 0–8 plan](../phase-prompts/openclaw/README.md). Each phase
records real health-check evidence. The final workflow requires sourced
research, a Codex build, tests, browser verification, independent review,
budget enforcement and successful restart recovery. A documented gap or
skipped check is not a pass.
