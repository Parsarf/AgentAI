# Operations runbook (Phase 14)

Single operator: the owner. "Escalation" below therefore means which outside party to contact. Everything here is
for the current single server (`179.236.71.203`) and the invitation-only beta. Commands run on the server as root
unless noted; the safe way is `python3 openclaw-project/bin/ssh-server '<command>'` from your computer.
Set `PYTHONPATH=/opt/agentai-platform/current` and `cd /opt/agentai-platform/current` before `python3 -m agentai_platform.ops.cli ...`.

## 1. What normal looks like

- Monitor every 5 minutes (`agentai-ops-monitor.timer`) writes `/var/lib/agentai-ops/monitor-status.json`; the nightly set runs at 03:40 UTC (`agentai-ops-backup.timer`).
- Alerts arrive by email at the owner address only when something is **warn** or **crit**, at most once per cooldown (crit 1 h, warn 6 h), plus one "resolved" message.
- Quick look: `ops monitor --no-alert` prints counts; `ops verify` checks the newest backup set; `ops inventory` lists every protected asset and who owns it.

## 2. Backups and keys

| Item | Setting |
|---|---|
| What | App database (online backup), supervisor custody database, per-tenant cell archives, tenant secrets, model-proxy spend dump, owner runtime archive, configuration, versions manifest |
| Where | `/var/backups/agentai/sets/<UTC id>/` (first tier, same server) **and** your computer (`bin/pull-backups.py`) |
| Encryption | `age`, public recipients only on the server: the server can write but **cannot read** backups |
| Key | Private file `~/agentai-backup-key/identity.txt` on your computer. Put it in your password manager and keep a second copy elsewhere. Lose it and every backup is unreadable; leak it and every backup is readable |
| Retention | Daily for 14 days plus two weekly points, **never older than 30 days** (contract); the newest set is always kept. Plaintext pre-migration database snapshots are pruned to the newest 3 |
| Per-tenant | Each cell archive is its own encrypted file with its own manifest keyed by a hashed label; the full set needs your key |
| Verification | Plain artifacts are integrity-checked before encryption; ciphertext hash and size are checked after copy; `fetch` re-checks ciphertext hash, decrypts, checks the plain hash and the file type |
| Targets | RPO 24 h, RTO 30 min (proposed; measured proof is Phase 15) |

**Pull a copy to your computer (do this at least weekly; it is also your off-server copy):** `python3 openclaw-project/bin/pull-backups.py`.
The monitor treats a pull in the last 7 days as an outside copy; without one it warns "NO off-server copy". A real automatic off-server destination (object storage or a second server) is a **launch blocker** until configured: add a `command` destination to `/etc/agentai-ops/config.json` (see `deploy/ops-config.example.json`).

### Restore one account (A) without touching B or the usage ledger
1. Pull the newest set (`pull-backups.py`).
2. On the server, **stop the app**: `systemctl stop agentai-platform-app agentai-billing-worker.timer`. The account must be quiet (no running task/request/operation) or the tool refuses.
3. On your computer: `cd openclaw-project/platform && .venv/bin/python -m agentai_platform.ops.cli restore-account --config <your local config> --identity ~/agentai-backup-key/identity.txt --account <id> --live-db <copy of the live database> --out <folder>`.
4. Read the report: `other_accounts_unchanged` and `ledger_intact` must be true. Restored schedules/watchers are paused, browser profiles revoked, in-flight tasks blocked, restored reservations closed; usage history and billing are never rolled back; deleted (tombstoned) conversations are not brought back.
5. Copy the output file over `/var/lib/agentai-platform/platform.sqlite3` (owner `agentai-platform`, mode 0600), start the app, then run `manage.py billing_worker --reconcile` so access follows Stripe's current state, not the old backup.

### Restore a customer cell
Fleet restore refuses another tenant's slug, so cells restore into a **quarantine cell** (own volume, network and token, egress dropped before it starts): `FleetCliDriver` `restore` claim, verified live in Phase 4. Inspect it, then promote deliberately; `discard_quarantine` removes only that quarantine.

