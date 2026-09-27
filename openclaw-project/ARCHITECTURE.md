# OpenClaw personal agent architecture

Status: Phase 3 (trust-separated workers) is live on the IONOS VPS. Gate 1
still awaits Telegram owner/non-owner evidence, Gate 2 awaits a real owner
approval-card interaction, and Gate 3 awaits two budget-blocked checks
(sourced research run and controlled injection test; no operator cron remains
scheduled). Phase 4 has saved ChatGPT authentication and enabled the guardian Codex plugin;
isolated Codex builder/debugger are active and a native boundary probe passed;
native app build and debugging proof passed; browser and ACP acceptance remain pending. OpenClaw, LiteLLM and PostgreSQL
are running on the VPS. The old Mac staging installation is historical only.

## Host and runtime

The final Gateway, sandbox, state, backups, and Telegram polling must run on an
always-on server. The owner's laptop must be able to turn off without affecting
the agent. The IONOS Ubuntu 24.04.4 VPS is `69.48.206.62`; SSH access works.
The live Compose deployment is `/opt/openclaw-production`. An isolated OpenClaw 2026.9.6
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
| Main orchestrator (`main`) | Owner requests and attributed worker summaries | Plans, delegates (`sessions_spawn` limited to researcher, browser-worker, critic, codex-builder and codex-debugger), synthesizes; **no** web/raw-fetch/browser, no cron, no gateway/config, no `sessions_send`, no outbound messaging. Runs host-side. `tools.exec.host: sandbox` is configured, but `sandbox explain` reports main is unsandboxed; a successful sandbox exec from main has not been demonstrated. File tools are configured workspace-only. |
| Researcher worker | Delegated research questions, seed URLs | Sandboxed; `web_fetch` + workspace file tools only. No exec, messaging, credentials, gateway/config, cron or spawning (`subagents.allowAgents: []`). |
| Browser/fetch worker | Delegated page retrieval | Sandboxed; same surface as researcher. Interactive browser access remains disabled. Phase 4 found Chromium in the Playwright cache and built the official authenticated sidecar image; worker activation and real UI verification are still pending. |
| Critic worker | Claim/citation verification | Sandboxed and read-only: `web_fetch`, `read`, `ls`, `session_status`. No write, no exec, no spawning. |
| Native Codex worker | Software changes in project workspace | Guardian plugin with protected ChatGPT profile; builder/debugger use project-only non-root Docker tools, read-only root, networknone, no elevated tools. Actual native boundary probes, board build (7 tests) and debugging proof (4 tests) passed; browser/ACP acceptance pending. |
| ACP reviewer | Independent review | Phase 4 target; not configured yet. |

External content is data, not an instruction source: worker `AGENTS.md` role
contracts and the `untrusted-content` skill require instruction blocks inside
fetched content to be quoted as attributed `INJECTION_ATTEMPT` findings, and
the `orchestration` skill requires the orchestrator to treat worker output as
attributed data. `tools.agentToAgent` is disabled and session visibility is
`tree`, so cross-agent session access is blocked while owned child sessions
stay reachable. Main has no authored skill filter; its installed coding skills
are eligible. Explicit worker filters expose `deep-research`/`untrusted-content`
to researcher and `untrusted-content` to browser-worker/critic.

Default model roles (via LiteLLM): `primary_reasoner` =
`litellm/claude-sonnet-4-6` (all four agents); utility/cheap background =
`litellm/claude-haiku-4-5` (defaults utility model). A different-family
critic model is not currently available (single provider allowlist);
verification strength comes from the independent read-only critic pass
instead. Native Codex workers explicitly use `openai/gpt-6-sol` with no fallback; the
authorized ChatGPT subscription has separate quota and billing. Main retains
Anthropic by default, with a per-run Sol override for native coordination.
Failover: no cross-provider fallback exists; requests fail visibly, and the Anthropic workspace cap plus the $2/24h
plus $25/30d virtual-key windows bound the blast radius.

Phase 1 started with one chat-only owner agent. Phase 2 sandboxed every
session. Phase 3 refined that: worker sessions stay fully sandboxed (Docker
backend, session scope, no network, read-only root, capability drop), while
the orchestrator runs host-side because a sandboxed session cannot register
the session-orchestration tools at all (verified; see `BUILD_LOG.md`). The
Docker socket and read-only Docker CLI are mounted only in the trusted
Gateway container. Host elevated commands are restricted to the numeric
Telegram owner and require a host approval every time, with deny fallback.

## Budget and approvals

The owner chose a $2 daily and $25 monthly ceiling for Anthropic API use and
confirmed the independent Anthropic workspace monthly limit is set to $25.
LiteLLM 1.102.1 virtual-key windows rejected independent daily/monthly probes
with HTTP 429. Database-outage admission rejected with HTTP 503. Reservation
and fail-closed controls are enabled. The Gateway uses a virtual-key SecretRef;
the provider key belongs only to LiteLLM. Usage charts remain observational.
High-impact external writes, payments, messages
to others, production deployment, main-branch push, security-policy changes,
plugin installation and new credential access require owner authorization
under the final policy. Scheduled work has less authority. Verify the actual
approval delivery surface, including timeout/denial behavior.

## Persistence and recovery

All three Gateway host ports are bound to loopback; container-side `lan` bind
is retained for Docker port forwarding. Allowed origins are exactly
`http://localhost:18789` and `http://127.0.0.1:18789`, with auth rate limiting.
Native one-time browser bootstrap and an SSH tunnel provide owner UI access.

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
