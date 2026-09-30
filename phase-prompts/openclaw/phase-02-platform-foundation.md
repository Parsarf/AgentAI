# Phase 2 — Platform architecture and secure runtime boundary

**Stage:** Build. **Dependencies:** 1.

## Paste this prompt

Execute only Phase 2 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Build the product foundation around the existing OpenClaw runtime; do not reinstall or rebuild working owner capabilities.

1. Inventory actual runtime versions/digests, app dependencies, host resources, network listeners, secret custody, database layout, existing budget controls, workers, Codex/ACP placement, jobs and backup tools. Use sanitized evidence, not historical deployment assumptions. Produce an installed-capability matrix with exact APIs/config/permissions verified through local source/help/schema and current primary documentation.
2. Design browser → application API → tenant routing → private Gateway; a separate narrow provisioning control service owns lifecycle operations. Keep Gateway/proxy/database private. Separate application records from native agent state. Define the API/role/object matrix, migration/version policy and machine-readable schemas for accounts, deployments, projects, conversations, tasks, operations, events, artifacts, usage and entitlements. Use tenant ownership constraints on relationships, not just opaque IDs.
3. Define the isolation threat model for mutually untrusted customers, including container/VM boundary, Docker daemon/socket authority, mount/network restrictions, provider auth and host-side Codex/ACP. A different session or working directory is insufficient. Document the chosen boundary and any stronger host/VM requirement before enabling customer execution.
4. Create maintainable app/control-service skeletons and database migrations with locked dependencies, config validation, secure defaults, health/readiness endpoints, structured redacted logs and correlation IDs. Prefer extending useful existing code; replace an owner-only assumption where it conflicts with the product contract.
5. Preserve least-authority sandbox policies, researcher/browser/critic separation, restricted outbound actions and stricter unattended execution. Raw outside content is attributed data. Skills guide procedure and cannot grant authority; skill improvements are proposed diffs, never automatic policy changes.
6. Prepare reversible deployment/migration steps, TLS ingress design, environment examples without secrets, server-side gates, and integration fixture interfaces. The web app receives neither Docker socket nor arbitrary shell/RPC endpoints. Use private previews while public rollout is pending.

Deliver architecture/API/role/isolation records, migrations, service skeletons, deployment/rollback instructions and version-contract fixtures. Done when the foundation starts privately with bounded resources, validates its schema, keeps secrets out of browser assets/logs, and supports server-side ownership enforcement. Customer activation waits for Phases 3–5 boundary proof.

## Required close-out

Update `openclaw-project/plans/product/phase-02.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-02/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