### Rebuild the host from nothing (outline, RTO target 30 min of hands-on time once a host exists)
New Ubuntu server → install Docker, Caddy, gVisor, age, nftables, fail2ban per `deploy/README.md` → `pull` your latest set back onto the server → `fetch` with your key → extract `config` and `tenant-secrets` → restore the app and custody databases → restore the owner archive (`bin/ops-restore.sh`) and the spend dump → point DNS at the new IP → run the monitor. Billing: reconcile with Stripe afterwards.

### A backup that will not decrypt or verify
`fetch` prints the reason (size, damaged ciphertext, wrong key, plain-hash mismatch, failed file check) and leaves no plain output. Use the previous set; never edit a manifest to "make it pass".

## 3. Alerts and the dead-man's switch

Destinations are configured by the owner in `/etc/agentai-ops/config.json` (email now; Telegram supported but off). Only those destinations can receive alerts; callers cannot name one.
Alert text carries a check name, one sentence, counts and a correlation id. It never carries tenant content, tenant references, tokens or paths (enforced by a sanitizer and tests).
The monitor and the backup job watch each other: if either stops reporting, the other raises `watchdog.<name>`.

## 4. Incidents

| Severity | Examples | Respond | Notify customers |
|---|---|---|---|
| SEV1 | Possible cross-customer exposure; leaked secret; host compromise; data loss | Immediately. Contain first (section 5), then diagnose | Yes, after facts are confirmed (draft C) |
| SEV2 | Service down; backups failing or stale; database integrity failure; billing granting wrong access | Within 1 hour | If customers are affected for more than 30 minutes (draft A) |
| SEV3 | One tenant's task or cell failing; dead-lettered billing events; certificate under 14 days; unresolved lifecycle holds | Same day | Only the affected customer |
| SEV4 | Single warn that clears; cosmetic issues | Next working day | No |

Steps: **contain** (switches, suspend, stop workers) → **preserve** (do not delete evidence; take `ops diagnostics`) → **diagnose** (monitor status, `journalctl`, diagnostics) → **recover** (restore or roll back, section 7) → **tell** (drafts below, only confirmed facts) → **review** (write what happened and what changes). Outside contacts: Stripe support (billing), Anthropic support (model access), IONOS support (server/network), your domain DNS provider.

### Notification drafts (fill brackets with confirmed facts only; never promise what you have not verified)
- **A. Outage:** "Between [start] and [end] UTC the AgentAI service was unavailable. Work that was running was [stopped and can be resubmitted / is safe]. Files you uploaded and results already produced were not affected. We are monitoring and will tell you if anything changes."
- **B. Billing:** "We could not confirm your latest payment. You can keep starting tasks until [time]; after that new tasks pause while running work finishes and your files stay available. Update your payment method at [billing page]."
- **C. Security (SEV1):** "On [date] we found [what was confirmed]. [Whether your data was involved: yes/no/unknown, and how we know]. We have [contained action]. What you should do: [specific steps]. We will update you by [time]."
- **D. Restore:** "We restored your workspace from the backup of [date]. Anything you changed after that time may need to be redone. Scheduled tasks and connected accounts were paused or disconnected for safety; you can re-enable them in your account."

## 5. Containing a problem (suspend things)

| Goal | How |
|---|---|
| Stop **all** customer activity | Dashboard → turn off **Free access** and **Require payment**; `systemctl disable --now agentai-lifecycle-worker agentai-supervisor-native`; if the host itself is at risk also `systemctl stop agentai-cells-docker` (stops every customer cell) |
| Suspend **one account** | Operator route `POST /internal/accounts/<id>/suspend` (needs an MFA-verified operator and a `suspend` grant); revokes sessions and stops new admissions |
| Cut a **provider/model route** | Revoke the account's LiteLLM virtual key (admin API `/key/delete`; not yet automated: `ProviderKeys.revoke`), or stop the LiteLLM container to stop every customer model call; owner-runtime budget caps are separate |
| Stop **billing effects** | Dashboard → *Require payment* off (new checkouts hidden); `systemctl disable --now agentai-billing-worker.timer` stops applying events (they stay stored) |
| Pause **one tenant's cell** | `stop` lifecycle operation; quarantined restores keep egress dropped |

