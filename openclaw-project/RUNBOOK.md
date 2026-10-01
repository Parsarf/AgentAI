# OpenClaw operations runbook

## Customer-platform foundation and accounts — product Phases1–3

Private source/config/start/check/rollback instructions are in
[platform README](platform/README.md) and [deployment guide](platform/deploy/README.md).
The temporary server smoke for product Phase2 was cleaned up; no persistent
platform listener/customer activation was installed. Existing owner services
remain the live system. New platform gates deny all execution/provisioning/
billing/Telegram/uploads until the corresponding subsequent phase passes.
Use product/plans records under `plans/product/`, not historical phase numbers.
Owner-selected offer/limits are in [product contract](../product/CONTRACT.md);
new customer caps are never applied to existing owner keys during preparation.

## Product Phase3 account operations (prepared, private)

[Account layer](platform/accounts/README.md) and [Phase3 record](plans/product/phase-03.md)
cover verified identity/session recovery, scoped operator MFA/grants and required
audit. App unit now targets private Gunicorn; this is a deployment bundle, not an
installed public sign-in. SMTP is disabled; host CLI/mail worker must not invite
real customers/send messages without authorization. Generic recovery queues IDs,
never codes; crashed running/uncertain mail jobs need reconciliation, not retry.

Bootstrap/migrate only dedicated private app state with a random private session
secret. Never use owner `.env` as app environment. Verify loopback TLS proxy
header overwrite and actual server resource envelope before installing. Retention
maintenance/alerts are prepared, not scheduled:180-day minimal audit,90-day chat
projection tombstones. Native erasure/export/account deletion and restore replay
must be built in6/8/10/14 before affected activation. No support impersonation,
unrestricted customer content access or application Docker/cloud authority.

Rollback only platform source/private DB; incompatible schema needs isolated
snapshot restore/current access reconciliation, not owner/proxy/native restore.
Force reauthentication after access-state recovery. Full acceptance remains15;
next build phase4 requires a new request. No account-layer live service exists yet.

## Phase 4A Jev research layer (inactive)

There is currently no Jev research plugin, toggle, or decision log in
production. `web_fetch` is the unchanged path. The planned one-switch
configuration is `JEV_RESEARCH_ENABLED=false`; do not set it true until
Gate 3, proxy billing, privacy/injection, paired quality, and live fallback
tests in `plans/phase-4a.md` pass. When deployed, its host-only JSONL log
location and LiteLLM Jev spend query must be added here and verified live;
unknown Jev spend must never be shown as zero. The one-step rollback will
turn that switch off and reload the plugin, with a live equality check against
plain `web_fetch`. Interactive browser decisions remain Phase 7A.

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

## Operations backup & recovery (Phase 7)

- Nightly operator backup: `openclaw-ops-backup.timer` (03:17 UTC ±5m, host
  systemd — separate from agent authority). Runs
  `/opt/openclaw-production/bin/ops-backup.sh`: native
  `backup create --verify` archive plus a LiteLLM `pg_dump` (spend history
  and virtual-key identity) plus SHA256SUMS into
  `/opt/openclaw-production/backups/ops/` (dir 0700, files 0600). Retention
  keeps the newest 14 own `oc-ops-*` sets; historical `phase*` archives are
  never pruned. No model calls, no outbound messages.
- Freshness: `bin/ops-status.sh` writes `backups/ops/status.txt`; exit 0 =
  fresh (RPO target 24 h, proposed) / 1 = stale or error. Local report only
  — no delivery authority is configured, so alerts are intentionally absent.
- Isolated restore drill: `bin/ops-restore.sh <archive>` verifies and
  restores into `restore-drill/<ts>/clone` offline and refuses to boot it.
  Before any start, sanitize the clone (telegram channel off,
  automations/cron off, delivery off, distinct port/db) using
  `OPENCLAW_STATE_DIR`/`OPENCLAW_CONFIG_PATH` + `config set`, then
  `config validate`. Never overwrite live state for a drill.
