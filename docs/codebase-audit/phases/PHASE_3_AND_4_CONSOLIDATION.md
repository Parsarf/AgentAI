# Phase 3 (consolidation) and Phase 4 (decision-driven) implementation specs

Purpose: executable specifications for Phase 3 items P3-1..P3-14 and the Phase 4 items listed in `docs/codebase-audit/HANDOFF.md` section 5, written for a cleanup AI that has no other context. Every file:line below was re-read on 2026-10-29 against branch `product-phases-6-11` (HEAD `03662de` plus the uncommitted tool-origin work). Production (Hostinger `srv2054170`, `179.236.71.203`, `ssh lumina`) was verified read-only by the audit; every server command in this file is TEXT for the owner to approve, never something to run unprompted. Owner priorities that govern every task: customer privacy first; no new per-task limits; preserve unfinished functionality; fail-closed bookkeeping fixes are fine.

All paths are relative to `/Users/parsa/AgentAI/openclaw-project/` (called `$P` below) unless they start with `/`. Platform commands run from `$P/platform` with `.venv/bin/python`. Frontend commands run from `$P/lumina`.

## Ordering and dependency graph

```
P0-1, P0-3 (clean tree, tool-origin work committed)   <- hard prerequisite for everything below
  |
  +-> P3-1 CI expansion  ---------------------------------> gates every later code task (they should land with CI green)
  |      \-> P3-8 test additions/replacements (new tests are picked up by P3-1's runner)
  +-> P3-2 doc drift (independent; do early, cheap)
  +-> P3-3 env example generator (independent; needs P3-1 to run its test in CI)
  +-> P3-4 service factory / Telegram   (after P1-1, P1-7; touches chat.py that P1-1 also touches)
  |      \-> P3-5 retention timer (after owner answers the retention contract; independent of P3-4)
  +-> P3-6 dead-symbol cleanup (after P0-3: tool_relay.py is uncommitted today)
  +-> P3-7 resource hygiene (after P1-9; chat_driver and browse/service are also touched by P1-1/P1-9)
  +-> P3-9 redacted exception logger (before P3-13 so new error paths can use it)
  +-> P3-10 commit server-only examples  -> P3-11 root-unit sandboxing (needs the unit files in git first)
  +-> P3-12 dashboard (needs P3-10 for the dashboard unit; P1-2 first)
  +-> P3-13 BG functional bugs (BG-004..BG-030 subset; after P3-9)
  +-> P3-14 git gc/asset strategy (after P0-5 push decision)

Phase 4 (all GATED by owner decisions; each has a staged path where every commit keeps the app working):
  P4-1 M-08 browser engine     P4-2 M-07 genui unification     P4-3 M-06 lumina-character
  P4-4 FE-002 question/vault   P4-5 AG-004/BE-013 lane         P4-6 BE-012 one migration system
  P4-7 AG-014 chat_driver/loop split   P4-8 M-05 orphaned modules + GX-017 fixtures
  Dependencies: P4-4 before P4-1 (the native engine also reaches the asking state); P4-6 before any new
  safety table; P4-7 after P1-1/P1-9 and P3-7 (so behaviour fixes are not mixed into a pure move);
  P4-5 after P4-7 step 3 (the slot/settlement code is easier to reason about once split).
```

## Pre-flight checklist (run before the first task, and again after any branch switch)

1. `git -C /Users/parsa/AgentAI status --short` must show no tracked modifications you did not make. The tool-origin files listed in the handoff (P0-3) must already be committed; if not, STOP and do P0-3 first (rule 3 of the handoff: never `git add -A` at the repo root).
2. `git -C /Users/parsa/AgentAI branch --show-current` is `product-phases-6-11`; create a work branch per task group (`git switch -c cleanup/p3-1-ci`), never commit to `main`.
3. Baseline platform tests (record pass/fail/skip counts, they are your regression reference):
   `cd $P/platform && .venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -15` (this is the full local suite; it takes a few minutes; modules needing OpenClaw/Chrome/age skip).
   `cd $P/platform && AGENTAI_SESSION_SECRET=$(.venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(64))') AGENTAI_STATE_DIR=$(mktemp -d) AGENTAI_PUBLIC_ORIGIN=https://localhost .venv/bin/python manage.py test accounts`
   `cd $P/lumina && npx tsc --noEmit && npx vitest run`
   `cd $P/browse && node --test test/` (needs Chrome; expect failures on a machine without the Mac path)
   `cd $P && node --test platform/tests/tool_origin_plugin.test.mjs`
4. `cd $P/platform && .venv/bin/python manage.py makemigrations --check --dry-run` is clean.
5. Never print or log secrets. Never run `p15_acceptance.py`, `p4_*`, `bin/phase*`, `experiments/jev-full-page/run_live.py`.

---

## P3-1: CI expansion

- **Findings**: M-10, ST-001, ST-017, AG-017, OP-009. **Finding check**: re-verified HIGH. `ls platform/tests/test_*.py` = 73 modules; the workflow's `unittest` line names 20 of them (the audit's "about 20/21" is exactly 20); `accounts/test_*.py` (14 files) run via `manage.py test accounts`. 53 modules never run in CI. The 4 non-workflow suites already in the job (browser-opt, research-opt, plugin `test.mjs`, dashboard) stay.
- **Goal / user-visible effect**: a push that breaks billing, browse, ops backup/restore, cell bridge, safety gates, the frontend type-check or the tool-origin plugin turns CI red instead of reaching the owner's server. No product behaviour changes.
- **Depends on / blocks**: needs P0-1 and P0-3 (`tool_origin_plugin.test.mjs` and `test_tool_origin.py` must be tracked before CI can run them). Blocks nothing hard, but every later code task should land with this green. **GATE**: none for the YAML. Owner question only if a module cannot be made green: "Park module X in the report-only list for now, or fix it first?" (default: park, with an expiry note).
- **Files to change**: `.github/workflows/platform.yml` (repo root, currently 35 lines, read in full); new `platform/tests/ci_blocking.txt`; `platform/tests/test_browse_modes.py:260` and `platform/tests/test_browse.py:547` (Chrome path); new `.github/workflows/` file is NOT needed (one workflow, several jobs). **Read first**: `.github/workflows/platform.yml`, `platform/tests/__init__.py`, `browse/test/runner.test.mjs:1-12`, `lumina/package.json`.
- **Current behaviour** (`.github/workflows/platform.yml`): job `checks`, `working-directory: openclaw-project/platform`, Python 3.12, Node 22, `pip install --require-hashes -r requirements.lock`, then `python manage.py test accounts`, then
  `python -m unittest tests.test_request_queue tests.test_lifecycle tests.test_supervisor tests.test_budget tests.test_capacity tests.test_foundation tests.test_fleet_driver tests.test_chat tests.test_gateway tests.test_telegram tests.test_files tests.test_events tests.test_native tests.test_policy_check tests.test_durable tests.test_phase10_assets tests.test_connectors tests.test_optimization tests.test_phase12_assets tests.test_switches`, then `node deploy/vercel/check.mjs`, then the optional-track tests.
- **The 53 modules NOT run today** (computed by diffing the workflow line against `ls platform/tests/test_*.py`):
  `test_activity test_billing test_billing_install test_broker test_browse test_browse_ask test_browse_fields test_browse_fill test_browse_goals test_browse_modes test_browse_service test_browse_sight test_browse_trace test_browse_untrusted test_browser_tool test_card_images test_cell_bridge test_cell_config test_chat_history test_display test_enroll_cli test_fleet_maintenance test_gen_artifacts test_gen_document test_genui test_ipv4 test_live test_maintenance test_model_proxy test_native_run test_native_runner test_native_wiring test_netpolicy test_ops_backup test_ops_cli test_ops_diagnostics test_ops_housekeeping test_ops_monitor test_ops_restore test_ops_rotation test_privacy test_probe_models test_request_worker test_routing test_safety_gates test_secrets_custody test_sleep test_task_progress test_tool_origin test_vault test_volumes test_worker test_workspace`.
  Also never run: `platform/tests/e2e/test_native_e2e.py`, `e2e/test_native_browser.py` (not under the `tests.test_*` names), `browse/test/*.mjs`, `lumina` (42 vitest files, `tsc`, build), `tests/tool_origin_plugin.test.mjs` (untracked today).
- **Which need OpenClaw / Chrome / age / Linux (skip guards, verified by grep)**:
  | Module | Guard | On ubuntu-latest |
  |---|---|---|
  | `test_ops_backup` (4 skips), `test_ops_cli` (1) | `shutil.which('age')` and `age-keygen` | runs only if `sudo apt-get install -y age` (package exists on 24.04) |
  | `test_browse.py:547` (one class) | `node` + `/Applications/Google Chrome.app` + `browse/node_modules` | skipped on Linux unless the path is made overridable (step 4) |
  | `test_browse_modes.py:263` | `CHROME = '/Applications/Google Chrome.app/...'` (line 260) | same |
  | `e2e/test_native_e2e.py:23` | pinned OpenClaw package (`OPENCLAW_PACKAGE`) | always skipped (needs real package) |
  | `e2e/test_native_browser.py:56` | OpenClaw 2026.9.6 + Chrome + node | always skipped |
  | `test_supervisor.py:177,192` (already in CI) | `socket.SO_PEERCRED` | these RUN on Linux CI (skipped on a Mac), a bonus |
  Modules that fake node with `shutil.copyfile(sys.executable, node)` (`test_fleet_driver`, `test_fleet_maintenance`, `test_native_wiring`) need nothing external.
