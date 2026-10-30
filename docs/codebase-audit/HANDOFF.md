# HANDOFF: Lumina cleanup, fix and hardening (for the next AI)

Written 2026-10-29 at the end of a full audit. This is the ONLY handoff file; all earlier handoff/continuation prompts were removed. It is self-contained: read it top to bottom, then open the spec file named in each task before changing anything.

Repo root `/Users/parsa/AgentAI` (git). Project `openclaw-project/`. Branch `product-phases-6-11`, HEAD `03662de` plus uncommitted work (see section 4). Production: `https://getlumina.pro` (frontend on Vercel) and `backend.getlumina.pro`, a Hostinger VPS `srv2054170` at `179.236.71.203`, reached with `ssh lumina`.

---

## Implementation status

See [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) for completed cleanup, local test results and the pending tool-origin commit review. P0-1, P0-2 and the owner-approved P0-3 source commits are complete. P3-1 CI implementation is saved in `671f121`; its first GitHub/Linux run is pending. The full local integration run was blocked by low disk space; see the progress record. No production settings have been changed.

## 1. Start here (paste this as your first action)

1. Read, in order: this file, `PRODUCTION_VERIFICATION_2026-10-29.md`, `TECH_DEBT_AUDIT.md`, `CLEANUP_PLAN.md`, `CLAUDE.proposed.md`. Skim `README.md` in this folder for the index.
2. Run the pre-flight in section 6. Report the baseline test result to the owner.
3. Work the task queue in section 7 strictly in order, one task per commit. Before each task open its spec in `phases/` (the file and task ID are listed). Specs were written by reading the code; **line numbers drift, so re-find them**.
4. Stop at every `GATE`. Ask the owner the exact question listed in section 9. Never infer approval from silence or from a note written by another agent.
5. After each task report: what changed (files), tests run and result, finding IDs closed, what is next, and any server step that is now waiting for the owner.

## 2. What Lumina is (short)

A customer AI-assistant platform. Customers sign in (Django app, cookie session), chat with an assistant that runs inside a per-customer isolated container ("cell": gVisor `runsc`, separate Docker engine, own LiteLLM key and budget) using OpenClaw 2026.9.6 (model Sonnet 5.5). Requests go through one durable global queue (one running request at a time on the host). The assistant can drive a browser through a tool relay → `BrowserTool` → `BrowseService` → observe/decide/act loop (the "ladder"): JEV (a TypeSafe-hosted model) chooses steps, else the assistant does; hands are `browse/runner.mjs` in a host Docker stage (the production engine). Customers can watch and take over via a Live view. Generative-UI "blocks" render cards in chat. Billing (Stripe), Telegram, connectors, vault, memory and schedules exist to varying degrees (see `FEATURE_INVENTORY.md`: 74 features: 42 active, 9 incomplete, 7 experimental, 7 legacy, 6 orphaned, 2 duplicated, 1 unknown).