- Rollback sequence: quiesce gateway → restore chosen archive to a fresh dir
  → point state/config at the restored assets → offline `doctor` → start.
  LiteLLM spend history/key identity restore from the nightly `pg_dump`;
  never use `down --volumes`; preserve `LITELLM_SALT_KEY`/master key.
- Off-host encrypted retention: **PENDING owner** (destination + key
  custody). Prepared options: `openclaw backup git --remote <private>` or
  an encrypted rclone target. Do not add a paid storage account without
  approval.
- RPO 24 h / RTO 30 min are proposed initial targets until the owner picks
  others. Acceptance evidence belongs to Phase 10.

## Private ops dashboard (Phase 8)

- `openclaw-dashboard.service` on the VPS: owner-only, read-first ops
  overview (gateway/proxy/db health, containers, LiteLLM spend vs the
  configured $2/$25 targets, Phase 7 backup freshness, pending approvals,
  connector state, app audit). Loopback `127.0.0.1:18795` only, stdlib
  Python, hardened systemd unit (200 MB memory cap). Source:
  `openclaw-project/dashboard/app.py`, deployed to
  `/opt/openclaw-production/dashboard/`.
- Owner access: SSH tunnel `ssh -L 18795:127.0.0.1:18795 <user>@69.48.206.62`,
  then http://127.0.0.1:18795. The app password is the file
  `/opt/openclaw-production/dashboard/owner-secret` (0600) — read it over
  SSH; it is never displayed by the app.
- Stop/start/rollback: `systemctl disable --now openclaw-dashboard` ( +
  remove unit + delete the directory to fully roll back). `POST /revoke-all`
  regenerates the session secret and kills every live session.
- Mutating controls (chat, resets, approval resolution, connector toggles,
  uploads, provisioning) are server-side disabled with visible reasons;
  native approvals are resolved through Telegram/Control UI as before.

## Browser optimization adapter (Phase 9 — DISABLED)

- `openclaw-project/browser-opt/` holds the Jev action-selection adapter
  (`jev_adapter.py`, pinned `jev-1.13.0` via `POST /v1/systemone`), pinned
  `config.json` (master kill switch `"enabled": false`), offline unit tests
  (19, no network), dev + held-out synthetic fixtures, and
  `compare_runner.py`.
- Kill switch: `config.json "enabled": false` makes `decide()` return
  `route_disabled` without any network call; `compare_runner.py
  --route optimized` additionally refuses without `--enable-optimized`.
  Rollback = delete the directory; the runtime never loaded it.
- Fallback: the existing browser-worker route; fires only when the
  optimized route executed nothing (no duplicate effects).
- NOT wired to any runtime yet: no TypeSafe account/credential exists
  (separate owner decision and billing), and the worker→adapter transport
  (host service / bridge allowlist / native plugin) is an open gap recorded
  in `plans/remaining-build-items.md` #9. Provisional thresholds
  (0.5 floor / 0.7 act) are settings, not measured claims; calibration and
  the 30-scenario comparison belong to Phase 11 under explicit owner
  authorization.

## Web search and browser tool status (2026-09-28)

- **Browser tool: ENABLED for `browser-worker` only.** `browser.enabled`,
  `browser.evaluateEnabled=false`, sandbox browser via pinned
  `openclaw-sandbox-browser@sha256:6752…` (contract
  `2026-05-12-cdp-relay-auth`; the gateway launches per-session browser
  containers and relays authenticated CDP itself). Grant layers touched:
  agent allow +, agent deny −, `tools.sandbox.tools.allow` +, and `browser`
  removed from BOTH global denies (`tools.deny`, `tools.sandbox.tools.deny`)
  — deny wins over every allow layer, which hid the tool initially. `main`
  keeps its own deny; critic lacks the allow. Live probe: browser-worker
  opened example.com, snapshot heading returned, per-session browser
  container spawned from the pinned digest.
