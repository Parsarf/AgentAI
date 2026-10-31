# Audit coverage: what was and was not verified

> **UPDATE 2026-10-29:** production was verified over SSH after this document was written. Statements below that production is "unverified" are superseded for the items in [PRODUCTION_VERIFICATION_2026-10-29.md](PRODUCTION_VERIFICATION_2026-10-29.md) (live host is Hostinger `179.236.71.203`; IONOS is dead; IS-002 and the tool-origin v2 drift confirmed; IS-004 resolved; M-01 latent, not observed).

Audit date 2026-10-29. Branch `product-phases-6-11`, HEAD `03662de`, 132 commits. Scan root `/Users/parsa/AgentAI` (git root); project `openclaw-project/`. This audit was read-only. Production is UNVERIFIED (L-01..L-03).

## 1. Coverage by scope

| Scope (findings file) | Read fully | Skimmed / targeted | Not read |
|---|---|---|---|
| Backend (`backend.md`, BE-001..024) | `accounts/{urls,views,middleware,services,models,api,settings,chat,files,streams,safety,vault,media,uishell,browse,signup,telegram,connections,lifecycle,requests,usage,billing}.py`; `agentai_platform/{request_queue,request_worker,billing,budget,switches,security,store,capacity,ssrf}.py` | `vault.py` head; most of `chat.py` and `connectors.py`; 13 management commands; 30 SQL migrations and 15 Django migrations (structure and shim pattern); `openapi.json` by script | internals of `gateway.py`, `events.py`, `artifacts.py`, `files.py` (service), `storage.py`, `genui/*` (HTTP surface and a skim), `routing/*`, `ops/*` (only `restore.py` SQL and import graph) |
| Orchestration (`orchestration.md`, AG-001..022) | `chat_driver.py`, `gateway.py`, `request_queue.py`, `request_worker.py`, `outcome.py`, `goals.py`, `tool_relay.py`, `browse/adapter.py`, `lifecycle/tool_origin*.py`, `lifecycle/cell_config.py` | `browse/{service,loop,ladder,native_runner}.py`, `lifecycle/{worker,coordinator,sleep,cell_bridge}.py`, `chat.py`, `budget.py`, `routing/*`, `genui/runner.py`, `config/*`, `browser-opt/`, `research-opt/`, `experiments/`, `evals/`, deploy units | OpenClaw 2026.9.6 internals; runtime behavior; `lumina/` |
| Frontend (`frontend.md`, FE-001..020) | structure of `lumina/src`, `lumina-character/src`, `platform/ui-reference` (grep, scripts, selected files) | `gen/*` (about 2.9k lines) by grep; CSS; tests by name | `lumina/public` (22 MB assets), `lumina-character/public` (61 MB), vendored `thinking-orbs`; vitest and `vite build` not run; `npm audit` not run; runtime behavior |
| Infra/security (`infra_security.md`, IS-001..025) | `platform/deploy/*` units, Caddy, cells-docker, model-proxy, vercel, `release.py`; `deploy/*` compose; `ops/{hostconfig,inventory,monitor,exposure,restore,backup}.py`; `settings.py`, `middleware.py`; `tool_relay`, `live/*`, `privacy.py`; docs | `dashboard/app.py` auth/session/headers portions only (1718 LOC); `bin/*`; `RUNBOOK.md` grep; `BUILD_LOG.md` grep; `evidence/deployments/*` | Dockerfiles (`deploy/Dockerfile.*`) not read in depth; `config/skills`, workspace templates; 5 `evidence/phase-*` manifests; `platform/tests/e2e/harness.py` skimmed; VPS, Vercel project settings, DNS |
| Structure (`structure.md`, ST-001..021) | manifests and lockfiles, CI workflow, test inventory, root clutter, 13 doc claims | vulture at confidence 80 (and 60 for context) | linters/type checkers (not installed) |
| History (`history.md`, GH-001..018) | all 132 commit subjects, 16 branches, 9 `origin/*` refs, 14 worktrees, 12 tags, path histories | pattern-only secret scan across refs | stash list, reflog, dirty state of each worktree, remote tags, contents of untracked top-level folders |
| Outside project (`outside_project.md`, OP-001..018) | root `README.md`, `.gitignore`, CI workflow, `product/*`, `phase-prompts/`, jev-* structure, `SONARQUBE-REPORT.md` | tarballs listed (not extracted), zips listed, `lumina-cost-audit` first lines only | `ssk-key` contents, `.claude/` transcripts and memory, PNG screenshots, `product/marketing/`, `sonarqube-export/issues.json` in full |

