# Structure audit: dependencies, duplication, tests, repo hygiene, doc drift (scope ST)

## Scope & method

Covered: dependency manifests and lockfiles; cross-cutting duplication; test inventory and CI coverage; top-level repo clutter; documentation drift (13 specific claims checked).
Branch `product-phases-6-11`. Uncommitted work in `tool_origin*`, `tool_relay*`, `cell_bridge`, `cell_config` is in progress and not judged.

Tools:
- `which ruff vulture mypy tsc knip madge` found none on PATH.
- A vulture binary exists inside the project venv: `platform/.venv/bin/vulture`. I ran it read-only: `vulture agentai_platform accounts --min-confidence 80 --exclude '*/migrations/*'`, plus a 60% run for context.
- The 60% run produced 241 lines. About 95% of them are Django `Command`/`Meta`/middleware classes and adapter/Protocol classes that are used dynamically. Treat it as noise, not a dead-code list.
- No type checker or linter was run. No network audit was run. Nothing was installed.
- `git`, `grep`, `ast`, `wc` and `du` were used.

Not checked:
- Production state, which is UNVERIFIED throughout.
- Any systemd unit's live status.
- Whether `jev-browser` actually runs.
- Contents of `ssk-key*` (never opened).

## File/module map

| path | responsibility | consumers/entry | notes |
|---|---|---|---|
| `requirements-local.txt` | `python-dotenv==1.2.3` only | `bin/*.py` (5 import dotenv) | `bin/phase6/authorize-google.py:12` also imports `mcp`, which is not declared anywhere |
| `platform/requirements.lock` | Hash-pinned: Django 5.2.17, django-otp 1.7.3, gunicorn 26.2.0, cryptography 50.0.2, cffi, asgiref, sqlparse, packaging, pycparser | CI, deploy `release.py` | No `pyproject`; no unpinned input file (`requirements.in`) |
| `lumina/package.json` and lock | Production SPA (React 19.3, vite 8.3.5, vitest 5.0.5, zod 4.6.7, mermaid, katex, three) | Built by deploy | 42 `*.test.*` files |
| `lumina-character/package.json` and lock | Tracked fork of `lumina` (see ST-002) | Nothing in deploy/CI | zod 4.6.5, vite 8.3.1, vitest 5.0.2; no mermaid/katex |
| `browse/package.json` | `playwright-core` 1.49.1 only | `browse/runner.mjs` | `node --test`; 2 test files |
| `dashboard/app.py` (1718 LOC) | Stdlib-only owner ops dashboard (HTTP server, cookies/HMAC, SSH/subprocess actions) | `bin/open-ops-dashboard.py`, `bin/update-ops-dashboard.py` | 71 top-level defs/classes; test file 457 LOC |
| `bin/` (16 files plus `phase4/`, `phase6/`) | Owner-Mac helper scripts: ssh/scp wrappers, backups, deploy-lumina, Telegram activation, connector management | Humans, RUNBOOK | See ST-009 |
| `config/phase*.batch.json`, `phase4/10/11-fixtures`, `phase5/`, `phase6/` | OpenClaw config batches and acceptance fixtures for historical phases | `evidence/` manifests, RUNBOOK, plans | Historical (see ST-009) |
| `platform/deploy/` | systemd units, Caddy, cells-docker, installers, `p4_*`, `p15_acceptance.py`, `release.py` | Deploy | 18 unit/timer files; docs name only 11 (ST-013) |
| `plans/` | 19 phase plans plus `product/` (phase-01..15, JSON evidence) | Humans | `plans/phase-*.md` are from September and describe the pre-product state |
| `docs/orchestration-audit/` | Earlier audit (9 docs) | Reference | `docs/codebase-audit/` is this audit |
| `.github/workflows/platform.yml` (git root) | The only CI | push/PR | Runs a hand-picked subset (ST-001) |
| `evidence/` | 183 tracked files, 1.5 MB | Manifests | Includes `.log` and `.png` |
| `research/` (12K), `research-opt/` (168K), `browser-opt/` (120K), `experiments/` (96K, untracked), `reviews/` (8K), `backups/` (496K, gitignored), `tmp/` (0B, gitignored) | Small side tracks | `research-opt/` and `browser-opt/` run in CI | Not a size problem |
| `../phase-prompts/`, `../product/` (git root) | Phase prompt plan and `CONTRACT.md` and costing | README references | Exist, so README links are valid |

