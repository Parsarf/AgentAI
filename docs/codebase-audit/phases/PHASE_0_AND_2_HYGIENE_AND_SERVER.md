# Phase 0 and Phase 2: repo hygiene and server hardening (implementation specs)

Purpose: step-by-step specifications for tasks P0-1..P0-6 and P2-1..P2-5 of `HANDOFF.md`, plus the PV-09 note. Written for a cleanup AI with no other context. Everything here was checked against the working tree on 2026-10-29 (branch `product-phases-6-11`, HEAD `03662de`, uncommitted tool-origin work present). Server commands are TEXT for the owner to approve; nothing in this file was run against production. Owner priorities: customer privacy first, no new per-task limits, preserve unfinished work.

## Ordering and dependency graph

```
P0-1 (.gitignore) ──► P0-3 (commit tool-origin) ──► P0-4 (tags) ──► P0-5 (push decision)
P0-2 (list/decide) ─ independent, after P0-1          P0-6 (worktrees) ─ independent
P2-0 (key-based helper scripts, NEW prerequisite) ──► P2-1 (SSH hardening)
P2-0 ──► P2-2 (off-server backup + restore drill) ──► P2-3 (OS updates) 
P0-3 + P0-4 + P2-2 ──► P2-4 (cleanup of releases / tarballs)
P0-3 ──► P2-5 (gunicorn, tool_relay, release rule)  [tool_relay.py is dirty until P0-3 lands]
PV-09 (quarantined restores) ─ independent, read-only first
```
Recommended execution order: P0-1, P0-3, P0-4, P0-2, P0-6, P0-5 (gate), P2-0, P2-1, P2-2, P2-3, P2-5, P2-4, PV-09.

NEW prerequisite found while writing this (called **P2-0** below): every operator helper in `openclaw-project/bin` (`ssh-server`, `scp-server`, and through them `pull-backups.py`, `deploy-lumina.py`, `update-ops-dashboard.py`, `connect-tool`, `platform/deploy/billing_install.py`) logs in with a PASSWORD from `openclaw-project/.env` and defaults to the dead IONOS host `69.48.206.62` (`bin/ssh-server:20-22`, `bin/scp-server:20-22`). Turning off SSH password login (P2-1) breaks all of them, and today `pull-backups.py` cannot reach the Hostinger server at all unless `.env` overrides the host. P2-0 must land first.

## Pre-flight checklist (do before ANY task here)
1. `cd /Users/parsa/AgentAI && git branch --show-current` must print `product-phases-6-11`. `git log --oneline -1` must start with `03662de` (or later commits made by this plan).
2. `git status --porcelain` read once and kept: it must match the list in P0-3 (11 modified files, the untracked set in P0-1/P0-3). Anything else is unrelated work: stop and ask.
3. Never `git add -A` / `git add .` / `git commit -a`. Stage named paths only. No push, no force, no history rewrite.
4. Baseline tests (record pass/fail/skip counts before touching anything), from `/Users/parsa/AgentAI/openclaw-project/platform`:
```bash
.venv/bin/python -m unittest tests.test_tool_origin tests.test_browser_tool tests.test_cell_bridge tests.test_native tests.test_supervisor 2>&1 | tail -5
node --test tests/tool_origin_plugin.test.mjs 2>&1 | tail -8
# CI list (.github/workflows/platform.yml) for the wider baseline:
.venv/bin/python -m unittest tests.test_request_queue tests.test_lifecycle tests.test_supervisor tests.test_budget tests.test_capacity tests.test_foundation tests.test_fleet_driver tests.test_chat tests.test_gateway tests.test_telegram tests.test_files tests.test_events tests.test_native tests.test_policy_check tests.test_durable tests.test_phase10_assets tests.test_connectors tests.test_optimization tests.test_phase12_assets tests.test_switches 2>&1 | tail -5
```
`tests/e2e/*` skip without OpenClaw/Chrome; say so in reports. Known older failures on a clean checkout are listed in `RELEASE_NOTES.md` ("Known limits": `accounts.test_streams`, `tests.test_chat_history`).
5. Server work: `ssh lumina` is the only approved route (alias in `~/.ssh/config`, key `~/.ssh/lumina_ed25519`, `ControlMaster auto` is ON, which matters for P2-1). Production is the Hostinger VPS `srv2054170` (`179.236.71.203`).

---

## Phase 0

### P0-1: root `.gitignore` additions
- **Findings**: M-03, GH-002, OP-002, ST-004. **Finding check**: re-verified (HIGH). Two corrections to the handoff wording: (a) root `.gitignore` ALREADY ignores `backups/`, `logs/`, `data/`, `.env`, `.env.*` (except `.env.example`), `*.key`, `*.pem`, `*.sqlite3*`, `.venv/`, `dist/`, `build/` (root `.gitignore:1-37`); `openclaw-project/.gitignore:7` also ignores `backups/` and `*.tar.gz`; `jev-browser/.gitignore` ignores `logs/` and `.env`. (b) The handoff's `id_*` would also hide any future source file named `id_utils.py`; use the specific SSH key names instead. Handoff patterns `*.zip`/`*.tar.gz`/screenshots must be ANCHORED to the repo root, because tracked evidence pictures exist (`openclaw-project/evidence/generative-ui/*.png`, `openclaw-project/lumina*/.impeccable/review/*.png`) and new evidence in the same places must stay visible.
- **Goal / user-visible effect**: `git status` stops listing keys, archives, screenshots, exports and the `node_modules` symlink; no tracked file becomes hidden.
- **Depends on / blocks**: blocks P0-3 (so the `git add` lists are unambiguous). **GATE**: none for the patterns. Owner question only for the optional lines (see "Owner choices").
- **Files to change**: `/Users/parsa/AgentAI/.gitignore` (append; one line changed: line 33 `node_modules/`). **Read first**: `.gitignore`, `openclaw-project/.gitignore`, `openclaw-project/lumina-character/.gitignore` (`node_modules/`, `dist/`).
- **Current behaviour**: root `.gitignore:33` is `node_modules/`. A trailing slash matches directories only, so the symlink `openclaw-project/lumina-character/node_modules -> ../lumina/node_modules` (a symlink is not a directory) shows as `?? openclaw-project/lumina-character/node_modules` in `git status`, and the same happens as `?? openclaw-project/browse/node_modules` inside the worktrees `fastclick` and `live-view`. Nothing matches a bare key file such as the deleted `ssk-key` (no extension, so `*.key` missed it). Untracked clutter now: `.claude/` (573 MB, mostly worktrees), `brag-output/`, `sonarqube-export/`, `lumina-cost-audit/`, 4 `jev-browser-*.tar.gz`, 2 `.zip`, 6 root PNGs.
- **Change**:
  1. Replace `node_modules/` with `node_modules` (matches dir AND symlink at any depth).
  2. Append the block below. Explanation per pattern is in the comments.
```diff
 # local hosting configuration and private credential variants
 .vercel/
-node_modules/
+node_modules
 .env.*
 !.env.example
 *.sqlite3
 *.sqlite3-wal
 *.sqlite3-shm
 *.pem
 *.key
+
+# private keys that have no extension (the deleted `ssk-key` was one); SSH key file names are listed
+# explicitly instead of `id_*` so that source files like id_utils.py are never hidden
+ssk-key*
+*_key
+*-key
+*-key.pub
+id_rsa*
+id_ed25519*
+id_ecdsa*
+id_dsa*
+
+# local tooling and scratch output. Anchored with a leading slash so only the repo root is affected:
+# tracked evidence/ and .impeccable/ pictures and any future ones in those folders stay visible.
+.claude/
+/brag-output/
+/sonarqube-export/
+/lumina-cost-audit/
+/*.png
+/*.PNG
+/*.jpg
+/*.jpeg
+/*.zip
+/*.tgz
+/*.tar.gz
```
  3. Do NOT ignore: `docs/` (holds the audit, untracked until the owner commits it), `product/marketing/`, `jev-browser/`, `jev-window-core/`, `openclaw-project/experiments/` (see P0-2), `SONARQUBE-*.md` (owner choice).
- **Verified now (simulated with `git ls-files --exclude-from=<patterns>`, no file edited)**: `git ls-files -c -i --exclude-from=<the patterns above>` prints NOTHING (no tracked file would be hidden). The same patterns hide exactly: `.claude/`, `brag-output/`, `sonarqube-export/`, `lumina-cost-audit/`, the 6 root images, 4 `jev-browser-*.tar.gz`, 2 zips, and the `node_modules` entries. What stays untracked afterwards (29 `??` entries shrink to 12): `SONARQUBE-FIX-PROMPT.md`, `SONARQUBE-REPORT.md`, `docs/`, `jev-browser/`, `jev-window-core/`, `product/marketing/`, `openclaw-project/docs/browser-tool-ownership.md`, `openclaw-project/evidence/browser-ownership/`, `openclaw-project/experiments/`, `tool_origin_install.py`, `tool_origin_plugin/`, `tests/tool_origin_plugin.test.mjs`.
- **Tests / commands to run** (after editing; from `/Users/parsa/AgentAI`):
```bash
git ls-files -c -i --exclude-standard | head            # MUST print nothing (no tracked file is hidden)
git check-ignore -v ssk-key ssk-key.pub foo_key id_ed25519 .claude/worktrees/x \
  "image copy.png" jev-browser-v4-with-playwright.tar.gz openmoji-svg-color.zip \
  sonarqube-export/x brag-output/x lumina-cost-audit/x openclaw-project/lumina-character/node_modules
# each line must show .gitignore:<line>:<pattern>. These must print NOTHING (still visible):
git check-ignore -v openclaw-project/evidence/generative-ui/new.png openclaw-project/lumina/.impeccable/review/new.png docs/x product/marketing/x id_utils.py
git status --porcelain | grep -c '^??'                  # expected 12 (see list above)
```
- **Acceptance criteria**: the three commands behave as annotated; `git ls-files | wc -l` is unchanged from before the edit; `git worktree list` still shows 15 entries.
- **Rollback**: `git checkout -- .gitignore` (before commit) or `git revert`.
- **Risks / Do not**: do not use unanchored `*.png`, `*.zip`, `*.tgz` (hides future evidence); do not add `docs/` or `product/` ; do not `git rm --cached` anything in this task; ignoring does not untrack, so already-tracked files are unaffected by design. `core.ignorecase=true` on this Mac makes `/*.png` also match `.PNG`, but Linux CI does not, hence both lines.
- **Owner choices (optional lines, ask once)**: `/SONARQUBE-FIX-PROMPT.md`, `/SONARQUBE-REPORT.md` (ignore, commit under `docs/`, or delete); `/jev-browser/` and `/jev-window-core/` (24 MB / 268 KB prototypes with their own `.gitignore`; ignore, commit, or move out of the repo).
- **Commit message**: `Ignore keys, archives, local tooling output and the node_modules symlink at the repo root (M-03, GH-002, OP-002, ST-004)`

