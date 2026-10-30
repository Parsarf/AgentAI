# File Map: /Users/parsa/AgentAI

Legend. Kind: **S** source, **G** generated/build output, **V** vendored, **A** assets, **E** evidence/records, **D** docs, **X** untracked clutter/scratch, **C** config/deploy. Production is unverified; "consumer" means what the repo says calls it. Class A-G labels follow the audit convention (A delete-safe after confirm, C product decision, G preserve).

## 1. Git root `/Users/parsa/AgentAI`

| Path | Kind | Responsibility | Consumer / entry | Notes |
|---|---|---|---|---|
| `openclaw-project/` | S | The whole product (see section 2) | everything | tracked, 10,224 files |
| `product/` | D/S | Offer: `CONTRACT.md`, `plan.json` (numeric source of truth), `cost-inputs.json`, `cost-results.json`, `calculate_costs.py`, `deployment-policy.json`, `SCREENS.md`, `wireframes.html` | `platform/deploy/billing_install.py:140`, `platform/tests/test_billing.py:17`, `billing.py:190-193` | `product/marketing/` untracked; `actual_*` still null (OP-007); constants duplicated in code (OP-008) |
| `phase-prompts/` | D | 19 numbered phase prompts, `final_phase.md` (F1-F13), coverage ledger, execution contract | humans/agents; cited by `plans/product/LAUNCH.md` | tracked; old `phase-0..12` only in history (GH-008) |
| `.github/workflows/platform.yml` | C | Only CI job "Customer platform" | push/PR | hand-listed subset of tests; no frontend (M-10) |
| `README.md` | D | Root readme | humans | last edited 5 Oct, stale (OP-016) |
| `.gitignore` | C | ignores `.env*`, `*.pem`, `*.key`, `.venv`, `logs/`, `data/`, `backups/`, `node_modules/` | git | does NOT cover `ssk-key*`, zips, tarballs, `jev-*`, `.claude/`; `node_modules/` misses symlinks (GH-002) |
| `CLAUDE.local.md` | D | Local Claude/cbm workflow | Claude Code | untracked/excluded; ServiceRouter lines stale (M-11) |
| `docs/codebase-audit/` | D | This audit (untracked) | humans | `_findings/` are raw per-scope inputs |
| `.claude/` | X | `settings.local.json` + `worktrees/` (14 git worktrees, 573 MB) | Claude Code | untracked, un-ignored; 13/14 branches fully merged (GH-014, OP-013) |
| `ssk-key`, `ssk-key.pub` | X (SECRET) | SSH keypair, purpose unknown | none known | never in history; NOT ignored; do not read or add (M-03, L-02) |
| `jev-browser/` (24 MB) | X | "Bare loop" JEV browser prototype (Python stdlib + Node CDP) | `python -m jevbrowse` | unreferenced by product; own `.venv`, `logs/`, `.env` (OP-004, OP-018) |
| `jev-browser-{pre-remodel,v2-complex,v3-before-reset,v4-with-playwright}.tar.gz` | X | Snapshots of the above | none | intentional history (OP-005) |
| `jev-window-core/` (268 KB) | X | macOS window-driving loop (Swift + Python) | `python3 run.py` | experimental, `.env` ignored by nested rule |
| `lumina-cost-audit/` (832 KB) | X (PRIVACY) | Measured cost analysis of production; includes owner browsing request logs | no code | un-ignored; keep out of git (OP-003, OP-007) |
| `sonarqube-export/`, `SONARQUBE-REPORT.md`, `SONARQUBE-FIX-PROMPT.md` | X | Sonar scan 2026-10-13 (28 vuln, 52 bugs, 709 smells) | input to fix prompt | none acted on (OP-010/011) |
| `brag-output/` | X | Hyperframes launch-video scaffold | `/brag` skill | marketing |
| `lumina-environment-v3-clips.zip` (242 MB), `openmoji-svg-color.zip` (5 MB) | A/X | Creature clips; OpenMoji archive | none in git | binaries at root |
| `image*.png`, `Screenshot *.png`, `5BAEE604-....PNG` | X | Ad-hoc screenshots | none | not opened |
| `.venv/` (root) | G | Python venv | ignored | |

## 2. `openclaw-project/`

### 2.1 `platform/` (the customer product backend, 405 tracked files)

