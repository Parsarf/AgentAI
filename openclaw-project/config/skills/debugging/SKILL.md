---
name: debugging
description: Reproduce, isolate, and fix a reported defect with a regression test that fails before the fix and passes after. Use when something behaves wrongly and the cause is unknown.
---

# Debugging task

## Inputs

Symptom report (expected vs actual); repo path + revision; how to run the
tests; scope of allowed changes.

## Steps

1. Reproduce first: write or run the smallest command that shows the wrong
   behavior. Capture the exact output and starting working-tree state. If the
   symptom cannot be reproduced, report it as unconfirmed and investigate the
   missing conditions; do not dismiss intermittent defects or claim a fix.
2. Isolate: form one hypothesis at a time; probe with the cheapest check that
   can disprove it (log, REPL, targeted test). Read the responsible code
   before editing anything.
3. Record the correct behavior as a failing regression test BEFORE fixing.
   Run it: it must fail on the original code for the right reason.
4. Fix the root cause with the smallest complete change. No drive-by
   refactors, no dependency changes, no test weakening.
5. Run the regression test, the full neighboring suite, and re-verify the
   original repro. All must pass.
6. Preserve evidence: failing output (before), the patch (diff), passing
   output (after). State root cause in one sentence with file:line.

## Limits

- Never delete or skip a failing test to make a suite green.
- Never "fix" by disabling the feature or catching the error silently.
- Compare plausible fixes by correctness, compatibility and maintenance cost;
  prefer the smaller change when those are equal. Record the rejected approach.
- Preserve pre-existing staged, unstaged and untracked work. Use a private
  starting patch/snapshot or an isolated worktree before risky experiments.

## Recovery

If evidence changes the scope, revise the hypothesis and plan. Undo only your
own attempted fix against the captured starting state; retain the regression
test and evidence. Never broadly reset, checkout, clean or stash other people's
edits. Preserve overlapping changes and report a conflict if safe separation
is impossible.