### P0-2: experiments/, backups/, jev-browser/logs, lumina-cost-audit/ (inventory + owner decision)
- **Findings**: GX-024, GX-025, GX-026. **Finding check**: sizes and status re-measured; `backups/` and `jev-browser/logs` are ALREADY ignored, only `experiments/` and `lumina-cost-audit/` are not. Names and sizes only below (no log contents were read).
- **Goal**: owner gets a table and decides ignore / move / delete per item. The cleanup AI deletes NOTHING.
- **GATE (ask the owner, per item)**: "For each of the four items below: keep in the repo (commit), ignore, move out of the repo to `~/AgentAI-archive/`, or delete?" Default recommendation is in the table.

| Item | Holds (names/sizes) | State | Recommendation |
|---|---|---|---|
| `openclaw-project/experiments/jev-full-page/` (96 KB) | `README.md` 8K, `run_live.py` 12K (mutates production: stops the request worker, submits one real task), `runtime.py` 12K, `probe_runner.py` 4K, `runner.mjs` 4K, `test_experiment.py` 8K, `test_runner.mjs` 4K, `__pycache__` (ignored) | untracked; source of the hand-installed overlay that ran on production 28 Oct 23:03 (PV-08) | **Commit it** as a record (it documents what ran in production) in its own commit, with a `README` line "NEVER run `run_live.py` without owner approval", OR move to `evidence/experiments/` . If the owner prefers it hidden: add `/openclaw-project/experiments/` to the root `.gitignore`. Do not delete (only local copy besides `/root/jev-full-page-*.tgz` on the server). |
| `openclaw-project/backups/` (496 KB) | `2026-09-24T01-15-27.824-07-00-openclaw-backup.tar.gz` 408K (mode 600, an OpenClaw state backup), `removed-by-native-migration-2026-10-26/` 88K with `pursuit-architecture.md`, `pursuit-baseline.md`, `pursuit-cleanup.md`, `pursuit-smoke-test.md`, `pursuit-validation.md` | already ignored (root and project `.gitignore`) | **Keep ignored.** Copy the whole folder once to the off-repo archive (`cp -a` to `~/AgentAI-archive/backups/`). The five `pursuit-*.md` are the only copies of removed docs (also in git history before d95b796); owner may commit them under `docs/archive/` instead. Never delete the tar.gz without owner OK (may hold state not elsewhere). |
| `jev-browser/logs` (10 MB, inside untracked `jev-browser/`, 24 MB) | 26 entries dated 2026-10-19: `YYYYMMDD-HHMMSS.jsonl` files (largest ~395 KB), matching per-run directories, and `latest.jsonl` | already ignored by `jev-browser/.gitignore:2`; may contain page text or URLs from test runs (privacy: treat as sensitive) | **Keep ignored; do not commit, do not upload.** Owner decides delete (recommended, it is a prototype log) or move to encrypted storage. Do not open the contents. |
| `lumina-cost-audit/` (832 KB) | `LUMINA_COST_AUDIT.md` 20K, `lumina_cost_audit.json` 32K, `OWNER_USAGE_2026-10-27.md` 4K, `browsing-audit-20261027/` 128K, `browsing-audit-20261028/` 80K, `browsing-log-20261028/` 568K (directory mode 700) | untracked at the repo root; the `browsing-*` folders look like per-run browsing evidence and may contain customer or owner page data | **Ignore (P0-1 already adds `/lumina-cost-audit/`)**; owner decides whether `LUMINA_COST_AUDIT.md` + `.json` are worth committing under `docs/` (they are summaries) and whether the `browsing-*` folders are deleted. Never commit the `browsing-*` folders without a privacy review. |

- **Commands (read-only) to re-measure**: `du -sh openclaw-project/experiments openclaw-project/backups jev-browser/logs lumina-cost-audit; ls -la <dir>` .
- **Acceptance**: owner's decisions recorded in the audit doc (`CLEANUP_PLAN.md` Phase 0 row); `git status` clean of these paths after P0-1.
- **Do not**: delete or move anything without the owner's per-item answer; do not run `experiments/jev-full-page/run_live.py`.
- **Commit message** (only if the owner chooses to commit `experiments/`): `Keep the full-page JEV experiment as a record of what ran in production on 28 Oct (GX-024, PV-08)`

