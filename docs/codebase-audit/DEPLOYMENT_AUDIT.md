# Deployment audit: repository vs production

> **UPDATE 2026-10-29:** production was verified over SSH after this document was written. Statements below that production is "unverified" are superseded for the items in [PRODUCTION_VERIFICATION_2026-10-29.md](PRODUCTION_VERIFICATION_2026-10-29.md) (live host is Hostinger `179.236.71.203`; IONOS is dead; IS-002 and the tool-origin v2 drift confirmed; IS-004 resolved; M-01 latent, not observed).

Audit date 2026-10-29. Branch `product-phases-6-11`, HEAD `03662de`.

## Read this first: production was NOT verified

- No production fact in this audit is confirmed. Every statement about servers is reconstructed from repository files and dated evidence records.
- **L-03**: production SSH was attempted read-only, twice (only `hostname`, `date`, `uptime`). Both attempts failed. No command ran on any server.
- **L-01**: the old IONOS address `69.48.206.62` named by 17 tracked files (README, RUNBOOK, SERVER_DEPLOYMENT, OPERATIONS, `bin/ssh-server`) timed out on port 22 from the audit machine. The owner's `~/.ssh/config` has `Host lumina` pointing to a Hostinger VPS `179.236.71.203` (user root, key `~/.ssh/id_ed25519`), commented "Lumina production server"; no repo document mentions that host.
- **L-02**: the provided `ssk-key` was rejected by `179.236.71.203` (server offered publickey and password). Its public fingerprint (SHA256:NItwjEf8...) differs from `~/.ssh/id_ed25519.pub` (SHA256:Rnb3Iaou...). The configured `~/.ssh/id_ed25519` key was not used because it was not authorized for this task.
- `getlumina.pro` resolves to `216.198.79.1` (Vercel front). The API origin `backend.getlumina.pro` was not resolved. Conclusion: either production moved from IONOS to Hostinger, or the runbooks target an old server. Everything VPS-dependent stays UNVERIFIED, including IS-002 (password SSH to root), the whole IONOS-vs-Hostinger topology, and whether the dated 2026-10-27 deployment evidence describes the host that serves customers today.

## 1. Intended topology (from the repository)

Reconstructed from `platform/deploy/*`, `SERVER_DEPLOYMENT.md`, `OPERATIONS.md`, `docs/architecture/native-execution.md`:

- **Edge**: Vercel static build plus rewrites for `/account /auth /v1 /app` to `BACKEND_ORIGIN` (`platform/deploy/vercel/routing.mjs`). Backend host `backend.getlumina.pro` runs Caddy (auto TLS). Caddy routes `^/v1/live/<32hex>/frame$` to 127.0.0.1:18801 (flush -1), `/app/scenes/*` from `/var/www/lumina-scenes`, `/account /auth /v1 /app` to 127.0.0.1:18800 with Host forced to `getlumina.pro` and `X-AgentAI-Client-IP`/`X-Forwarded-For` set from `{remote_host}` (M-04), everything else 404.
- **Customer app**: gunicorn (1 worker, sync, 1 thread, timeout 15) on 18800, SQLite at `/var/lib/agentai-platform/platform.sqlite3` in a 0700 state dir. Units: `agentai-platform-app`, `-request-worker`, `-lifecycle-worker`, `-supervisor-native` (root), `-cell-bridge` (root), `-browse` (root, live gateway thread on 18801), `-tool-relay` (10.77.0.1:4100), `-model-proxy` (10.77.0.1:4000 to LiteLLM 127.0.0.1:4000); timers: billing-worker 30 s, platform-mail 60 s, ops-backup 03:40 UTC, ops-monitor 5 min.
- **Tenants**: per-customer gVisor container on a separate Docker engine (`/run/agentai-cells/docker.sock`), bridge 10.77.0.1/16, pool 10.78.0.0/16, nft table `agentai_cells` with two doors (4000 model relay, 4100 tool relay).
- **Owner stack** (`/opt/openclaw-production`): postgres, LiteLLM (127.0.0.1:4000), OpenClaw Gateway (loopback 18789/18790/3978, mounts docker.sock), dashboard 18795 (unit not in repo).
- **Public ports expected**: 22, 80, 443 only (`ops/monitor.py:24`).
- **Release process**: `platform/deploy/release.py` canary release with schema-compatible rollback; `bin/deploy-lumina.py` writes the UI bundle to `/var/lib/agentai-platform/ui` and refreshes `/var/www/lumina-scenes`; dated records in `evidence/deployments/*` (latest recorded: `20261027T114539Z-cancel-e700e33`, commit e700e33).

