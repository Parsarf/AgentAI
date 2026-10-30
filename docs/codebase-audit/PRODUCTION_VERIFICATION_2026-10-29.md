# Production verification — 2026-10-29

**Supersedes** every "production UNVERIFIED" statement in the other audit documents for the items listed below. Anything not listed here is still unverified.

## Method and what was (not) changed
- Connected as `root@179.236.71.203` (Hostinger VPS `srv2054170`, Ubuntu 26.04.1, up 12 days) with a new dedicated key (`~/.ssh/lumina_ed25519`, alias `ssh lumina`), after the owner installed it via the Hostinger web terminal.
- Ran the read-only script from `DEPLOYMENT_AUDIT.md` §6 (36 sections, checked beforehand for mutating commands) plus three small follow-ups (masked `systemctl cat` of two units, read-only `sqlite3` counts, a `cat` of `/etc/caddy/Caddyfile`). Raw output: `_findings/vps_readonly_2026-10-29.txt`. No secret values were printed (names and file modes only).
- **Nothing was changed on the server by the auditor.** Server-side changes in this session were made by the owner in the web terminal: `/root/.ssh/authorized_keys` now holds only the new key, and `/root/authorized_keys.bak-*` holds the old copy (public keys only; delete when convenient).
- Local changes (owner-approved): deleted `ssk-key`, `ssk-key.pub`, `~/.ssh/id_ed25519(.pub)`; generated `~/.ssh/lumina_ed25519`; rewrote the `lumina` entry in `~/.ssh/config` (backup `~/.ssh/config.bak-20261029`).
- The private key `ssk-key` was displayed in the session transcript when the owner asked for it to be read; it is deleted, was never authorized on this server, and was never in git.

## Which server is production (L-01 resolved)
`backend.getlumina.pro` → `179.236.71.203` (reverse DNS `srv2054170.hstgr.cloud`); `getlumina.pro` → Vercel. The IONOS address `69.48.206.62` (named in 17 tracked files) has ports 22 and 443 closed and nothing in DNS points at it. **The repo's runbooks target the wrong server.** The owner may delete the old IONOS server only after confirming nothing unique remains on it (see `CLEANUP_PLAN.md`).

