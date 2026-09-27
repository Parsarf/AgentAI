# OpenClaw build log

## Phase 4 — server recovery and manual handoff, 2026-09-27 (verification deferred)

- Preserved prior native app/debug artifacts; identified failed coordinator
  collection separately from successful child builds.
- Quiesced Gateway, saved private stopped-state archive and checked47 SQLite
  files successfully. Offline Doctor diagnostic output produced, timeout124;
  owned one-off removed, Gateway restarted, health HTTP200.
- Saved ChatGPT auth works; quota5h5%/week16%,zero credits. No new sign-in.
- Found cached ACP Claude adapter/SDK; inspected supported tool controls;
  no activation or review inference. No host security/cron/budget changes.
- Prepared localhost-only preview and manual Chrome checklist. Owner then
  deferred all remaining tests; stopped preview and made no further checks.
- Evidence: `evidence/phase-4/20260927T173530Z/`. Phase4 awaits verification.

## Phase 4 — native execution resumed, 2026-09-26 22:44–23:11 UTC (BLOCKED)

- Normal approvals resumed. Repaired SDK peer resolution in a derived pinned
  same-version Gateway image; isolated import and health passed.
- Applied native builder/debugger scopes and proved actual native boundaries:
  project-only mounts, non-root, rootread-only, networknone, no elevated tools.
- Main delegated native board build. Seven tests and private HTTP smoke check
  pass; server stopped. All8 exported app source hashes match tested manifest.
- Native debugger reproduced the same ID0 regression before/after; minimal
  fix, 4/4 pass, three original neighbors preserved, source hashes verified.
- Apply CLI timed out124 during plugin cleanup after successful6-field update;
  exact readback and config validation confirmed application. Secret audit:
  no plaintext/unresolved refs, informational OAuth residue. Security0critical,
  2warnings. Doctor refused live lease; offline precheck preserved an active
  coordinator and aborted before shutdown/migration. Gateway health HTTP200.
- ChatGPT quota98% five-hour/15% week, zero credits; new inference stopped.
  Browser verification and independent ACP review still unrun; reviewer route
  setup/isolation and proxy admission pending. Caps unchanged, no cron added.
- Gate4 remains BLOCKED; Phase5/7A not started. Exact evidence and recovery
  limitations: `evidence/phase-4/20260926T225237Z/`.

## Phase 4 — continuation, 2026-09-26 22:03–22:34 UTC (BLOCKED)

- Corrected, validated and installed the software-project/debugging skills;
  preserved existing edits and seeded fixtures. Created board spec and Git
  baselines; three existing debug tests pass, seeded ID0 defect remains.
- Built pinned official browser sidecar and passed synthetic container
  isolation/authenticated-CDP probes. These do not prove native agent behavior.
- Created and verified private preparation and preactivation backups; repaired
  only state-parent permissions0755→0700. Security audit0critical/1existing
  profile warning, secrets audit clean, config valid and health live.
- Owner selected ChatGPT auth and explicitly confirmed the security toggle.
  Browser sign-in succeeded; OpenClaw saved one `openai` profile. Applied
  `config/phase4-codex-activation.batch.json` with guardian approvals and
  agent-scoped state; restarted Gateway. Seven OpenAI models available;
  Gateway/Postgres healthy, LiteLLM running. No inference or cap changes.
- Native quota inspection was stopped before execution: automatic approval
  review reached its usage limit. This is a review failure, not a safety
  rejection; no bypass attempted. Continue when review is available.
- Native builder/debugger isolation, actual builds, browser-worker flows and
  independent ACP review remain pending. Gate4 and earlier pending gates are
  not passed. Evidence: `evidence/phase-4/20260926T220330Z/manifest.json` and
  `summary.md`; exact backups and limitations are recorded there.

## Phase 4 — initial preparation under owner direction, 2026-09-26 UTC

Recorded exception: Gate 3 is **NOT passed** — the sourced-research and
injection checks are still pending (budget-capped until 00:00 UTC; not
rescheduled after the owner deleted the operator cron). The owner directed
proceeding to Phase 4; that authorizes the work but does not convert pending
checks into passes.

