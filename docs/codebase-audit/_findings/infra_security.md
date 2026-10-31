# Findings: Infrastructure, security, deployment (SCOPE prefix IS)

Audit date 2026-10-29. Branch `product-phases-6-11`. Repo-only: no SSH, no network, no scripts run. Production state is UNVERIFIED everywhere below unless a file in the repo records it (and then it is dated by that file).
Uncommitted in-progress work (tool_origin, tool_relay, cell_bridge, cell_config) was read but not judged as finished.

## Scope & method

Read: `platform/deploy/*` (17 systemd units/timers, `caddy/`, `cells-docker/`, `model-proxy/`, `vercel/`, examples, `release.py`, `p15_acceptance.py`, `billing_install.py`), `deploy/*` (compose, Dockerfiles, env examples, litellm), `bin/*`, `config/*` (examples), `dashboard/app.py` (auth, sessions, headers), `platform/accounts/settings.py` + `middleware.py`, `agentai_platform/{tool_relay,live/gateway,live/ticket,privacy}.py`, `lifecycle/{cell_bridge,netpolicy,cell_config}.py`, `ops/{hostconfig,inventory,monitor,exposure,restore,backup}.py`, `RELEASE_NOTES.md`, `SERVER_DEPLOYMENT.md`, `RUNBOOK.md` (grep), `platform/OPERATIONS.md`, `plans/product/privacy.md`, `evidence/deployments/*`.
Commands: `git ls-files` + regex scans for secret shapes (names/paths only, no values printed), `git check-ignore`, `rg` for env names, `ls -la` on `.env`/`ssk-key` (mode only).
Not checked: anything on the VPS; Vercel project settings; DNS; `platform/tests/e2e/harness.py` only skimmed (test-only, uses tmp dirs, local loopback); `BUILD_LOG.md` deployment entries only grepped; the 5 `evidence/phase-*` manifests. Brief paths `docs/release/RELEASE_NOTES.md` and `docs/SERVER_DEPLOYMENT.md` do not exist: the files are `RELEASE_NOTES.md`, `SERVER_DEPLOYMENT.md`, `RUNBOOK.md`, `BUILD_LOG.md` at the project root.

## File/module map

| path | responsibility | consumers/entry | notes |
|---|---|---|---|
| `platform/deploy/agentai-platform-app.service` | gunicorn Django app, 127.0.0.1:18800, user agentai-platform | Caddy `@customer` | hardened (empty CapabilityBoundingSet, ProtectSystem=strict, MemoryMax 128M) |
| `platform/deploy/gunicorn.conf.py` | 1 worker, 1 sync thread, timeout 15, backlog 16, accesslog off | app unit | single-worker SQLite design |
| `platform/deploy/agentai-platform-control.service` | legacy stdlib "control" server (`agentai_platform.server --service control`, port 18801 from config) | none in repo; not in monitor REQUIRED_UNITS | port clashes with live gateway default (IS-004) |
| `agentai-request-worker.service` | `manage.py request_worker`: runs queued chat requests | app DB, cell bridge socket | idle while `customer_execution` off |
| `agentai-lifecycle-worker.service` | `lifecycle.worker_main`: queue to supervisor; no root/docker | supervisor socket | AF_UNIX only |
| `agentai-supervisor-native.service` | root supervisor, native Fleet backend on cell engine | lifecycle worker, bridge, browse | caps CHOWN/DAC/FOWNER/SYS_ADMIN/NET_ADMIN/SETGID/SETUID/MKNOD; `ProtectControlGroups=no`; no ProtectSystem |
| `agentai-supervisor.service` | older custody-only supervisor ("native effects disabled") | none | LEGACY candidate: superseded by `-native`; both bind `RuntimeDirectory=agentai-supervisor` |
| `agentai-cell-bridge.service` | root, app to customer Gateway relay, unix socket 0660 + SO_PEERCRED | app, tool relay, browse | allowlisted methods (`cell_bridge.py:26`) |
| `agentai-browse.service` | root, sandboxed browser jobs + live-frame gateway (thread, 127.0.0.1:18801) | request worker via `/run/agentai-browse/browse.sock` | no ProtectSystem/ProtectHome/PrivateTmp |
| `agentai-tool-relay.service` | app-user MCP/HTTP server on 10.77.0.1:4100 for cells | cell OpenClaw | bearer = cell's model key, verified by bridge `cell.identify` |
| `agentai-billing-worker.service/.timer` | oneshot every 30 s after inactive | Stripe webhook inbox | |
| `agentai-platform-mail.service/.timer` | oneshot every 60 s | email jobs | mail disabled by default (`AGENTAI_MAIL_ENABLED`) |
| `agentai-ops-backup.service/.timer` | root, 03:40 UTC nightly age-encrypted backup set | `agentai_platform.ops.cli backup` | `After=openclaw-ops-backup.service` (owner unit, not in repo) |
| `agentai-ops-monitor.service/.timer` | root, every 5 min health/queue/backup/exposure check | `ops.cli monitor` | |
| `caddy/Caddyfile.getlumina` | customer TLS edge for `backend.getlumina.pro` | systemd caddy | routes below |
| `caddy/agentai-limits.conf` | systemd drop-in limiting caddy (MemoryMax 128M, TasksMax 32) | `/etc/systemd/system/caddy.service.d/` | |
| `Caddyfile.example` | design-only | none | |
| `cells-docker/` | second Docker engine for customer cells (gVisor `runsc` default, bridge `agentai0` 10.77.0.1/16, pool 10.78.0.0/16, iptables off), firewall unit, ufw route script | `agentai-cells-docker`, `-firewall` | `agentai_cells.nft.generated` is a stale checked-in artifact (IS-005) |
| `model-proxy/` | root-less DynamicUser relay 10.77.0.1:4000 to LiteLLM 127.0.0.1:4000, completions/models only | cells | bounded head/body, no content logging |
| `vercel/` | static build + rewrites `/account /auth /v1 /app` to `BACKEND_ORIGIN` | Vercel Production | |
| `release.py` | canary release with schema-compatible rollback | operator on server | copies live DB to 0700 scratch in state dir, cleans up |
| `p15_acceptance.py`, `p4_*_check.py`, `signup_live_check.py`, `capture_fleet_probe.py`, `check_native_fs.mjs`, `prepare_native_cli.py` | one-off live acceptance/probe scripts run by hand on the server | operator | mutate live DB / docker (IS-019) |
| `billing_install.py` | installs Stripe config files | operator | |
| `*.example.json`, `accounts.env.example` | host config templates | operator | `accounts.env.example` documents 8 of ~45 env names (IS-007) |
| `deploy/docker-compose.production.yml` | owner stack: postgres, litellm (127.0.0.1:4000), openclaw-gateway (loopback 18789/18790/3978, mounts docker.sock), openclaw-cli | owner `docker compose` | image digests pinned |
| `deploy/Dockerfile.{sandbox,claude-code,sdk-peer}` | owner tool-sandbox images | `bin/phase4/build-*.sh` | not read in depth |
| `deploy/litellm.yaml` | duplicate of `config/litellm.example.yaml` (not mounted) | `tests/test_phase10_assets.py:50` only | DUPLICATED |
| `deploy/openclaw-key.request.json`, `*.env.example` | budget-key request / env templates | operator | no values |
| `bin/ssh-server`, `scp-server`, `open-*.py`, `owner-console.py`, `activate-telegram.py` | operator SSH helpers; password from `openclaw-project/.env` | owner Mac | password auth (IS-002) |
| `bin/deploy-lumina.py`, `update-ops-dashboard.py`, `pull-backups.py`, `setup-backup-key.py`, `ops-restore.sh`, `phase4/`, `phase6/` | frontend deploy, dashboard push, off-server backup pull, age key creation, restore drill, connector setup | operator | |
| `dashboard/app.py` (1718 LOC) + `static/` + `workread.mjs` | owner dashboard on 127.0.0.1:18795, password+session, `docker exec` into gateway/postgres | SSH tunnel | god file; unit file not in repo |
| `config/` | `openclaw.example.json`, litellm example, phase batch jsons, fixtures, skills, workspace templates | owner config | not read in depth |
| `evidence/deployments/*`, `evidence/browser-reliability/*` | dated deployment records (tracked, 183 tracked files under `evidence/`) | humans | contain no secrets by regex scan |
| `platform/agentai_platform/ops/*` | backup/restore/monitor/alerts/exposure | ops units | quality is high; restore refuses unclassified tables |

