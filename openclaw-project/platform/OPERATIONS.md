# Operations runbook (Phase 14)

Single operator: the owner. "Escalation" below therefore means which outside party to contact. Everything here is
for the current single server (`<PROD_IP>`) and the invitation-only beta. Commands run on the server as root
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
The lifecycle worker then creates the cell (capped volume, gateway token, its own LiteLLM key with no budget and no expiry (120 requests and 4,000,000 tokens a minute), model route). Trial capacity is two cells. An account without a cell can send, but its request waits.

**Money:** Lumina applies no spending limit of its own (changed 2026-11-14). A customer may choose limits per task, per day and per billing period in Settings > Usage (`POST /v1/spending-limits`, table `spend_limits`); the owner may store a default for accounts that chose none with `manage.py spend_limits set --task 5 --daily 15 --period 25` (`show`, `clear`). A task's reservation is the customer's task limit, or the no-limit marker (`spend_limits.NO_LIMIT`, never charged or held). After the run the spend delta of the cell's key is written as a ledger receipt (`litellm-reported-v1`). If provider spend cannot be read the receipt records what was last read, else zero (`spend-unreadable-v1`); a reservation is never charged. `AGENTAI_CUSTOMER_RESERVATION_MICROUSD` (default 0) forces a task ceiling on every account if set; `AGENTAI_SERVICE_ALLOCATION_MICROUSD` is no longer a limit. The plan figures in an entitlement (`period_microusd` and so on) are facts about the plan, not limits. With free access on, the provider cost of every account is yours and is unbounded unless a limit is set.

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

Every assistant gets web search from the official `@openclaw/brave-plugin` pinned to the runtime version (`SEARCH_PLUGIN_VERSION` in `lifecycle/cell_config.py`), installed by the supervisor after a cell starts (it waits for the Gateway, then marks the cell so it only happens once). The key is a single shared Brave key kept root-only in `/var/lib/agentai-supervisor-secrets/_shared/brave-api-key` (wired through `search_key_file` in `native-wiring.json`) and passed to the cell over stdin, never on a command line. Because it sits inside each cell's own config, a prompt-injected assistant could read it: **use a dedicated customer key with its own cap, and rotate it (it is currently the owner key from `/opt/openclaw-production/integrations/brave/`).** To rotate: write the new key to `_shared/brave-api-key`; every assistant picks it up the next time its cell starts (the marker `workspace/.search-<version>` records a salted hash of the key it holds, so a different key is set again without reinstalling the plugin). `bin/phase6/rotate-brave-key.py` changes only the owner's own connector key, not this one. Each cell also gets `workspace/AGENTS.md` (working rules: use `web_search` then `web_fetch`, never invent prices, cite pages, do not scrape search engines), rewritten on every start.

Measured on the real assistant (Haiku): "find and rank the 5 cheapest carbon pickleball paddles" returned a ranked, sourced answer for about $0.12 and roughly one minute; the same request without the plugin (scraping search pages) cost $0.20 and produced no ranking. Brave itself bills per search (about half a cent).


## 15. Browser tasks (2026-10-13)

`agentai-browse.service` (root) runs customer browser jobs: one Chromium stage at a time in the existing sandbox image (two processors, 2 GiB), using the dependencies in `/opt/agentai-browse/runner` (`package.json`, lockfile, `node_modules`: installed by hand from `openclaw-project/browse` when they change) and the release's own runner, `agentai_platform/browse/hosted_runner.mjs`, mounted over the installed `runner.mjs` (since 2026-11-22; before that the runner was copied by hand and could fall a release behind). The app user reaches it only through `/run/agentai-browse/browse.sock`. It keeps no state across restarts: a run interrupted by a restart is marked stopped by the request worker. Turn the feature on or off with the owner switch `browse_tasks` (needs the `browse_ready` fact and the `browse_cost` confirmation); off by default. Each task costs roughly 0.3 to 30 cents of model money on the customer's key (measured 0.28 cents for a one-page lookup). JEV only records what it would have chosen (`--jev-mode shadow`). Stopping the service or switching the feature off never affects chat. Logs: `journalctl -u agentai-browse`. **Reading a run:** every browser task writes `/var/lib/agentai-browse/jobs/<request id>/trace.jsonl` (root-only, deleted with the screenshots after 24 hours). It records, with timings, each page read, each JEV call (outcome, the probability of each question, why an answer was refused and what JEV actually said), who decided the step and why (`route`), every Haiku or Sonnet call, every runner command and its error, the safety rules that stopped the run, loop signals, what the person did during a take-over (kind of input only) and the end. Since the JEV rework it also records, per step, `mode` (controls or picture, and why: no controls listed, most of the window covered, or a refused click), `probe` (what was under a point chosen from a picture: tag, text field or not, secret or not, never its label) and `claude_page` (Claude took, or gave back, a page, and the rule that did it). JEV has no confidence cut-off: a valid answer is acted on, and Claude takes a page over by rules (the same step twice with nothing happening, a step JEV could not carry out, three JEV steps that changed nothing, six scrolls in a row). A picture step sends TypeSafe a screenshot of the customer's page, taken only after the payment, sign-in and human-check rules have passed. It holds no page text, no typed text, no request text and no query strings. Print it with `python3 -m agentai_platform.browse.trace <request id>` (add `--problems` for only what went wrong); the journal gets one line per finished run with the path, and one for every crash. `agentai-browse` runs `python3 -m agentai_platform.browse.trace` from the release folder: `cd /opt/agentai-supervisor/current && python3 -m agentai_platform.browse.trace <id>`.