## Results against findings
| Finding | Production result | Effect |
|---|---|---|
| L-01 | Live host is Hostinger; IONOS dead | Confirmed. Docs stale (class B). |
| IS-002 | `PasswordAuthentication yes`, `PermitRootLogin yes`; the server journal shows internet password-guessing (invalid user `admin`); fail2ban: 20 failures, 3 bans total | **Confirmed, High.** Disable password login now that key login works (needs owner approval; change is on the server). |
| IS-004 | `agentai-platform-control` and legacy `agentai-supervisor` units are **not installed**; 18801 is held by the live-view gateway | **Resolved.** Repo files are LEGACY (see `LEGACY_CODE.md`); no port clash in production. |
| IS-005 | Live `nft` table has doors for 10.77.0.1:4000 and :4100; ufw has matching rules; a `quarantined` set exists | Live rules are correct. The checked-in `agentai_cells.nft.generated` is a stale sample (class A after review). |
| IS-006 | Drop-ins exist: `agentai-browse.service.d/jev.conf` (`--jev-mode live`), `openclaw-dashboard.service.d/feature-switches.conf`; `openclaw-dashboard.service` exists only on the server and runs as root (no `User=`) with `ProtectSystem=strict`, `PrivateTmp`, `ProtectHome`, `MemoryMax=200M` | Confirmed. Commit these unit files as examples (class B/G). |
| Drift: `runner.mjs` | Live `/opt/agentai-browse/runner/runner.mjs` SHA-256 `b20b4250…ee643` **equals** the repo's `browse/runner.mjs` | No drift. Five `.bak-*` copies sit next to it. |
| Drift: Caddyfile | Live differs from `platform/deploy/caddy/Caddyfile.getlumina` by **one comment line** only | No functional drift. |
| AG-006 / M-08 | `/opt/agentai-platform/current` and `/opt/agentai-supervisor/current` → `20261028T212308Z-tool-origin-v2`. The UI bundle `lumina-ui-03662de` was installed 28 Oct 22:30 | **Confirmed: production runs the tool-origin v2 build that is uncommitted in git.** The only copies are the working tree and `/root/lumina-tool-origin-v2*.tgz`. Commit it (Phase 0 of `CLEANUP_PLAN.md`). |
| M-08 / AG-013 | `/etc/agentai-supervisor/browse-engine.json`: `{"default":"runner","native":[]}` | **The host Docker `runner.mjs` is the production browser engine; native browser engine is not rolled out to any account.** |
| M-02 / AG-002 / AG-003 | TypeSafe key files exist (`routing/typesafe.key`, `_shared/typesafe-key`); switches: `browse_tasks` ON, `jev_services` ON (owner confirmed `data_handling` 2026-10-14), `jev_routing` OFF; browse service starts with `--jev-mode live` | The JEV path is **live-capable in production**. Whether screenshots leave the host per step was read from code (`ladder.py:333,397`), not observed on the wire. The privacy decision (M-02) stands as High. |
| M-01 / BE-001 / AG-001 | 137 requests total (completed 120, failed 9, cancelled 8); all 133 reservations `settled`; **0 active reservations, 0 queued tasks, 0 waiting requests** | **Latent, not observed.** The code defect is unchanged, but no stuck allowance exists in production data (8 accounts). Treat as High-by-code, low current exposure. |
| BE-011 | Timers on the host: billing-worker, platform-mail, ops-monitor, ops-backup, openclaw-ops-backup. No `retention_accounts` timer, no root crontab, `/etc/cron.d` holds only docker/e2scrub jobs | Confirmed: nothing schedules retention. |
| BE-007 | `accounts.env` contains no `AGENTAI_TELEGRAM_*` names | Telegram is not configured in production (broken wiring is latent). |
| BE-015 | 20 `AGENTAI_*` names set; `AGENTAI_CARD_IMAGES` is set but read by no code; `AGENTAI_VAULT_KEY_FILE` and `AGENTAI_UPLOADS_ENABLED` are not set | Vault and uploads are inactive in production. |
| IS-016 | Backup config: one destination, `local`, off-server `False`; nightly sets present 20–29 Oct (10 sets, 759 MB); owner archive timer at 03:17 | Confirmed local-only on the host. An off-server copy (Mac pull) is not verified. |
| Exposure | Public listeners: 22, 80, 443 only. ufw default deny. Dashboard on 127.0.0.1:18795. 0 failed systemd units. `find` for group-writable/world-readable secret files: none | Good. |
| Cells | No customer cell container was running at check time | Cell isolation (`runsc`, caps, read-only root) was **not inspected**. |
| Schema | `schema_migrations` has 30 rows (repo has 30 SQL migrations); `django_migrations` present | Count matches. Checksums not compared. |

## New observations (not in the earlier findings)
- **PV-01 Release sprawl (Low/Medium, hygiene):** ~100 release directories under `/opt/agentai-platform/releases` (5.0 GB) and ~85 `.tgz` plus 2 `.bundle` files in `/root` (1.9 GB). The last code bundles are dated 14 Oct. Disk is 18% used, so no urgency. Some `.tgz` may be the only copy of released code.
- **PV-02 Secret copies on disk (Low):** `/etc/agentai-platform/accounts.env.bak-live1` and `.bak-safety1` (mode 600) hold old copies of the environment file. Review and remove when no longer needed.
- **PV-03 Pending OS updates (Medium):** 19 upgradable packages incl. kernel `7.0.0-38 → 42`, `docker-ce 29.9.0 → 29.9.2`, `containerd.io`, systemd. A reboot is needed for the kernel; uptime is 12 days. No unattended-upgrade state was checked.
- **PV-04 Switch provenance (Low):** `customer_execution` was turned ON by `claude-code-test-run` (2026-10-11/12) and `jev_routing` OFF by "assistant" 2026-10-13. Production switches were changed by automation labels, not named people; confirm this is intended.
- **PV-05 `last` not installed** on the server, so login history was not reviewed; the sshd journal was.

## Still unverified (next steps)
- Live cell isolation (needs a running cell), LiteLLM config (`turn_off_message_logging`, budgets), actual TypeSafe outbound traffic, backup restore, owner-side off-server backup, `accounts.env` values, and whether `/root/lumina-tool-origin-v2*.tgz` matches the uncommitted working tree.
- Proposed (needs owner approval before any change): disable SSH password and root-password login after confirming the new key works from a second session; commit the tool-origin v2 work; add `ssk-key*`-style patterns to the root `.gitignore`.

---

# Second pass (same day, still read-only)