| Path | Kind | Responsibility | Consumer / entry |
|---|---|---|---|
| `platform/accounts/` | S | Django project: `settings.py`, `urls.py` (route table), `views.py` (auth, projects, `endpoint()` decorator), `middleware.py` (Boundary + Account), HTTP layers `chat.py`, `files.py`, `streams.py`, `browse.py`, `billing.py`, `telegram.py`, `connections.py`, `vault.py`, `safety.py`, `genui.py`, `signup.py`, `uishell.py` (SPA bundle at `/app/`) | gunicorn `accounts.wsgi` (`agentai-platform-app.service:9`) |
| `platform/accounts/management/commands/` | S | 13 commands: `request_worker`, `billing_worker`, `deliver_account_mail`, `tool_relay` (modified), `retention_accounts` (unscheduled), `telegram_worker` (no unit), `bootstrap_accounts`, `account_admin`, `signup_admin`, `onboard_trial`, `seed_trial`, `lifecycle_status`, `verify_interactive_ui` | systemd units or operators |
| `platform/accounts/migrations/` | S | Django migrations 0000-0015 (shims re-run SQL adopter) | `bootstrap_accounts` |
| `platform/accounts/test_*.py`, `tests.py` | S (test) | 14 Django test modules | CI `manage.py test accounts` |
| `platform/agentai_platform/` | S | Service library, see 2.1.1 | accounts, workers |
| `platform/migrations/0001..0030_*.sql` | S | Authoritative checksummed schema | `Store.initialize()`; editing breaks `/readyz` |
| `platform/tests/` | S (test) | 73 `test_*.py` + `e2e/` + `tool_origin_plugin.test.mjs` (untracked) | CI runs about 20 (ST-001) |
| `platform/deploy/` | C | 18 systemd units/timers, `caddy/`, `cells-docker/`, `model-proxy/`, `vercel/`, `release.py`, `p4_*`/`p15_acceptance.py` (hand-run), `*.example.json`, `accounts.env.example` | operator on server |
| `platform/openapi.json` | D | 111 paths, v0.8.0 | docs only (BE-016) |
| `platform/requirements.lock` | C | Hash-pinned Python deps (9 pkgs) | CI, `release.py` |
| `platform/ui-reference/` | S/D | 94-line plain-JS reference client | `UI_CONTRACT.md:10` only (FE-018) |
| `platform/*.md` | D | `README`, `OPERATIONS`, `BILLING`, `UI_CONTRACT`, `SERIAL_REQUESTS`, `deploy/README`, `LIVE_VIEW` | humans |
| `platform/.venv`, `__pycache__`, `node_modules` | G | local only | ignored |

#### 2.1.1 `agentai_platform/` modules

| Module(s) | Responsibility | Consumer / status |
|---|---|---|
| `chat.py`, `request_queue.py`, `request_worker.py`, `chat_driver.py`, `gateway.py`, `outcome.py`, `goals.py`, `budget.py`, `task_progress.py` | Agent loop: admit, queue, supervise, settle (see ARCHITECTURE) | ACTIVE; M-01 |
| `tool_relay.py` | MCP-over-HTTP door for cells | ACTIVE, uncommitted edits |
| `billing.py`, `switches.py`, `safety.py`, `privacy.py`, `security.py`, `store.py`, `capacity.py`, `config.py`, `ssrf.py`, `vault.py`, `saved.py`, `activity.py`, `events.py` | Stripe state machine; owner switches; protection toggles; scrub; session helpers; sqlite store; vault AES-GCM | ACTIVE |
| `files.py`, `artifacts.py`, `storage.py` | Upload, artifact versions, single-use download tickets | ACTIVE if `AGENTAI_STORAGE_DIR` set (not deep-audited) |
| `telegram.py`, `connectors.py` | Telegram ingress; OAuth/custody for Google/GitHub | INCOMPLETE (BE-007, BE-008) |
| `browse/` | Browse service: `adapter` (tool schemas), `service`, `service_main`, `loop` (safety floor), `ladder` (JEV chooser), `native_runner`, `native_scripts`, `modes`, `candidates`, `goals`, `trace`, `untrusted`, `session(s)`, `client` | ACTIVE; two engines (M-08) |
| `lifecycle/` | Cell config, bridge, supervisor, fleet driver, coordinator, sleep, netpolicy, volumes, secrets custody, LiteLLM admin; `tool_origin*.py` + `tool_origin_plugin/` | ACTIVE; tool_origin IN PROGRESS; `broker.py` dormant |
| `live/` | `gateway.py` (frame server), `ticket.py` (HMAC), `now.py` | ACTIVE |
| `genui/` | `document.py`, `artifacts.py`, `runner.py`, `schema.py`, `store.py`, `images.py`, `gen_registry.json`, `intent.py` | ACTIVE; `intent.py` orphan |
| `routing/` | JEV shadow classifier, display chooser, config, store, report CLI | switches default off; `services.py` deleted (M-11) |
| `ops/` | backup, restore, monitor, alerts, exposure, inventory, hostconfig, crypto, destinations | ACTIVE; `rotation.py` orphan |
| `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py`, `optimization.py`, `policy_check.py` | Unfinished product features | ORPHANED (M-05), preserve |
| `server.py` | Legacy stdlib control server (`--service control`) | LEGACY candidate (IS-004) |
| `bridge_client.py`, `adapters.py` | Unix-socket client; adapter protocols | support |

### 2.2 Frontend