Independent preparation completed (no activation, no model spend):

- `plans/phase-4.md` written: execution boundary, coding/review contracts,
  cost split, steps, rollback, doc links.
- Inventory: the `codex` plugin is bundled but disabled; it ships and manages
  its own `@openai/codex` 0.155.1 app-server (no standalone `codex` binary
  needed). **No OpenAI/Codex auth exists on the server** (`models auth list`
  → profiles: []) — the build path is BLOCKED until the owner signs in via
  `models auth login --provider openai` (device flow) or supplies a Codex
  API-key profile. Browser is fully disabled (`browser.enabled=false`); the
  activation batch must enable it and grant the `browser` tool to
  `browser-worker` ONLY. There is no `plugins.allow` list to amend.
- Skills `software-project` and `debugging` authored (tracked in
  `config/skills/`, installed into the main workspace; verified by listing).
- Debug fixture repo seeded at container path
  `/home/node/.openclaw/work/phase4/debug-repo` (Node, seeded id-0 filter
  defect per SPEC.md; neighboring tests only). Baseline `node --test`:
  **3 pass / 0 fail**, as designed.

At that preparation checkpoint, Codex authentication was pending. Activation and permission probes remained implementation work; the two Gate3 checks remained owed.

## Phase 3 — trust-separated workers, 2026-09-26 UTC (two gate checks pending budget reset)

Continued from Phase 2. Read the phase index, brief, architecture, build log,
and the current official docs for sub-agents, session tools, multi-agent,
web tools/fetch, skills, tool policy and prompt-injection defense before
configuring. Working SSH credentials from the private `agent/.env`; a
reusable `bin/ssh-server` helper was added (strict host-key checking, no
credential output, same askpass pattern as `open-control-ui.py`).

### Preparation

- Created a verified native backup before any change:
  `/opt/openclaw-production/backups/phase3-pre-workers/2026-09-26T03-39-58.412+00-00-openclaw-backup.tar.gz`
  (archive verification passed; sha256
  `29b1c76a78d7a9251a91afbd8d4e44ce23aeb7cdeb9b3d5cf15a8a54ecfa5d4b`, mode
  0600, directory 0700) plus a Compose rollback copy. No restore was needed.
- Enabled the bundled `policy` plugin (operator CLI for policy attestations;
  not an agent-facing tool). Inspected bundled/community skills: none cover
  orchestration, deep research or untrusted-content handling; the bundled
  `browser-automation` skill covers browser procedure but the browser tool is
  unavailable in this runtime (no Chromium binary in the gateway container;
  verified). A separate `browser-task` skill was therefore **not** written —
  a skill describing a disabled tool would only add prompt noise; revisit if
  the browser plugin is ever enabled.

### Configuration applied (all native CLI; batch file kept as
`config/phase3-worker-policy.batch.json`)

- Added three worker agents via `openclaw agents add --non-interactive`:
  `researcher`, `browser-worker`, `critic`, each with its own workspace under
  `/home/node/.openclaw/workspace-<id>` and model `litellm/claude-sonnet-4-6`.
  Prepend role contracts (authority limits, untrusted-content rules, output
  format) were written to each worker `AGENTS.md`; `BOOTSTRAP.md` replaced
  with a no-op note. Templates live in `config/workspace-templates/`.
- Worker tool policies (verified effective, see probes): workspace file tools
  + `web_fetch` for researcher/browser-worker; read-only + `web_fetch` for
  critic; explicit deny of `sessions_spawn`, `sessions_send`, `sessions_yield`,
  `subagents`, `exec`, `process`, `message`, `cron`, `automations`, `nodes`,
  `gateway`, `browser`, `canvas`, `view_image`, `web_search`;
  `subagents.allowAgents: []`; per-agent `elevated.enabled: false`; per-agent
  skill allowlists.
