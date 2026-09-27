# OpenClaw operations runbook

Production belongs on the IONOS VPS and must work while the Mac is off. The
deployment plan is [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md). The temporary
Mac Node/OpenClaw binaries were removed to recover disk space. Its private
staging state and disposable restore clone were removed during owner-authorized
cleanup. Current evidence and recovery backups remain; production state is
solely on the VPS.

## Server checks after deployment

### Current live VPS

The existing live deployment is `/opt/openclaw-production/docker-compose.yml`.
Its container names are `openclaw-production-{openclaw-gateway,litellm,postgres}-1`.
Use these commands on the VPS:

```sh
cd /opt/openclaw-production
docker compose config --quiet
docker compose ps
docker exec openclaw-production-openclaw-gateway-1 node dist/index.js config validate --json
docker exec openclaw-production-openclaw-gateway-1 node dist/index.js doctor --json
docker exec openclaw-production-openclaw-gateway-1 node dist/index.js secrets audit --check
docker exec openclaw-production-openclaw-gateway-1 node dist/index.js security audit --json
```

Doctor currently reports two deliberate restrictions: container-side LAN bind
behind host loopback publications, and disabled Skill Workshop authority under
the chat-only profile. Do not widen policy just to remove these findings.

### Open the owner's Control UI

On the Mac, from this repository:

```sh
.venv/bin/python openclaw-project/bin/open-control-ui.py
```

