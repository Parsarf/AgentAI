# Phase 8 — Owner acceptance, handoff and runbook

Continue only after Gate 7. Read the phase index, architecture, migration
decisions, build log and evaluation results. Verify current commands and
health checks before using them. This phase tests the finished system; avoid
quietly expanding its authority to make the demonstration pass.

## Work

1. Agree on a small, disposable product idea and an explicit objective
   budget. Prepare only the approvals the owner has already authorized.
   Through Telegram, run the original brief's acceptance flow: research
   existing products; analyze competitors; design a better version; delegate
   implementation to native Codex; run tests; verify the UI in a browser;
   obtain independent review; fix defects; return one clean final report.
2. Observe the actual trace. Check that hostile content stayed with restricted
   workers; Codex wrote in its isolated workspace; ACP review was independent;
   tests and browser verification actually ran; no unnecessary delegation
   happened; approvals were requested before restricted actions; and the
   objective remained within budget. Inspect logs rather than trusting agent
   self-report. Run a final doctor and security audit.
3. Write `RUNBOOK.md`: start/stop/restart, health checks, updates/rollback,
   backup/restore, secret rotation, budget adjustment, integration revocation,
   skill review and how to investigate a failed run. Update `ARCHITECTURE.md`,
   `MIGRATION_DECISIONS.md` and `BUILD_LOG.md` to match reality. Ensure git
   contains only non-secret, reviewable configuration and artifacts.
4. Give the owner a concise handoff: working capabilities, evidence links,
   observed spend, known limits, remaining optional work and a safe shutdown
   procedure. Do not claim end-to-end success for an untested integration.

## Gate 8 — Definition of done

OpenClaw is the sole active agent runtime; the trust-separated design and
security evals pass; delegation and verification work as intended; memory is
selective and correctable; objectives survive restart; budget limits hold;
approved integrations work with scoped authority; the acceptance task finishes
with objective evidence; and the runbook is usable. If any criterion fails,
record it as open and stop short of a completion claim.
