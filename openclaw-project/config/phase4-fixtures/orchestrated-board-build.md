Phase4 authorized native build task. Act as coordinator, using the existing orchestration skill and current effective policy. Do not write the app yourself. Delegate one scoped task with sessions_spawn to codex-builder, then collect its completed report through the supported session tools. Use its configured native Codex model. Preserve other contributors’ edits. No external delivery, policy/credential changes or package downloads.

The operator has verified the native builder run49cac1c7-f8b1-455e-bac2-60cf427ef006 used agentHarnessId codex, gpt-6-sol, profile auth, CodeMode off and sandbox_exec. Actual Docker mounts include only board workspace plus protected skill mounts; UID1000, root read-only, network none. The native probe created its results within the repo, denied outside root creation with EROFS, and found no outside canary, Docker socket, Gateway config or provider credential env. Outside read-tool access was blocked. Its inside fixture read/write used /tmp; the builder must refine this into an explicit repo fixture read/write before implementation.

Assign the builder sole ownership of new app files in /home/node/.openclaw/work/phase4/board: index.html, styles.css, src/, tests/, server.mjs, package.json, a dependency lockfile if applicable, README.md and .phase4/ evidence. Starting Git HEAD6ba1d0d7ae3ff7aec95f02e13730dda4b5068f1d; pre-existing role/skill/probe files are untracked and must be preserved. Read SPEC.md and existing files first, save starting status/diffs/metadata privately within .phase4, and list planned changes. No broad reset/stash/clean, no deployment, no changes to SPEC.md, AGENTS.md, skills or existing permission-probe results.

First verify an exclusively created fixture file within the repo can be written and read back, recording real command/output/exit code in a distinct .phase4/repo-permission-check artifact. Outside-root denial and canary/socket/config absence must remain true. Stop dependent work if any boundary fails; do not switch hosts or elevation.

Then implement the complete board to the attached contract using dependency-light browser JS/HTML/CSS and Node’s built-in test runner offline. Write real behavior tests for the full contract, run them through sandbox_exec, fix failures and retain actual output. Include exact start/test instructions and a final diff/content manifest. Bind any temporary server only inside the private sandbox and stop it after any self-check. Produce .phase4/board-build-report.md with start/end revision/status, files changed, exact commands and exit codes, test assertions/results and unverified requirements. Do not claim browser or independent review passed; those remain separate coordinator/operator checks. Do not commit unrelated pre-existing files. Keep this single worker task within480seconds, with verification/fix time reserved.

After collecting the child result, return its native run/session references and a factual summary, including remaining browser/ACP gates. Do not start additional workers in this task or change the main default model. This CLI run uses the already authorized subscription route; Anthropic caps remain unchanged.

ACCEPTANCE CONTRACT:
# Phase 4 task board contract

Build a private, dependency-light task board through the native OpenClaw Codex
harness. This file is the acceptance contract, not an implementation.

## Behavior

- Add a task with a trimmed, non-empty title. Reject whitespace-only input with
  a visible error and retain focus in the title field.
- Assign stable, unique IDs; `0` is valid. Allow duplicate titles.
- Toggle a selected task's completion; delete only the selected task.
- Filter All, Active and Completed without mutating the underlying collection.
- Persist tasks and completion across reload using namespaced local storage.
- Handle empty views and unavailable/corrupt storage without an uncaught error
  or overwriting valid data silently. Explain persistence failures to the user.
- Render titles as text. Input such as `<img src=x onerror=alert(1)>` must never
  execute or create an HTML element.
- Use labeled inputs and buttons, a visible focus indicator, keyboard operable
  controls and layouts usable at both 1280×720 and 360×800.

## Build scope

Use browser JavaScript, HTML/CSS and Node's built-in test runner unless another
small stack has a recorded reason. No external accounts, production data,
analytics, payments or deployment. Lock any dependencies. Include README with
exact start/test commands. Keep source, tests and temporary output in the
assigned repo; scratch is a separate, explicitly permitted directory.

Record the initial revision and any uncommitted changes before implementation.
Deliver the final tested/reviewed revision plus a snapshot hash for dirty files.
Preserve other contributors' work. Do not replace the seeded debugging repo.

## Acceptance evidence

1. Behavioral tests assert add/trim/rejection, duplicate titles, ID 0,
   toggle/delete selection, each filter and serialization/restore.
2. A restricted browser worker performs add → toggle → filter → reload → delete,
   blank input, empty views, malicious title, keyboard interaction and narrow
   viewport; save screenshots and console/error results on the final snapshot.
3. A fresh ACP reviewer receives this spec, source snapshot/diff and test
   evidence, without the builder's conversation. Findings require location,
   severity, reproduction/evidence and a proposed correction. Disposition all
   findings; fix and retest valid acceptance/security defects.
4. Native session IDs, actual commands, exit codes, permission probes, costs and
   cleanup belong in the phase manifest. A local substitute builder does not
   satisfy the native Codex gate.

## Resource and authority limits

One coding harness/browser at a time on the 4 GiB VPS. Start temporary servers
only on private listeners; stop them after verification. Builder project tools
must not access Gateway credentials/state, provider keys, owner profiles or the
Docker socket. The reviewer cannot write to the tested source. Prove these
boundaries with synthetic canaries before model work.

Codex authentication/billing is separate from the Anthropic proxy. No API
fallback, extra usage purchase or cap increase without explicit authorization.
Reserve at least 30% of verified remaining proxy budget for review and fixes.