## Features

None of my own. This scope audits cross-cutting structure rather than product features. Statuses for `lumina-character`, `jev-*` and `browser-opt` are given in the findings below.

## Findings

**ST-001** | CI / test gap | **High** | HIGH | M
- The CI platform job runs only 20 of 73 `platform/tests/test_*.py` modules, by an explicit allow-list.
- Not run in CI (53 modules): test_billing, test_browse* (10), test_browser_tool, test_cell_bridge, test_cell_config, test_ops_* (7), test_worker, test_routing, test_safety_gates, test_secrets_custody, test_native_run/runner, test_live, test_vault, test_tool_origin and others.
- Also not in CI: `dashboard/test_dashboard.py` is run; but `lumina` (42 vitest files), `browse/test` (2 files), `platform/tests/*.mjs` and the e2e tests are not run in CI at all.
- The workflow also never runs `tsc`, `vite build` or `check:design`.
- Evidence: `.github/workflows/platform.yml` (the `unittest tests.test_request_queue ...` line); `ls platform/tests/test_*.py` (73). Computed by diffing module names.
- Impact: billing, browse and ops regressions can merge unnoticed. The active hotfix areas (browse, chat, billing) are among the uncovered ones.
- Action: F (reliability). Switch to `unittest discover` with explicit skips. The tests that need `age`, Chrome or Linux already self-skip via `skipUnless`.
- Risk: some of the 53 may currently fail or need the sandbox. Run once locally first.

