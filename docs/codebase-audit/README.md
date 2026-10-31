# Lumina codebase audit (2026-10-29)

Start here. Scope: everything under `/Users/parsa/AgentAI`. Method: seven scoped investigators + two gap-closing investigators + read-only SSH verification of production (Hostinger `srv2054170`).

| Read this | When |
|---|---|
| **`HANDOFF.md`** | **Give this ONE file to the AI doing the cleanup: self-contained state, rules, ordered task queue, owner decisions** |
| `TECH_DEBT_AUDIT.md` | Executive summary, top 5 fixes, quick wins, open questions |
| `PRODUCTION_VERIFICATION_2026-10-29.md` | What was actually verified on the live server (overrides "unverified" elsewhere) |
| `CLEANUP_PLAN.md` | Prioritised, dependency-aware plan with the A–G classes, preserve list, do-not-do list |
| `TECHNICAL_DEBT.md` | Full register (125 rows + Supplement A) |
| `SECURITY_AND_RELIABILITY.md`, `DEPLOYMENT_AUDIT.md` | Risks; repo vs production |
| `SYSTEM_OVERVIEW.md`, `ARCHITECTURE.md`, `EXECUTION_FLOWS.md`, `FILE_MAP.md`, `DEPENDENCIES.md` | How it works |
| `FEATURE_INVENTORY.md`, `INCOMPLETE_FEATURES.md`, `LEGACY_CODE.md`, `ORPHANED_CODE.md`, `DUPLICATIONS.md` | What exists and its status |
| `AUDIT_COVERAGE.md` | What was and was not verified |
| `CLAUDE.proposed.md` | Draft project context file for future AI sessions (not installed) |
| `phases/` | Detailed per-task fix specs (4 files, ~3,100 lines): files, diffs, tests, commands, acceptance, rollback |
| `_findings/` | Raw investigator reports (backend, orchestration, frontend, infra_security, structure, history, outside_project, gap_backend, gap_tooling), reconciliation notes, raw server output |