**Waiting for the customer (sign-in, password, human check).** These stops no longer end the run. The job stays alive in the `paused` state with `needs_you` set to what is needed; the customer works in the Live view (`control`) and the run goes on when they press "I'm done, continue" (`resume`), or by itself once the page has stopped being a sign-in or human-check page on two looks in a row (`HAND_POLL_SECONDS`). The wait has the usual idle limit (`takeover_seconds`); when it runs out, or after `MAX_HANDOFFS` waits in one run, the run ends as a `handoff` exactly as before. Payment pages and consequential buttons still end the run. Trace events: `handoff_wait`, `handoff_done` (outcome resumed / auto / timeout / cancelled). Nothing typed is read; only whether the page is still that kind of page.

**A button that changes something (2026-11-21).** A button that removes, sends, submits or confirms still ends the run in a hand-off. Two things are new. JEV's pick of such a button no longer ends the run by itself: the assistant, which knows the task, is asked first (`second_opinion` in the trace). And with the owner switch `browser_press_approval` **on** (it is off unless the owner turns it on, and fails closed), a button the assistant chooses too is put to the customer on the Live page ("Lumina wants to press "Remove" on shop.example. Allow it?"): with a yes that one button is pressed and the run goes on; a no, no answer within the usual wait, or a fourth question in one run is the hand-off. Buttons that pay, buy, order, book, subscribe, donate or transfer (`candidates.PAYMENT`) and anything on a payment page are never asked about and never pressed, with the switch on or off. Trace events: `approval_asked`; stats `approval_asked`, `approval_given`.

## 16. Activity window

The request worker turns the assistant's tool use (search, page reads, commands, file names) into `activity` task events (`agentai_platform/activity.py`): fixed categories, short redacted detail, command output trimmed to 1.2 KB, never file contents; only calls made during this request are shown. Lumina's Activity panel (Ctrl+J or the Activity button in a chat) polls `/v1/tasks/{id}/events` and embeds the live browser screenshot when the task is a browser task. No new switch: it needs no paid feature. The `activity` event is best-effort and never fails a task.

## 17. Files the assistant makes

**Any format.** A file reaches the customer in one of two ways:

1. **The assistant delivers it** with the `lumina_file_deliver` tool (`agentai_platform/file_tools.py`, served by the tool relay). It names a file in its workspace and, optionally, a format to convert to (pdf, docx, xlsx, pptx, png, zip and more). The relay reads the bytes from the account's own workspace through the cell bridge (`workspace.stat`, `workspace.read`: root, read-only, O_NOFOLLOW from directory descriptors, 2 MiB slices), converts them in the render service when asked (`deploy/RENDERER.md`), and saves the result. The assistant gets a picture of the first page back to check its work.
2. **Otherwise the request worker sweeps the workspace** after the task (`workspace.scan`): every file written since the task started, in any format. When the assistant delivered something itself during the task, nothing is swept: its notes and sources stay where they are.

Limits for both: 50 MB a file, 50 files and 200 MB a task, 2 GiB an account (uploads and generated files together). Never delivered: native programs and installers (by ending and by first bytes), hidden files, the runtime's own files (`AGENTS.md` and friends), work leftovers (`.log`, `.tmp`, `.pyc`) and anything under `tmp/`, `scratch/`, `node_modules`, `dist`, `build`. A file that was left out is named in the task's timeline with the reason (`artifact_skipped`).

Each file is an immutable artifact version in the customer's project (same name = new version, unchanged = nothing); folders in the name are kept (`reports/Q3 sales.xlsx`). Customers see them as cards under the answer and on the Files page (`GET /v1/files`, one query), preview them (`/v1/artifacts/<id>/versions/<n>/preview`: the picture itself, the first lines of text, or a first-page picture; always an image or plain text, sandboxed), download with single-use tickets (streamed from disk, always as an attachment), and **delete** them (`POST /v1/artifacts/<id>/delete`: every version, the bytes, the preview picture and unused tickets; no trash). "Download all" makes one ZIP for the account and replaces the previous one.

**Download as.** An answer, a whole chat or a table can be downloaded as PDF, Word, Markdown, text, Excel or CSV (`POST /v1/conversations/<id>/export`, `POST /v1/export/table`). These are made on the spot and sent back; nothing is stored.