## 2. Repo-versus-docs contradictions

| ID | Contradiction | Where |
|---|---|---|
| L-01 | IONOS `69.48.206.62` in 17 tracked files vs owner's Hostinger `lumina` host; IONOS unreachable | README, RUNBOOK:96, SERVER_DEPLOYMENT:19-20, OPERATIONS, `bin/ssh-server` |
| ST-014 | README says Phases 1-2 delivered and phase 4 next; RUNBOOK header says no persistent listener installed; BUILD_LOG stops 2026-10-12 while work continued to 10-27 | README.md, RUNBOOK.md:1-35, ARCHITECTURE.md:1-45 |
| M-11 | ServiceRouter described as live; deleted in 5db9636 | CLAUDE.local.md, docs/architecture/*, docs/orchestration-audit/* |
| IS-015 | Privacy doc says one host door (now two: 4000 and 4100); deploy README says LiteLLM has no published port (compose publishes 127.0.0.1:4000); `RELEASE_NOTES.md` out of chronological order; `SERVER_DEPLOYMENT.md` still says "Gate 1 still awaits owner access checks" | privacy.md:6-7, deploy/README.md:19-20 |
| IS-002 | privacy.md says key-only server login; OPERATIONS.md:97 says move to key login is still to do; RUNBOOK uses root password | |
| ST-013 | Seven unit files not named in OPERATIONS/RUNBOOK/deploy README | platform/deploy |
| IS-005 | `agentai_cells.nft.generated` (no doors) vs `netpolicy.py` (doors 4000/4100) | cells-docker |
| IS-004 | Port 18801 assigned to both control server and live gateway | config.example.json:5 vs service_main.py:54 |
| OP-015 | LAUNCH.md says JEV routing record-only; code says JEV decides browser steps; model 1.13 vs 1.14 | LAUNCH.md:6, cell_config.py:15 |
| GH-005 | RELEASE_NOTES documents native1-4 and safety1 deploys with no tag or hash | RELEASE_NOTES.md:1,18 |
| IS-017 | GitHub suspended 14 Oct (stale?) vs README/CI/PR #1 assume GitHub | RELEASE_NOTES.md:151-155 |
| BE-016 | `readyz`/`signin` hard-code `execution_enabled:false` while execution can be live | views.py:108-109,149 |
| IS-018 | CLAUDE.local.md says `evidence/` is not indexed but 183 files are tracked | |

## 3. Hand-made server changes not in git (IS-006)

From `RELEASE_NOTES.md:129-137` and units referenced by code:

1. `/etc/systemd/system/openclaw-dashboard.service` and `openclaw-dashboard.service.d/feature-switches.conf` (dashboard is a REQUIRED_UNIT; no unit in repo).
2. `/etc/systemd/system/agentai-browse.service.d/jev.conf` (`--jev-mode live`; code default is already `live`, so redundant or hides other overrides).
3. `/opt/agentai-browse/runner/runner.mjs`: copied by hand five times (`.bak-live1/5/7`) from `browse/runner.mjs`; no repo script syncs it.
4. `/etc/agentai-platform/live.secret`, `AGENTAI_LIVE_SECRET_FILE` and `AGENTAI_SAFETY_OWNER_ACCOUNT` lines in `accounts.env`, `"safety_file"` in `native-wiring.json`, `/etc/caddy/Caddyfile` (the `/app/scenes` block added by 4bdf03c; deployed state unverified).
5. `openclaw-ops-backup.service/.timer` (owner backup 03:17 UTC; referenced by `agentai-ops-backup.service:3`).
6. `/etc/caddy/Caddyfile.before-agentai`, `/etc/docker/daemon.json`, `/etc/agentai-ops/config.json`, `/etc/agentai-supervisor/{fleet-custody,browse-engine}.json`.
7. Owner switch values (`feature-switches/switches.json`), for example `jev_services` ON on 14 Oct per release notes.

## 4. Candidates for drift (repo state that may differ from what runs)

| ID | Candidate | Why it may differ | How to check |
|---|---|---|---|
| AG-006 / M-08 | Tool-origin v2 (`tool_origin*.py`, plugin, relay busy-lanes, cell_config hook) is UNCOMMITTED (IN PROGRESS) but `docs/browser-tool-ownership.md` (untracked) says release `20261028T212308Z-tool-origin-v2` is live and verified by manifest | Prod may run code with no commit | `readlink /opt/agentai-platform/current`, manifest hashes vs working tree |
| IS-006 | `/opt/agentai-browse/runner/runner.mjs` hand copies | No sync script | `sha256sum` vs `browse/runner.mjs` |
| GH-013 / IS-006 | Commits `ef2a8ac` (browser reliability, interactive generative UI) and `03662de` (chatbar Tools menu) are later than the last deployment record (`20261027T114539Z-cancel-e700e33`, e700e33) and may be undeployed; 42cb3fd (daily $15) and 2612e41 sit between | Evidence stops at e700e33 | compare release ids to `git log` |
| M-11 | If prod still runs live3/live4-era code, `routing/services.py` exists there | Deleted in 5db9636 | `ls` routing dir on host |
| M-08 | Browse engine per account (`/etc/agentai-supervisor/browse-engine.json`); an OOM canary on 27 Oct reverted an account to the runner | Default `runner`; native gated | read the file |
| GH-018 | `/var/www/lumina-scenes` still served by Caddy though source assets moved to `lumina-character` | deploy script references unchecked | `ls`, `bin/deploy-lumina.py` |
| BE-005 / BE-011 | No `--reconcile` timer, no `retention_accounts` schedule in repo; host cron may exist | Out-of-repo cron | `crontab -l`, `systemctl list-timers` |
| IS-005 | Real `/etc/agentai-cells/agentai_cells.nft` vs sample | generated at runtime | `nft list table inet agentai_cells` |
| M-02 | Is the TypeSafe key installed (`/var/lib/agentai-platform/routing/typesafe.key`, `_shared/typesafe-key`)? | Gate is key file only | `stat` (not contents) |
| GH-013 | Vercel/CI may deploy from `origin/main` (PR #1 merge of 12 Oct), 87 commits behind P | Unknown | Vercel project settings |
| BE-003 | Whether Caddy sees Vercel peer addresses | Header overwrite | access logs (privacy: sample count only) |

## 5. Unit and port conflicts (IS-004 and related)

- Port **18801**: `agentai-platform-control.service` (legacy stdlib server, `config.server.example.json:5`) vs live-frame gateway thread in `agentai-browse` (`service_main.py:54`, Caddy `@liveframe`). `server-smoke.json` (30 Sep) showed the control listener. If both enabled, one fails to bind; the browse side logs nothing (daemon thread).
- **`agentai-supervisor.service`** (custody-only, legacy) and **`agentai-supervisor-native.service`** both declare `RuntimeDirectory=agentai-supervisor`; they cannot both run. Confirm the old one is disabled.
- **`openclaw-dashboard`** is a REQUIRED_UNIT with no repo unit; **`agentai-browse`** is a root unit missing from the monitor list (IS-003).
- Cells reach host doors 10.77.0.1:4000 and :4100; the checked-in nft sample has neither (IS-005); `native-wiring.example.json:10` has `model_proxy_port: null` while docs say 4000.
- 2019 (Caddy admin) is in `LOOPBACK_PORTS` and undocumented (IS-015g).

## 6. Read-only VPS checklist (run later, owner reviews first)

The commands below are read-only. Do not print secret contents: use `stat`, `sha256sum`, `grep -c` or key-name-only `awk -F= '{print $1}'`. Run as root on the CORRECT host (first resolve L-01). Save the output; do not paste it into chat unreviewed. The script at the end bundles all sections.

**A. Identity and units**
- `hostname; date -u; uptime; cat /etc/os-release | head -3` (confirms which provider/host this is).
- `systemctl list-unit-files 'agentai-*' 'openclaw-*' caddy.service fail2ban.service --no-pager` vs `platform/deploy/agentai-*.service`; flag `openclaw-dashboard`, `openclaw-ops-backup`, `agentai-platform-control`, `agentai-supervisor`.
- `systemctl is-enabled agentai-platform-control agentai-supervisor agentai-supervisor-native agentai-browse`.
- For each repo unit `systemctl cat <unit>` diffed with the repo file; `ls /etc/systemd/system/*.service.d/` (expect `agentai-browse.service.d/jev.conf`, `openclaw-dashboard.service.d/feature-switches.conf`, `caddy.service.d/agentai-limits.conf`); `systemd-analyze security <unit>` for root units.
- `systemctl list-timers --all | grep -E 'agentai|openclaw'` (expect billing-worker, platform-mail, ops-backup, ops-monitor, openclaw-ops-backup); `systemctl --failed`.

**B. Listeners and firewall**
- `ss -lntp`: public only 22/80/443; loopback 18800, 18801 (ONE owner), 18789, 18790, 3978, 4000, 18795, 2019, 19101-19140; 10.77.0.1:4000 and :4100. `ss -lntp | awk '$4 ~ /^(0.0.0.0|\[::\]|\*):/'` must show only 22/80/443.
- `ufw status verbose`; `nft list table inet agentai_cells`; `head -30 /etc/agentai-cells/agentai_cells.nft` (confirm doors 4000/4100).
- Compare `/etc/docker/daemon.json` and `/etc/agentai-cells/daemon.json` with `platform/deploy/cells-docker/daemon.json`; `docker -H unix:///run/agentai-cells/docker.sock info | egrep 'Runtimes|Default Runtime'`; `runsc --version`.
- `sshd -T | egrep 'passwordauthentication|permitrootlogin|pubkeyauthentication|allowusers'`; `fail2ban-client status sshd`; `last -n 20`; `ssh-keygen -lf /root/.ssh/authorized_keys` (fingerprints only; compare with the Mac's `ssh-keygen -lf ssk-key.pub` and `~/.ssh/id_ed25519.pub`).

**C. Caddy**
- `diff /etc/caddy/Caddyfile platform/deploy/caddy/Caddyfile.getlumina`; `caddy validate --config /etc/caddy/Caddyfile`; `ls /etc/caddy/`; confirm `@liveframe` is before `@customer`; `cat /etc/systemd/system/caddy.service.d/*.conf`; `ls -la /var/www/lumina-scenes`.

**D. App configuration (names only)**
- `awk -F= '/^[A-Z_]+=/{print $1}' /etc/agentai-platform/accounts.env | sort` vs the env inventory in `_findings/infra_security.md`.
- `stat -c '%U:%G %a %n'` on `/etc/agentai-platform/accounts.env /etc/agentai-platform/live.secret /etc/agentai-supervisor/*.json /var/lib/agentai-platform /var/lib/agentai-platform/platform.sqlite3 /var/lib/agentai-supervisor-secrets /var/backups/agentai /var/lib/agentai-ops /opt/openclaw-production/secrets /opt/openclaw-production/dashboard/owner-secret`.
- Wiring keys: `python3 -c 'import json;d=json.load(open("/etc/agentai-supervisor/native-wiring.json"));print(sorted(d))'` vs `native-wiring.example.json` (`tool_relay_port`, `model_proxy_port`, `native_browser`, `safety_file`).
- `cat /etc/agentai-supervisor/browse-engine.json` and `/opt/openclaw-production/feature-switches/switches.json` (switch states only; expect `jev_*`, `browse_tasks`, `customer_execution`, `open_signups`, `billing_checkout`).
- Releases: `readlink /opt/agentai-platform/current /opt/agentai-supervisor/current`; `ls /opt/agentai-platform/releases /opt/agentai-supervisor/releases`; compare with `evidence/deployments/*/deployment.json` (last `20261027T114539Z-cancel-e700e33`) and `git log` (HEAD `03662de`).
- `sha256sum /opt/agentai-browse/runner/runner.mjs` vs the Mac's `browse/runner.mjs`; `ls /opt/agentai-browse/runner`.
- `ls -la /var/lib/agentai-platform/ui | head` vs a fresh `lumina` build hash.
- `sqlite3 -readonly /var/lib/agentai-platform/platform.sqlite3 'select max(name) from schema_migrations'` vs `platform/migrations` (latest in evidence `0030_gen_artifact_events.sql`).
- TypeSafe key presence only: `stat -c '%U:%G %a' /var/lib/agentai-platform/routing/typesafe.key /var/lib/agentai-supervisor-secrets/_shared/typesafe-key` (M-02).

**E. Owner stack**
- `cd /opt/openclaw-production && docker compose config --quiet`; diff compose with `deploy/docker-compose.production.yml`; `docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'` (ports must be 127.0.0.1-bound; image digests vs pins); `docker inspect openclaw-production-openclaw-gateway-1 --format '{{.HostConfig.CapDrop}} {{.HostConfig.Binds}}'`.
- LiteLLM config: `turn_off_message_logging: true`, `fail_closed_budget_enforcement: true`.
- Dashboard: `systemctl cat openclaw-dashboard` (User=?), `ss -lntp | grep 18795`, `ls -la /opt/openclaw-production/dashboard`.