### Reconstructed production topology (from config; UNVERIFIED on the VPS)

- Host: one IONOS Ubuntu 24.04 VPS (2 vCPU, ~4 GiB RAM, 120 GiB) per `SERVER_DEPLOYMENT.md`; the IP is committed in 12+ tracked files. Public ports expected: 22, 80, 443 only (`ops/monitor.py:24`).
- Edge: Vercel (static + rewrites) to `https://backend.getlumina.pro` (Caddy, auto-TLS) to loopback. Caddy routes: `^/v1/live/<32hex>/frame$` to 127.0.0.1:18801 (flush -1); `/app/scenes/*.mp4|jpg` served from `/var/www/lumina-scenes`; `/account /auth /v1 /app` to 127.0.0.1:18800 with Host forced to `getlumina.pro`, `X-AgentAI-Client-IP`/`X-Forwarded-For` set to `{remote_host}`, `Forwarded` stripped; all else 404. Owner Gateway stays loopback 18789.
- Customer app: gunicorn 18800 + SQLite `/var/lib/agentai-platform/platform.sqlite3` (0700 state dir enforced in `settings.py:19`).
- Owner stack (`/opt/openclaw-production`, docker compose project `openclaw-production`): postgres (internal network `budget-data`), LiteLLM (127.0.0.1:4000), OpenClaw Gateway (loopback 18789/18790/3978), dashboard 18795 (systemd `openclaw-dashboard`, unit not in repo).
- Tenant boundary: per customer a gVisor (`runsc --platform=systrap`) container on a SEPARATE Docker engine (`/run/agentai-cells/docker.sock`, data-root `/var/lib/agentai-cells/docker`), bridge `agentai0` 10.77.0.1/16, pool 10.78.0.0/16, own volume under `/var/lib/agentai-fleet/.openclaw/fleet/cells/<tenant>`, own LiteLLM virtual key and budget. nftables table `agentai_cells` (generated by `lifecycle/netpolicy.py`) drops cell to host input except two doors: model relay 10.77.0.1:4000, tool relay 10.77.0.1:4100; drops cell to private ranges/metadata; ufw route/allow rules in `agentai-cells-routes.sh`.
- Host bridges (root): `agentai-cell-bridge` (unix socket, 0660 group agentai-platform, SO_PEERCRED), `agentai-supervisor-native`, `agentai-browse` (browser stages run via `docker run` on the cells engine: `--read-only --cap-drop ALL --pids-limit 256 --memory 1536m`, `service.py:651`).
- Backups: age-encrypted sets (public recipient only on host) to `/var/backups/agentai` (local, `offsite:false` default); owner pulls to the Mac with `bin/pull-backups.py`; retention 14 daily + 2 weekly, max 30 days.
- Third parties: Anthropic (via LiteLLM), Brave search, TypeSafe/JEV `api.typesafe.ai`, Stripe, Telegram, SMTP (off), Google connectors (read-only scopes), Vercel.

### Entry points (units, timers, commands)

Long-running: `agentai-platform-app`, `-request-worker`, `-lifecycle-worker`, `-supervisor-native` (`-supervisor` legacy), `-cell-bridge`, `-browse`, `-tool-relay`, `-model-proxy`, `-cells-docker`, `-cells-firewall`, `caddy`, `fail2ban`, `docker`, `openclaw-dashboard` (not in repo). Timers: `billing-worker` (30 s), `platform-mail` (60 s), `ops-backup` (03:40 UTC), `ops-monitor` (5 min); owner-side `openclaw-ops-backup.timer` (03:17 UTC, not in repo). Management commands run by units: `request_worker`, `tool_relay`, `billing_worker`, `deliver_account_mail`. Operator-run: `release.py`, `p15_acceptance.py`, `bin/deploy-lumina.py`, `ops.cli {backup,monitor,restore-account,fetch}`.

### Env var / secret inventory (names only)

