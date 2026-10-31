# Findings: everything outside openclaw-project/ (SCOPE OP)

Branch product-phases-6-11 (HEAD 03662de). Read-only audit. Production state UNVERIFIED throughout (no SSH/network).

## 1. Scope & method

Covered: `jev-browser/`, `jev-window-core/`, 4 `jev-browser-*.tar.gz`, `lumina-cost-audit/`, `brag-output/`, `sonarqube-export/` + `SONARQUBE-*.md`, `product/`, `phase-prompts/`, `.github/workflows/platform.yml`, root `README.md`, `.gitignore`, `CLAUDE.local.md`, `.claude/`, two zips, loose PNGs, `ssk-key`/`ssk-key.pub`.
Tools: `ls`, `du`, `git ls-files`, `git check-ignore -v`, `git worktree list`, `tar -tzf` (listing only, nothing extracted), `unzip -l`, `rg/grep`, `sed -n`, `wc`.
Not done: `ssk-key` contents never read (only `ls -l`, `git`, and the first token of the `.pub` file: `ssh-ed25519`). `.claude/` transcripts/memory not read; `.claude/settings.local.json` read for its first ~600 bytes only (allow-list of Bash commands incl. ssh/scp to the `lumina` host). Did not run any tests, did not run jev-* code, did not open the PNGs, did not open the zips beyond a listing. Sonar `issues.json` not parsed in full; I used `SONARQUBE-REPORT.md` and checked the current code at the cited files.

## 2. File/module map

| path | responsibility | consumers/entry | notes |
|---|---|---|---|
| `README.md` (3 KB, tracked) | root readme | humans | see OP-016 |
| `.gitignore` | ignores `.env`, `.env.*`, `*.pem`, `*.key`, `.venv`, `logs/`, `data/`, `backups/`, `skills/`, `node_modules/`, sqlite | git | does NOT match `ssk-key`, `*.png`, `*.zip`, `*.tar.gz`, `jev-*`, `.claude/` |
| `CLAUDE.local.md` | local-only Claude guidance (cbm index workflow, blind spots) | Claude Code | untracked? it is not in `git ls-files`, and not in `git status` list, so it is ignored/excluded elsewhere (not verified how) |
| `.github/workflows/platform.yml` | single CI job "Customer platform" | push + PR | see OP-009 |
| `product/` (96 KB, 11 tracked files + `marketing/`, `__pycache__`) | customer offer: `CONTRACT.md`, `COST_CAPACITY.md`, `EXAMPLE_TASK.md`, `EXISTING_VPS_TRIAL.md`, `SCREENS.md`, `plan.json` (numeric source of truth), `cost-inputs.json`, `cost-results.json`, `calculate_costs.py`, `deployment-policy.json`, `wireframes.html` | `plan.json` read by `platform/deploy/billing_install.py:140` and `platform/tests/test_billing.py:17`; `calculate_costs.py` reads `plan.json`+`cost-inputs.json` | `product/marketing/` untracked (not examined) |
| `phase-prompts/` (164 KB, tracked) | 19 numbered phase prompts + `final_phase.md` (deferred items F1-F13), coverage ledger, execution contract, super-agent prompt | human/agent prompts; referenced from `openclaw-project/plans/product/LAUNCH.md` | |
| `jev-browser/` (24 MB, UNTRACKED) | "bare loop" prototype: goal, Chrome screenshot, JEV model picks an action, repeat. Python stdlib + Node CDP runner, ~2.2 kLOC (`jevbrowse/{loop,jev,browser,dashboard,log,goal}.py`, `runner/runner.mjs`, `web/index.html`, tests) | `python -m jevbrowse "<goal>"` | .venv 13 MB, logs 10 MB (26 jsonl), `.env` (ignored by its own `.gitignore`) |
| `jev-browser-{pre-remodel,v2-complex,v3-before-reset,v4-with-playwright}.tar.gz` (29-192 KB, UNTRACKED) | snapshots of the above | none | see section 5 |
| `jev-window-core/` (268 KB, UNTRACKED) | extract of the loop that drives an existing macOS window (Swift helper `Window.swift` 295 LOC, `loop.py`, `model.py`, `run.py`, tests) | `python3 run.py '<prompt>'` | compiled `.build/jev-window` present; `.env` ignored by its own `.gitignore` |
| `lumina-cost-audit/` (832 KB, UNTRACKED) | read-only analysis of production usage and browser requests: `LUMINA_COST_AUDIT.md` (2026-10-20), `lumina_cost_audit.json`, `OWNER_USAGE_2026-10-27.md`, `browsing-audit-20261027/`, `browsing-audit-20261028/` (+`dinner/` evidence), `browsing-log-20261028/` (`BROWSING-REQUESTS.md`, `JEV-REQUESTS.md`, json; mode 600) | none (no code in `product/` or `platform/` references it; only audit docs do) | derived from owner-account production data |
| `brag-output/composition/` (32 KB, UNTRACKED) | Hyperframes launch-video project scaffold (`index.html`, `hyperframes.json`, `AGENTS.md`) | `/brag` skill | marketing artefact, not product |
| `sonarqube-export/` (3.4 MB, UNTRACKED) | raw SonarQube JSON export (`issues.json`, `rules.json`, measures, hotspots, quality gate) | input to `SONARQUBE-FIX-PROMPT.md` | |
| `SONARQUBE-REPORT.md` (50 KB), `SONARQUBE-FIX-PROMPT.md` (6 KB) (UNTRACKED) | readable report and an instruction prompt for an AI fixer | | see OP-010..012 |
| `.claude/` (573 MB, UNTRACKED) | `settings.local.json` (4 KB) + `worktrees/` (573 MB, 14 git worktrees, see OP-013) | Claude Code | |
| `lumina-environment-v3-clips.zip` (242 MB, UNTRACKED) | 34 files: `clips/*_enter/_exit/_event.mp4`, `loops/*.mp4`, `lumina_states.json`, `join-scores.csv`, README (creature animation clips for the chat film) | none in git (the live app serves its film from `/var/www/lumina-scenes` per commit 4bdf03c) | |
| `openmoji-svg-color.zip` (5.4 MB, UNTRACKED) | 4495 OpenMoji SVGs | `.claude/worktrees/openmoji` and `lumina/public` emoji (indexed as not-indexed assets) | vendored asset archive |
| 6 loose PNGs (`image*.png`, `Screenshot ... .png`, `5BAEE604-....PNG`; 1.2-1.8 MB each, UNTRACKED) | ad-hoc screenshots | none | not opened |
| `ssk-key`, `ssk-key.pub` | SSH keypair (ed25519 per `.pub` prefix) | unknown | see OP-001 |
| `.venv/` (root) | python venv | ignored by `.gitignore` | |

