# Phase 1 — Product contract, screens and cost model

**Stage:** Design. **Dependencies:** None.

## Paste this prompt

Execute only Phase 1 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Define the first customer offer and reconcile the current personal-agent architecture with the hosted customer product requested by the owner. Read the current implementation and evidence; produce a requirement inventory before designing new services.

1. Specify supported launch tasks: sourced research, a small app build/debug workflow, project files, dashboard/Telegram conversations, and observable task execution. Classify memory, durable work, scheduling and each connector as launch-required or an explicit later release. Carry every requirement into the backlog even if its release is later; never silently omit it. Keep purchases by the agent separately disabled: service subscription billing does not authorize agent purchases.
2. Specify exact accepted input/output file types, MIME validation, per-file and total upload limits, project/artifact storage, task duration, concurrent tasks, model routes, maximum task budget, daily/monthly limits, trial rules and plan entitlements. Give every limit a unit and enforcement point. Choose numeric defaults as proposed product decisions, not existing implemented facts.
3. Define queued/running/waiting/paused/cancelled/failed/budget-exhausted/completed states and observable outcomes. Explain partial outputs, bounded retries, uncertain external writes, refunds/credits, spending estimates versus final charges, unavailable providers, support escalation and budget stops. Specify whether pause means execution pause or only timeline pause.
4. Specify retention separately for chat, memory, uploads, artifacts, events, audit, backups, billing and provider copies. Define export, account deletion, backup expiry and legal retention decisions; do not promise instant removal from providers/backups. Decide the lawful product disclosures with the owner where needed.
5. Design the actual screens and navigation: sign-in/recovery, onboarding/deployment status, overview, projects, conversation/task/live timeline, files and artifact versions, approvals, memory/schedules, integrations, usage/billing, account/Telegram linking and internal operations. Provide annotated wireframes with loading/empty/error/offline/budget-denied states, accessible controls and mobile layouts. Reuse the dashboard's existing useful design.
6. Write one complete example: a private reading-list app with validated title/URL, tags/search/status/notes, reload persistence and JSON export. Map its research → plan → build → tests → browser → independent review → fixes → ZIP handoff to screens, native operations, task states, usage and assertions. No public app deployment is required.
7. Create a cost/capacity worksheet covering every model, Codex/ACP, search, optional Jev, infrastructure, database, storage/backups, identity/mail, monitoring and payment fees. Record dated sources or an explicitly unknown input; calculate scenario totals using the formulas in the execution contract. Show conservative concurrency/headroom and break-even assumptions. Do not claim a four-GiB VPS can host two tenants without measurement.

Deliver `product/CONTRACT.md`, `product/SCREENS.md`, `product/EXAMPLE_TASK.md`, `product/COST_CAPACITY.md` and the initial requirements/status ledger. Record consequential unresolved choices. Done when a customer can understand the offer and every launch feature has an ID, numerical limit where applicable, observable assertion, implementation phase and acceptance case.

## Required close-out

Update `openclaw-project/plans/product/phase-01.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-01/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