**F. Cells and tenants**
- `docker -H unix:///run/agentai-cells/docker.sock ps --format '{{.Names}} {{.Status}}'` (count vs `max_running_cells`); per cell `docker -H ... inspect <cell> --format '{{.HostConfig.Runtime}} {{.HostConfig.CapDrop}} {{.HostConfig.Privileged}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.NetworkMode}}'`.
- `ls -la /var/lib/agentai-fleet/.openclaw/fleet/cells | head` (0700); `stat /var/lib/agentai-browse/jobs` (0700); `find /var/lib/agentai-browse/jobs -mindepth 1 -maxdepth 1 -mmin +1500 | wc -l` (expect 0).
- `journalctl -u agentai-browse --since '-1h' | grep -c 'browse:'` (count only; do not read page text).

**G. Backups and monitoring**
- `systemctl status agentai-ops-backup.timer openclaw-ops-backup.timer`; `ls -la /var/backups/agentai/sets | tail`; `head -40 /var/lib/agentai-ops/backup-status.json`; `python3 -c` listing config keys and `offsite` flags from `/etc/agentai-ops/config.json`; `head -60 /var/lib/agentai-ops/monitor-status.json`; `find / -name 'identity.txt' -path '*agentai*' 2>/dev/null` (no age identity on host).
- `[ -f /etc/agentai-ops/telegram-token ] && stat -c '%a %U' /etc/agentai-ops/telegram-token`.
- Cron: `crontab -l; ls /etc/cron.d` (look for `retention_accounts`, `--reconcile`).