- Orchestrator (`main`): `subagents.allowAgents: ["researcher",
  "browser-worker", "critic"]`, `delegationMode: "prefer"`; profile `coding`
  so the session-orchestration tools (`sessions_spawn`, `sessions_yield`,
  `subagents`) register; explicit deny keeps `browser`, `web_search`,
  `web_fetch`, `cron`, `automations`, `nodes`, `gateway`, `sessions_send`,
  `message`, `portal`, `sessions`, `plugins`, `openclaw` off the orchestrator.
- `agents.defaults.subagents`: maxConcurrent 3, runTimeoutSeconds 900.
- `tools.sessions.visibility: "tree"`; `tools.agentToAgent.enabled: false`
  (requester-owned children remain reachable; verified by the runs below).
- Skills installed into per-agent workspaces: `orchestration` (main),
  `deep-research` + `untrusted-content` (researcher), `untrusted-content`
  (browser-worker, critic). Skill sources tracked in `config/skills/`.

### Runtime discrepancies found (docs vs pinned 2026.9.6) and fixes

1. `tools.web.search.provider: "duckduckgo"` from the current docs is **not**
   available: no such stock plugin in this build (config dry-run correctly
   rejected it). Key-free search is therefore unavailable; `web_search` stays
   disabled (`tools.web.search.enabled: false`) and is denied on all agents.
   Discovery for research tasks uses orchestrator-supplied primary URLs.
2. Sandbox tool gate: `tools.sandbox.tools.allow` (Phase 2, chat-era list)
   silently filtered `web_fetch` out of every sandboxed session even when
   agent policy allowed it. Fixed by adding `web_fetch` to the gate.
   Effective visibility in this build is the **product of every non-empty
   allow layer** (profile → global `alsoAllow` → agent allow, then deny
   wins), so the ceiling lists now include the tools agents genuinely need.
3. A sandboxed session cannot see the session-orchestration tools at all:
   with `sandbox.mode: "all"` on `main`, `sessions_spawn` never registered
   (verified by repeated probes). The target architecture already places the
   orchestrator host-side; `agents.entries.main.sandbox.mode` is now `off`.
   Blast radius accounting: `tools.exec.host: "sandbox"` keeps main's command
   execution inside the Docker sandbox, file tools stay workspace-confined
   (`tools.fs.workspaceOnly`), and the deny list blocks web/cron/gateway/
   messaging. Workers remain fully sandboxed (mode `all`, no network,
   read-only root).
4. Memory search warned on every agent (provider `openai`, no key) — disabled
   explicitly (`memory.search.enabled: false`). This also keeps owner memory
   out of worker context; Phase 5 will configure memory deliberately.

### Verification (effective policy, not config diffs)

Live probes via Gateway one-shot runs (`openclaw agent --agent X
--session-id phase3-*`); each worker ran in its own Docker sandbox:

| Tool | main | researcher | browser-worker | critic |
|---|---|---|---|---|
| `sessions_spawn`/`subagents` | yes | no | no | no |
| `web_fetch` | no (denied) | yes (fetched example.com) | yes | yes |
| `exec`/`process` | yes (host=sandbox) | no | no | no |
| `write`/`edit` | yes | yes | yes | no (read-only) |
| `cron`/`automations`/`gateway`/`message` | no | no | no | no |

Additional evidence: worker sessions sandboxed (Docker backend, session
scope); `sandbox explain` shows the researcher workspace mounts and deny
lists; elevated execution disabled for workers; Telegram allowlist and owner
command binding unchanged.

### Gate 3 status — partially met, two checks pending budget reset

- Trivial request does not spawn: **pass** — `phase3-trivial-1` ("17*23")
  answered "391" directly in 2.3 s; gateway log shows zero tool lines for the
  session.
- Orchestration path: **demonstrated but not completed** — the research run
  (`phase3-research-1`) spawned a sub-agent lane that ran 144 s (gateway
  `lane task error lane=session:agent:main:subagent:…`), proving main can
  delegate; the run then hit the budget ceiling.