## 6. Failed-task triage
1. Find the account label in `ops diagnostics` (hashed). 2. Read the task state and the last operation `error` code. 3. `budget_exhausted` → allowance (not a fault). `blocked` → missing capability or an approval wait. `failed` with `runtime_rejected`/`capacity_wait` → check monitor `running_cells`, `unresolved_holds`, memory. 4. Uncertain operation → `Coordinator.reconcile` from the supervisor receipt; never clear a hold by editing rows. 5. Customer content is not visible to you; ask the customer for a scoped, audited consent if you need it.

## 7. Releases and rollback

`python3 release.py --tarball <file> --id <id> [--dry-run]` (in `deploy/`) builds beside the live release, migrates a **copy** of the database, serves the new code on a canary port and probes it, then starts the **previous** release against the migrated copy to learn whether a binary rollback is possible. Only then does it stop the app briefly, take a final backup, migrate, switch and probe; any failure switches back, and restores the pre-migration backup when the old code cannot read the new schema. Exit codes: 0 released, 2 rolled back, 1 refused before touching anything. Drills run the identical code in a throwaway sandbox (`--sandbox DIR`, `--drill-fail-live`).
Migrations must stay additive; a destructive migration needs its own plan.

## 8. Secret rotation (each keeps a working secret at every moment)

| Secret | Procedure |
|---|---|
| Stripe webhook secret | In Stripe roll the secret with an overlap; `add_webhook_secret` (keeps previous + new); after 24 h `drop_old_webhook_secrets` |
| Tenant model key | `rotate_provider_key`: issue → store → revoke old (a failed revoke is queued and retried by `retry_pending_revocations`) |
| App session secret | `rotate_session_secret` then `systemctl restart agentai-platform-app` (every user is signed out) |
| SMTP / bot tokens | Create the new credential at the provider, edit `/etc/agentai-platform/accounts.env` (or the bot config), restart the service, revoke the old one |
| Backup key | New `setup-backup-key.py` on a fresh directory, add the new public key **next to** the old in `age_recipients`, run a backup, pull, then remove the old recipient after keeping the old private key for as long as old sets exist (≤ 30 days) |
| Tenant gateway token | Fixed at cell creation: rotate by deleting the cell (data kept) and recreating it on the same volume with a new token (planned procedure, not automated) |
| SSH | Move to key login, then disable password and root-password login (see findings) |
After any suspected exposure rotate everything the exposed host could read, including provider keys.

## 9. Host exposure checks (monitor `host_exposure`)
Public ports must be exactly 22, 80, 443; the firewall must be active; secret files must be private; SSH password login should be disabled. Loopback-only services are listed in code (`monitor.py`). A new public port is **crit**.

## 10. Cross-customer path review