**H. Hand-made change audit**
- `ls -la /etc/agentai-platform/*.bak* /etc/caddy/*.bak* /opt/agentai-browse/runner/*.bak* /opt/openclaw-production/feature-switches/*.bak*`; `ls -la /root` for `*.bundle`, `*.tgz`, `release.tgz` (backup sprawl holding old configs and secrets).

**I. Security spot checks**
- `find /etc/agentai-* /var/lib/agentai-* /opt/openclaw-production -maxdepth 3 -type f \( -name '*secret*' -o -name '*.key' -o -name '*.env' \) \( -perm -o+r -o -perm -g+w \)` (loose modes).
- `unattended-upgrades --dry-run -d`; `apt list --upgradable | head`; kernel/docker/runsc/caddy versions vs `versions.json` in the newest backup set.
- `journalctl --disk-usage`; `/etc/systemd/journald.conf` retention.

### One-script form (for owner review before running)

Save as `lumina-readonly-audit.sh`, review every line, then run `sudo bash lumina-readonly-audit.sh > audit-$(date +%F).txt 2>&1` ON THE SERVER. Nothing below writes outside stdout; there are no `rm`, `systemctl start/stop`, `docker run/exec`, or network calls.

```bash
#!/usr/bin/env bash
# Read-only Lumina production audit. Review before running. Prints no secret contents.
set +e
sec() { printf '\n===== %s =====\n' "$1"; }
sec identity;   hostname; date -u; uptime; head -3 /etc/os-release
sec units;      systemctl list-unit-files 'agentai-*' 'openclaw-*' caddy.service fail2ban.service --no-pager
sec enabled;    systemctl is-enabled agentai-platform-control agentai-supervisor agentai-supervisor-native agentai-browse openclaw-dashboard 2>&1
sec dropins;    ls -la /etc/systemd/system/*.service.d/ 2>&1
sec timers;     systemctl list-timers --all --no-pager | grep -E 'agentai|openclaw'
sec failed;     systemctl --failed --no-pager
sec listeners;  ss -lntp
sec public;     ss -lntp | awk '$4 ~ /^(0.0.0.0|\[::\]|\*):/'
sec ufw;        ufw status verbose 2>&1
sec nft;        nft list table inet agentai_cells 2>&1
sec sshd;       sshd -T 2>&1 | grep -E 'passwordauthentication|permitrootlogin|pubkeyauthentication|allowusers'
sec fail2ban;   fail2ban-client status sshd 2>&1
sec lastlog;    last -n 20
sec authkeys;   for f in /root/.ssh/authorized_keys; do [ -f "$f" ] && ssh-keygen -lf "$f"; done
sec caddy;      caddy validate --config /etc/caddy/Caddyfile 2>&1 | tail -3; ls -la /etc/caddy /var/www/lumina-scenes 2>&1; sha256sum /etc/caddy/Caddyfile
sec envnames;   awk -F= '/^[A-Z_]+=/{print $1}' /etc/agentai-platform/accounts.env 2>&1 | sort
sec modes;      stat -c '%U:%G %a %n' /etc/agentai-platform/accounts.env /etc/agentai-platform/live.secret /etc/agentai-supervisor/*.json /var/lib/agentai-platform /var/lib/agentai-platform/platform.sqlite3 /var/lib/agentai-supervisor-secrets /var/backups/agentai /var/lib/agentai-ops /opt/openclaw-production/secrets /opt/openclaw-production/dashboard/owner-secret 2>&1
sec typesafe;   stat -c '%U:%G %a %n' /var/lib/agentai-platform/routing/typesafe.key /var/lib/agentai-supervisor-secrets/_shared/typesafe-key 2>&1
sec wiring;     python3 -c 'import json;print(sorted(json.load(open("/etc/agentai-supervisor/native-wiring.json"))))' 2>&1
sec engines;    cat /etc/agentai-supervisor/browse-engine.json 2>&1
sec switches;   cat /opt/openclaw-production/feature-switches/switches.json 2>&1
sec releases;   readlink /opt/agentai-platform/current /opt/agentai-supervisor/current 2>&1; ls /opt/agentai-platform/releases /opt/agentai-supervisor/releases 2>&1
sec runner;     sha256sum /opt/agentai-browse/runner/runner.mjs 2>&1; ls -la /opt/agentai-browse/runner 2>&1
sec ui;         ls -la /var/lib/agentai-platform/ui 2>&1 | head
sec migrations; sqlite3 -readonly /var/lib/agentai-platform/platform.sqlite3 'select max(name) from schema_migrations' 2>&1
sec compose;    (cd /opt/openclaw-production && docker compose config --quiet 2>&1; docker ps --format '{{.Names}} {{.Image}} {{.Ports}}')
sec cells;      docker -H unix:///run/agentai-cells/docker.sock ps --format '{{.Names}} {{.Status}}' 2>&1
sec cellinspect; for c in $(docker -H unix:///run/agentai-cells/docker.sock ps -q 2>/dev/null); do docker -H unix:///run/agentai-cells/docker.sock inspect "$c" --format '{{.Name}} {{.HostConfig.Runtime}} {{.HostConfig.CapDrop}} {{.HostConfig.Privileged}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.NetworkMode}}'; done
sec jobs;       stat -c '%a %n' /var/lib/agentai-browse/jobs 2>&1; find /var/lib/agentai-browse/jobs -mindepth 1 -maxdepth 1 -mmin +1500 2>/dev/null | wc -l
sec backups;    systemctl status agentai-ops-backup.timer openclaw-ops-backup.timer --no-pager 2>&1 | head -20; ls -la /var/backups/agentai/sets 2>&1 | tail
sec backupcfg;  python3 -c 'import json;d=json.load(open("/etc/agentai-ops/config.json"));print(sorted(d),[x.get("type","?")+":"+str(x.get("offsite")) for x in d.get("destinations",[])])' 2>&1
sec identity_on_host; find / -xdev -name 'identity.txt' -path '*agentai*' 2>/dev/null
sec cron;       crontab -l 2>&1; ls /etc/cron.d 2>&1
sec baks;       ls -la /etc/agentai-platform/*.bak* /etc/caddy/*.bak* /opt/agentai-browse/runner/*.bak* /opt/openclaw-production/feature-switches/*.bak* /root/*.bundle /root/*.tgz 2>&1
sec loosemodes; find /etc/agentai-* /var/lib/agentai-* /opt/openclaw-production -maxdepth 3 -type f \( -name '*secret*' -o -name '*.key' -o -name '*.env' \) \( -perm -o+r -o -perm -g+w \) 2>/dev/null
sec upgrades;   apt list --upgradable 2>/dev/null | head -20; journalctl --disk-usage
```