Key code: `platform/accounts/` (Django views/urls/middleware), `platform/agentai_platform/` (chat, request_queue, budget, chat_driver, gateway, browse/*, lifecycle/*, genui/*, ops/*, routing/*), `platform/migrations/*.sql` (30 files, checksummed) + `platform/accounts/migrations`, `lumina/src` (React SPA served at `/app/`), `browse/runner.mjs`, `dashboard/app.py` (owner dashboard, stdlib), `platform/deploy/` (systemd, Caddy, release.py). Details: `ARCHITECTURE.md`, `EXECUTION_FLOWS.md`, `FILE_MAP.md`.

## 3. Verified production state (2026-10-29; details in `PRODUCTION_VERIFICATION_2026-10-29.md`)

- Hostinger `srv2054170`, Ubuntu 26.04.1, up 12 days, 0 failed units, public ports 22/80/443 only, ufw default-deny. The old IONOS host `69.48.206.62` is dead (17 tracked files still name it).
- 8 accounts, 137 requests (120 completed, 9 failed, 8 cancelled); 133 reservations all settled; 0 queued tasks.
- Current release (platform and supervisor) = `20261028T212308Z-tool-origin-v2`, built from the **uncommitted** working tree; verified byte-identical. UI = `lumina-ui-03662de`. `runner.mjs` and the Caddyfile match the repo (Caddyfile differs by one comment).
- Switches: `browse_tasks` ON, `customer_execution` ON, `jev_services` ON, `open_access` ON, `jev_routing` OFF. TypeSafe key files present; browse service runs `--jev-mode live`. Browser engine: `runner` (native browser not rolled out to anyone).
- SSH: password login and root login are ON (`50-cloud-init.conf` sets `PasswordAuthentication yes` and wins over `60-cloudimg-settings.conf`; `PermitRootLogin yes` in `sshd_config`). Host monitor already warns about this and about "no off-server backup". fail2ban active (20 failures, 3 bans total).
- LiteLLM: `turn_off_message_logging: true`, `fail_closed_budget_enforcement: true`. Cells engine default runtime `runsc`. No cell was running at check time (cell isolation not inspected).
- Hygiene: ~100 old release dirs (5.0 GB), ~85 tarballs + 2 git bundles in `/root` (1.9 GB, some may be the only copy of released code), `accounts.env.bak-*` copies (mode 600), 19 pending OS updates incl. kernel, pre-migration DB copies in `/var/lib/agentai-platform` (customer data outside backup retention).
- A hand-installed experiment (`jev-full-page`) ran on the live browse service 2026-10-28 23:03–23:05 outside the release process.
- NOT verified: running-cell isolation, real TypeSafe payloads, backup restore, the owner's off-server copy, secret values.

## 4. Local and git state you inherit

- 11 tracked files are modified and uncommitted (in-progress tool-origin work, **equals production**): `docs/browser-reliability.md`, `platform/accounts/management/commands/tool_relay.py`, `platform/agentai_platform/lifecycle/{cell_bridge,cell_config,tool_origin}.py`, `platform/agentai_platform/tool_relay.py`, `platform/tests/e2e/{harness,stub_model,test_native_e2e}.py`, `platform/tests/test_browser_tool.py`, `platform/tests/test_tool_origin.py`. Untracked but part of it: `lumina-character/node_modules` symlink (not part of it), `platform/agentai_platform/lifecycle/tool_origin_install.py`, `lifecycle/tool_origin_plugin/`, `platform/tests/tool_origin_plugin.test.mjs`, `docs/browser-tool-ownership.md`, `evidence/browser-ownership/` (privacy review needed before committing).
- Old reports were deleted on 2026-10-29 (uncommitted): see `~/AgentAI-removed-20261029.tar.gz` (untracked originals) and `git checkout -- <path>` (tracked ones). A second archive `~/AgentAI-removed-handoffs-20261029.tar.gz` holds the removed handoff files.
- SSH keys were replaced: use only `ssh lumina` (key `~/.ssh/lumina_ed25519`, mode 0600, no passphrase). The old `ssk-key` and `id_ed25519` are deleted. Config backup: `~/.ssh/config.bak-20261029`. ControlMaster is on: for a real second-session test use `-o ControlMaster=no -o ControlPath=none`.
- 47 local commits are unpushed; GitHub status unknown (an earlier note says the account was suspended 14 Oct). Local `main` is an ancestor of HEAD, 107 behind. 14 `worktree-*` branches (13 strict ancestors, `worktree-product-images` has 1 unique commit: never merge it, never delete it).

## 5. Rules (non-negotiable)

1. **Privacy first.** Never log or print customer text, URLs, bodies, cookies, tokens or keys; never add them to docs. Do not add new per-task limits or guardrails (owner rule). Fail-closed bookkeeping fixes are fine.
2. **Preserve unfinished work.** Do not delete anything in `CLEANUP_PLAN.md` "Class G" or `ORPHANED_CODE.md`. "No caller found" is not evidence of dead code (dynamic dispatch, systemd, Django urls, switches, string registries).
3. **Never `git add -A` / `git add .`.** Stage named paths only.
4. **No push, no force-push, no history rewrite, no `git gc --prune=now`** without the owner's explicit yes.
5. **Never edit an existing `platform/migrations/*.sql`** (checksummed; breaks `/readyz`). New schema = next free number from the registry in section 8. Deploy migrations only via `release.py`; older code refuses a newer database.
6. **Production is read-only by default.** Any server change needs the owner's explicit yes for that exact command in the current conversation, a backup/rollback first, and for SSH changes a second live session. You never restart services, edit `/etc`, or delete server files on your own.
7. **Never deploy while the tool-origin work is uncommitted, and never hand-copy files to the server.** Release through `platform/deploy/release.py` (canary + rollback). Every production change must leave a release record.
8. Do not run mutating project scripts (`p15_acceptance.py`, `p4_*`, `bin/phase*`, `experiments/jev-full-page/run_live.py`, `activate-telegram.py`) and do not install global tools.
9. Match the surrounding code style (dense one-liners are common here). Tests: use `platform/.venv`; some suites skip without OpenClaw/Chrome/age and say so. `tests.test_native_run` and `tests.test_request_worker` are NOT in CI: run them by hand.
10. Keep each change small and reversible; one task per commit; commit messages reference finding IDs. Update the audit doc (mark RESOLVED + hash) after each task.

## 6. Pre-flight (before the first task)

```
cd /Users/parsa/AgentAI && git status --porcelain | head -30   # expect the 11 modified files above
git branch --show-current                                      # product-phases-6-11
cd openclaw-project/platform && ../../openclaw-project/platform/.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -5   # baseline; record failures/skips
cd ../lumina && npx tsc --noEmit && npx vitest run 2>&1 | tail -5
cd ../browse && node --test test 2>&1 | tail -5
ssh lumina 'hostname'                                           # srv2054170 (read-only)
```
Record the baseline (pass/fail/skip counts) in your first report so later regressions are attributable.

## 7. Task queue (ordered). Spec file → task. `GATE` = ask the owner first.

### Phase 0: hygiene, no behaviour change → `phases/PHASE_0_AND_2_HYGIENE_AND_SERVER.md`
| Task | Finding IDs | What | GATE |
|---|---|---|---|
| P0-1 | M-03, GH-002, OP-002, ST-004 | Root `.gitignore`: `ssk-key*` and specific key names (not `id_*`), root-anchored `/*.tar.gz`, `/*.zip`, `/*.png`, `.claude/`, clutter dirs; `node_modules` without trailing slash. Spec simulated it: no tracked file is hidden. | none |
| P0-2 | GX-024..026 | Ignore (do not delete) `experiments/`, `lumina-cost-audit/`; report what `backups/`, `jev-browser/logs` hold | owner decides deletions |
| P0-3 | AG-006, GH-005 | Commit the tool-origin work in 4 commits (plugin+installer; relay/bridge/config+tests; e2e harness; docs); optional 5th for `evidence/browser-ownership/` after privacy review. Re-verify equality with `/root/lumina-tool-origin-v2*.tgz`. | owner reviews each commit |
| P0-4 | GH-001, GH-005 | Tag deployed commits: `release/10efb73-genui`-style names matching `release/live*`; native1-4/safety1 only if the proof step verifies the commit | owner OK on mapping |
| P0-5 | GH-013, IS-017 | Push plan: HEAD is 47 ahead of `origin/product-phases-6-11`, 87 ahead/1 behind `origin/main` (`515fdde`, tree = `9d11041`, so `main` can fast-forward after a merge, no force) | **owner decision** |
| P0-6 | GH-006, GH-014 | Read-only worktree inspection (13 of 14 have no unique work; `fastclick` and `live-view` dirty only by the `node_modules` symlink), safety bundle, prune order | **owner OK to prune** |

### Phase 2 (server first aid) → same spec file. Do P2-0 before P2-1.
| Task | IDs | What | GATE |
|---|---|---|---|
| P2-0 | GX-008, SP-04 | Switch `bin/ssh-server`, `bin/scp-server` (and the scripts using them: `pull-backups.py`, `deploy-lumina.py`, `update-ops-dashboard.py`, `connect-tool`, `billing_install.py`) from password + dead IONOS IP to the `ssh lumina` alias | none |
| P2-1 | IS-002 | Disable SSH password/root-password login: edit `50-cloud-init.conf` (+ optional `00-` drop-in in case cloud-init rewrites it), `PermitRootLogin prohibit-password`, `sshd -t`, **reload** (socket-activated), systemd-run timer that restores the old config after 15 min unless cancelled, test with a real second session | **owner yes per command** |
| P2-2 | IS-016 | Off-server backup: option A manual `bin/pull-backups.py`, option B rclone destination; restore drill decrypting only the app-db artifact, never touching the live DB | **owner picks option and drill account** |
| P2-3 | PV-03 | OS updates + reboot in a window: baseline of agentai units/ports/timers/nft, two Docker engines (main: litellm/gateway/postgres; cells engine `agentai-cells-docker`), post-reboot checks, rollback | **owner schedules** |
| P2-4 | PV-01, PV-02, SP-02 | Read-only listing script, never-remove rules (current symlink targets, N latest, tool-origin-v2, only-copy tarballs), then approved-list `rm`; pre-migration DB copies need review | **owner approves the exact removal list** |
| P2-5 | PV-06/07/08 | gunicorn 26.2 control-socket EACCES: `control_socket_disable=True` in `gunicorn.conf.py` (+test); `tool_relay` swallow `ConnectionError` in a `ThreadingHTTPServer.handle_error` subclass (+2 tests); `release.py` `--commit` + `RELEASE.json`, rule that every overlay goes through a release; optional supervisor release script | owner deploys |
| PV-09 | SP-05 | Quarantined restores: warning reads `/var/lib/agentai-cells/quarantine.json` (HostIsolation), not `ops/restore.py`; read-only review; follow-up `quarantine_cli` | **owner per-item delete** |

### Phase 1: security and reliability (code, one commit each)
**`phases/PHASE_1A_RELIABILITY_AND_MONEY.md`** (money path flagged)
| Task | IDs | What | GATE |
|---|---|---|---|
| P1-7 | BE-004, ST-018 | Exempt only `/v1/billing/webhook` and `/v1/telegram/webhook` from the 8192-byte cap; Telegram view also needs its own size check; test through the full middleware stack with a 9 KB body | none |
| P1-6 | BG-011, BE-021 | Remove the duplicate `DATA_UPLOAD_MAX_MEMORY_SIZE`; structured genui bodies up to 128 KiB must pass; chat message cap | **cap: 256 KiB vs 30 MiB** |
| P1-12 | BE-002 | `/v1/tasks/<id>/stream` behind `AGENTAI_SSE_ENABLED` (default off → 404) or delete | **keep-behind-flag vs delete** |
| P1-8 | BE-005 | Billing `--reconcile` timer (draft units in spec) | owner installs; **interval (6 h recommended)** |
| P1-1 | M-01 (BE-001, AG-001, BE-006) | **Money path.** `BudgetLedger.settle_in/release_in`; `RequestQueue.cancel` (waiting) and the revoked-author branch release the reservation and close the task in the same transaction; `RequestQueue.sweep()` (startup + every 60 s) repairs terminal requests holding active reservations or `queued` tasks (never touches `uncertain`); `admitting` hold so a request is unclaimable until `ledger.admit` commits, and `admit` refuses terminal requests. Cancel of an already-claimed request does not release (driver `_close` settles). | **migration 0032 (admitting column): yes/no** |
| P1-9 | AG-005, AG-007 | **Money path, after P1-1.** `check_parked` returns `'expired'` and `driver.expire_parked` actually stops the run; repeated unreadable usage snapshot → stop after N (`blind_limit`, 0 = alert only); fix `test_native_run.py` park-limit test to assert outcome | **spend-guard policy: stop after ~15 blind checks vs log only** |
| P1-10a..f | BG-015, BG-006, BG-004, BG-013, BG-014, BE-017 | events `task_state` returns an event seq; ascending `LIMIT` drops newest rows; inline asset cap (raise to 10 MiB); one failing file aborts all asset captures; plan phase stuck `running` after crash; `task.create` cap on `chat_send` = **do not add** (document) | **asset cap; confirm no new cap** |

**`phases/PHASE_1B_PRIVACY_AND_SECURITY.md`**
| Task | IDs | What | GATE |
|---|---|---|---|
| P1-11 | M-02 (AG-002, AG-003, IS-014) | Screenshots to TypeSafe: recommended default "never send", per-account privacy switch `picture_privacy` (on by default; owner can turn off for one account); gate read at call time, fail-closed at three points (`Look.private`, `Policy.on` in `loop.py`, `JevChooser.images_ok` wired by `make_jev_for` in `service_main.py`); pages with no controls go to the assistant for that page only; update switch text and `plans/product/privacy.md`; tests: no `assets`/image header when gate on, text request unchanged. Note: the assistant (Anthropic) also receives the picture; the policy covers TypeSafe only. Option B (images only when no controls) not recommended. | **owner policy A / B / C** |
| P1-3 | BG-008 | `ops/restore.py` resurrects forgotten data. Memory: skip backup rows whose live status is `deleted`/`superseded`. Saved choices: migration **0031** `saved_choice_tombstones` (field name only); `saved.forget` writes, `saved.remember` clears; restore merges with live winning | none |
| P1-4 | BG-001 | Redactor: add `sk-ant-`, `sk-proj-`, AWS ids, bearer tokens, PEM, unquoted `password=`, secret-named dict keys (~1.4 ms per 32 KiB); synthetic test samples built at runtime | none |
| P1-2 | GX-001/002/003 | Dashboard (runs as root, deployed by `bin/update-ops-dashboard.py`): stop shell-sourcing `accounts.env` (non-shell `read_env_file`, `runuser -m` with explicit env), Content-Length 400/411/413 + socket timeout, progressive lockout instead of one-hour loopback lock | **does `accounts.env` have non-plain KEY=VALUE lines?** |
| P1-5 | BG-002/003/012 | Validator: shape-safe `_children`, wider catch, `without_documents`, per-row isolation in `attach_cards`; phase ownership always enforced, approval cards rendered from the server's phase title; `.json` uploads accepted (`kind == 'json'`) | **BG-003 button: confirm dialog (rec.) vs force message = label** |
| P1-10 (client IP) | M-04 (BE-003, IS-009) | Measure first (`ss`, read-only). Vercel adds a shared-secret header; Caddy trusts `X-Forwarded-For` only when present; middleware falls back to the TCP peer on malformed header. Confirm the Vercel header mechanism against current docs. `caddy validate` + 7-case curl matrix. | **owner approves Caddy + Vercel change and the secret** |
| P1-13 / P1-14 | GX-008..016, OP-011/012 | `build-browser-image.sh` pinned commit + `sha256sum -c`; `out_dir` chown uid 1000 mode 0700 (`browse/service.py` ~L519); random private dir for connect-tool and in-container staging; shared `_ssh.py` for the six SSH wrappers; `activate-telegram.py` dry-run + backup before `sed -i`; `platform/tests/test_bin_hygiene.py` | **GX-014 / GX-016 wording** |

### Phase 3: consolidation (after CI expansion) → `phases/PHASE_3_AND_4_CONSOLIDATION.md`
P3-1 CI: only 20 of 73 `platform/tests` modules run; spec names the 53, those gated on age/Chrome/OpenClaw, and a full replacement workflow (blocking list + report-only job + lumina/browse/plugin/lint jobs). P3-2 doc drift edit list incl. the 17 files naming `69.48.206.62` (`evidence/*` and `BUILD_LOG.md` are immutable: add a banner, don't edit; `CLAUDE.local.md` edits are proposals only). P3-3 env example generated from `settings.py` (38 names read, 8 documented → 30 undocumented) + test. P3-4 one `ChatService` factory (built in 5 places; only `accounts/chat.py` passes a pricer or gateway, which is why Telegram cannot complete), auth/rate decorator; **GATE: Telegram finish vs hide**. P3-5 retention timer + dry-run first; **SP-01: `chat_messages` are never deleted** (**GATE: retention contract, six questions in spec**). P3-6 dead-symbol list (only a short list is safe; `Visuals` is lazy-loaded; keep `email_messages`, `start_picker`, `running_cells` signatures; **GATE: `GoalChain.limit`/`AGENTAI_GOAL_CHAIN_LIMIT` does nothing**). P3-7 resource hygiene (job eviction, classify-once, usage-wait slot hold, poller visibility pause, N+1). P3-8 tests (weak/no-assert tests, dashboard edges, `state/data.tsx`, `ChatBridge`). P3-9 redacted exception logger (class, module, request id only). P3-10 commit examples of server-only files (dashboard unit via `systemctl cat`, `jev.conf` 104 B, `feature-switches.conf` 67 B marked UNVERIFIED until compared; `runner.mjs` sync script). P3-11 systemd sandboxing in stages on a canary (note supervisor-native comment: mount-namespace sandboxing broke loop mounts on 2026-10-12). P3-12 dashboard IONOS-era pages (legacy containers still run on Hostinger; **GATE: retire or keep**). P3-13 remaining BG bugs (BG-007/010/018/030 etc.). P3-14 `git gc` (no `--prune=now`; decide the push first).

### Phase 4: needs decisions (options + staged path in spec)
P4-1 browser engine (M-08), P4-2 genui unification (M-07), P4-3 `lumina-character` (M-06), P4-4 question/vault UI (FE-002), P4-5 single lane fairness (AG-004/BE-013), P4-6 one migration source (BE-012 → migration 0033), P4-7 split `chat_driver.py` / `loop._run` (AG-014), P4-8 orphaned modules (M-05) + GX-017 fixtures.

## 8. Cross-task rules

**Migration registry** (three specs wanted `0031`): `0031_saved_choice_tombstones` (P1-3, required) · `0032_request_admission_hold` (P1-1, optional) · `0033_safety` (P4-6, later). Take the next free number at implementation time; old code refuses newer DBs.

**Order when tasks share files** (rebase between): `request_queue.py`/`budget.py`/`chat_driver.py`: P1-1 → P1-9 → P3-4 → P4-5 → P4-7. `accounts/middleware.py`: P1-7 → P1-6 → M-04. `ops/restore.py`: P1-3 → P2-2 drill → PV-09. `release.py`: P0 → PV-08 → P3-10. `dashboard/app.py`: P1-2 → P3-12. `browse/loop.py`/`ladder.py`: P1-11 → P3-7 → P4-1 → P4-7.

**Two tasks are named `P1-10`**: refer to them by finding ID (BE-017 family vs client IP).

## 9. Owner decisions (ask exactly these; each spec lists both options)
1. Add `admitting` column (migration 0032) or rely on the admit-refusal check plus sweep? 2. Chat message cap 256 KiB instead of 30 MiB? 3. `/v1/tasks/<id>/stream`: keep behind `AGENTAI_SSE_ENABLED` or delete? 4. Spend guard: stop after ~15 unreadable checks (~5 min) or log only? 5. `task.create` cap on chat sends: none (recommended; steered sends never count). 6. Inline asset cap to 10 MiB? 7. Billing reconcile interval (6 h)? 8. Screenshots: never send by default with per-account opt-out (recommended)? 9. BG-003 buttons: confirm dialog (recommended) or message = label? 10. Does `accounts.env` contain non-plain `KEY=VALUE` lines? 11. Wording for `config/openclaw.example.json` (GX-014) and worker skill text (GX-016). 12. May the SSH passwords in `.env` be removed once scripts use keys? 13. `chat_messages` retention contract (SP-01). 14. `GoalChain.limit`: wire or remove? 15. Telegram: finish or hide; retire the IONOS-era dashboard pages? 16. Phase 0/2 gates: tag mappings, push plan, worktree pruning, P2-2 option A/B + drill account, reboot window, removal lists, per-item quarantine deletes. 17. Phase 4 options.

## 10. Do-not-do list
Do not delete `routing/*`; do not merge or delete `worktree-product-images` (migration `0023` collides; its payload is in `d95b796` as `0025`); no `git add -A`; do not delete `lumina-character/` (only copy of the film UI and ask/vault components at HEAD), the orphaned product modules (`durable`, `memory`, `schedules`, `watchers`, `skills`, `optimization`, `policy_check`, `genui/intent`, `ops/rotation`, `lifecycle/broker`), `gen/legacy.tsx`/`Cards.tsx` (only renderer of stored historical cards), the `jev-browser`/`jev-window-core` prototypes or old tags without a decision; do not edit SQL migrations; do not remove `browse/runner.mjs` (it IS the production engine); do not log messages/URLs/bodies; do not add per-task limits; do not delete server `.bak`/release/tarball files before owner review; do not rewrite history; do not treat Sonar's 28 vulnerabilities as a to-do list (the audit recorded the two privacy-relevant ones: `0o777` out dir, predictable `/tmp` name); do not trust the code graph for ServiceRouter (deleted in `5db9636`), Django route→view edges or driver injection; do not deploy by hand; do not run production-mutating scripts.

## 11. Preserve list (must keep working)
Webhook verification (Stripe raw-body HMAC, dedup inbox), uniform-404 enumeration defence, fail-closed switches, per-tenant isolation (every route derives `account_id` from the session; no IDOR found in routes read), age-encrypted backups with the private key never on the host, privacy-first logging (no URLs/bodies/exception text), vault crypto (AES-GCM, per-account HKDF), live-ticket HMAC (120 s), the orphaned-but-valuable product modules, the legacy-card renderer.

## 12. Corrections to earlier audit text (trust these)
M-01 is latent in production and the "unfunded" path does not leak by itself (the race is BE-006) · BE-015 is 30 undocumented env names, not 23 · BG-001 gap is narrower (the `activity` path already redacts bearer/`KEY=`/`Authorization:`) · BG-002 `section blocks=[3]` does not raise · GX-006: legacy owner containers run on Hostinger · PV-09 source is `HostIsolation` → `quarantine.json` · IS-004 resolved (control server/legacy supervisor not installed) · IS-005: live nft has the 4000/4100 doors, only the checked-in sample is stale · `jev_services` is no longer in the switch catalog; `privacy.md` still says "shadow mode" · `CLAUDE.local.md` ServiceRouter/`test_service_handoff` notes are stale · native1-4/safety1 predate `d95b796`.

## 13. Reference map (this folder, `/Users/parsa/AgentAI/docs/codebase-audit/`)
`README.md` index · `TECH_DEBT_AUDIT.md` summary · `TECHNICAL_DEBT.md` register (125 rows + Supplement A BG/GX/PV + Supplement B SP) · `CLEANUP_PLAN.md` classes A–G, preserve + do-not-do · `PRODUCTION_VERIFICATION_2026-10-29.md` · `SECURITY_AND_RELIABILITY.md` · `DEPLOYMENT_AUDIT.md` (VPS checklist/script) · `SYSTEM_OVERVIEW.md`, `ARCHITECTURE.md`, `EXECUTION_FLOWS.md`, `FILE_MAP.md`, `DEPENDENCIES.md` · `FEATURE_INVENTORY.md`, `INCOMPLETE_FEATURES.md`, `LEGACY_CODE.md`, `ORPHANED_CODE.md`, `DUPLICATIONS.md` · `AUDIT_COVERAGE.md` (what was/was not verified) · `CLAUDE.proposed.md` (draft context file, not installed) · `phases/` (4 spec files) · `_findings/` (raw investigator reports, reconciliation, raw server output).

## 14. Definition of done and reporting
A task is done when: tests added/updated and passing (state which suites skipped), the acceptance criteria in its spec are met, the audit doc line is marked RESOLVED with the commit hash, no unrelated changes, and any server step is listed for the owner. If a spec is wrong or a finding no longer holds, say so ("Finding check") and update the doc instead of forcing the change. If you cannot proceed without an owner decision, stop and ask; do not guess. Final report at the end: tasks completed (IDs + hashes), tasks blocked and why, open decisions, server steps pending, regressions or new findings.