| Shared path | Control | Evidence |
|---|---|---|
| Account database | Every customer table keyed by `account_id`; scoped store checks; routes return identical 404s for other accounts | `accounts/tests.py` two-account tests, `tests/test_foundation.py` |
| Model proxy (LiteLLM, shared) | Per-account virtual key with its own budget, model allowlist and rate limits; spend ledger per account | `tests/test_secrets_custody.py`, `tests/test_budget.py` |
| Supervisor / worker | Enrolled bindings only, peer-credential check, fenced operations, one active cell | `tests/test_supervisor.py`, `tests/test_worker.py`, live `p4_pipeline_check.py` |
| Cells and worker stages | Separate engine, gVisor, per-tenant volume, network egress policy, no secrets in stages | live `p4_live_check.py`, `p4_broker_check.py` |
| Download and storage URLs | Single-use, expiring, scoped tickets | `accounts/test_files.py` (ticket flow) |
| Event streams | Per-account stream ids, 3 per account, revocation closes them | `accounts/test_streams.py` |
| Caches and logs | `Cache-Control: no-store`; request logs carry only request id and status; rate buckets are hashed | `accounts/middleware.py` |
| Metrics and monitor output | Counts and hashed labels only; sanitizer on all alert text | `tests/test_ops_monitor.py`, `test_ops_diagnostics.py` |
| Backups | Per-tenant encrypted artifacts and manifests; account-scoped restore proven not to change other accounts, the ledger or billing | `tests/test_ops_backup.py`, `test_ops_restore.py` |
| Support tools | Diagnostics only; impersonation and export routes are refused; content needs consented, audited access | `tests/test_ops_diagnostics.py`, `/internal/.../impersonate` |
| Billing | Customer ↔ account mapping only through objects this platform created; payload metadata is never trusted | `tests/test_billing.py` |
| Telegram ingress | One bot, per-account one-time link codes, identity bound by chat id | `accounts/test_telegram.py` |
| Shared Docker engines | Owner engine and cell engine separate; cells never see either socket | Phase 4 evidence |
Open items from this review are listed in `plans/product/phase-14.md`.

## 11. Drills (run in isolated targets; check capacity first, never delete live data)
Scheduled-backup observation (check `last_success_set` advances nightly) · corruption rejection (flip a byte, `fetch` must refuse) · release canary and rollback in a sandbox · cell quarantine restore (`p4_live_check.py`). Measured RPO/RTO and a restore with the real timer firing are Phase 15.


## 12. Customer execution (the live assistant path)

**How a message runs:** the customer sends in the chat page → the app queues it and reserves budget → the lifecycle worker wakes the account's cell if it is stopped (`customer_execution` on) → the request worker claims it → the cell bridge (root, allowlisted methods only) relays it into the cell's own Gateway → the reply is copied into the transcript → real model spend is read from the cell's LiteLLM key and settled in the ledger → the cell sleeps after 15 minutes idle (60 s if another account is waiting for the one cell slot).

| Unit | Runs as | Role |
|---|---|---|
| `agentai-model-proxy` | root | relays 10.77.0.1:4000 (cells) to 127.0.0.1:4000 (LiteLLM). Cells reach nothing else on the host. |
| `agentai-cell-bridge` | root | the only path from the app to a cell; holds the cell tokens; `/run/agentai-cell-bridge/bridge.sock` (app user only) |
| `agentai-request-worker` | app user | runs waiting requests; does nothing while the switch is off |
| `agentai-lifecycle-worker` | app user | creates, starts (wake), stops (idle) and realigns cells |

**Turn it on or off:** dashboard → Feature switches → *Let customer messages run on the live assistant*. Off stops new work immediately (running requests finish or are reconciled); nothing else needs touching.

**Give an account its own assistant (one-time, per account, host side):**
```
ACC=<account id>
cd /opt/agentai-supervisor/current
setpriv --reuid agentai-platform --regid agentai-platform --clear-groups env PYTHONPATH=. python3 -m agentai_platform.lifecycle.provision_cli --account $ACC
PYTHONPATH=. python3 -m agentai_platform.lifecycle.enroll_cli --app-db /var/lib/agentai-platform/platform.sqlite3 --account $ACC --image <pinned image digest>
```
The lifecycle worker then creates the cell (capped volume, gateway token, its own LiteLLM key capped at $25 / 35 days, model route). Trial capacity is two cells. An account without a cell can send, but its request waits.

**Money:** per message the app reserves `AGENTAI_CUSTOMER_RESERVATION_MICROUSD` (default $1); after the run the spend delta of the cell's key is written as a ledger receipt (`litellm-reported-v1`). If provider spend cannot be read the reserved amount is charged (`reservation-upper-bound-v1`). `AGENTAI_SERVICE_ALLOCATION_MICROUSD` (default $50 = 2 accounts x $25) bounds the whole service.