Caveats: `stat`/`ls` of key files show names and modes only. `cat` is used only for `browse-engine.json` and `switches.json` (switch states, no secrets); review those two lines before running if unsure. `docker compose config --quiet` may expand env from `.env` internally but prints nothing on success.

## 7. How to unblock access

Pick one; do not paste private key material into chat.

1. **(a) Authorize `ssk-key` on the target server.** Append the contents of `ssk-key.pub` (the PUBLIC key; safe to copy) to `~/.ssh/authorized_keys` of the intended user on the target server, using the host provider's web console or browser terminal, or an already-working session. Then tell the assistant which user and host to use.
2. **(b) Use the existing owner key.** Tell the assistant explicitly to use the `lumina` alias and `~/.ssh/id_ed25519` (the alias already points to `179.236.71.203`, user root). It was not used so far because it was not authorized for this task.
3. **(c) Confirm the correct server and network path.** Confirm which IP is production (Hostinger `179.236.71.203` vs the old IONOS `69.48.206.62`; check where `backend.getlumina.pro` resolves), that port 22 is open to the audit machine's current public IP in the provider firewall and not blocked by fail2ban, and that the IONOS host still exists (its port 22 timed out).

After access exists: run section 6 (single script), then replace each UNVERIFIED label in `TECHNICAL_DEBT.md` and `SECURITY_AND_RELIABILITY.md` with the observed result, and update the docs per L-01.