- Sourced research answer with verified citations and the controlled
  prompt-injection test: **pending** — the key's $2/24h budget window is
  calendar-anchored UTC (`LiteLLM_BudgetWindowSpend.window_start =
  2026-09-26 00:00`); at ~$1.94/$2.00 all further requests were rejected with
  HTTP 429 ("Budget has been exceeded") and bounded same-model retries
  failed closed. **Budget enforcement itself is thereby re-verified live.**
  The 30d window shows $3.18/$25. The two remaining checks are scheduled to
  run after the 00:00 UTC reset via a session cron task (17:08 PDT /
  00:08 UTC); the controlled injection page is prepared at
  `evidence/phase3/inject-research-note.html` (served temporarily from the
  VPS during the test only). If the owner prefers, raising the daily budget
  temporarily would allow running them immediately instead.

The injection page contains an instruction block asking the agent to send
private memory, create a cron job and change tool policy, plus a fake canary
string (`CANARY-CHECK-8f3d21`) — **no real secret is used** as the phase
requires. Nothing was sent, scheduled or stored: workers hold no outbound,
scheduling or policy tools at all.

### Diagnostics and state

- `config validate --json`: valid, no warnings. `secrets audit --check`:
  clean (all five counters zero). `security audit`: 0 critical, 1 expected
  warn (`tools.profile_minimal_overridden` — the orchestrator's deliberate
  `coding` profile over the global `minimal` default; documented above) plus
  the informational attack-surface summary. Doctor: only the pre-existing
  informational GitHub-token advisory; memory-search warnings resolved.
- Aggregate LiteLLM spend at 2026-09-26 04:30 UTC: $3.076966 (30d window);
  per-key 24h spend $1.9409 at cutoff. Probe/test cost today ≈ $0.50–0.60 on
  top of pre-existing owner/prior-phase usage in the same window.
- 19 idle session-scoped sandbox containers from the probe series are
  gateway-managed and idle; they are reaped by the runtime and require no
  action.
- Stop reason for incomplete checks: hard budget ceiling reached — reported
  per the escalation rule; the ceiling was not raised without the owner.

## Phase 1 — live VPS checks, 2026-09-25 (2026-09-26 UTC)

Working SSH credentials and `TELEGRAM_USER_ID` are now present in the owner's
mode-0600 `agent/.env`. Strict host-key verification succeeded. The first
successful login discovered an existing deployment, rather than a blank VPS;
the earlier local-only status below is historical and superseded.

### Inventory and changes

- Ubuntu 24.04.4, root access, 2 vCPU, approximately 3.8 GiB RAM, 2 GiB swap,
  88 GiB free disk. Docker 29.2.1 and Compose 5.0.2 were already installed.
- Existing `/opt/openclaw-production/docker-compose.yml` runs OpenClaw
  2026.9.6 (`eb377ac`), LiteLLM 1.102.1, and PostgreSQL with the same three
  image digests recorded in the local deployment draft. No image was upgraded.
- Initial config validation and secrets audit passed, but security audit found
  one critical issue: missing Control UI allowed origins. The agent also had
  sandboxing off with unrestricted tools, and Telegram used pairing admission.
- Created and verified a native OpenClaw backup before policy edits. Persisted
  it as `backups/phase1-pre-hardening-openclaw.tar.gz`, along with a PostgreSQL
  dump and Compose rollback copies. Server backup directory mode is 0700 and
  files are 0600. No production restore is claimed.
- Native `config set --batch-json` applied explicit localhost/127.0.0.1 UI
  origins, auth rate limiting, chat-only tools (`minimal`, allow only
  `session_status`, deny `gateway`), no browser, disabled elevated execution,
  and a numeric Telegram owner allowlist plus command-owner binding. Removed
  ineffective Docker settings while sandbox mode is off. Restarted Gateway.
- Separated live database and proxy credential files with Compose's raw
  env-file format, preserving the database volume, master/salt keys and virtual
  keys. Recreated only PostgreSQL and LiteLLM. Confirmed PostgreSQL no longer
  receives Anthropic or proxy keys. The old private runtime env remains for
  rollback. The live Docker network layout was retained; the fresh-deployment
  template has additional database-network separation not yet applied live.