Storage: `AGENTAI_STORAGE_DIR=/var/lib/agentai-platform/storage` and `AGENTAI_ARTIFACT_SIGNING_KEY` in `/etc/agentai-platform/accounts.env`; the directory is in the nightly encrypted backup set as `customer-files` (a deleted file therefore stays in earlier backups until they expire). Conversions need `AGENTAI_RENDER_SOCKET`; without it files are delivered as written. Uploads from customers stay off (`AGENTAI_UPLOADS_ENABLED`, needs the scan capability). Capture failure never fails a task. Claude Code (ACP) stays unactivated for customers: it would spend outside the metering proxy; the assistant's own write/exec tools are metered and are what coding uses.

## 17a. How the assistant is instructed

One home per instruction (`agentai_platform/agent_rules.py` explains the split):

| Layer | What it holds | Where | When the model reads it |
|---|---|---|---|
| Core rules | Who Lumina is, who the customer is, what good work looks like, memory, and the four limits that never change. About 1,000 tokens. | `AGENTS.md` in the cell workspace | Every session |
| Skills | How to do one kind of work: `lumina-browsing`, `lumina-files`, `lumina-apps`, `lumina-show`, `lumina-integrations` | `skills/<name>/SKILL.md` in the cell workspace | On demand: the runtime lists the one-line descriptions and the assistant reads a skill when the work calls for it |
| Tool descriptions | Each tool's contract: what it does, parameters, limits, what it returns | With each tool (`tool_relay.py`, `file_tools.py`, `show_tool.py`, `mcp_connections/relay.py`, ...) | When the tool is loaded |
| The message | Facts about this one request: its task id, the mode the customer chose, what they asked Lumina to remember | `chat_driver.py` `_outgoing` | Each message, in a block marked as Lumina's, above the customer's own words |

`write_rules` writes the core rules and skills at every cell start (unchanged skill files are left alone). A running session keeps the skill list it started with; a new chat picks up changes. `skills/` and `lumina-ui/` are never swept up as customer files.

**Showing visuals.** The assistant calls `lumina_show` (`show_tool.py`) with blocks and datasets. They are checked against the component registry before anything is shown; a wrong block comes back as a tool error naming the block and the reason. A valid one is stored as a `document` block, appears at the end of the chat at once, and is attached to the reply when the task ends. The customer's answer style decides what is allowed: plain answers (or Text mode, or a surface outside the app) allow nothing; the middle style allows no buttons or follow-ups. The older fenced `lumina-doc` reply is still read, so stored answers and updates to an existing interactive answer keep working. The skill teaches 21 core components; the rest of the registry stays available through `lumina-ui/components/<type>.json`.

**Output room.** One reply may be up to 32,000 tokens on Sonnet and 16,000 on Haiku (`SONNET_MAX_OUTPUT`, `HAIKU_MAX_OUTPUT` in `lifecycle/cell_config.py`): a document or app is written in one tool call, and the old 8,192 ceiling cut long files off.

**Not verified from this repository.** Whether the model proxy on the server runs Sonnet 5.5 with thinking on and at what effort (the model entries say `reasoning: false`, but that model thinks by default when the setting is left out). Check one real request in the proxy's usage log before tuning cost.

## 18. Sign-ups and customer approval

Public sign-up is behind the owner switch `open_signups` (off by default). Owner actions live in the dashboard **Customers** page, which calls `manage.py signup_admin` as the app user: approve (activates, seeds allowance, queues the assistant create via `host_create`, emails), decline, suspend (ends sessions), resume, and the customer limit (`/var/lib/agentai-platform/signup-settings.json`, default 2, max 200). Unconfirmed sign-ups are removed after 24 h. Check after any change: `deploy/signup_live_check.py`. Rollback of the switch: turn `open_signups` off. Server files added: dashboard `app.py`/`switches.py` (backups `*.bak-signup`).

## Saved logins and cards (the vault)

Customers can keep a login or a card (Settings, Saved info). Each item is sealed with AES-256-GCM, a key per account derived from one master key, a random nonce per item, and the owner/kind/id bound in, so a copied or swapped row will not open. The card security code is refused, never dropped silently. A saved item is opened only when a running task reaches that site's sign-in page (or a payment page) and the customer says yes to that one use; the secret then goes from the web app over the private browse socket straight into the page's fields. It is not given to any model or JEV, and it is not written to the trace, the steps or a picture (the run stops at the payment step afterwards, and the customer enters the code and places the order).

- Key: one line `kid:base64url(32 bytes)` in a root-only (0600) file, named by `AGENTAI_VAULT_KEY_FILE` in `accounts.env`. Make one with `python -c "from agentai_platform.vault import Keyring; print(Keyring.generate())"`. Without the file the vault is off (Settings says so; nothing is saved or opened).
- Keep a copy of the key file somewhere other than the server and its backups: without it saved items cannot be opened (customers would add them again). Rotating: put a new `kid` line first; older lines still open old items.
- Backups hold only the sealed rows. `vault_items` is never restored from a backup, so an item a customer deleted cannot come back.
- Install `cryptography` with the rest of `requirements.lock` (`pip install --require-hashes --no-deps -r requirements.lock`); the lock lists hashes for CPython 3.12-3.14 on Linux x86_64 and aarch64.

## Generative UI files and migration