## 3. Features

| ID | name | status | flags | frontend | backend | evidence | prod verified? | notes |
|---|---|---|---|---|---|---|---|---|
| FEAT-OP-01 | jev-browser bare-loop prototype | EXPERIMENTAL | UNTRACKED, SUPERSEDED | web/index.html dashboard | `jevbrowse/*.py` + `runner/runner.mjs` | `jev-browser/README.md:1-12`; no references from `openclaw-project/{platform,browse,lumina,bin}` (grep `jev-browser` returns only audit docs) | n/a | production browser uses `browse/runner.mjs` (different code) and `platform/agentai_platform/browse/*` |
| FEAT-OP-02 | jev-window-core macOS window loop | EXPERIMENTAL | UNTRACKED | none | `loop.py`, `Window.swift` | `jev-window-core/README.md:3` | n/a | |
| FEAT-OP-03 | CI workflow | ACTIVE | PARTIAL COVERAGE | | `.github/workflows/platform.yml` | file read | unknown whether GitHub runs are green | OP-009 |
| FEAT-OP-04 | product/plan.json to billing | ACTIVE | | | `platform/deploy/billing_install.py:140`, `agentai_platform/billing.py:190-193` | `plan_from_plan_json` | unknown | plan consumed at deploy and in tests |
| FEAT-OP-05 | lumina-cost-audit | LEGACY (snapshot analysis) | UNTRACKED | | none | no code consumer | n/a | OP-007 |
| FEAT-OP-06 | cost model (`calculate_costs.py`) | ACTIVE-as-docs | scenario arithmetic only | | `product/calculate_costs.py` ("never used as the task admission guard") | | n/a | `cost-results.json` has `actual_*: null` (placeholder, never updated with measured data, while `lumina-cost-audit` now has measured per-task numbers) |