- **Brave search: ENABLED for `researcher` only** as the
  `brave-search__brave_web_search` MCP tool. The official Brave MCP image is
  pinned to `docker.io/mcp/brave-search@sha256:f58a5c22c1196ec7bd1ca586ce216f2334fc298550ddcf652c0e8adb6d256d78`.
  Gateway launches it through `/usr/local/bin/docker` with a read-only root,
  dropped capabilities, resource limits, and no published port. It reads only
  `/opt/openclaw-production/integrations/brave/private/api-key` (owner 1000,
  mode 0400) through a read-only mount; no key is stored in MCP config. Its
  server and native tool filters expose only `brave_web_search`. Search is
  read-only and auto-approved for researcher. Main and all other workers deny
  the MCP namespace. `mcp doctor brave-search --probe`, `mcp probe
  brave-search --json`, a direct Brave API call, and one researcher turn passed.
  The old `BRAVE_API_KEY` gateway env entry was removed; the mounted file is
  the active credential location.
- **Native `web_search`: disabled.** This build rejects Brave as a native
  provider ("install or enable plugin brave"). Use the MCP tool for Claude
  workers. A different supported native provider would need its own credential.
- **Brave rollback:** `bin/connect-tool disable brave-search`, then
  `bin/connect-tool remove brave-search` if removal is required. The private
  pre-change config and researcher instruction backups are under
  `/opt/openclaw-production/integrations/connector-backups/20260928T190244311040Z`;
  restore only the Brave-authored fields and instruction text, preserving later
  edits. Removal does not revoke the Brave API key. Rollback (browser): revert
  the seven paths from the pre-p11 backup archive.

The key appeared in a diagnostic tool transcript during installation. Rotate
it in the Brave dashboard. From a trusted interactive VPS terminal, run
`python3 /opt/openclaw-production/integrations/brave/rotate-key.py` and enter
the replacement key at its hidden prompt. From the Mac, run
`bin/connect-tool check brave-search`, then make one bounded search before
revoking the old key. Never put the new key in chat, a shell argument, or
tracked configuration.

## Phase 4A Jev research layer — CORRECTED status (2026-09-28 ~22:10 UTC)

Supersedes the earlier "no plugin exists" note. Current truth:

- `jev-research` plugin source: `research-opt/` (Python reference adapter +
  tests, and the deployed Node middleware `plugin/index.mjs` with 10+node
  tests green). Staged at `openclaw-state/extensions/jev-research/` and
  config-enabled — **but the gateway does not load it at runtime** (absent
  from the startup plugin list; suspected manifest/entry contract mismatch
  in `openclaw.plugin.json`). This is the one open defect.
- Toggle: `openclaw-state/jev-research/config.json` `{"enabled": true|false}`
  (currently **false**). Decision log:
  `openclaw-state/jev-research/decisions.jsonl` (0600; empty — middleware
  has never fired). Jev key: disposable `phase4a-jev-eval` virtual key
  ($0.05 cap) mounted read-only at `/run/secrets/phase4a-jev-eval.key`;
  Jev endpoint `http://litellm:4000/typesafe/v1/systemone` (verified
  reachable, `jev-1.13.0`, $0.000011676 probe charge recorded).
- Fail-open is proven: with the plugin inert, researcher fetches return the
  unmodified baseline result.
- **Layer verdict: NOT PROMOTED.** Paired comparison (15 cases) not run
  within the authorized window; per the frozen gate the toggle stays off.
- Budget: temporary $10/24h auto-restores to $2 at 22:29 UTC via
  `phase4a-budget-restore.timer` (verified armed). Verify with
  `config get`-style LiteLLM key readback after the fire.
- To resume: fix the plugin load contract (read the plugin loader source for
  the expected manifest fields), confirm `jev-research` appears in the
  startup plugin list, then run the frozen 15-case paired comparison under
  a fresh owner-authorized budget window.

