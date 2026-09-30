# Phase 4 — Isolated customer agent lifecycle

**Stage:** Build. **Dependencies:** 3.

## Paste this prompt

Execute only Phase 4 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Target: **one service-operated VPS and one shared public domain**. Customers
supply no servers/domains. Read the Phase4 single-VPS assessment and deployment
policy and `product/EXISTING_VPS_TRIAL.md`; the earlier ADR002 VM-per-customer
target is superseded. Target the existing VPS first; do not require a hardware
upgrade to finish the build. The default-cell snapshot admitted zero agents;
measure a smaller on-demand profile rather than guessing that it fits. Keep all
planned features and ownership boundaries; queue work that cannot be admitted.

Automate native Fleet cells through the narrow internal control service,
preserving the owner deployment. A cell and all its coding/reviewer/browser
workers need distinct effective identities/storage/network/secret boundaries and
a verified stronger runtime for untrusted code. Neither app nor Gateway receives
the host Docker socket. Evaluate worker-broker/native sandbox integration before
activation. Separate customer VMs are an optional later scaling path, not the
required customer onboarding model.

1. Implement create/start/stop/upgrade/backup/restore/delete operations with durable operation IDs, account binding, generation/revision, pending/ready/failed/deleting states, leases/timeouts, retry/reconciliation and scoped cleanup. A retry after partial setup must converge on the same deployment; reconcile uncertain results before repeating effects.
2. Give each customer a separate Gateway, state/workspace/memory/artifact roots, secret store, Gateway credential, provider virtual key or independently enforced budget, network boundary and CPU/RAM/PID/disk quotas. Separate coding/reviewer/browser execution too. No customer process receives host Docker socket, another deployment's mounts, shared owner auth or provisioning credentials.
3. Keep the single customer bot at ingress rather than polling its token from every Gateway. Preserve existing owner bot behavior until a documented migration/cutover; two pollers with the same token are invalid. Link app identity to native agent identity internally.
4. Implement the existing-host trial profile: two invited account records, at most one running customer cell/task globally, safe on-demand wake/drain/stop and sequential isolated build/browser/review stages. Account creation must not start a cell. Measure fixed host overhead and per-stage/tenant peaks; enforce atomic headroom admission, reservations for starting/uncertain/maintenance states and bounded per-account queues. Show capacity waits without exposing another account. Preserve owner work; never stop a live owner workload to admit a customer. A failed wake must preserve history/artifacts and retry safely. Do not assert a smaller cap proves a usable profile. Keep optional later resize as a throughput change using the same accounts/domain.
5. Upgrade by pinned image/config version with backup, compatibility check, canary/health and rollback. Restore one tenant into a separately reserved quarantined cell with independent roots/network on the VPS with outbound channels/jobs disabled. Preserve usage/key identity and reconcile pending effects. Delete only the bound tenant after the contract's retention/grace rules and revoke secrets/keys.
6. Prepare simultaneous A/B fixtures with unique canaries for chats, memory, files, tools and credentials; prove mounts, networks and effective worker authority deny cross-access. Exercise failed creation/retry and deletion isolation locally where feasible. Full live concurrency, restore and failure drills remain Phase 15.

Deliver lifecycle API/worker, deployment templates, capacity admission, reconciliation/cleanup and fixtures. Done when the deterministic lifecycle works in a disposable environment, failed setup is safely retryable and no app endpoint can select another tenant's deployment. Mark live two-customer isolation acceptance pending until actually measured and tested.

## Required close-out

Update `openclaw-project/plans/product/phase-04.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-04/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