## 2. Tools run

| Tool | Result |
|---|---|
| `tsc --noEmit` | exit 0 in both `lumina` and `lumina-character` (the fork was checked against lumina's `node_modules` via symlink) |
| `manage.py makemigrations --check --dry-run` | "No changes detected" (throwaway 0700 state dir in scratchpad) |
| `vulture` (venv binary `platform/.venv/bin/vulture`) | partial: confidence 80 produced a short list (ST-012); confidence 60 produced 241 lines, about 95% Django/Protocol noise |
| AST import graph (stdlib `ast`, `python -I`) | found modules with zero non-test importers (M-05) |
| Custom scripts | openapi vs `urls.py` diff; frontend path vs `urls.py` diff; env-var inventory by regex; route-to-test string match |
| `git` | log, show, diff, ls-files, check-ignore, worktree, tag, rev-list, `-G` secret-pattern scan |
| `rg`/`grep`/`sed -n`/`wc`/`du`/`ls`/`tar -tzf`/`unzip -l` | as needed |
| `ruff`, `mypy`, `knip`, `madge`, `gitleaks`, `pip-audit`, `npm audit` | NOT installed or not run |
| Test suites (unittest, Django `manage.py test`, vitest, `node --test`, e2e) | NOT run |
| `vite build`, `npm run check:design` | NOT run |

## 3. Gaps

1. **Production gap**: no SSH, no network. Every runtime impact, switch state, engine choice, deployed release, firewall state, TypeSafe key presence and cron job is unverified. See DEPLOYMENT_AUDIT.md.
2. **Backend modules not deep-audited**: `gateway.py`, `events.py`, `artifacts.py`, `storage.py`, `genui/*`, `routing/*`, `ops/*`. The "no IDOR found" statement covers the routes read only; it is not a clean bill.
3. **Frontend**: vitest, build and `check:design` were not run, so pass state is unknown; 20 or so hot files were judged by name matching.
4. **`evidence/` logs not reviewed** for emails, tokens or customer data (183 tracked files).
5. **`dashboard/app.py`**: only auth/session/header portions read (1718 LOC).
6. **`config/skills`, workspace templates, phase fixtures**: classified by importer search only.
7. **Dockerfiles** (`deploy/Dockerfile.sandbox|claude-code|sdk-peer`): not read in depth.
8. **`lumina-character`**: structural diff only; not read file by file.
9. **Vendored `thinking-orbs`**: not audited. **About 4,500 OpenMoji SVGs and film assets** (`lumina/public`, `lumina-character/public`) not inspected.
10. **Type debt is thin by construction**: only `tsc` exit 0 and `any` counts; no `mypy`, so Python type debt is unmeasured (the register has one Type debt row, FE-013).
11. **Performance** claims (poll rates, SQLite write lock, slot holds) are by reading code, not measurement.
12. **Untracked folders** (`jev-browser`, `jev-window-core`, `lumina-cost-audit`, `brag-output`, `product/marketing`): existence and structure only.
13. **Worktree dirty state** not checked; remote tags not checked; stash and reflog not checked.
14. **Uncommitted tool_origin / tool_relay / cell_bridge / cell_config work**: read, not judged; findings AG-006/008/019 are about its process and shape, not correctness.

## 4. Count caveats

- Severity totals are approximate: investigators rated independently and the lead did not recount precisely. The register has 125 rows (12 High, 40 Medium, 66 Low, 7 Info after the choices documented in `TECHNICAL_DEBT.md`); "after dedupe about 10-12 distinct High" in the reconciliation matches.
- **CI test count**: ST-001 counted 20 of 73 `platform/tests/test_*.py` modules in the allow-list; OP-009 counted 21. Re-reading the `unittest` line in `.github/workflows/platform.yml` while writing this document lists 20 modules (request_queue, lifecycle, supervisor, budget, capacity, foundation, fleet_driver, chat, gateway, telegram, files, events, native, policy_check, durable, phase10_assets, connectors, optimization, phase12_assets, switches), plus `manage.py test accounts`; OP's 21 probably includes the Django suite. Say "about 20 of 73". Note the list includes tests of ORPHANED modules (policy_check, durable, optimization) but excludes billing, browse, ops, cell and tool-origin tests.
- Test-def total (1163 `def test_`) is a count of definitions, not passing tests.
- Line numbers come from the investigators and drifted in places (the Sonar report line numbers are older than the code); they were not all re-verified. The lead re-verified M-01, M-02, M-03, M-11 and the CI count.
- `ST-016` (docs verified OK) is not counted as a debt row.

## 5. Integrity statements

- **ssk-key**: the infra investigator printed only the 40-byte PEM header (`head -c 40`) to confirm the file type; the outside-project investigator used `ls -l`/`git` and read only the first token of the `.pub` file. No one read the key body. This audit does not quote it.
- **Tracked application code was not modified**: at audit start `git status` showed 11 modified tracked files (the in-progress tool_origin/tool_relay/cell_bridge/cell_config/e2e/doc work); a check run while writing this document (`git status --porcelain`, count of modified tracked files) again shows the same 11. Only files under `docs/codebase-audit/` were created. The writers of this document ran no command that modifies the repo. (`manage.py makemigrations --check --dry-run` used a throwaway state directory and wrote nothing.)
- No server was contacted by this writer. The lead's earlier probes (L-03) executed no remote command.

## 6. Ways to finish (what to run next)

1. Unblock access and run the one-script checklist (DEPLOYMENT_AUDIT.md section 6) to resolve L-01 and every UNVERIFIED label.
2. Run the suites locally: `cd openclaw-project/platform && python -m unittest discover tests` (expect env skips and possibly some failures), `python manage.py test accounts`, `cd ../lumina && npm ci && npx tsc --noEmit && npx vitest run && npm run build`, `cd ../browse && node --test`.
3. Install and run `ruff`, `mypy`, `pip-audit`, `npm audit`, `gitleaks`; knip/madge for the frontend.
4. Deep-audit the unread backend modules (gateway, events, artifacts, storage, genui, routing, ops) with attention to tenant scoping.
5. Review `evidence/**/*.log` for customer data; grep for emails and token shapes.
6. Read the Dockerfiles, `config/skills`, workspace templates, and the rest of `dashboard/app.py`.
7. Check each of the 14 worktrees for uncommitted files before pruning.
8. Re-run the 14 Sonar spot-checks against the repository after Phase 1 fixes.

## 7. Phase-11 completeness checklist

| # | Item | Status | Note |
|---|---|---|---|
| 1 | All seven scopes investigated and written to `_findings/` | PASS | BE, AG, FE, IS, ST, GH, OP present |
| 2 | Reconciliation applied (M-01..M-12, L-01..L-03) and IDs consistent | PASS | master IDs used throughout |
| 3 | Findings carry file:line evidence | PASS | line numbers as cited by investigators; not all re-verified |
| 4 | Dedupe complete | PARTIAL | related pairs remain separate by choice (BE-013/AG-004, GH-013/IS-017, BE-021/IS-007 partly) |
| 5 | Production verified | FAIL | SSH failed (L-01..L-03); all runtime claims UNVERIFIED |
| 6 | Tests executed | FAIL | no suite run; pass state unknown |
| 7 | Static analysis / linters | PARTIAL | tsc, makemigrations --check, vulture partial; ruff/mypy/knip/madge not installed |
| 8 | Dependency vulnerability scan | FAIL | no network; pip-audit and npm audit not run |
| 9 | Secret scan | PARTIAL | regex on tracked files and history patterns; evidence logs and unprefixed secrets not covered; gitleaks not run |
| 10 | Git history reconstructed (eras, branches, tags, worktrees) | PASS | GH scope |
| 11 | Feature inventory classified (ACTIVE/LEGACY/ORPHANED/INCOMPLETE) | PARTIAL | per-scope tables exist; consolidated documents were written by other writers and were not re-checked here |
| 12 | Technical debt register with coverage of the 9 dimensions | PASS | TECHNICAL_DEBT.md; type debt thin (see gap 10) |
| 13 | Security and reliability risks grouped with privacy first | PASS | SECURITY_AND_RELIABILITY.md |
| 14 | Deployment audit with checklist and unblock steps | PASS | DEPLOYMENT_AUDIT.md; checklist unrun |
| 15 | Cleanup plan with dependencies, preserve list and do-not-do list | PASS | CLEANUP_PLAN.md; not executed |
| 16 | Skill-format deliverable (TECH_DEBT_AUDIT.md) | PASS | executive summary, findings table, top 5, quick wins, looks-bad-but-fine, open questions |
| 17 | No tracked application code modified | PASS | 11 modified tracked files, same as at start |
| 18 | No secret values reproduced | PASS | names and paths only; `ssk-key` body never read |
| 19 | Backend deep audit of gateway/events/artifacts/storage/genui/routing/ops | FAIL | explicitly not done |
| 20 | Frontend build/test pass state | FAIL | not run |
| 21 | Evidence logs reviewed for sensitive data | FAIL | not read |
| 22 | In-progress tool_origin work judged | PARTIAL | read and flagged (AG-006/008/019); correctness not judged by design |
| 23 | Other writers' deliverables (FEATURE_INVENTORY, LEGACY, ORPHANED, INCOMPLETE, DUPLICATIONS, SYSTEM_OVERVIEW, FILE_MAP, ARCHITECTURE, EXECUTION_FLOWS, DEPENDENCIES, CLAUDE.proposed) linked consistently | PARTIAL | IDs follow the same scheme; cross-links not verified by this writer |

---

## Update 2026-10-29 (run 2): gaps closed and what remains

**Closed since the first version**
- Production verified over SSH (read-only): `PRODUCTION_VERIFICATION_2026-10-29.md` (two passes; raw output `_findings/vps_readonly_2026-10-29.txt`).
- Backend modules not deep-audited before: `gateway.py`, `events.py`, `artifacts.py`, `files.py`, `storage.py`, `genui/*`, `routing/*`, `ops/*`, `live/*`, `vault.py`, most of `lifecycle/*` → `_findings/gap_backend.md` (BG-001..030 plus a verified-clean list). Executed three pure functions with `python3 -I` to confirm BG-001, BG-002, BG-012.
- `evidence/` (183 tracked files) reviewed for sensitive data: none found (infra addresses and local paths only); `dashboard/app.py` in full; `bin/`; Dockerfiles/compose/config; test-quality scan; lumina vs lumina-character divergence quantified; side directories; the jev prototypes → `_findings/gap_tooling.md` (GX-001..028).
- Checklist items now answered: LiteLLM logging/budget flags, cells engine runtime, sshd drop-ins, unit/port conflicts, drift of `runner.mjs`, Caddyfile and the deployed release against the working tree.

**Still not verified**
- Running-cell isolation (no cell was up), real TypeSafe payloads on the wire, backup restore, the owner's off-server copy, `accounts.env` values, the two quarantined restores' contents.
- `fleet_driver.py` and `supervisor.py` only skimmed; frontend rendering of model-written documents; the unopened PNG screenshots and the `backups/` tarball (listed, not opened); `jev-browser/logs` screenshots.
- No test suite or build was run (only `tsc --noEmit`, `makemigrations --check` and the small pure-function checks); linters (ruff, mypy, knip, madge) are not installed; `npm audit`/`pip-audit` need network and were not run.
- The cbm code graph was not used as evidence.

**Integrity**: no application code was modified (tracked-file status unchanged: the same 11 modified files as at session start). Local SSH keys were replaced at the owner's instruction; the server's `authorized_keys` was edited by the owner in the Hostinger terminal. The auditor ran only read-only commands on the server.

**Counts**: Register = 125 rows (first pass) + Supplement A (BG 30, GX 28, PV 8). Severity totals are approximate because investigators rated independently; no new High came from the gap work.