The registry protocol is `lumina-doc`; automatic page/image fetching and its `AGENTAI_CARD_IMAGES` / `AGENTAI_BRAVE_IMAGE_KEY_FILE` switches have been retired. Existing `card_images` rows remain account-scoped and readable through `/v1/media/{id}`. Do not delete historical conversations or artifacts.

New images, media and downloads resolve only references present in a stored document, inside its conversation project. The asset endpoint rechecks ownership, MIME type and size; project uploads use the existing scanned-files pipeline and generated files use single-use artifact tickets internally. Documents never auto-fetch arbitrary external URLs. See `docs/generative-ui/protocol.md` for artifact events, versions and state recovery.

## Native execution: running it, watching it, rolling it back

OpenClaw owns each customer run; Lumina admits it, supervises it and settles it (`docs/architecture/native-execution.md`).

- **Units.** `agentai-request-worker` (supervises runs, parks requests that wait for a person, admits the next turn of a goal), `agentai-tool-relay` (app user; serves the
  `lumina_browser` tool to cells on the cells bridge address, port from `AGENTAI_TOOL_RELAY_PORT`, default 4100) and `agentai-browse` (unchanged). `agentai-tool-relay` is in the
  monitor's required units and on the owner dashboard. Install the unit, set `tool_relay_port` in `native-wiring.json` (it opens the one firewall rule and makes new cell configs carry the
  tool), run `cells-docker/agentai-cells-routes.sh` for the ufw rule, then restart `agentai-lifecycle-worker`. **Existing cells pick the tool and the deny list up at their next start**
  (`CellProvisioner.before_start` rewrites their config); until then they simply have no browser tool.
- **Switches.** `browse_tasks` turns the browser tool (and Browse mode) on and off; turning it off also stops running browser jobs. `pursuit` and `jev_services` no longer exist; a
  stored `true` for either is ignored.
- **A request that looks stuck.** `customer_requests`: `parked_reason` set = waiting for a person (no slot held); `closing=1` = no more steering; `continue_goal=1` = the next goal turn is
  about to be admitted. `chat_deliveries` lists every input handed to the runtime (kind, key = native run id, state, deadline). `outcome`/`outcome_note`/`verification` are the verdict.
  A delivery key like `<request>-a1.r<epoch>` means the cell restarted and the input was handed over again under a fresh key (the interrupted original never runs).
- **Cell restarts.** Supervision waits up to `OUTAGE_LIMIT` (90 s) for an unreachable cell, then leaves the request `uncertain`; the worker recovers it from the stored deliveries and
  presents the inputs again. A request unreachable for 30 minutes is abandoned at its reserved cost.
- **Rollback.** There is no hidden fallback to the old loop. To stop customer execution use the `customer_execution` switch; to take the browser away use `browse_tasks`. Migration
  `0028` is additive except that it drops `pursuit_state` (advisory plan state nothing else read) and rebuilds `chat_deliveries` with the same rows.
- **Known limits.** The runtime's `ask_user` does not work with the bridge's connection model (a question to the customer is an ordinary reply); with the host stage one browser job
  runs at a time on the host (with the native browser, one per account).

### Safety menu: who gets it, two scopes (2026-10-27)

The owner's menu of safety switches (sidebar item "Safety"). Code: `agentai_platform/safety.py` (rules), `accounts/safety.py` (routes), `lumina/src/components/safety/` (UI; its README explains the seams).

