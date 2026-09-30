# OpenClaw runtime and customer platform architecture

## Current customer-platform foundation — 2026-09-29

Product Phases1–2 define the owner-selected $79/$25/$5 plan and a separate
private product app/control foundation. See [platform architecture](platform/ARCHITECTURE.md),
[capability matrix](platform/CAPABILITIES.md) and [product contract](../product/CONTRACT.md).
Foundation readiness was proved with temporary unprivileged/resource-bounded
server smoke; customer activation remains disabled. Separate tenant VMs are
the selected boundary; the owner VPS admits no customers. Native OpenClaw
remains the runtime, and current owner config/state/proxy DB are preserved.
Historical sections below retain their earlier labels/limitations; latest
BUILD_LOG and product inventory supersede stale capability statements.

Latest increment: Phase6 personal integration preparation is applied. Native
Google/GitHub definitions are disabled pending account authentication and
repository selection. Only researcher is eligible to consume those read-only
tools; main and other workers explicitly deny MCP. Phase5 memory setup is
applied, with behavioral acceptance deferred. The historical phase details
below retain their original evidence limitations; no outstanding gate is passed.

Google runs as a pinned `workspace-mcp1.29.0` non-root stdio container spawned
by the trusted Gateway's existing Docker CLI. It mounts only a dedicated private
Google client/token directory, with no Docker socket, Gateway state or worker
workspace. Provider network egress is necessary; root filesystem is read-only,
resource limits and tmpfs logs configured. Native filters expose reads only;
local proposals handle drafts. GitHub uses its official hosted read-only MCP
endpoint; selected-repository credential setup is pending. No connector write
approval mechanism or runtime behavior is asserted from configuration alone.

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
templates and review artifacts. Local operator credentials are in ignored mode0600
`openclaw-project/.env`. Owner-authorized cleanup removed the old Python
application’s working tree and disposable Mac staging state; current server
services/databases, recovery backups and `~/.openclaw` were untouched.

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

Follow the [current Phase 1–19 plan](../phase-prompts/openclaw/README.md). Each phase
records real health-check evidence. The final workflow requires sourced
research, a Codex build, tests, browser verification, independent review,
budget enforcement and successful restart recovery. A documented gap or
skipped check is not a pass.

## Phase 5 memory and objective setup (2026-09-27)

Main alone has builtin MemoryCore FTS retrieval: provider/fallback none,
memory-only sources, no extra roots or transcript recall. Compact USER.md is
startup context; detailed project notes live under memory/. Dreaming stays off,
compaction flush is disabled, and workers are denied memory/goal tools.
Prose attribution is a note convention, not native provenance/trust metadata.

Native per-session goals persist objectives. Owner resume reconciles checkpoint,
actual child task/flow IDs and side-effect receipts. Task/flow persistence does
not restart a process; no managed workflow controller is activated. Records
have native retention (normally7days; lost tasks24hours), so durable project
artifacts hold essential receipts. Cancellation covers children/schedules
separately from goal clear.

The one Phase5 script job is disabled and limited to session_status, one call,
five seconds, no model or delivery. Its runtime boundary is not yet proven.
Installed scheduler capacity is fixed8; concurrency1 cannot be configured.
All12 older jobs were preserved. Gate5 acceptance and earlier missing fixtures
remain deferred. See RUNBOOK.md and evidence/phase-5/20260927T180152Z/.

## Operations layer (Phase 7)

A host systemd timer (`openclaw-ops-backup`, 03:17 UTC daily) performs the
operator backup — a consistency-aware native OpenClaw archive with post-write
verification plus a LiteLLM PostgreSQL dump for spend history and virtual-key
identity — bounded local retention (14 sets), and a local-only freshness
report. The timer is outside agent authority: agent cron jobs are untouched,
and the backup job makes no model calls and sends nothing. Restore/rollback
entry points stage isolated clones with channels, schedules and delivery
disabled before any start; drills are Phase 10 acceptance work. The
repeatable acceptance suite is defined but unexecuted in `evals/`.

## Private control dashboard (Phase 8)

A separate, minimal owner dashboard (`dashboard/app.py`, stdlib-only,
loopback-only, systemd-hardened) composes read-only operational truth from
fixed native operations — gateway/LiteLLM/Postgres health, container state,
spend vs configured caps, backup freshness, pending approvals, connector
state — plus scoped session listing and an allowlisted virtual file view
over the container `work/` root. It stores only its own auth secrets and an
append-only application audit stream; it holds no OpenClaw state, tokens or
model credentials. All mutating controls are feature-gated off server-side
pending Phase 10 targeted proof; the native Control UI remains the
chat/settings surface. Additional audiences remain unauthorized by default.

## Browser optimization adapter (Phase 9, disabled)

A self-contained adapter library owns deterministic snapshot→candidate
building, fail-closed response validation against the pinned TypeSafe
`jev-1.13.0` schema (candidate membership, finite unit-sum probabilities,
argmax consistency, Choice-only confidence), a local-estimate action budget,
bounded retries, and explicit escalate/stop/no-valid-action outcomes. Jev
holds no authority: its only possible effect is choosing among code-created
candidates; execution, identity re-checks and outcome verification stay in
code, and owner approvals are unchanged. The route is disabled at the
config level and unwired from the runtime pending a reviewed transport and
an owner-authorized TypeSafe account (Phase 11).

## Browser/search tool surfaces (2026-09-28)

Browser capability is worker-scoped: only `browser-worker` may call browser
tools; sessions spawn pinned per-session sandbox-browser containers
(authenticated CDP relay, no host publishing beyond the sandbox bridge) and
the orchestrator stays browser-denied. Brave search is available to
`researcher` as the `brave-search__brave_web_search` MCP tool, backed by a
pinned official Brave container and a private mounted key file. Main and all
other workers explicitly deny its namespace. Native `web_search` remains
disabled because this build does not support Brave as a native provider.

## Product Phase3 account boundary

The separate platform app now uses Django authentication/sessions/CSRF, confirmed
operator TOTP and private Gunicorn. Read [account architecture](platform/accounts/README.md)
and [ADR006](platform/ARCHITECTURE.md). Account ownership is resolved server-side,
not shared owner login/UI filters. New app credentials contain only private
session/mail custody, never owner Gateway/provider/Telegram/SSH keys. Native
execution/provisioning/billing remain off; owner services unchanged.