## 4. Findings

- **ID**: OP-001 | **Category**: Security hygiene | **Severity**: High | **Confidence**: HIGH | **Effort**: S
  Untracked private key at the repo root with no ignore rule. `ssk-key` (399 bytes, mode `-rw-------`) and `ssk-key.pub` (91 bytes, `ssh-ed25519`) sit at `/Users/parsa/AgentAI/`. `git check-ignore -v ssk-key ssk-key.pub` prints nothing (not ignored); `git ls-files ssk-key ssk-key.pub` prints nothing (not tracked); `git log --all -- ssk-key` shows no history. `.gitignore` has `*.key` and `*.pem` but the name `ssk-key` matches neither. A single `git add -A` or `git add .` would stage it. Contents never read. Whether it is the key behind the `lumina` ssh host (the allow-list in `.claude/settings.local.json` uses `ssh lumina`) is unknown.
  Impact: accidental commit/push of a private key; only protection is human care. Action: **F** add a `ssk-key*` (or `*-key`) rule or move the key to `~/.ssh`; confirm it is not already pushed (`git log --all` shows not). Risk: none.

- **ID**: OP-002 | **Category**: Repo hygiene | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
  Large untracked blobs and sensitive-ish artefacts sit at the root with no ignore rules: `lumina-environment-v3-clips.zip` (242 MB), `openmoji-svg-color.zip`, 4 tarballs, 6 PNGs (~8 MB), `.claude/` (573 MB), `jev-browser/`, `jev-window-core/`, `lumina-cost-audit/`, `sonarqube-export/`, `brag-output/`. 28+ entries in `git status` as `??`. Only `.env` files inside jev-* are protected, by those directories' own `.gitignore`. Risk is `git add -A` pulling 800+ MB and `lumina-cost-audit/` (owner-account request logs) into history. Action: **C/F** decide keep-outside-repo vs ignore; add ignore rules. Evidence: `git ls-files jev-browser jev-window-core lumina-cost-audit brag-output sonarqube-export | wc -l` = 0.

- **ID**: OP-003 | **Category**: Privacy | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: S
  `lumina-cost-audit/browsing-log-20261028/{BROWSING-REQUESTS.md,JEV-REQUESTS.md,browsing-requests.json,source.json}` (mode 600, dir 700) and `browsing-audit-20261028/dinner/{native-evidence.txt,request-evidence.txt}` are exports of the owner account's browser requests. Header says "Scope: all retained browser records for your configured owner account". Owner data only, but this is request-level content, untracked and un-ignored, in the same tree as the product. I did not read beyond the first lines. Action: **F** ignore or relocate before any commit; the project rule (memory: privacy over task guardrails) favours keeping such logs out of git.

- **ID**: OP-004 | **Category**: Duplication / provenance | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  `jev-browser/` is NOT referenced by production code and is not a package, service or copy used by the platform. In `openclaw-project`, "JEV" is an external hosted vision/choice model from TypeSafe (`platform/agentai_platform/optimization.py:20` `MODEL='jev-1.13.0'`; `browser-opt/config.json` `jev-1.13.0`; README of jev-browser says `jev-1.14.0` with `TYPESAFE_API_KEY`), called over HTTP from `browse/`, `routing/`, `browser-opt/jev_adapter.py`, `genui` display. `grep -rn 'jev-browser\|jev-window' openclaw-project` (excluding node_modules/evidence) hits only audit docs. `openclaw-project/browse/runner.mjs` (345 LOC) vs `jev-browser/runner/runner.mjs` (353 LOC): top-level function names differ substantially (jev-browser has `act/look/shot/settle/ensureTab/...`; project has `main/fingerprint/...`), so not a verbatim copy. The platform's `browse/{goals,session,trace,untrusted,ladder,candidates,loop}.py` share file names with the `pre-remodel` tarball's `jevbrowse/engine/*`, suggesting lineage (observed naming overlap only; derivation not proven, same caveat as `docs/orchestration-audit/02-path-registry.md` P38). Action: **G/C** keep as design history; decide location (OP-002).