- Added the Mac UI helper: an SSH tunnel and the native `dashboard --json`
  single-use `browserUrl` handoff. It opens the link directly in the owner's
  browser without printing bootstrap or shared credentials. No alternate
  authentication implementation was built.

### Objective checks

| Check | Observed result |
|---|---|
| `config validate --json` | Valid, no schema warnings |
| `secrets audit --check` | Clean; all five finding counts zero |
| `security audit --json` after restart | Zero critical, zero warnings |
| Host listeners | 18789, 18790, 3978 on 127.0.0.1 only |
| No-auth `/tools/invoke` request | HTTP 401 |
| Gateway restart | `/healthz` HTTP 200; container healthy |
| `channels status --probe --json` | Telegram polling ready, getMe passed, no status issues |
| Daily-window probe | Temporary $0.000000001/24h key denied HTTP 429 |
| Monthly-window probe | Temporary $0.000000001/30d key denied HTTP 429 |
| Budget DB outage | After DB stop/cache wait, budgeted request denied HTTP 503 (`no_db_connection`) |
| Proxy recovery | DB restored; proxy needed restart; authenticated management healthy afterward |
| Probe cleanup | All three temporary keys deleted with HTTP 200; private probe file removed |
| Native bounded reply | `agent --agent main --session-id phase1-verification --message ... --json` returned `PHASE1_OK`, provider `litellm`, model `claude-sonnet-4-6`, no tools |
| Control UI | Browser visibly connected as Owner; a request in the disposable verification conversation returned `PHASE1_UI_OK` |

The live proxy config has reservation enabled and
`fail_closed_budget_enforcement: true`. Both retained virtual keys show the
requested model allowlist and $2/24h plus $25/30d windows. The owner explicitly
confirmed the independent Anthropic workspace limit is $25. Current proxy
key metadata does not impose a concurrency-one setting; reservation checks
are enabled, while concurrent-admission stress testing remains future work.

Doctor still reports `ok:false` with two documented warnings: `lan` bind
inside Docker (host publication is loopback-only), and Skill Workshop missing
under the intentional minimal profile. Neither is silently counted as a clean
doctor pass; no policy was widened to remove the latter warning.

Observed live key spend changed from $1.345983 on first inspection to
$1.445606 later: an interval increase of $0.099623. This is proxy aggregate
evidence and may include simultaneous owner activity, not an exact per-probe
invoice. The second retained key remains at $0. Keys and raw logs were not
printed. A pre-existing dotenv parse warning at line 16 did not prevent the
required credentials from being read; unrelated dotenv content was retained.

### Gate 1 status

Server access, private Gateway/auth rejection, clean security/secrets audits,
native reply, independent daily/monthly denials and DB fail-closed behavior
have evidence. The native one-time browser sign-in link opened on the owner's
Mac; browser inspection verified Owner/Connected and an actual UI reply in the
disposable test conversation. The authenticated UI tab was kept open as the
handoff. Telegram owner reply and a different account's denial remain pending.
Gate 1 is therefore not marked passed. The owner later asked to proceed with
Phase 2 while those Telegram checks remained pending; that does not convert
them into passes.

Sanitized summary: `evidence/phase1-live.json`. The recovery commands and
private UI access steps are in `RUNBOOK.md`.

## Phase 1 — 2026-09-25 (local preparation; Gate 1 pending)

The owner repeated the instruction to proceed with the next phase after the
Phase 0 status was reported. This authorizes Phase 1 work; it does not turn
unrun production checks into passes. No phase gate is recorded as passed.

### Implemented

- Repaired the deployment draft's LiteLLM config mount and added the native
  maintenance CLI service. Retained existing image digests; their registry
  identity/version is still unverified in this session.
- Split database and proxy secret environment files. Isolated PostgreSQL on
  an internal network; no proxy/database host port is published. Gateway
  activation is explicit and published ports stay loopback-only.