### P0-3: commit the in-progress tool-origin work in logical commits
- **Findings**: AG-006, GH-005. **Finding check**: re-verified (HIGH): `git status --porcelain` shows 11 modified tracked files (307 insertions, 148 deletions) and these untracked product files: `tool_origin_install.py` (45 lines), `tool_origin_plugin/index.mjs` (62) + `openclaw.plugin.json` (1), `tests/tool_origin_plugin.test.mjs` (50), `openclaw-project/docs/browser-tool-ownership.md` (35), `openclaw-project/evidence/browser-ownership/20261028/` (144 KB of logs, `owner-acceptance.py`, `rollout.py`, `release.json`, sha256 manifests). The audit already showed production equals this tree.
- **Goal**: git history matches production exactly; later releases can be tagged and rebuilt from git.
- **Depends on**: P0-1. **Blocks**: P0-4, P2-5, every deploy. **GATE**: owner reviews the diff before the first commit ("Commit these 4 commits as proposed? Include `evidence/browser-ownership/` (it contains logs and two scripts that mutate production) or leave it untracked?").
- **Read first**: `git diff` of each file, `openclaw-project/docs/browser-tool-ownership.md`, `platform/tests/test_tool_origin.py`.
- **Coupling facts that decide the grouping** (verified by grep): `cell_config.py:63,139` imports `tool_origin_install` (so the installer + plugin must be committed first); `cell_bridge.py:482,489` imports `inspect_origin` from `tool_origin.py` (new function; `resolve` is kept with an optional `nonce`, `tool_origin.py:91`, so HEAD's old caller keeps working after commit 1); `tool_relay.py` (relay) now expects `{'origin','status'}` dicts and the management command (`accounts/management/commands/tool_relay.py`) sends the nonce, so these two move together with the bridge; `tests/test_tool_origin.py` imports `inspect_origin` and `tool_origin_install` and tests `cell_config` (its last test), so it belongs to commit 2, not 1.
- **Pre-flight (read-only)**:
```bash
cd /Users/parsa/AgentAI
git status --porcelain
git diff --stat
git diff --check                      # whitespace problems: must print nothing
```
- **Commit plan** (run each `git add` exactly; paths are from the repo root `/Users/parsa/AgentAI`):

**Commit 1: runtime hook (plugin + installer + proof core)**
```bash
git add openclaw-project/platform/agentai_platform/lifecycle/tool_origin.py \
        openclaw-project/platform/agentai_platform/lifecycle/tool_origin_install.py \
        openclaw-project/platform/agentai_platform/lifecycle/tool_origin_plugin/index.mjs \
        openclaw-project/platform/agentai_platform/lifecycle/tool_origin_plugin/openclaw.plugin.json \
        openclaw-project/platform/tests/tool_origin_plugin.test.mjs
git diff --cached --stat                # exactly 5 files
```
Tests before committing (from `openclaw-project/platform`): `node --test tests/tool_origin_plugin.test.mjs` and `.venv/bin/python -m py_compile agentai_platform/lifecycle/tool_origin.py agentai_platform/lifecycle/tool_origin_install.py`. (The Python unit file is committed in commit 2; at this commit only its first class `OriginChecks` can pass, so do not run the file.) Message: `Tool ownership: one-use runtime proof hook, installer and proof check (AG-006, GH-005)`

**Commit 2: relay, bridge and cell config wiring + their tests**
```bash
git add openclaw-project/platform/agentai_platform/lifecycle/cell_bridge.py \
        openclaw-project/platform/agentai_platform/lifecycle/cell_config.py \
        openclaw-project/platform/agentai_platform/tool_relay.py \
        openclaw-project/platform/accounts/management/commands/tool_relay.py \
        openclaw-project/platform/tests/test_tool_origin.py \
        openclaw-project/platform/tests/test_browser_tool.py
git diff --cached --stat                # exactly 6 files
```
Tests: `.venv/bin/python -m unittest tests.test_tool_origin tests.test_browser_tool tests.test_cell_bridge tests.test_native tests.test_supervisor` plus the CI list from the pre-flight. Message: `Tool relay binds each browser call to its admitted run through the cell bridge and nonce proof (AG-006)`

**Commit 3: end-to-end harness and stub model**
```bash
git add openclaw-project/platform/tests/e2e/harness.py \
        openclaw-project/platform/tests/e2e/stub_model.py \
        openclaw-project/platform/tests/e2e/test_native_e2e.py
git diff --cached --stat                # exactly 3 files
```
Tests: `.venv/bin/python -m unittest tests.e2e.test_native_e2e` (skips without OpenClaw; if it runs on the owner's machine, say so). Message: `E2E harness installs the ownership hook and stubs a browser tool call (AG-006)`

**Commit 4: docs**
```bash
git add openclaw-project/docs/browser-tool-ownership.md openclaw-project/docs/browser-reliability.md
git diff --cached --stat                # exactly 2 files
```
Message: `Document how a browser tool call proves which task owns it (GH-005)`

**Optional commit 5 (owner decision, privacy review first)**: `openclaw-project/evidence/browser-ownership/`. Before adding run: `rg -n -i -l "bearer|password|secret|token|api[_-]?key|authorization|cookie" openclaw-project/evidence/browser-ownership` and open any hit; remove or redact. The folder includes `rollout.py` and `owner-acceptance.py` (scripts that act on production): add the line "do not re-run" to a README or leave the folder untracked. Message: `Record the 28 Oct tool-origin v2 rollout evidence`
- **After each commit**: `git status --porcelain` shows only the remaining planned paths; after commit 4: only the non-product untracked items from P0-1.
- **Byte-for-byte check against production** (read-only; scp is a download; pattern for re-verifying; do it BEFORE commit 1 and AFTER commit 4):
```bash
S=$(mktemp -d /private/tmp/claude-501/lumina-verify.XXXXXX); cd "$S"
scp lumina:/root/lumina-tool-origin-v2.tgz lumina:/root/lumina-tool-origin-v2-supervisor.tgz .
for f in *.tgz; do tar -tzf "$f" | grep -E '(^/|(^|/)\.\./)' && echo "UNSAFE PATH in $f" ; done   # must print nothing
mkdir plat sup git; tar -xzf lumina-tool-origin-v2.tgz -C plat; tar -xzf lumina-tool-origin-v2-supervisor.tgz -C sup
# working tree (or, after the commits, the committed tree):
( cd /Users/parsa/AgentAI && git archive HEAD:openclaw-project/platform ) | tar -x -C git
diff -rq -x __pycache__ -x '*.pyc' -x .venv -x node_modules plat git | grep -v '^Only in git'
```
Accept only "Only in git" lines (tests, docs, deploy files that the tarball omits). Any `differ` or `Only in plat` line means production has something git does not: STOP and tell the owner. The scratch dir is untrusted data: extract with `tar` only, never run anything from it. Before the commits, replace the `git archive HEAD:...` line with `rsync -a --exclude __pycache__ --exclude .venv /Users/parsa/AgentAI/openclaw-project/platform/ git/`. The tarball layout (flat vs `platform/` prefix) is not documented; if the `diff` shows everything as Only in, compare `plat/<subdir>`.
- **Acceptance criteria**: 4 commits (+1 optional); `git status --porcelain | grep -v '^??'` empty; the verification above reports no `differ`; all listed suites pass (e2e skip allowed).
- **Rollback**: `git reset --soft HEAD~N` only for commits not pushed and not tagged, otherwise `git revert`. Nothing here touches production.
- **Risks / Do not**: do not `git add` anything under `__pycache__`; do not fold unrelated untracked folders into these commits; do not amend after tagging.

### P0-4: tag deployed commits
- **Findings**: GH-005, GH-001. **Finding check**: re-verified. Existing tags: `release/live1..live8`, `release/live5-browse`, `ui-parchment-v1`, `ui-pre-film`, `lumina-character-final`. Repo convention is `release/<name>`, so the handoff names `native1-4` etc. become `release/native1` (the deviation is deliberate). No tag exists after live8.
- **Evidence for the mapping** (read-only): `evidence/deployments/20261027T110435Z-genui-10efb73/deployment.json` (`commit: 10efb73`, previous release `safety1`), `.../20261027T114539Z-cancel-e700e33/deployment.json` (`commit: e700e33`), server release directory names (`20261028T014523Z-hardening-ef2a8ac`, `20261028T212308Z-tool-origin-v2`; vps listing `_findings/vps_readonly_2026-10-29.txt:323-470`), `RELEASE_NOTES.md:1-7` (safety1 deployed 27 Oct 06:44 UTC; "this shipped the uncommitted redesign in the working tree"), `git log` times (UTC): `d95b796` 27 Oct 09:07 UTC ("Remaining pending work in openclaw-project", the first commit containing native1-4 and safety1 code), `ef2a8ac` 28 Oct 01:44 UTC (the hardening release directory is stamped 01:45 UTC), `03662de` 28 Oct 22:29 UTC (UI bundle `lumina-ui-03662de` installed 22:30).
- **Important**: native1..native4 (26-27 Oct) and safety1 (27 Oct 06:44 UTC) were deployed from the uncommitted working tree BEFORE `d95b796` existed (09:07 UTC). `d95b796` is "the first commit that contains them", not proven to be identical. Proof step below; do NOT tag a guess as exact.

| Proposed tag | Commit | Confidence | Message text |
|---|---|---|---|
| `release/safety1` | `d95b796` | MEDIUM until verified | "safety1 (27 Oct 06:44 UTC). Deployed from the uncommitted tree; d95b796 is the first commit containing it." |
| `release/native4` | `d95b796` | MEDIUM until verified | same pattern |
| `release/native1`..`native3` | none unless verified | LOW | skip unless the diff proves it; else record in RELEASE_NOTES only |
| `release/genui-10efb73` | `10efb73` | HIGH (deployment.json) | "genui release 20261027T110435Z" |
| `release/cancel-e700e33` | `e700e33` | HIGH (deployment.json) | "cancel hotfix release 20261027T114539Z" |
| `release/hardening-ef2a8ac` | `ef2a8ac` | HIGH (dir name + time) | "hardening release 20261028T014523Z" |
| `release/tool-origin-v2` | the LAST commit of P0-3 (the docs commit; hash known only after P0-3) | HIGH after the P0-3 byte check | "tool-origin v2, production since 28 Oct 21:23 UTC; UI bundle 03662de" |

- **Proof step for safety1/native4** (read-only; owner runs or approves): 
```bash
S=$(mktemp -d /private/tmp/claude-501/lumina-tagproof.XXXXXX); cd "$S"; mkdir srv git
ssh lumina 'tar -C /opt/agentai-platform/releases/safety1 --exclude=.venv --exclude=__pycache__ -cf - .' | tar -x -C srv
( cd /Users/parsa/AgentAI && git archive d95b796:openclaw-project/platform ) | tar -x -C git
diff -rq srv git | grep -v '^Only in git'      # empty => safety1 == d95b796 (platform tree); repeat with native4 (also /opt/agentai-supervisor/releases/<id>)
```
Tag only the releases whose diff is empty; for the others add a line to `RELEASE_NOTES.md` instead ("deployed from the working tree; closest commit d95b796; not identical").
- **Commands (proposed, DO NOT RUN until the owner approves; annotated tags, local only)**:
```bash
cd /Users/parsa/AgentAI
git tag -a release/genui-10efb73     10efb73 -m "genui release 20261027T110435Z (production, verified by evidence/deployments)"
git tag -a release/cancel-e700e33    e700e33 -m "cancel hotfix release 20261027T114539Z"
git tag -a release/hardening-ef2a8ac ef2a8ac -m "hardening release 20261028T014523Z"
git tag -a release/safety1           d95b796 -m "safety1, deployed 27 Oct 06:44 UTC from the uncommitted tree; d95b796 is the first commit containing it (verified identical: YES/NO)"
git tag -a release/native4           d95b796 -m "native4, same note as safety1 (verified identical: YES/NO)"
git tag -a release/tool-origin-v2    <hash of last P0-3 commit> -m "tool-origin v2, production since 20261028T212308Z; UI bundle built from 03662de"
git tag -l 'release/*' -n1
```
Record the hashes in a new "Releases after live8" table in `openclaw-project/RELEASE_NOTES.md` (below the live1-live8 table, line ~116-125): columns `Release | Commit | Verified | Note`. Commit message: `Record the commits behind the native, safety, genui, cancel, hardening and tool-origin releases (GH-005, GH-001)`.
- **Acceptance**: `git tag -l 'release/*'` lists the new tags; `git rev-parse release/tool-origin-v2^{commit}` equals the verified commit.
- **Rollback**: `git tag -d <name>` (tags are local until P0-5). **Do not**: use `-f`, move existing tags, or push tags before P0-5.

### P0-5: push decision (47 unpushed commits, `main`)
- **Findings**: GH-013, IS-017. **Finding check**: re-measured with `git rev-list`: HEAD is **47 ahead / 0 behind** `origin/product-phases-6-11` (`3b2fdbb`, 13 Oct); **87 ahead / 1 behind** `origin/main` (`515fdde`); local `main` (`3c6ed08`, 4 Oct) is 107 commits behind HEAD and also 1 behind `origin/main`. `origin/main` has exactly one commit HEAD lacks, `515fdde` "Merge pull request #1 from Parsarf/product-phases-6-11", whose tree is identical to its second parent `9d11041` (tree `fe8b9e0`), which IS in HEAD's history. So `main` can be brought to HEAD without a force. The count will be 47 + the new commits from P0-3 and the tag step. RELEASE_NOTES says GitHub was suspended (appeal pending): first confirm the account works.
- **GATE (owner decides; the AI never pushes)**. Questions:
  1. Is the GitHub account restored (`gh auth status`)? Is the repository `Parsarf/AgentAI` private? (History contains 17 tracked files naming the old IONOS IP and runbooks; the audit's history secret scan was pattern-only: GH-010.)
  2. Push `product-phases-6-11` (and which tags: all `release/*`, or none)?
  3. Make `main` equal to the current branch? Options: (A) merge `origin/main` into the branch (an empty merge) then push the branch and fast-forward `main`; (B) open a new PR into `main`; (C) leave `main` stale.
  4. Push the 14 `worktree-*` branches? (Recommended no; only 7 of them exist on origin already.)
- **Read-only commands**:
```bash
cd /Users/parsa/AgentAI
git fetch --dry-run origin 2>&1 | head                         # network: only if the owner approves
git rev-list --left-right --count origin/product-phases-6-11...HEAD     # expect: 0 <N>
git rev-list --left-right --count origin/main...HEAD                    # expect: 1 <N+40>
git log --oneline origin/product-phases-6-11..HEAD | wc -l
git log --oneline HEAD..origin/main                                     # only 515fdde
git log --format='%h %an <%ae> %s' origin/product-phases-6-11..HEAD | awk '{print $2,$3,$4}' | sort | uniq -c   # authors/emails that would become public
git diff --stat origin/product-phases-6-11 HEAD | tail -1
git for-each-ref --format='%(refname:short) %(objectname:short)' refs/tags
git merge-base --is-ancestor origin/main HEAD && echo "origin/main is an ancestor" || echo "origin/main is NOT an ancestor (1 content-empty merge commit)"
```
- **If the owner approves option A** (commands as text, owner/AI runs only after "yes"):
```bash
git switch product-phases-6-11
git merge --no-ff --no-edit origin/main                  # empty diff expected: tree equals 9d11041
git diff --stat HEAD~1 HEAD | tail -1                    # must print nothing
git push origin product-phases-6-11
git push origin release/safety1 release/native4 ...      # only the tags the owner approved
git push origin product-phases-6-11:main                 # fast-forward; plain push, no --force
```
- **Do not**: `git push --all`, `--force`, `--mirror`, deleting remote refs, or pushing before the history scan question (GH-010) is answered. **Rollback**: pushes are not reversible without force; hence the gate.

### P0-6: the 14 worktrees
- **Findings**: M-03 (GH-014, OP-013). **Finding check**: re-measured 29 Oct. All 14 `worktree-*` branches are ancestors of HEAD (0 commits ahead) except `worktree-product-images` (1 commit `b956e68` "Comparison cards: server-fetched, same-origin product pictures", 16 files, +1033/-10, migration number `0023` collides with a migration already at HEAD: never merge). Two worktrees show one dirty entry each, both `?? openclaw-project/browse/node_modules` (the symlink class fixed by P0-1): `fastclick`, `live-view`. Sizes: `.claude/worktrees` is 573 MB total (`smooth-scroll` 174M, `emoji-jev` 57M, `release` 56M, `openmoji` 53M, others 8-31M). Tags protect `live1`, `live3`, `live5`, `live5-browse`, `live6`; seven branches also exist on origin.
- **Goal**: free about 570 MB and stop worktree noise without losing any unique commit.
- **GATE**: owner says "prune these worktrees" (list below). Branch deletion is a separate yes.
- **Read-only inspection loop** (run from the main checkout):
```bash
cd /Users/parsa/AgentAI
git worktree list --porcelain | grep -c '^locked'         # 0 expected
for wt in $(git worktree list --porcelain | awk '/^worktree /{print $2}' | grep '/\.claude/worktrees/'); do
  b=$(git -C "$wt" rev-parse --abbrev-ref HEAD)
  echo "== $(basename "$wt")  branch=$b  head=$(git -C "$wt" rev-parse --short HEAD)"
  echo "   unique commits vs product-phases-6-11: $(git rev-list --count product-phases-6-11..$b)"
  echo "   on origin: $(git rev-parse --verify -q origin/$b >/dev/null && echo yes || echo no)   tags: $(git tag --points-at $b | tr '\n' ' ')"
  echo "   dirty entries:"; git -C "$wt" status --porcelain | sed 's/^/     /'
  echo "   symlinks named node_modules (target must NOT be inside the worktree):"; find "$wt" -maxdepth 3 -type l -name node_modules -exec sh -c 'echo "     $1 -> $(readlink "$1")"' _ {} \;
  echo "   size: $(du -sh "$wt" | cut -f1)"
done
git stash list | head
```
- **Safety backup first** (once): `git bundle create ~/AgentAI-backups/pre-worktree-prune-$(date +%F).bundle --all` and `git bundle verify` on it.
- **Prune commands** (text; run per worktree only for ones with `unique commits = 0` and no dirty entry other than the `node_modules` symlink):
```bash
git worktree remove .claude/worktrees/<name>            # refuses if dirty; for the two node_modules-symlink cases use --force AFTER confirming above that the symlink target is outside the worktree
git branch -d worktree-<name>                           # -d (not -D): refuses if not merged into HEAD
git worktree prune -v
```
  Preconditions: the loop output shows `unique commits: 0`; for `fastclick`/`live-view` the only dirty entry is the symlink; the bundle is verified. Remove in this order: `smooth-scroll`, `emoji-jev`, `release`, `openmoji`, the 29-31 MB group (`botcheck`, `fastclick`, `jev-tune`, `notes`, `notes2`, `thinking-branch`), `live-view`, `lumina-layout-stability`, `orbs`.
- **NEVER remove / delete**: the branch `worktree-product-images` (1 unique commit; owner decides; you may remove only its worktree directory, the branch stays); remote branches `origin/worktree-*`; any tag.
- **Acceptance**: `git worktree list` shows only the main checkout (plus product-images if kept); `du -sh .claude` shrinks by about 540 MB; `git log --oneline --all | wc -l` unchanged except for deleted merged branch names (commits still reachable from HEAD and tags).
- **Rollback**: recreate with `git worktree add .claude/worktrees/<name> <branch>`; if a branch was deleted, recreate from its old hash printed by `git branch -d` (`git branch worktree-<name> <hash>`), or restore from the bundle.
- **Commit message**: none (no tracked change).

---

## Phase 2 (server). Every command needs the owner's explicit yes for that command

### P2-0 (new prerequisite): make the operator helpers use the SSH key
- **Findings**: IS-002 (follow-up), IS-016. **Finding check**: new, HIGH. `bin/ssh-server:14-22` and `bin/scp-server:14-22` read `OPENCLAW_NEW_SSH_USER/PASSWORD` from `openclaw-project/.env`, force `PreferredAuthentications=password` and `PubkeyAuthentication=no`, and fall back to host `69.48.206.62` (dead). `pull-backups.py:21` uses `ssh-server`.
- **Goal**: all helpers work with `ssh lumina` (key, no password) so P2-1 does not break deploys or backups.
- **GATE**: none for the code change; the `.env` password can be deleted only after P2-1 is verified (owner action).
- **Files to change**: `openclaw-project/bin/ssh-server` and `bin/scp-server` (whole files, about 45 lines each), `bin/pull-backups.py:19-21,28-29`. **Read first**: those three files, `~/.ssh/config` (the `lumina` alias exists).
- **Change**:
  1. In `ssh-server`: if env `OPENCLAW_SSH_TARGET` is set, or `.env` has no password, use key auth with the alias (default `lumina`):
```diff
-values = dotenv_values(env_file)
-pfx = ...
-user = values.get(pfx + "USER", "")
-if not user or not values.get(pfx + "PASSWORD"):
-    raise SystemExit("Set OPENCLAW_SSH_USER and OPENCLAW_SSH_PASSWORD in openclaw-project/.env")
+alias = os.environ.get("OPENCLAW_SSH_TARGET", "lumina")      # key login through ~/.ssh/config (default); set to "" to use the old password mode
+if alias:
+    if len(sys.argv) < 2: raise SystemExit("Usage: ssh-server <remote command...>")
+    raise SystemExit(subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-T", alias, "--"] + sys.argv[1:], stdin=subprocess.DEVNULL).returncode)
+... (existing password code stays below, unchanged, for the empty-alias case)
```
  Do the same in `scp-server` with `["scp", "-o", "BatchMode=yes", local, f"{alias}:{remote}"]`. Keep the existing code path intact below the new early return so nothing else changes.
  2. In `pull-backups.py` leave `ssh = [sys.executable, str(here / 'ssh-server')]`; it now works through the alias. Make the stderr visible on failure: replace `stderr=subprocess.DEVNULL` with `stderr=None` only for the first `ls` (so a failed login says why).
  3. `owner-console.py:55,105` and `open-*.py` also use the password and the `SSH = [...]` list; they are listed in the audit as a separate item. Do not change them here; note them in P2-1 acceptance ("these still need the key").
- **Tests**: none exist for `bin/` (confirm `git grep -n "ssh-server" -- '*test*'` is empty). Add `platform/tests/test_ops_scripts.py`? No: keep it a manual check (below).
- **Commands**: `python3 openclaw-project/bin/ssh-server 'hostname; id -un'` prints `srv2054170` and `root`; `python3 openclaw-project/bin/scp-server /dev/null /root/.scp-test && python3 openclaw-project/bin/ssh-server 'rm -f /root/.scp-test'` (owner approves these two server writes).
- **Acceptance**: the two commands work with `OPENCLAW_SSH_TARGET` unset and with the `.env` password line removed.
- **Rollback**: `git revert`. **Risks**: `ControlMaster auto` reuses a socket; fine. **Do not**: put the key path or any password into code or `.env`; do not delete `.env` values until P2-1 passes.
- **Commit message**: `Operator helpers log in with the SSH key by default (IS-002, IS-016)`

### P2-1: SSH hardening
- **Findings**: IS-002. **Finding check**: re-verified from `_findings/vps_readonly_2026-10-29.txt:165-168` and `PRODUCTION_VERIFICATION` (HIGH): `sshd -T` shows `permitrootlogin yes`, `passwordauthentication yes`; `/etc/ssh/sshd_config.d/50-cloud-init.conf` (`PasswordAuthentication yes`) is read before `60-cloudimg-settings.conf` (`no`) and the first value wins; `sshd_config` has `PermitRootLogin yes`; `/root/.ssh/authorized_keys` holds only `lumina-prod-2026-10-29` (ED25519, SHA256:X1GGObCx...). fail2ban jail `sshd` is active (20 failures, 3 bans). SSH is socket-activated (`systemd` holds fd 172/173 for port 22 with `sshd`).
- **Goal**: password and root-password login impossible; key login for root keeps working.
- **GATE**: owner "yes" per command block. Question: "Confirm P2-0 is done and you have the Hostinger web-terminal open in a browser tab before we start."
- **Depends on**: P2-0. **Blocks**: nothing.
- **Step 0: safety net (before any edit)**
  1. Open the Hostinger panel web terminal (VPS srv2054170) in a browser: this is the rollback path and works without SSH.
  2. Open **terminal A** (keep it open to the end): `ssh -o ControlMaster=no -o ControlPath=none lumina`. (Your config has `ControlMaster auto`: a "new" ssh would silently reuse A's connection and prove nothing. Always add those two options when testing.)
  3. In A, back up and arm an automatic rollback:
```bash
install -d -m 700 /root/ssh-hardening-backup
cp -a /etc/ssh/sshd_config /etc/ssh/sshd_config.d /root/ssh-hardening-backup/
sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication|pubkeyauthentication|usepam|authenticationmethods|port) ' | tee /root/ssh-hardening-backup/before.txt
# automatic undo in 15 minutes unless cancelled after verification:
systemd-run --unit=ssh-hardening-undo --on-active=15m /bin/sh -c 'cp -a /root/ssh-hardening-backup/sshd_config /etc/ssh/sshd_config && cp -a /root/ssh-hardening-backup/sshd_config.d/. /etc/ssh/sshd_config.d/ && systemctl reload ssh'
```
- **Step 1: check cloud-init will not undo it** (read-only; do not print user-data, it can hold a password):
```bash
grep -n -E '^\s*ssh_pwauth|^\s*disable_root' /etc/cloud/cloud.cfg /etc/cloud/cloud.cfg.d/*.cfg 2>/dev/null
cat /etc/ssh/sshd_config.d/50-cloud-init.conf /etc/ssh/sshd_config.d/60-cloudimg-settings.conf
ls /etc/ssh/sshd_config.d/
cloud-init --version; cloud-init status
```
  If `ssh_pwauth` is true/unset, add `/etc/cloud/cloud.cfg.d/99-lumina-ssh.cfg` containing the single line `ssh_pwauth: false` (cloud-init only rewrites `50-cloud-init.conf` on a new instance id, but this removes the chance).
- **Step 2: the edits (exact)**
```bash
# a) first-value-wins file:
sed -i 's/^PasswordAuthentication yes$/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf
# b) root login: keys only
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
# c) optional hardening of the other password-like path
printf 'KbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/01-lumina-hardening.conf
```
  Preferred variant if the owner wants it robust against cloud-init rewriting `50-cloud-init.conf`: instead of (a) create `/etc/ssh/sshd_config.d/00-lumina-hardening.conf` with `PasswordAuthentication no`, `KbdInteractiveAuthentication no` (it sorts before `50-`, and the first value wins) and leave `50-cloud-init.conf` untouched. Either way verify with `sshd -T`.
- **Step 3: validate, then reload (not restart)**
```bash
sshd -t && echo CONFIG_OK                        # must print CONFIG_OK; if not, restore from /root/ssh-hardening-backup and stop
sshd -T -C user=root,host=test,addr=203.0.113.9 | grep -Ei '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication|pubkeyauthentication) '
systemctl reload ssh
```
  `reload` sends SIGHUP: running sessions (terminal A) stay up, the listener is not closed, and with socket activation there is no gap. Do NOT `restart` (drops the listener for a moment; only needed for port changes, which we do not make). Unit name on Ubuntu is `ssh` (not `sshd`).
- **Step 4: verify from a SECOND session (terminal B, on the Mac) before touching A**
```bash
ssh -o ControlMaster=no -o ControlPath=none lumina 'echo KEY_LOGIN_OK; id -un'                       # must print KEY_LOGIN_OK root
ssh -o ControlMaster=no -o ControlPath=none -o PreferredAuthentications=password -o PubkeyAuthentication=no -o NumberOfPasswordPrompts=1 root@179.236.71.203 true
#   expected: "Permission denied (publickey)." (no password prompt at all)
python3 openclaw-project/bin/ssh-server 'hostname'                                                  # helper still works (P2-0)
```
  Then in A: `systemctl stop ssh-hardening-undo.timer` (cancels the auto-undo) and `systemctl is-active ssh fail2ban`.
- **Step 5: after**: `fail2ban-client status sshd` (jail still running; it matches `_SYSTEMD_UNIT=ssh.service`; a password attempt now fails earlier, still logged and still counted; key logins never count). If the owner's own IP got banned while testing: `fail2ban-client set sshd unbanip <ip>`. The host monitor check `host_exposure` turns ok at its next run (5 min timer); confirm: `python3 -c "import json;d=json.load(open('/var/lib/agentai-ops/monitor-status.json'));print([c for c in d['checks'] if c['name']=='host_exposure'])"` (field names: check the file; read-only).
- **Acceptance**: `sshd -T` shows `passwordauthentication no`, `permitrootlogin prohibit-password`; key login works; password login refused; monitor `host_exposure` ok; `systemctl --failed` empty.
- **Rollback**: (1) automatic: the 15-minute `ssh-hardening-undo` timer restores the backup and reloads. (2) manual from any shell: `cp -a /root/ssh-hardening-backup/sshd_config /etc/ssh/sshd_config; cp -a /root/ssh-hardening-backup/sshd_config.d/. /etc/ssh/sshd_config.d/; rm -f /etc/ssh/sshd_config.d/00-lumina-hardening.conf /etc/ssh/sshd_config.d/01-lumina-hardening.conf; sshd -t && systemctl reload ssh`. (3) if SSH is unreachable: Hostinger panel web terminal, run the same commands (this terminal does not use sshd).
- **Risks / Do not**: do not close terminal A before step 4 passes; do not `systemctl restart ssh` as the first action; do not disable `PubkeyAuthentication`; do not remove the second key line in `authorized_keys` (there is only one; also keep `/root/authorized_keys.bak-*` for now); do not change the port; `ufw` already restricts to 22/80/443 so no firewall change is needed. Later (separate decision): a non-root admin user with `sudo`.
- **After success (owner action)**: remove the SSH password line from `openclaw-project/.env`; delete `/root/authorized_keys.bak-*` once happy.

### P2-2: off-server backup and a restore drill
- **Findings**: IS-016, monitor `backup_offsite` warn. **Finding check**: re-verified (HIGH) by reading the code:
  - Host config `/etc/agentai-ops/config.json` holds `age_recipients` (public keys only) and `destinations`; the live value is `[{"type":"local","path":"/var/backups/agentai","offsite":false}]` (`hostconfig.py:27`, vps `backupcfg`). `offsite` is a flag on each destination (`destinations.py:27,73`, `hostconfig.py:47-48`). A set is "off-server" only if a destination with `offsite: true` received it (`backup.py:184`: `offsite_ok = any(d.offsite and delivered[i] ...)`), recorded as `offsite_copy` and `last_offsite_epoch` (`backup.py:249-250`).
  - Monitor (`monitor.py:87-92`): OK if `offsite_copy`, OK if `/var/lib/agentai-ops/last-pull.json` is younger than 7 days ("manual pull"), else WARN. `ops.cli check` additionally prints "LAUNCH BLOCKER: no off-server destination configured" if no destination has `offsite` (`cli.py:33`), so the pull alone silences the monitor but NOT the launch blocker.
  - `bin/pull-backups.py` copies up to 14 newest COMPLETE sets (`/var/backups/agentai/sets/<id>/`, ids `YYYYMMDDTHHMMSSZ`) to `~/agentai-backups/sets/<id>/` over SSH, checks every file's sha256 against `manifest.json` (stops on mismatch), prunes local to `--keep`, then writes `/var/lib/agentai-ops/last-pull.json {"epoch": ...}` on the server. Files stay age-encrypted; the owner's private key is `~/agentai-backup-key/identity.txt` (exists on the Mac; `age` 1.x is installed at `/opt/homebrew/bin/age`). `~/agentai-backups` does not exist yet. 10 sets (20-29 Oct, 759 MB) exist on the server.
- **Goal**: an encrypted copy of the sets exists off the server and one account restore is proven.
- **Depends on**: P2-0 (key-based helper). **GATE**: owner yes for (1) the first pull (writes `last-pull.json` on the server), (2) choosing option A or B below, (3) the drill account id ("Which account may I restore in the drill? Use your own/test account, not a customer").
- **Option A (manual pull, minimal, satisfies the monitor)**: run on the Mac, weekly at least (< 7 days):
```bash
cd /Users/parsa/AgentAI/openclaw-project && python3 bin/pull-backups.py --keep 14      # default dest ~/agentai-backups, dir created 0700
ls -la ~/agentai-backups/sets | tail -3; du -sh ~/agentai-backups
```
  Keep a second copy of `~/agentai-backup-key/identity.txt` outside the Mac (password manager + USB); without it every backup is unreadable. Schedule it (owner choice): a launchd job or a calendar reminder.
- **Option B (automatic, closes the launch blocker)**: add a `command` destination to `/etc/agentai-ops/config.json` (example: `deploy/ops-config.example.json`, key `_second_copy_example`), e.g. rclone to an object-storage bucket the owner owns:
```json
{"type":"command","offsite":true,
 "put":["rclone","copyto","{src}","remote:agentai/{name}"],
 "list":["sh","-c","rclone lsf --format 'pst' --separator '\\t' remote:agentai/{prefix} | sed 's|^|{prefix}|'"],
 "remove":["rclone","deletefile","remote:agentai/{name}"]}
```
  Needs `rclone` installed on the host and an rclone remote configured for root (credentials live on the host; the data is age-encrypted so only the bucket credentials are at stake: use a bucket-scoped key). Then `python3 -m agentai_platform.ops.cli check --config /etc/agentai-ops/config.json` (on the host) must stop reporting the LAUNCH BLOCKER, and the next `systemctl start agentai-ops-backup.service` must report `offsite_copy: true`. Note the command destination runs from the root unit with `ProtectSystem=full` and `ReadWritePaths=/var/lib/agentai-ops /var/backups/agentai` (`agentai-ops-backup.service`): rclone's config path must be readable and its cache writable (put it under `/var/lib/agentai-ops`). Do B only after the owner picks a provider.
- **Restore drill of ONE account** (nothing touches the live database; the private key never goes to the server; do it on the Mac):
```bash
# 0. data on the Mac: the pull from Option A above
# 1. a local config that points the ops tool at the pulled sets
cat > ~/agentai-backups/ops-local.json <<'EOF'
{"destinations":[{"type":"local","path":"/Users/parsa/agentai-backups","offsite":false}]}
EOF
chmod 600 ~/agentai-backups/ops-local.json; chmod 700 ~/agentai-backups     # LocalDir refuses a root readable by others (destinations.py:31)
cd /Users/parsa/AgentAI/openclaw-project/platform
.venv/bin/python -m agentai_platform.ops.cli verify --config ~/agentai-backups/ops-local.json   # structure and size check, prints the newest complete set
# 2. a consistent COPY of the live database (online backup, live file untouched); it holds all customers, so keep it on the Mac only and delete it after
ssh lumina "sqlite3 -readonly /var/lib/agentai-platform/platform.sqlite3 \".backup '/root/drill-live.sqlite3'\" && chmod 600 /root/drill-live.sqlite3"
D=$(mktemp -d /private/tmp/claude-501/restore-drill.XXXXXX); chmod 700 "$D"
scp lumina:/root/drill-live.sqlite3 "$D/live-copy.sqlite3"; ssh lumina 'rm -f /root/drill-live.sqlite3'
ssh lumina "sqlite3 -readonly /var/lib/agentai-platform/platform.sqlite3 'select id from accounts'"   # ids only; pick the owner's/test account
# 3. restore into a NEW file (refuses to overwrite; decrypts only the app-db artifact)
.venv/bin/python -m agentai_platform.ops.cli restore-account --config ~/agentai-backups/ops-local.json \
   --identity ~/agentai-backup-key/identity.txt --account <ACCOUNT_ID> --live-db "$D/live-copy.sqlite3" --out "$D/out"
```
  Read `ops/cli.py:67-69` and `ops/restore.py:restore_account` for the guarantees: the output is built from a copy of the live DB; the account's `RESTORE` tables come from the backup, `MERGE` tables only gain missing rows, `LEDGER` tables only gain rows, `LIVE` tables never change (accounts, billing, entitlements, vault_items, safety_*); schedules/watchers are paused, browser profiles revoked, in-flight tasks blocked, requests cancelled, goals stopped, reservations closed; then proofs: every other account's rows and all global tables are byte-identical (`snapshot_others`), no ledger row lost, `integrity_check` ok, foreign keys ok. An unclassified table aborts (`check_classified`). The account must be quiesced (`quiesced()`: no active task, request or lifecycle operation) or it refuses: choose an idle account.
  **Pass criteria**: the JSON report shows `"other_accounts_unchanged": true`, `"ledger_intact": true`, `"billing_requires_reconcile": true`, and the file `"$D/out/restored-<epoch>.sqlite3"` exists; `sqlite3 <file> 'pragma integrity_check'` prints `ok`. **Do NOT copy it over the live DB**; that is a real restore (OPERATIONS.md section "Restore one account": stop app, swap, start, `billing_worker --reconcile`). Cleanup: `rm -r "$D"` (it holds customer data).
  Also test the corruption path once (cheap): copy one `*.age` of a pulled set to a scratch dir, flip a byte, run `verify`/`fetch` on that set: it must refuse (`artifact damaged`) .
- **Acceptance**: `~/agentai-backups/sets` has the newest sets; `last-pull.json` updated; monitor `backup_offsite` ok after the next 5-minute monitor run; drill report saved (no contents) in the audit doc.
- **Rollback**: Option A: nothing on the server changes except `last-pull.json` (`rm /var/lib/agentai-ops/last-pull.json`). Option B: remove the destination from `config.json` (it is also in the nightly backup of config).
- **Risks / Do not**: do not put `identity.txt` on the server or in git/chat; do not run `fetch` of ALL artifacts for the drill (it decrypts `tenant-secrets` and `config`); do not delete server sets; do not run restore against the live DB path.
- **Commit message** (for the code in P2-0 only): see P2-0.

### P2-3: OS updates and the kernel reboot
- **Findings**: PV-03. **Finding check**: re-verified from `_findings/vps_readonly_2026-10-29.txt:648-670`: 19 upgradable packages: kernel (`linux-image-virtual`, `linux-libc-dev`, `linux-perf`, `bpftool` 7.0.0-38 to 42), `docker-ce`, `docker-ce-cli`, `docker-ce-rootless-extras` 29.9.0 to 29.9.2, `containerd.io` 2.4.1 to 2.4.2, `docker-buildx-plugin`, `docker-compose-plugin`, systemd libs (`libsystemd0`, `libudev1`, `libnss-systemd`, `libpam-systemd`, `libsystemd-shared`), `cloud-init(-base)` 26.1 to 26.2, `python3-distupgrade`, `qemu-guest-agent`. Unattended-upgrades is enabled, no `/var/run/reboot-required`, uptime 12 days.
- **Goal**: apply updates in a planned window and reboot onto the new kernel with every service verified.
- **Depends on**: P2-1 (so the window also tests post-reboot key login) and P2-2 (fresh off-server backup first). **GATE**: owner picks the window ("When can the site be down for about 10 minutes? Customers' running tasks will be interrupted; no cell was running at last check") and says yes per block.
- **Why docker/containerd matter here**: there are TWO engines. The main engine runs the compose stack (`openclaw-production-litellm-1`, `-openclaw-gateway-1`, `-postgres-1`) and the browse host stage; the cells engine is `agentai-cells-docker.service` (own socket `/run/agentai-cells/docker.sock`, runtime `runsc`, bridge `agentai0`, pool `10.78.0.0/16`, iptables off, firewall via `agentai-cells-firewall` nft table). Upgrading `docker-ce`/`containerd.io` restarts `docker.service` (the main engine, so LiteLLM, gateway, postgres bounce; the model relay at 127.0.0.1:4000 and port 3978/18789-18790 go down briefly) and may restart `containerd`, which cells may share. Customer cells must be STOPPED/idle before, and the cells engine and firewall must be re-checked after.
- **Steps**:
  1. **Safety copy**: Hostinger panel snapshot of the VPS (owner action, the real rollback for the kernel/docker), then on the server `systemctl start agentai-ops-backup.service` and wait for success (`journalctl -u agentai-ops-backup -n 5 --no-pager`), then on the Mac `python3 openclaw-project/bin/pull-backups.py`.
  2. **Baseline (read-only), save the output to `/root/pre-update-baseline.txt` on the server**:
```bash
systemctl list-units 'agentai-*' caddy.service fail2ban.service docker.service containerd.service openclaw-dashboard.service --no-legend --plain
systemctl list-timers --no-legend | grep -E 'agentai|openclaw'
systemctl --failed --no-legend
ss -ltnp | awk 'NR>1{print $4}' | sort
docker ps --format '{{.Names}} {{.Status}}'; docker info --format 'live-restore={{.LiveRestoreEnabled}} runtime={{.DefaultRuntime}}'
DOCKER_HOST=unix:///run/agentai-cells/docker.sock docker ps -a --format '{{.Names}} {{.Status}}'
nft list tables; nft list set inet agentai_cells quarantined 2>/dev/null | head   # set name from the live ruleset; read-only
uname -r; apt list --upgradable 2>/dev/null
sqlite3 -readonly /var/lib/agentai-platform/platform.sqlite3 "select count(*) from customer_requests where state in ('waiting','starting','running','uncertain')"   # must be 0
```
  3. **Quiet the platform** (no new per-task limits: use the existing owner switch only if the owner wants; otherwise pick an idle time): confirm the last query returned 0 and no cell container is running.
  4. **Simulate, then apply** (inside `systemd-run` so a dropped SSH session cannot interrupt dpkg):
```bash
apt-get update
apt-get -s upgrade | grep -E '^(Inst|Conf)' | head -40          # simulation only
systemd-run --unit=lumina-apt-upgrade --collect --property=StandardOutput=journal -- /bin/sh -c 'DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold upgrade'
journalctl -u lumina-apt-upgrade -f          # follow until it finishes
```
  `--force-confold` keeps our `docker/daemon.json`, `sshd_config` and cloud-init edits. Do not run `dist-upgrade`/`do-release-upgrade` (`python3-distupgrade` is just a library update).
  5. **Services after apt, before reboot**: `systemctl --failed`; `docker ps`; the cells engine and the live-restore behaviour from step 2. Restart anything that did not come back with `systemctl restart <unit>` in this order: `docker`, `agentai-cells-docker`, `agentai-cells-firewall`, `agentai-model-proxy`, `agentai-cell-bridge`, `agentai-tool-relay`, `agentai-lifecycle-worker`, `agentai-supervisor-native`, `agentai-request-worker`, `agentai-browse`, `agentai-platform-app`, `caddy`.
  6. **Reboot window** (kernel 7.0.0-42): `ls /var/run/reboot-required`; announce; `systemctl stop agentai-request-worker agentai-lifecycle-worker` (stops new work), `sync`, `shutdown -r +2 'planned kernel update'`. Keep terminal A and the Hostinger web terminal open. Expected downtime 1-3 minutes plus service start.
  7. **Post-reboot checks** (compare with the baseline file): 
```bash
uname -r                                  # 7.0.0-42-*
systemctl --failed --no-legend            # empty
for u in agentai-browse agentai-cell-bridge agentai-cells-docker agentai-cells-firewall agentai-lifecycle-worker agentai-model-proxy agentai-platform-app agentai-request-worker agentai-supervisor-native agentai-tool-relay caddy fail2ban docker openclaw-dashboard ssh; do printf '%s %s\n' $u "$(systemctl is-active $u)"; done
systemctl list-timers --no-legend | grep -E 'agentai-(billing-worker|ops-backup|ops-monitor|platform-mail)|openclaw-ops-backup'      # all 5 timers present
ss -ltnp | awk 'NR>1{print $4}' | sort    # public only 22, 80, 443; 10.77.0.1:4000 and :4100; 127.0.0.1: 2019 18789 18790 18795 18800 18801 4000 3978
ufw status | head -20; nft list tables    # cell rules and the `quarantined` set restored from /var/lib/agentai-cells/quarantine.json
docker ps --format '{{.Names}} {{.Status}}'      # litellm, openclaw-gateway, postgres Up
for p in /healthz /readyz; do curl -s -o /dev/null -w "$p %{http_code}\n" http://127.0.0.1:18800$p; done
curl -s -o /dev/null -w "public %{http_code}\n" https://backend.getlumina.pro/healthz
systemctl start agentai-ops-monitor.service; python3 -c "import json;d=json.load(open('/var/lib/agentai-ops/monitor-status.json'));print(d['overall'],d['counts'])"
journalctl -p err -b --no-pager | tail -20
apt list --upgradable 2>/dev/null | tail -n +2 | wc -l      # 0
```
  Customer smoke test (owner): sign in at `https://getlumina.pro/app/`, send one message, confirm a normal reply and that the browser tool still works (this boots a cell on the new containerd/runsc). 
- **Acceptance**: the checks above match the baseline; monitor overall improves (host_exposure and backup_offsite warns gone after P2-1/P2-2; `quarantine` warn remains until PV-09).
- **Rollback**: Hostinger snapshot restore (any problem with kernel/boot); for docker regressions `apt-get install docker-ce=5:29.9.0-1~ubuntu.26.04~resolute docker-ce-cli=5:29.9.0-1~ubuntu.26.04~resolute containerd.io=2.4.1-2~ubuntu.26.04~resolute` (versions from the audit listing) then restart units in step 5 order. The previous kernel stays installed; pick it at the Hostinger console only if boot fails.
- **Risks / Do not**: do not update while a cell, restore or release is running; do not reboot before the backup is pulled; do not enable `Unattended-Upgrade::Automatic-Reboot`; do not touch `/etc/docker/daemon.json` (it carries the cells and runtime settings); do not run `apt autoremove` in this window.

### P2-4: release / tarball / `.bak` cleanup
- **Findings**: PV-01, PV-02, PV-09 (secret copies), IS-006. **Finding check**: numbers from `PRODUCTION_VERIFICATION_2026-10-29.md`: disk 18% used (no urgency), about 100 release directories under `/opt/agentai-platform/releases` (5.0 GB, plus `/opt/agentai-supervisor/releases`), about 85 `.tgz` and 2 `.bundle` files in `/root` (1.9 GB), journals 133.7 MB. Current symlinks both point to `20261028T212308Z-tool-origin-v2`; the previous release is `20261028T014523Z-hardening-ef2a8ac`. Additional privacy item the audit did not list: pre-migration database copies `/var/lib/agentai-platform/backup-*-premigrate-*.sqlite3` (customer data outside the backup retention) and `ui.before-*` folders: include them in the listing.
- **Goal**: reclaim about 6 GB and remove stale secret copies, without losing the only copy of any released code.
- **Depends on**: P0-3 (code in git), P0-4 (tags), P2-2 (copy of tarballs off the server). **GATE**: owner reviews the listing and approves the exact `rm` file list ("Remove exactly the files in the approved list? A copy of the archive is on your Mac and verified?").
- **Step 1: read-only listing script** (text; run as `ssh lumina 'bash -s' < list-cleanup-candidates.sh`; writes nothing):
```bash
#!/bin/bash
# READ-ONLY inventory for P2-4. No rm, no mv, no writes.
set -u
echo "== disk"; df -h / | tail -1
echo "== current links"; for l in /opt/agentai-platform/current /opt/agentai-supervisor/current; do echo "$l -> $(readlink -f $l)"; done
echo "== running processes using a release"; for p in /proc/[0-9]*; do readlink "$p/cwd" 2>/dev/null; done | grep -E '/opt/agentai-(platform|supervisor)/releases/' | sort | uniq -c
echo "== units referencing releases/"; grep -rl 'releases/' /etc/systemd/system /etc/agentai-* 2>/dev/null
for root in /opt/agentai-platform/releases /opt/agentai-supervisor/releases; do
  echo "== $root (newest first: name, size MB, mtime)"
  for d in $(ls -1t "$root"); do printf '%s\t%s\t%s\n' "$d" "$(du -sm "$root/$d" | cut -f1)" "$(stat -c %y "$root/$d" | cut -c1-16)"; done
done
echo "== /root archives (size bytes, mtime, name)"; ls -l --time-style=+%F\ %R /root/*.tgz /root/*.bundle 2>/dev/null | awk '{print $5, $6, $7, $8}'
echo "== secret-bearing and backup copies"; ls -l /etc/agentai-platform/accounts.env.bak* /etc/caddy/Caddyfile.* /opt/agentai-browse/runner/*.bak-* /opt/openclaw-production/feature-switches/*.bak-* /root/authorized_keys.bak-* 2>/dev/null
echo "== database and ui copies"; ls -l /var/lib/agentai-platform/backup-*premigrate*.sqlite3 2>/dev/null; du -sm /var/lib/agentai-platform/ui.before-* /var/lib/agentai-platform/ui.prev 2>/dev/null
echo "== deployment evidence on server"; ls /var/lib/agentai-ops/releases.log 2>/dev/null && tail -3 /var/lib/agentai-ops/releases.log | cut -c1-200
```
- **Safe-removal rules** (the AI applies these to the listing and prepares a numbered `candidates.txt` for the owner; it removes nothing):
  1. NEVER remove: the two `current` link targets; the release that `readlink -f` shows in a running process or unit; the previous release `20261028T014523Z-hardening-ef2a8ac`; `20261028T212308Z-tool-origin-v2` (platform and supervisor) and `/root/lumina-tool-origin-v2*.tgz` ("keep tool-origin-v2": production's only verified copy until P0-3 and its byte check are done and the tag exists); `safety1` and `native4` (documented rollback targets in `RELEASE_NOTES.md:7`); `20261027T110435Z-genui-10efb73` and `20261027T114539Z-cancel-e700e33` while `evidence/deployments` references them.
  2. Keep the newest N=5 release directories per tree (by mtime) in addition to rule 1.
  3. A `/root/*.tgz` or `.bundle` is "the only copy" unless the owner has a verified copy: first archive ALL of them to the Mac (`mkdir -m 700 ~/AgentAI-archive/server-root-2026-10-29; scp 'lumina:/root/*.tgz' 'lumina:/root/*.bundle' ~/AgentAI-archive/server-root-2026-10-29/` then compare `sha256sum` on both sides; `/root/agentai-code-backup-20261014-*.bundle` and the `live*`/`native1`/`sup-native1`/`safety1`/`lumina-*` tarballs hold code that exists in git only from d95b796 on). Releases between 13 Oct and 27 Oct (live9-live25 era) were deployed from the uncommitted tree, so those tarballs are the only provenance: remove them only AFTER the archive copy is verified, and keep at least `/root/native1.tgz`, `/root/sup-native1.tgz`, `/root/safety1.tgz`, `/root/lumina-ui.tgz` until P0-4's proof step has run.
  4. Keep `/root/jev-full-page-experiment.tgz` and `jev-full-page-update.tgz` (PV-08 evidence) until the owner decides.
  5. `.bak` files: `accounts.env.bak-live1` and `.bak-safety1` hold old copies of the environment file (secrets): after the owner confirms the current values are what runs (monitor ok), remove them; shred is not meaningful on this filesystem, plain `rm`. Caddy and runner `.bak-*`: keep the newest of each, remove older after the owner agrees. `authorized_keys.bak-*`: remove after P2-1 passes.
  6. Premigrate DB copies: keep the newest two; older ones hold customer data outside retention: owner decides (privacy).
- **Step 2: exact commands, run only after approval** (the approved lists are files the owner has seen; `set -e`, one tree at a time):
```bash
# releases (the approved names only; the guard refuses a current/previous target)
for n in $(cat /root/approved-release-removals.txt); do
  for t in /opt/agentai-platform /opt/agentai-supervisor; do
    d="$t/releases/$n"; [ -d "$d" ] || continue
    case "$(readlink -f $t/current)" in "$d") echo "REFUSE current: $d"; continue;; esac
    rm -rf --one-file-system -- "$d"
  done
done
# archives and backup copies (the approved paths only)
xargs -a /root/approved-file-removals.txt -d '\n' rm -v --
df -h / | tail -1
```
  The two list files are written by the owner (or by the AI after the owner approved the numbers). No wildcards in the `rm` lines.
- **Acceptance**: `df` shows about 6 GB freed; `systemctl --failed` empty; `readlink -f` of both `current` links unchanged; app `/readyz` 200; `ls /opt/agentai-platform/releases | wc -l` about 12.
- **Rollback**: removed files cannot be restored on the server; they are in `~/AgentAI-archive/server-root-2026-10-29/` (tarballs) and in git/tags (code). Hence the archive-and-verify step.
- **Do not**: `rm -rf releases/*`; touch `/opt/agentai-browse/runner/runner.mjs` (the production engine); remove anything under `/var/backups/agentai` or `/var/lib/agentai-ops`; run it before P2-2.

### P2-5: PV-06 gunicorn control server, PV-07 tool_relay resets, PV-08 release rule
- **Depends on**: P0-3 (tool_relay.py is dirty until committed). **GATE**: owner deploys (through `release.py`, see PV-08). One commit per sub-fix.

#### PV-06: "Control server error: [Errno 13] Permission denied: '/home/agentai-platform'"
- **Finding check**: root cause identified (HIGH) from the pinned code. `requirements.lock:8` pins `gunicorn==26.2.0` (the local `platform/.venv` has the same version, read at `.venv/lib/python*/site-packages/gunicorn/`). Gunicorn 25.1.0 added a runtime control socket for `gunicornc` (`config.py:3229-3303`): `control_socket` defaults to `$XDG_RUNTIME_DIR/gunicorn.ctl`, else `$HOME/.gunicorn/gunicorn.ctl`, and the arbiter starts it after the workers (`arbiter.py:1002-1026`, skipped when `control_socket_disable` is true); a failure inside its thread is logged as `Control server error: %s` (`ctl/server.py:200`). Our unit runs as `agentai-platform` with `ProtectHome=yes` and `ReadWritePaths=/var/lib/agentai-platform` only (`deploy/agentai-platform-app.service:5,15,24`) and has no `XDG_RUNTIME_DIR`, so creating `/home/agentai-platform/.gunicorn` is refused (EACCES, errno 13). No customer effect; the app serves normally; 28 log lines in 3 days.
- **Goal**: the error disappears; no new socket or surface exists on the host (privacy/attack surface: the control socket would let a local user with permission reload or scale workers; we do not use `gunicornc`).
- **Files to change**: `platform/deploy/gunicorn.conf.py:18` (append one setting). **Read first**: that file (18 lines), the unit above, `tests/check_account_http.py:39` (starts real gunicorn with this config).
- **Change** (disable, rather than point it at `/var/lib/agentai-platform`, because we never use `gunicornc` and a disabled feature is the smaller surface):
```diff
 forwarded_allow_ips='127.0.0.1,::1'
+# gunicorn >= 25.1 opens a control socket under $HOME by default; the sandboxed unit cannot write there
+# (Errno 13 every worker cycle) and nothing here uses `gunicornc`, so keep the feature off.
+control_socket_disable=True
```
- **Tests**: add to `platform/tests/test_deploy_config.py` (new, small): 
```python
import runpy, unittest
from pathlib import Path
class GunicornConfig(unittest.TestCase):
    def test_control_socket_stays_disabled(self):
        conf = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'deploy' / 'gunicorn.conf.py'))
        self.assertIs(conf.get('control_socket_disable'), True)   # fails before the fix: the key is absent
    def test_setting_is_a_real_gunicorn_option(self):
        from gunicorn.config import Config
        cfg = Config(); cfg.set('control_socket_disable', True); self.assertTrue(cfg.control_socket_disable)
```
- **Commands** (from `openclaw-project/platform`): `.venv/bin/python -m unittest tests.test_deploy_config`; `AGENTAI_SESSION_SECRET=x AGENTAI_STATE_DIR=$(mktemp -d) AGENTAI_PUBLIC_ORIGIN=https://localhost .venv/bin/gunicorn --check-config -c deploy/gunicorn.conf.py accounts.wsgi:application` (should print nothing and exit 0); `.venv/bin/python tests/check_account_http.py` (real gunicorn; see its header for env). Add `tests.test_deploy_config` to the CI unittest list in `.github/workflows/platform.yml` only if the owner wants CI changes (separate task M-10).
- **Acceptance**: after deployment `journalctl -u agentai-platform-app --since '24 hours ago' | grep -c 'Control server error'` is 0 for 24 h; `ls /home/agentai-platform` unchanged; `/readyz` 200. The canary in `release.py` also runs this config as the app user.
- **Rollback**: `git revert` and redeploy; or leave the setting (harmless). **Do not**: pass `--no-control-socket` in the unit file instead (the conf file is what the canary also uses); do not loosen `ProtectHome`.
- **Commit message**: `Gunicorn: keep the control socket off in the sandboxed app unit (PV-06)`

#### PV-07: `ConnectionResetError` tracebacks in the tool relay
- **Finding check**: confirmed in code (HIGH). `agentai_platform/tool_relay.py:218-221` builds a plain `ThreadingHTTPServer`; any exception from a handler thread (a cell that drops the TCP connection while the relay reads the body at `:206` or writes the reply at `:175`) falls to `socketserver.BaseServer.handle_error`, which prints a full traceback to stderr. `:177-183` (`_closed`) already treats a hung-up caller as normal for the long browser call, but the read/write paths are not covered. Journals showed 6 relay errors in 3 days (2 are `ConnectionResetError: [Errno 104]` from `10.78.0.2`).
- **Goal**: a caller hanging up is silent at debug level; real handler bugs still log a traceback. Privacy: the traceback includes request internals; silencing resets also reduces noise that could hold arguments; content is still never logged.
- **Files to change**: `platform/agentai_platform/tool_relay.py:218-221` (`serve`) and the imports at `:15-21`. **Read first**: `tests/test_browser_tool.py:285-330` (`RelayChecks`, uses `serve(..., '127.0.0.1', 0)`).
- **Change**:
```diff
 def serve(relay: Relay, identity: Identity, host: str, port: int):
-    server = ThreadingHTTPServer((host, port), make_handler(relay, identity))
-    server.daemon_threads = True
-    return server
+    class Server(ThreadingHTTPServer):
+        daemon_threads = True
+
+        def handle_error(self, request, client_address):
+            if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):   # the cell hung up (reset, broken pipe, timeout): normal, nothing to report
+                log.debug('tool_relay_caller_gone')
+                return
+            super().handle_error(request, client_address)
+    return Server((host, port), make_handler(relay, identity))
```
  and add `import sys` to the import block (keep alphabetical: after `socket`). `ConnectionError` covers `ConnectionResetError`, `BrokenPipeError`, `ConnectionAbortedError`; `TimeoutError` covers socket timeouts. No address or payload is logged.
- **Tests** (add to `RelayChecks` in `tests/test_browser_tool.py`): 
  - `test_caller_reset_is_silent`: `server = serve(self.relay, self.identity, '127.0.0.1', 0)`; `buf = io.StringIO()`; `with contextlib.redirect_stderr(buf): try: raise ConnectionResetError(104, 'reset')  except ConnectionResetError: server.handle_error(None, ('10.78.0.2', 5))`; assert `buf.getvalue() == ''`; `server.server_close()`.
  - `test_real_handler_errors_still_report`: same with `ValueError('x')`; assert `'ValueError' in buf.getvalue()` (fails if someone silences everything).
- **Commands**: `.venv/bin/python -m unittest tests.test_browser_tool tests.test_tool_origin`.
- **Acceptance**: after deploy `journalctl -u agentai-tool-relay --since '24 hours ago' | grep -c ConnectionResetError` is 0; a normal browser tool call still works (owner smoke test).
- **Rollback**: `git revert`. **Do not**: catch `Exception` broadly; do not change the busy-lock or the origin logic in the same commit; do not log `client_address`.
- **Commit message**: `Tool relay: a cell hanging up is not an error worth a traceback (PV-07)`

#### PV-08: every production overlay goes through the release process
- **Finding check**: re-verified (HIGH): the 28 Oct 22:53-23:01 overlays (`/root/jev-full-page-experiment.tgz`, `jev-full-page-update.tgz`) ran for about 3 minutes in the live browse service with no release record. Reading `deploy/release.py` explains why this was possible: `release.py` only handles the PLATFORM tree (`ROOT=/opt/agentai-platform`, `release.py:30`); the SUPERVISOR tree (`/opt/agentai-supervisor/releases`, which contains the browse service) and `runner.mjs` have no scripted release, so they are hand-extracted. `release.py` also does not record which git commit it deployed (`--id` is a free string; `finish()` logs only the report), and the release directory has no manifest (noted in `PRODUCTION_VERIFICATION` second pass).
- **Goal**: a written rule + two small safeguards, so a production tree can always be traced to a commit and an experiment cannot silently run on live traffic. No new per-task limits.
- **Gate**: owner approves the rule text; owner decides whether the supervisor release script (part C) is built now.
- **Part A: the rule (documentation)**. Add section "7a. Production changes: one path only" to `platform/OPERATIONS.md` after section 7 (`OPERATIONS.md:82-86`):
  1. Nothing reaches `/opt/agentai-platform`, `/opt/agentai-supervisor`, `/opt/agentai-browse` or `/var/lib/agentai-platform/ui` except as a release: a tarball produced by `git archive <commit>` from a CLEAN tree whose commit is committed (and tagged `release/<name>` after the deploy).
  2. Platform tree: `deploy/release.py --tarball ... --id <UTC>-<name>-<shortsha> --commit <sha>`; dry run first (`--dry-run`), then the real run. Supervisor tree: extract to `/opt/agentai-supervisor/releases/<same id>`, `chown -R root:root`, `chmod -R go-w`, `ln -sfn` the `current` link, restart the listed services, check journals; frontend: `bin/deploy-lumina.py --apply`.
  3. Every release leaves a record: an entry in `evidence/deployments/<UTC>-<name>-<sha>/deployment.json` (fields as in the two existing examples) and a `RELEASE_NOTES.md` line.
  4. Experiments that must touch live traffic need an explicit written owner OK in the conversation, an owner switch or a single-account scope, a time limit, and the same record. "Hand-install a tarball and restore it" is not allowed, even for minutes. Experiments run on a copy (`--sandbox`) or on a separate port/account.
  5. Drift check (read-only, run weekly or after any incident): `ssh lumina 'find /opt/agentai-platform/releases /opt/agentai-supervisor/releases -maxdepth 1 -newer /var/lib/agentai-ops/releases.log -printf "%p %TY-%Tm-%Td %TH:%TM\n"'` lists release directories created after the last `release.py` log entry (hand-made ones); `ls -l --time-style=long-iso /root/*.tgz | awk '$6>"<date of last release>"'` lists unrecorded tarballs.
- **Part B: small code change in `deploy/release.py`** (records the commit and a manifest; backwards compatible):
```diff
-    ap = argparse.ArgumentParser(); ap.add_argument('--tarball', required=True); ap.add_argument('--id', required=True); ap.add_argument('--dry-run', action='store_true')
+    ap = argparse.ArgumentParser(); ap.add_argument('--tarball', required=True); ap.add_argument('--id', required=True); ap.add_argument('--commit', help='git commit the tarball was built from (recorded in the release log and next to the code)'); ap.add_argument('--dry-run', action='store_true')
 ...
-    report = {'release': args.id, 'steps': [], 'result': 'refused'}
+    report = {'release': args.id, 'commit': args.commit, 'steps': [], 'result': 'refused'}
 ...
         new.mkdir(parents=True); run(['tar', '-xzf', args.tarball, '-C', str(new)], check=True)
+        (new / 'RELEASE.json').write_text(json.dumps({'id': args.id, 'commit': args.commit, 'tarball_sha256': hashlib.sha256(Path(args.tarball).read_bytes()).hexdigest()}))   # add `import hashlib`
```
  (`release.py:133` adds the argument, `:148` the report field, `:154` the file.) `--commit` stays optional so old drills keep working; the OPERATIONS rule makes it mandatory for real runs. Tests: extend the existing release drill test if one exists (`git grep -n "release.py" -- tests`); otherwise add `tests/test_release_cli.py` that calls `main(['--tarball', t, '--id', 'x', '--sandbox', d, '--drill-fail-live'])` is too heavy for CI; instead unit-test the argparse addition by importing `release` and asserting `release.main` accepts `--commit` (use `argparse` introspection) and leave the full drill to the existing `--sandbox` procedure run by the owner on the server.
- **Part C (optional, owner decides): `deploy/release_supervisor.py`** with the same shape as `release.py` for `/opt/agentai-supervisor` (build beside, validate, switch link, restart named units, probe, roll back the link on failure) so the browse service has the same canary + rollback. Spec it as a follow-up task; do not hand-write deployment commands in the meantime.
- **Acceptance**: `OPERATIONS.md` shows section 7a; `release.py --help` lists `--commit`; the next real release writes `RELEASE.json` and the evidence record; the drift check prints nothing unexpected.
- **Rollback**: `git revert`. **Do not**: make `--commit` mandatory in code before the owner agrees; do not touch the existing probes or the rollback logic; do not run `release.py` yourself.
- **Commit messages**: `Release procedure: one path to production, with commit and manifest recorded (PV-08)` (docs + `release.py`)

---

## Quarantined restores (PV-09)
- **Finding check (correction)**: the audit text says "review and release or delete per `ops/restore.py`". `ops/restore.py` does NOT quarantine anything: it only builds a new database file for the account-restore path (above) and never touches cells. The monitor's `quarantine` warning (`monitor.py:119-120`, `hostprobe.py:124-128`) reads `/var/lib/agentai-cells/quarantine.json`, a JSON list of cell SUBNETS written by `HostIsolation` (`lifecycle/maintenance.py:115-171`). A subnet is added when a CELL restore creates a quarantine cell (`FleetCliDriver._restore`, `lifecycle/fleet_driver.py:219-249`: separate cell `aa-<sha256("quarantine:"+tenant)[:32]>`, own volume, token and network; egress dropped by the nft `quarantined` set BEFORE any restored code runs) and is removed by `discard_quarantine` (`fleet_driver.py:252-263`). The monitor warns when the FILE is older than 7 days and non-empty (`quarantine_max_days: 7`, age is the file's mtime, not per item). The two warned entries match the two `quarantined` /24 ranges in the live nft table. They may be leftovers from the Phase-4 live checks (`deploy/p4_live_check.py` creates and discards quarantine cells; a crashed run leaves the subnet behind) or real restores. OPERATIONS.md line 38 says "Inspect it, then promote deliberately"; no promote tool exists in the repo (the "release" in the audit means removing the firewall quarantine or discarding the cell).
- **Safe review (read-only; owner approves running)**:
```bash
ssh lumina 'cat /var/lib/agentai-cells/quarantine.json; echo; stat -c "%y %n" /var/lib/agentai-cells/quarantine.json'     # subnets only
ssh lumina 'DOCKER_HOST=unix:///run/agentai-cells/docker.sock docker ps -a --format "{{.Names}} {{.Status}} {{.CreatedAt}}" | grep "^openclaw-cell-aa-"'
ssh lumina 'DOCKER_HOST=unix:///run/agentai-cells/docker.sock docker network ls --format "{{.Name}}" | grep "^openclaw-cell-aa-"'
# which of those names are QUARANTINE cells (not live tenants)? compute the quarantine names for every bound tenant (custody read-only):
ssh lumina "python3 -I - <<'EOF'
import hashlib, sqlite3
con = sqlite3.connect('file:/var/lib/agentai-supervisor/custody.sqlite3?mode=ro', uri=True)
for account, tenant in con.execute('SELECT account, tenant FROM bindings'):
    print(account, 'aa-' + hashlib.sha256(('quarantine:' + tenant).encode()).hexdigest()[:32])
EOF"
```
  Match the printed `aa-...` names against the docker list (cell container `openclaw-cell-<name>`, network `openclaw-cell-<name>-net`). Classification: (1) subnet present, no container, no network: stale firewall entry (leftover); (2) container exists, stopped: a real quarantined restore awaiting inspection; (3) container running: unexpected, investigate. Do NOT open the restored volume (`/var/lib/agentai-fleet/.openclaw/fleet/cells/<name>`): it may contain a customer's data; if inspection is needed it is done by the owner or with the customer's consent, never by the cleanup AI.
- **Release / delete (destructive, owner decision per item)**: 
  - Case 1 (stale subnet only): back up `quarantine.json` and the nft rules file (`cp -a`), then remove the subnet by calling `HostIsolation.release`-equivalent logic (`_apply([s for s in current if s != subnet])`). There is no CLI for it; the safe form is a small operator script built from `native_wiring.build_native_backend('/etc/agentai-supervisor/native-wiring.json')` (which returns the driver whose `.isolation` is the `HostIsolation`). `release(tenant)` needs the network to still exist; for a leftover without a network write the filtered list directly with `isolation._apply(...)`, which validates with `nft -c` before loading. Specify this script as a follow-up task (`lifecycle/quarantine_cli.py` with `list` and `discard <account>` subcommands, tests in `tests/test_fleet_driver.py` style) instead of ad-hoc edits.
  - Case 2 (quarantined cell kept): `driver.discard_quarantine(binding)` removes only that quarantine (cell, volume image, auth dir, token, firewall entry), as proven by `p4_live_check.py:167-170`. "Promote" (turn the quarantine into the live cell) has no implemented path: restoring the customer's data into production means the full cell restore procedure in `OPERATIONS.md` (stop, backup, restore) and is a separate owner decision.
  - After either: `systemctl start agentai-ops-monitor.service`; the `quarantine` check turns ok when the file is empty or newer than 7 days.
- **Do not**: edit `quarantine.json` by hand without the nft reload (the set and the file must agree); delete volumes manually; remove a subnet while a quarantined cell still runs (it would regain egress).
- **Commit message** (if the follow-up CLI is built): `Add an operator command to list and discard quarantined cell restores (PV-09)`