## Phase4 — shared-VPS assessment, no live provisioning

Owner target is one service-operated VPS/shared domain. See
[assessment](plans/product/phase-04-single-vps-assessment.md) and
[capacity calculation](plans/product/phase-04-capacity.json). Current host has
~0.95GiB available/2vCPU and >99% swap occupied; admit0 customer agents. Do not
activate the disabled lifecycle driver, remove owner browser containers, resize
hardware, remount filesystems or change Docker default runtime from this report.
16GiB/4CPU is a proposed budgeted upgrade candidate, not purchased/tested capacity.

Resume Phase4: prepare scoped backup/upgrade/rollback, distinct tenant identities,
fixed supervisor + native Fleet adapter/worker broker, verified stronger runtime,
per-cell persistent disk quotas and egress rules, then private A/B negative tests.
Gate execution on Phase5 all-route admission and15 acceptance. No separate
customer-operated VM/domain is required. No live control service or cell exists.

## Existing-VPS trial clarification — 2026-09-30

Owner selected trying the existing server before any upgrade. The current target
is two invite-only accounts, one global running customer task, on-demand private
cells and sequential isolated worker stages. Keep every planned feature; no
hardware upgrade prerequisite for implementation. Default-profile zero-slot
measurements remain historical evidence, not proof of a smaller profile. Follow
`product/EXISTING_VPS_TRIAL.md` and deployment policy v2. Measure a fitting profile
and complete isolation/budget checks before execution. Account invitations do
not automatically start an agent; later resize changes capacity, not accounts,
domain or feature scope. No live deployment or feature activation in this update.

## Phase4/5 local continuation — 2026-09-30

Durable lifecycle metadata/coordinator and offline budget reservation/receipt core
are implemented, with scoped operation/usage read views and fixed MFA operator
queue routes. See platform/agentai_platform/lifecycle/README.md and platform/BUDGET.md
(paths relative to openclaw-project). Native lifecycle/worker dispatch, secrets,
stronger-runtime/quotas/network isolation, real route accounting and a fitting
existing-host profile remain incomplete; runtime/customer/payment/mail gates stay
off. No live migration or listener installed. Package new immutable SQL002/003
and Django004–007 with the release; explicit private bootstrap is required and
old releases reject the newer schema. Host-only lifecycle_status reads counts;
seed_trial prepares one seven-day/$1 entitlement without resetting one already
present. No account or invitation was created. Continue Phase4 native integration
and Phase5 provider enforcement before dependent chat activation.

## Product Phase4 supervisor continuation — 2026-10-01

Read `platform/agentai_platform/lifecycle/SUPERVISOR.md` before installation or
recovery. The new host journal is independent of app metadata; never reset a
global hold or delete an uncertain intent to retry. Obtain a bound native drain
receipt first. Keep the web user out of the controller group; never proxy the
Unix control socket. Shipped native backend is disabled and service uninstalled.

The host `openclaw` executable is2026.2.24/Node22.22.0; earlier Fleet2026.9.6
evidence does not establish that host command's compatibility. Do not run owner
doctor --fix or replace owner binaries to correct this. The separate candidate
installer in platform/deploy/prepare_native_cli.py uses official pinned Node/
package integrity, a dedicated directory and no install scripts. Run only in a
bounded transient service,384MiB/no swap/25% CPU/64 tasks/10min, retaining512MiB
owner headroom. An incomplete staging directory requires scoped investigation
before retry; no blind overwrite. Installer fit is not customer task admission.

Separate candidate follow-up: Fleet2026.9.6 help and empty registry JSON pass.
Installed exact fs-safe Linux0.18.1 package after the omitted-optional warning;
native require mode and synthetic read/traversal/symlink/no-clobber-move checks
pass, fixtures cleaned. This is not native customer OS/worker isolation. GitHub
Linux gate for3f0cc73 passes40 account+51 core cases and Vercel routing.
