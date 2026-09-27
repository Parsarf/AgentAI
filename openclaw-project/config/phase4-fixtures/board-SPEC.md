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
