# Phase 0 — Research, migration decisions, architecture

You are designing a **new, single-owner OpenClaw runtime**. Read
`phase-prompts/openclaw/README.md` and the whole
`phase-prompts/openclaw-super-agent-prompt.md` first. The current AgentAI repo
is reference material, not an implementation to port. Do not install,
reconfigure, archive, delete, push, or expose anything in this phase.

## Work

1. Inventory the intended host, installed OpenClaw version if present,
   operating system, Node/Docker availability, existing credentials by *kind*
   only, current gateway state, and the location of the old repo. Do not print
   secret values. If no host is available, write the checks the host operator
   must run and mark host-dependent claims unverified.
2. Read **current official docs** for each brief feature: gateway/channel and
   owner pairing, sandbox/tool policy/exec approvals, sub-agents, native Codex,
   ACP, skills, memory/compaction, cron/background work, usage/budgets,
   integrations, doctor, security audit, backup/restore. Record exact docs
   URLs and the version/command/config path actually supported. Flag missing,
   renamed or incompatible capabilities. In particular, verify whether usage
   visibility is also a **hard enforceable budget ceiling**; do not equate a
   chart or provider quota with an admission control.
3. Write `MIGRATION_DECISIONS.md`: map each AgentAI component to `REPLACED`,
   `DROP`, or a narrowly justified `KEEP`. Cover Python loop, router, tools,
   approvals, Telegram, browser, vault, scheduler, memory, multi-user accounts,
   billing, purchases and test/ops work. Keep the purchase path disabled; plan
   no payment migration. List user data that needs export or retention and
   propose a reversible archive method. Do not archive yet.
4. Write `ARCHITECTURE.md`: host/network, agent roles and actual model IDs,
   which roles see hostile content, workspace/sandbox boundaries, tool
   authority, approval surfaces, Codex/ACP distinction, secrets, budget
   enforcement, persistence, recovery, and acceptance checks. Make optional
   integrations explicit. Resolve contradictory claims in the brief against
   current docs; document the resolution instead of inventing config.
5. Create `BUILD_LOG.md` with a Phase 0 report: evidence, unresolved decisions,
   estimated recurring cost, exact prerequisites for Phase 1, and any blocker.

## Gate 0

The owner can review `MIGRATION_DECISIONS.md` and `ARCHITECTURE.md` as concrete
artifacts. Each feature claim cites current documentation or a local probe.
The old code and live configuration are untouched. Stop for the architecture
decision required by the source brief before installation.