Source of truth for the app is `platform/accounts/settings.py` (lines in parentheses). Documented in `platform/deploy/accounts.env.example`: only `AGENTAI_SESSION_SECRET, AGENTAI_STATE_DIR, AGENTAI_PUBLIC_ORIGIN, AGENTAI_MAIL_ENABLED, AGENTAI_SMTP_{HOST,USER,PASSWORD}, AGENTAI_FROM_EMAIL`.
Referenced but NOT in that example (documented only in OPERATIONS.md/RELEASE_NOTES.md prose or nowhere): `AGENTAI_TELEGRAM_{BOT_TOKEN,WEBHOOK_SECRET,BOT_USERNAME}` (79-81), `AGENTAI_STORAGE_DIR`, `AGENTAI_ARTIFACT_SIGNING_KEY` (92-93), `AGENTAI_UPLOADS_ENABLED` (99), `AGENTAI_SWITCHES_FILE`, `AGENTAI_SWITCH_FACTS_FILE` (105-106), `AGENTAI_CELL_BRIDGE_SOCKET` (108), `AGENTAI_SERVICE_ALLOCATION_MICROUSD` (110), `AGENTAI_ROUTING_CONFIG_FILE`, `AGENTAI_TYPESAFE_KEY_FILE` (111-112), `AGENTAI_UI_BUNDLE_DIR` (113), `AGENTAI_BROWSE_SOCKET` (114), `AGENTAI_TOOL_RELAY_{BIND,PORT}` (116-117), `AGENTAI_GOAL_CHAIN_LIMIT` (118), `AGENTAI_LIVE_SECRET_FILE`, `AGENTAI_LIVE_PATH` (120-121), `AGENTAI_SAFETY_SNAPSHOT`, `AGENTAI_SAFETY_OWNER_ACCOUNT` (122-123), `AGENTAI_VAULT_KEY_FILE` (124), `AGENTAI_CUSTOMER_RESERVATION_MICROUSD` (125), `AGENTAI_BILLING_{SECRET_KEY_FILE,WEBHOOK_SECRET_FILE,API_VERSION,PRICE_ID,PLAN_FILE,PUBLIC_ORIGIN,ALLOW_LIVE}` (128-134).
Other processes: live gateway `LIVE_FRAMES_ROOT, LIVE_SECRET_FILE, AGENTAI_LIVE_SECRET, LIVE_HOST, LIVE_PORT` (`live/gateway.py:143-148`); runner `BROWSE_OUT, BROWSE_CHROME, BROWSE_ALLOW_LOOPBACK` (`browse/runner.mjs:11-13`); lifecycle worker `AGENTAI_SWITCHES_FILE, AGENTAI_SWITCH_FACTS_FILE` set in the unit file (`agentai-lifecycle-worker.service`); Vercel `BACKEND_ORIGIN`; owner tooling `OPENCLAW_SSH_{USER,PASSWORD,HOST}`, `OPENCLAW_NEW_SSH_*`, `OPENCLAW_SERVER`, `OPENCLAW_TELEGRAM_BOT_{TOKEN,USERNAME}`, `TELEGRAM_USER_ID`; owner stack `LITELLM_MASTER_KEY, LITELLM_SALT_KEY, DATABASE_URL, ANTHROPIC_API_KEY, POSTGRES_PASSWORD` (deploy/*.env.example), `LITELLM_API_KEY`, `OPENCLAW_DOCKER_SOCKET_GID`; `OPENCLAW_BROWSER_CDP_AUTH_TOKEN` generated by `bin/phase4/probe-browser.sh`.
Secret FILES (path-referenced, not env): `/etc/agentai-platform/{accounts.env,live.secret}`, `/etc/agentai-supervisor/{native-wiring.json,fleet-custody.json,browse-engine.json}`, `/var/lib/agentai-supervisor-secrets/` (+ `_shared/typesafe-key`), `/var/lib/agentai-platform/routing/typesafe.key`, `/etc/agentai-ops/{config.json,telegram-token}`, `/opt/openclaw-production/{secrets,dashboard/owner-secret,dashboard/session-secret,dashboard/gateway-token}`, `deploy/secrets/{litellm.env,postgres.env}`.

## Features

| ID | name | status | flags | frontend | backend | entry/flow evidence | prod verified? | notes |
|---|---|---|---|---|---|---|---|---|
| FEAT-IS-01 | Customer HTTPS edge (Vercel to Caddy to gunicorn) | ACTIVE | prod-unverified | rewrites in `vercel/routing.mjs` | `Caddyfile.getlumina`, `settings.py` | Caddy `@customer` to 18800; `evidence/deployments/*/verification.log` probes 200/200/200/401 | partly (27 Oct evidence) | CORS absent by design (same origin) |
| FEAT-IS-02 | Live view frame gateway | ACTIVE | secret file gated | `lumina` Live page | `live/gateway.py`, started in `browse/service_main.py:26-37` | Caddy `@liveframe` to 18801; HMAC ticket 120 s (`live/ticket.py`) | unknown | gateway is a thread in the root browse service |
| FEAT-IS-03 | Tool relay (native browser tool for cells) | ACTIVE (uncommitted edits) | in-progress | n/a | `tool_relay.py`, `management/commands/tool_relay.py` | unit `agentai-tool-relay.service`; bearer to `cell.identify` | unknown | port 4100 on 10.77.0.1 |
| FEAT-IS-04 | Model relay for cells | ACTIVE | | n/a | `model-proxy/agentai_model_proxy.py` | unit `agentai-model-proxy.service`, ufw rule, `test_model_proxy.py` | unknown | |
| FEAT-IS-05 | Cell isolation (gVisor, separate engine, nft drop-only) | ACTIVE | prod-unverified | n/a | `cells-docker/`, `lifecycle/netpolicy.py` | daemon.json, firewall unit | unknown | see IS-005 |
| FEAT-IS-06 | Encrypted backup + scoped restore | ACTIVE (local only) | offsite open | n/a | `ops/*`, `bin/pull-backups.py` | `agentai-ops-backup.timer` | unknown | IS-016 |
| FEAT-IS-07 | Monitor + alerts (email/Telegram) | ACTIVE | gaps | n/a | `ops/monitor.py`, `alerts.py` | `agentai-ops-monitor.timer` | unknown | IS-003 |
| FEAT-IS-08 | Canary release w/ rollback | ACTIVE | | n/a | `deploy/release.py` | `evidence/deployments/*/release.log` | yes (27 Oct runs recorded) | |
| FEAT-IS-09 | Owner dashboard | ACTIVE | unit not in repo | `dashboard/static` | `dashboard/app.py` | `bin/update-ops-dashboard.py` restarts `openclaw-dashboard` | unknown | IS-011 |
| FEAT-IS-10 | Legacy control server | LEGACY/UNKNOWN | port clash | n/a | `agentai_platform/server.py`, `agentai-platform-control.service` | no caller in monitor/Caddy | unknown | IS-004; a prior audit listed it as H-03 |
| FEAT-IS-11 | `agentai-supervisor.service` (custody-only) | LEGACY | superseded | n/a | `supervisor_main` | `-native` unit replaces it | unknown | confirm not enabled |
| FEAT-IS-12 | Native browser engine (cell's own browser) | INCOMPLETE/EXPERIMENTAL | gated off (`native_browser:false` in example) | n/a | `cell_bridge.py` BROWSER_METHODS | `native-wiring.example.json` | n/a | an OOM canary on 27 Oct reverted an account to the runner (`evidence/deployments/20261027T114539Z-cancel-e700e33/deployment.json`) |

## Findings

**IS-001** | Security hygiene (secret) | **High** | HIGH | S
An OpenSSH private key `ssk-key` (+ `ssk-key.pub`) sits untracked at the git root `/Users/parsa/AgentAI/` (git status `??`, mode 0600, dated 20 Oct). It is NOT gitignored: root `.gitignore` has `*.key` and `*.pem` but nothing matching `ssk-key`, `git check-ignore -v ssk-key` returns nothing. One `git add -A`/`git add .` publishes it. The same goes for 4 `jev-browser-*.tar.gz`, `*.zip` and screenshots at root (not ignored at root; `openclaw-project/.gitignore` has `*.tar.gz` but only below that dir).
Evidence: `git status` snapshot; `ls -la ssk-key*`; `head -c 40 ssk-key` shows the `BEGIN OPENSSH PRIVATE KEY` header only. `git log --all -- ssk-key` empty (never committed).
Impact: potential leak of an SSH credential (what it authorizes is unknown; OPERATIONS.md says key login is not yet adopted).
Action F: add `ssk-key*`, `*_key`, `id_*` and root-level `*.tar.gz`/`*.zip` to the root `.gitignore` (or move the key out of the repo); the lead should confirm with the owner what host it opens. Risk of change: none.

**IS-002** | Security (host access) | **High** | MEDIUM (prod unverified) | M
Operator access to the VPS is `root` over SSH with a password stored in `openclaw-project/.env` (`bin/ssh-server:21-24` reads `OPENCLAW_SSH_USER/PASSWORD`; `RUNBOOK.md:96` uses `root@69.48.206.62`). Port 22 listens on 0.0.0.0 (`plans/product/server-smoke.json` listener readback, 30 Sep). `SERVER_DEPLOYMENT.md:19-20` says "a dedicated SSH key remains an operations follow-up"; `OPERATIONS.md:97` lists "Move to key login, then disable password and root-password login" as still to do; `ops/exposure.py:evaluate_ssh` emits only WARN for it. `plans/product/privacy.md:25` says "keep the server login to key-only", which contradicts the above.
Impact: root on the host reads every customer DB, volume and tenant key. Brute-force exposure mitigated only by fail2ban (listed in REQUIRED_UNITS, unverified). This is the largest single privacy risk in scope.
Action F: on the VPS check `sshd -T | egrep 'passwordauthentication|permitrootlogin'` (see checklist); then adopt key login. Owner's stated priority is customer privacy, so this directly matches it.

**IS-003** | Monitoring gap | **Medium** | HIGH | S
`ops/monitor.py:19-20` `REQUIRED_UNITS` lacks `agentai-browse` (root service that runs every customer browser job and the live gateway), `agentai-platform-control`, and `agentai-model-proxy` is present but browse is not (`rg agentai-browse platform/agentai_platform/ops` finds only restore.py table names). The monitor TIMERS table still lists legacy `openclaw-ops-backup.timer`. A dead browse service would not raise a crit alert.
Action D: add `agentai-browse` to REQUIRED_UNITS (it is Restart=on-failure but start failure loops silently). Risk: a test may assert the tuple; check `tests/test_ops_monitor*`.

**IS-004** | Config conflict | **Medium** | MEDIUM | S
Port 18801 is claimed twice: `config.server.example.json:5` / `config.example.json:5` (`control_port` for `agentai-platform-control.service`) and `browse/service_main.py:54` `--live-port` default plus Caddy `@liveframe` (`Caddyfile.getlumina:7`). `server-smoke.json` (30 Sep) shows 18801 listening for the control service; today Caddy sends live frames there. If both units are enabled one fails to bind and the failing side is either live view (silent: browse prints nothing on bind error from a daemon thread, `service_main.py:36`) or control. `OPERATIONS.md`/release notes treat the control server as dead; `config.py:29` only checks app_port != control_port.
Action D/A after VPS check: `systemctl is-enabled agentai-platform-control`; if disabled/unused classify the unit and `server.py` as LEGACY (C: product decision to keep). Risk: low.

**IS-005** | Firewall artifact drift | **Medium** | MEDIUM | S
`platform/deploy/cells-docker/agentai_cells.nft.generated` (15 lines, tracked since `85c83a4`) has an `input` chain that drops ALL new connections from cells to the host with no door for 4000/4100, whereas `lifecycle/netpolicy.py:68-71` emits `tcp dport` returns for `model_proxy_port` and `tool_relay_port`, and `agentai-cells-routes.sh` adds ufw allows for both. The example `native-wiring.example.json:10` has `"model_proxy_port": null` while the ufw script and docs say the relay is 4000. Since nft `drop` at priority -5 beats a later ufw accept, whether cells reach the model relay depends on the REAL `/etc/agentai-cells/agentai_cells.nft` content, which is generated at runtime. The checked-in file is a stale sample and no tool in repo reads it (rg finds only the unit and routes script mention the name).
Impact: misleading for anyone rebuilding the host from the repo; verification needed on VPS.
Action A/D: delete or regenerate the sample from `NetPolicy(…, 4000, tool_relay_port=4100)`; verify live (`nft list table inet agentai_cells`).

**IS-006** | Config drift (server vs repo) | **Medium** | HIGH | M
Server state that is documented as hand-made and not in git (`RELEASE_NOTES.md:129-137`) or referenced by repo code but absent from repo:
1. `/etc/systemd/system/openclaw-dashboard.service` and `openclaw-dashboard.service.d/feature-switches.conf` (dashboard is a REQUIRED_UNIT; no unit file in repo).
2. `/etc/systemd/system/agentai-browse.service.d/jev.conf` (`--jev-mode live`; the repo unit ExecStart has no `--jev-mode`, default in code is `live`, `service_main.py:50`, so the drop-in is redundant or may carry other overrides).
3. `/opt/agentai-browse/runner/runner.mjs`: copied by hand five times (`.bak-live1/5/7`) from `browse/runner.mjs`; no repo script syncs it (deploy README says "reinstall from `openclaw-project/browse`").
4. `/etc/agentai-platform/live.secret` and `AGENTAI_LIVE_SECRET_FILE` line in `accounts.env`; `AGENTAI_SAFETY_OWNER_ACCOUNT` in `accounts.env`; `"safety_file"` in `native-wiring.json`; `/etc/caddy/Caddyfile` (repo copy said identical as of live1; the later `/app/scenes` block was added by commit `4bdf03c`, deployed state unverified).
5. `openclaw-ops-backup.service/.timer` (owner backup at 03:17 UTC, referenced `After=` in `agentai-ops-backup.service:3` and in monitor TIMERS).
6. `/etc/caddy/Caddyfile.before-agentai`, `/etc/docker/daemon.json` (owner engine), `/etc/agentai-ops/config.json` (age recipient; the example has a placeholder), `/etc/agentai-supervisor/{fleet-custody,browse-engine}.json`.
7. Owner switch values (`feature-switches/switches.json`), e.g. `jev_services` set ON 14 Oct per release notes.
Action: compare on the VPS per the checklist; consider committing the dashboard unit and the missing drop-ins as examples (class B/G).

**IS-007** | Config debt (env sprawl) | **Medium** | HIGH | M
About 45 distinct env names; only 8 are in `accounts.env.example`. Naming is inconsistent for the same concept: live secret is `AGENTAI_LIVE_SECRET_FILE` for the app (`settings.py:120`) but `LIVE_SECRET_FILE`/`AGENTAI_LIVE_SECRET` for the gateway (`live/gateway.py:144-145`) and a CLI flag `--live-secret-file` (default `/etc/agentai-platform/live.secret`) for the browse service, which re-reads the file with different permission rules (root-owned, no 027 bits, `service_main.py:33-35`) than the app (group-readable). Telegram: `AGENTAI_TELEGRAM_BOT_TOKEN` (app) vs `OPENCLAW_TELEGRAM_BOT_TOKEN` (owner tooling). SSH: `OPENCLAW_SSH_*` vs `OPENCLAW_NEW_SSH_*` (selected by `OPENCLAW_SERVER`, default "new", `bin/ssh-server:19`). Defaults diverge: switches file path is `''` in `settings.py:105` but `/opt/openclaw-production/feature-switches/switches.json` in `browse/service_main.py:49` and in the lifecycle-worker unit; `AGENTAI_PUBLIC_ORIGIN` defaults to `https://localhost` while `AGENTAI_BILLING_PUBLIC_ORIGIN` defaults to `https://getlumina.pro` (`settings.py:10,133`); `AGENTAI_STATE_DIR` default `BASE_DIR/data`; `DATA_UPLOAD_MAX_MEMORY_SIZE` is defined twice (200000, then 31457280 at line 100), the first is dead.
Action B: extend `accounts.env.example` with a commented full list and a test asserting every `os.environ` name in settings appears there.

**IS-008** | Observability / error handling | **Medium** | HIGH | S
`settings.py:101-103` sends the `django` logger (including `django.request` 500 tracebacks) to a `NullHandler`; the only per-request log is `{"event":"account_http","request_id","status"}` (`middleware.py:39`). Server errors therefore leave no traceback anywhere (gunicorn `errorlog='-'` captures worker crashes only). This is deliberate for privacy ("No URL/query/body/cookie/header/exception text in customer logs", `middleware.py:38`) and is good for customer privacy, but debugging production 500s relies on the request id and reproduction. Related: `p15_acceptance` reported 500s on malformed ids earlier (commit `febecb9`).
Action C (product decision): add a redacted handler that logs only exception class + file:line (no message).

**IS-009** | Rate limiting / proxy trust | **Medium** | MEDIUM | M
`Caddy` passes `X-AgentAI-Client-IP {remote_host}` (`Caddyfile.getlumina:25`); `BoundaryMiddleware` trusts it from loopback (`middleware.py:14-17`). Behind Vercel `remote_host` is a Vercel egress address, so the anonymous ingress bucket `ingress.anonymous` (120 per 60 s, `AccountMiddleware`) and any IP-keyed auth throttle are shared across ALL customers (acknowledged in `caddy/README.md`: "rate limits may aggregate Vercel proxy peers"). One abuser can exhaust anonymous access (login page, signup) for everyone behind the same Vercel peer. Also `backend.getlumina.pro` is a publicly resolvable host serving the full `/account /auth /v1 /app` surface, so Vercel adds no gate and direct hits bypass any Vercel protections.
Action E: verify the peer set on the VPS; consider trusting Vercel's forwarded client IP only when the peer matches Vercel's published ranges, or add a shared-secret header from Vercel that Caddy requires.

**IS-010** | Resource hygiene | **Low/Medium** | MEDIUM | S
Uploads allow 30 MiB bodies (`middleware.py:21`, `settings.py:100`) into a sync single-worker gunicorn (`workers=1 threads=1 timeout=15 backlog=16`) with `MemoryMax=128M` and Caddy without a `request_body max_size`. A slow or large upload occupies the only worker for up to the 15 s timeout; `FILE_UPLOAD_MAX_MEMORY_SIZE=0` streams to temp files in `PrivateTmp`, which helps. `AGENTAI_UPLOADS_ENABLED` is off by default, so this is latent.
Action F: add Caddy `request_body { max_size 32MB }` on `/v1/requests` etc., or leave as is until uploads launch.

**IS-011** | Auth (owner dashboard) | **Medium** | MEDIUM | M
`dashboard/app.py`: one shared password in `dashboard/owner-secret`; HMAC compare OK (`:156-162`); sessions are random, hash-stored, idle 2 h / absolute 24 h, CSRF token on POST (`:1025`), strict CSP, `X-Frame-Options`, bind 127.0.0.1 only (`:82`) so access is via SSH tunnel. Weaknesses: (a) failed-login throttle is per `client_address[0]`, which is always 127.0.0.1 through the tunnel, so 5 failures lock the owner out for an hour and the throttle is in memory (reset on restart); (b) no `Host` header validation, only `Origin` check on one POST path (`:817`); a DNS-rebinding page in the owner's browser could reach 127.0.0.1:18795 if a session cookie exists (SameSite=Strict mitigates cookie sending for cross-site, but not same-host rebinding); (c) cookie has no `Secure` (HTTP loopback, acceptable); (d) the process shells `docker exec` into gateway/postgres/litellm (`:269-:1068`), so a dashboard compromise equals root-equivalent control of the owner stack; the unit file (user, hardening) is not in the repo so privilege is unknown.
Action F: add Host allowlist (`127.0.0.1:18795`, `localhost:18795`) and check the unit runs with minimal privilege.

**IS-012** | Container privilege | **Medium (by design)** | HIGH | -
`docker-compose.production.yml:55-56` mounts `/var/run/docker.sock` and `/usr/bin/docker` into `openclaw-gateway` (owner engine) and adds the docker socket gid via `group_add`. Compose comment states tool containers do not get it. Gateway runs with `--bind lan` inside the container (loopback-published only), `cap_drop: NET_RAW, NET_ADMIN` (not ALL), no `read_only`. Customer cells use the separate engine, so a customer-cell escape does not hit this socket, but an owner-gateway RCE is root. Postgres service lacks `cap_drop`; litellm drops ALL.
Action G: preserve; consider `cap_drop: ALL` + `read_only` for gateway when tested; document in threat model.

**IS-013** | Privilege / systemd hardening | **Medium** | HIGH | M
Root services `agentai-browse`, `agentai-cell-bridge`, `agentai-supervisor-native`, `agentai-ops-*` omit `ProtectSystem`, `ProtectHome`, `PrivateTmp`, `PrivateDevices` (browse and bridge have only NoNewPrivileges, RestrictSUIDSGID, caps `CAP_DAC_OVERRIDE CAP_CHOWN CAP_FOWNER`). They process customer-controlled web content/screenshots (browse) and relay chat frames (bridge). Running as root with `CAP_DAC_OVERRIDE` means any parsing bug can read any file on the host. `agentai-model-proxy` and app-user units are well hardened (empty capability set), so the gap is specific to the root units, some of which need Docker access. `agentai-supervisor-native.service` also sets `ProtectControlGroups=no`, `CAP_SYS_ADMIN`, `CAP_NET_ADMIN`, `CAP_MKNOD`.
Action E/F: add `ProtectHome=yes PrivateTmp=yes ProtectKernelTunables/Modules=yes` to browse and bridge after testing; review whether `CAP_DAC_OVERRIDE` is needed. Risk: browse reads job folders under `/var/lib/agentai-browse` and runs docker; test on a canary.

**IS-014** | Privacy (data leaving host) | **High** | HIGH (code path), MEDIUM (frequency) | M
`browse/ladder.py:333,397` send the customer's browser window as raw base64 JPEG (`'assets': {ref: {'type':'image','format':'jpg','data_base64': shot['data']}}`) to `api.typesafe.ai` (`routing/config.py:15`, `browse/service_main.py:18`) whenever `look.shot` is set (popup, panel, human check, picture mode). Text goes through `privacy.scrub`, but images cannot be scrubbed, and `plans/product/privacy.md:17` documents only "page text and element labels ... passed through `privacy.scrub`". The scrub is also per-account switchable (`personal_data_scrub`, `privacy.py` ContextVar). Trace files keep up to 400 chars of the raw model answer (`ladder.py:623`). Retention of screenshots on host is 24 h (documented).
Impact: pictures of pages the customer is logged into may reach a third party without the customer being told (policy/legal, not code-correctness).
Action C: product decision: document it in privacy.md and the customer-facing data terms (`jev_routing` has a data-terms tick for chat routing; check browser JEV has the same), or disable `shot` for pages flagged sensitive, or ask TypeSafe for no-retention terms.

**IS-015** | Doc drift | **Low** | HIGH | S
(a) `plans/product/privacy.md:6-7` says the model relay is "the only host door"; since native execution there are two (4000 and 4100, `netpolicy.py`, `agentai-cells-routes.sh`). (b) `deploy/README.md:19-20` says the LiteLLM API "has no published host port"; compose publishes `127.0.0.1:4000:4000` (`docker-compose.production.yml:40-41`). (c) `deploy/litellm.yaml` duplicates `config/litellm.example.yaml` and is not mounted; README says canonical is the latter. (d) `SERVER_DEPLOYMENT.md` still reads "Gate 1 still awaits owner access checks" and mentions the "legacy AgentAI working-tree code retired 2026-09-27". (e) `RELEASE_NOTES.md` sections are in non-chronological order and the "Latest: live8" header (13-14 Oct) is below three newer 26-27 Oct sections; "Running release" text is stale. (f) `caddy/README.md` has missing spaces ("loopback18800", "return404"). (g) Ports listed in `monitor.py` `LOOPBACK_PORTS` omit 4100 (not loopback, bound to 10.77.0.1; `evaluate_listeners` ignores `10.*`, so no false alarm) but include 2019 (Caddy admin) which is not documented anywhere else.
Action B: refresh the docs; low risk.

**IS-016** | Backup / DR | **Medium** | MEDIUM | M
Default destination is local only (`hostconfig.py:DEFAULTS` `offsite: False`; example `ops-config.example.json`); `privacy.md:27` lists "Off-server backup destination" as still open; the real off-server copy is manual `bin/pull-backups.py` from the owner's Mac, which records the pull so the monitor "knows an outside copy exists". Backup set includes `/etc/agentai-platform/accounts.env`, tenant secrets and compose secrets (age-encrypted to the owner's public recipient only; the private key must never be on the host, `inventory.py` `encryption-keys`). Not covered: the vault key file (`AGENTAI_VAULT_KEY_FILE`, path unknown, `vault_items` are never restored by design), `live.secret` (outside `config_paths`), `/opt/agentai-browse/runner`, dashboard dir (`owner-secret`, `session-secret`; only the owner `oc-ops-*.tar.gz` may include it). Restore drill for the owner stack is `ops-restore.sh` (offline clone); no automated restore test for the customer app DB was found (restore code is well tested: `restore_account` proves other accounts unchanged).
Action F/C: confirm a second off-host copy exists and the age private key custody; add `live.secret` and the vault key path to `config_paths` if their loss would break restore.

