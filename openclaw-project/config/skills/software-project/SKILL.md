---
name: software-project
description: Run a scoped build or change task on a software repo with acceptance tests and an evidence report. Use when a request names a repo, a spec, and done criteria.
---

# Software project task

## Task contract

Objective; repo path + starting revision; behavior spec; acceptance tests or
checklist; allowed change scope (files/dirs); permissions; time/budget bound;
artifact paths (diff, test output, report).
Derive these from the request, repo and accepted phase plan when available.
Record routine assumptions; ask only for missing information that blocks safe
implementation, and continue independent work meanwhile.

## Steps

1. Inspect before changing: read the spec and relevant code. Record the starting
   revision, staged/unstaged changes and untracked files. Save a private patch
   or snapshot of existing edits before touching those files. Run the existing
   tests and distinguish known baseline failures from regressions you introduce.
2. Plan the smallest complete solution. Note every file you will create or
   modify before you touch it.
3. Implement inside the allowed scope only. No new dependencies without a
   recorded reason and a locked version.
4. Run the acceptance tests with exact commands. Capture command, exit code,
   and output. If a test fails, fix and rerun; do not weaken a test to pass.
5. For UI work, use the authorized browser worker to exercise core actions,
   persistence, empty/error states, keyboard operation and a narrow viewport.
   Inspect console failures and retain sanitized screenshots. If unavailable,
   record the unmet verification requirement; screenshots alone do not pass.
6. When the phase or task requires independent review, request a fresh ACP
   reviewer on the tested snapshot with the spec, diff, commands and results;
   omit the builder's conversation. Record every finding and its disposition,
   fix valid defects and rerun affected checks on the final snapshot.
7. Compare final changes against the captured starting state, including staged
   and untracked files. Preserve other contributors' changes; a diff stat alone
   does not prove that every edit belongs to this task.
8. Report: revision and working-tree snapshot tested, exact commands + results, files changed, known
   limitations, artifacts written. Report facts observed, not intentions.

## Limits

- Never modify policy, credentials, CI secrets, or files outside scope.
- Never mark acceptance done from a plan or a mock; only from a run.
- A known baseline defect may be the requested work. Report unrelated failures
  separately. A missing permission blocks only dependent actions; continue
  useful authorized work and identify the precise remaining requirement.

## Recovery

Undo only your own changes using the recorded starting patch/snapshot. Never
use broad checkout, reset, clean or stash operations to discard another person's
work. If overlapping edits cannot be separated, preserve the current state and
report the conflict. Prefer a disposable worktree for risky experiments.
Retry a transient command at most twice, then change approach and record why.