- **ID**: OP-005 | **Category**: Version history | **Severity**: Info | **Confidence**: HIGH | **Effort**: -
  jev-browser snapshots (file lists only; sizes from `ls -l`):
  - `pre-remodel` (Oct 19 16:23, 110 KB, 49 entries): `jevbrowse/{server,compat,models,demo,runs,__main__}.py` + `engine/{trace,goals,untrusted,session,loop,candidates,ladder}.py`, `runner/runner.mjs`, `fixtures/`, `web/index.html`, `sync.sh`, `runs/` with 3 run dirs, `tests/test_app.py`. A server-based app with an "engine" package.
  - `v2-complex` (17:15, 71 KB, 37): flat modules `planner, run, server, config, models, discovery, budget, policy, actions, decide, engine, observe, record, verify, runner_client, privacy`, tests `test_units.py`+`test_app.py`. Planner/budget/policy-heavy.
  - `v3-before-reset` (17:32, 192 KB, 66): same families plus `goal.py`, 6 run dirs (`record.jsonl`/`trace.jsonl`/`live.jpg`). Larger mostly because of run data.
  - `v4-with-playwright` (18:50, 29 KB, 22): reduced to `jev.py, log.py, browser.py, dashboard.py, loop.py, goal.py, __main__.py`, `runner/{runner.mjs,_probe.mjs}`, tests `test_dashboard.py`+`test_loop.py`. Name notwithstanding, current README says no packages at all (CDP direct); `_probe.mjs` exists only in v4.
  - Current working dir (Oct 19 20:15): same module set as v4 minus `_probe.mjs`; README states "no planner, no second model; features get added back one at a time".
  Trajectory: complex multi-component agent, then deliberate reset to a bare loop in one afternoon. `jev-window-core` (Oct 23) is a further extraction of the bare loop to a native window.

- **ID**: OP-006 | **Category**: Secrets | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  `jev-browser/.env` (253 B, mode 600) and `jev-window-core/.env` (126 B, mode 600) exist and are ignored by each directory's own `.gitignore` (`git status --ignored` shows `!!`). Values not read. The jev-browser tarballs list only `.env.example`, not `.env`, so no secret in the archives per the file lists. But protection depends on the nested `.gitignore` files, which sit in untracked directories; if those dirs were committed with `git add -f` or the nested ignore were removed, `.env` is only covered by the root rule `.env` (which also matches, since root `.gitignore` has `.env` without a slash). Fine in practice; noted for completeness.

- **ID**: OP-007 | **Category**: Doc/analysis drift | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  `lumina-cost-audit` is an analysis OF production data (95 task attempts, 2026-10-12 to 10-20; avg $0.0478/attempt, $0.0640 per success; "monthly fixed overhead UNKNOWN"), written after the product code, and consumed by nothing in `product/` or `platform/`. In contrast `product/cost-results.json` still has `actual_complete_task_cost: null` and `actual_monthly_service_cost: null`, and `COST_CAPACITY.md` uses hypothetical assumptions. The measured per-task cost (about $0.05-0.06) is far below the $5 per-task cap and the $0.278 "base" research-route scenario, so the product cost model has not been reconciled with the audit. Action: **C** product decision whether to feed audit numbers into `cost-inputs.json`.

