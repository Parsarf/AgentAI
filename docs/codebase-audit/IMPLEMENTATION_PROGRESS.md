# Cleanup implementation progress

Started 2026-10-29. This supplements HANDOFF.md; production has not been changed.

## Completed

- **P0-1 RESOLVED — `a973add`** (M-03 ignore-rule portion, GH-002,
  OP-002, ST-004): private-key filenames, root archives/images, local tooling
  and private exports are ignored; `node_modules` also matches symlinks.
  `git ls-files -c -i --exclude-standard` is empty. Synthetic key/archive paths
  are ignored; source, nested evidence images and audit docs remain visible.
  No files were deleted and no existing work was staged with this commit.

## Preservation and inventory

- A private local snapshot of the inherited modified source, new tool-origin
  files and audit documents was saved under
  `backups/cleanup-start-20261030T015547Z/`, with SHA-256 checksums. The binary
  working-tree patch also preserves the inherited tracked deletions. This is a
  local recovery copy, not an off-server production backup.
- **P0-2 RESOLVED — `cc136cf`:** experiments are preserved and ignored, following HANDOFF.md's
  newer direction. `lumina-cost-audit/` (832 KiB) is ignored by P0-1.
- `openclaw-project/backups/` (496 KiB) remains ignored: one 415,467-byte
  state archive (mode 0600) and five archived pursuit documents. Contents of
  the state archive were not opened.
- `jev-browser/logs/` (10 MiB) remains ignored. Treat its browsing logs and
  screenshots as private; contents were not opened. No deletion is proposed.

## Baseline and checks

- Earlier review: Django accounts 228 passed; frontend 362 passed plus type
  check and production build; tool-origin plugin 3 passed.
- The handoff's platform discovery command needs `-t .` so package-relative
  imports work. Without it: 967 tests, 29 errors, 2 skips. Of the errors,
  24 were sandbox socket restrictions, 3 were local browser-fixture startup
  errors and 2 were package-relative imports. The latter modules passed all
  15 tests when invoked with their package names.
- Tool-origin/relay/bridge/native/supervisor checks with localhost socket
  access: **88 tests passed, 2 skipped** (Linux peer-credential tests on Mac).
- Native-run, request-worker, chat-history and task-progress checks: **66 passed**.
- Tool-origin JS plugin checks repeated during cleanup: **3 passed**.
- One sandbox run reported a concurrent-proof assertion failure. It did not
  recur in 50 isolated repetitions or the unrestricted 88-test run. Keep the
  existing regression test; no production-code change was made for it.

## Tool-origin preservation

- **P0-3 RESOLVED (source custody / AG-006):** owner approved the four
  local commits in this conversation:
  - `82bbdf4`: hook, installer, proof core and JS tests.
  - `af10c90`: relay/bridge/config wiring and Python tests.
  - `6df24da`: end-to-end harness and stub.
  - `6404d90`: ownership docs.
  `evidence/browser-ownership/` remains untracked pending its separate privacy
  review. Production archives matched 131 supervisor + 216 platform source
  files with no changed, missing or unsafe entries. The committed service
  source has no remaining working-tree changes. Release tags/pushes and the
  rest of GH-005 are still pending, not implicitly resolved by these commits.

## CI expansion

- **P3-1 IMPLEMENTED — `671f121`** (M-10, ST-001, AG-017): expanded CI is saved locally; first Linux/GitHub run is pending. Preserve the existing 20 blocking
  modules and promote five locally verified modules (native-run, request-worker,
  chat-history, task-progress, tool-origin): 25 blocking, 48 report-only. Add
  frontend build/tests and plugin tests, and browser tests with a visible
  report-only Linux baseline.
  Chrome fixtures now honor BROWSE_CHROME. The new tool-origin inputs are
  tracked. Local results: original blocking list 244 tests passed (2 skipped),
  Python browse fixtures 78 passed, Node browser runner 26 passed. YAML and all
  run-step shell syntax passed; a synthetic failing test preserved its nonzero
  exit through the blocking pipeline. Explicit bash pipefail prevents tail
  from hiding failures. Linux/GitHub execution remains unverified. Scanner
  tooling is deferred; no unpinned lint tool installation was added. The Python
  fixture job installs browse dependencies and explicitly checks for the configured
  Linux Chrome binary so real-browser classes do not silently stay Mac-only.
  Migration drift check passed with an isolated state directory. The report-only
  runner was exercised with one simulated failing module: all 48 modules were
  reported and the failing exit status was preserved.

## Full integration limitation

The final unrestricted `unittest discover -s tests -t .` run executed **1,012
tests in 299 seconds**, ending with **290 errors and 2 skips**. Error groups:
253 SQLite disk I/O errors, 36 SQLite unable-to-open errors, and 1 explicit
`No space left on device`. The Mac had about **143 MiB free** when checked.
This is not a green full-suite result; rerun after disk space is available.
The focused suites listed above passed before this failure. The explicitly
named test temporary directories contained almost no remaining data, so no
unrelated directories or user files were deleted to free space. No customer
production database was used by these tests.

## Next decision

Owner approved P0-3; all four commits are saved. Next: screenshot privacy
policy (P1-11), including keeping text-only JEV active while leaving the old
optimization switch unwired. Pushing, tagging, deploying, pruning, server
changes and customer-data retention changes remain separate decisions.