The helper reads the private SSH login from `openclaw-project/.env`, creates a loopback
tunnel, asks the native `dashboard --json` command for `browserUrl`, and opens
that single-use sign-in link directly in the browser. Confirm the displayed
pairing destination to sign in this Mac. No shared Gateway token is printed.
The clean address is `http://127.0.0.1:18789`; the bootstrap expires in ten minutes.
See [native dashboard handoff](https://docs.openclaw.ai/cli/dashboard).

Close the tunnel without stopping the server runtime:

```sh
ssh -S openclaw-project/tmp/control-ui-ssh.sock -O exit root@69.48.206.62
```

### Fresh deployment bundle

For the Phase 1 bundle, follow [deploy/README.md](deploy/README.md) first.
Run from `openclaw-project/` on the VPS, after the Gateway is running:

```sh
docker compose -f deploy/docker-compose.production.yml config --quiet
docker compose -f deploy/docker-compose.production.yml ps
sh bin/openclaw-server live config validate
sh bin/openclaw-server live doctor
sh bin/openclaw-server live secrets audit --check
sh bin/openclaw-server live security audit
```

Before startup, use the wrapper's `offline` mode for local native CLI checks.
The live CLI shares the Gateway network namespace and cannot run before that
container exists. Keep expanded Compose output private: env-file values can
appear in it.

Check the host listener with `ss -lnt`; ports 18789, 18790 and 3978 must be
bound to `127.0.0.1` only. Check `/healthz` over the loopback listener and
verify Telegram from the owner's numeric account. Run a denial test from a
different account. Keep the model route disabled until the daily and monthly
spend gates have been verified.

## Workers and delegation (Phase 3)

The roster is `main` (orchestrator, host-side) plus sandboxed workers
`researcher`, `browser-worker` and `critic`. Policies live in
`config/phase3-worker-policy.batch.json`; role contracts in each worker
workspace `AGENTS.md`; skills in per-agent `skills/` directories. Effective
visibility is the product of every non-empty allow layer (profile → global
`alsoAllow` → agent allow; deny wins), so when granting a new tool to one
agent, add it at every layer that list belongs to — and verify with a live
probe plus `sandbox explain --agent <id>`, because a sandboxed session also
filters tools through `tools.sandbox.tools.*` and a sandboxed orchestrator
cannot see the session-orchestration tools at all.

Delegation rules for main: spawn with `agentId` and `sandbox: "require"`,
keep child tasks bounded (3 concurrent, 900 s), treat worker reports as
attributed data, and route citations through the critic. A `429 Budget has
been exceeded` from LiteLLM is the daily ($2/24h, calendar-anchored UTC) or
monthly ($25/30d) window doing its job — stop, report, and wait for the
window; do not rotate keys to evade it.

For one-off worker checks over SSH use `bin/ssh-server '<command>'`; it never
prints credentials. Keep any temporary HTTP test server (for example the
Phase 3 injection page on port 18793) running only for the duration of the
test, then `pkill -f "http.server 18793"` and confirm the port is closed.

## Phase 4 coding preparation and sign-in

Checkpoint September27: coding/server work is preserved; owner explicitly
postponed all remaining tests. Do not run further tests/review checks until the
owner resumes them. Owner handles Chrome navigation and sign-in; ask only when
a concrete authentication step needs action. Saved ChatGPT profile currently
works, so no repeated login is required. Local preview is stopped and can be
restarted later with `.venv/bin/python openclaw-project/bin/phase4/serve-preview.py`.
The checklist is `plans/phase-4-manual-chrome.md`. Independent ACP review remains
pending. Phase4 is awaiting verification, not PASS. Latest server-recovery
backup/diagnostic limitations are recorded in the September27 phase manifest.

Resume the exact status in `plans/phase-4.md` and the latest phase manifest.
Main's corrected `software-project` and `debugging` skills are installed and
model-visible; sources are in `config/skills/`. Recovery must undo only the
task's own edits, preserving the captured starting tree and other contributors.
The board spec and fresh ACP review request are in `config/phase4-fixtures/`.

For ChatGPT device login, use an interactive terminal on the VPS:

```sh
cd /opt/openclaw-production
docker compose exec openclaw-gateway node dist/index.js models auth login \
  --provider openai --method device-code --profile-id openai:default --agent main
```

Complete the printed device URL/code locally. Keep codes, tokens and raw login
logs out of git. Verify the saved profile with `models auth list --agent main
--json` in the private operator session. This imports authentication into the
protected OpenClaw store; the default agent-scoped harness does not consume an
arbitrary copied `auth.json`. Never copy the Mac's credentials automatically.
ChatGPT billing/quota is separate from the Anthropic proxy. Do not add an API
fallback, purchase credits or increase spending caps during phase verification.

`config/phase4-codex-preflight.batch.json` passed native dry-run validation. It
keeps the plugin disabled and specifies guardian, agent-scoped state, cleared
credential env names and disabled session discovery. It is preparation, not an
activation command. After login, discover supported models and configure a
dedicated builder whose project tools stay inside Docker. Guardian alone does
not protect host-readable credentials. Reuse the pinned Gateway image as the
builder tool image if desired: its Node 24.19.0 passed isolated container probes
without credentials/state/socket mounts. The default Debian tool image lacks
Node. Keep the existing researcher/critic tool images and policies scoped.

The official browser image was built from the `v2026.9.6` source files
`scripts/docker/sandbox/Dockerfile.browser` and
`scripts/sandbox-browser-entrypoint.sh` under
`/opt/openclaw-production/phase4-browser-image`. Image tag:
`openclaw-sandbox-browser:phase4-2026.9.6`; record the exact image ID in evidence.
The native contract label must equal `2026-05-12-cdp-relay-auth`. Use a dedicated
browser-worker sidecar with `allowHostControl: false`, noVNC off, bounded
resources and empty profile. Include the browser tool at every relevant allow
layer and remove only the matching global/sandbox deny; other agents keep
explicit browser denies. Validate and inspect effective policy before launch.
Operator `browser` CLI calls target the host browser and do not prove worker
delegation. Never bypass the sidecar's authenticated CDP relay.

ACP review uses the acpx `claude` adapter, a fresh session and a read-only tested
snapshot. The Anthropic CLI backend is a different route. Prove auth, proxy
compatibility and model/budget routing before use; neither a working directory
nor `approve-reads` alone establishes OS isolation. Keep OpenClaw core/plugin
MCP bridges disabled for the reviewer. Record unresolved setup requirements as
blocked, and finish after Gate 4 only when all behavioral evidence exists.

## Backup and recovery

Private pre-change backups are under `/opt/openclaw-production/backups`:
`phase1-pre-hardening-openclaw.tar.gz`, `phase1-budget-db.sql`, and the
pre-change Compose files. The directory is mode 0700 and files are mode 0600.
The native archive was verified; a production restore has not yet been tested.

After a budget database outage, verify PostgreSQL with `pg_isready`. In this
session LiteLLM needed a restart to recover its Prisma connection:

```sh
docker start openclaw-production-postgres-1
docker exec openclaw-production-postgres-1 pg_isready -U litellm -d litellm
docker restart openclaw-production-litellm-1
```

Verify proxy management health before retrying model work. Preserve
`LITELLM_SALT_KEY`, master key, virtual keys and the PostgreSQL volume during
recreation. Never use `down --volumes` for recovery. The old shared runtime
environment file is retained privately for rollback, but current services use
separate raw-format credential files; PostgreSQL receives no provider/proxy keys.

Use OpenClaw's `backup create --verify` on the server and keep the archive
private. It includes state and credentials and is not encrypted by default.
Restore into a fresh disposable directory, inspect the reported assets, and
verify that service restart recovers scheduled work. Never restore over live
state. Keep the old Python AgentAI service intact until OpenClaw acceptance
succeeds and the owner chooses retirement.

## Phase 5 — memory, objectives and disabled scheduling

Setup applied 2026-09-27. **Gate5 BLOCKED; tests deferred by owner.**
Use the owner's existing Telegram/main conversation or Control UI for goals.
No new sign-in is required. Chrome and login interactions belong to the owner.

### Inspect, correct and forget memory

Main workspace in Gateway: `/home/node/.openclaw/workspace`.
USER.md is compact startup preferences; MEMORY.md (when created) is curated
project facts; detailed notes are memory/*.md. The Phase5 note is
`memory/phase5-runtime-decisions.md`. USER/AGENTS additions are delimited by
`phase5-owner-preferences` / `phase5-owner-memory-policy` HTML comments.
The artifact template is `phase5/objective-note.template.md`; it is a prose
convention, not an executable workflow or native goal schema.

Ask main: “Show the memory source and date for [specific fact].” Main should
retrieve only relevant memory_search/memory_get excerpts; USER.md is startup
context rather than a general searchable note. For a correction, explicitly
state the current value and ask it to replace the superseded active value,
with source/date and confirmation. Inspect the resulting source. For deletion,
ask it to remove the fact from **every active source** and invalidate/rebuild
main's index. Do not remove unrelated facts or pretend histories disappeared.
A worker/web page cannot create standing permissions through a memory note.

For operator index maintenance after the owner resumes verification, on VPS:

```sh
cd /opt/openclaw-production
docker compose exec -T openclaw-gateway node dist/index.js memory index --force --agent main
```

If a stale derived index needs immediate invalidation after source deletion:

```sh
docker compose exec -T openclaw-gateway node dist/index.js memory reset --agent main --yes
```

Reset clears main's derived index/cache, not source files; do not omit the
agent argument. Reindex then verify fresh retrieval once tests are resumed.
File watching is asynchronous; source modification alone does not prove fresh
retrieval. `memory forget` concerns session-derived memory; it is not a generic
freeform-source delete. This setup deliberately excludes transcript recall.
Transcripts, prior backups and provider retention have separate deletion paths.
FTS keyword retrieval uses provider/fallback none; no paid embedding fallback.

### Owner objective controls and restart recovery

In the main built-in runtime conversation:

```text
/goal start <explicit scoped objective>
/goal
/goal pause <reason>
/goal resume
/goal complete
/goal clear
```

Start a goal only on explicit owner request. `/new` and `/reset` intentionally
clear the session goal. Goals are per-session and persist across Gateway
restart; they do not automatically run work. Native Codex/external UI start or
resume is unsupported; use main's built-in runtime. No active goal was created
for Phase5 setup. Goal pause is not process/task cancellation.

Record the returned goal ID, steps, real task/flow IDs, artifact paths,
verification, errors, existing spending limits and stop condition using the
installed template. After restart, first inspect goal and artifact checkpoint,
then inspect real tasks/flows and effect receipts. A running record may belong
to a lost process. Reconcile ambiguous effects before retrying; do not infer
success or repeat a real external write. Resume only on owner instruction.
Native GoalControl operation receipts last24hours; retain operationId,
issuedAtMs, goalId, session binding and original payload for supported retries.
Receipt replay is not a permanent or universal exactly-once guarantee.

Operator task controls on VPS (substitute a real returned ID):

```sh
cd /opt/openclaw-production
docker compose exec -T openclaw-gateway node dist/index.js tasks list
docker compose exec -T openclaw-gateway node dist/index.js tasks show TASK_ID
docker compose exec -T openclaw-gateway node dist/index.js tasks cancel TASK_ID
docker compose exec -T openclaw-gateway node dist/index.js tasks flow list
docker compose exec -T openclaw-gateway node dist/index.js tasks flow show FLOW_ID
docker compose exec -T openclaw-gateway node dist/index.js tasks flow cancel FLOW_ID
```

Cancellation must stop later steps and reconcile children until terminal.
Clearing a goal alone does not cancel children or automations. Task states are
queued/running/succeeded/failed/timed_out/cancelled/lost; “paused” is a goal
state, not a task state. Waiting approval needs a supported managed checkpoint.
Native TaskFlow stores records; CLI list/show/cancel is not a workflow runner.
Mirrored child flows are tracked natively; no managed controller is activated.
A supported controller would need to reload flow revision, sticky cancellation,
actual child outcomes and receipts before resuming. Do not build a replacement
engine merely to claim restart recovery. Normal finished task/flow retention
is7days (lost tasks24hours); essential project receipts belong in artifacts.

### Phase5 schedule controls

Job ID: `4435c5f6-ca9e-46a0-9f1e-24edb5202c27`.
Declaration key: `phase5-quiet-status-v1`. **Disabled; never run for Phase5.**
Declared daily08:00 America/Los_Angeles, exact no stagger, isolated critic.
Script payload only, timeout5seconds, toolBudget1, toolsAllow session_status.
Delivery none, no model turn; source returns state only with no notify/wake.
Stored wakeMode is native default now; runtime quietness remains unverified.
Finite job cap is stricter than interactive tools, but effective runtime and
unattended approval behavior must be proven before enabling it.

```sh
cd /opt/openclaw-production
docker compose exec -T openclaw-gateway node dist/index.js automations list --all --json
docker compose exec -T openclaw-gateway node dist/index.js automations disable 4435c5f6-ca9e-46a0-9f1e-24edb5202c27
```

Leave disabled while tests are deferred. Only after explicit owner verification
resumption and satisfactory acceptance, the enable command is:

```sh
docker compose exec -T openclaw-gateway node dist/index.js automations enable 4435c5f6-ca9e-46a0-9f1e-24edb5202c27
```

Installed scheduler capacity is fixed8; `cron.maxConcurrentRuns` is unsupported.
There is no applied global concurrency1 setting. Do not patch the scheduler or
claim a single-job reservation proves global concurrency or exactly-once
execution. A single-run concurrency requirement needs supported native controls
or a revised owner-approved requirement before schedule acceptance.
Four older enabled weekly model jobs remain; no promise of zero background
spend. All12 preexisting jobs were preserved. Existing spending caps unchanged.
No restricted-action schedule was tested. Keep restricted tools denied;
missing unattended approval must safely deny/wait, never auto-approve.

### Phase5 rollback and deferred acceptance

Private pre-change **field/source backup**, not a whole-state archive:
`/opt/openclaw-production/backups/phase5-config-20260927T180152Z`.
Restore untested. Captured config and source files may contain private content;
do not publish the backup. Earlier Phase4 stopped-state archive is separate.

1. Disable the above Phase5 job. For removal of only this job:
   `node dist/index.js automations rm 4435c5f6-ca9e-46a0-9f1e-24edb5202c27`
   inside Gateway. Preserve all preexisting jobs.
2. Compare current authored fields with
   `config/phase5-native-memory.batch.json`. Restore each prior field value
   from the private original config using native config set; unset a field
   originally absent through native config unset. Stop/reconcile if newer
   unrelated edits overlap. Do not replace the whole current config.
3. Remove only this phase's delimited AGENTS/USER sections; preserve later
   owner edits. Remove this phase's new memory note and artifact template,
   preserving actual future project checkpoints. Invalidate/rebuild main's
   derived index if needed; histories/backups remain separate.
4. Validate native config and exact readback. Do not run deferred fixtures.

Remaining acceptance: selective recall with12 irrelevant facts, correction,
active deletion, hostile candidate, three-step restart recovery, ambiguous
checkpoint receipt reconciliation, cancellation, actual schedule/timezone,
unattended approval denial/expiry, diagnostics/security and backup restore.
Use synthetic/isolated state and bounded model probes only after the owner
explicitly resumes tests. No Chrome automation by this coding agent.
See [Phase5 plan](plans/phase-5.md) and
[manifest](evidence/phase-5/20260927T180152Z/manifest.json).

## Phase6 — account connection and read-only operation

Setup evidence: [manifest](evidence/phase-6/20260927T200739Z/manifest.json).
Both `google-readonly` and `github-readonly` are currently disabled. The account
email is owner-provided, not verified provider identity. An installed image and
valid config do not establish account access. No paid acceptance suite is needed
to finish sign-in; lightweight identity and scope readback are still necessary.

### Google sign-in

1. Create or select an owner-controlled Google Cloud OAuth **Desktop** client;
   enable Gmail API, Google Calendar API and Drive API. Follow Google's current
   consent requirements. Install its downloaded JSON on the VPS at
   `/opt/openclaw-production/integrations/google/private/client-secret.json`,
   owner1000:1000, mode0600. Directory mode0700. Never put its contents in chat,
   a repository, memory, or worker workspace.
2. The operator-only helper `bin/phase6/authorize-google.py` calls the installed
   connector's native `start_google_auth` tool, using read-only service scopes.
   It is staged in the private Phase6 artifact directory. Run from a trusted
   interactive SSH terminal, not the agent exec tool. The one-off container
   shares host networking solely for its loopback OAuth callback; normal agent
   connector execution uses the default isolated Docker network.
3. From the browser computer, forward the callback port to the VPS:
   `ssh -N -L 8000:127.0.0.1:8000 <ssh-user>@69.48.206.62`.
   Keep the trusted operator auth process alive while completing consent.
   Check the printed callback port; if the connector selects another port,
   forward that exact port instead. Do not paste callback codes/URLs into chat.

```sh
cd /opt/openclaw-production
# Set the supplied owner account email in this trusted terminal only.
export OWNER_GOOGLE_ACCOUNT='<owner-google-email>'
docker run --rm -it --network host --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --user=1000:1000 --pids-limit=128 \
  --memory=384m --cpus=0.5 --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  --mount type=bind,src=/opt/openclaw-production/integrations/google/private,dst=/data \
  --mount type=bind,src=/opt/openclaw-production/integrations/phase6/20260927T200739Z/authorize-google.py,dst=/operator/authorize-google.py,readonly \
  --env USER_GOOGLE_EMAIL="$OWNER_GOOGLE_ACCOUNT" \
  --env WORKSPACE_MCP_LOG_DIR=/tmp/logs --entrypoint python \
  sha256:17620499dba778fa67572e0ac5f93ae59c570734901b5671ddfbb1197fc0fc4c \
  /operator/authorize-google.py
```

The helper itself is prepared/import-checked but its OAuth flow is unexecuted.
Verify returned provider identity and stored scopes before activation: only
openid, userinfo.email/profile, gmail.readonly, calendar.readonly and
drive.readonly expected. Readonly Drive includes all accessible Drive files;
selected-item request discipline is not a per-file credential restriction.
Never treat a configured email or token filename as provider identity proof.

After protected identity/scope readback, enable through native commands:

```sh
docker compose exec -T openclaw-gateway node dist/index.js mcp configure google-readonly --enable
docker compose exec -T openclaw-gateway node dist/index.js mcp doctor google-readonly --probe --json
```

Probe is tool-catalog/connection verification, not an expensive model test.
Confirm only the selected read tools are exposed to researcher. Native config
publish/hot reload applies changes; CLI `mcp reload` alone does not refresh a
separate Gateway process. Start a new owner turn after changed tool policy.
Reconnect with the same operator helper. Revoke Google app access via the
owner's Google account permissions, disable the connector, then remove only
that account's token files after identifying them privately. Never revoke an
unrelated client or remove the entire shared directory indiscriminately.

### GitHub sign-in and repository limits

Repository names remain missing; repo origin is not account authorization.
Prefer a fine-grained PAT restricted to the chosen repositories: metadata,
contents, issues and pull requests read only. Give it an expiry. Installed MCP
headers/env do not accept SecretRef objects. The supported protected path is
an auth profile plus `auth: oauth`/`oauth.authProfileId` bearer mapping.
Native `models auth paste-token --provider github --profile-id github:phase6
--agent researcher --expires-in 30d` accepts the token in a trusted interactive
terminal; use an expiry no longer than the actual token's lifetime. Provider
token/profile compatibility must be verified before binding that profile to
this connector; do not claim account access merely from saving a profile.
Do not insert literal tokens into `mcp set` arguments, tracked config or chat.
Broad OAuth credentials are
not silently substituted for repository restriction. Hosted MCP authentication
and identity endpoint compatibility remain unverified.

After identity/scope checks and protected auth binding, use native
`mcp configure github-readonly --enable` and `mcp doctor github-readonly --probe`.
Revoke the credential at GitHub Settings → Developer settings → Personal access
tokens → Fine-grained tokens; disable the connector and remove only its native
auth profile/binding. Scope reduction may require issuing a replacement
restricted token and swapping its protected reference before revoking the old one.

### Boundaries, diagnostics and rollback

Reader: researcher only. Main gets attributed summaries and links. No provider
write tools, automatic inbox polling or integration-triggered jobs are enabled.
Email/event/repository drafts are local workspace proposals. Denied/expired
auth must return reconnect-required without fallback to a broader account.
Writes remain unavailable until a separately authorized supported path exists.

Private pre-change config and main/researcher instruction backups:
`/opt/openclaw-production/integrations/phase6/20260927T200739Z`.
Disable both definitions with native `mcp configure <name> --disable` before
rollback. Remove only those two definitions with `mcp unset <name>`. Restore
the11 authored fields from the backup using native set/unset, reconciling any
later edits. Remove only Phase6-delimited instruction blocks. Preserve existing
workers, jobs, budgets, OAuth profiles, memory and owner content. Removing an
MCP definition does not itself revoke a provider token.

Static setup audits: health200, config valid, security0critical/2baseline
warnings (profile overrides and model tier), existing OAuth legacy residue1;
no plaintext/unresolved/shadowed/store-residue findings. General Doctor,
provider reads/refresh, boundary/injection/outage fixtures and restore are
deferred. Gate6 remains BLOCKED by missing authentication/repository selection
and unrun acceptance. Existing enabled jobs may still incur unrelated spend.