- **ID**: OP-008 | **Category**: Contract vs implementation | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: M
  Spot-check of `product/plan.json` / `CONTRACT.md` against code (14 claims):
  1. $79/mo, $25 included, $15/24h, $5/task: loaded from plan.json by `billing.py:190-193` (`daily_provider_cost_usd`, `max_task_cost_usd`); commit 42cb3fd raised daily $5 to $15 and docs agree (CONTRACT.md:13,71; no stale `$5 per 24h` found by grep). MATCH.
  2. max_queued_tasks 3: `billing.py:193`, enforced at `budget.py:80`. MATCH.
  3. max_projects 10: `accounts/chat.py:27` `MAX_PROJECTS=10`, `accounts/api.py:79`. MATCH (hard-coded duplicate of plan.json, comment says so).
  4. max_message_characters 16000: `accounts/chat.py:165`, `accounts/requests.py:18`, `telegram.py:220`. MATCH (three hard-coded copies).
  5. max_upload_bytes 10 MiB: `agentai_platform/files.py:21`, `accounts/files.py:25`. MATCH.
  6. batch 25 MiB / 10 files: `files.py:22-23`. MATCH.
  7. max_stream_connections 3: `events.py:25`. MATCH.
  8. trial $1, 7 days, 1 project: `seed_trial.py` ("seven-day/$1", `daily_microusd 1000000`). MATCH in spirit; `trial_days` as a number not re-read from plan.json (not verified).
  9. max_running_tasks 1: serial queue exists (LAUNCH.md "serial task queue"); `ops/monitor.py:30` `max_running_cells: 1`. Plausible; no explicit `max_running_tasks` read from plan.json (grep finds none).
  10. max_task_duration_seconds 3600: NOT found. `routing/config.py:21` sets default `max_task_duration_seconds 1800` and `max_task_cost_usd 1.00` (differs from plan's $5/3600 s); `chat_driver.py:35` `PARK_LIMIT=1800`. DRIFT, two independent sets of task limits (routing config vs plan). Not verified which is authoritative at runtime.
  11. max_task_steps 60 / max_model_calls 30 / max_search_requests 20: no enforcement found by grep (only `browse/adapter.py:76 MAX_STEPS = 12` for browser plans). UNVERIFIED/possibly unenforced.
  12. max_storage_bytes 2 GiB / max_zip_uncompressed 250 MiB / max_artifact 100 MiB: storage quota exists (`files.py:102` "storage quota exceeded"); the specific constants not found by my grep for `2147483648`. UNVERIFIED.
  13. automatic_overage false: `plan.json`; billing blocks on exhaustion per CONTRACT.md:70; consistent with LAUNCH.md. MATCH (docs).
  14. `plan.json` `status: owner_selected_not_live` and `CONTRACT.md:3` "not a live offer" vs `plans/product/LAUNCH.md:3` "Production runs launch1". Wording stale relative to the deployed trial/open-access state (Stripe not yet configured per LAUNCH.md item 2, so "not live" for paid is still true). Action: **C** refresh status text.
  Duplicated constants (items 3-5, 7) mean plan.json edits do not propagate automatically; only prices/daily/task/queue are wired. Action: **B**.

- **ID**: OP-009 | **Category**: CI gaps | **Severity**: Medium | **Confidence**: HIGH | **Effort**: M
  `.github/workflows/platform.yml` runs on push and PR, ubuntu, py3.12 + node 22, `pip install --require-hashes -r requirements.lock`. Steps: Django `manage.py test accounts`; a hand-listed set of 21 `unittest` modules under `platform/tests`; `node deploy/vercel/check.mjs`; browser-opt, research-opt and dashboard unit tests offline. Misses: (a) the `lumina/` React/TypeScript app (no `npm test`, `tsc`, `eslint` or build; `lumina/src/**/*.test.tsx` exist, e.g. `Chat.test.tsx`, `Live.test.tsx`, `Tasks.test.tsx`); (b) `browse/test/` runner tests; (c) `platform/tests/tool_origin_plugin.test.mjs` (new, uncommitted); (d) `platform/tests/e2e/*` (reasonable: needs infra); (e) any `platform/tests/test_*.py` not named in the hand-written list (e.g. `test_billing`, `test_browser_tool`, `test_tool_origin`, `test_browse_modes`, `test_live`, `test_service_handoff` appear absent from the list; needs `ls platform/tests` cross-check by the other investigator); (f) no lint/type/security step (no ruff, no pip-audit, no SonarQube), (g) no deploy/release job. Because the list is explicit, new test files silently never run in CI. Action: **E/D** switch to discovery (`unittest discover`) plus a Lumina `npm ci && tsc && vitest/npm test && build` job. Risk: tests may be env-dependent.

- **ID**: OP-010 | **Category**: Static-analysis status | **Severity**: Info | **Confidence**: HIGH | **Effort**: -
  Sonar scan (2026-10-13, 32,074 lines, quality gate OK per `quality_gate_status.json`): 28 vulnerabilities, 52 bugs, 709 code smells; 789 issues total. Vulnerabilities are CSRF-exempt endpoints (5 modules), `/tmp` use (3), clear-text `http://` literals (11, mostly localhost/test), disabled TLS verification in `dev_local_ui.py`, hard-coded dev password, f-string SQL, world-accessible chmod. `SONARQUBE-FIX-PROMPT.md` instructs an AI to make minimal fixes, "do not touch files outside openclaw-project, the screenshots, .claude/", no commits. It hands over an 80%+ noise list: most items are by-design (see OP-012).

- **ID**: OP-011 | **Category**: Still-present check | **Severity**: Low | **Confidence**: HIGH | **Effort**: -
  Spot-check of 14 Sonar items against current code (line numbers drifted since the report; I matched by content):
  1. `accounts/billing.py:145` `@csrf_exempt def webhook` PRESENT (Stripe webhook; signature-verified, by design).
  2. `accounts/streams.py:68` `@csrf_exempt def stream` PRESENT.
  3. `accounts/telegram.py:93` `@csrf_exempt def webhook` PRESENT (secret-token webhook).
  4. `accounts/files.py` csrf_exempt: now one at line 172 (report cited 4 lines, 73/107/164/205; the line shift and a single current hit suggest it was partly refactored or the report counted differently; `files.py` last changed 07fd6b9).
  5. `dev_local_ui.py:78-80` `check_hostname=False`, `CERT_NONE` PRESENT (loopback dev helper, probing `127.0.0.1`).
  6. `dev_local_ui.py:20` `PASSWORD = 'Local-UI-Preview-2026!'` with `local-ui@example.invalid` PRESENT (dev-only credential in a tracked file).
  7. `accounts/views.py:281` f-string `SELECT 1 FROM {table}` PRESENT (table name interpolated; whether `table` is from a fixed allow-list not verified).
  8. `accounts/views.py:37` `assets(request,name)` PRESENT (restricts by ASSETS dict; fine).
  9. `switches.py:207` `os.chmod(tmp, 0o644)` PRESENT, comment says no secrets.
  10. `browse/service.py:519` `os.chmod(out_dir, 0o777)` PRESENT (comment: stage runs as uid 1000, dir holds only screenshots). World-writable directory shared with a container.
  11. `browse/runner.mjs:12` `BROWSE_OUT || '/tmp/out'` PRESENT.
  12. `bin/phase6/manage-connectors.py:115` `staging = "/tmp/connect-tool-"+run_id+".json"` PRESENT (docker cp staging path; predictable name under /tmp).
  13. `lifecycle/cell_config.py:17` http literal: comment line exists, file modified (uncommitted work).
  14. Report is not newer than code: SONARQUBE-REPORT.md was never committed or re-run (mtime Oct 13; code has 20+ commits since).
  Conclusion: none of the sampled vulnerability findings has been fixed; the report was not acted on (no commit references it).

- **ID**: OP-012 | **Category**: Triage | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  Which Sonar items matter: CSRF-exempt webhook/stream endpoints are by design if they authenticate by signature/token/session header (not verified here; belongs to the platform investigator). `0o777` on the browse out dir (OP-011 #10) and the predictable `/tmp` staging name (#12) are the only ones with a plausible privacy angle (other local users or containers on the VPS reading screenshots). Per memory "privacy over task guardrails", prioritise those two. The rest are noise or dev-only.

- **ID**: OP-013 | **Category**: Repo hygiene | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
  `.claude/worktrees/` holds 14 registered git worktrees (`git worktree list`): botcheck, emoji-jev, fastclick, jev-tune, live-view, lumina-layout-stability, notes, notes2, openmoji, orbs, product-images, release, smooth-scroll (174 MB), thinking-branch. 573 MB total, each on its own `worktree-*` branch. These are stale experiments (branch names such as `worktree-emoji-jev`, `worktree-jev-tune` relate to JEV). `.git` is 351 MB. Not ignored (`?? .claude/`). A `git worktree` checkout under the main tree means recursive tools (rg, cbm index, sonar, `find`) see duplicated source; the audit's grep needs excludes. Action: **A** prune merged worktrees after checking each branch for unmerged commits (not examined here). Risk: losing unmerged work.

- **ID**: OP-014 | **Category**: Phase status | **Severity**: Info | **Confidence**: MEDIUM | **Effort**: -
  Status of the 19 prompts in `phase-prompts/openclaw/` per `plans/product/phase-NN.md` status lines, `BUILD_LOG.md`, `LAUNCH.md` (production side unverified):
  | phase | state | evidence |
  |---|---|---|
  | 1 product contract | implemented (design READY) | BUILD_LOG "Product Phases 1-2"; `product/CONTRACT.md` |
  | 2 platform foundation | implemented (private foundation READY) | same |
  | 3 customer accounts | implemented, "activation blocked" at that time | BUILD_LOG Phase 3 entry; later live per LAUNCH.md |
  | 4 tenant provisioning | PARTIAL (native acceptance NOT_RUN); later driver work | BUILD_LOG top entries |
  | 5 usage/admission | implemented core (budget.py, billing.py); PARTIAL per 4/5 entry | BUILD_LOG 09-30 entry |
  | 6 dashboard chat | build READY; live native chat dependent | `phase-06.md` |
  | 7 Telegram linking | build READY; real bot linking deferred (F5) | `phase-07.md`, `final_phase.md` |
  | 8 files/artifacts | build READY; uploads disabled by default (scan not wired) | `phase-08.md` |
  | 9 live work | build READY; fail-closed | `phase-09.md`; live viewer has code (`live/*`) |
  | 10 native capabilities | build complete offline; activation BLOCKED | `phase-10.md`; F2 Claude Code agent |
  | 11 integrations | build complete offline; all services DISCONNECTED | `phase-11.md` |
  | 12 optional optimization build | optional build complete; adapters DISABLED | `phase-12.md` (but note: JEV routing/display switches are described ON in LAUNCH.md) |
  | 13 billing | implementation READY, acceptance NOT_RUN; Stripe account/keys not created | `phase-13.md`, LAUNCH.md item 2 |
  | 14 operations | READY, deployed; off-server backup (F1) still a launch blocker | `phase-14.md`, LAUNCH.md item 4 |
  | 15 system acceptance | PARTIAL: 21 PASS, 2 BLOCKED, 7 NOT_RUN | `phase-15.md:status` |
  | 16 optional optimization evaluation | NOT started (paid benchmark needs owner go) | LAUNCH.md "Needs a go" |
  | 17 private beta | NOT started | LAUNCH.md |
  | 18 launch | NOT started | LAUNCH.md |
  | 19 optional purchases | NOT started; browser purchasing locked (`credentialed_browsing`, F3) | `final_phase.md` |
  `final_phase.md` records F1-F13 deferred items. Note: there is no `plans/product/phase-16..19.md`; their prompts live only in `phase-prompts/`.

- **ID**: OP-015 | **Category**: Doc drift | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  `plans/product/LAUNCH.md:6` says "JEV routing (switch ON, record-only)", and `final_phase.md` F4 says "Chat routing is currently OFF and browser JEV runs in record-only mode", while code comments and commits say the browser steps ARE decided by JEV (`lifecycle/cell_config.py:15` "the browser's steps no longer use [Haiku]: JEV decides them", commit 825ecee "Browser JEV rework: picture mode (JEV 1.14)"; `optimization.py:20` still says `jev-1.13.0`, "DISABLED" in its docstring, while jev-browser/README and commit mention 1.14). Three documents give three different states for JEV. Which is true in production is unverified. Action: **C**.

- **ID**: OP-016 | **Category**: Doc drift | **Severity**: Low | **Confidence**: LOW | **Effort**: S
  Root `README.md` (3 KB, last modified Oct 5, earlier than most work including generative UI, browser reliability, tool origin) was not reconciled with the later structure (Lumina rename, `lumina/`, `browse/`, `jev-*`, `product/`). Content not fully reviewed here; flagging by age only.

- **ID**: OP-017 | **Category**: Experiment placement | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  `openclaw-project/experiments/jev-full-page/` (untracked) is an inside-project JEV experiment; with `jev-browser/` and `jev-window-core/` that makes three separate JEV prototypes in three places, none tracked. Action: **C** consolidate into one `experiments/` home or archive.

- **ID**: OP-018 | **Category**: Reproducibility | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  `jev-browser/.venv` (13 MB) and `jev-browser/logs` (10 MB, 26 run logs) plus `jev-window-core/.build/jev-window` (compiled binary) and `__pycache__` are build/runtime state inside the prototype dirs; logs hold run content from live browsing (page-derived data) though outside git. Safe to delete if the prototypes are archived. Class **A** after owner confirms.

## 5. Looks bad but is fine

1. `jev-browser/` is not a dependency of production, despite the name and tarballs: production JEV is the hosted TypeSafe model called over HTTPS from `platform/agentai_platform/{optimization,browse,routing}` and `browser-opt/`; no code path imports or shells to it.
2. `product/calculate_costs.py` has `actual_* = null` and `hypothetical_*` fields: intentional; module docstring says "Scenario arithmetic only; never used as the task admission guard". Real guards are `budget.py`/`billing.py` using microusd integers.
3. Four near-duplicate tarballs: they are intentional snapshots of different architectures (pre-remodel engine, v2 planner, v3 pre-reset, v4 minimal), not accidental copies; the file lists differ materially.
4. `@csrf_exempt` on `billing.webhook` and `telegram.webhook`: webhook endpoints cannot carry a CSRF token; Sonar flags them mechanically. (Authentication of each not verified in this scope.)
5. `dev_local_ui.py` `CERT_NONE` and the hard-coded password on `example.invalid`: loopback preview tool for local UI, not shipped to customers (by name and content; deployment of this file not verified).
6. `ssk-key` mode 600 and absent from git history: no leak so far; the finding (OP-001) is about the missing guard, not an observed leak.

## 6. Cross-scope links

- `product/plan.json` consumed by `platform/deploy/billing_install.py:140`, `platform/tests/test_billing.py:17`, `product/calculate_costs.py`; duplicated constants in `accounts/chat.py:27`, `accounts/api.py:79`, `accounts/chat.py:165`, `accounts/requests.py:18`, `events.py:25`, `files.py:21-23`. Platform investigator should verify limits: max_task_duration (1800 vs 3600), task cost 1.00 vs 5.00 in `routing/config.py:21`, steps/model calls/search caps (OP-008 #10-12).
- CI list in `platform.yml` vs `platform/tests/` and `lumina/src/**/*.test.tsx`, `browse/test/`: frontend and platform investigators should report which tests are not run in CI.
- Sonar items in `platform/accounts/*`, `browse/service.py:519` (0o777), `browse/runner.mjs:12`, `bin/phase6/manage-connectors.py:115`, `dev_local_ui.py`: platform/browse investigators.
- JEV state in `switches.py:64` (`jev_routing`), `:77` (`jev_display`), `optimization.py:20` (model version) vs docs (OP-015).
- Uncommitted work (tool_origin, tool_relay, cell_bridge, `tool_origin_plugin/`) is not covered by `platform.yml` (`tool_origin_plugin.test.mjs` is not run); treated as in-progress.
- `docs/orchestration-audit/*` and `_findings/structure.md` already describe jev-browser/jev-window-core as unreferenced prototypes; consistent with this file.

## 7. Open questions for the maintainer

1. What is `ssk-key`? Is it the key for the `lumina` host? Should it move to `~/.ssh` and be rotated if it was ever shared?
2. Should jev-browser, jev-window-core, lumina-cost-audit, the zips, PNGs and tarballs be committed (as `experiments/` or `archive/`), ignored, or moved out of the tree?
3. Which of the 14 `.claude/worktrees` branches contain unmerged work worth keeping?
4. Is the product plan's `status: owner_selected_not_live` / CONTRACT "not a live offer" still the intended wording now that `launch1` is deployed to getlumina.pro?
5. Which limits are authoritative: `product/plan.json` (60 steps, 30 model calls, 3600 s, $5/task) or `routing/config.py` (1800 s, $1/task)? Are steps/model-call/search caps enforced at all?
6. Is JEV currently choosing browser actions in production (jev-1.14 picture mode) or record-only (LAUNCH.md)?
7. Should CI switch to test discovery and gain a Lumina frontend job? Should a periodic Sonar run be wired in?
8. Should `lumina-cost-audit` measured numbers update `product/cost-inputs.json`/`COST_CAPACITY.md`?