**ST-002** | Duplication / repo structure | **High** | HIGH | M
- `lumina-character/` is a second, tracked copy of the `lumina/` SPA (4,697 tracked files versus 4,701), including a duplicate OpenMoji asset tree and `.impeccable/review/*.png`.
- 88 `diff -rq` differences in `src/`. It has its own `package.json` and lock, and diverging versions (zod 4.6.5 vs 4.6.7, vite 8.3.1 vs 8.3.5, vitest 5.0.2 vs 5.0.5).
- Its `node_modules` is a symlink to `../lumina/node_modules` (untracked per git status, because `.gitignore`'s `node_modules/` does not match a symlink).
- Referenced by: only `docs/architecture/findings.md` and `docs/orchestration-audit/06-history-and-legacy.md`. Nothing in deploy, CI or `release.py`.
- History: 1 commit in 6 months (`d95b796`) versus 46 for `lumina`; last commit Oct 27.
- It has `AskBox.tsx` and its own `AGENTS.md`/`DESIGN.md`, so it looks like an in-progress alternative UI. That is a C product decision. Do not delete.
- Impact: repo bloat, and the risk that fixes land in the wrong copy.
- Action: C. Decide whether to promote or archive it. Make the symlink ignore pattern `node_modules` (no slash).

**ST-003** | Repo hygiene / secret exposure | **High** | HIGH | S
- `ssk-key` and `ssk-key.pub` sit untracked at the git root (`git status ??`).
- `git ls-files` is 0 and `git check-ignore` returns no match. The ignore patterns `*.key` and `*.pem` do not match these names.
- A single `git add -A` or `git add .` at the root would commit what the name suggests is a private key. I did not read the file.
- Action: F. Add `ssk-key*` to the root `.gitignore` or move the files out of the repo. Rotate if it was ever committed (`git log --all -- ssk-key` was not run).
- Also confirm ST-004 for similar accident risk.

**ST-004** | Repo hygiene | **Medium** | HIGH | S
- Untracked and not ignored at the git root: `jev-browser/` (24M), `jev-window-core/` (268K), `lumina-cost-audit/` (832K), `brag-output/`, `sonarqube-export/` (3.4M), `SONARQUBE-*.md`, 4 `jev-browser-*.tar.gz` (32K to 188K), `lumina-environment-v3-clips.zip` (242M), `openmoji-svg-color.zip` (5.1M), and 6 loose screenshots (1.2 to 1.7M each).
- `.gitignore` covers `*.tar.gz` only in `openclaw-project/.gitignore`, not at root, so the tarballs show as `??`.
- None are tracked. Total about 280M of untracked clutter beside a 351M `.git`.
- Risk: accidental `git add -A`, and a cluttered `git status`.
- Action: A/C. Move to a sibling directory or add ignores. Nothing here is required by the platform.

**ST-005** | Relation of jev-* to platform | **Low** | MEDIUM | S
- `jev-browser/` (an experimental "bare loop": goal, screenshot, model, one action) and `jev-window-core/` (Swift macOS window control) have no imports from or to `platform/`, `lumina/` or `browse/`. The only hits for these names are in `docs/orchestration-audit/*`.
- The unrelated "Jev" in `platform/agentai_platform/optimization.py:20` (`MODEL = 'jev-1.13.0'`, a remote TypeSafe model, DISABLED) and `browser-opt/` is a different artefact that shares the name.
- Status: EXPERIMENTAL / ORPHANED relative to the platform. Per rules, a C decision, not a deletion.

**ST-006** | Dependency debt | **Medium** | HIGH | S
- `mcp` (and `workspace-mcp` command) is imported by `bin/phase6/authorize-google.py:12-13` and is declared nowhere. `requirements-local.txt` lists only python-dotenv.
- README claims "helpers require only requirements-local.txt" (`README.md`, "Current local credentials..." paragraph). That is false for this script.
- Action: D/doc. Declare it, or note the optional extra.

**ST-007** | Dependency pinning consistency | **Low** | HIGH | S
- `lumina` mixes exact pins with caret ranges: `react-markdown ^10.1.0`, `remark-gfm ^4.0.1` (also in `lumina-character`). The lock fixes them, but `npm install` without `ci` can drift.
- `browse` pins `playwright-core 1.49.1`, a release from about late 2024 (version-based impression only; no audit run). Verify whether it is deliberate, because the runner's Chromium compatibility is pinned.
- Python: `requirements.lock` is complete and hashed (good); there is no input file, so upgrades have no source of truth.
- Declared versus imported: third-party imports in application code (Django, django_otp, gunicorn, cryptography) all match the lock. `packaging`, `sqlparse`, `pycparser`, `cffi` and `asgiref` are transitive.
- CI uses Python 3.12 while the local venv is 3.14. Both are inside the README's "3.12-3.14".

**ST-008** | God files | **Medium** | HIGH | L
- `dashboard/app.py` is 1718 LOC with 71 top-level definitions: HTTP server, HMAC session cookies, CSRF, HTML rendering strings, SSH/subprocess actions and state in one module. It has its own `now_iso()` (`dashboard/app.py:98`) and its own compare_digest auth.
- `platform/agentai_platform/chat_driver.py` is 907 LOC. `browse/ladder.py` is 701, `billing.py` 683, `browse/service.py` 654, `lifecycle/cell_bridge.py` 583 (in progress), `connectors.py` 544, `chat.py` 505.
- The dashboard is stdlib-only by design (`ARCHITECTURE.md:166-168`), which is why it does not share platform helpers. It is a separate deployment (not in `platform/deploy/*.service`), so it is a different tier rather than a duplicate. It has 10 commits in 6 months.
- Action: E, low urgency. If splitting, start with the HTML templates.

**ST-009** | One-off phase scripts | **Low** | MEDIUM | S
- Referenced only from `bin/`, plans/evidence or RUNBOOK text (counts via `git grep -F basename`, excluding the audit docs).
- Zero references anywhere: `bin/phase4/build-sdk-image.sh`, `bin/phase6/prepare-server.py` (171 LOC). They may be run by hand, so UNKNOWN rather than dead.
- Referenced by evidence manifests only (historical): `config/phase4/10/11-fixtures`, `config/*.batch.json`, `platform/deploy/p4_*_check.py` (8 to 9 refs each, mostly docs/evidence), `platform/deploy/p15_acceptance.py` (394 LOC, 5 refs).
- Most are historical acceptance tooling. Classification: LEGACY (kept as evidence). Option: move into an `archive/` folder. Action: A after maintainer confirmation.

**ST-010** | Logging inconsistency | **Medium** | HIGH | M
- Only 7 modules use `logging.getLogger` across `platform/agentai_platform`, `platform/accounts` and `dashboard`.
- 17 library modules use bare `print(` (for example `server.py`, `chat.py` is not one; `accounts/views.py`, `middleware.py`, `billing.py`, `telegram.py`, `browse/trace.py`, `live/gateway.py`).
- Combined with 126 `except Exception` sites in the same tree, of which about 39 have a bare `pass` on the following line (heuristic, not a full AST count), failures are partly unlogged.
- Impact: harder incident forensics. Privacy-wise, fewer log lines is safer, so any fix must be redaction-aware.
- Action: B/F. Introduce one logger helper with redaction before adding calls.

**ST-011** | Cross-cutting duplication (small) | **Low** | MEDIUM | M
- HTTP clients: only 5 files call `urlopen` (telegram, dashboard, bin/activate-telegram, release, prepare_native_cli) and one uses `http.client` (`routing/classifier.py`). No shared client; each has its own timeout/error handling. Low volume, so low risk.
- Env loading: two hand-rolled `.env` parsers, `bin/owner-console.py:45 load_env` and `platform/deploy/release.py:40 read_env`. The platform settings use `os.environ` (39 reads in `accounts/settings.py`).
- Time: 11 hardcoded `%Y-%m-%dT%H:%M:%S` formats in 5 files, `dashboard.now_iso`, and `billing._now`, with no shared util.
- Atomic file write: 17 files use `os.replace`, with only `storage.write_private` and `switches._write` named as helpers. This may be intentional isolation of owner and customer code (see the privacy memory).
- sqlite: raw `sqlite3.connect` in 12 modules besides Django ORM. `store.py` is the main entry, but `ops/*` and `lifecycle/*` each open their own connection.
- Action: B only where it reduces risk. Do not couple the dashboard to the platform.

**ST-012** | Dead-code signal (vulture >=80%) | **Low** | MEDIUM | S
- Hits (all 80+ confidence; not verified for dynamic use):
  - unused imports: `accounts/middleware.py:7` (`RequestDataTooBig`, `TooManyFieldsSent`), `accounts/views.py:88` (`AnonymousUser`), `agentai_platform/chat_driver.py:20` (`activity_mod`)
  - unused variables: `browse/service.py:146` (`start_picker`), `lifecycle/profiles.py:38` (`running_cells`), `server.py:96` (`signum`, signal handler arg: fine), `accounts/delivery.py:5` (`email_messages`), `tool_origin_install.py:9` (`g`; in-progress)
- `activity_mod` and `RequestDataTooBig` may be re-export or patch targets in tests: check with `grep` before removal. Class dead-code hits at 60% are not trustworthy (see Scope).
- Action: A.

**ST-013** | Doc drift: deploy units | **Medium** | HIGH | S
- 18 unit/timer files exist in `platform/deploy/`. These seven are not named in `OPERATIONS.md`, `RUNBOOK.md` or `deploy/README.md`: `agentai-billing-worker.service`, `agentai-ops-backup.service`, `agentai-ops-monitor.service`, `agentai-platform-app.service`, `agentai-platform-control.service`, `agentai-supervisor.service`, `agentai-tool-relay.service`.
- Several are named only through their timer, so this is partly a grep artefact. `agentai-tool-relay.service` is in-progress.
- The docs name `agentai-model-proxy.service`, which exists under `deploy/model-proxy/` (not a missing file).
- Action: doc only.

**ST-014** | Doc drift: README/RUNBOOK stale status | **Medium** | HIGH | S
- `README.md`: "Product Phases 1-2 now deliver... verified by 14 targeted checks"; "Next implementation phase 4"; "Customer accounts/provisioning/chat/billing remain subsequent product phases". Meanwhile `BUILD_LOG.md:1561-1589` records Phases 4, 13 and 14 built, and plans reach phase-15; recent commits cover chat, genui and browse reliability.
- `README.md` says "Legacy AgentAI code/docs are removed" (fine) and "the Mac is not a runtime dependency" (fine).
- `RUNBOOK.md:1-35` has a header that still describes "Phases 1-3 ... no persistent platform listener installed" and "next build phase4 requires a new request" (`RUNBOOK.md:35`), while BUILD_LOG says the new host is live.
- `ARCHITECTURE.md:1-45` is accreted by dated blocks ("Latest increment: Phase 6"); it admits "Historical sections ... retain their earlier labels". Its status line "Phase 4 ... browser and ACP acceptance remain pending" predates the new-host Phase 4 of 2026-10-12.
- Impact: a newcomer or the next agent reads the wrong current state. Action: doc.

**ST-015** | Doc drift: platform/README | **Low** | HIGH | S
- `platform/README.md` says "exact pure-Python dependencies and hashes in requirements.lock". The lock itself says cryptography and cffi are compiled wheels (`requirements.lock:2-3`).
- The README test commands (`tests/check_account_concurrency.py`, `check_account_http.py`, `test_foundation.py`, `test_chat`, `test_gateway`) all exist, so those claims hold.
- "The application now uses Django accounts and Gunicorn; the earlier stdlib server is retained solely for private foundation/control fixtures" holds: `server.py` still serves `--service control`, and `agentai-platform-control.service` exists. Control is "hard-disabled" (not verified).

**ST-016** | Doc drift verified OK (spot checks) | n/a
- `product/CONTRACT.md:13,71` says $15 rolling 24h and $5 per task. `product/plan.json:8` has `daily_provider_cost_usd: "15.00"`, and commit `42cb3fd` matches.
- But `ARCHITECTURE.md:11` and `CONTRACT.md:166` still say "$79/$25/$5" without the daily line, and the README never mentions $15. Consistent enough; not drift.
- `BUILD_LOG.md` latest entries are dated 2026-10-12, but git shows work through Oct 27 (browser reliability, tool_origin) with no BUILD_LOG entry for the last two weeks: 25 BUILD_LOG commits in 6 months, with `docs/browser-reliability.md` carrying the newer record instead.
- Test counts in BUILD_LOG ("421 platform / 79 Django / 35 dashboard tests pass") versus today: 1163 `def test_` across `platform/tests`, `platform/accounts` and `dashboard`. Not comparable without running; only the `test_`-def total is known here.

**ST-017** | Tests: skips and shape | **Low** | HIGH | S
- Skips are all environment-gated `unittest.skipUnless`: `age` missing (4 in `test_ops_backup.py`, `test_ops_cli.py`), Chrome (`test_browse_modes.py:263`, `e2e/test_native_browser.py:56`), the OpenClaw package (`e2e/test_native_e2e.py:23`) and Linux `SO_PEERCRED` (`test_supervisor.py:177,192`).
- No `xfail`, `.skip`, `.todo` or `.only` in lumina or browse tests.
- On macOS, the supervisor peer-credential, age backup and e2e tests silently skip. CI (ubuntu) lacks `age`, Chrome and the OpenClaw package, so backup/restore and browser e2e are never executed anywhere automatically (compounds ST-001).

**ST-018** | Tests: churn without coverage | **Medium** | MEDIUM | M
- Top churn in the last 6 months (git log): `lumina/src/styles/app.css` 29, `chat.py` 23, `Chat.tsx` 21, `browse/loop.py` 16, `accounts/urls.py` 16, `openapi.json` 14, `browse/ladder.py` 14.
- Weakly or indirectly covered (by a test-file name mention count, a crude proxy):
  - `accounts/middleware.py` has 0 test files that mention it (7 commits; it holds `BoundaryMiddleware` and `AccountMiddleware`, the request-boundary logic). It is likely exercised through the Django test client, but it is unverified.
  - `browse/service_main.py` 1 file, `accounts/urls.py` 1, `lifecycle/fleet_driver.py` 3, `lifecycle/coordinator.py` 5.
  - Frontend files with no sibling test: `pages/Info.tsx` (8 commits), `pages/Home.tsx` (7), `components/TaskStrip.tsx` (7), `App.tsx` (7). `Chat.test.tsx`, `Shell.test.tsx` and `api.test.ts` exist.
- Mitigation: `platform/tests/` has 78 files and 14 more in `accounts/test_*.py`. The platform is well covered overall; these are the gaps.
- Action: add a middleware boundary test (a privacy-relevant request-size and boundary check).

**ST-019** | Tests: implementation-detail assertions | **Low** | LOW | M
- Some tests assert on source text and wiring. `test_phase10_assets` and `test_phase12_assets` check static phase asset files. `lumina/tests/` holds screenshot preview scripts (`preview_*.py`, `browser-layout.js`) that are not automated assertions.
- Not sampled in depth. LOW confidence. The finding is that CI-listed "assets" tests pin historical fixtures (`config/phase*`), so they tie CI to the files in ST-009.

**ST-020** | Hygiene: evidence / logs in git | **Low** | HIGH | S
- 183 tracked files under `evidence/`, including `.log` files (`evidence/browser-reliability/*/*.log`, `evidence/deployments/*/*.log`) and screenshots. `.gitignore` ignores `logs/`, not `*.log`.
- `lumina-character/.impeccable/review/*.png` and critique markdown are tracked.
- I did not read the logs, so whether they contain customer data or secrets is unknown. Given the privacy priority, a grep for emails or tokens is recommended.
- `openclaw-project/.gitignore` has `.env` twice (harmless).
- Action: F, check only.

**ST-021** | Stale plans | **Low** | MEDIUM | S
- `plans/phase-4.md` through `phase-10.md` are from Sep 26 to 29 (`plans/phase-4.md` last commit 2026-09-28), written for the pre-product owner runtime (Gate 3 "recorded exception").
- `plans/remaining-build-items.md` (Phase 7 inventory, 2026-09-27) lists ACP reviewer and native coding as GAP/PARTIAL. Product phases moved on; the status of these items is unknown.
- `plans/product/*` is current through phase-15, and README states "Historical plans/evidence keep old numbers", so the drift is documented. Classification: LEGACY. Preserve.

## Looks bad but is fine

1. `dashboard/app.py` at 1718 LOC does not use platform helpers. It is a deliberately stdlib-only, separately deployed owner tool (`ARCHITECTURE.md:166`). Its duplicated helpers (time, HMAC) are the price of isolation.
2. The vulture 60% output (241 lines of "unused class `Command`/`Meta`/`Middleware`") is Django's dynamic loading (management commands, `MIDDLEWARE` settings), not dead code.
3. `requirements.lock` has only 11 lines but is correct: it is hash-pinned with `--no-deps`, and the project deliberately avoids a larger dependency tree. No known-risk versions are identifiable from the versions alone (Django 5.2.x LTS line).
4. Many `config/phase*` files and `platform/deploy/p4_*` scripts look like clutter, but evidence manifests cite them as acceptance records. Moving them would break provenance.
5. `lumina-character/node_modules` shows as untracked because it is a symlink into `lumina/node_modules`, not a copy (no 2x disk use).
6. The `skipUnless` tests are not hidden failures: each skip states its precondition.

## Cross-scope links

- CI covers 20 of 73 platform test modules (ST-001). The lead should map this against the testing/ops scopes, particularly billing, browse and ops tests.
- `lumina-character` vs `lumina` (ST-002) is relevant to the frontend scope: confirm which one `release.py` and `deploy-lumina.py` build.
- `ssk-key*` (ST-003) is relevant to the security scope. Check whether any deploy doc references the key file name.
- Undocumented units (ST-013) and the `agentai-tool-relay.service` (in progress) belong to the ops and deploy scope.
- `bin/phase6/authorize-google.py` imports `mcp` (ST-006), linked to the connectors scope.

## Open questions for the maintainer

1. Is `lumina-character` the intended next UI (promote and merge), or an experiment to archive?
2. Should CI run the full discover suite and the vitest and `browse` tests? Is the allow-list deliberate for speed?
3. Are `ssk-key` and `ssk-key.pub` an SSH deploy key? Were they ever committed on any branch or backed up elsewhere?
4. Where should `jev-browser`, `jev-window-core`, the zips and the tarballs live: outside the repo, or ignored?
5. Are `bin/phase6/prepare-server.py` and `bin/phase4/build-sdk-image.sh` still used?
6. Is `BUILD_LOG.md` still the status source of truth, given no entry since 2026-10-12 while work continued to 10-27?
7. Is `playwright-core` 1.49.1 pinned on purpose?