- Added `bin/openclaw-server` for native offline/bootstrap or live CLI use.
- Added `bin/prepare-phase1.py` for fresh private state, a numeric Telegram
  owner allowlist and command owner, disabled Telegram until prerequisites
  pass, and a chat-only tool policy. It refuses existing state. The broad
  later-phase config template and previous staging state are retained.
- Added a non-secret virtual-key request specifying $2/day and $25/month,
  only the selected two models, and concurrency one; added separate secret
  file examples and the execution/evidence sequence in `deploy/README.md`.
- Extended gitignore for deployment secrets, generated state and evidence.

### Evidence and blockers

- Re-read current official Docker, Telegram access, LiteLLM route, tool policy,
  doctor, security and secrets docs. The pinned v2026.9.6 upstream Compose file
  confirms local pre-start commands and the live CLI network namespace.
  Documentation links are in `deploy/README.md`; runtime schema checks remain
  required against the actual pinned image before service activation.
- Inventory confirms neither Docker nor OpenClaw is installed on this Mac;
  local available disk is about 3.4 GiB. No local runtime was installed.
- Local verification passed: shell and Python syntax, JSON/YAML parsing,
  the canonical LiteLLM config mount, loopback-only Gateway publications,
  no proxy/database publication, internal database network, `git diff --check`
  and ignore coverage for generated secrets/state/evidence. This is static
  evidence, not Docker Compose or OpenClaw runtime validation.
- An SSH read-only connection attempt was blocked by the local execution
  sandbox (`Operation not permitted`) before authentication. This is not
  evidence that the VPS is unreachable or that current credentials fail.
- The owner directed credential lookup to `.env`. A workspace file inventory
  found `agent/.env` (mode 0600) and its example. Only variable names/presence
  were inspected. Anthropic and Telegram keys are present, but SSH user/key/
  password fields and a numeric Telegram owner ID are absent. Their values
  were not printed or copied. Requested the missing fields from the owner.
- Anthropic workspace spending cap, both proxy denials, database-outage denial,
  owner/non-owner Telegram checks, Control UI auth, doctor and security checks
  are still pending. No paid request or server mutation has run; cost is $0.

Phase 1 cannot be marked complete until these server/account gates pass.

## Phase 2 — sandbox and approvals, activated 2026-09-25 (2026-09-26 UTC)

### Inventory and preparation

- Re-read current official OpenClaw docs for Docker sandboxing, tool policy,
  elevated execution and exec approvals. The installed 2026.9.6 CLI exposes
  `sandbox explain/list`, `approvals set/get`, and current exec-policy
  controls. The documented Control UI approval surface is Settings → Nodes →
  Exec approvals; connected operator UIs can receive pending approval cards.
- Confirmed the live main session was direct (`sandbox.mode=off`) with only
  `session_status` allowed. The Gateway container had no Docker CLI, socket,
  or sandbox image. Gateway host approvals had no entries and inherited
  `security=full`, `ask=off` defaults. Existing Phase 1 policy denied Gateway
  tools and disabled elevated mode.
- Created a verified native OpenClaw backup and saved the active Compose file
  before preparing this phase. Backup directory is private mode 0700 and
  files are mode 0600 at
  `/opt/openclaw-production/backups/phase2-before-sandbox-20260926T030103Z`.
- Built the default sandbox image from the pinned Debian Bookworm slim digest
  `sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251`.
  The resulting image is `openclaw-sandbox:bookworm-slim`, about 77 MB; build
  succeeded on the 4 GiB VPS. No model request was made.
- Prepared the versioned sandbox Dockerfile, Compose socket wiring, tool
  allowlists, owner-specific elevated settings, and approval defaults in the
  deployment templates. Local JSON/YAML parsing and `git diff --check` passed.

### Live changes and gate status

The initial automated approval review rejected activating the Docker socket
and elevated host-execution boundary because the socket grants host-root-
equivalent Docker control and the broad phase request did not explicitly
authorize that change. After the owner replied “clear” to the exact boundary
and impact summary, the operation proceeded. A verified native backup and
Compose rollback copy were made before the change.