**IS-017** | Source custody | **Medium** | MEDIUM (stale) | S
`RELEASE_NOTES.md:151-155`: GitHub account suspended 14 Oct; code lives on one Mac plus `*.bundle` backups in `/Users/parsa/AgentAI-backups` and a copy in `/root/` on the server. Current status after 14 Oct is unknown. Large untracked artifacts at the root (`jev-browser/`, `jev-window-core/`, four `jev-browser-*.tar.gz`, `lumina-cost-audit/`, `sonarqube-export/`, `brag-output/`, `product/marketing/`) are outside any backup.
Action C: owner to confirm push status; verify the bundle dates.

**IS-018** | Secret handling positives and residuals | **Low** | HIGH | -
No secret shapes found in any tracked file (regex: `sk-ant-`, `sk-`, `whsec_`, `sk_live/test`, `ghp_`, `AKIA`, `xox*`, `AIza`, PEM headers). `.env` is ignored by both `.gitignore`s (`openclaw-project/.env` mode 0600; `git check-ignore -v` confirms); `.env.*`, `*.pem`, `*.key`, `accounts.env`, `*.sqlite3` also covered. Tracked secret-looking names are templates only (`*.env.example`, `deploy/openclaw-key.request.json`, `lifecycle/secrets_custody.py`, `bin/setup-backup-key.py`, `bin/phase6/rotate-brave-key.py`). Residual: public VPS IP `69.48.206.62`, the SSH host-key fingerprint and the account id `f40a5f6b...` (`p15_acceptance.py:30`) are in tracked files; tracked `evidence/**/*.log` (183 tracked files in `evidence/`, contrary to CLAUDE.local.md's "not indexed") deserve a leak review before the repo is ever made public. Stripe, Telegram, SMTP, Anthropic keys are referenced by name or file path only.

**IS-019** | Ops scripts mutate live state | **Low** | HIGH | S
`p15_acceptance.py` sets up Django on the production DB, creates a user `p15-acceptance-b`, and writes results to `/tmp/p15-results.json` (world-visible path; UMask of the invoking shell). Hard-coded account `A = 'f40a5f...'` (owner test account). `p4_live_check.py`, `p4_pipeline_check.py`, `signup_live_check.py` are the same style. They are documented as run by hand, not by a timer; no unit references them (checked units and `rg`).
Action C: leave, but ensure scripts remove temp rows on abort and write under `/var/lib/agentai-ops`.

**IS-020** | Unbounded in-memory state | **Low** | HIGH | S
`tool_relay.py` `Identity._seen` (credential to account) and `_fails` (source to timestamps) are never evicted (only filtered on read); the live gateway `_marked` is capped at 256; dashboard `_login_fails` per IP and `_used_dl` also grow. Bounded by number of cells/IPs and restarts, so practically harmless.
Action C: opportunistic cleanup.

**IS-021** | Tool relay auth model | **Low** | MEDIUM | S
The tool relay authenticates a cell by its LiteLLM virtual key sent as `Authorization: Bearer` over plain HTTP on the bridge (10.77.0.1:4100). Brute-force limit `FAIL_LIMIT=20` per source address per minute (`tool_relay.py:34`); compare is done by the root bridge (`cell.identify`, uses `hmac` import) rather than in the relay. Because each cell has its own source address inside 10.78.0.0/24 and nft blocks spoofing across cells (not verified), the per-source limit is meaningful. Reuse of the model key as a second credential widens its blast radius slightly; the key is already in the cell. Body capped 64 KiB; no content logged (`log_message` is a no-op).
Action G: preserve; note in THREAT_MODEL.

**IS-022** | Live view security | **Low** | HIGH | -
Tickets are HMAC-SHA256, 120 s TTL, bound to account+task (`live/ticket.py`); frame gateway returns 403 on any failure, caps waiters at 12, responds `no-store`, `nosniff`, `CORP: same-origin`; Caddy forwards only the exact regex path. Weakness: `verify()` returns the account id but `FrameGateway.frame` ignores it (checks only request_id match), fine since the ticket is bound to the request id; a leaked ticket shows one task's screen for under 2 minutes. The secret is shared by app and root browse service through a file; rotate = restart both (documented only in RELEASE_NOTES live1).
Action G.

**IS-023** | Duplicate / dead config candidates | **Low** | MEDIUM | S
`deploy/litellm.yaml` (dup, test-referenced only); `platform/deploy/Caddyfile.example` (design only); `agentai-supervisor.service` (superseded by `-native`, which also defines `RuntimeDirectory=agentai-supervisor`: both cannot run); `agentai_cells.nft.generated` (IS-005); `platform/deploy/__pycache__`, `dashboard/__pycache__`, `bin/__pycache__` exist locally but are gitignored (`git ls-files | grep pycache` empty). Checked: `rg` for each name in units, tests, docs and bin scripts. Do not delete before the VPS comparison (class A after verification).

**IS-024** | Tests gap | **Low** | MEDIUM | M
No test covers the systemd units/Caddy file consistency (e.g. that every unit named in `monitor.REQUIRED_UNITS` exists in `platform/deploy`, which is false for `openclaw-dashboard`, `agentai-model-proxy` is present, `fail2ban`/`caddy`/`docker` are system units). Dashboard has `dashboard/test_dashboard.py` (457 lines) for the 1718-line app. Uncommitted work touches `tests/e2e/harness.py`, `test_tool_origin.py`, `test_browser_tool.py` (in progress, not judged).
Action D: add a consistency test (units in repo vs REQUIRED_UNITS vs OPERATIONS.md ports).

**IS-025** | Header / TLS posture | **Low** | HIGH | S
Positive: HSTS 1 year + includeSubDomains (`settings.py:50-51`), `__Host-` cookies with Secure/HttpOnly/SameSite=Strict, CSRF trusted origin pinned to `AGENTAI_PUBLIC_ORIGIN`, ALLOWED_HOSTS pinned, strict API CSP `default-src 'none'`, `X-Frame-Options DENY`, `Referrer-Policy same-origin`, `Cache-Control no-store`, no CORS code anywhere in `platform/accounts` or `agentai_platform` (checked by grep), TLS via Caddy ACME. Gaps: `SECURE_HSTS_PRELOAD=False`; no `Permissions-Policy`, no `Cross-Origin-Opener-Policy` on the API; Caddy file sets none of these itself (Django does, but `/app/scenes` static responses from Caddy and the 404 `respond` carry only Caddy defaults and the `Cache-Control` for scenes). The UI shell CSP is set elsewhere (`/app/` view), not reviewed here. The `__Host-` prefix requires Path=/ and no Domain, satisfied by Django defaults.
Action F (optional): add a Caddy `header` block for `X-Content-Type-Options nosniff` on `/app/scenes/*`.

## Looks bad but is fine

1. Single gunicorn worker with 1 sync thread (`gunicorn.conf.py`): intentional with SQLite `IMMEDIATE` transactions and a 128 MiB memory cap; the live view and long operations were deliberately moved to other processes (live gateway is a thread in the browse service, SSE avoided).
2. `agentai-browse`, `cell-bridge`, `supervisor-native` run as root: they need Docker/nft/chown; the app user never gets a docker handle or cell token (`cell_bridge.py` header; socket 0660 + SO_PEERCRED, method allowlist). The root exposure is the narrow, designed trust anchor (but see IS-013 for the missing sandbox directives).
3. `django` logger to NullHandler: privacy-first (IS-008 notes the trade-off), and `print` lines only carry request id and status.
4. `agentai_cells.nft` "drop-only" with `policy accept`: it only touches packets from `cell_sources`, to avoid breaking other tables (comment in the routes script; two engines clashed on 12 Oct).
5. `docker-compose` publishes LiteLLM on `127.0.0.1:4000`: loopback only, required for the model relay; README text is stale, config is safe.
6. `deploy/litellm.yaml` unreferenced duplicate and `DRILL_FAIL = False` in `release.py`: test hooks, not live bugs.
7. `BoundaryMiddleware` trusts `X-AgentAI-Client-IP`: only honored when the TCP peer is loopback and Caddy overwrites the header; gunicorn listens on 127.0.0.1 and `forwarded_allow_ips` is loopback only.
8. `SECURE_PROXY_SSL_HEADER` plus SSL redirect with all traffic via Caddy: Caddy sets `X-Forwarded-Proto https` explicitly.

## Cross-scope links

- Frontend `lumina` Live page polls `/v1/live/<task>/frame?t=` (Caddy `@liveframe`, `live/gateway.py`, ticket minted by `accounts` view using `AGENTAI_LIVE_SECRET_FILE`); the route must stay before the general `/v1` rule.
- `bin/deploy-lumina.py` writes `/var/lib/agentai-platform/ui` (UI bundle, `AGENTAI_UI_BUNDLE_DIR`) and refreshes `/var/www/lumina-scenes` (Caddy `@scenes`); owner is the frontend scope.
- `browse/runner.mjs` (browse scope) is hand-copied to `/opt/agentai-browse/runner/runner.mjs`; stage image `openclaw-sandbox-browser:phase4-2026.9.6` default (`service_main.py:55`).
- `accounts/urls.py` routes behind `/v1/*` (backend scope): `/healthz`, `/readyz`, `/v1/telegram/webhook`, `/v1/billing/webhook` are in `PUBLIC_UNMETERED` (`middleware.py:49`).
- `lifecycle/netpolicy.py` + `native_wiring.py` (lifecycle scope) generate the nft file; wiring keys `tool_relay_port`, `model_proxy_port`, `native_browser`, `safety_file`.
- Dashboard imports `routing/config` and owner switch modules by path (`dashboard/app.py:31-60`) and shells to `agentai_platform.routing.report_cli`.
- Uncommitted: `tool_relay.py`, `management/commands/tool_relay.py`, `lifecycle/{cell_bridge,cell_config,tool_origin}.py` and the new `tool_origin_plugin/` installer; this audit read the working-tree versions.

## Open questions for the maintainer

1. What does `ssk-key` authorize, and is it deployed on the VPS or on GitHub? Is SSH password login / root login still on?
2. Is `agentai-platform-control.service` enabled today, and does anything still call 18801 as control? Is `agentai-supervisor.service` (non-native) disabled?
3. Does TypeSafe receive screenshots of customer browsers in production (JEV `live` mode), and do the customer terms cover it?
4. Where is the second off-server backup copy (beyond Mac pull) and where do the age private-key copies live? Where is `AGENTAI_VAULT_KEY_FILE` and is it backed up?
5. Is the code on GitHub again, or still a single Mac plus bundles?
6. Which Vercel peer addresses does Caddy see, and is anonymous rate limiting (120 per minute) shared across customers in practice?
7. Does `openclaw-dashboard.service` run as root, and where is its unit committed?
8. Should the root units (browse, bridge) gain the full systemd sandbox set?

## DEPLOYMENT: read-only VPS comparison checklist (run later; nothing here is verified)

Run as root or with sudo, read-only. Compare against the repo file named in the right column. Do not print file contents of secrets: use `stat`, `sha256sum`, `grep -c` or key-name-only `awk -F= '{print $1}'`.

A. Units and drop-ins
- `systemctl list-unit-files 'agentai-*' 'openclaw-*' caddy.service fail2ban.service --no-pager` vs `platform/deploy/agentai-*.service` (extra/missing units; flag `openclaw-dashboard`, `openclaw-ops-backup`, `agentai-platform-control`, `agentai-supervisor`).
- `systemctl is-enabled agentai-platform-control agentai-supervisor agentai-supervisor-native agentai-browse`.
- For each repo unit: `systemctl cat <unit>` diff against the repo file; list drop-ins `ls /etc/systemd/system/*.service.d/` (expect `agentai-browse.service.d/jev.conf`, `openclaw-dashboard.service.d/feature-switches.conf`, `caddy.service.d/agentai-limits.conf`) and `systemd-analyze security <unit>` for root units.
- `systemctl list-timers --all | grep -E 'agentai|openclaw'` vs the 4 repo timers plus `openclaw-ops-backup.timer`.
- `systemctl --failed`.

B. Listeners and firewall
- `ss -lntp` vs expected: public only 22, 80, 443; loopback 18800 (app), 18801 (ONE owner only), 18789, 18790, 3978, 4000, 18795, 2019, 19101-19140 (cells); 10.77.0.1:4000 and :4100.
- `ufw status verbose`; `nft list table inet agentai_cells` vs `lifecycle/netpolicy.py` output for the wiring in `/etc/agentai-supervisor/native-wiring.json` (confirm doors for 4000 and 4100; IS-005); `cat /etc/agentai-cells/agentai_cells.nft | head -30`.
- `diff /etc/docker/daemon.json` (owner engine) and `/etc/agentai-cells/daemon.json` vs `platform/deploy/cells-docker/daemon.json`; `docker -H unix:///run/agentai-cells/docker.sock info | egrep 'Runtimes|Default Runtime'`; `runsc --version`.
- `sshd -T | egrep 'passwordauthentication|permitrootlogin|pubkeyauthentication|allowusers'`; `fail2ban-client status sshd`; `last -n 20`; `ls -la /root/.ssh/authorized_keys` (key count only, `ssh-keygen -lf` fingerprints, compare to the `ssk-key.pub` fingerprint from the Mac).

C. Caddy
- `diff /etc/caddy/Caddyfile platform/deploy/caddy/Caddyfile.getlumina`; `caddy validate --config /etc/caddy/Caddyfile`; `ls /etc/caddy/`; confirm `@liveframe` before `@customer`; `curl -sI` is network (skip). `cat /etc/systemd/system/caddy.service.d/*.conf`; `ls -la /var/www/lumina-scenes`.

D. App configuration (names only)
- `awk -F= '/^[A-Z_]+=/{print $1}' /etc/agentai-platform/accounts.env | sort` vs the env inventory above; `stat -c '%U:%G %a' /etc/agentai-platform/accounts.env /etc/agentai-platform/live.secret /etc/agentai-supervisor/*.json /var/lib/agentai-platform /var/lib/agentai-platform/platform.sqlite3 /var/lib/agentai-supervisor-secrets /var/backups/agentai /var/lib/agentai-ops /opt/openclaw-production/secrets /opt/openclaw-production/dashboard/owner-secret`.
- `python3 -c 'import json;d=json.load(open("/etc/agentai-supervisor/native-wiring.json"));print(sorted(d))'`; compare keys and `tool_relay_port`, `model_proxy_port`, `native_browser`, `safety_file` vs `native-wiring.example.json`.
- `cat /etc/agentai-supervisor/browse-engine.json` (per-account native overrides; expect none after 27 Oct) and `/opt/openclaw-production/feature-switches/switches.json` (switch states only, no secrets).
- `readlink /opt/agentai-platform/current /opt/agentai-supervisor/current`; `ls /opt/agentai-platform/releases /opt/agentai-supervisor/releases`; compare release ids to `evidence/deployments/*/deployment.json` (last: `20261027T114539Z-cancel-e700e33`, commit e700e33) and to `git log` (HEAD at audit time `03662de`; later commits ef2a8ac and 03662de may be undeployed).
- `sha256sum /opt/agentai-browse/runner/runner.mjs browse/runner.mjs` (Mac side) and `ls /opt/agentai-browse/runner`.
- Frontend: `ls -la /var/lib/agentai-platform/ui | head`, compare bundle hash with `lumina` build.
- DB: `sqlite3 -readonly /var/lib/agentai-platform/platform.sqlite3 'select max(name) from schema_migrations'` vs repo `platform/migrations` (latest in evidence: `0030_gen_artifact_events.sql`).

E. Owner stack
- `cd /opt/openclaw-production && docker compose config --quiet && diff docker-compose.yml <(repo deploy/docker-compose.production.yml)`; `docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'` (image digests vs compose pins; ports must be 127.0.0.1-bound); `docker inspect openclaw-production-openclaw-gateway-1 --format '{{.HostConfig.CapDrop}} {{.HostConfig.Binds}}'`.
- `diff` LiteLLM config mounted (`config/litellm.example.yaml`) and check `turn_off_message_logging: true` and `fail_closed_budget_enforcement: true`.
- Dashboard: `systemctl cat openclaw-dashboard` (User=?), `ss -lntp | grep 18795`, `ls -la /opt/openclaw-production/dashboard`.

F. Cells and tenants
- `docker -H unix:///run/agentai-cells/docker.sock ps --format '{{.Names}} {{.Status}}'` (count vs `max_running_cells`); `docker -H ... inspect <cell> --format '{{.HostConfig.Runtime}} {{.HostConfig.CapDrop}} {{.HostConfig.Privileged}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.NetworkMode}}'` for each cell.
- `ls -la /var/lib/agentai-fleet/.openclaw/fleet/cells | head` (modes 0700), `stat` of `/var/lib/agentai-browse/jobs` (0700) and age of oldest job dir (retention 24 h: `find /var/lib/agentai-browse/jobs -mindepth 1 -maxdepth 1 -mmin +1500 | wc -l`, expect 0).
- `journalctl -u agentai-browse --since '-1h' | grep -c 'browse:'` (no page text expected; spot check lengths only).

G. Backups and monitoring
- `systemctl status agentai-ops-backup.timer openclaw-ops-backup.timer`; `ls -la /var/backups/agentai/sets | tail`; `cat /var/lib/agentai-ops/backup-status.json | head -40` (assets covered vs `ops/inventory.py` `BACKED_UP`); `cat /etc/agentai-ops/config.json | python3 -c 'import json,sys;d=json.load(sys.stdin);print(sorted(d), [x["type"]+":"+str(x.get("offsite")) for x in d.get("destinations",[])])'` (offsite?); `cat /var/lib/agentai-ops/monitor-status.json | head -60`; confirm age recipient count (`age_recipients`), no `identity.txt` on host (`find / -name 'identity.txt' -path '*agentai*' 2>/dev/null`).
- Alerts: `[ -f /etc/agentai-ops/telegram-token ] && stat -c '%a %U' /etc/agentai-ops/telegram-token`.

H. Hand-made change audit (from RELEASE_NOTES.md:129-137)
- `ls -la /etc/agentai-platform/*.bak* /etc/caddy/*.bak* /opt/agentai-browse/runner/*.bak* /opt/openclaw-production/feature-switches/*.bak*` and `ls /root/*.bundle /root/*.tgz` (backup sprawl containing old configs and secrets; remove old `.bak` secrets copies after review).
- `ls -la /root` for stray releases/tarballs (`release.tgz`) that hold code or env.

I. Security spot checks (read-only)
- `ss -lntp | awk '$4 ~ /^(0.0.0.0|\[::\]|\*):/'` must show only 22/80/443.
- `find /etc/agentai-* /var/lib/agentai-* /opt/openclaw-production -maxdepth 3 \( -perm -o+r -o -perm -g+w \) -type f -name '*secret*' -o -name '*.key' -o -name '*.env'` for loose modes.
- `unattended-upgrades --dry-run -d` availability and `apt list --upgradable | head`; kernel/docker/runsc/caddy versions vs `versions.json` in the newest backup set.
- `journalctl --disk-usage` and `/etc/systemd/journald.conf` retention (log retention vs privacy; app logs carry only request ids).
