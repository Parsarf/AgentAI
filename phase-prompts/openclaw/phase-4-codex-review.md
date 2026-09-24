# Phase 4 — Native Codex build path and independent review

Continue from Gate 3. Read the phase index, architecture and build log.
Check the installed-version [native Codex](https://docs.openclaw.ai/plugins/codex-harness-reference)
and [ACP](https://docs.openclaw.ai/tools/acp-agents) docs separately. The
native Codex app-server path is the default coding path; ACP is the route for
Claude Code/Gemini reviewers, not a synonym for native Codex.

## Work

1. Configure Codex with its own scoped project workspace and the approved
permission policy. Verify the host's Codex auth without exposing a token.
Use documented native diagnostics and a harmless dry run before code changes.
2. Configure the supported ACP backend and at least one available independent
review harness, preferably Claude Code if the owner has installed and logged
in. Verify `/acp doctor` or its documented current equivalent, actual harness
auth, cwd access and permission behavior. If reviewer auth is absent, mark the
review gate blocked rather than substituting an unverified claim.
3. Write compact `software-project` and `debugging` skills. Require a concrete
plan, bounded build attempts, tests that exercise behavior, browser inspection
for UI work, independent review for consequential work, and one final report.
Do not turn every task into a multi-agent workflow.
4. Give the orchestrator a small disposable app task. Have native Codex build
it in a project workspace. Run the tests yourself through the supported path,
inspect the app, obtain ACP reviewer findings, fix valid defects, and rerun the
relevant check. Then provide a deliberately broken disposable repo and verify
a focused regression test proves the fix.
5. Run doctor, Codex and ACP diagnostics, security audit and a secret scan.
Record artifacts, exact checks, reviewer findings, fixes and cost in the log.

## Gate 4

Codex built a working artifact, objective tests passed, the independent
reviewer actually ran, and the debug case has a regression test. The owner
sees one synthesized answer with the evidence. Stop at this gate.