- **Who.** The account named in `AGENTAI_SAFETY_OWNER_ACCOUNT` (`/etc/agentai-platform/accounts.env`) and any account the owner grants from the menu ("All users" tab, "Who can open this menu"; table `safety_access`). Everyone else, signed in or not, gets the 404 of a route that does not exist. With no owner set, nobody gets it, whatever was granted.
- **Two scopes.** "My account" (rows in `safety_overrides` under the account id) and "All users" (rows under `*`, owner only). For one account the more specific setting wins: its own row, else the all-users row, else on; an expired "off" counts as no row. A granted account sees only "My account". Every change needs the signed-in password; all-users changes and grants have their own audit actions (`safety.change_all`, `safety.access_grant`, `safety.access_revoke`).
- **What cannot be switched.** `shared` (server-wide: systemd, Caddy, Docker isolation, provider caps, CSRF, operator two-step, login limits) and `core` (tenant isolation, vault encryption, audit log) are shown and never changed here; the `privacy` ones (personal-data scrub, saved-login notice, secret redaction, SSRF guard) can be switched off for your own account but never for everyone. The routes refuse these with `400 locked`.
- **What each switch does, and where it is read.** A switch marked `wired` is asked for by code (a test fails if one says wired and nothing reads it); the rest say "not enforced yet" in the menu.
  - *App layer* (asks `safety.is_on(con, account, key)`): `budget_caps` and `queue_limit` (`budget.py`, `request_queue.py`), `rate_limits` (`accounts/services.py`), `project_chat_limits` (`chat.py`), `upload_limits` (size and count only; the file-type and content checks always apply: `files.py`, `accounts/files.py`), `secret_redaction` (stored event records only: `events.py`; the Activity window's tool-call summaries are always redacted), `vault_notice` (`accounts/vault.py`; a card security code is never stored whatever it says).
  - *Browse service* (a `switch(key)` on the loop's `Policy`, read at every step): `payment_stop`, `sensitive_approval`, `denied_sites` (banking sites, human checks and sign-in pages), `untrusted_page_text`, `personal_data_scrub` (what goes to JEV only; stored traces always scrub), `screenshot_retention` (the 24-hour purge keeps an account's pictures while it is off; each job folder carries an `account` marker). `ssrf_guard` is read when a native job starts (the cell's network firewall always applies).
  - *Tool adapter* (`browse/adapter.py`): `assistant_output_cleaning` (the task, steps, search terms and choices the assistant sends to the browser) and `untrusted_page_text` (web text it reads).
  - *Cell config*, applied the next time a cell starts: `tool_ceilings` (the assistant may use the browser tool itself, outside Lumina's browser rules) and `ssrf_guard` (the cell's browser may reach private addresses; never inherited, set from the switch at every start).
  - *Nothing to read*: `routing_policy`, `confirmations`, `web_limits` describe protections that are not in the live code; they say so.
  - *Moved out of the switchable list*: `message_length_limit` (the database enforces it too) and `cell_limits` (they protect the whole host) are `shared`; `session_epochs` (sign-out-everywhere) and `block_validation` (the code builds on the checked result) are `core`.
- **How other processes read the switches.** The app writes every setting to `safety-switches.json` in its state directory (`AGENTAI_SAFETY_SNAPSHOT`, default `<state dir>/safety-switches.json`, mode 0640) after each change, on the owner's first visit, and after each grant or revoke; a failed write answers `503` so the owner knows the other processes have not heard. The browse service reads it (`--safety-file`, default `/var/lib/agentai-platform/safety-switches.json`) and the supervisor reads it through `"safety_file"` in `native-wiring.json` (add the same path). Nothing but the app ever opens the app's database for this: a root process opening a WAL database the app owns could leave a root-owned `-shm` file the app cannot open. A missing or unreadable file means every switch is on. Off-switches that expire lapse by themselves (the reader judges the stored time).
- **Revoking** an account's access also deletes the switches it had set, so nobody is left unprotected without the menu. A restore never changes either table (`LIVE` in `ops/restore.py`).
- **Release note.** This needs Django migrations `0014_safety_overrides` and `0015_safety_access`. A release copied into `releases/<name>` without running them leaves the app refusing the schema; use `deploy/release.py` (it migrates a copy first) or run `manage.py migrate` as part of the release.

### Browser engine: the cell's own browser (2026-10-26)

A browse job's hands are either the host's Docker stage (`runner`, as before) or the customer's own cell browser (`native`: OpenClaw's browser plugin driven by `browse/native_runner.py` through
the cell bridge). The brain is the same either way: code rules, then JEV, then the assistant (`lumina_browser_step`). The engine is chosen when a job starts and recorded on it (`engine` in its
trace); a job never switches engine, and a native job that fails fails visibly (there is no silent fallback to the stage).

Turning it on, in this order (nothing changes for a customer until the last step):
1. Cells need Chromium: the cell image must be the browser build of the pinned runtime (`OPENCLAW_INSTALL_BROWSER=1`), with memory for Chromium (measure before enabling more than a canary account).
2. Release the supervisor tree and the platform tree (`bin/deploy-*`, `release.py`), restart `agentai-cell-bridge`, `agentai-browse`, `agentai-tool-relay`, `agentai-request-worker`, the app.
   The bridge now lets root (the browse service) use `browser.*` over its own admin-scoped connection; the app user still cannot.
3. In `native-wiring.json` set `"native_browser": true`. Each cell takes the browser config at its next start (headless, no sandbox, the default address policy that blocks private and
   internal addresses, evaluate on; the assistant's own `browser` tool stays denied).
4. Create `/etc/agentai-supervisor/browse-engine.json` (example: `platform/deploy/browse-engine.example.json`): `{"default": "runner", "native": ["<account id>"]}`. It is read at every job start:
   add the canary account, run a browse task from it, check the job trace for `engine: native`, the Live view, a hand-off (payment page) and Stop; widen the list; set `"default": "native"` last.
- **Rollback.** Remove the account from the file (new jobs use the stage at once; a running job finishes where it started). `"native_browser": false` takes the browser out of cells at their next start.
- **What persists.** The cell's browser profile keeps the customer's own cookies between jobs (their sign-ins), on their own cell volume; a job closes the browser when it ends so a sleeping cell holds
  no process. A cell with a live browser job, or whose customer still has the wheel in a hand-off window, is not put to sleep.
- **Found on the first real cell (27 Oct 2026).** The browser plugin's start writes `<state>/credentials/browser-extension-relay.secret` with an atomic rename-without-replace, which the gVisor cell rejects (EINVAL); the whole start then fails as `UNAVAILABLE: SuppressedError: An error was suppressed during disposal` with no other detail. If the file already exists (a regular file the cell user owns, mode 0600, 64 hex characters) the plugin only reads it, so the host writes it before every start (`CellProvisioner.ensure_browser_relay_secret`, only when `native_browser` is on). The image's Chromium (Playwright `chromium-1243`) is pinned with `browser.executablePath`. To see a failure like this again: run the plugin's own start in a throwaway Node process in the cell (`/app/dist/control-service-*.mjs`) and print the nested `error` / `suppressed` / `cause`; the gateway log keeps only the wrapper. Measured: the cell uses about 1.0 GiB of its 2 GiB at idle; Chromium started and stopped cleanly.
- **Still to measure with real models and the real cell image** (not possible from a developer machine): JEV's accuracy on the cell browser's page descriptions, the assistant's cost and step count when it
  drives a page, Chromium memory per cell and under several cells, Live view frame rate in a gVisor cell. Until those are measured the host stage stays the default engine.


### Browser OOM and cancellation recovery

An embedded Chromium instance shares the assistant container's 2 GiB cap. On 2026-10-27 a real browser launch exhausted that cap and Docker confirmed `OOMKilled=true`; the browser timed out and the native websocket became unreachable. The affected account was moved from the `native` override in `/etc/agentai-supervisor/browse-engine.json` to the existing `runner` default. That separate hardened browser stage has its own 1.5 GiB limit within the existing host-capacity reservation. The override file is read for each new job; no customer shopping action is replayed. Keep embedded-browser rollout separate from ordinary deployment until its combined memory envelope is validated.

`NativeGateway.cell_running()` reads the host's `cell.status`, independently of the assistant websocket. If it confirms the container has stopped, request reconciliation closes cancelled work as cancelled (or unexpected exits as failed), reconciles usage, and frees the execution slot. An unreachable/invalid probe never proves termination. An external browser must also confirm a terminal state before that slot is released. Do not repair this condition by merely rewriting a request to completed or dropping its reservation.


## 18a. Several customers at once (roadmap #8)

Several customers' assistants run at the same moment. How many is decided by the host, not by a constant: `host_capacity()` (`agentai_platform/lifecycle/profiles.py`) reads live free memory, CPU count, disk and process
limits and charges each running cell its enforced caps (memory 2 GiB, one CPU), with one browser stage (1.5 GiB, 1.5 CPU) reserved for the whole host. A cell is charged `1 CPU / cpu_oversubscribe` of CPU
reservation (default 2: an assistant mostly waits for the model provider; its cgroup cap of one CPU is unchanged). A bigger server therefore admits more cells with no code change.
On the 4-CPU / 16 GiB server that is about three; 8 CPU / 32 GiB about 8; 16 CPU / 32 GiB about 13 (memory first).

* **Who waits.** A request runs when its own account has a cell up and nothing running (one task per account at a time). Otherwise it waits in line, never failed. Across accounts the order is fair
  (the account served longest ago goes first). When the host is full, the cell idle longest is released after a short idle (`handover_idle`, 60 s) to make room, and the waiting customer sees "Every assistant is busy".
* **Owner settings** (`/var/lib/agentai-platform/signup-settings.json`, read fresh each time, no restart): `max_running_cells` (1 to 200; absent = by capacity) lowers the ceiling, `cpu_oversubscribe` (1 to 4, default 2).
  `max_accounts` is a different number: how many customers may have an assistant at all. To go back to one customer at a time: set `max_running_cells` to 1.
* **Look.** `manage.py lifecycle_status` prints the cell slots by state and the number of running requests; `agentai_platform.lifecycle.profiles.host_capacity_for(store)()` shows the live answer.
* **Worker threads.** `agentai-request-worker` runs one thread per running request (`AGENTAI_REQUEST_PARALLEL`, default 8); the cells themselves are limited by the capacity above, not by this.
* **Rollback.** Migration 0040 keeps the old slot tables for one release, but an older release does not know the new ones: before rolling the app back, set `max_running_cells` to 1 and let the extra cells go idle
  (or stop them), so the older code never sees two cells running at once.
* **Long replies.** A reply the model cut off at its output limit is continued automatically in the same task, at most three times (`chat_driver.CUTOFF_CONTINUES`); the customer's timeline says so.

## 18b. Plans that run in parallel, change while running, and schedules (roadmap #10, #11, #78)

* **Parallel phases.** A plan whose phases declare `dependsOn` runs every phase whose prerequisites are done: the first in the plan's own chat, the others in **lanes** (hidden child conversations,
  `conversations.parent_id`, each with its own runtime session), at most three phases at once. A lane takes one of the account's **background slots** (`request_slots.kind='background'`, two per account:
  `request_queue.BACKGROUND_PER_ACCOUNT`); the customer's own task keeps its interactive slot. A plan with no dependencies runs one phase at a time, as before. Lanes are never listed as chats and their
  tasks show under the plan's chat. A failed phase stops new phases from starting; running phases go on.
