# OpenClaw operations runbook

Production belongs on the IONOS VPS and must work while the Mac is off. The
deployment plan is [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md). The temporary
Mac Node/OpenClaw binaries were removed to recover disk space. Its private
staging state is retained only as historical evidence and must not be used as
the server's live state.

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

The helper reads the private SSH login from `agent/.env`, creates a loopback
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