- **Change**:
  1. Create `platform/tests/ci_blocking.txt`: one module per line, no `tests.` prefix. Start it with the 20 modules already blocking (so nothing regresses).
  2. Replace the workflow with the text below. It keeps the blocking list as data, runs every other module report-only into the job summary, and adds `lumina`, `browse`, plugin and lint jobs. Promotion of a module = move one line into `ci_blocking.txt`.
  3. First run on a branch; read the report-only summary; for each red module decide "fix" (test depends on Mac paths/timing) or "park". Promote in batches of 5-10 modules per commit, in this order (cheapest first, pure-Python, no host deps): `test_activity test_billing test_billing_install test_browse_ask test_browse_fields test_browse_fill test_browse_goals test_browse_sight test_browse_trace test_browse_untrusted test_card_images test_chat_history test_display test_gen_artifacts test_gen_document test_genui test_ipv4 test_live test_privacy test_routing test_safety_gates test_secrets_custody test_sleep test_task_progress test_vault test_worker test_workspace test_request_worker test_cell_bridge test_cell_config test_tool_origin test_browser_tool test_model_proxy test_netpolicy test_volumes test_maintenance test_broker test_enroll_cli test_fleet_maintenance test_native_run test_native_runner test_native_wiring test_ops_diagnostics test_ops_housekeeping test_ops_monitor test_ops_restore test_ops_rotation test_probe_models test_browse_service test_browse_modes test_browse test_ops_backup test_ops_cli`. Known flaky candidates (GX-022: real `time.sleep`/wall-clock polling): `test_browse_service`, `test_native_runner`; give them `continue` status until P3-8 removes the sleeps.
  4. Make the Chrome path overridable so the browse suites can run on CI: `test_browse_modes.py:260` -> `CHROME = os.environ.get('BROWSE_CHROME') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'`; same for the path test at `test_browse.py:547` (read that line first; add `import os` only if missing). `browse/test/runner.test.mjs:9` already does `process.env.BROWSE_CHROME ||= '/Applications/...'`, so setting `BROWSE_CHROME=/usr/bin/google-chrome` in CI works for the node tests (GitHub's ubuntu image ships Google Chrome; if absent the step fails visibly, which is the desired report).
  5. End state (after all modules are green or consciously parked): replace the two-step blocking/report-only runner by `python -m unittest discover -s tests -t . -p 'test_*.py'` and delete `ci_blocking.txt`.

```yaml
# .github/workflows/platform.yml  (full replacement text)
name: Lumina CI
on: [push, pull_request]
permissions:
  contents: read
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  platform:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: openclaw-project/platform
    env:
      AGENTAI_PUBLIC_ORIGIN: https://localhost
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      - run: sudo apt-get update && sudo apt-get install -y age
      - run: python -m pip install --require-hashes -r requirements.lock
      - name: Account API checks
        run: |
          export AGENTAI_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
          export AGENTAI_STATE_DIR="$(mktemp -d)"
          python manage.py test accounts --verbosity 1
      - name: Migration drift
        run: |
          export AGENTAI_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
          export AGENTAI_STATE_DIR="$(mktemp -d)"
          python manage.py makemigrations --check --dry-run
      - name: Platform tests (blocking list)
        run: python -m unittest $(sed 's/^/tests./' tests/ci_blocking.txt | tr '\n' ' ') -v 2>&1 | tail -n 40
      - name: Platform tests (report-only, not yet promoted)
        continue-on-error: true
        run: |
          fail=0
          : > "$RUNNER_TEMP/report.md"
          for f in tests/test_*.py; do
            m=$(basename "$f" .py)
            grep -qx "$m" tests/ci_blocking.txt && continue
            if timeout 300 python -m unittest "tests.$m" >"$RUNNER_TEMP/$m.log" 2>&1; then
              echo "PASS $m" >> "$RUNNER_TEMP/report.md"
            else
              echo "FAIL $m (see log tail)" >> "$RUNNER_TEMP/report.md"; tail -n 15 "$RUNNER_TEMP/$m.log" | sed 's/^/    /' >> "$RUNNER_TEMP/report.md"; fail=1
            fi
          done
          { echo '### Report-only platform modules'; cat "$RUNNER_TEMP/report.md"; } >> "$GITHUB_STEP_SUMMARY"
          exit $fail
      - name: Vercel routing checks
        run: node deploy/vercel/check.mjs
      - name: Tool-origin plugin test
        run: node --test tests/tool_origin_plugin.test.mjs
      - name: Optional optimization track checks (offline)
        run: |
          (cd ../browser-opt && python -m unittest test_jev_adapter test_route)
          (cd ../research-opt && python -m unittest test_adapter)
          node --test ../research-opt/plugin/test.mjs
          (cd ../dashboard && python -m unittest test_dashboard)

  lumina:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: openclaw-project/lumina
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: openclaw-project/lumina/package-lock.json
      - run: npm ci
      - run: npx tsc --noEmit
      - run: npx vitest run
      - run: npm run build          # check-design + tsc + vite build (see package.json)

  browse:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: openclaw-project/browse
    env:
      BROWSE_CHROME: /usr/bin/google-chrome
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: openclaw-project/browse/package-lock.json
      - run: npm ci
      - name: Browse runner tests (start report-only; remove continue-on-error once green)
        continue-on-error: true
        run: node --test test/

  lint-report:
    runs-on: ubuntu-latest
    continue-on-error: true            # report-only, never blocks
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install ruff vulture
      - name: ruff (pyflakes rules only)
        run: ruff check --select F --exit-zero openclaw-project/platform/agentai_platform openclaw-project/platform/accounts
      - name: vulture (>=80 percent)
        run: vulture openclaw-project/platform/agentai_platform openclaw-project/platform/accounts --min-confidence 80 || true
```
  Notes on the YAML: (a) `lumina` needs no env; vitest runs under jsdom. (b) The `lint-report` tools are installed without hashes on purpose and are not part of the product lock; they only print. (c) If a runner lacks `/usr/bin/google-chrome`, the `browse` job and the Chrome-gated Python tests fail/skip visibly; do not install Chrome from an unpinned URL.
- **Tests to add/update**: none new for the YAML itself. Validate it locally with `python3 -I -c "import yaml,sys;yaml.safe_load(open('.github/workflows/platform.yml'))"` only if PyYAML exists in the venv (else read it carefully; GitHub validates on push). Regression proof that the runner works: temporarily add a failing assertion in a promoted module on a throwaway branch and confirm the blocking step fails (then discard the branch).
- **Commands to run**: pre-flight set; plus `cd $P/platform && .venv/bin/python -m unittest $(sed 's/^/tests./' tests/ci_blocking.txt | tr '\n' ' ')` locally to prove the list is importable. Skips locally: age (if not installed), Chrome gated classes (unless `BROWSE_CHROME` set), e2e (OpenClaw).
- **Acceptance criteria**: workflow green on the branch; the job summary lists every one of the 53 modules as PASS/FAIL; `ci_blocking.txt` grows monotonically; `lumina` job runs 42 vitest files + build; the plugin test appears in the log.
- **Rollback**: `git revert` the commit; the old workflow is restored. Promotion commits are independent one-liners to `ci_blocking.txt`.
- **Risks and edge cases**: `requirements.lock` is hash-pinned: do not add tools to it. `concurrency.cancel-in-progress` cancels older pushes of the same ref (fine). The `Migration drift` step needs the same env as the Django tests. Report-only step uses `continue-on-error`, so a red module never blocks until promoted; do not forget to promote or the coverage is cosmetic. `tests/e2e` modules are never discovered by the `tests/test_*.py` glob; add them to the end-state `discover` run only if they skip cleanly (they do).
- **Do not**: do not `pip install` anything outside the lock for the blocking path; do not delete or `@skip` a failing test to turn CI green (park it in the report-only list instead and file the reason); do not run `p15_acceptance.py`/`bin/phase*`.
- **Commit message**: `CI: run lumina, browse, plugin and every platform test module (blocking list + report-only) (M-10, ST-001, ST-017, AG-017)`

---

## P3-2: Documentation drift

- **Findings**: M-11, ST-014, IS-015, AG-016, OP-015, L-01, ST-013, plus GX-008 context for the IP. **Finding check**: re-verified HIGH. Extra checks done: `routing/` has no `services.py` (listing: `__init__ bench classifier config decision display policy report_cli shadow store`), `platform/tests/test_service_handoff.py` does not exist, `git grep ServiceRouter` hits only `docs/architecture/findings.md:35` and `docs/orchestration-audit/*` (those are historical analysis and already say "deleted"); `git ls-files | xargs grep -l 69.48.206.62` returns exactly 17 files (list below). One correction to the audit: `OPERATIONS.md:211` says `pursuit` and `jev_services` "no longer exist" and that is TRUE for the code (`git grep jev_services` in `platform/ accounts/ dashboard/` finds nothing), while the server's persisted switch file still contains `jev_services` ON (PRODUCTION_VERIFICATION). Do not "fix" that sentence; the stale entry is server state (see P3-10).
- **Goal**: a new reader (human or AI) gets the true state: Lumina is a live customer platform on Hostinger; IONOS is dead; ServiceRouter is gone.
- **Depends on / blocks**: none. Do after P1-14 so `bin/*` stop pointing at the dead IP. **GATE**: `CLAUDE.local.md` is the owner's private, untracked instruction file: the AI must only PROPOSE the edit (write it into the report), never edit it.
- **Files to change / edit list** (quote = exact current text; verify with `rg -nF` before editing, then replace):

  `README.md`
  - Current: `The owner OpenClaw deployment runs on the always-on IONOS VPS with LiteLLM` -> `The owner OpenClaw deployment and the Lumina customer platform run on the always-on Hostinger VPS (srv2054170, 179.236.71.203, \`ssh lumina\`) with LiteLLM`.
  - Current: `Product Phases1–2 now deliver the [customer contract](../product/CONTRACT.md)` through `Customer accounts/provisioning/chat/billing remain subsequent product phases.` (the whole 4-line sentence block) -> `The customer platform is built and live in invitation-only beta: accounts, chat, native execution, browser tasks, billing and operations are delivered (see [BUILD_LOG.md](BUILD_LOG.md), [RELEASE_NOTES.md](RELEASE_NOTES.md), platform/OPERATIONS.md). Status of record: docs/codebase-audit/PRODUCTION_VERIFICATION_2026-10-29.md.`
  - Current: `Product Phase3 account build and targeted private boundaries now pass.` through `Next implementation phase4.` -> delete the three lines (stale; the phase-by-phase history is in BUILD_LOG.md).
  - Current: `Production services and\ndatabases were not changed.` (end of the "Read SERVER_DEPLOYMENT" paragraph) -> delete that sentence (it describes the Phase-0 audit session).

  `RUNBOOK.md`
  - Line 1-14 heading `## Customer-platform foundation and accounts — product Phases1–3` and the sentence `The temporary server smoke for product Phase2 was cleaned up; no persistent\nplatform listener/customer activation was installed.` -> `The customer platform is installed and live on the Hostinger VPS (agentai-platform-app, request-worker, cell-bridge, supervisor-native, browse, tool-relay, billing-worker, mail timer; list: platform/OPERATIONS.md section 12). Existing owner services (OpenClaw gateway, LiteLLM, PostgreSQL in /opt/openclaw-production) also remain.`
  - Line 36 `No account-layer live service exists yet.` -> delete.
  - Line 28-29 `Retention\nmaintenance/alerts are prepared, not scheduled:180-day minimal audit,90-day chat\nprojection tombstones.` keep but append ` (still not scheduled as of 2026-10-29; see P3-5)` until P3-5 lands.
  - Line 49 `Production belongs on the IONOS VPS and must work while the Mac is off.` -> `Production is the Hostinger VPS (179.236.71.203) and must work while the Mac is off. The former IONOS VPS (69.48.206.62) is retired.`
  - Line 96 `ssh -S openclaw-project/tmp/control-ui-ssh.sock -O exit root@69.48.206.62` -> `ssh -S openclaw-project/tmp/control-ui-ssh.sock -O exit lumina`
  - Line 427 `\`ssh -N -L 8000:127.0.0.1:8000 <ssh-user>@69.48.206.62\`` -> `\`ssh -N -L 8000:127.0.0.1:8000 lumina\``
  - Line 557 `\`ssh -L 18795:127.0.0.1:18795 <user>@69.48.206.62\`` -> `\`ssh -L 18795:127.0.0.1:18795 lumina\``

  `SERVER_DEPLOYMENT.md`
  - Line 9-10 `The owner already has an IONOS VPS at \`69.48.206.62\` with Ubuntu 24.04,\n2 vCPUs, 4 GiB RAM, and a 120 GiB disk.` -> `Historical: the first host was an IONOS VPS at 69.48.206.62 (retired). Production is now the Hostinger VPS srv2054170 (179.236.71.203). Read the rest of this file as the original deployment plan; the live layout is described in platform/OPERATIONS.md.` Keep the host-key fingerprint paragraph but prefix it with "(IONOS, historical)".

  `ARCHITECTURE.md`
  - Line 31 `Status: Phase 3 (trust-separated workers) is live on the IONOS VPS.` -> `Status (2026-10-29): the owner stack and the Lumina customer platform run on the Hostinger VPS. The paragraph below is the 2026-10-12 owner-stack status and is kept as history.`
  - Line 44 `The IONOS Ubuntu 24.04.4 VPS is \`69.48.206.62\`; SSH access works.` -> `The Hostinger Ubuntu VPS is \`179.236.71.203\` (\`ssh lumina\`); the former IONOS VPS (69.48.206.62) is retired.`

  `platform/OPERATIONS.md`
  - Line 161 sentence `In this version it **only records**; requests run exactly as before.` -> append ` This is the routing classifier only (jev_routing, off in production). The browser service has its own JEV decision path (\`--jev-mode live\`), described under "Browser".` (OP-015: JEV has two separate uses.)
  - No other change; the unit table at line 126-140 is correct. Add the 7 units ST-013 lists as unnamed (`agentai-billing-worker`, `agentai-ops-backup`, `agentai-ops-monitor`, `agentai-platform-app`, `agentai-platform-control`, `agentai-supervisor`, `agentai-tool-relay`) to the table with one line each (copy the `Description=` text of each unit in `platform/deploy/`).

  `plans/product/privacy.md`
  - Line 7 `The only host door is the model relay (10.77.0.1:4000).` -> `Cells reach the host through exactly two doors: the model relay (10.77.0.1:4000) and the tool relay for the browser tool (10.77.0.1:4100, agentai-tool-relay; verified in the live nft table and ufw 2026-10-29).`

  `deploy/README.md` (this is `$P/deploy/README.md`, the owner-stack compose guide, NOT `platform/deploy/`)
  - Line 19-20 `the older\n\`deploy/litellm.yaml\` draft is not mounted. Its API has no published host port.` -> `the older \`deploy/litellm.yaml\` draft is not mounted. The proxy is published on host loopback only (\`127.0.0.1:4000\`, \`deploy/docker-compose.production.yml:49\`) so the host model relay and cell bridge can reach it; nothing is published on a public interface.`

  `platform/deploy/README.md`
  - Lines 78-85: `Schedule \`retention_accounts\` every15min ... No schedule/worker was installed this phase.` -> keep until P3-5; then replace with the real unit/timer name.

  The other 10 tracked files naming `69.48.206.62` and the policy for each (`git ls-files | xargs grep -l 69.48.206.62`; 17 total):
  | File | Policy |
  |---|---|
  | `ARCHITECTURE.md`, `RUNBOOK.md`, `SERVER_DEPLOYMENT.md` | edit as above |
  | `plans/product/CLI_HANDOFF.md:124` | file removed 2026-10-29 (obsolete continuation prompt); no edit needed, so the list below is 16 live files |
  | `BUILD_LOG.md:1092,1545` | historical record: do NOT edit; add ONE line under the title: `> IP 69.48.206.62 in entries below is the retired IONOS host; production is 179.236.71.203 (Hostinger).` |
  | `bin/ssh-server:25`, `scp-server:24`, `activate-telegram.py:33`, `open-ops-dashboard.py:31`, `open-control-ui.py:27`, `owner-console.py:56` | code, owned by P1-14: replace `values.get(pfx + "HOST") or "69.48.206.62"` with `values.get(pfx + "HOST") or sys.exit("set OPENCLAW_NEW_SSH_HOST (or use ssh lumina)")` (use the file's existing exit idiom) |
  | `evidence/phase-4/20260926T220330Z/manifest.json`, `phase-5/.../manifest.json`, `phase-6/...`, `phase-7/...`, `phase-8/.../manifest.json` and `phase-8/.../summary.md` | evidence is immutable (checksummed records): do NOT edit; the banner in BUILD_LOG covers them |
  Replacement policy in one line: live host is Hostinger `179.236.71.203` reached with `ssh lumina`; prose uses the SSH alias, never the raw IP, except in historical records which get a banner instead of an edit.

  `/Users/parsa/AgentAI/CLAUDE.local.md` (PROPOSE ONLY; owner applies):
  - Current (line 19): `` `ServiceRouter.choose` shows 0 callers (`self.services.choose`), `` -> delete this clause; `ServiceRouter` and `routing/services.py` were deleted in commit `5db9636`. Replace with: `` `ChatDriver` still accepts a `services=` argument but nothing production passes one (P36 router era removed); `RequestWorker -> driver.execute` is missing from the graph. ``
  - Current (line 23): `(e.g. `platform/tests/test_service_handoff.py`)` -> replace with `(e.g. `platform/tests/test_request_worker.py`, `test_native_run.py`)`; `test_service_handoff.py` does not exist.
  - Add: `Production is the Hostinger VPS (ssh lumina); the IONOS IP 69.48.206.62 is dead.`
- **Current behaviour**: see quotes above (each quote was read from the file today).
- **Change**: apply each edit with `Edit` using the exact quoted string as `old_string`; if a quote no longer matches (file moved on), re-read the paragraph and keep the intent. One commit for docs, one for the `bin/` code (P1-14).
- **Tests to add/update**: add `platform/tests/test_docs_no_dead_host.py`: `git ls-files`-free (tests must not shell out to git): walk `$P` for `*.md`, `*.py`, `*.sh`, `*.service`, `*.conf`, `*.example`, skipping `evidence/`, `BUILD_LOG.md`, `node_modules`, `.venv`, and assert the string `69.48.206.62` does not occur (allowlist: files that carry the word `IONOS` on the same line or the retired banner). Regression case that fails before the fix: today `bin/ssh-server` and RUNBOOK fail it. Keep the allowlist in the test so adding a new mention is a conscious act.
- **Commands to run**: `rg -nF "69.48.206.62" /Users/parsa/AgentAI/openclaw-project --glob '!evidence' --glob '!BUILD_LOG.md'` should be empty (or only banner lines); `cd $P/platform && .venv/bin/python -m unittest tests.test_docs_no_dead_host`.
- **Acceptance criteria**: rg above clean; README no longer claims "Next implementation phase4"; privacy.md names both doors.
- **Rollback**: `git revert` (docs only).
- **Risks**: do not "correct" statements you cannot verify (for example the exact container list on the host); quote the audit doc instead. Do not touch `evidence/`.
- **Do not**: do not edit `CLAUDE.local.md`, `evidence/**`, `BUILD_LOG.md` bodies, or `docs/orchestration-audit/*` (bannered Historical).
- **Commit message**: `Docs: current host, platform status, relay doors, LiteLLM port; retire IONOS references (M-11, ST-014, IS-015, AG-016, OP-015)`

---

## P3-3: accounts.env.example generated from the code, with a test

- **Findings**: M-09, BE-015, IS-007. **Finding check**: re-verified with a different count. `platform/accounts/settings.py` reads 38 distinct `AGENTAI_*` names through `os.environ.get('...')`; `platform/deploy/accounts.env.example` documents 8 (`AGENTAI_SESSION_SECRET, STATE_DIR, PUBLIC_ORIGIN, MAIL_ENABLED, SMTP_HOST, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL`), so **30 names in settings.py are undocumented** (the audit's "23" is an earlier/other count); one more app-side name lives outside settings (`AGENTAI_SIGNUP_SETTINGS_FILE`, `lifecycle/capacity.py:8`), making **31** for the `accounts.env` universe. The "2 documented-but-unread" are `AGENTAI_CARD_IMAGES` and `AGENTAI_BRAVE_IMAGE_KEY_FILE`: they are NOT in the example file; they appear only in `platform/OPERATIONS.md:198` (explicitly as switches that "have been re[moved]") and `RELEASE_NOTES.md:193`. No code reads them (`rg` over code finds nothing). So the real drift is 31 undocumented names and zero stale names in the example; do not delete those two doc mentions without reading line 198 in context.
  The 30 undocumented in settings.py: `ARTIFACT_SIGNING_KEY, BILLING_ALLOW_LIVE, BILLING_API_VERSION, BILLING_PLAN_FILE, BILLING_PRICE_ID, BILLING_PUBLIC_ORIGIN, BILLING_SECRET_KEY_FILE, BILLING_WEBHOOK_SECRET_FILE, BROWSE_SOCKET, CELL_BRIDGE_SOCKET, CUSTOMER_RESERVATION_MICROUSD, GOAL_CHAIN_LIMIT, LIVE_PATH, LIVE_SECRET_FILE, ROUTING_CONFIG_FILE, SAFETY_OWNER_ACCOUNT, SAFETY_SNAPSHOT, SERVICE_ALLOCATION_MICROUSD, STORAGE_DIR, SWITCHES_FILE, SWITCH_FACTS_FILE, TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME, TELEGRAM_WEBHOOK_SECRET, TOOL_RELAY_BIND, TOOL_RELAY_PORT, TYPESAFE_KEY_FILE, UI_BUNDLE_DIR, UPLOADS_ENABLED, VAULT_KEY_FILE` (all prefixed `AGENTAI_`).
  Other-process names (not in `accounts.env`): gateway `LIVE_FRAMES_ROOT, LIVE_SECRET_FILE, LIVE_HOST, LIVE_PORT, AGENTAI_LIVE_SECRET` (`live/gateway.py:143-148`); dev only `LOCAL_UI_PORT, DJANGO_SETTINGS_MODULE` (`dev_local_ui.py`); deploy checks `DOCKER_HOST, AGENTAI_PLATFORM` (`deploy/p4_*.py`); plus `DOCKER_HOST` is injected, not read from the file (`cell_bridge_main.py:55`).
  **Naming collisions** (document, do not rename production vars): (a) live-frame secret has three spellings: app `AGENTAI_LIVE_SECRET_FILE` (settings.py:120), gateway `LIVE_SECRET_FILE` and `AGENTAI_LIVE_SECRET` (gateway.py:144-145). Fix: make `gateway.py` read `AGENTAI_LIVE_SECRET_FILE` first and fall back to the two old names (back-compat; the live unit may be using the old name, which is hand-installed on the server and UNVERIFIED), then document only the new name. (b) Telegram token has three different tokens with similar names: `OPENCLAW_TELEGRAM_BOT_TOKEN` (local `.env` consumed by `bin/activate-telegram.py:29`, the owner/operator bot that script wires into the customer env), `AGENTAI_TELEGRAM_BOT_TOKEN` (customer bot, `accounts.env`, `settings.py:79`), and `TELEGRAM_BOT_TOKEN` (owner OpenClaw secret store name in `deploy/README.md:109`). Put a 3-row table in the example file's comments; do not rename.
- **Goal**: an operator can build a correct `/etc/agentai-platform/accounts.env` from the example alone, and a CI test fails when code starts reading an undocumented variable.
- **Depends on / blocks**: needs P3-1 to run the test in CI. Independent otherwise. **GATE**: none (no behaviour change except the gateway alias, which is additive).
- **Files to change**: new `platform/deploy/gen_env_example.py`; regenerate `platform/deploy/accounts.env.example` (currently 12 lines); new `platform/tests/test_env_example.py`; `platform/agentai_platform/live/gateway.py:143-146` (alias). **Read first**: `accounts/settings.py` (whole, 134+ lines), `lifecycle/capacity.py:8`, `deploy/agentai-platform-app.service:8` (`EnvironmentFile=`), the other `.service` files that use `EnvironmentFile`.
- **Current behaviour**: `accounts.env.example` has the 8 names above and a "never commit a filled version" header. `settings.py:6-134` reads the rest with patterns like `os.environ.get('AGENTAI_TOOL_RELAY_PORT', '4100')`.
- **Change**:
  1. `gen_env_example.py` (stdlib only, `ast` based, no imports of Django): (a) `names_read(paths)` walks `accounts/settings.py`, `accounts/**/*.py` (non-test), `agentai_platform/**/*.py` (non-test) and returns `{name: [(file, line, default_expr_or_None)]}` for calls `os.environ.get(<str literal>[, default])`, `os.environ[<str literal>]`, `os.getenv(<str literal>[, default])`; a non-literal first argument is recorded under the key `'<dynamic>'` and makes `--check` fail unless allowlisted. (b) A table `DOC = {NAME: (section, one_line_help, kind)}` in the script holds the human text and `kind in {'secret','path','flag','int','text'}`. (c) `render()` emits the file: header (keep the existing two header lines), then sections (Core, Mail, Storage and artifacts, Switches, Execution wiring, Browser and live view, Billing, Telegram, Safety and vault, Routing/JEV). Every variable is a commented line `# AGENTAI_X=<default>   # help` except the 3 required ones (`SESSION_SECRET`, `STATE_DIR`, `PUBLIC_ORIGIN`) which stay uncommented as today. Secrets and key files are shown as `REPLACE_ME`/path placeholders, never real values. (d) `--check` exits 1 and prints a diff if the committed file differs from `render()`; `--write` rewrites it. The script refuses to render a name that has no `DOC` entry (this is what forces new variables to be documented).
  2. Defaults come from the code (`default_expr` printed with `ast.unparse`), so the "diverging defaults" part of M-09 disappears: example defaults == code defaults by construction.
  3. Add `AGENTAI_SIGNUP_SETTINGS_FILE` and a "process-specific variables" footer listing the gateway and dev names above (comment only).
  4. `gateway.py`: `secret_file = os.environ.get('AGENTAI_LIVE_SECRET_FILE') or os.environ.get('LIVE_SECRET_FILE')`; leave the `AGENTAI_LIVE_SECRET` fallback unchanged.
  5. `test_env_example.py` (see below). Run `python platform/deploy/gen_env_example.py --write` once and review the diff by eye before committing.

```diff
--- a/platform/agentai_platform/live/gateway.py
+++ b/platform/agentai_platform/live/gateway.py
@@ -144 +144 @@
-    secret_file = os.environ.get('LIVE_SECRET_FILE')
+    secret_file = os.environ.get('AGENTAI_LIVE_SECRET_FILE') or os.environ.get('LIVE_SECRET_FILE')   # LIVE_SECRET_FILE is the old unit spelling
```
- **Tests to add** (`platform/tests/test_env_example.py`, `unittest`, stdlib only; locate the repo with `Path(__file__).resolve().parents[1]`):
  - `test_every_name_the_code_reads_is_in_the_example`: `names = gen.names_read(...)`; `text = Path('deploy/accounts.env.example').read_text()`; for each name except those in `PROCESS_SPECIFIC` (the gateway/dev/deploy-check set, kept in the script), `assertRegex(text, rf'(?m)^#?\s*{name}=')`. Regression: fails today with 31 names listed.
  - `test_the_example_names_nothing_the_code_does_not_read`: every `^#?\s*(AGENTAI_[A-Z0-9_]+)=` in the example is in `names_read` or in `PROCESS_SPECIFIC` or in `RETIRED = set()`. Today passes (no stale names); guards the future.
  - `test_the_generated_file_is_the_committed_file`: `render()` equals the file (so edits to settings.py force a regenerate).
  - `test_no_dynamic_env_reads_unreviewed`: `'<dynamic>'` not in names (or only the allowlisted file:line).
  - `test_secret_placeholders_only`: no line in the example matches `=[A-Za-z0-9+/_-]{24,}$` (no real-looking secret).
- **Commands to run**: `cd $P/platform && .venv/bin/python deploy/gen_env_example.py --check` (non-zero before the regen), `--write`, `--check` (0); `.venv/bin/python -m unittest tests.test_env_example tests.test_live`; `AGENTAI_...` env set as in P3-1 then `manage.py test accounts` (settings unchanged).
- **Acceptance criteria**: example lists all 31 names with help text; test red before, green after; adding `os.environ.get('AGENTAI_NEW')` to settings.py without docs turns the test red.
- **Rollback**: `git revert`; the old 12-line example returns. The gateway alias is additive, so revert is also safe.
- **Risks and edge cases**: `ast` cannot see names read via helper wrappers (for example `_env('X')`); `rg "_env\w*\("` in `platform/` first and teach `names_read` any wrapper that exists (today there is none in settings.py). Do not import `settings.py` to introspect (it raises `ImproperlyConfigured` on partial config, `settings.py:82-96`). Defaults that are computed (`str(STATE_DIR / 'safety-switches.json')`) print as the expression text; that is intended.
- **Do not**: do not put real values, hostnames of the owner's server or filled secrets in the example; do not rename production variables; do not read `/etc/agentai-platform/accounts.env` (it is a server secret file).
- **Commit message**: `Generate accounts.env.example from the code and test that every env name is documented (M-09, BE-015, IS-007)`

---

## P3-4: single ChatService factory, auth/rate preamble, task.create on chat_send, Telegram finish-or-hide

- **Findings**: BE-024, BE-017, BE-007. **Finding check**: re-verified. `ChatService(` is constructed in 5 places: `accounts/chat.py:57` (the only one with `pricer`, `execution`, `browse`, `events`, `gateway_factory`, `require_cell`, `service_limit_microusd`), `accounts/telegram.py:31`, `accounts/management/commands/telegram_worker.py:17`, `accounts/files.py:47`, `accounts/views.py:252` (`projects` POST). The four others build a bare `ChatService(store, queue=RequestQueue(store), ledger=BudgetLedger(store))`: no pricer (so a send "waits unfunded", `chat.py(agentai_platform):250`), no gateway, no `require_cell`. For `files.py`/`views.projects` that is harmless today (they call project/file methods, not `send`); for Telegram it is the actual reason BE-007 cannot complete in production. BE-017: `chat_send` (`accounts/chat.py:165-189`) has no `rate('task.create', ...)`; `chat_goal` (line 198) and `chat_retry` (line 266) do (`rate('task.create', request.account_id, 30, 3600)`).
- **Goal**: one place builds the service; omissions like BE-017 and BE-007 stop being possible by copy-paste.
- **Depends on / blocks**: after P1-1/P1-7 (they edit `chat.py`/`views.py`). **GATE (two questions)**: (1) *task.create on chat_send* is a **new per-task limit on the main path** (30 sends per hour per account). The owner's standing rule is "no new per-task limits", so the question is: "Do you want chat_send capped at 30 messages/hour/account like goal and retry are, or should goal/retry be left alone and chat_send stay uncapped?" Default if unanswered: do NOT add the cap; implement only the shared decorator and a comment. (2) *Telegram*: finish it or hide it (options below).
- **Files to change**: new `accounts/wiring.py`; `accounts/chat.py:28-62` (factory moves, names re-exported); `accounts/telegram.py:25-35`; `accounts/management/commands/telegram_worker.py:14-20`; `accounts/files.py:41-52`; `accounts/views.py:240-256`; tests `accounts/test_chat.py`, `test_telegram.py`, `test_files.py`. **Read first**: those ranges plus `accounts/services.py:25-34` (`rate`), `accounts/views.py:94-97` (`customer`), `agentai_platform/telegram.py:62-125,277-312`.
- **Current behaviour**: `accounts/chat.py:46-58`
  `def service(): ... live = execution_on(); browse = browse_on(); kwargs = {'pricer': FixedRoute(...)} if live else {} ... return ChatService(store, queue=RequestQueue(store, require_cell=live), ledger=BudgetLedger(store, service_limit_microusd=... if live else None), execution=live, browse=browse, events=EventService(store), gateway_factory=gateway, **kwargs)`
  and `accounts/telegram.py:30-35`: `TelegramService(store, chat=ChatService(store, queue=RequestQueue(store), ledger=BudgetLedger(store)), transport=TelegramBotApi(...) if settings.TELEGRAM_ENABLED else None, ...)`. Every view starts with `denied = customer(request); if denied: return denied`.
- **Change**:
  1. `accounts/wiring.py` (no import of `.views` to avoid a cycle; `chat.py` imports `.views` today):
```python
"""The one place that wires services for the web process."""
from django.conf import settings
from django.db import connection
from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatService, FixedRoute
from agentai_platform.events import EventService
from agentai_platform.request_queue import RequestQueue
from .lifecycle import AccountStore

def store(): return AccountStore(connection.settings_dict['NAME'])

def chat_service(*, live=None, browse=None):
    # body = today's chat.service(), with execution_on()/browse_on() still defaulting from SwitchStore
    ...
```
  2. `chat.py`: keep `execution_on`, `browse_on` there (tests and `api.py:24`, `requests.py:13` import them); replace the body of `service()` with `return wiring.chat_service(live=execution_on(), browse=browse_on())` and keep the name `service` in the module (tests patch `accounts.chat.service`, `genui.py:7` imports it).
  3. `telegram.py`, `telegram_worker.py`, `files.py`, `views.projects`: use `wiring.chat_service()` instead of the bare constructor. Behaviour change check: for `files.py` and `projects` nothing observable changes except that `RequestQueue(require_cell=live)` is now set (affects only `claim`, not these paths) and an extra `SwitchStore` file read per call (cheap). Do this as its own commit with the full `manage.py test accounts` run.
  4. Preamble decorator in `accounts/views.py` next to `endpoint`: `def customer_endpoint(methods, fields=(), *, rate_scope=None, limit=None, window=3600, **kw)` that applies `endpoint(...)`, then `denied = customer(request)`, then (if `rate_scope`) `rate(rate_scope, request.account_id, limit, window)`. Convert ONLY the Telegram and chat views whose preamble is exactly the 3-line pattern (leave anything with custom ordering alone; `files.py:_guard` is richer, leave it). This is a mechanical change; one commit; no behaviour change (`Limited` -> 429 handled by `endpoint`/middleware as today: confirm by reading `endpoint` first).
  5. BE-017 (only if the owner says yes): in `chat_send` after `customer()`: `rate('task.create', request.account_id, 30, 3600)` placed before `service().send`, **after** the steering path decision? Read `ChatService.send` first: a steered send (`chat.py(agentai_platform):305`, "steered") is not a new task and must not consume the cap. So the cap belongs inside the service path that creates a task, not in the view. Implementation: pass a `before_task=` callback from the view into `send(...)` or check `result['admission'] != 'steered'` is impossible after the fact; therefore prefer the owner-"no" default and document.
  6. **Telegram options**. *Option A, finish*: (i) `telegram.service()` uses `wiring.chat_service()` so inbound messages get a pricer and `require_cell`; (ii) add a result relay: when `RequestWorker._run` finishes a request whose conversation is bound to Telegram, enqueue the reply into `telegram_outbox` via `TelegramService._reply` (new hook `on_finish(claim, receipt)` on `RequestWorker`, default none; the Telegram wiring sets it). Privacy point to put to the owner: this copies assistant output to Telegram's servers; the privacy page must say so before activation. (iii) add `deploy/agentai-telegram-worker.service` + `.timer` that run `manage.py telegram_worker --drain` every 30 s as `agentai-platform` with the same hardening block as `agentai-billing-worker.service`; (iv) a React link UI in `lumina` (none exists). Effort L; do not start before the owner decides it ships. *Option B, hide (recommended now)*: keep code and routes; assert in a test that with `TELEGRAM_ENABLED=False` (the default when `AGENTAI_TELEGRAM_*` are unset, `settings.py:82-90`) `/v1/account/telegram/link` returns 503 `telegram_not_enabled`, the webhook returns 403, `features.telegram` is false in `/v1/app`, and the account overview context has no Telegram block. Update `INCOMPLETE_FEATURES.md` status line. Before choosing B on production, the owner confirms (read-only) that `AGENTAI_TELEGRAM_BOT_TOKEN` is absent from `/etc/agentai-platform/accounts.env` (`grep -c '^AGENTAI_TELEGRAM_BOT_TOKEN=' ... ` prints a count, not the value).
- **Tests to add/update**:
  - `accounts/test_chat.py::WiringChecks.test_all_services_come_from_one_factory`: `override_settings` + monkeypatch `accounts.wiring.chat_service` with a recorder and call `files._services()`, `views.projects` POST, `telegram.service()`; assert the recorder was hit 3 times (fails before: each builds its own).
  - `accounts/test_chat.py::test_service_still_prices_when_execution_is_on` : existing tests (line 125 patches `accounts.chat.service`, line 181 uses `SERVICE_ALLOCATION_MICROUSD`) must pass unchanged; add one asserting `service().pricer` is a `FixedRoute` when the switch file has `customer_execution` on, and `UnmeasuredRoute` when off.
  - `accounts/test_telegram.py::test_link_is_unavailable_while_disabled` (Option B) as described.
  - If BE-017 is approved: `test_chat_send_hits_the_hourly_task_cap` (31st send in one window -> 429, steered send does not count). Otherwise `test_chat_send_has_no_hourly_task_cap_by_decision` documenting the decision (so nobody adds it silently).
- **Commands to run**: `cd $P/platform && AGENTAI_SESSION_SECRET=... AGENTAI_STATE_DIR=$(mktemp -d) AGENTAI_PUBLIC_ORIGIN=https://localhost .venv/bin/python manage.py test accounts.test_chat accounts.test_telegram accounts.test_files accounts.test_genui accounts.test_requests`; `.venv/bin/python -m unittest tests.test_chat tests.test_telegram tests.test_files`.
- **Acceptance**: `rg -n "ChatService\(" platform/accounts` shows only `wiring.py`; Telegram state is explicit and tested; no behaviour change on `/v1/conversations/*/send` for a normal send.
- **Rollback**: `git revert` per commit (factory, preamble, Telegram are separate commits).
- **Risks**: import cycle `chat.py` <-> `views.py` <-> `wiring.py`; `wiring.py` must import only `.lifecycle` and `agentai_platform`. `files._services()` is called per request; do not cache the service across requests (switch file changes must apply live). Hidden trap: `accounts/genui.py:7` binds `service` at import, so patching `accounts.chat.service` in tests does not reach genui views (pre-existing).
- **Do not**: do not add a cap to steered sends; do not send customer text to Telegram before the owner accepts the privacy wording; do not enable Telegram in production as part of this task.
- **Commit message**: `Wire ChatService in one factory, share the customer/rate preamble, decide Telegram state (BE-024, BE-017, BE-007)`

---

## P3-5: retention timer

- **Findings**: BE-011, BG-005 (tickets), BG-028 (prune_expired). **Finding check**: re-verified and sharpened. `accounts/management/commands/retention_accounts.py` (35 lines) is scheduled by nothing (`platform/deploy/*.timer`: billing-worker, ops-backup, ops-monitor, platform-mail only; README says "No schedule/worker was installed"). What it actually does in one transaction: deletes expired `ActionToken`, `RateBucket`, `Session` rows, `EmailJob` older than 180 days, `Audit` (`accounts_audit`) and `audit_events` older than 180 days (it drops and recreates the append-only triggers inside the transaction), writes a `Tombstone` per conversation whose `created_at` is older than 90 days **and deletes only that conversation's `events` rows**, then deletes all `events` older than 30 days. **It never deletes `chat_messages`, `conversations`, `tasks`, `customer_requests`, `data_blocks`, `download_tickets`, `event_streams` or `telegram_outbox` rows.** The contract says (`/Users/parsa/AgentAI/product/CONTRACT.md:147-149`) chat/task summaries are kept "90 days rolling". So today customer message text (`chat_messages.content`, up to 16 000 chars each; no delete trigger on it, verified in `migrations/0005`/`0006`) is retained forever in the hot DB and in every backup. This is the largest privacy gap in this file. Also the cutoff uses `conversations.created_at`, so an active old conversation loses its events while still in use.
- **Goal**: a defined, tested, scheduled retention that matches the contract once the owner settles the open questions; until then, a dry-run that tells the owner exactly what would be deleted.
- **Depends on / blocks**: needs the owner's retention contract answers (GATE); independent of other tasks. Deleting customer data is irreversible: **no unit is enabled and no non-dry run happens without the owner's explicit yes.**
- **GATE: questions for the owner (ask verbatim)**:
  1. "Chat messages: delete a conversation's messages 90 days after its LAST activity, after its creation, or only when the customer deletes it?" (Recommendation: 90 days after last message, because creation-based cutoffs delete live conversations.)
  2. "What should a customer see for a conversation past retention: an empty conversation, or it disappears from the list?" (Recommendation: it disappears; keep a `tombstone` so restores do not resurrect it, as `ops/restore.py:109-111` already honours.)
  3. "Do tasks/requests/results (`customer_requests.message`, `.result`, `tasks`) follow the same 90 days?" (They contain the same text. Recommendation: yes: blank `message`/`result` and keep the metadata rows for billing/ledger integrity.)
  3b. "Other tables hold customer-derived text too (names verified in `migrations/*.sql`): `chat_deliveries`, `ui_blocks`/`data_blocks`, `browse_runs`/`browse_steps` (goal, URLs), `gen_artifact_state`/`gen_artifact_events`, `route_decisions`, `telegram_outbox`, `saved_choices`. Which of them follow the 90 days?" (Recommendation: all except `saved_choices` and `vault_items`, which are customer-managed and deleted by the customer. Read each table's columns with `sqlite3 -readonly <copy of db> '.schema <table>'` on a COPY before writing the deletes; column names in this spec are indicative.)
  4. "Artifacts and uploaded files follow the contract line 'until customer/project deletion or 30 days after subscription end': confirm they are NOT touched by this timer."
  5. "Backups hold deleted data for up to 30 days (contract line 'Backups'); confirm that is acceptable and that restores re-apply tombstones (already built)."
  6. "Run time and cadence: daily 03:10 UTC, after the 03:40 backup or before it?" (Recommendation: before the backup so the backup carries less data: 03:10.)
- **Files to change**: `accounts/management/commands/retention_accounts.py`; new `platform/deploy/agentai-retention.service` and `agentai-retention.timer`; `platform/deploy/README.md:78-85`; tests `accounts/test_ops.py` or new `accounts/test_retention.py`. **Read first**: the command (whole), `accounts/models.py:47` (`Tombstone`), `ops/restore.py:100-125`, `deploy/agentai-billing-worker.service` + `.timer` (the template to copy), `migrations/0005_chat_transcript.sql`, `0006_telegram_ingress.sql` (column names; the live table is `chat_messages` rebuilt in 0006).
- **Change**:
  1. Add `--dry-run` (default for an interactive run; the timer passes `--apply`): every delete becomes a `SELECT count(*)` and the command prints a JSON line of counts per table (counts only, no ids, no text). Same transaction structure; dry-run writes no audit row of kind `completed`.
  2. Add the new deletions behind answers 1-3, as ordered statements inside the existing `with connection.cursor()` block: find `old = SELECT account_id,id FROM conversations WHERE <last_activity> < cutoff` (last_activity = `coalesce((SELECT max(created_at) FROM chat_messages m WHERE m.account_id=c.account_id AND m.conversation_id=c.id), c.created_at)`), tombstone each, `DELETE FROM chat_messages WHERE account_id=? AND conversation_id=?`, blank `customer_requests.message/result` for that conversation (if answer 3 yes), delete `data_blocks`/`ui_blocks` for it, and `DELETE FROM download_tickets WHERE expires_epoch < now-86400` (BG-005) and `event_streams` closed older than 1 day. Use batches (`LIMIT 500` loop) so the SQLite write lock is held briefly; the web app shares the DB.
  3. Replace the raw `events` delete with `EventService.prune_expired` or delete that function (BG-028): pick the call (one implementation).
  4. Unit (copy of the billing worker's hardening block, `User=agentai-platform`, `ReadWritePaths=/var/lib/agentai-platform`, `MemoryMax=96M`, `ExecStart=/opt/agentai-platform/current/.venv/bin/python manage.py retention_accounts --apply`) and `agentai-retention.timer` (`OnCalendar=*-*-* 03:10:00`, `Persistent=true`, `RandomizedDelaySec=5m`). Not in `release.py`'s probe set; add a monitor check later (BG-024 style) that the last run is < 36 h.
- **Procedure (dry-run first, all steps TEXT for the owner)**:
  1. Deploy the code via `release.py` (P0-3 first). 2. Owner runs on the server, as the app user, read-only: `cd /opt/agentai-platform/current && set -a && . /etc/agentai-platform/accounts.env && set +a && sudo -u agentai-platform -E .venv/bin/python manage.py retention_accounts --dry-run` (the owner sources the env file themselves; the AI must not). 3. Compare counts to expectations (with 8 accounts and 137 requests the numbers are tiny; anything surprising stops the rollout). 4. Take a backup (`ops backup`), run `--apply` once by hand, run `ops monitor`, spot-check one old conversation is gone and a recent one intact. 5. `systemctl enable --now agentai-retention.timer`. 6. Next morning verify `journalctl -u agentai-retention` shows the count line and no error.
- **Tests to add** (`accounts/test_retention.py`, Django `TestCase`; build the rows with the same raw SQL the existing retention test at `accounts/tests.py:301-303` uses):
  - `test_dry_run_deletes_nothing_and_reports_counts` (insert 1 old + 1 new conversation with messages; run `call_command('retention_accounts', '--dry-run')`; assert both conversations' messages still present and output JSON has `chat_messages > 0`). Fails before (no flag).
  - `test_apply_removes_messages_of_an_old_conversation_but_not_a_recent_one` and `test_an_old_conversation_with_a_recent_message_is_kept` (cutoff by last activity).
  - `test_other_accounts_are_untouched`; `test_tombstone_written_once_and_restore_skips_it` (call twice; then `restore` helper test in `tests/test_ops_restore.py` style asserts `skipped_tombstoned_conversations`).
  - `test_no_customer_text_in_command_output` (assert the output does not contain the inserted message text).
  - `test_audit_trigger_is_restored_after_failure` (force an exception mid-run, assert `SELECT sql FROM sqlite_master WHERE name='identity_audit_no_delete'` still exists).
- **Commands**: `manage.py test accounts.test_retention accounts.tests`; `.venv/bin/python -m unittest tests.test_ops_restore`; `systemd-analyze verify platform/deploy/agentai-retention.service platform/deploy/agentai-retention.timer` (on a Linux box; if unavailable say so).
- **Acceptance**: dry-run output reproducible; apply deletes only what the owner's answers allow; unit passes `systemd-analyze verify`; README updated.
- **Rollback**: `systemctl disable --now agentai-retention.timer`; `git revert`; deleted data is recoverable only from backups (30 days), which is why the dry run and a pre-run backup are mandatory.
- **Risks**: the command drops two append-only triggers inside a transaction (relies on SQLite transactional DDL; keep that structure and its failure test); a long transaction blocks web writes: batch it; the `Audit` Django model and `audit_events` are different tables; `events` rows referenced by `gen_artifact_events` cursors may make an expired cursor return a summary (documented in the contract).
- **Do not**: never enable the timer before the dry-run review; do not delete `provider_receipts`, `usage_entries` or `accounts_audit` rows younger than 180 days (financial/audit); do not log message text or ids with text; do not apply a shorter cutoff than the contract without the owner's written yes.
- **Commit message**: `Retention: dry-run, delete chat messages per contract, tickets/streams; add retention timer unit (BE-011, BG-005, BG-028)`

---

## P3-6: dead-symbol cleanup (final safe list only)

- **Findings**: ST-012, AG-015, FE-003. **Finding check**: every candidate re-verified with `rg`/`grep -rnw` over `platform/`, `lumina/src` (including tests), `deploy`, and string registries. Most candidates are NOT safe; the list below is the complete final decision.
- **Goal**: remove only what is provably unused; no behaviour change.
- **Depends on**: P0-3 (the `tool_relay.py` file is uncommitted today). **GATE**: none for the SAFE list; owner for the DECIDE list.
- **SAFE to remove (verified)**:
  | Item | Evidence | Edit |
  |---|---|---|
  | `import hmac` at `platform/agentai_platform/tool_relay.py:14` | `grep -n hmac` finds only the import line | delete the line (do after P0-3 commit; re-grep first because the file is being edited) |
  | `RequestDataTooBig, TooManyFieldsSent` in `platform/accounts/middleware.py:7` | `grep -n` finds only the import line; no test references them | change to `from django.core.exceptions import SuspiciousOperation` (keep `SuspiciousOperation`, it is used at line ~30) |
  | `activity_mod` alias at `platform/agentai_platform/chat_driver.py:20` | `from . import activity as activity_mod, outcome as outcome_mod`; `rg activity_mod` finds only that line, no test patches it | `from . import outcome as outcome_mod` (keep `outcome_mod`; confirm it is used with `rg outcome_mod chat_driver.py`) |
  | local `from django.contrib.auth.models import AnonymousUser` at `platform/accounts/views.py:88` | the only occurrence in the file | delete the line |
  | `Plus` in `lumina/src/components/Icons.tsx:20` | only definition; Icons is consumed as `import * as I` but no `I.Plus`, no `I[...]` dynamic access (`grep -rnE "\bI\["` empty) | delete the export |
  | `safeAssetSrc` in `lumina/src/gen/safety.ts:44` | no reference anywhere; its default base `/v1/files/content?path=` is not a backend route (ORPHANED_CODE sec. 2) | delete the function (and any now-unused import in that file) |
  | `implementedTypes` (`gen/manifest.ts:246`), `rendererKeys` (`gen/registry.ts:70`) | no references in src, tests or python | delete both exports |
  | `LAYOUT`, `STATES`, `RESPONSIVE` (`gen/variants.ts:7,11,12`) | referenced only at their definition (other variants constants ARE used: `DENSITY`, `EMPHASIS`, `EXPANSION`, `INTERACTION`, `SIZE`, `APPEARANCE`) | delete the three constants; also drop the type aliases `Emphasis/Expansion/Interaction` (lines 17-19) only if `rg -w` shows no importer (it showed none) |
  | `gen/schemas.ts` types `Layout` (line 44) and `RawDocument` (line 185) | type-only, no importer | delete both `export type` lines |
- **NOT safe (do not remove; reasons)**:
  - `gen/components/visuals.tsx` default export `Visuals`: loaded by `React.lazy(() => import('./visuals'))` in `gen/components/extended.tsx:14` and `.Graph` at line 111. A name-based tool calls it unused; it is live.
  - `browse/service.py:146 start_picker=None` and `lifecycle/profiles.py:38 running_cells=0`: they are keyword parameters of public constructors/functions (the latter documented in its docstring); removing breaks callers and tests. Leave.
  - `accounts/delivery.py:5 email_messages`: required by Django's `BaseEmailBackend.send_messages(self, email_messages)` signature. Leave.
  - `server.py:96 signum`: signal-handler signature. Leave.
  - About 40 test-only exports (`protocol.ts` `splitReply/parseFence/EnvelopeStream`, `registry.ts` `modelCatalog/compactCatalog/schemaSummary/OFFERED`, `lib/safety.ts` `canSet/requestBody`): keep (FE-005: the model-prompt plumbing awaits a caller). 
- **DECIDE (owner)**: `GoalChain.limit` (`agentai_platform/goals.py:25-26`, passed by `accounts/management/commands/request_worker.py:45` as `limit=settings.GOAL_CHAIN_LIMIT`). Verified: `GoalChain` never reads `self.limit`; the real cap is `ChatDriver.goal_chain_limit` from the constant `GOAL_CHAIN_LIMIT = 20` (`chat_driver.py:38,59,625`). So `AGENTAI_GOAL_CHAIN_LIMIT` (settings.py:118) is a knob that does nothing; the operator who sets it believes they changed the cap. Options: (A) delete the parameter, the settings line and the env doc (honest); (B) wire it: pass `goal_chain_limit=settings.GOAL_CHAIN_LIMIT` into the `ChatDriver(...)` in `request_worker.py:39` (makes the knob real; default 20 so no change). Question: "Should AGENTAI_GOAL_CHAIN_LIMIT really control the goal-turn cap (B), or be removed (A)?" Recommendation: B (preserve intent, no new limit: the default stays 20).
- **Change**: one commit per language. After each edit re-run the greps listed under Evidence (they are the acceptance test).
- **Tests**: no new tests. Existing suites must stay green. Add nothing that mentions the removed names. Frontend: `npx tsc --noEmit && npx vitest run && npm run build`. Python: `manage.py test accounts` + `unittest tests.test_chat tests.test_tool_origin tests.test_browser_tool tests.test_native_run`.
- **Acceptance**: `rg -n "hmac" platform/agentai_platform/tool_relay.py` shows no import; tsc/vitest/build green; the NOT-safe list untouched.
- **Rollback**: `git revert`.
- **Risks**: `outcome_mod` removal of the wrong alias would break `chat_driver.py` at import time: run `python -c "import agentai_platform.chat_driver"` from `$P/platform` with the venv. vulture's 60%-confidence class hits are not trustworthy; ignore them.
- **Do not**: do not run a bulk vulture/ts-prune "fix"; do not delete `routing/*`, `gen/legacy.tsx`, or any orphaned product module (P4-8).
- **Commit message**: `Remove verified-unused imports and exports (ST-012, AG-015, FE-003)`

---

## P3-7: resource hygiene

- **Findings**: AG-011, AG-012, AG-013, FE-007, FE-008, FE-009, BG-021. **Finding check**: re-verified. (a) `BrowseService.jobs` (`browse/service.py:155`) is a plain dict filled at line 172 and never popped; `purge()` (line ~447) removes screenshot folders for finished jobs but keeps the `Job` objects (each holds `events`, `trace`, prefs); `_account_slots` (line 152, 501) gains one semaphore per account forever. (b) `ShadowRouter.before` (`routing/shadow.py:42-52`) is called on every claim including re-claims after `Defer` (`request_worker.py:64-65`), so a deferred request re-classifies each time; `_started/_threads` are only popped in `after()` which `_run` calls only for finished requests (`request_worker.py:82-83`), so Parked/Defer/exception leak entries. Switch `jev_routing` is OFF in production, so impact is latent. (c) `_reconcile_usage` (`chat_driver.py:749-783`) loops `self.sleep(self.pause)` until the provider spend "holds still" or `usage_wait=45` s, all while the single global slot is held (the caller is on the claimed request). (d) Frontend pollers: `state/data.tsx:54` already skips when `document.visibilityState !== 'visible'`; these do not: `pages/Chat.tsx:59` (2.5 s), `components/AgentThinking.tsx:33` (2.5 s), `lib/useActivity.ts:23` (1.5 s), `gen/ChatBridge.tsx:71`, `pages/Tasks.tsx:19` (4 s), `pages/Live.tsx:45`. (e) N+1: `pages/Chat.tsx:71-76` and `pages/Files.tsx:18-19` call `GET /v1/projects` then `GET /v1/projects/<id>/files` per project on every message or working change.
- **Goal**: bounded memory in the root browse process, no duplicate classifier calls, no tab polling when hidden, fewer requests. No new limits on customers.
- **Depends on**: after P1-9 (touches `chat_driver`), independent of P3-4. **GATE**: for (c) only: "OK to cap the post-run usage wait at 15 s while another account is waiting (owner-visible effect: a few seconds earlier release of the lane; the receipt falls back to the reserved upper bound if spend has not appeared)?" Default: do (a),(b),(d),(e); leave (c) as is until answered because it changes how a charge is computed.
- **Files to change**: `browse/service.py:152-175,420-460,501`; `routing/shadow.py:42-52,77-90`; `request_worker.py:60-90`; `chat_driver.py:749-783`; `lumina/src/lib/usePoll.ts` (new), `pages/Chat.tsx`, `AgentThinking.tsx`, `useActivity.ts`, `ChatBridge.tsx`, `Tasks.tsx`, `Live.tsx`, `Files.tsx`; backend `accounts/files.py` (new aggregate route) + `urls.py` + `openapi.json`. **Read first**: those ranges, `tests/test_browse_service.py` (purge tests near line 280-295), `tests/test_request_worker.py`, `lumina/src/lib/api.ts`.
- **Change**:
  1. *Job eviction* in `BrowseService.purge` (the existing background `watch_purge` already calls it every `PURGE_EVERY_SECONDS`): after removing a finished job's folder (or when its folder is gone), `self.jobs.pop(request_id, None)` for jobs in a `FINAL` state (`service.py:35`) older than the screenshot retention. Preserve: a job in `queued/running/handoff/paused/asking` is never evicted; `poll()` of an evicted id already raises `BrowseError('unavailable')` via `_job`, which matches "expired". Also drop `_account_slots` entries whose semaphore is unlocked and whose account has no live job (do it under `self._guard`).
```diff
@@ def purge(self, max_age=SCREENSHOT_RETENTION_SECONDS, now=time.time):
-        removed = 0
+        removed = 0
+        with self._guard:
+            for rid, job in list(self.jobs.items()):
+                if job.state in FINAL and now() - job.finished_at > max_age: self.jobs.pop(rid, None)
```
   (`job.finished_at` does not exist today: read `Job` first; if there is no timestamp add `job.finished_at = self.clock()` where the state first becomes final, one place: find with `rg "state = 'done'|\.state in FINAL" browse/service.py`.)
  2. *Classify once*: in `ShadowRouter.before`, `if claim.request_id in self._started or self.log.has(claim.account_id, claim.request_id): return` (add `has()` to the log store with a `SELECT 1`); pop `_started/_threads` in a `finally` in `RequestWorker._run` for Parked/Defer/exception paths via a new `ShadowRouter.forget(claim)` (no external call).
  3. *Slot hold* (GATE): see question; implementation if approved: `deadline = self.clock() + (self.usage_wait if not self._others_waiting() else min(self.usage_wait, 15))`. `_others_waiting` = `self.queue` count of `waiting` rows for other accounts (one SELECT). Do not change the fallback.
  4. *Pollers*: new `lib/usePoll.ts`: `export function usePoll(fn: () => void | Promise<void>, ms: number, on = true)`, fires `fn` immediately, then on an interval only while `document.visibilityState === 'visible'`, and once on `visibilitychange -> visible`; cleans up. Replace the ad hoc `setInterval/setTimeout` loops in the six files above one file per commit, keeping each file's existing stop/reload semantics (note `Chat.tsx:21` comment warns about scroll/freeze regressions: do not change what `loadThread` does).
  5. *N+1*: add `GET /v1/files` returning `{artifacts: [...]}` across all of the account's projects (one SQL join in `accounts/files.py`, same row shape and 200 cap per project as today, newest first: do this together with BG-006), register it in `urls.py` and `openapi.json` (keep the 111-path openapi test green), and make `Chat.tsx`/`Files.tsx` call it once. Keep the old per-project route.
- **Tests to add/update**:
  - `tests/test_browse_service.py::test_finished_jobs_are_evicted_after_retention_but_live_jobs_never`: create 2 jobs (one `done`, one `running`), advance `now`, call `purge`, assert `s.jobs` contains only the running one and `poll` for the evicted id raises `BrowseError`. Fails before.
  - `tests/test_routing.py::test_a_deferred_request_is_classified_once`: fake transport counting calls; `before(claim)` twice; assert 1 call; and `test_parked_request_does_not_leak_started_entries`.
  - `lumina/src/lib/usePoll.test.tsx`: fake timers + `Object.defineProperty(document,'visibilityState',...)`; assert no calls while hidden, one call on becoming visible.
  - `lumina/src/pages/Files.test.tsx` (new or extend): `api` mock asserts `GET /v1/files` called once and `/v1/projects/*/files` not called.
  - `accounts/test_files.py::test_account_wide_listing_returns_all_projects_for_this_account_only`.
- **Commands**: `cd $P/platform && .venv/bin/python -m unittest tests.test_browse_service tests.test_routing tests.test_request_worker tests.test_native_run`; `manage.py test accounts.test_files`; `cd $P/lumina && npx vitest run src/lib src/pages && npx tsc --noEmit`.
- **Acceptance**: `len(service.jobs)` is bounded after a purge cycle; one classifier call per request; no network calls from a hidden tab (verify in the browser devtools Network tab with the tab backgrounded; mark "not run" if no browser available); Chat/Files issue one files request.
- **Rollback**: `git revert` per commit.
- **Risks**: evicting a job a person is still handing over (state `handoff`) would be a customer-visible failure: the FINAL set in `service.py:35` includes `'handoff'`; **exclude `handoff` from eviction** (use the live-states tuple at `purge`: `('queued','running','handoff','paused','asking')` as the "never evict" set instead of FINAL). `_account_slots` removal races with `_slot_for` (line 501): do it under `_guard`.
- **Do not**: do not add per-customer limits; do not change polling intervals while visible; do not touch `gen/context.tsx` visibility logic (it flushes drafts).
- **Commit message**: `Resource hygiene: evict finished browse jobs, classify once, pause hidden-tab polling, one files request (AG-011, AG-012, FE-007, FE-008, FE-009)`

---

## P3-8: add missing tests, replace weak ones

- **Findings**: FE-015, GX-005, GX-019, GX-020, GX-021, GX-022, GX-023. **Finding check**: GX-019 re-verified: `platform/tests/test_native_run.py:204-215` (`DeferChecks.test_a_session_still_owned_by_a_live_request_defers_new_work`) still ends with a comment and `self.queue.cancel(self.a, other['id'])`, no assertion. GX-020/021/023 line numbers re-read below. `lumina/src/state/data.tsx` (81 lines) and `lumina/src/gen/ChatBridge.tsx` (75 lines) have no test file (`ls lumina/src/state` shows only `data.tsx`, `settings.tsx`).
- **Goal**: tests fail when the behaviour they are named for breaks.
- **Depends on**: P3-1 (so the new tests run in CI). GX-005 dashboard tests precede P3-12's fixes (they pin current behaviour first; the P3-12 fixes then flip two of them). **GATE**: none.
- **Files to change / exact tests**:
  1. **GX-019** `platform/tests/test_native_run.py:205-215`. Add the missing assertion. The behaviour under test is in `chat_driver.py:176-188`: `_session`/`_begin` return `Defer('another conversation still owns a native run')` / `Defer('the session still has a run that something else owns')`. Replace the trailing comment+cancel with:
```diff
-        # a claim for the second request while the first still owns the session's run
-        self.queue.cancel(self.a, other['id'])
+        second = self.queue.claim(owner='w2', capacity=OK)       # the slot is free again after the park
+        self.assertIsNotNone(second)
+        self.assertEqual(second.request_id, other['id'])
+        self.assertIsInstance(self.driver.execute(second), Defer)     # the session's run is still owned by `first`, so new work waits
+        self.assertEqual(self.queue.get(self.a, other['id'])['state'], 'starting')   # nothing was sent to the gateway
+        self.assertEqual([c for c in self.gateway.calls if c[0] == 'send' and 'second' in str(c)], [])
```
     Characterise first: before asserting, run the test once with `print(self.driver.execute(second))` to confirm the real return type on this tree (`Defer` is already imported at line 16). If `claim` returns `None` instead (the park does not free the slot), the right assertion is `self.assertIsNone(second)` plus a second assertion after `self.queue.cancel(self.a, first['id'])` that the other request becomes claimable; pick the one the code actually does and say which in the commit body. The negative proof that the test now bites: temporarily make `_session` return `None` and watch it fail.
  2. **GX-020** (a) `tests/test_fleet_driver.py:291-298` `test_admission_never_runs_for_non_runnable_kinds`: `forbidden()` raises `AssertionError`, which a broad `except` in `supervisor.execute` would swallow. Replace with a counter: `calls = []; def forbidden(): calls.append(1); raise AssertionError(...)` and assert `self.assertEqual(calls, [])` after `supervisor.execute(self.claim())` so it fails even if the error is swallowed. (b) `test_activity.py:58-60` (`normalize` must not raise): keep, add `self.assertEqual(result, expected_shape)` for the one returned dict: read what `normalize('activity', ...)` returns and assert one allowlisted key set equals it. (c) `test_browse_trace.py:32-34` (`emit` on unwritable path) is legitimate "must not raise": add `self.assertFalse(missing_path.exists())` to prove nothing was created either. (d) `test_billing.py:96` is legitimate (signature contract): leave.
  3. **GX-021** doc/source-text tests: (a) `tests/test_browse_service.py:290` `assertIn('watch_purge', Path(svc.__file__).with_name('service_main.py').read_text())` -> replace with a behavioural check: import `agentai_platform.browse.service_main` and assert the function that builds the service starts a thread targeting `watch_purge` (use `unittest.mock.patch('agentai_platform.browse.service.watch_purge')` and call the factory with fakes; read `service_main.py:60-100` first; if the factory cannot be called without a socket, keep the text test but annotate "wiring smoke check, brittle by design" and move on). (b) `tests/test_tool_origin.py:106` `assertIn('before_tool_call', ... read_text())` is covered behaviourally by `tool_origin_plugin.test.mjs`; delete the text assertion once P3-1 runs that node test in CI. (c) `test_phase10_assets.py:50`, `test_phase12_assets.py:68`, `test_maintenance.py:74-78`: stable-asset checks, leave. (d) frontend `gen.components.test.tsx:198` CSS substring: leave unless it fails on reword.
  4. **GX-022** flakiness: (a) replace the fixed sleep `tests/test_browse_service.py:400` (`time.sleep(1.3)`) and the polling loops at `:227,:464` and `test_native_runner.py:148,161` with an injected clock/`threading.Event` wait (`event.wait(timeout=5)` returning True is the assertion). `BrowseService` already takes `clock=` and `sleep=` (`service.py:146`); use them. (b) do it only for tests that flaked in P3-1's first runs (read the report-only summary) to avoid churn; list of 35 `time.sleep(` call sites: `rg -n "time\.sleep\(" platform/tests`.
  5. **GX-023** frontend: (a) `lumina/src/gen/export.test.ts:46-47`: the `GEN_WRITE` branch `return`s without asserting. Change to: write files, then fall through to the same `expect(...)`s (they will then pass trivially but still run), and add `expect(process.env.CI).toBeUndefined()` inside the branch so a CI run with `GEN_WRITE=1` fails loudly instead of silently passing and mutating files. (b) `expect(x).toBeTruthy()/toBeDefined()` (131 sites; 40 in `components/safety/Safety.test.tsx`, 17 in `gen/gen.components.test.tsx`): do not mass-edit. Rule: when `x` comes from `getBy*` (which already throws if absent) leave it; when it comes from `queryBy*`/`find` use `.not.toBeNull()`; when it is a value (not an element) assert the value (`toBe`/`toEqual`). Apply to the two heaviest files only in this task and record the remaining count.
  6. **FE-015** new `lumina/src/state/data.test.tsx`: mock `../lib/api` (`api`, `onUnauthorized`, `resetCsrf`); `vi.useFakeTimers()`; render `<DataProvider><Probe/></DataProvider>` where `Probe` prints `status` and `requests.length`. Tests: `starts loading then in after /v1/me resolves`; `polls every 15 s when nothing is running and every 3 s when a request is waiting` (advance timers, count mock calls); `does not poll while the tab is hidden` (stub `document.visibilityState`); `an unauthorized callback clears requests, chats and drafts and sets anon` (invoke the callback captured from the `onUnauthorized` mock); `a late response after sign-out is ignored` (the `authVersion` guard: resolve a deferred promise after the callback fired, assert state unchanged). New `lumina/src/gen/ChatBridge.test.tsx`: render `GenBlock` inside `MemoryRouter` with a minimal document block (`kind: 'document'`) and a stub `bridge`; tests: `an invalid document reports one diagnostic and renders the fallback`; `request() resolves a task by id from bridge.tasks`; `a task_plan block exposes its phases through plan(id) and skips disabled phases` (the `p.enabled !== false` filter at line 24); `a stale block version resets the state revision` (rerender with higher `version`).
  7. **GX-005** `dashboard/test_dashboard.py` (class `FeatureSwitchesOverHttp` already starts the real `Handler` on an ephemeral port; add a sibling `HandlerSecurityEdges(FeatureSwitchesOverHttp)` reusing `call`/`login`): `test_lockout_after_five_wrong_passwords_returns_429` (reset `app._login_fails.clear()` in setUp and cleanup; 5 wrong posts then the 6th, even with the right password, is 429; this pins current behaviour, GX-002's fix in P3-12 changes the key not the count); `test_download_link_with_forged_signature_is_refused` (login, then `GET /files/dl?path=x&ver=&exp=<future>&sig=bad` -> 403); `test_download_link_expired_is_refused` (`exp=1`); `test_download_link_cannot_be_replayed` (stub `app.workread = lambda *a, **k: {'ok': True, 'content': 'hello'}`, compute `sig = app._sign(f"dl|{csrf}|x||{exp}")` with `csrf` from the page, first GET 200, second GET 403 "already used"); `test_live_stream_with_foreign_origin_is_refused_before_auth` (`Origin: http://evil.example` -> 403 even without a session; use `urllib.request.Request(headers=...)`); `test_post_without_csrf_is_refused` for `/toggle` and `/switch` (no `csrf` field -> 403). Negative case that fails before any fix: none (these pin existing, correct behaviour), which is the point; run `git stash`-free by temporarily editing `hmac.compare_digest` in a scratch copy only if you want proof of bite.
- **Commands**: `cd $P/platform && .venv/bin/python -m unittest tests.test_native_run tests.test_fleet_driver tests.test_activity tests.test_browse_trace tests.test_browse_service`; `cd $P/dashboard && python3 -m unittest test_dashboard` (stdlib only; note: the dashboard tests need no docker); `cd $P/lumina && npx vitest run src/state src/gen src/components/safety && npx tsc --noEmit`.
- **Acceptance**: each replaced test fails when its guarded behaviour is sabotaged (do one sabotage per test locally, then revert); `test_a_session_still_owned...` has at least one assertion; vitest count rises by the new files.
- **Rollback**: `git revert` (tests only).
- **Risks**: characterisation of GX-019 may reveal the park DOES free the slot and `execute` defers: fine, assert that. Fake-timer tests with React 19 + `@testing-library/react` need `act(async () => vi.advanceTimersByTimeAsync(...))`. Dashboard tests share module globals (`_login_fails`, `_streams`): reset in `setUp`/`addCleanup`.
- **Do not**: do not weaken or delete an existing assertion to make a replacement pass; do not add `time.sleep` to new tests; do not run the e2e suites to "check".
- **Commit message**: `Tests: assert deferral, behavioural wiring checks, dashboard security edges, state/data and ChatBridge coverage (GX-019..023, GX-005, FE-015)`

---

## P3-9: redacted exception logger

- **Findings**: M-12, BE-010, IS-008, ST-010 (+ST-011). **Finding check**: re-verified. `accounts/settings.py:101-103`: `LOGGING = {... 'handlers': {'null': {'class': 'logging.NullHandler'}}, 'loggers': {'django': {'handlers': ['null'], 'propagate': False}}}` (so Django's `django.request` ERROR traceback and `django.security.*` messages vanish). `accounts/middleware.py:39` prints only `{'event':'account_http','request_id':...,'status':...}`; the comment above it says "No URL/query/body/cookie/header/exception text in customer logs". A 500 therefore leaves a status line and nothing else. Deliberate privacy posture; the trade-off is no diagnostics.
- **Goal**: when a request fails with an unexpected exception, the journal gets: exception CLASS name, module, innermost frame `module:function:lineno`, the request id and status. Never the message, args, path, query, headers, traceback source lines, or locals. Helps the owner correlate a customer's "something went wrong" with `X-Request-ID`.
- **Depends on / blocks**: before P3-13. **GATE**: owner confirms the policy sentence "exception class names and code locations may be logged; exception messages never": it is a privacy-posture change (even if safe), so ask once.
- **Files to change**: new `platform/accounts/redacted_log.py`; `platform/accounts/settings.py:101-103`; `platform/accounts/middleware.py` (request id exposure); `platform/accounts/management/commands/request_worker.py:42-43` area and `agentai_platform/request_worker.py` where `except Exception` re-raises (use the helper explicitly, not a global hook). **Read first**: `accounts/middleware.py` lines 1-45 (where `request.request_id` is set and `convert_exception_to_response` sits), Django's `django/utils/log.py` DEFAULT_LOGGING (to know that `django.request` passes `record.request` and `record.status_code`).
- **Design**: a `logging.Handler` subclass that ignores `record.getMessage()` and `record.exc_text`, and builds its own line from `record.exc_info` and `record.request`.
```python
# accounts/redacted_log.py
"""Logs that an exception happened, never what it said."""
import json, logging, sys

class RedactedExceptionHandler(logging.Handler):
    def emit(self, record):
        try:
            exc = record.exc_info[1] if record.exc_info else None
            tb = record.exc_info[2] if record.exc_info else None
            while tb is not None and tb.tb_next is not None: tb = tb.tb_next      # innermost frame
            request = getattr(record, 'request', None)
            line = {'event': 'exception', 'logger': record.name, 'level': record.levelname,
                    'exc': type(exc).__name__ if exc else None, 'module': type(exc).__module__ if exc else None,
                    'where': f"{tb.tb_frame.f_globals.get('__name__', '?')}:{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}" if tb else None,
                    'request_id': str(getattr(request, 'request_id', '')) or None,
                    'status': getattr(record, 'status_code', None)}
            sys.stdout.write(json.dumps(line) + '\n'); sys.stdout.flush()      # same channel as the account_http line
        except Exception:
            pass          # a logger must never raise

def log_exception(where, exc, request_id=None):
    """For code outside Django's request cycle (workers): class name and a caller-chosen label only."""
    RedactedExceptionHandler().emit(logging.makeLogRecord({'name': where, 'levelname': 'ERROR', 'exc_info': (type(exc), exc, exc.__traceback__)}))
```
  `where` reveals file/function/line, not source text; a function name is not customer data. The handler never touches `exc.args`, `str(exc)`, `record.msg`, `record.args`, `exc_text`, `request.path`.
- **Exact LOGGING config**:
```diff
--- a/platform/accounts/settings.py
+++ b/platform/accounts/settings.py
@@ -101,3 +101,9 @@
-LOGGING = {'version': 1, 'disable_existing_loggers': False,
- 'handlers': {'null': {'class': 'logging.NullHandler'}},
- 'loggers': {'django': {'handlers': ['null'], 'propagate': False}}}
+LOGGING = {'version': 1, 'disable_existing_loggers': False,
+ 'handlers': {'null': {'class': 'logging.NullHandler'},
+              'redacted': {'class': 'accounts.redacted_log.RedactedExceptionHandler', 'level': 'ERROR'}},
+ 'loggers': {'django': {'handlers': ['null'], 'propagate': False},                       # warnings (4xx messages carry paths) stay discarded
+             'django.request': {'handlers': ['redacted'], 'level': 'ERROR', 'propagate': False},
+             'django.security': {'handlers': ['redacted'], 'level': 'ERROR', 'propagate': False},
+             'django.db.backends': {'handlers': ['null'], 'propagate': False}}}        # SQL text can hold customer data: never log
```
  `django.db.backends` is listed explicitly so nobody enables SQL debug logging by accident. Dotted child loggers do not inherit `propagate: False` handlers once they define their own handlers, so the three entries above are complete.
- **Change**: (1) add the module; (2) swap LOGGING; (3) keep `account_http` print unchanged; (4) in the request-worker `except Exception: ... raise` sites that currently log nothing (`RequestWorker._run`'s `except Exception: self.queue.uncertain(claim); raise` in `agentai_platform/request_worker.py`) add `log_exception('request_worker', exc)` ONLY via an injectable `on_error=None` argument (the platform package must not import `accounts`); wire it in `accounts/management/commands/request_worker.py`. Do not add logging to the 126 swallow sites in bulk; do it for the ones P3-13 touches.
- **Tests** (`accounts/test_logging.py`, Django `TestCase` with `override_settings(DEBUG=False)`; use `RequestFactory`-free client calls):
  - `test_an_unhandled_exception_logs_class_and_request_id_but_not_the_message`: register a URL (via `urlpatterns` override in the test module, `ROOT_URLCONF` set to a tiny conf) whose view does `raise ValueError('SECRET-CUSTOMER-TEXT-12345')`; capture stdout with `contextlib.redirect_stdout`; call it through `self.client` with `raise_request_exception=False`; assert the captured text contains `"exc": "ValueError"` and the `X-Request-ID` header value, and `assertNotIn('SECRET-CUSTOMER-TEXT-12345', captured)`, also not the URL path and not the cookie value sent in the request.
  - `test_exception_args_and_traceback_source_never_appear`: raise `RuntimeError('a', 'b')` after setting a local `password = 'hunter2-local'`; assert `'hunter2-local'` and `'raise RuntimeError'` (source text) not in output.
  - `test_warning_level_4xx_messages_are_not_logged`: trigger a 404 on a path containing `private-token`; assert nothing captured.
  - `test_helper_never_raises_even_with_a_hostile_exception`: exception whose `__str__` raises; `log_exception` returns without error and without calling `__str__` (set a flag in `__str__`, assert unset).
  - `test_db_backend_logger_has_no_output_handler`: `logging.getLogger('django.db.backends').handlers` are only Null.
- **Commands**: `cd $P/platform && AGENTAI_...env.. .venv/bin/python manage.py test accounts.test_logging accounts.tests`; `.venv/bin/python -m unittest tests.test_request_worker`.
- **Acceptance**: a deliberate 500 in a test produces one JSON line with class and request id; the privacy tests pass; `grep` of the new code finds no `getMessage`, `exc_text`, `str(exc)`, `request.path`.
- **Rollback**: revert the LOGGING hunk (module can stay unused).
- **Risks**: Django's `django.request` logger also fires for 4xx at WARNING (filtered by level) and 5xx at ERROR (included); `record.request` may be a `WSGIRequest` without `request_id` if the exception occurs before the request-id middleware runs (then `request_id` is None: acceptable; read `middleware.py` to find which middleware sets `request.request_id` and confirm it runs first); gunicorn captures stdout into the journal, same as `account_http`. An exception whose CLASS NAME is attacker-influenced is impossible (class names come from code), but a third-party exception module path could be long: truncate `where` and `module` to 120 chars.
- **Do not**: never log `str(exc)`, `exc.args`, `repr` of locals, or `record.msg`; never enable `django.db.backends`; no per-customer identifiers other than the request id.
- **Commit message**: `Log exception class, location and request id only, never messages (M-12, BE-010, IS-008)`

---

## P3-10: commit examples of server-only files; runner.mjs sync script

- **Findings**: IS-006, ST-013, GX-009 context. **Finding check**: the audit (PRODUCTION_VERIFICATION IS-006 row and `_findings/vps_readonly_2026-10-29.txt`) shows these server-only files, with contents masked: `/etc/systemd/system/agentai-browse.service.d/jev.conf` (104 bytes, Oct 16), `/etc/systemd/system/openclaw-dashboard.service.d/feature-switches.conf` (67 bytes, Oct 26), and `/etc/systemd/system/openclaw-dashboard.service` (runs as root, no `User=`, `ProtectSystem=strict`, `PrivateTmp`, `ProtectHome`, `MemoryMax=200M`; exact text not captured). I cannot read the server. The byte sizes let me reconstruct the two drop-ins with high likelihood (the strings below are exactly 104 and 67 bytes, computed with `len()`), but they remain UNVERIFIED until the owner compares them.
- **Goal**: the repo holds reviewable, redacted-free example copies of every server-only unit/drop-in, a checked comparison against the server, and a safe sync procedure for `runner.mjs` (the file that IS the production browser engine, with five hand copies and `.bak` files on the server).
- **Depends on**: P0-3. Blocks P3-11 and P3-12. **GATE**: the owner approves running the read-only capture commands below and reviews the output before anything is committed (units can contain tokens; these three should not, but check).
- **Files to add** (exact repo paths; content below; mark each with a header comment "example copy of a server-only file; verify with `systemctl cat`"):
  1. `platform/deploy/agentai-browse.service.d/jev.conf.example` (104 bytes expected; on the server it is `/etc/systemd/system/agentai-browse.service.d/jev.conf`):
```
[Service]
ExecStart=
ExecStart=/usr/bin/python3 -m agentai_platform.browse.service_main --jev-mode live
```
     Finding check on purpose: `service_main.py:51` now defaults `--jev-mode` to `live`, so this drop-in is redundant after the code default changed (RELEASE_NOTES.md:137 says "delete it for the old `shadow` default"). Recommendation: commit the example as documentation, then ask the owner whether to delete it on the server in a later maintenance step (not now).
  2. `dashboard/openclaw-dashboard.service.d/feature-switches.conf.example` (67 bytes expected; server path `/etc/systemd/system/openclaw-dashboard.service.d/feature-switches.conf`):
```
[Service]
ReadWritePaths=/opt/openclaw-production/feature-switches
```
     Rationale: the dashboard unit uses `ProtectSystem=strict`; `dashboard/app.py:79-81` writes `switches.json`/`facts.json` under that directory.
  3. `dashboard/openclaw-dashboard.service.example`: DO NOT invent. The owner runs, on the server, read-only: `systemctl cat openclaw-dashboard.service > /root/dashboard-unit.txt` and sends the text; the AI commits it verbatim after checking it contains no `Environment=` secret values (replace any value with `REDACTED`) and adds the header comment. Known facts to cross-check: `User` absent (root), `ProtectSystem=strict`, `PrivateTmp=yes`, `ProtectHome=yes`, `MemoryMax=200M`, listens on `127.0.0.1:18795` (`app.py:84`). Include in the example a `# TODO P3-11` note listing missing directives.
  4. `platform/deploy/capture-server-units.sh.txt` (documentation only, not executable): the exact read-only commands for the owner: `for u in agentai-browse openclaw-dashboard; do systemctl cat $u.service; done`, `ls -l /etc/systemd/system/*.service.d/`, `sha256sum /opt/agentai-browse/runner/runner.mjs`. No secrets are printed by these.
  5. Extend `OPERATIONS.md` section "Browser" with one line pointing to the examples.
- **runner.mjs sync script design** (`platform/deploy/sync_runner.py`, root-run on the server, stdlib only, modelled on `release.py`'s style: `argparse`, `--dry-run`, steps printed as `ok`/`FAIL`, log appended to `/var/lib/agentai-ops/releases.log`):
  - Inputs: `--source /path/to/browse/runner.mjs` (from the release tarball; `release.py` already unpacks `browse/` if the tarball contains it: confirm with `tar tzf`; if not, include `browse/runner.mjs` and `browse/package.json` in the release tarball built by the owner's process), `--dest /opt/agentai-browse/runner/runner.mjs` (default), `--id <release id>`.
  - Steps: (1) compute sha256 of source and dest; if equal, print `already in sync` and exit 0 (idempotent). (2) Refuse if the browse service has a live job: read the service's job state through its socket `GET /...` is not exposed to root scripts safely, so instead refuse unless `systemctl is-active agentai-browse` is active AND `/run/agentai-browse` shows no `queued|running|handoff|paused|asking` job directory with fresh `mtime` (< 120 s) under the jobs root; `--force-idle` lets the owner override after checking. (3) Copy dest to `runner.mjs.bak-<id>` (`shutil.copy2`, same dir, mode preserved). (4) Write source to `runner.mjs.new` (mode 0644, owner root), `os.fsync`, then `os.replace` onto dest (atomic). (5) `node --check runner.mjs` using the same node the runner is launched with (read from `service_main`'s spawn; default `/usr/bin/node`), fail -> restore the `.bak` and exit 2. (6) `systemctl restart agentai-browse`; wait up to 20 s for `systemctl is-active`; probe `GET` of the service socket health route used by `service_main` (read it; do not invent). Failure -> restore `.bak`, restart, exit 2. (7) Append a log line `runner.mjs <old sha> -> <new sha> id=<id>`.
  - `--check` mode (no writes): prints `in sync` / `DRIFT <sha-server> <sha-repo>`; this is the drift detector the audit lacks. A tiny `bin/check-runner-drift.sh.txt` documents `ssh lumina 'sha256sum /opt/agentai-browse/runner/runner.mjs'` against `sha256sum browse/runner.mjs`; PRODUCTION_VERIFICATION says they match today (the AI should verify this claim at run time, not assume it).
  - Cleanup of the four old `runner.mjs.bak-*` files is P2-4 (owner), not this task.
- **Tests**: `platform/tests/test_sync_runner.py` using a temp dir as both source and dest and fake `run`/systemctl via function injection (follow `release.py`'s `SandboxControl`/`CONTROL` pattern): `test_noop_when_identical`, `test_backs_up_and_replaces_atomically`, `test_refuses_when_a_job_is_live`, `test_restores_when_node_check_fails`, `test_restores_when_service_does_not_come_back`, `test_check_mode_writes_nothing`. Regression that fails before: the script does not exist. Also `platform/tests/test_deploy_examples.py`: parse each `*.example`/`.conf.example` with `configparser`-like check that every `[Service]` key is a valid systemd directive from a small allowlist and that no line matches secret patterns (`KEY=`, `TOKEN=`, `PASSWORD=` with a value longer than 8 characters).
- **Commands**: `cd $P/platform && .venv/bin/python -m unittest tests.test_sync_runner tests.test_deploy_examples`; `.venv/bin/python deploy/sync_runner.py --help`; on the server only after approval: `python3 deploy/sync_runner.py --check` (read-only).
- **Acceptance**: examples exist and the byte lengths of the two drop-ins are 104 and 67 (state if the owner's capture differs and commit the captured text instead); sync script tests green; `--check` documented.
- **Rollback**: delete the new files (docs/tooling only). On the server the script restores `.bak` itself.
- **Risks**: a mid-job restart of `agentai-browse` kills a customer's browser task (the idle check mitigates; do the live run in a quiet window with the owner). `release.py` replaces the platform tree only; do not graft the runner into it before `sync_runner.py` is proven.
- **Do not**: do not run `sync_runner.py` on the server without the owner's yes; do not paste any `Environment=` value; do not commit `live.secret`, `safety_file` contents, or owner switch values (the audit lists them as server-only state).
- **Commit message**: `Commit example copies of server-only units and add a runner.mjs drift check/sync script (IS-006)`

---

## P3-11: systemd sandboxing for the root units (browse, cell bridge, supervisor-native)

- **Findings**: IS-013 (+ IS-006 for the dashboard unit, covered in P3-12). **Finding check**: re-verified from the unit files. `platform/deploy/agentai-browse.service` and `agentai-cell-bridge.service` run `User=root` with only `NoNewPrivileges`, `RestrictSUIDSGID`, `RestrictAddressFamilies`, a reduced `CapabilityBoundingSet`, resource limits; no `ProtectSystem/ProtectHome/PrivateTmp/PrivateDevices/ProtectKernel*`. `agentai-supervisor-native.service` carries a comment that **mount-namespace sandboxing already broke production on 2026-10-12** (a private mount namespace hid loop mounts from the cell engine). `systemd-analyze security` was NOT run by the audit, so no baseline exposure score exists: step 0 below produces it.
- **Goal**: shrink what a compromised root helper can touch (browse parses customer web content; the bridge holds every cell token) without breaking docker/loop-mount behaviour.
- **Depends on**: P3-10 (so the live units are in git and diffable). **GATE**: the owner approves every server command (all are TEXT here) and picks a quiet window; the AI never runs them.
- **Files to change**: add drop-ins as repo examples first: `platform/deploy/agentai-browse.service.d/sandbox.conf.example`, `agentai-cell-bridge.service.d/sandbox.conf.example`, `agentai-supervisor-native.service.d/sandbox.conf.example` (drop-ins, not edits to the base units, so rollback is "delete the file"). Fold into the base units only after a week of clean operation. **Read first**: the three unit files (read in full), `browse/service_main.py:40-56` (paths used), `lifecycle/cell_bridge_main.py:20-60`, `lifecycle/cell_bridge.py:140-160` (`DOCKER_HOST` handling), `native-wiring.example.json`.
- **Facts the plan relies on** (read from code): browse writes under `/var/lib/agentai-browse/jobs` (StateDirectory), its socket in `/run/agentai-browse` (RuntimeDirectory), reads `/etc/agentai-supervisor/native-wiring.json`, `/etc/agentai-supervisor/browse-engine.json`, `/var/lib/agentai-supervisor-secrets/_shared/typesafe-key`, `/etc/agentai-platform/live.secret`, `/opt/openclaw-production/feature-switches/*.json`, runner at `/opt/agentai-browse/runner`, and drives docker through `DOCKER_HOST` (`service_main.py:81`); bind-mount source paths in `docker run -v` are resolved by dockerd in the host namespace, not by the unit. The bridge holds cell tokens under `/var/lib/agentai-supervisor` (read), listens on `/run/agentai-cell-bridge/bridge.sock`, and runs `docker exec` through `DOCKER_HOST`.
- **Per-directive plan** (apply in stages; each stage is one drop-in; stop at the first failure):
  | Stage | Unit | Directive | Why safe / what could break | Canary check |
  |---|---|---|---|---|
  | 0 | all three | none: baseline | run `systemd-analyze security <unit> --no-pager > /root/sec-before-<unit>.txt` (read-only) | scores recorded |
  | 1 | browse, bridge | `LockPersonality=yes`, `RestrictRealtime=yes`, `ProtectClock=yes`, `ProtectHostname=yes`, `SystemCallArchitectures=native`, `RestrictNamespaces=yes` | no filesystem namespace is created by these. `RestrictNamespaces` blocks the unit's own `unshare`; docker CLI does not unshare (the daemon does) | start unit, `systemctl status`, run one browse job |
  | 2 | browse, bridge | `PrivateTmp=yes` | `/tmp` private to the unit. Break risk: anything staged in `/tmp` and then bind-mounted by dockerd into a container would be invisible to the daemon. Check `rg -n "/tmp" platform/agentai_platform/browse platform/agentai_platform/lifecycle/cell_bridge*.py`; if the stage dir is under `/tmp`, skip this stage | one full browse job with a screenshot |
  | 3 | browse, bridge | `ProtectHome=yes` | hides `/root`, `/home`. Break risk: docker CLI config at `/root/.docker` (not needed for local socket use) | job runs |
  | 4 | browse, bridge | `ProtectKernelTunables=yes`, `ProtectKernelModules=yes`, `ProtectKernelLogs=yes`, `ProtectControlGroups=yes`, `PrivateDevices=yes` | these create a mount namespace with read-only `/proc/sys`, `/sys`, no `/dev` nodes beyond the basic set. Browse/bridge do not mount or touch devices. Docker CLI talks to a socket | job + `docker ps` from inside via a normal run |
  | 5 | browse | `ProtectSystem=strict` + `ReadWritePaths=/var/lib/agentai-browse /run/agentai-browse /var/lib/agentai-supervisor` + `ReadOnlyPaths=/etc/agentai-supervisor /etc/agentai-platform /opt/agentai-browse /opt/openclaw-production/feature-switches` | the biggest step: any path the code writes that is not listed fails with EROFS. Find them first: `rg -n "open\(|write_text|mkdir|rename" platform/agentai_platform/browse/*.py` | job, handoff, Stop, purge cycle (wait one `PURGE_EVERY_SECONDS`) |
  | 5 | bridge | `ProtectSystem=strict` + `ReadWritePaths=/run/agentai-cell-bridge` + `ReadOnlyPaths=/var/lib/agentai-supervisor /etc/agentai-supervisor` | bridge only reads tokens and serves a socket | customer chat round trip |
  | 6 | browse, bridge | `CapabilityBoundingSet=CAP_DAC_OVERRIDE` only if stage 5 shows `CAP_CHOWN`/`CAP_FOWNER` are unused (chown of job dirs to the app group is used by browse for `UMask=0077`/group access: keep `CAP_CHOWN CAP_FOWNER` for browse) | test with `strace -f -e trace=chown,fchown,fchownat -p <pid>` is not allowed here; instead run stage 5 with the current set and only drop a capability after one week and a log review | `journalctl -u` clean |
  | - | supervisor-native | **Only non-mount directives**: `LockPersonality=yes`, `RestrictRealtime=yes`, `ProtectClock=yes`, `ProtectHostname=yes`, `SystemCallArchitectures=native`, `MemoryDenyWriteExecute=no` (explicitly leave off; Python), `RestrictNamespaces=no` (it runs mount/loop helpers) | **Never** add `ProtectSystem`, `PrivateTmp`, `PrivateDevices`, `ProtectKernel*`, `ProtectHome`, `ReadOnlyPaths` here (the 2026-10-12 incident, comment in the unit). Its attack surface is reduced by the capability list it already has; target exposure stays high by design and that is documented | start the cell, create a quarantine drill via the existing `p4_live_check.py`? NO (do not run that script): use a normal sleep/wake of the test account |
- **Canary procedure** (single production host, so "canary" = drop-in on one unit at an idle moment, with an instant rollback): (1) owner confirms no customer task is running (`ops monitor --no-alert` or the dashboard Overview shows 0 running); (2) `cp` the stage drop-in to `/etc/systemd/system/<unit>.service.d/sandbox.conf`; (3) `systemd-analyze verify /etc/systemd/system/<unit>.service`; (4) `systemctl daemon-reload && systemctl restart <unit>`; (5) wait 30 s, `systemctl is-active <unit>`, `journalctl -u <unit> -n 30 --no-pager` (look for EROFS/EPERM/ENOENT, no customer text is logged by these units); (6) functional probe with the owner's own account: one browse task (screenshot appears, Stop works), one chat round trip; (7) if anything fails: `rm .../sandbox.conf && systemctl daemon-reload && systemctl restart <unit>` and record the failing directive; (8) next stage after at least one clean hour (production verified 0 failed units; keep it so). Bridge before browse (smaller path set).
- **`systemd-analyze security` targets** (measure first; the numbers are targets, not facts): browse `<= 5.5` (from the unmeasured baseline, expect about 9 "UNSAFE"), bridge `<= 5.0`, supervisor-native: no target; record the score and the written reason it cannot improve. Add `platform/deploy/sandbox-targets.md`-free: put the measured before/after table in the commit body, not in a new doc.
- **Tests**: `platform/tests/test_unit_files.py` (new, stdlib): parse each `platform/deploy/*.service` and `*.service.d/*.example` and assert (a) `agentai-supervisor-native.service` and its drop-in contain none of `ProtectSystem, PrivateTmp, PrivateDevices, ProtectKernel, ProtectHome, ReadOnlyPaths` (regression guard for the 2026-10-12 incident; fails today? passes today, protects the future), (b) every non-root unit keeps `NoNewPrivileges=yes`, (c) drop-ins contain only allowed keys, (d) `ReadWritePaths` entries are absolute. Server-side acceptance is manual (above).
- **Commands**: `cd $P/platform && .venv/bin/python -m unittest tests.test_unit_files`; server (owner-approved TEXT): `systemd-analyze security agentai-browse.service --no-pager | tail -3`.
- **Acceptance**: measured before/after table; each stage survived its probe; no new failed units after 24 h (`systemctl --failed`).
- **Rollback**: delete the drop-in, `daemon-reload`, restart the unit (seconds). `git revert` for the repo examples.
- **Risks**: a browse restart drops a live task (idle window); `PrivateTmp` interplay with docker bind mounts (stage 2 check); `ProtectSystem=strict` on browse can break the runner-dir read inside `stage_argv` only if the code opens it itself (it passes the path to docker). The supervisor comment is a hard warning: do not "improve" its score.
- **Do not**: do not touch supervisor-native beyond the non-mount list; do not edit base units in place on the server; do not restart units during a customer task; do not run `systemd-analyze` with `--offline` against files you did not read.
- **Commit message**: `Add staged systemd sandbox drop-in examples for browse and bridge; guard supervisor-native against mount sandboxing (IS-013)`

---

## P3-12: dashboard: stale IONOS-era pages (GX-006), lockout key (GX-002), Content-Length guard (GX-003)

- **Findings**: GX-006, GX-002, GX-003 (+GX-004 optional). **Finding check**: GX-006 is partly WRONG. It says the legacy pages "can only render unknown/unavailable" on the live host. The read-only host listing (`_findings/vps_readonly_2026-10-29.txt`, docker section) shows `openclaw-production-openclaw-gateway-1`, `-litellm-1` and `-postgres-1` RUNNING on Hostinger (ports 127.0.0.1:18789-18790, :4000), and `/opt/openclaw-production/dashboard/owner-secret` exists. So the owner stack was migrated to the new host and the `docker exec` pages work. GX-002 and GX-003 are re-verified in `dashboard/app.py`: login lockout keys on `self.client_address[0]` (`do_POST`, lines 1003-1015; `_login_fails` is an unbounded dict) and `_form()` (lines 735-738) does `min(int(Content-Length or 0), 8192)` so a negative value reaches `rfile.read(-1)` and a non-numeric one raises `ValueError` in the handler thread.
- **Goal**: keep what works, retire what the owner no longer uses, and fix the two loopback-attackable weaknesses.
- **Depends on**: P1-2 (shell-sourcing fix), P3-8 item 7 (tests pin the current behaviour), P3-10 (dashboard unit in git). **GATE**: "Do you still use the OWNER OpenClaw assistant (its Telegram bot, scheduled tasks, approvals queue, memory, integrations pages)? If yes, nothing is retired; if no, the five pages below are removed."
- **Route triage** (`dashboard/app.py` `do_GET`, verified route table):
  | Route (line) | Backend it drives | Live-host status | Decision |
  |---|---|---|---|
  | `/` Overview `home_page` (760) | mixed: platform DB + gateway | works | KEEP |
  | `/switches` (766), `/routing` (770), `/customers` (774) | `/opt/agentai-platform`, `accounts.env` | works | KEEP (the live control surface) |
  | `/system` (763) | `docker exec` gateway version, `pg_isready`, `docker ps` | works (containers exist) | KEEP, PORT: add a "Lumina services" block (`systemctl is-active` for the units listed in `platform/OPERATIONS.md` section 12) |
  | `/costs` (971) | LiteLLM Postgres spend | works; customer cell keys also spend through this LiteLLM | KEEP |
  | `/audit` (987) | dashboard audit log | works | KEEP |
  | `/files`, `/files/dl` (856, 889) | owner gateway work root via `workread.mjs` | works | KEEP (security-sensitive: covered by P3-8 tests) |
  | `/live`, `/live/stream` (788, 816) | owner gateway live view | likely works | KEEP |
  | `/sessions` (778), `/approvals` (913), `/schedules` (926), `/memory` (947), `/integrations` (964) | owner OpenClaw gateway only (`docker exec ... node dist/index.js`) | work, but concern only the owner assistant, not customers | owner decides (GATE): RETIRE if unused |
  Retire procedure if the owner says no longer used: (1) group them under one nav item "Owner assistant" and add a 30-day banner ("scheduled for removal; tell me if you use this"); (2) after 30 days remove the five `if path == ...` blocks, the helpers only they call (`sessions_data`, approvals/cron/memory/integration helpers: confirm with `rg -n "<name>" dashboard/app.py` that nothing else calls them), and their tests; (3) never remove `run()`/`docker exec` helpers still used by `/system` and `/costs`.
- **Change (GX-003 and GX-002 are code; do them regardless of the GATE)**:
```diff
--- a/dashboard/app.py
+++ b/dashboard/app.py
@@ def _form(self) -> dict:
-        n = min(int(self.headers.get("Content-Length") or 0), 8192)
+        try:
+            n = int(self.headers.get("Content-Length") or 0)
+        except ValueError:
+            n = -1
+        if not 0 <= n <= 8192:
+            raise BadForm()                      # new tiny exception class; do_POST maps it to self._deny(400, "bad request")
```
  and wrap the two `self._form()` calls in `do_POST` (login path line ~1010 and the authenticated path line ~1030) in `try/except BadForm: return self._deny(400, "bad request")`.
  Lockout (GX-002): the attacker model is another local process on the server or on the owner's tunnel host; every client is `127.0.0.1`. Design: (a) issue a random `dsh_try` cookie on `GET /login` (HttpOnly, SameSite=Strict) and key `_login_fails` on that cookie id; requests with no cookie share the key `'nocookie'`. So a local process with no cookie can lock only `'nocookie'`, never the owner's browser. (b) Keep 5 failures/hour per key, and add a global ceiling of 30 failures/hour across all keys (still returns 429) so cookie-cycling brute force is bounded; the owner's password is a long random file secret, so the ceiling is a backstop, not the main defence. (c) Bound the dict: prune keys older than 1 hour whenever it exceeds 1000 entries. Owner trade-off to state: a local attacker with a fresh cookie each time can still trigger the global ceiling and block logins for up to an hour (the same DoS as today, but now it needs 30 requests instead of 5, and the owner can restart the service to clear it); say so in the commit body.
- **Files to change**: `dashboard/app.py:735-738,1003-1031,93` (+ `do_GET` login branch ~750 for the cookie), `dashboard/test_dashboard.py`. **Read first**: `app.py` 735-760, 1001-1031, `_deny`, `_send`, `check_password`, `_login_fails` (line 93).
- **Tests** (extend the P3-8 `HandlerSecurityEdges` class): `test_negative_content_length_is_a_400_not_a_hang` (raw `http.client` request with `Content-Length: -1` and a 2 s socket timeout; fails before: it blocks); `test_non_numeric_content_length_is_a_400` (before: thread traceback, no response); `test_five_failures_with_one_cookie_do_not_lock_another_cookie` (two `CookieJar`s; the second logs in fine); `test_global_failure_ceiling_returns_429`; `test_failure_table_is_bounded`. The P3-8 test `test_lockout_after_five_wrong_passwords_returns_429` must still pass with one cookie jar.
- **Commands**: `cd $P/dashboard && python3 -m unittest test_dashboard` (stdlib; no docker needed); `python3 -c "import ast;ast.parse(open('app.py').read())"`.
- **Acceptance**: no request can hang a handler thread; the owner can log in while a cookie-less local process hammers `/login`.
- **Rollback**: `git revert`; deploy via `bin/update-ops-dashboard.py --apply` (dry-run by default, takes a timestamped backup, by owner).
- **Risks**: the dashboard is root and hand-deployed (`bin/update-ops-dashboard.py:23` copies it to `/opt/openclaw-production/dashboard`); a syntax error locks the owner out of the switches page: run the unit tests and `python3 -m py_compile` before any deploy, keep the previous file as `app.py.bak-<date>` (the script does).
- **Do not**: do not delete pages before the owner answers; do not widen the `ORIGINS` set; do not log passwords or session tokens.
- **Commit message**: `Dashboard: reject bad Content-Length, key login lockout on a browser cookie with a global ceiling; triage legacy pages (GX-002, GX-003, GX-006)`

---

## P3-13: backend functional bugs not covered elsewhere (compact specs)

- **Findings**: BG-004, BG-005 (done in P3-5), BG-006, BG-007, BG-010, BG-013, BG-014, BG-015, BG-016, BG-017, BG-018, BG-019, BG-020, BG-021 (done in P3-7), BG-022..BG-030. **Finding check**: sources re-read for BG-004/006/007/010/013/014/015/016/025/030; all HIGH-confidence claims still hold at the current lines given below. BG-001/002/003/008/011/012 belong to P1.
- **Depends on**: P3-9 (use `log_exception`); each item below is its own commit. **GATE**: BG-017 (expose or delete `add_version`), BG-022 (host firewall: owner-approved), BG-029 (terminal status wording).
- Each item: *where*, *change*, *test (fails before)*, *risk*. Run `manage.py test accounts.test_files accounts.test_genui` and `unittest tests.test_files tests.test_gen_artifacts tests.test_ops_backup tests.test_secrets_custody tests.test_events` after each.
  1. **BG-004 images over 200 KiB are unreadable**. `accounts/files.py:266,272` read with `max_bytes=MAX_PREVIEW_BYTES` (`agentai_platform/files.py:24`, 200 KiB); a screenshot or chart larger than that raises `ValueError('content exceeds bound')`, mapped to 400. Change: add `MAX_INLINE_MEDIA_BYTES = 8 * 1024 * 1024` in `agentai_platform/files.py` and use it for `gen_asset` (image/pdf media types only) and the `download=1` path; keep the sandbox CSP. Test `test_gen_asset_serves_a_300_kib_png` (fails before with 400). Risk: memory (8 MiB read into RAM per request; acceptable).
  2. **BG-006 newest rows dropped**. `ORDER BY created ASC LIMIT N` at `agentai_platform/artifacts.py:118-121` (200 versions), `files.py:168-170` (200 files), `genui/store.py:114-119` (`data_blocks` LIMIT 100). Change: select newest N (`ORDER BY created DESC LIMIT N`) then reverse in Python so the API order is unchanged; for `gen_asset`'s "latest by name" use a direct `SELECT ... WHERE display_name=? ORDER BY version DESC LIMIT 1`. Test: insert 205 artifact versions, assert the newest 200 are listed and the oldest 5 are not. Risk: `UI_CONTRACT.md` documents `/blocks` as unpaged; keep the cap, change only which end is kept.
  3. **BG-007 bundle recursion and memory**. `artifacts.py:185-186,205-224`: skip entries whose `media_type == BUNDLE_MEDIA` in `build_bundle` (add `AND media_type<>?` to the query), build the zip into `tempfile.SpooledTemporaryFile(max_size=8*1024*1024)` instead of `BytesIO`, avoid `getvalue()` (read from the file object into `capture`), and also bound the COMPRESSED size by `MAX_BUNDLE_UNCOMPRESSED`. Test: build a bundle, build again, assert the second manifest lists no bundle artifact (fails before: it includes the first). Risk: low.
  4. **BG-010 incomplete set evicts a complete one**. `ops/backup.py:_prune` (lines 228-240) treats any set with a manifest as complete. Change: read each manifest (`dest.read` of `sets/<id>/manifest.json`; reuse what `ops/sets.py:26-32` does) and keep only `manifest.get('complete')` sets in the `complete` list passed to `select_keep`; incomplete sets are removed only after a newer complete set exists. Test in `tests/test_ops_backup.py` (needs `age`): two sets same day, older complete, newer incomplete; after prune the older survives (fails before).
  5. **BG-013 swallowed file captures**. `chat_driver.py:718-746` single `try/except Exception: pass` around the loop; names collide via `path.replace('/', '_')`. Change: per-file `try/except Exception as exc` that emits an `error` event (`self._emit(claim, 'error', {'what': 'file_not_saved', 'name': name[:128]}, 'system')`: check the event allowlist in `events.py` for an allowed kind first) and continues; name = `path` with `/` -> `__` plus a short hash when the flattening would collide; make `capture_or_version` one transaction (`artifacts.py:65-84`). Test `test_one_failing_file_does_not_drop_the_rest` (fake `artifacts.capture_or_version` raising on the first call; assert the second file is saved and one error event emitted; fails before).
  6. **BG-014 plan phase stuck `running` with no request id**. `genui/runner.py:106-126`. Change: in `sync()` treat a phase with `state='running' AND request_id IS NULL AND started_epoch < now - 120` as `failed` with summary "Could not start this phase (interrupted)"; the deterministic key `phase-<block>-<phase>-<attempts>` makes a retry idempotent. Also allow `skip`/`retry` for that state. Test: insert such a row, call `sync()`, assert `failed`, then `retry` works (fails before: advance returns early forever).
  7. **BG-015 `task_state` is an integer**. `agentai_platform/events.py:127-141`: rename the loop variable (`for item in rows`) and return `task_state: state_row['state']` (capture the state row into `state_row` first). Test `test_events_endpoint_returns_the_task_state_string` (fails before). Risk: none.
  8. **BG-016 negative `after` on the SSE stream**. `accounts/streams.py:80-82`: replace `int(...)` with the `isdecimal()` check the polling view uses; 400 on negative. Test posts `after=-1` and expects 400 and no `stream.open` audit.
  9. **BG-017 `add_version` unreachable**. GATE question: "Expose 'upload a new version of a file' to customers or delete `ArtifactService.add_version`?" Either way add the 2 GiB quota check first (`artifacts.py:51-54` logic reused). Test: `add_version` over quota raises `Conflict`.
  10. **BG-018 rotation not operable**. `ops/rotation.py:19-65` has no CLI. Change: add `ops rotate provider-key|webhook-secret|session-secret` subcommands in `ops/cli.py` (the choices list at line 20), with `--dry-run`; write files via temp file + `os.fchmod(fd, 0o600)` + `os.replace` (fix the chmod-after-write window at `rotation.py:32,50-51` and the non-atomic env rewrite at `:64`); after replacing a tenant key print the line "restart or re-inject the cell key: lifecycle op `restart` for tenant X" and, optionally, enqueue that operation. Update `OPERATIONS.md` section 8 to the real commands. Tests in `tests/test_ops_rotation.py`: file mode never wider than 0600 during the write (use `os.stat` in a patched `os.replace`), crash mid-write leaves the old env file intact. GATE: owner approves because it touches live secrets (risk medium); ship the CLI with `--dry-run` default and no unit.
  11. **BG-019 orphan LiteLLM key on crash**. `lifecycle/secrets_custody.py:130-138` and `ops/rotation.py:22-26`: before `/key/generate` call `/key/info`/list by `key_alias=tenant` (read the admin helper in `lifecycle/litellm_admin.py` for the real call) and reuse or delete a stray key; record intent first. Test with the fake admin client. Confidence MEDIUM-LOW (duplicate-alias behaviour unverified): implement as lookup-then-generate only.
  12. **BG-020 empty secret file after crash**. `secrets_custody.py:52-72`: write to `name.tmp` with `O_EXCL`, `fsync`, then `os.link(tmp, final)` (fails if the final exists, preserving "never overwrite") and unlink tmp; in `_read` treat an empty file as absent. Test: pre-create an empty file, assert `gateway_token` regenerates instead of raising `CustodyError('corrupt secret')`.
  13. **BG-022 IPv6 gap in the cell firewall**. `lifecycle/netpolicy.py:55-92` only matches `ip saddr/daddr`. GATE (host firewall, medium risk, confidence LOW): first the owner reports whether IPv6 is enabled (`sysctl net.ipv6.conf.all.disable_ipv6`, read-only). If IPv6 is off, add a test asserting the generated ruleset drops `meta nfproto ipv6` in `forward` for cell sources and stop; if on, design with the owner. Do not change live nftables from this task.
  14. **BG-023 vault key missing from the recovery inventory**. `ops/inventory.py:ASSETS`: add `vault-key` with `backed_up_by=''` and a restore note ("without this key `vault_items` ciphertext is unusable; keep an off-host copy"); also the live-frame secret and artifact signing key lines. Test: `ops inventory` output includes it; monitor treats `backed_up_by=''` as informational, not a failure (read how existing off-host entries such as the age key are handled).
  15. **BG-024 only the first backup destination is verified**. `ops/cli.py:33-35,51`, `ops/hostconfig.py:27,126-127`: loop `verify` over every destination; make a missing off-site destination fail `check` (exit non-zero) once the owner has set one up (P2-2); until then keep it a warning. Test with two fake destinations, the second corrupted.
  16. **BG-025 plan launch race**. `agentai_platform/chat.py:403-411` re-checks `status` but not `version`: add `or fresh['version'] != version: raise Conflict('version conflict')`. Test: bump the version between read and transaction (patch `blocks.get`), expect `Conflict`.
  17. **BG-026 test double inside production module**. Move `SyntheticGateway` (`gateway.py:237-404`) to `agentai_platform/testing/synthetic_gateway.py` and update `chat_driver.py:25,904` + tests; keep `from .gateway import SyntheticGateway` as a deprecated re-export for one release only if any tool imports it (`rg SyntheticGateway` first). Risk low.
  18. **BG-027 frame gateway starvation**. `live/gateway.py:28,36,69-70`: cap concurrent waiters per request id (2) in addition to the global 12; test with 3 waiters on one id (third gets 429) and one waiter on another id (served). This IS a limit, but it protects other tenants' availability and is not a per-task customer limit; mention it to the owner in the commit body.
  19. **BG-028 two retention implementations** (done in P3-5: call or delete `EventService.prune_expired`).
  20. **BG-029 stopped plan stays `launched`**. `genui/runner.py:216-227`: GATE wording; recommended: set `ui_blocks.status='stopped'` (new allowed status; check the CHECK constraint in `migrations/` for `ui_blocks.status` first: if it forbids it, this needs a NEW migration `0031_*.sql`, not an edit). Test: stop a plan, assert `edit`/`launch` are refused and the UI summary shows stopped.
  21. **BG-030 swallowed failures that matter**. `ops/hostconfig.py:84-90` `tenants()` returns `[]` on any error: change to raise `OperationalError` into the backup run so the set is marked incomplete (`expected_assets` at `hostconfig.py:119` should include `tenant-cells` whenever the custody DB exists); `genui/runner._audit` (`runner.py:157`) keep best-effort but call `log_exception`; the others (`chat_driver` `attach_cards:619`, `_capture_files` done in item 5, `lifecycle/worker._say:126`, `ops/backup._deliver:225`) add `log_exception` and a reason string in the backup report (`_deliver`: store `type(exc).__name__`, never a path with customer data). Test: custody DB unreadable -> backup report `complete: False` with reason `tenants_unreadable` (fails before: complete).
- **Acceptance / Rollback / Do not**: each item has its failing-first test; rollback is `git revert` of that item's commit. Do not edit `migrations/*.sql`; do not widen any customer-facing limit downwards; do not log message text, file names, or paths.
- **Commit message** (one per item): `<area>: <fix> (BG-0xx)`

---

## P3-14: `git gc` and the asset strategy

- **Findings**: GH-011, GH-002. **Finding check**: re-verified read-only: `git count-objects -vH` shows `count: 1683`, `size: 336.60 MiB` (loose objects), `in-pack: 6874`, `size-pack: 5.08 MiB`, `garbage: 0`. So almost all of the 351 MB is uncompressed loose objects and `git gc` will shrink it a lot without touching history. The working tree tracks 10 263 files (4 535 under `lumina-character/public`, 4 496 under `lumina/public`, mostly OpenMoji SVGs).
- **Goal**: a smaller, faster repo with no history rewrite; a decision on large assets.
- **Depends on**: P0-5 (owner's push plan; do gc after the 47 unpushed commits are safe on a remote, because gc is local-only and safe either way, but a remote copy is the real backup). **GATE**: (1) "OK to run `git gc` on the local repo?" (safe, reversible only by re-cloning; nothing is deleted that is reachable, but unreachable objects older than the prune expiry can be removed; see Do-not). (2) Asset strategy choice below.
- **Files / commands (TEXT for the owner or run by the AI after the yes; they only touch `.git`)**:
  1. Record before: `git -C /Users/parsa/AgentAI count-objects -vH` and `du -sh /Users/parsa/AgentAI/.git`.
  2. Safety copy of refs: `git -C /Users/parsa/AgentAI for-each-ref > /private/tmp/claude-501/-Users-parsa-AgentAI/5009f90a-3794-4ea3-b6d7-1c09800e73d3/scratchpad/refs-before-gc.txt` (any scratch path) and a tag list: `git tag -l | wc -l`.
  3. Run `git -C /Users/parsa/AgentAI gc` (NOT `--prune=now`, NOT `--aggressive` first time; default prune expiry is 2 weeks, so recent unreachable commits such as the dangling work from `worktree-*` branches survive).
  4. Verify: `git fsck --no-dangling` exits 0; `git for-each-ref` output identical to step 2; `git log --oneline -3`; `git worktree list` unchanged; `git count-objects -vH` shows `count` near 0 and `size-pack` in the 100-300 MB range (expectation, not a measurement).
  5. Do NOT run `git reflog expire` / `git gc --prune=now` / `git filter-repo` / `bfg`.
- **Asset strategy options** (decide, do not execute without the owner): (A) leave as is (the two copies of OpenMoji SVGs are the bulk; `lumina-character` goes away or is archived under P4-3, halving the count); (B) stop tracking OpenMoji SVGs and fetch at build time from the pinned OpenMoji npm package (`lumina/scripts/build-openmoji-index.mjs` already exists and builds the index; the SVGs are generated artifacts) with a checksum file; needs `.gitignore` of `lumina/public/openmoji/` and a build step (the Vercel build must run it); (C) Git LFS for the 31 `.mp4/.jpg` film scenes in `lumina-character/public/scenes` only. Recommendation: A now, B after P4-3, C only if the owner keeps `lumina-character`. Rule for all options: no history rewrite; removing files from the tip leaves history size unchanged, which is acceptable.
- **Tests**: none (no code). Acceptance below is a command checklist.
- **Acceptance**: step 4 outputs recorded in the report; the app still runs (`git status` clean for tracked files; `cd $P/lumina && npx tsc --noEmit`).
- **Rollback**: gc cannot be undone, but it loses nothing reachable; if `fsck` fails, restore from the remote or the Time Machine copy. This is why the push decision comes first.
- **Risks**: the Mac working tree is the only complete copy (handoff section 3): do NOT gc while another process (IDE git) is running; avoid during a `git rebase`/merge.
- **Do not**: no `--prune=now`, no history rewrite, no force-push, no deleting worktrees (P0-6 is separate).
- **Commit message**: none (no tracked change); if a `.gitattributes`/`.gitignore` change for assets is approved: `Stop tracking generated OpenMoji SVGs; fetch at build (GH-011)`.

---

# Phase 4: decision-driven items

Every Phase 4 task has the same shape: **options, recommendation, prerequisite tests, staged path**. A "checkpoint" is a commit after which the app works and every suite listed under "Prerequisite tests" is green; you may stop at any checkpoint without leaving the product half-migrated. All stages are GATED on the owner's choice of option unless the stage is marked "safe now".

## P4-1: M-08 browser engine: cutover or freeze

- **Findings**: M-08, GH-004, AG-010, GX-017-adjacent. **Finding check**: verified in code and docs. Production default is the host Docker `runner.mjs` engine (`/etc/agentai-supervisor/browse-engine.json` = `{"default":"runner","native":[]}`, read at every job start by `engine_for`, `browse/service_main.py:92-101`). The native engine (`NativeRunner`, `NativeTransport`, `native_scripts.py`, bridge `browser.*` methods, Live-view frame path) is built, tested and gated off; `docs/architecture/native-browser-plan.md` says "built; rollout gated" and makes the cutover conditional on workstream 8 (an eval comparison on real models, not yet run: `evals/cases.yaml` has no native-vs-runner case, `evals/README.md` says nothing there executes during build phases). A third, separate path, the tool-origin hook that lets an assistant call `lumina_browser` from inside a cell via `agentai-tool-relay`, is live in production and uncommitted (P0-3). SSRF/private-range policy is implemented in `agentai_platform/ssrf.py`, `lifecycle/netpolicy.py`, `browse/native_runner.py` and `browse/runner.mjs`.
- **Options**:
  | Option | What | Cost | Risk |
  |---|---|---|---|
  | A. Freeze | Keep `runner.mjs` as the engine indefinitely; native stays dormant but maintained (CI runs its tests); add shared SSRF vectors; stop adding native features | low | dual-engine upkeep continues |
  | B. Cut over | Eval gate -> canary account -> percentage -> default native -> delete runner/stage code | high (needs real-model spend, a week of canary) | customer-facing; screencast fidelity unmeasured ("frame rate under motion is NOT measured", plan doc) |
  | C. Retire native | Delete the native engine and bridge `browser.*` surface, keep runner | medium | throws away reviewed work (admin-scope bridge design, per `openclaw-native-browser-findings`: `browser.request` needs admin, screenshot is a file path) |
  **Recommendation: A now, B only after the eval gate produces data, never C.** The runner is the proven path; the native path's value (browser inside the customer's own cell, one profile per customer) is real but gated by evidence the repo does not have.
- **Depends on / blocks**: P0-3 (commit tool-origin), P3-1 (CI runs native tests), P4-4 (the asking/vault UI is needed by BOTH engines), P1-11 (screenshot egress policy shared by both). **GATE (ask)**: "Freeze the native browser engine (A) or authorise the eval spend and a canary on your own account (B)? If B, what is the maximum model spend for the eval run (the plan's gate needs real models)?"
- **Files**: `browse/runner.mjs`, `platform/agentai_platform/browse/{service.py:647 (stage_argv), native_runner.py, native_scripts.py, service_main.py:80-110}`, `ssrf.py`, `lifecycle/netpolicy.py`, `platform/deploy/browse-engine.example.json`, `evals/cases.yaml`, `evals/run.py`, `docs/architecture/native-browser-plan.md`. **Read first**: the plan doc sections 5, 8, 9 and "Decision gate" lines; `native_runner.py` top; `netpolicy.py` private-range lists; `runner.mjs` `privateIp`/`urlAllowed` (exported, see `browse/test/runner.test.mjs:12`).
- **Prerequisite tests (must be green before stage 3+)**: `tests.test_browse tests.test_browse_modes tests.test_browse_service tests.test_browse_ask tests.test_browse_fill tests.test_browse_goals tests.test_browse_fields tests.test_browse_sight tests.test_browse_trace tests.test_browse_untrusted tests.test_native_runner tests.test_native_wiring tests.test_browser_tool tests.test_cell_bridge tests.test_cell_config tests.test_tool_origin tests.test_netpolicy`, `node --test browse/test/ tests/tool_origin_plugin.test.mjs`, and `tests/e2e/test_native_browser.py` on a machine with the pinned OpenClaw package and Chrome (owner's Mac; skipped in CI).
- **Staged path (checkpoints)**:
  1. **(safe now) CP1: one shared SSRF vector file**. Add `platform/tests/fixtures/ssrf_vectors.json`: list of `{url_or_ip, expected: allow|deny, reason}` covering loopback, RFC1918, link-local/metadata `169.254.169.254`, CGNAT `100.64/10`, `::1`, IPv4-mapped IPv6, decimal/octal/hex IP forms, userinfo tricks (`http://good.com@127.0.0.1/`), trailing dot hosts, `localhost.` and DNS names resolving privately (use a stub resolver). Add one test per implementation reading the same file: Python `ssrf.py`, `netpolicy.py` (its address-classification function), `native_runner.py` (`allow_private=False` path), and a node test `browse/test/ssrf-vectors.test.mjs` calling `urlAllowed`/`privateIp` from `runner.mjs`. Where an implementation disagrees with the vectors, DO NOT fix in this commit: list the disagreements in the commit body and ask the owner (these are security bugs: fix each in its own commit). Checkpoint: tests added, behaviour unchanged.
  2. **CP2: consolidate Python copies** behind `agentai_platform/ssrf.py` (one `classify_address(ip) -> str`), `netpolicy.py` and `native_runner.py` import it. Pure refactor, vectors prove equivalence. `runner.mjs` keeps its own copy (JS), covered by the same vectors.
  3. **CP3: eval gate (needs owner spend approval)**. Add cases to `evals/cases.yaml` for both engines on the same 10-20 tasks (task success, steps to done, ladder escalation rate, per-task model cost, wall time, crash/hang rate: the metrics named in plan section 8) and run via `evals/run.py` against the owner's own account only. Output goes to `evals/RESULTS.md`. Cutover criterion from the plan: "native meets or beats the current one on success and does not exceed current cost".
  4. **CP4: canary**. Owner edits `/etc/agentai-supervisor/browse-engine.json` (TEXT, owner-approved) to `{"default":"runner","native":["<owner-test-account-id>"]}`; read at each job start, no restart. Run for a week; watch `journalctl -u agentai-browse` and the monitor. Rollback = remove the id from the list (instant).
  5. **CP5: percentage -> default**. Add accounts in batches; then `"default": "native"`. Rollback = `"default": "runner"`.
  6. **CP6 (separate decision, only after a full release on native)**: delete `runner.mjs`, `stage_argv`, the host stage docker image build (`bin/phase4/build-browser-image.sh`), `agentai-browse` host stage unit parts and their tests (plan line 131). Not part of this task.
- **Tests to add**: `platform/tests/test_ssrf_vectors.py`, `browse/test/ssrf-vectors.test.mjs`, `platform/tests/test_engine_switch.py` (`engine_for` returns `runner` for malformed JSON, missing file, non-dict, unlisted account; `native` for listed account and for `default:"native"`). Regression: vectors currently expose any divergence.
- **Commands**: `cd $P/platform && .venv/bin/python -m unittest tests.test_ssrf_vectors tests.test_engine_switch tests.test_netpolicy tests.test_native_runner`; `cd $P/browse && node --test test/`.
- **Acceptance (Option A)**: vectors green in all 4 implementations; docs updated to say "frozen". (Option B) as the staged path.
- **Rollback**: CP1/CP2 `git revert`; CP4/CP5 edit `browse-engine.json`.
- **Risks**: engines differ in what `screenshot` returns (native: file path) and in the Live-view frame source (plan decision gate: keep the runner frame path for Live if native latency is worse); the asking/vault UI (P4-4) must work on both. Do not conflate with tool-origin (a different feature).
- **Do not**: do not delete `runner.mjs` ("it IS the production engine", handoff section 6); do not change `browse-engine.json` on the server without the owner; do not add per-task limits to the eval run; do not merge SSRF implementations without the vectors passing on all four.
- **Commit messages**: `Add shared SSRF test vectors for all browser engines (M-08)`; `Consolidate Python SSRF classification (M-08)`; `Add native-vs-runner eval cases (M-08)`.

---

## P4-2: M-07 generative-UI unification

- **Findings**: M-07, FE-004, FE-005, GH-007. **Finding check**: re-verified. `lumina/src/components/genui/BlockView.tsx` (30 lines) dispatches per `block.kind`: `document` -> lazy `gen/ChatBridge` (new stack); `form` -> `FormBlock`; `task_plan` -> `PlanBlock` (old stack, 176 lines); `table|chart|comparison` -> `Cards.tsx` (8 lines) -> `gen/legacy.tsx` (21 lines, read-only adapter into the new `Renderer`). The backend still validates exactly two interactive kinds in the old format (`genui/schema.py:44 validate_form`, `:180 task_plan`) plus the new `document` kind (`genui/document.py`, 452 lines). Old table/chart/comparison are historical only. `gen/ChatBridge.tsx:16` itself imports the OLD `PlanBlock` and `planSpec`, so the new stack depends on the old one for plans. `GET /v1/genui/registry` (`accounts/genui.py:105`, `urls.py:59`) is served and never called by the frontend; `genui/gen_registry.json` is generated from `gen/export.test.ts` (the freshness test) and loaded by the Python server.
- **Options**:
  | Option | What | Verdict |
  |---|---|---|
  | A. Keep both | Status quo; every genui change checked in two places | cheap now, growing cost |
  | B. Migrate form + plan into `gen`, keep only the read-only legacy adapter | removes ~800 lines of the old path over time | **recommended** |
  | C. Delete the legacy adapter | customers lose old cards in history | **no** (handoff: "do not delete `gen/legacy.tsx`") |
- **Depends on**: P3-1, P3-8 (ChatBridge tests), P3-6 (dead exports), P1-5 (genui validator fixes BG-002/003 change the backend contract: do those first). **GATE**: "Plan editing semantics (edit phases, approve/skip/retry, launch) must stay identical: confirm that the PlanBlock UI may be re-implemented in the new design system as long as the behaviour tests pass?" and BG-003 button semantics from P1-5.
- **Files**: `lumina/src/components/genui/*`, `lumina/src/lib/genui/*`, `lumina/src/gen/{ChatBridge,legacy,registry,manifest,schemas,protocol}.ts(x)`, backend `platform/agentai_platform/genui/{schema,document,store,runner}.py`, `platform/accounts/genui.py`, `UI_CONTRACT.md`. **Read first**: all of the above plus `lumina/src/components/genui/blocks.test.tsx` (153 lines) and `lib/genui/genui.test.ts` (106 lines).
- **Prerequisite tests**: `npx vitest run src/components/genui src/lib/genui src/gen`, `manage.py test accounts.test_genui`, `tests.test_genui tests.test_gen_document tests.test_gen_artifacts`. Add before touching anything (CP0): a **contract test** `platform/tests/test_genui_contract.py` that loads `genui/gen_registry.json` and asserts the set of component types equals the frontend's `IMPLEMENTED_TYPES` snapshot stored in `platform/tests/fixtures/gen_parity.json` (already exists; check what it covers first). This closes FE-005's "two sources, no cross-check".
- **Staged path (each stage ends at a working app)**:
  1. **CP0 (safe now)**: contract test above + a vitest that renders every `kind` through `BlockView` with a fixture and asserts non-fallback output (the existing `blocks.test.tsx` may already; extend only missing kinds).
  2. **CP1**: make `gen/ChatBridge` stop importing from `components/genui`: move `planSpec`/plan types to `lib/genui/schema.ts` (they are already there) and move `PlanBlock.tsx` to `gen/components/PlanEditor.tsx` unchanged (git mv + import fix). `BlockView` still routes `task_plan` to it. Pure move.
  3. **CP2**: add a `form` component to the `gen` registry that wraps the existing `FormBlock` logic (`useAutosave`, `/v1/blocks/<id>/{state,submit}`), registered under the same server contract; `BlockView` routes `form` to it. No backend change; `FormBlock.tsx` becomes a thin shim then is deleted when no import remains.
  4. **CP3**: backend: emit forms/plans as `document` blocks only when the owner has accepted BG-003 semantics; keep accepting old-format `form`/`task_plan` specs on read forever (history). New migration only if a table/column changes (next is `0031`; never edit existing SQL).
  5. **CP4**: delete duplicated zod specs for table/chart/comparison from `lib/genui/data.ts` except what `legacy.tsx` types need; keep `Cards.tsx`->`legacy.tsx`. Call `GET /v1/genui/registry` nowhere (the parity test replaces it) or delete the route after the owner confirms no external client (`ORPHANED_CODE` sec. 2).
- **Tests to add**: contract test, `BlockView` per-kind render matrix, a plan-edit regression (`edit -> launch -> approve phase -> skip -> retry`) against the stored block API (backend: `accounts/test_genui.py`), unchanged before/after.
- **Commands**: as under Prerequisite tests, plus `npx tsc --noEmit && npm run build`.
- **Acceptance**: after CP2 `components/genui/FormBlock.tsx` is a shim or gone; after CP4 `rg "components/genui" lumina/src/gen` finds nothing.
- **Rollback**: each CP is one commit; revert the last.
- **Risks**: autosave semantics (`useAutosave` debounces to `/v1/blocks/<id>/state`) must be byte-identical or partially saved forms can be lost; plan `version` conflict handling (`BG-025`) must survive the move.
- **Do not**: do not delete `gen/legacy.tsx`; do not change backend validators in the same commit as a frontend move; do not edit `gen_registry.json` by hand (it is generated; run `GEN_WRITE=1 npx vitest run src/gen/export.test.ts` locally, never in CI).
- **Commit messages**: `genui: add frontend/backend registry parity test (M-07)`; `genui: move PlanBlock into gen (no behaviour change) (M-07)`; `genui: form as a gen component (M-07)`.

---

## P4-3: M-06 `lumina-character`: promote, archive or keep

- **Findings**: M-06, GH-012, GX-018, FE-001. **Finding check**: re-verified from the audit numbers: 4 697 tracked files (4 535 in `public/`, 61 MB of assets), one commit (`d95b796`), not referenced by `.github/`, `platform/deploy`, `deploy/` (only docs); it is NOT a subset of `lumina`: it alone has `AskBox, ChatQuestion, FieldsBox, QuestionPanel, SavedInfo, SceneBackground, useBrowseQuestion.ts, useTaskEvents.ts, chatActions.ts, styles/obsidian.css, DESIGN_SYSTEM.md` (the browser-question and saved-info UI that FE-002 needs). Also the untracked `lumina-character/node_modules` symlink (git status `??`) escapes the `node_modules/` ignore pattern (fixed by P0-1: pattern `node_modules` without slash).
- **Options**: A. **Archive** (preserve then remove from the tree); B. **Promote** (make it the real front end; would require porting `gen/`, `safety/`, `ui/`, `lib/safety*` into it: months); C. **Keep frozen in place**, document, ignore in tooling.
- **Recommendation: A after P4-4 has ported the question/vault components; until then C.**
- **Depends on**: P4-4 (port the components first), P0-1 (ignore pattern). **GATE**: "Archive `lumina-character` (preserved as a tag plus a tarball outside the repo, then removed from the working tree), or keep it?"
- **Files**: whole directory `lumina-character/`; `.gitignore`; docs mentioning it (`rg -n "lumina-character" --glob '!lumina-character/**'`). **Read first**: `docs/codebase-audit/_findings/frontend.md` FE-001, `GX-018` in `gap_tooling.md`, `git log --oneline -- openclaw-project/lumina-character | head`.
- **Staged path**:
  1. **CP1 (safe now)**: add `lumina-character/README.md`-free: instead put one line in the root docs index: "frozen, not built, not deployed; see tag". Fix the node_modules ignore (P0-1). No code change.
  2. **CP2**: after P4-4 ported the components into `lumina`, run a feature-diff check: for each fork-only file listed above, write down where its function now lives in `lumina` or "intentionally dropped" (a table in the commit body).
  3. **CP3 (preserve)**: create `git tag -a archive/lumina-character-2026-10-29 -m "frozen fork before removal"` at the current HEAD (local tag; pushing is P0-5) and a bundle outside the repo: `git -C /Users/parsa/AgentAI archive --format=tar.gz -o ~/lumina-character-archive-2026-10-29.tar.gz HEAD:openclaw-project/lumina-character` (the owner chooses the location; the AI must not write into `~` without asking). Verify with `tar tzf ... | wc -l` equals `git ls-files openclaw-project/lumina-character | wc -l`. Note the existing tag `lumina-character-final` (5db9636) preserves an earlier layout (per GH-012 it holds the code with `lumina/` as path); do not rely on it alone.
  4. **CP4**: `git rm -r openclaw-project/lumina-character` in its own commit (revert-safe). Update docs that link into it.
  5. **CP5**: P3-14 option B for emoji assets applies to the remaining `lumina/public`.
- **Tests**: none new; before CP4 run the whole lumina suite and build (`npx vitest run && npm run build`) to prove nothing imports the fork (`rg -n "lumina-character" lumina platform deploy .github` is empty except docs).
- **Acceptance**: archive tarball file count matches; tag exists; repo tracked file count drops by ~4 697; lumina build green.
- **Rollback**: `git revert` the removal commit (all files return); or restore from the tag/tarball.
- **Risks**: it holds the only copy of the "film UI" scene assets and ask/vault components at HEAD; CP2 table is the guard. The untracked `node_modules` symlink must not be committed.
- **Do not**: do not delete before CP2/CP3; do not push the tag without the owner's P0-5 decision; do not rewrite history to drop the 61 MB.
- **Commit messages**: `Archive lumina-character (tag + tarball), remove from tree (M-06)`.

---

## P4-4: FE-002 browser question and vault UI: port or retire

- **Findings**: FE-002 (High, MEDIUM confidence), BG-related vault/saved routes. **Finding check**: the condition is TRUE today. The browse loop always receives an ask gate (`browse/service.py:548 ask_gate=self._ask_gate(job)`), and `loop.py:351,414,453` raise questions for saved-login offers, card offers and field questions whenever it finds options; the job then sits in state `asking` for up to `ASK_SECONDS = 300` (`service.py:93`) with `takeover_until` extended. The shipping `lumina/src` has no caller for `POST /v1/browse/<id>/answer` (only `lumina-character/src/lib/useBrowseQuestion.ts:23` does), nor for `/v1/vault*` and `/v1/saved*`. `ChatDriver` maps `asking -> 'browser_question'` (`chat_driver.py:39`), so the request parks "waiting on a person" with nothing to click. The customer can still take over through the Live view (pause/resume/release are wired in `Live.tsx:65`), which is the workaround.
- **Options**:
  | Option | What | Verdict |
  |---|---|---|
  | A. Port | Bring `AskBox/ChatQuestion/FieldsBox/QuestionPanel/SavedInfo` + `useBrowseQuestion` into `lumina`, restyled with lumina tokens | **recommended** (vault/saved info are the core of sign-in and card flows) |
  | B. Retire | Backend never asks: `ask_gate=None` makes the loop choose defaults silently | **rejected for privacy**: skipping the question means the loop would use saved logins/cards without consent (`_offer_fill` is exactly the consent step) |
  | C. Convert questions into hand-offs | `_ask_gate` immediately sets state `handoff` with a reason ("you need to choose"), the customer acts in the Live view | acceptable interim, loses the saved-info convenience |
- **Depends on / blocks**: blocks P4-3 CP2 and P4-1 (both engines). Needs P3-8 (frontend test patterns). **GATE**: "Is the saved-card/saved-login (vault) feature meant to ship to customers now? (If not: choose C and keep the vault routes hidden.)"
- **Files**: new in `lumina/src/` (copy from `lumina-character/src/`): `components/AskBox.tsx`, `ChatQuestion.tsx`, `FieldsBox.tsx`, `QuestionPanel.tsx`, `SavedInfo.tsx`, `lib/useBrowseQuestion.ts`, tests `*.test.tsx`; integrate in `pages/Live.tsx` (line ~129) and the chat thread where `parked == 'browser_question'`; `lib/api.ts` types for `question` (the job payload field, see `service.py:275-281`). Backend: none for A. **Read first**: the fork's files and tests, `service.py:275-345` (`question` view and `answer()` contract: `answer(account, request_id, question_id, *, option=None, resume=False, secret=None, fields=None)`), `loop.py:340-460`, `accounts/browse.py:answer`, `accounts/vault.py`, `UI_CONTRACT.md` browse section.
- **Staged path**:
  1. **CP1 (safe now, interim): a visible prompt** with zero new backend: in `Live.tsx` and the thread, when `run.state === 'asking'` or the request is parked `browser_question`, show "The browser needs your choice. Take over to answer, or press Continue." with two buttons using existing endpoints (`/v1/browse/<id>/release` or `/pause`, and `/answer` with `{resume: true}`). This removes the silent 5-minute stall. Test: vitest renders the banner for an `asking` run.
  2. **CP2**: port `useBrowseQuestion` + `AskBox`/`ChatQuestion` (choice questions only, `kind: 'choice'`), restyle, port their tests. The options list carries only labels the backend already sanitises (`question view` returns `options[{id,label,item?}]`).
  3. **CP3**: port `FieldsBox` (sensitive fields: `input_type`, `sensitive: true` must render `type=password`, never echoed, never stored in React state longer than the submit, never logged) and `SavedInfo` (`/v1/saved`, `/v1/vault`, forget/delete).
  4. **CP4**: gate by switch/feature flag already in `AppInfo.features` (add `vault` flag if absent; read `accounts/api.py:app`) so production can turn the UI on per owner decision.
- **Tests**: ported fork tests (`AskBox.test.tsx`, `ChatQuestion.test.tsx`, `FieldsBox.test.tsx`, `SavedInfo.test.tsx`, `tasks.test.ts`) adapted to lumina's test setup; new `Live.asking.test.tsx` for CP1; backend regression `accounts/test_requests.py`/browse tests already cover `answer`. Privacy test: render `FieldsBox` with a sensitive field, assert the value never appears in `document.body.innerHTML` after submit and that `api` was called once with it.
- **Commands**: `cd $P/lumina && npx vitest run src/components src/pages src/lib && npx tsc --noEmit && npm run build`; `cd $P/platform && .venv/bin/python -m unittest tests.test_browse_ask tests.test_browse_fields tests.test_vault`.
- **Acceptance**: with the fake browse backend in the existing preview scripts (`lumina/tests/preview_*.py` are manual), an `asking` job can be answered from the UI; no secret value is logged or kept after submit.
- **Rollback**: `git revert` per CP; CP4 flag off hides everything.
- **Risks**: sensitive-field handling is the privacy surface of this task: no `console.log`, no `localStorage`, no analytics, `autocomplete="off"`/`new-password`. The 300 s `ASK_SECONDS` stays as is (no new limit; do not shorten).
- **Do not**: do not choose B; do not store card data or logins in the frontend; do not wire vault routes before the owner confirms the product decision.
- **Commit messages**: `Live: show a prompt when the browser is asking (FE-002)`; `Port browser question UI from lumina-character (FE-002)`.

---

## P4-5: AG-004 / BE-013 single-lane fairness

- **Findings**: AG-004, BE-013, BE-006/M-01 interplay. **Finding check**: re-read `request_queue.claim` (`request_queue.py:147-173`), `lifecycle/sleep.py:25-30 can_sleep`, `lifecycle/worker.py:133-170 tick/facts`. Facts: (1) one global row in `request_slot` (id=1): if it exists `claim` returns `None`. (2) Otherwise `claim` takes the single oldest `waiting` request by `sequence` (skipping accounts parked on a person) and then returns `None` if `lifecycle_slot` is held by a different account (line 167). (3) `can_sleep` returns False while the holder account has `running_tasks`, `queued_tasks` or `pending_approvals` (`sleep.py:28`), where `queued_tasks` counts `tasks.state='queued'` (`worker.py:58`). (4) `tick` shortens the idle window to `handover_idle=60` s when another account is waiting. **Reproduced by reading, not executed**: holder X has a NEWER queued task, waiting Y has the OLDER one. `claim` picks Y's request, sees the cell held by X, returns `None` every poll; X's cell cannot sleep because `queued_tasks > 0`; X's newer task cannot be claimed because `claim` only ever examines Y's row. Neither moves. The audit rated MEDIUM confidence; step 1 below turns it into a test that proves or disproves it before any fix. BE-013: `gunicorn.conf.py` has `workers=1`, `threads=1`, and `rate()` writes a bucket under `transaction.atomic()` on authenticated requests (`middleware.py:~63`), so every request serialises on one SQLite writer.
- **Options**: A. **Document only** (SERIAL_REQUESTS.md already describes the lane; add the stall). B. **Fair FIFO without new concurrency** (recommended): fix the stall by teaching sleep/handover about queue order. C. **Real concurrency** (N slots, N cells): large, touches the core invariant "one running slot", capacity model (`OPERATIONS.md`: trial capacity is two cells), budget, and cell lifecycle; separate project.
- **Depends on**: P1-1 (reservation release) and P4-7 CP-settlement (so the slot/settlement code is stable). **GATE**: "Is strict arrival order across customers acceptable (an older waiting customer is served before a holder's newer message), or should the cell holder keep priority for a bounded time?" (A bounded priority is a new limit; the recommendation is plain FIFO.)
- **Files**: `platform/agentai_platform/request_queue.py:147-173`, `lifecycle/sleep.py`, `lifecycle/worker.py:41-62,133-170`, tests `tests/test_request_queue.py`, `tests/test_worker.py`, `tests/test_sleep.py`, `tests/test_request_worker.py`; `SERIAL_REQUESTS.md`. **Read first**: those ranges and `worker.py:86-131 (waiting_accounts, enqueue_wakes)`.
- **Staged path**:
  1. **CP1 (safe now): characterisation test** `tests/test_worker.py::test_holder_with_a_newer_queued_task_does_not_block_an_older_waiting_account` building: account X with a running cell and a queued task (newer sequence), account Y with a waiting request (older sequence), `wake=True`. Tick repeatedly with an advancing clock past `idle_after`/`handover_idle`; assert Y's request becomes claimable. Mark `@unittest.expectedFailure` if it fails today (that records the bug without breaking CI, and flips to a hard failure when the bug is fixed, forcing removal of the marker). If it passes today (the existing handover logic at `test_worker.py:210` already covers it), record the test as a guard and close AG-004 as not reproducible.
  2. **CP2 (if reproduced)**: pass the fact "an older request from another account is waiting" into `can_sleep`:
```diff
--- a/platform/agentai_platform/lifecycle/sleep.py
+++ b/platform/agentai_platform/lifecycle/sleep.py
@@ def can_sleep(facts: CellFacts, now: float, *, idle_after=IDLE_AFTER_SECONDS) -> bool:
-    if facts.running_tasks or facts.queued_tasks or facts.pending_approvals:
+    if facts.running_tasks or facts.pending_approvals:
         return False
+    if facts.queued_tasks and not facts.older_waiting_elsewhere:
+        return False
```
     with `CellFacts.older_waiting_elsewhere` (default False, so every existing call keeps its behaviour) computed in `worker.facts()` as "exists a `customer_requests` row in state `waiting` and unpaused for another account whose `sequence` is lower than every `waiting` sequence of this account". The holder's own newer queued task then waits its turn after Y. Running work is never interrupted (`running_tasks` still blocks).
  3. **CP3**: `claim` fairness hardening: when the oldest waiting row belongs to an account whose cell is not the slot holder, and the holder has no `starting|running` request, return `None` only if a handover is in progress (the lifecycle worker will wake the right cell) — already the effect; add an assertion test rather than code unless CP1 shows another stall.
  4. **CP4 (optional, GATE)**: BE-013 reads: skip the authenticated-GET rate bucket write for `GET` requests on endpoints not in `ACCOUNT_RATE_SCOPES` (`services.py:25-26`). That lowers protection against read floods; ask before doing it, and prefer raising `threads` to 2 only after confirming SQLite WAL write contention is acceptable (measure; do not guess).
- **Tests**: CP1 test above; `tests/test_sleep.py::test_queued_tasks_block_sleep_unless_an_older_request_waits_elsewhere`; `tests/test_request_queue.py::test_fifo_across_accounts_when_the_slot_is_free`; regression that running work still blocks sleep.
- **Commands**: `cd $P/platform && .venv/bin/python -m unittest tests.test_worker tests.test_sleep tests.test_request_queue tests.test_request_worker tests.test_native_run`.
- **Acceptance**: CP1 test passes (or is `expectedFailure` with the reproduction documented); after CP2 no cell with queued-only work blocks an older waiting account past `handover_idle`; running work is untouched.
- **Rollback**: `git revert` CP2 (default False keeps old behaviour for any partial rollout).
- **Risks**: handing over a cell while its owner has a queued (not running) task delays that customer by one other customer's whole run (up to `RUN_TIMEOUT`); FIFO makes that fair, but state it to the owner. Do not touch `request_slot` semantics (the core invariant).
- **Do not**: do not add per-account run-time or message limits; do not introduce a second slot here; do not change reservation/settlement code in this task.
- **Commit messages**: `Reproduce single-lane stall as a test (AG-004)`; `Let a cell hand over when an older request waits elsewhere (AG-004)`.

---

## P4-6: BE-012 one migration system

- **Findings**: BE-012. **Finding check**: re-verified. Two systems share one SQLite file: (1) 30 numbered `platform/migrations/*.sql` files (`0001_foundation.sql` ... `0030_gen_artifact_events.sql`), checksummed in `schema_migrations` and applied by `Store.initialize()` (`agentai_platform/store.py:23-48`; `/readyz` demands `applied == expected`, `store.py:54-60`); (2) Django `accounts/migrations/0000..0015`, where `0000_foundation.py` adopts all SQL files (applies any missing SQL then records them) and the newer Django migrations `0014_safety_overrides.py` / `0015_safety_access.py` create `safety_overrides` and `safety_access` with raw `RunSQL`. `Store(...).initialize()` alone (used by the standalone server `server.py:89` and `bootstrap_accounts`) therefore yields a database WITHOUT the two safety tables; `ops/restore.py:38` lists them, `agentai_platform/safety.py` reads/writes them with raw SQL, and `accounts/services.py:_rate_limits_off` swallows the resulting error (`except Exception: return False`) so the missing table would be masked as "limits on". `makemigrations --check` is clean (verified by the audit).
- **Options**: A. **SQL files are the single source**: add `0031_safety.sql` with `CREATE TABLE IF NOT EXISTS safety_overrides(...)`, `safety_access(...)` identical to Django 0014/0015; make Django 0014/0015 `IF NOT EXISTS` so a fresh `manage.py migrate` (0000 applies 0031, then 0014) does not fail. B. **Django is the single source**: port every SQL file into Django migrations: huge, and checksum history breaks `/readyz`. C. **Detect only**: a test that fails when code references a table the SQL system does not create.
- **Recommendation: C immediately (CP1), then A (CP2-CP3).** B is not worth the checksum risk.
- **Depends on / blocks**: before adding any other new table (every future table should be an SQL file). Next number is `0031` (note `0023` collision with the unmerged `worktree-product-images` branch: never merge it). **GATE**: none for CP1; owner approves CP2-3 only because a schema change ships through `release.py` (it migrates a copy first, canary, rollback exists).
- **Files**: new `platform/tests/test_schema_parity.py`; new `platform/migrations/0031_safety.sql`; `platform/accounts/migrations/0014_safety_overrides.py`, `0015_safety_access.py`; `agentai_platform/safety.py` (table DDL reference), `ops/restore.py:20-40` (table list). **Read first**: `store.py`, `accounts/migrations/0000_foundation.py` (read in full above), `0014`, `0015`, `deploy/release.py:115-123,185-215` (migration step = `manage.py bootstrap_accounts`, which calls `Store.initialize()`).
- **Staged path**:
  1. **CP1 (safe now)**: `test_schema_parity.py`: (a) create an empty DB with `Store(path).initialize()` ONLY; collect `SELECT name FROM sqlite_master WHERE type='table'`; (b) parse the table names referenced by `ops/restore.py` lists (LIVE/derived lists at lines 20-40) and by `agentai_platform/safety.py`; assert each exists. Today the safety tables fail (record as `expectedFailure` with the reason; it flips to a failure when fixed so you remove the marker). (c) second test: run Django `migrate` on an empty DB (use `manage.py test`'s test DB: `from django.db import connection; connection.introspection.table_names()`) and assert the SET of tables from (a) is a subset: proves the two paths converge.
  2. **CP2**: add `0031_safety.sql` (`CREATE TABLE IF NOT EXISTS safety_overrides(account_id TEXT NOT NULL, feature TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)), changed_by TEXT NOT NULL, changed_epoch INTEGER NOT NULL, expires_epoch INTEGER, PRIMARY KEY(account_id, feature))` and the matching `safety_access` DDL copied exactly from `0015_safety_access.py`; if either differs from the live schema, STOP and compare with a read-only `.schema` of a COPY of the production database taken via the backup, because two different definitions would hide a real drift).
  3. **CP3**: change `0014`/`0015` `RunSQL` to `CREATE TABLE IF NOT EXISTS`. They have already run in production (no effect), and they stay idempotent on fresh databases where `0000` now creates the tables first. Run `makemigrations --check` (must stay clean: RunSQL text is not tracked by the autodetector).
  4. **Release**: ship through `release.py` (canary migrates a copy, starts the new release, probes `/readyz`, checks the previous release still serves the migrated schema). On the live DB `Store.initialize()` applies `0031` as a no-op create-if-missing and records its checksum.
- **Tests**: CP1 tests; after CP2 the `expectedFailure` marker is removed and the test must pass; `manage.py test accounts` (fresh DB path) and a unit that runs `Store.initialize()` twice (idempotent).
- **Commands**: `cd $P/platform && .venv/bin/python -m unittest tests.test_schema_parity tests.test_foundation tests.test_ops_restore tests.test_safety_gates`; `manage.py makemigrations --check --dry-run`; `manage.py test accounts`.
- **Acceptance**: `Store.initialize()`-only DB has all tables referenced by code; `/readyz` stays green on the canary; `makemigrations --check` clean.
- **Rollback**: before release `git revert`. After release: `release.py` rollback (previous release runs against the migrated schema because 0031 only adds IF NOT EXISTS tables that already existed).
- **Risks**: editing an already-applied Django migration is safe only because it does not re-run; do not renumber. `schema_migrations` checksum is over file text: after commit, NEVER edit `0031_safety.sql` again.
- **Do not**: do not edit any existing `platform/migrations/*.sql`; do not merge `worktree-product-images` (collides on 0023); do not drop or recreate the safety tables.
- **Commit messages**: `Test that Store.initialize creates every table the code uses (BE-012)`; `Add 0031_safety.sql and make Django safety migrations idempotent (BE-012)`.

---

## P4-7: AG-014 split `chat_driver.py` and extract the `loop._run` safety floor

- **Findings**: AG-014, ST-008, AG-020 (swallowed stops) touching, AG-015. **Finding check**: verified with an AST listing. `chat_driver.py` is 907 lines; `class ChatDriver` spans lines 51-901 (about 850 lines, 60 methods, `_Blind` helper at 838). `browse/loop.py`: `BrowseRunner._run` is lines 124-344 (221 lines) inside a 465-line class. The floor rules inside `_run` appear in this order (line offsets inside `_run`): cancel check, pause gate, deadline, page read, `policy.url_ok` (block), bot-check wall retry then handoff, second `url_ok`, payment page handoff (with or without a saved-card note), login page handoff (before any model sees the page), JEV decision handling, `policy.gate` for risky next steps, repeat/stuck/no-change detection, `max_steps`.
- **Goal**: reviewable modules and a pure, table-testable safety floor, with zero behaviour change per commit.
- **Depends on**: P1-1, P1-9, P3-1 (CI green with native_run/browse suites), P3-7 (so behaviour fixes are not tangled with moves). **GATE**: none technically; owner awareness: this is a pure refactor in the money-and-safety path, so ask once "OK to spend a release cycle on a no-behaviour-change refactor?".
- **Rules for every extraction commit**: (1) move code verbatim; (2) leave a one-line wrapper method on the old class with the SAME name and signature (tests patch `driver._reconcile_usage`, `driver._finish`, etc.; `rg "_reconcile_usage\|driver\._" platform/tests` before each move); (3) re-export moved module-level names from `agentai_platform/chat_driver.py` (`RETRY_NOTE`, `synthetic_gateway_factory`, `PARK_LIMIT`, `GOAL_CHAIN_LIMIT`, `RUN_TIMEOUT`, `OUTAGE_LIMIT`: tests import `RETRY_NOTE`, `ChatDriver`, `synthetic_gateway_factory`); (4) the full prerequisite suites must be green before AND after; (5) no signature, logging, exception-type or ordering change.
- **Module boundaries for `chat_driver` (new files next to it; `agentai_platform/chat_driver.py` stays the public module)**:
  | New module | Moves (current methods) | Notes |
  |---|---|---|
  | `driver_files.py` | `_capture_files` (718-746), `_browser_evidence` (665-680), `_artifact_count` | take `(store, artifacts, emit, claim, gateway, since)`; BG-013 fix happens later in P3-13, not here |
  | `driver_settlement.py` | `_usage_before`, `_reserved`, `_over_budget`, `_budget_stop`, `_reconcile_usage` (749-783), `_Blind` | class `Settlement(ledger, store, clock, sleep, pause, usage_wait)`; holds the reservation/receipt logic the audit calls the only settlement (M-01): extra care |
  | `driver_browser.py` | `_stop_browser_jobs`, `_release_waiting_browser_jobs`, `_browser_stopped`, `_human_wait`, `_cell_gone` | the `HUMAN_WAIT` map moves with them |
  | `driver_goal.py` | `_goal`, `_pause_goal`, `_chain_length`, `GOAL_CHAIN_LIMIT` use | |
  | `driver_recovery.py` | `reconcile`, `_interrupted`, `abandon`, `check_parked`, `_extend_deadlines` | |
  | stays in `chat_driver.py` | `__init__, execute, _admit, _begin, _deliver, _supervise, _finish, _failed, _close, _emit, _present*, _mirror, _absorb` (the run lifecycle) | target under about 450 lines |
  Order (each is one commit; run the suites after each): (1) `driver_files` (smallest, no money), (2) `driver_goal`, (3) `driver_browser`, (4) `driver_recovery`, (5) `driver_settlement` LAST and only after P1-1, because it is where the reservation fix lands. Stop after any step; the app works at every commit.
- **Safety floor extraction (`browse/loop.py`)**: new `browse/floor.py` with a pure function and no I/O:
```python
@dataclass(frozen=True)
class FloorFacts:
    url: str; title: str; text: str; snapshot: str; page_text: str
    walls_on: bool; read_only: bool; payment_stop_on: bool; card_filled: bool

@dataclass(frozen=True)
class FloorVerdict:
    status: str      # 'blocked' | 'handoff'
    reason: str
    rule: str        # trace label: 'bot check wall' | 'payment page' | 'login page' | 'url'

def page_floor(policy_url_ok, cand, facts) -> FloorVerdict | None:
    """The rules that apply to every page before any model sees it, in the order _run applies them today."""
```
  Order inside `page_floor` MUST equal `_run`: (1) `not policy.url_ok(url)` -> blocked (`'the page moved to a site that is not allowed'`); (2) `walls_on and cand.page_is_bot_check(title, text)` -> handoff `WALL_REASON`; (3) `read_only and payment_stop_on and cand.page_is_payment(url, snapshot, page_text)` -> handoff (the saved-card variant when `card_filled`); (4) `walls_on and cand.page_is_login(snapshot)` -> handoff `LOGIN_REASON`. `_run` keeps everything that has side effects (trace emit, `_end`, the bot-check retry/wait loop at lines ~160-172, saved-login offers, cancel/pause/deadline). A second pure function `stuck_verdict(history, failed_steps, unchanged_pages)` covers "too many failed steps / repeating the same step / the page is not changing". Extraction procedure: (a) FIRST write the characterisation table test (below) against the CURRENT `_run`; (b) then add `floor.py` and replace the inline conditions one rule per commit, running the table test each time; (c) compare trace output (`trace.emit('floor', rule=...)`) unchanged.
- **Prerequisite tests**: chat driver: `tests.test_native_run tests.test_chat tests.test_request_worker tests.test_genui tests.test_events tests.test_chat_history tests.test_task_progress` + `manage.py test accounts`. Loop: `tests.test_browse tests.test_browse_modes tests.test_browse_fill tests.test_browse_goals tests.test_browse_ask tests.test_browse_untrusted tests.test_browse_sight`. Existing named coverage of floors: `test_browse.py:175 test_stops_at_the_payment_step_and_never_clicks_checkout_or_buy`, `:214 test_a_human_verification_wall_is_handed_to_the_user_not_guessed_at`, `:512 test_page_is_login_reads_the_snapshot_lines`, `test_browse_fill.py:66`, `test_browse_modes.py:128,324,377` (repeat/stuck), `test_browse_service.py:434` (denied site).
- **Tests to add (before any move)**: `platform/tests/test_driver_surface.py`: snapshot of `sorted(n for n in dir(ChatDriver) if not n.startswith('__'))` stored in the test (fails if a method disappears), plus `import agentai_platform.chat_driver as m` asserting the re-exported constant names. `platform/tests/test_browse_floor.py`: a table of `(facts, expected verdict)` for each rule and for the ORDER (a payment page that is also a login page -> payment wins; a blocked URL that is also a bot-check wall -> blocked wins; walls off -> no wall verdict; read-only off -> no payment verdict), run first through a thin wrapper around current `_run` behaviour using the existing fake session fixtures (`test_browse.py` helpers), then directly against `page_floor`. Negative case that must fail if someone reorders rules: the two precedence rows.
- **Commands**: the suites above plus `python -c "import agentai_platform.chat_driver, agentai_platform.browse.loop"` from `$P/platform` with the venv after every commit; `wc -l platform/agentai_platform/chat_driver.py` for the progress record.
- **Acceptance**: `chat_driver.py` below about 450 lines; `_run` below about 150 lines; both prerequisite suites identical pass counts before/after; `test_driver_surface` and `test_browse_floor` green.
- **Rollback**: each extraction commit is independently revertable (wrappers keep the old surface).
- **Risks**: `_reconcile_usage` ordering relative to `_close` decides whether a charge is written before the request closes (M-01); `self.sleep`/`self.clock` injection must pass through to `Settlement` unchanged or tests with fake clocks hang; `_run`'s local variables (`history`, `res`, `started`) are mutated by branches: pass them explicitly.
- **Do not**: no logic fixes, renames or "while here" cleanups inside a move commit; do not change exception handling (the 20 `except Exception` stay); do not extract settlement before P1-1 lands; do not touch the PARK_LIMIT/usage-snapshot behaviour of P1-9.
- **Commit messages**: `chat_driver: move file capture to driver_files (no behaviour change) (AG-014)` (and one per module); `browse: extract the page safety floor as a pure function (AG-014)`.

---

## P4-8: M-05 orphaned modules decision matrix, and GX-017 phase fixtures

- **Findings**: M-05 (BE-014, AG-009), GX-017, GX-013. **Finding check**: re-verified sizes and states: `durable.py` 165 lines, `memory.py` 129, `schedules.py` 111, `watchers.py` 102, `skills.py` 111, `optimization.py` 164, `policy_check.py` 91 (has `main()`), `genui/intent.py` 29 (a website-requirements form template `website_form()`), `ops/rotation.py` 65, `lifecycle/broker.py` 199. Switch locks verified in `switches.py:111-118`: `customer_schedules` is `locked='Locked until the safety checks for unattended work have been run (Phase 15).'` and another switch is locked "until each customer has an isolated workspace and a metered key". No deletion is proposed anywhere: owner rule "preserve unfinished functionality".
- **Decision matrix** (action per module: WIRE = make it a live feature; HIDE = keep code, ensure no UI/route/switch exposes it, keep tests; PARK = leave exactly as is and record the decision):
  | Module | What it is | Recommendation | Why / prerequisite | Verify before any change |
  |---|---|---|---|---|
  | `optimization.py` (`OptimizationGate`) | gate for JEV browser optimization; header says DISABLED; docstring `MODEL='jev-1.13.0'` vs live `jev-1.14.0` | **WIRE as part of P1-11** (decide the egress policy, then make `browser_optimization` the actual switch in `jev_for`) | it is the data-egress control for screenshots to TypeSafe; leaving it unwired means the switch text lies | `rg "OptimizationGate\|browser_optimization" platform`, `tests.test_optimization` |
  | `ops/rotation.py` | key/secret rotation helpers, no CLI | **WIRE via P3-13 item 10 (BG-018)** | incident response needs it operable | `tests.test_ops_rotation` |
  | `policy_check.py` | effective tool-ceiling checks over `plans/product/capability-inventory.json` | **WIRE into CI (P3-1 report-only step)** if the owner confirms nobody runs it by hand | pure static check, cheap | owner question: "do you run `python -m agentai_platform.policy_check` by hand?"; `tests.test_policy_check` is already in CI |
  | `lifecycle/broker.py` | host-owned worker-stage envelopes; used by `deploy/p4_broker_check.py` | **PARK** (dormant by design) | native cells replaced the stage design; keep with its tests | `tests.test_broker`; do not run `p4_broker_check.py` |
  | `durable.py` (objectives) | multi-step objectives with checkpoints | **PARK** | overlaps goals (`goals.py`) and plans; needs a product decision on the single "long task" model | tables exist in SQL; `ops/restore.py` lists them |
  | `memory.py` | memory entries/terms | **HIDE** (already: `urls.py` routes `memory` to the `disabled` view) | privacy-heavy (stores customer facts): needs retention (P3-5), export/delete and a UI | confirm `features` flags false in `/v1/app`; retention answers cover its tables |
  | `schedules.py` | recurring tasks | **HIDE/PARK**; the switch is locked | unattended runs spend money with nobody present: needs a funding/stop policy (owner), not a code fix | `customer_schedules` locked text |
  | `watchers.py` | watch conditions + notifications | **PARK** | same as schedules plus outbound notifications | tables `watchers`, `watcher_notifications` |
  | `skills.py` | skill versions per account | **PARK**; link to `config/skills` which is hand-installed on the owner host (P4-8 fixtures below) | | `.gitignore` has `skills/`: check `git ls-files config/skills` before assuming it is tracked |
  | `genui/intent.py` | `website_form()` template for the Plan/website flow | **PARK**; wire only if the frontend offers "Build a website" (P4-2 decides the form component) | 29 lines, harmless | `rg "website_form\|submit_requirements" platform lumina/src` |
  Process per module once the owner picks: (1) write the decision into `ORPHANED_CODE.md` and `INCOMPLETE_FEATURES.md` (status line, date); (2) WIRE items become their own tasks (P1-11, P3-13); (3) HIDE items get a test pinning the hidden state (`accounts/test_*.py::test_<feature>_routes_are_disabled`: GET `v1/memory`, `v1/schedules`, `v1/integrations` return 503 `capability_not_enabled`, switch locked); (4) PARK items get nothing but the doc line. **GATE**: "For each of memory, schedules, watchers, skills, durable objectives: which one is the next product feature, if any? The rest stay parked."
- **GX-017: phase fixtures and config assets with no code consumers**. Verified references (`git grep` outside `config/`, `evidence/`, audit docs):
  | Asset under `config/` | Consumers found | Code consumer? |
  |---|---|---|
  | `phase10-claude-code-activation.batch.json`, `phase10-claude-code-preflight.batch.json`, `phase10-fixtures/` | `platform/tests/test_phase10_assets.py` (in CI), `plans/product/phase-10*.md`, `phase-10-harness-inventory.json`, `requirements.json` | yes (a test) |
  | `phase11-fixtures/` (hostile injection samples) | `platform/tests/test_phase10_assets.py`, `plans/product/phase-11.md`, referenced inside `cases.json` | yes (a test); no loader executes the hostile files |
  | `phase3-worker-policy.batch.json` | `BUILD_LOG.md`, `RUNBOOK.md` only | no |
  | `phase4-codex-activation.batch.json`, `phase4-codex-preflight.batch.json`, `phase4-native-workers.batch.json` | `BUILD_LOG.md`, `RUNBOOK.md`, `plans/product/phase-10-harness-inventory.json`, `docs/orchestration-audit/*` | no code |
  | `phase4-fixtures/` | `RUNBOOK.md`, `plans/phase-4.md`, `plans/product/phase-10.md` | no code |
  | `phase5/`, `phase5-native-memory.batch.json` | `BUILD_LOG.md`, `RUNBOOK.md`, `plans/phase-5.md`, `platform/tests/test_optimization.py` (phase5) | `phase5/` yes (a test); the batch file no |
  | `phase6/` | `bin/phase6/prepare-server.py`, `bin/connect-tool`, `CONNECT_TOOLS.md`, `plans/product/phase-11-permission-matrix.json` | yes (scripts; production-mutating, never run) |
  | `skills/`, `workspace-templates/` | `ARCHITECTURE.md`, `RUNBOOK.md`, `BUILD_LOG.md`, `docs/architecture/findings.md`; `.gitignore` contains `skills/` | possibly hand-installed on the owner host |
  **Recommendation: do not delete or move any of them** (they are phase evidence and are consumed by tests/plans). If the owner wants them out of the way, the only safe action is `git mv` into `config/archive/` AFTER the verification below, in one commit, updating every referencing path.
  **How to verify before archiving any asset** (all read-only): (1) `cd /Users/parsa/AgentAI && git grep -n "<asset-name>" -- . ':!openclaw-project/evidence' ':!docs/codebase-audit'` and read every hit; (2) `rg -n "<asset-name>" openclaw-project/bin openclaw-project/platform openclaw-project/deploy` for scripts and code; (3) check JSON path references inside `plans/product/*.json` (`rg -n "config/phase" plans/product`); (4) confirm tests: `cd $P/platform && .venv/bin/python -m unittest tests.test_phase10_assets tests.test_phase12_assets tests.test_optimization` pass before the move and still pass after (they are in CI today); (5) ask the owner whether the server holds a hand-installed copy (`ls /opt/openclaw-production/config` TEXT, read-only) because `config/skills` and `workspace-templates` may be deployed by hand and a repo move would then hide the source of truth; (6) after the move, `git grep` for the old path must be empty except history docs.
- **Tests to add**: `platform/tests/test_orphan_decisions.py`: asserts the HIDE decisions (`memory`, `schedules`, `integrations`, `controls`, `streams`, `exports` kinds answer 503 `capability_not_enabled` through the Django test client, `customer_schedules` switch is `locked`), so a half-wired feature cannot go live by accident. For GX-017: `test_phase10_assets` already pins the consumed assets; nothing else is added.
- **Commands**: `cd $P/platform && AGENTAI_...env.. .venv/bin/python manage.py test accounts && .venv/bin/python -m unittest tests.test_orphan_decisions tests.test_phase10_assets tests.test_phase12_assets tests.test_optimization tests.test_policy_check tests.test_ops_rotation tests.test_broker tests.test_durable`.
- **Acceptance**: decision recorded per module in `ORPHANED_CODE.md`; HIDE tests green; no file deleted.
- **Rollback**: `git revert` (docs and one test).
- **Risks**: removing an "orphan" breaks `ops/restore.py` table lists and tests; `config/skills`/`workspace-templates` may be live on the owner host; the hostile-injection samples in `phase11-fixtures` must never be fed to a live model by a new loader.
- **Do not**: no deletion of any module in this list or any `config/` asset; do not run `bin/phase6/*`, `p4_*`, or `p15_acceptance.py`; do not add a loader that executes the hostile fixtures.
- **Commit message**: `Record orphaned-module decisions and pin hidden features with tests (M-05, GX-017)`.

---

## Owner decisions collected from this file (ask once, in this order)

1. P3-4: cap `chat_send` at 30/hour like goal/retry (BE-017), or not? (Default: not; "no new per-task limits".) Telegram: finish (A) or hide (B)? (Recommend hide.)
2. P3-5: the six retention questions (messages by last activity or creation; what the customer sees; tasks/results text; other tables; artifacts untouched; run time). Nothing is deleted until answered and a dry-run is reviewed.
3. P3-6: should `AGENTAI_GOAL_CHAIN_LIMIT` really control the goal cap (wire) or be removed?
4. P3-7: cap the post-run usage wait at 15 s while another account waits? (Default: leave.)
5. P3-9: confirm the logging policy "exception class names and code locations yes, messages never".
6. P3-10 / P3-11: approve the read-only capture commands, and a quiet window for sandbox stages.
7. P3-12: do you still use the owner OpenClaw assistant pages (sessions, approvals, schedules, memory, integrations)?
8. P3-13: expose or delete `ArtifactService.add_version` (BG-017); terminal status wording for stopped plans (BG-029); IPv6 state of the host (BG-022).
9. P3-14: OK to run `git gc` (after the push decision P0-5); asset strategy A/B/C.
10. P4-1: freeze native browser (A) or fund the eval and a canary (B)? P4-4: does the vault/saved-card feature ship now? P4-3: archive `lumina-character` after the port? P4-2: re-implement PlanBlock in the new design system? P4-5: plain FIFO across customers? P4-6: ship `0031_safety.sql` through `release.py`? P4-7: spend a release cycle on the no-behaviour-change refactor? P4-8: which parked feature is next?
