# Phase 7 — Repeatable evaluation and operational recovery

This carries useful unfinished *outcomes* from old AgentAI Phase 7 into the
new runtime; it does not copy its pytest stack, Postgres assumptions or Docker
Compose layout. Continue from Gate 6 and read the phase index, architecture,
log, and installed-version docs for evaluations, audit, backup, restore,
updates and recovery. Use the smallest repeatable harness available.

## Work

1. Build `evals/` with input, expected behavior, objective evidence and
   scoring for reasoning, coding/debugging, research citations, browser
   inspection, selective memory, restart resume, provider/tool failure,
   appropriate delegation, cost ceiling and security. Include injection via
   web, email, repo and file; credential exfiltration; policy changes; and
   unattended approvals. Use synthetic secrets and disposable targets.
2. Give each security case a hard pass/fail gate. A skipped check, unavailable
   connector or reviewer assertion without a trace is not a pass. Bound retries
   and cost. Store sanitized transcripts, commands, versions, test artifacts
   and scores so a later session can reproduce failures.
3. Verify operations: a disposable backup of configuration and necessary
   OpenClaw state, a restore into a separate test location, owner access after
   restore, secrets supplied through the documented secure path, restart and
   update rollback steps. Do not reset or overwrite the owner's live state.
   Decide explicitly which old AgentAI data is archived/exported and how to
   verify its retention; do not drag multi-user DB data into OpenClaw blindly.
4. Run the suite, doctor, deep security audit when appropriate, and relevant
   health checks. Fix actual failures and rerun the affected cases. Record
   category scores, cost, gaps and recovery evidence in `BUILD_LOG.md`.

## Gate 7

All security cases pass with evidence. Other categories meet their stated
thresholds or have a concrete gap plan. A disposable restore and restart are
proven. Stop for owner review; no production acceptance claim yet.