* **Exact accounting.** The cell's model key has one running total. Every request records it when it starts and ends (`spend_marks`); when requests overlap each stretch of spend is shared equally between
  the ones running in it (`spend_share.py`), so every cent is charged once. A request that ran alone is charged exactly its end minus its start, as before.
* **Revising a running plan.** A failed phase, a changed result or the customer's own wish leads to a *proposal*: the assistant returns the whole revised plan, it is checked (phases that are running or finished
  never change; a failed one may only be switched off and replaced), stored as a difference in `plan_proposals`, and shown in the plan. The customer applies it, or has chosen automatic revision for that plan
  (`plan_settings`, at most twice, `genui/replan.MAX_AUTO_REPLANS`). Routes: `/v1/blocks/<id>/replan`, `/proposal`, `/auto-replan`.
* **Schedules and watchers.** `schedule_engine.py` starts scheduled runs once enforcement is proven (`schedules.ENFORCEMENT_PROVEN`, backed by `tests/test_schedule_engine.py`): one run per schedule per local day
  (`schedule_runs`), a missed run follows the schedule's policy (`run_once` or `skip` within a grace window, never back-filled), the customer's grant expires, a watcher-gated schedule runs only when the watcher saw
  a change, the run carries the schedule's own time and spending limit and never waits for a person. Nothing runs for customers until the owner switch `customer_schedules` is on (it is off).