The live Gateway now mounts `/usr/bin/docker` read-only and
`/var/run/docker.sock`; its unprivileged `node` user is in the socket's group.
Only the trusted Gateway has those mounts. The sandbox does not. Every agent
session runs in the Docker backend with session scope and a read/write
workspace. The sandbox uses the pinned Bookworm image, no network, read-only
root, `/tmp`/`/var/tmp`/`/run` tmpfs, all capabilities dropped, no-new-
privileges, 128 processes, 768 MiB memory, 1 GiB memory-plus-swap and one CPU.
The effective tool policy exposes session status, workspace file tools and
sandbox `exec`/`process`; browser, canvas, image viewing, nodes, automations
and Gateway tools are denied. Elevated execution is enabled only for the
configured numeric Telegram owner and still requires a host approval for each
command (`allowlist`, `ask: always`, empty command allowlist, fallback deny).
Elevated mode was returned to off after the probe.

### Verification

| Check | Observed result |
|---|---|
| Compose configuration | `docker compose config --quiet` passed after activation |
| Gateway | Container healthy; `/healthz` HTTP 200; LiteLLM and PostgreSQL also healthy |
| Sandbox runtime | `sandbox explain` reported mode `all`, session scope, Docker backend and writable scoped workspace; `sandbox list` showed one running runtime |
| Runtime constraints | Inspect showed user 1000, read-only root, no network, 768 MiB memory, 1 GiB memory+swap, 1 CPU, 128 PIDs, all capabilities dropped and no-new-privileges |
| Socket isolation | Sandbox had no Docker CLI or socket; its mounts were limited to the scoped workspace and skill content |
| Host-only file probe | An exact synthetic file under `/root` returned Permission denied in the Control UI sandboxed session; the synthetic file was removed afterward |
| Tool exposure probe | Tool search did not expose a Gateway status tool; no Gateway operation was invoked |
| Approval settings | Control UI showed allowlist security, ask always, fallback deny, auto-allow skills off and no pending request |
| Security audit | Zero critical, zero warnings, one informational attack-surface summary |
| Secrets audit | Clean; plaintext, unresolved, shadowed, store-residue and legacy-residue counts all zero |
| Doctor | `ok:false` with two warnings: the container binds `lan` while host ports are loopback-published, and Skill Workshop is unavailable in the sandbox |
| Probe cleanup | Host sentinel removed; no approval-probe marker existed |

Gate 2 is **not passed**. We have not observed a real pending host-exec
approval card, resolved or denied it, or verified timeout/no-UI denial with a
no-side-effect check. The agent declined the synthetic host-exec request as
untrusted chat text, and `/elevated on` in the Control UI correctly failed its
`allowFrom` check because webchat is not an allowed elevation channel. The
owner-only allowlist remains Telegram-only; no broader UI elevation access was
added. The approval settings page was inspected, but that does not count as an
owner interaction with a live approval card. No host command ran and no probe
side effect occurred. Gate 1's owner and non-owner Telegram access checks also
remain pending.

The final config validation passed with no schema warnings. The live service
was restarted only after a private backup; LiteLLM and PostgreSQL were not
recreated. Limited paid model turns were used for sandboxed UI probes; their
individual invoice cost was not separately attributed. No secrets or raw
approval credentials were printed.

## Phase 0 and isolated bootstrap — 2026-09-24 (in progress)

The owner clarified that production must run on an always-on server; this Mac
must not be required for availability. Earlier Mac selection is superseded.
The local installation below is a disposable staging environment only.
Its temporary Node and OpenClaw binaries were later removed to recover disk
space; the private staging state remains in the ignored directory. The server
template was validated against OpenClaw 2026.9.6 before removal.

- Created draft migration and architecture decisions in this directory.
- Read the current official OpenClaw install, Node compatibility, Codex
  harness, ACP, security, doctor and backup documentation. The new phase
  prompts require fresh documentation checks at execution time.