## Production equals the uncommitted working tree (AG-006 refined)
`/root/lumina-tool-origin-v2.tgz` (platform) and `/root/lumina-tool-origin-v2-supervisor.tgz` were downloaded to a scratch directory, checked for unsafe paths (none), extracted in isolation and diffed against `openclaw-project/platform/{agentai_platform,accounts}`: **no differences**. SHA-256 prefixes of `tool_relay.py` and `lifecycle/tool_origin.py` on the server match the local files. **Committing the current working tree makes git match production exactly.** The release directory has no manifest file, so provenance is by directory name only.

## Verified results
| Item | Result |
|---|---|
| SSH hardening detail | `/etc/ssh/sshd_config.d/50-cloud-init.conf` sets `PasswordAuthentication yes` and is read before `60-cloudimg-settings.conf` (`no`), so the first value wins. `sshd_config` also has `PermitRootLogin yes`. To disable password login, edit `50-cloud-init.conf` (and set `PermitRootLogin prohibit-password`), validate with `sshd -t`, keep a second session open. Cloud-init may rewrite the file; check `/etc/cloud/cloud.cfg` `ssh_pwauth`. |
| Host monitor (`/var/lib/agentai-ops/monitor-status.json`, 21 checks, overall **warn**) | Three warns: `backup_offsite` ("NO off-server copy"), `host_exposure` ("SSH allows root login with a password"), `quarantine` ("a quarantined restore has been kept longer than the limit", 2 items; matches the two `quarantined` /24 ranges in the live nft table). The repo's own monitor already flags the first two; both remain open. |
| LiteLLM (`/opt/openclaw-production/config/litellm.yaml`) | `turn_off_message_logging: true`, `fail_closed_budget_enforcement: true`. Checklist item E closed. |
| Cells engine | Default runtime `runsc` (gVisor), `no-new-privileges: true`, bridge `agentai0`, pool `10.78.0.0/16`, `iptables: false`. 3 images. No cell running, so per-cell inspection is still open. |
| Unattended upgrades | Enabled (`20auto-upgrades`: update lists and unattended-upgrade both 1). No `/var/run/reboot-required`. 19 packages still upgradable (kernel, docker-ce, systemd), so the kernel update has not been applied. |
| Service errors, last 3 days (counts) | request-worker 1 (`CapabilityUnavailable`), platform-app 28, tool-relay 6, cell-bridge 0, supervisor-native 0. |

## New findings from the second pass
- **PV-06 (Low, HIGH confidence): recurring gunicorn "Control server error".** `agentai-platform-app` logs `[ERROR] Control server error: [Errno 13] Permission denied: '/home/agentai-platform'` about 28 times in 3 days (e.g. 2026-10-28 20:08, 20:44, 21:32, 21:47, 22:16, 22:56, 23:35; 2026-10-29 01:00). It looks like a gunicorn worker feature trying to create state under a home directory the sandboxed unit cannot write. No customer effect seen; it adds log noise and could hide real errors. Cause not investigated (read-only pass). Action D (low risk): point the setting at `StateDirectory`/disable it in `gunicorn.conf.py`. Verify on a canary.
- **PV-07 (Low, HIGH): `tool_relay` prints tracebacks on cell disconnects.** `ConnectionResetError: [Errno 104]` from cell `10.78.0.2` (2 occurrences in 3 days) is not caught by the relay's request loop (socketserver default handler). Harmless but noisy; the relay is in-progress code (AG-008 area). Action D.
- **PV-08 (Medium, HIGH): hand-installed experiment ran in production.** `journalctl -u agentai-browse` shows `JEV miss: ValueError: Full-page observation missing; refusing experimental JEV call` at 2026-10-28 23:03:29 and 23:03:48, then a service stop at 23:05:58. `/root/jev-full-page-experiment.tgz` (22:53) and `/root/jev-full-page-update.tgz` (23:01) are the overlays. The string exists in no tracked file and not in the current release (`grep` on `/opt/agentai-supervisor/current`), so the experiment was deployed outside the release process, ran for ~3 minutes against the live browse service (with `jev_services` ON), and was removed. The source is the untracked `openclaw-project/experiments/jev-full-page/`. It shows production can be patched by hand without a release record. Action E/F: require every production overlay to go through `release.py`, and record experiments in `evidence/deployments/`.
- **PV-09 (Info): monitor's `quarantine` warn.** Two quarantined restore directories are older than the configured limit; review and either release or delete per `ops/restore.py` rules (needs owner decision; deleting is destructive).

## Updated unverified list
Still not checked: per-cell isolation of a running cell, actual TypeSafe outbound payloads, backup restore, owner's off-server copy (the monitor says none exists on the host side; the Mac pull is unverified), `accounts.env` values, and whether the 2 quarantined restores contain customer data.
