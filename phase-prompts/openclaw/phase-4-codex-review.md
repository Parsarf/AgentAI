# Phase 4 — Verified software build, independent review and debugging

Implement the owner's software-engineering capability: the orchestrator gives
native Codex a scoped task, verifies its artifact, obtains independent ACP
review, fixes valid defects and delivers one useful answer. Prove this path on
two disposable repos rather than reporting successful configuration alone.

Read [the execution contract](execution-contract.md) and apply it throughout.
Start from accepted Gate 3 and the build log's effective trust policy. Check
installed-version docs for the [native Codex harness](https://docs.openclaw.ai/plugins/codex-harness-reference),
[Codex permissions](https://docs.openclaw.ai/plugins/codex-harness-reference/approval-and-sandbox),
[ACP](https://docs.openclaw.ai/tools/acp-agents) and
[ACP delivery](https://docs.openclaw.ai/tools/acp-agents/delivery).

## Required result

A working small app built through native Codex, with real tests, browser
verification and an independent ACP review; plus a broken repo repaired with
a regression test. Both use scoped server workspaces and reproducible commands.

## 1. Verify execution placement and authority

Inventory Codex, its OpenClaw plugin, ACP backend, reviewer harness, auth status
and models on the actual execution host. Prefer an already-authorized Claude
Code reviewer; another supported independent harness is acceptable with a
recorded reason. A builder reviewing its own conversation is not independent.

Document each harness's process location, OS identity, auth source, writable
roots, network access, inherited environment, dynamic tools, approval policy
and timeout before launch. Native Codex is the build path; ACP is the review
path. Inspect effective defaults rather than assuming Gateway exec approvals
or Docker worker settings constrain host-side harness operations. Consult the
current native permission reference for defaults and sandbox-backed execution.

Give the builder only its disposable repo and scratch space. Give the reviewer
read access to the tested snapshot and separate scratch space for checks.
Neither receives owner cookies, ambient channel/provider keys, Docker socket,
live Gateway state or deployment authority. A working directory alone is not
an isolation boundary. If ACP needs host-side launch, constrain the harness
through supported permissions and an appropriate OS/container boundary. Do
not globally disable agent sandboxing or use bypass/full-access modes to pass.
Keep required harness authentication in its supported protected auth path;
project execution must not read or export that credential store.

Run native diagnostics and harmless permission probes: a builder fixture write
inside the repo succeeds; access to a synthetic file outside permitted roots
is denied; a reviewer source write is denied. Record policy and actual results.
Missing server auth or an unsafe/unsupported boundary blocks harness activation.

## 2. Define coding and review contracts

Refine or create `software-project` and `debugging` skills after inspecting
existing procedures. Each states triggers, inputs, steps, verification, limits
and recovery; native policy enforces its permissions.

A coding request includes objective, repo path/starting revision, behavior
spec, acceptance tests, allowed changes, permissions, budget/time allocation
and artifact paths. Require inspection before changes, the smallest complete
solution and a report of actual commands/results. If parallel work is useful,
assign distinct file ownership and integrate before verification.

A review request includes the spec, final diff/snapshot, test evidence and risk
areas. Use a fresh session without the builder's conversation or hidden
reasoning. Findings name file/location, severity, evidence/reproduction and
suggested fix. Disposition every finding as fixed, disproved with evidence or
explicitly deferred. Unresolved acceptance/security defects block completion.

## 3. Build and verify a concrete app

Unless the owner chose a fixture, use a private local task board. It must add
a task, reject blank titles, toggle completion, delete a selected task, filter
all/active/completed and preserve tasks after browser reload. Use local fixture
storage; no production account/service is required. Pick a small stack that
fits the server, lock dependencies and save the spec/checklist before launch.

Have the orchestrator initiate the actual native Codex build; retain native
session/run IDs. Run behavioral tests from the resulting repo through the
supported path and capture command, exit code and tested revision. Start the
app privately and use the restricted browser worker to exercise every core
action, empty/error states, keyboard use and a narrow viewport. Check rendering
and console failures; save sanitized screenshots. A screenshot without working
controls does not pass.

Obtain the independent ACP review, fix valid findings through Codex and rerun
affected tests/browser flows. Deliver the same snapshot that was finally tested
and reviewed, with lockfile and exact start/test instructions. Stop temporary
servers after verification unless the owner needs the preview kept available.

## 4. Prove focused debugging

Use a separate disposable repo with a seeded defect, such as a filter that
incorrectly excludes a task whose ID is `0`. Record correct behavior in a
fixture spec and let Codex reproduce and diagnose observable symptoms. Add a
regression test that fails on the original version, make the minimal fix, and
show the same test plus neighboring cases passing afterward. Preserve failing
output, patch and passing output. Do not weaken the test or replace the repo.

## Artifacts and verification

Produce `plans/phase-4.md`, both repo paths, the skills, sanitized session
references, test/browser evidence, reviewer findings/dispositions and the
execution-contract manifest. Update the build log, relevant architecture and
coding runbook. Run config validation, doctor, native Codex/ACP diagnostics,
secrets/security audits and a changed-artifact secret scan. Check owner-only
launch authority and absence of unexpected live-state changes. Record each
billing route separately; the Anthropic proxy cap does not prove Codex or
reviewer costs are capped.

## Gate 4

PASS requires objective evidence for every item:

1. Native Codex built the app inside the verified execution boundary.
2. All app acceptance assertions and real browser interactions pass.
3. Independent ACP review ran on the delivered snapshot; valid acceptance and
   security defects were fixed and reverified.
4. The debug case has the same regression test failing before and passing
   after the fix, with neighboring behavior preserved.
5. Final policy/health/secret checks and budget evidence meet the contract;
   the artifacts reproduce from their recorded instructions.

Give one synthesized owner-facing report with evidence links. An unavailable
harness, missing auth or unrun check means BLOCKED/FAIL with the precise next
action. Stop after Phase 4.
