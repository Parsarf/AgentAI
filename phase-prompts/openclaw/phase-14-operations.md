# Phase 14 — Backups, recovery, monitoring and security operations

**Stage:** Build. **Dependencies:** 4–13.

## Paste this prompt

Execute only Phase 14 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Extend existing operator backup/freshness/restore tools to the customer platform.

1. Inventory all recovery assets: per-tenant state/workspaces/auth/plugins/artifacts, application database/mappings/events, proxy budget/spend database, pinned deployment versions and encryption custody. Use consistency-aware native archives and database backups; a live database filesystem copy is insufficient.
2. Implement encrypted off-host backups using an approved destination and key-custody path, verification, per-tenant manifests, bounded retention/pruning and failure alerts. Keep decryption keys separate and raw archives private. If destination/key custody is missing, complete tooling and record the launch blocker rather than claiming secure off-site recovery.
3. Prepare restore of account A without replacing account B or resetting the shared usage ledger. Scope application rows/relationships, regenerate secret bindings safely, preserve or reconcile spend history and disable cloned channels/outbound jobs before startup. Restored billing state must reconcile current provider state, not blindly reinstate old access.
4. Add tenant-aware health/task/deployment/usage/queue/backup monitoring, correlation IDs and stale/unknown states. Alert only through authorized destinations. Define support access, incident severity, escalation, notification drafts, provider/tenant suspension, failed-task triage and privacy-safe diagnostics.
5. Implement ingress/account/task/stream/provider rate limits, dependency/image pinning, secret rotation/revocation procedures, release canaries, schema-compatible rollback and host exposure checks. Review every cross-customer path, including shared control services, storage URLs, worker processes, caches, metrics, backup exports and support tools.
6. Use proposed RPO 24h/RTO 30min unless the contract chose others. Prepare scheduled-backup observation, tenant restore/restart/corruption rejection and rollback drills in isolated targets. Check available capacity first; never prune unrelated live data for a drill.

Deliver encrypted backup/restore tooling, monitors/alert adapters, incident/security/runbooks and release rollback. Done when setup checks succeed and every selected production service has an observable recovery path and owner. Actual scheduled-fire, measured RPO/RTO and no-cross-tenant restore proof remain Phase 15 requirements.

## Required close-out

Update `openclaw-project/plans/product/phase-14.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-14/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
