# Readiness review — 2026-09-27

Verdict: usable private monitoring preview and supervised agent foundation;
not a completed, accepted autonomous personal agent. Build READY labels in the
phase log describe increments, not whole-product readiness. Some remaining
work is implementation, not merely testing.

Scope: read local implementation/plans/evidence and inspect all six live
owner dashboard pages through the existing authenticated browser. No paid
model/provider calls, heavy acceptance suites, failure injection, file
exfiltration, service restarts or configuration changes. Static findings below
are not presented as executed exploit tests. Deployment identity was not
independently compared with the local source hash.

## Capability assessment

| Capability | Evidence and limits |
|---|---|
| Private operations overview | Live gateway HTTP200, Postgres available, spend ledger and recent archive visible. Container summary says ok despite two unhealthy sandboxes. Proxy spend covers its ledger, not all native Codex/ACP/other billing paths; caps are hardcoded display targets, not enforcement proof. |
| Sessions | Live session keys appear; updated-time cells are blank. No conversation viewer or new-chat/reset functionality here. Native Control UI remains the chat/settings surface. |
| Files | Default live page says path rejected. Local safe_rel rejects the empty root and filenames with extensions, so ordinary artifacts cannot be browsed/downloaded as advertised. |
| Approvals | Live page says no pending approvals; approval/denial controls intentionally disabled. This visit does not prove handling of a real pending request. |
| Integrations | Live definitions visible; both Google and GitHub disabled. Owner authentication and repository selection pending. No connected-account read proof. |
| Audit | Live login records visible. Application audit is not a complete agent/tool-action trail and is host-admin editable. |
| Native coding | Earlier build/debugging evidence exists; real browser flows and independent ACP review remain unaccepted. Historical quota exhaustion is a dependency to recheck, not a claim about current availability. |
| Research/trust boundaries | Config and prior permission probes exist; sourced-research/injection gates remain open. |
| Memory/durable goals | Native configuration exists; recall/correction/deletion/cancellation behavior unverified. Autonomous recovery controller is explicitly not configured; owner-driven resume only. |
| Scheduling/recovery | Backup archive verified; timer configured. Scheduled-fire and isolated restored-runtime/rollback proof absent in reviewed evidence. Restore tooling stages clones but refuses startup. Off-host encrypted retention pending. |
| Browser optimization | Disabled offline adapter; worker transport not wired, provider account and separate spend protection pending. Comparison runner records planned baseline runs and always refuses optimized execution; benchmark fixture set has only 10 held-out scenarios versus required 30. |
| Evaluation automation | Case catalog/schema manager implemented. evals/run.py only lists/validates/shows cases; it cannot execute the acceptance suite. This is a missing runner, not just an unrun suite. |

## Concrete dashboard defects found by source review

- File containment checks inspect only the final path for symlinks. Ancestor
  symlinks are unchecked; separate test/stat/cat operations introduce a race,
  and size is checked before an unbounded cat. Requires bounded descriptor-
  based reads with containment enforcement before relying on file access.
- Download signatures cover path and expiry, not the authenticated session,
  despite the evidence claiming session binding. They are replayable during
  the validity window; no one-use consumption exists.
- Logout clears the browser cookie but does not revoke that token server-side.
  Sessions are signed timestamps without random session IDs; same-second
  logins share tokens. Global secret regeneration revokes all sessions but
  does not substitute for per-session invalidation. Failed audit on logout is
  ignored; revoke-all changes state before confirming the audit write.
- Cached spend/connector observations are stamped as current rather than
  retaining the original observation timestamp. Backup freshness reports only
  archive modification time, not completeness of the archive/database pair or
  successful restore. Neither is full health/recovery proof.

## Work needed before calling it finished

1. Fix the file browser/containment, session revocation, download binding,
   misleading health/timestamps and blank session dates; retain private access.
2. Finish executable evaluation tooling and the approved independent review
   route. Either implement supported autonomous resume or explicitly narrow
   the product promise to owner-driven goals.
3. Complete owner-selected account setup; wire optional browser optimization
   only if it remains selected and its isolation/billing prerequisites hold.
   Finish its executable comparison integration and required fixtures first.
4. Run focused, low-cost checks for these defects and essential authorization,
   budget and recovery boundaries when authorized. Full paid comparisons and
   final owner workflow remain deferred until explicit testing resumption.

No acceptance gate was passed by this review. The owner can inspect the private
preview and try supervised workflows while understanding these limitations.