| Path | Kind | Responsibility | Consumer / entry |
|---|---|---|---|
| `lumina/` | S | Live React SPA. `src/main.tsx` → `App.tsx`; `pages/` (Chat, Home, History, Tasks, Live, Files, Login, Info); `components/`; `state/data.tsx` (global store); `lib/api.ts` (only HTTP client); `gen/` (new generative UI); `components/genui` + `lib/genui` (old); `components/safety` | Vite build → `lumina/dist` → `AGENTAI_UI_BUNDLE_DIR` → served at `/app/` |
| `lumina/public/` | A | 22 MB OpenMoji SVGs, earth.jpg | build |
| `lumina/src/vendor/thinking-orbs/` | V | Orb engine | `components/Orb.tsx` |
| `lumina/dist/`, `node_modules/` | G | build output / deps | ignored |
| `lumina/tests/`, `scripts/` | S | manual browser harnesses; `check-design.mjs` (in build) | not in CI |
| `lumina-character/` | S/A (fork) | Frozen full copy of the film/parchment UI incl. ask/vault UI; 61 MB scene assets | nothing in deploy/CI (M-06); `node_modules` is an untracked symlink |

### 2.3 Browser, optimization, owner tooling

| Path | Kind | Responsibility | Consumer / entry |
|---|---|---|---|
| `browse/` | S | `runner.mjs` (Playwright in Docker stage, default engine), `package.json` (`playwright-core 1.49.1`), `test/` | `browse/service.py` `stage_argv`; hand-copied to `/opt/agentai-browse/runner` (IS-006) |
| `browser-opt/`, `research-opt/` | S | Phase 9/12 adapters, rubric, JEV adapter | CI unit tests only |
| `experiments/` | X | `jev-full-page/` JEV experiment (untracked) | none |
| `evals/` | S | acceptance cases | tests |
| `dashboard/` | S | `app.py` stdlib owner dashboard, `static/`, `workread.mjs`, `test_dashboard.py` | `bin/open-ops-dashboard.py`, `update-ops-dashboard.py` |
| `bin/` | S | Owner-Mac helpers: `ssh-server`, `scp-server`, `deploy-lumina.py`, `pull-backups.py`, `setup-backup-key.py`, `ops-restore.sh`, `owner-console.py`, `activate-telegram.py`, `phase4/`, `phase6/` | humans (RUNBOOK) |
| `deploy/` | C | Owner stack: `docker-compose.production.yml`, Dockerfiles, `litellm.yaml` (dup), env examples | owner `docker compose` |
| `config/` | C | `openclaw.example.json`, `litellm.example.yaml`, `phase*.batch.json`, fixtures, `skills/`, `workspace-templates/` | tests, `bin/phase6/*`; no runtime consumer (AG-009) |
| `requirements-local.txt` | C | `python-dotenv` only | `bin/*.py` (`mcp` undeclared, ST-006) |

### 2.4 Docs, plans, evidence, misc

| Path | Kind | Notes |
|---|---|---|
| `ARCHITECTURE.md`, `README.md`, `RUNBOOK.md`, `SERVER_DEPLOYMENT.md`, `RELEASE_NOTES.md`, `BUILD_LOG.md`, `CONNECT_TOOLS.md`, `MIGRATION_DECISIONS.md` | D | Accreted and partly stale (ST-014, IS-015); BUILD_LOG last entry 12 Oct |
| `docs/` | D | `architecture/` (native-execution.md is current), `orchestration-audit/` (historical), `generative-ui/`, `browser-reliability.md` (modified), `browser-tool-ownership.md` (untracked), `SYSTEM_DESCRIPTION.md` |
| `plans/` | D | `phase-4..10` (Sep, owner-runtime numbering), `plans/product/` (phase-01..15, LAUNCH.md, privacy.md) |
| `evidence/` | E | 183 tracked files, 1.5 MB: deployment records, browser-reliability logs/PNGs; `evidence/browser-ownership/` untracked. CLAUDE.local.md calls it not indexed (IS-018) |
| `research/`, `reviews/` | E | small notes (12K, 8K) |
| `backups/` | G | 496K, gitignored |
| `tmp/` | G | empty, gitignored |
| `prompt.md`, `prompt-analysis-2026-10-15.md` | D | prompt records |

## 3. Quick "where is X" index

| Need | Go to |
|---|---|
| Customer HTTP routes | `platform/accounts/urls.py`, handlers in same dir |
| Request lifecycle | `agentai_platform/{chat,request_queue,request_worker,chat_driver}.py` |
| Browser safety rules | `agentai_platform/browse/loop.py:162-196` |
| Owner switches | `agentai_platform/switches.py` |
| Plan limits | `product/plan.json`, `billing.py:190-193` |
| Systemd/Caddy | `platform/deploy/` |
| Frontend API calls | `lumina/src/lib/api.ts` and callers (map in `_findings/frontend.md` cross-scope section) |