**When something looks wrong**
- *Request stuck "uncertain"*: the request worker reconciles it from the cell transcript; a request that never reached a session is failed with nothing charged; one whose cell cannot be reached for 30 minutes is stopped and charged the reserved amount.
- *Cell recorded running but gone* (engine or host restart): the lifecycle worker issues a stop to make the record true; the next message wakes it.
- *Replies say names cannot be resolved*: DNS inside a cell is written by the supervisor after every start (`CellProvisioner.after_start`); restart the cell to rewrite it.
- *Cell killed under load*: cells are capped at 2 GiB (a 1 GiB cap was OOM-killed in a real turn).
- Two services must **not** gain mount-namespace sandboxing (`ProtectKernelModules`, `ProtectKernelLogs`, `PrivateTmp`, ...): `agentai-supervisor-native` mounts loop volumes that the cell engine has to see.
- The cell engine does not manage iptables (two engines on one host clobbered each other's chains on 2026-10-12). Cell egress is the nft table `agentai_cells` plus the `ufw route`/`ufw allow` rules written by `agentai-cells-routes`.


## 13. Smart routing (JEV, shadow mode)

Dashboard → **Routing**: status, what JEV recommended over 30 days, settings, and *Emergency rollback*. It needs the `jev_routing` switch (data-terms tick) and the key at `/var/lib/agentai-platform/routing/typesafe.key` (owner `agentai-platform`, mode 0600). In this version it **only records**; requests run exactly as before. Each request costs about $0.00003 for the classification. Details and limits: `plans/product/routing.md`. Re-run the classification benchmark with `python3 -m agentai_platform.routing.bench --key-file <key> --out <file>`.


## 14. Web search for customer assistants (2026-10-13)

Every assistant gets web search from the official `@openclaw/brave-plugin` pinned to the runtime version (`SEARCH_PLUGIN_VERSION` in `lifecycle/cell_config.py`), installed by the supervisor after a cell starts (it waits for the Gateway, then marks the cell so it only happens once). The key is a single shared Brave key kept root-only in `/var/lib/agentai-supervisor-secrets/_shared/brave-api-key` (wired through `search_key_file` in `native-wiring.json`) and passed to the cell over stdin, never on a command line. Because it sits inside each cell's own config, a prompt-injected assistant could read it: **use a dedicated customer key with its own cap, and rotate it (it is currently the owner key from `/opt/openclaw-production/integrations/brave/`).** Each cell also gets `workspace/AGENTS.md` (working rules: use `web_search` then `web_fetch`, never invent prices, cite pages, do not scrape search engines), rewritten on every start.

Measured on the real assistant (Haiku): "find and rank the 5 cheapest carbon pickleball paddles" returned a ranked, sourced answer for about $0.12 and roughly one minute; the same request without the plugin (scraping search pages) cost $0.20 and produced no ranking. Brave itself bills per search (about half a cent).


## 15. Browser tasks (2026-10-13)

`agentai-browse.service` (root) runs customer browser jobs: one Chromium stage at a time in the existing sandbox image, using the runner in `/opt/agentai-browse/runner` (reinstall from `openclaw-project/browse`: `runner.mjs`, `package.json`, lockfile, `node_modules`). The app user reaches it only through `/run/agentai-browse/browse.sock`. It keeps no state across restarts: a run interrupted by a restart is marked stopped by the request worker. Turn the feature on or off with the owner switch `browse_tasks` (needs the `browse_ready` fact and the `browse_cost` confirmation); off by default. Each task costs roughly 0.3 to 30 cents of model money on the customer's key (measured 0.28 cents for a one-page lookup). JEV only records what it would have chosen (`--jev-mode shadow`). Stopping the service or switching the feature off never affects chat. Logs: `journalctl -u agentai-browse`.