* **Rate limits.** One `RouteLimiter` per (account, route) in the model relay remembers what the provider said (Retry-After, remaining/reset headers) and makes concurrent calls wait once, together, for at most
  90 s per call; the same waiting applies to a customer's own model key (and is said to be their provider's limit). The time spent waiting is added to the run's own time limit. Connectors will use the same class.
* **Push.** The task-state stream is on (`agentai-push`, Caddy `@push`, `AGENTAI_PUSH_PATH=/v1/push`). `/etc/agentai-platform` is `root:agentai-platform` mode 0710 so the push service (running as `agentai-platform`)
  can open the one secret it needs (`live.secret`, mode 0640); every other file in it stays root-only. To turn it off: remove `AGENTAI_PUSH_PATH` from `accounts.env` and restart the app (tabs poll again).
* **The supervisor's ceilings** (`/etc/agentai-supervisor/enrollment-policy.json`, root, 0600): `max_cells` (cells that may exist: 2 to 39) and `max_running` (cells that may run at once; the host's own hard backstop under
  the app's live capacity). Both were 2/1 and are 4/4 on this host; raise them when the server grows, then `systemctl restart agentai-supervisor-native`.

## 18c. Things learned running the Phase 1 proof (read before touching cells by hand)

* **A deploy restarts the supervisor too (since #71, 2026-11-20)**, only while no cell operation is in flight (the deploy log says when it skipped it). Running cells survive it. The supervisor sets up every cell it starts (tool hook, configuration, rules), so a change to that code reaches a cell at its next start; a running cell whose tool hook is older than the release is restarted at its next quiet moment (#70). A cell stop never runs while a request of that account waits or runs, and no request starts while a stop runs (#72).
* **Stopping the supervisor stops the lifecycle worker.** `agentai-lifecycle-worker` has `Requires=agentai-supervisor-native`. `systemctl restart agentai-supervisor-native` brings both back; a plain `stop` then `start` of
  the supervisor does NOT restart the worker, and nothing wakes a customer's cell until it is started again (`systemctl start agentai-lifecycle-worker`).
* **A cell is removed through the runtime's own registry, or the next creation fails.** The runtime keeps its own list of cells (`openclaw fleet list --json`, run in `/var/lib/agentai-fleet` with the supervisor's `HOME`
  and `DOCKER_HOST`). Removing a container, volume and custody row by hand leaves a registry entry that still owns its port, and the next `create` comes back `runtime_rejected`. `fleet rm <tenant>` (no `--purge-data` unless
  the data is meant to go) is the supported removal; then its Docker network (`openclaw-cell-<tenant>-net`), `auth-profile-secrets/<tenant>` and the supervisor's custody record. `deploy/phase1_root.sh` does all of it for a
  disposable test account and refuses anything that is not a `p1b*` account.
* **A cell that is left running is invisible to the app but counts against the host.** The supervisor's running ceiling (`max_running` in `enrollment-policy.json`) counts what the host runs, not what the app database
  remembers. After any manual test, compare `docker --host unix:///run/agentai-cells/docker.sock ps` with `manage.py lifecycle_status`.
* **Memory per cell.** Idle about 0.5 GiB; under a heavy task 1.3 to 1.6 GiB (the runtime itself warns at 1.0 and 1.5 GiB). The capacity model charges the 2 GiB cap per cell.
* **A test account's chat limit.** The owner's own account is near the per-project chat limit; anything that makes chats (the live proof) archives them afterwards.

## 18d. Permissions, connected services, changes and leaving (roadmap Phase 2 and 3, built 2026-11-15, not deployed)

Everything below is off until its owner switch is on; `deploy/PENDING_DEPLOY.md` has the steps for the day it is deployed.

- **Who may do what.** One table (`agentai_platform/permissions.py`) and one function (`security.allowed`). Every route names an action (`accounts/route_actions.py`); the
  account middleware refuses a role that lacks it with 403 `not_permitted`. Every customer is an organization of one whose owner they are, so nothing changes for them.
  A new route with no row fails `accounts/test_phase23.py`; a new relay tool with no row fails `tests/test_permissions.py`.