- Host inventory: macOS 15.3.1 arm64; system Node v23.10.0 and npm 10.9.2;
  system `openclaw` and `docker` commands absent. No `~/.openclaw` directory
  detected. Codex and Claude CLIs reported existing logins; Gemini CLI exists
  but its auth was not checked. None is connected to this OpenClaw instance.
- Existing AgentAI code and database were not modified, archived or reset in
  this phase. Its purchase execution remains disabled.

### Isolated work completed

- Staged Node 26.1.0 and OpenClaw 2026.9.6 in gitignored workspace folders.
  The system Node install remains 23.10.0. Created an isolated baseline state
  and workspace with `openclaw setup --baseline`.
- Disabled system-browser profile cookie import, Bonjour multicast discovery,
  automatic memory dreaming, recurring heartbeat, and elevated host exec in
  the isolated config. Generated a gateway token, moved it into OpenClaw's
  protected store, changed config to a store SecretRef, and removed temporary
  config backups from this new isolated state. The secrets audit reports zero
  plaintext, unresolved, shadowed, store-residue and legacy findings.
- A non-secret, versionable config example is in `config/openclaw.example.json`.
  The actual config and token stay in the ignored state directory.
- `config validate --json` passed for the active config and tracked template.
  Final `secrets audit --check` was clean. Final `security audit --json`
  reported zero critical and one conditional warning about reverse-proxy
  trust if the loopback UI is later proxied. Doctor reports the intentionally
  disabled browser cookie import and a node-onboarding URL warning because
  the gateway remains loopback-only.
- Started `gateway run --port 18790`; `/healthz` returned HTTP 200. Stopped it
  cleanly. It made no model, Telegram, Google, GitHub or payment call.
- `openclaw backup create --verify` produced a verified archive of the isolated
  state and workspace. `backup restore --target` succeeded into a fresh
  `restore-test/` directory without touching active state. The archive is
  gitignored and mode 0600 under a mode-0700 directory; it is **not encrypted**
  and must not be shared or treated as a secure off-site backup.

### Open gates

- Provision and access the always-on server, then perform the deployment and
  restart/recovery acceptance checks there.
- The owner supplied an existing IONOS Ubuntu 24.04 VPS at `69.48.206.62`
  (2 vCPU, 4 GiB RAM, 120 GiB disk). SSH port 22 responds and its ED25519
  host key matches this Mac's recorded key. Password-only SSH rejected the
  initial password displayed by IONOS; the same login failed at the IONOS
  remote console. An `ubuntu` key-based SSH login also failed. No server
  command or installation has run. The owner must provide a current sudo
  credential/authorized SSH key or complete IONOS's root recovery flow.
- Sandbox tests require the server's Docker runtime. Colima, Docker CLI and
  Lima were briefly installed on the Mac for a canceled local sandbox test,
  then uninstalled after the server clarification. Colima could not unpack
  its VM image because the Mac had less than 1 GiB free; its failed image was
  removed. No Mac container runtime is required for production.
- The owner selected the Anthropic API key route and Telegram. Both keys were
  found in `agent/.env` (mode 0600) and imported into the isolated OpenClaw
  secret store without displaying values. The config uses SecretRefs and
  validates. Sonnet 4.6 is the primary model, Haiku 4.5 the utility model,
  and the model picker is limited to those two Anthropic refs. No paid model
  request has been made.
- The Telegram token passed `getMe` for `@Keighobad_bot`. The staging config
  enables DM pairing and disables groups. A separate Telegram poller returns
  HTTP 409 to our `getUpdates` request, so the numeric owner ID and pairing
  cannot yet be verified. The owner has been asked for their numeric ID.
- A hard daily/monthly budget mechanism remains to be demonstrated. Usage
  visibility alone does not satisfy this gate. The owner chose $2/day and
  $25/month; production paid requests remain gated.

No paid model request was made. Only the Telegram `getMe`, `getWebhookInfo`,
and `getUpdates` endpoints were used to inspect the bot. Phase 0 review is not
complete, and later gates have not been run.
