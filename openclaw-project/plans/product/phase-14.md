# Product Phase 14 — backups, recovery, monitoring and security operations

**Status (2026-10-12):** implementation **READY** (built, deployed, exercised on the live server); acceptance **NOT_RUN** (Phase 15).
**One launch blocker recorded:** there is no *automatic* off-server backup destination yet. Backups are encrypted and verified, kept on the
server (first tier) and copied to the owner's computer by `bin/pull-backups.py`; that protects against mistakes, corruption and a bad
release, and the pull gives a real outside copy, but losing the server *and* skipping a pull would lose up to a week. See "Decisions needed".
Runbooks: [`platform/OPERATIONS.md`](../../platform/OPERATIONS.md). Evidence: [`evidence/product/phase-14/20261012T2030Z/manifest.json`](../../evidence/product/phase-14/20261012T2030Z/manifest.json).

## What was built (all under `platform/agentai_platform/ops/` unless noted)

| Area | Piece | What it does |
|---|---|---|
| Inventory | `inventory.py` | Every recovery asset with owner, method and restore path; the monitor flags any asset missing from the newest set |
| Encryption | `crypto.py` | `age` with **public recipients only on the host**: the server can write backups but cannot read them; private key stays with the owner |
| Backup | `backup.py`, `destinations.py`, `hostconfig.py` | Consistency-aware sources (SQLite online backup, native archives, pg dump, config/secrets tar, versions), each verified before encryption and re-checked after copy; per-tenant artifacts and manifests keyed by hashed labels; incomplete sets never count as fresh and never trigger pruning; retention 14 daily + 2 weekly, **never past 30 days** (plan `backup_expiry_days`); plaintext pre-migration snapshots pruned (`housekeeping.py`) |
| Restore | `sets.py`, `restore.py` | Ciphertext hash/size check before decrypt, plain hash and file-type check after; account-scoped restore into a **new** database file with explicit per-table rules, proof that every other account and global table is byte-identical, ledger/billing/entitlements never rolled back, tombstones respected, restored schedules/watchers paused, browser profiles revoked, in-flight work blocked, reservations closed; an unclassified table aborts the restore |
| Monitoring | `monitor.py`, `hostprobe.py`, `exposure.py`, `pins.py` | 21 checks with ok / warn / crit / **unknown** (a probe that fails is never "ok"), correlation ids, hashed tenant labels only; services, owner stack, disk/memory, database integrity, lifecycle/request/billing queues and holds, backup freshness/coverage/per-tenant staleness/off-server copy, timers, TLS expiry, cells and egress firewall, host exposure (ports, firewall, secret modes, SSH), image/dependency pinning |
| Alerts | `alerts.py` | Only configured destinations (email now, Telegram supported), sanitized text, per-severity cooldown, one "resolved" message, monitor ↔ backup dead-man's switch |
| Rate limits | `accounts/middleware.py`, `accounts/requests.py`, `secrets_custody.py` | Anonymous ingress 120/min per source (probes and provider webhooks exempt); per-account task creation 30/hour on top of the queue and budget caps; per-key provider `rpm_limit`/`tpm_limit`; existing: login/recovery/MFA/webhook/billing/connector limits, API 60 read / 10 mutate per user, 3 streams per account |
| Rotation | `rotation.py` | Provider key (issue → store → revoke, failed revokes queued), webhook secret overlap, session secret |
| Support | `diagnostics.py` | States, counts, error codes and hashed account labels only; canary test proves no message text, names or references |
| Releases | `deploy/release.py` | Canary on a database copy, previous-release compatibility probe, brief stop, final backup, migrate, switch, probe, automatic rollback (restoring the pre-migration backup when the old code cannot read the new schema); sandbox drills |
| Tenant backups | `lifecycle/worker.py`, `coordinator.py` | The lifecycle worker queues a backup for each stopped cell older than 20 h (system request limited to stop/backup); running cells are never archived and show as stale |
| Operator tools | `bin/setup-backup-key.py`, `bin/pull-backups.py`, `ops cli` | Key creation on the owner's computer, verified pull, `check`, `verify`, `fetch`, `restore-account`, `diagnostics`, `inventory` |