- **A person's role.** `organization_members`. Changing it (`POST /v1/organization/members/<actor>/role`) ends that person's sessions. There is no invitation screen yet;
  to put an existing customer into an organization use `OrganizationService.add_member` from a shell.
- **What an organization decides** (`organization_policies`, `POST /v1/organization/policy`): tools allowed, services allowed, kinds of change (allowed, an admin as well,
  blocked), spending limits for members, own model keys. A member sees these as "set by your organization".
- **Connected services.** `platform/CONNECTORS.md`. Tokens are sealed in `connector_secrets` with the key in `AGENTAI_CONNECTOR_KEY_FILE` (back it up; without it the
  tokens cannot be opened). `manage.py connector_refresh` (timer) renews tokens and purges those of removed connections; its log lines are a connection id and an outcome.
  A connection that shows "needs you" must be reconnected by its customer. Removing one is always possible and answers with a receipt (`connector_revocations`).
- **A change in a connected service** is a row in `actions`. To see what is waiting: `SELECT id,kind,state,ended_reason FROM actions WHERE state IN ('proposed','approved','executing','uncertain')`.
  `uncertain` means the answer to a write never came: the request worker reads it back on its next pass and never sends it again blindly. One that stays `uncertain` has a
  connection that can no longer be asked (see `ended_reason`); look at the provider by hand before telling the customer.
- **How long things are kept.** One table, `agentai_platform/retention.py`. `manage.py retention_sweep --dry-run` prints it; without `--dry-run` it deletes what is older
  than its row allows (timer `agentai-retention`, daily). A new table without a row fails `tests/test_data_lifecycle.py` and the privacy test.
- **Exports, deletions, closing an account** are rows in `account_jobs`, moved by `manage.py account_jobs` (timer, every minute). Each has its checkpoints in `steps_json`
  and carries on from the last one. `manage.py offboard_account --account <id> --status` shows where one stands; `--account <id> [--export] [--cooling-off-days N]` starts
  one for a customer who asked by email. A job `waiting` for `cell` or `memory` is retried every pass; one that ends `failed` has a verification scan that found something:
  read `report_json` (`verification.found` says where) and fix that store before running it again.
- **The live proof** for both phases: `deploy/phase23_live.py` (needs the switches `synthetic_connector` and `connector_writes` on, and the key file).

## 19. Experimental "ultrafast" decider (owner testing only, 2026-10-30)

Safety switch `standard_browser` (Safety console, Browser group). ON for everyone by default. Turn it OFF for **your own account** (choose a time limit: it comes back by itself) and your next browser task is decided the jev-ultrafast way instead of the standard way. **Both run on the same sandboxed browser stage and the same loop** (`browse/loop.py`), so every stop and limit applies to both: payment and sign-in stops, human checks, the denied-sites list, address checks, a clean profile each task, step and time limits, budget, Stop and hand-over. The switch only chooses who decides each step (`browse/service_main.py`, `jev_for`). It is read when a task starts. Nobody else can use it: the account id in `/etc/agentai-supervisor/ultrafast-owner` (copied from `AGENTAI_SAFETY_OWNER_ACCOUNT`) must match, and the switch cannot be changed for all users.

**What differs from the standard decider** (`browse/ultrafast_brain.py`, `UltrafastChooser`): it asks TypeSafe for the `jev-latest` alias (on 2026-10-30 that answers as `jev-1.14.0`, the model the standard chooser pins; any answer not naming a `jev-*` model is refused and the one that answered is recorded), and when the field to type into needs text the request does not give, a small fast model (OpenRouter, jev-ultrafast's own prompt) writes it instead of handing the step to the assistant. If that writer fails or refuses, that one step goes to the assistant exactly as before. The writer sees only the current request (never saved chat history), the field name and the page title and first 1,500 characters, all scrubbed, and is never asked about a password or a sensitive control. Stats count its steps as `helper_text`. `done` is still confirmed by the assistant, which writes the answer.

**Not the vendored agent:** jev-ultrafast's own loop drives a Chrome over the DevTools protocol, which the sandboxed stage does not expose, so its loop is not used. A first version that ran it beside a separate shared Chrome was built and then retired: it needed its own Chrome, users and firewall, shared one browser profile, had none of the stops above, and failed in the real service. It is in git history (commits 2aa3396, 2b37c2e).

**Install / undo:** `python3 openclaw-project/bin/update-ultrafast.py` (plan), `--apply`, `--rollback`. Releases are timestamped folders under `/opt/agentai-supervisor/releases` and `/opt/agentai-platform/releases`; `/etc/agentai-supervisor/ultrafast-rollback` records the previous two. Key: `/var/lib/agentai-supervisor-secrets/_shared/openrouter-key` (root, 0600), copied from `.env` without printing it. Cost: the text writer's spend is billed by OpenRouter and not counted in the task's budget (a few hundredths of a cent per typed field).