Defect found and fixed while building: a system "backup" request was recorded as a "stop" because of a hard-coded kind (caught by a test).
Other build issues fixed (kept for the record): shared-engine test setup closures, a sanitizer that left half of a secret, first-run watchdog false alarm, canary scratch directory not reachable by the app user, sandbox state permissions.

## Recovery paths and owners (every selected production service)

App database, custody database, tenant cells, tenant secrets, model-proxy spend, owner runtime, configuration, versions: each has an inventory
entry with owner (the owner), method and restore procedure in `OPERATIONS.md`; Stripe state and DNS are provider-held with a stated procedure.
The encryption key has a stated custody rule (password manager + second copy, never on the host).

## Checks actually run

- Local: **421 platform** (2 skipped), **79 Django**, **35 dashboard** tests pass. New: 62 ops tests (real `age` encryption in the backup/restore/CLI tests) plus lifecycle and Django additions.
- Live on the server (2026-10-12): first encrypted set (7 artifacts, 12 MB, 7 s, complete); structural verify; monitor against the real host (19 ok, 2 warn: fresh timers not yet fired, SSH root password login); three real releases through the canary tool, all passed.
- Live on the owner's computer: set pulled and hash-verified; **all 7 artifacts decrypted and verified with the private key**; account-scoped restore run against the real production schema snapshot (every real table classified; other account unchanged, post-backup rows kept, backup rows restored); a flipped byte is rejected with "ciphertext hash mismatch" and no plain output.
- Drills in throwaway sandboxes (own release tree, database copy and port; production untouched): broken release **refused**; healthy canary with forced live failure → **automatic rollback** (binary compatible); schema-changing release with forced failure → **pre-migration database restored** and the drill table gone; clean sandbox release succeeds.
- Email alert path delivered real messages to the owner address (monitor and watchdog alerts).

## Findings and open items

1. **No automatic off-server destination (launch blocker).** Needs a destination: object storage (e.g. Backblaze B2, AWS S3) or a second server; the `command` destination type (rclone/scp) is built and tested with a fake, not against a real remote.
2. **SSH accepts passwords and root password login** (monitor warns). Moving to keys is a deliberate owner step (the helper scripts currently use the password); not changed.
3. **Nightly timers have not fired yet** (installed today). First scheduled fire, measured RPO/RTO and a restore after a real timer run are Phase 15.
4. **Tenant-cell backups in the nightly flow are tested offline only** (no enrolled tenants). Running cells cannot be archived; the sleep policy stops idle cells and the monitor flags stale tenants.
5. **Not automated yet:** emergency revocation of one account's LiteLLM key from the CLI, tenant gateway-token rotation (procedure documented), Telegram alert destination (supported, off), alert acknowledgement.
6. Backups hold secrets (tenant tokens, provider keys, owner env): protected only by the `age` key. Rotate everything after a suspected key leak.
7. The sandbox drill proves the release procedure; a full rehearsal on a second server was not run (no second server).

## Decisions needed from the owner
- Pick the off-server destination (or accept manual weekly pulls for the private beta only).
- Decide when to switch SSH to keys-only.
- Confirm alerts stay on email (the only enabled destination) or add Telegram.
- Keep or change RPO 24 h / RTO 30 min.

## Cost, unknowns, rollback
- **Cost:** nothing paid. A storage destination later is small (the sets are about 12 MB each, ≤ 16 sets).
- **Unknowns:** real RPO/RTO under load, behavior with real running tenants, deliverability of alerts to a spam folder, `age` format longevity (open specification, widely implemented).
- **Rollback:** `systemctl disable --now agentai-ops-backup.timer agentai-ops-monitor.timer`; the code is additive; configuration is `/etc/agentai-ops/config.json`; backups can stay or be removed (`/var/backups/agentai`). The previous app release is one `ln -sfn` away (`release.py` records the compatibility result for each release).
