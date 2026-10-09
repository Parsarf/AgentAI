# Phase 10 — coding, research, memory and durable agent work

Status: **BUILD COMPLETE for everything buildable offline; activation BLOCKED.**
Implementation readiness and acceptance are separate: nothing here is deployed,
no customer cell exists, and every runtime behavior is unprobed until Phase 4
cell activation and Phase 15 cases. Date: 2026-10-09. Local only; no paid call,
no deployment, no production migration, no customer contact.

## Delivered (by prompt item)

1. **Roles / tool ceilings** — `agentai_platform/policy_check.py` over the
   recorded inventory: 0 failures. Four customer-blockers recorded (owner
   integration tools on researcher; unsandboxed `main`; global elevated; global
   browser). Metadata only; effective-denial and two-primary-source/injection
   proof are P15-RESEARCH. `config/phase10-fixtures/cases.json` carries the assertions.
2. **Claude Code / ACP** — owner decision 2026-10-09: the build/debug harness is
   **Claude Code on Sonnet 5.5 (`claude-sonnet-5-5`), replacing Codex**.
   `phase-10-harness-inventory.json` records the required identity, roots,
   network, env, auth and billing; none is configured and the launch mechanism
   was read from the installed schema/help and official docs (2026-10-09): `claude-cli` backend or ACP `claude` via acpx; **both run on the Gateway host outside OpenClaw's sandbox**, ACP cannot be spawned from a sandboxed session, and the documented default auth is a subscription login (forbidden for customers). Confinement therefore depends on the customer cell, not Gateway sandbox config. No config was written; nothing was probed live.
   Historical Codex config/evidence is preserved and is not Claude Code evidence.
   The ACP reviewer is also unconfigured and now shares the builder's model
   family, so independence rests on fresh session, snapshot-only input and
   read-only source. Missing safe isolation blocks activation (build blocker,
   not a test gap). Anthropic API access through the metered proxy is the
   candidate route and needs your confirmation.
3. **Procedures** — orchestration, deep-research, software-project, debugging,
   untrusted-content (existing) plus new `browser-task` and `skill-improvement`
   under `config/skills/`. Reviewer request template already exists.
4. **Memory** — `memory.py` (SQL 0009): customer+project scope, source/date/
   confidence/last-confirmed, selective recall, correction, deletion with
   immediate index invalidation, outside content as data, large output by
   artifact reference. Backup/history retention in RUNBOOK.
5. **Durable work** — `durable.py` (SQL 0010): objectives, ordered checkpoints
   with idempotent receipts, native→app state map (unknown ⇒ needs_reconciliation),
   reconcile-before-resume, sticky cancellation across children and restarts.
   **Launch gap, stated plainly:** only *explicit* resume exists; autonomous
   post-restart execution is not implemented (schema forbids recording it). The
   persisted goal record is not autonomous execution.
6. **Scheduling** — `schedules.py`: IANA timezones, bounded timeout, per-run
   budget, cheap-check-first, unattended approval unavailable/expired ⇒ deny,
   pending ⇒ wait, one firing per local day, five-per-account cap. **Creation is
   refused until `enforcement_proven=True`** (not set). The native scheduler's
   capacity of eight is unverified and not used as a product field.
7. **Skills and watchers** — `skills.py` (per-tenant create/list/search/run/
   version, proposals only, outside origin refused) and `watchers.py` (unchanged ⇒
   zero model calls; deduplicated, budget-gated notifications; idempotent
   creation). Fixture assertions in `cases.json` and `tests/test_native.py`.
8. **Fixtures prepared, not run** — board build/browser/review, ID-zero debug
   (existing `config/phase4-fixtures`), `memory-12-facts.json`,
   `durable-three-step.md`, `schedule-nochange.md`, each mapped to its P15 case.

## Claude Code preparation (2026-10-09, nothing applied)

Read-only server probe: no `claude` binary, no acpx, `acp` unset, catalog lacks
`claude-sonnet-5-5`. Prepared (not applied): LiteLLM route, pinned-build
Dockerfile, preflight and activation config batches (dry-run validated on a
scratch profile), and `phase-10-claude-code-activation.md` with ordered steps,
backup-first, probe and rollback. **Open blocker:** Claude Code may spend
outside the LiteLLM proxy caps; customer use stays blocked until proven.

## Checks actually run

- Platform suite: 173 tests OK (2 skipped) — new: `test_native` 10,
  `test_policy_check` 4, `test_durable` 10, `test_phase10_assets` 4. One earlier
  full run had one unidentified failure that did not recur in three subsequent
  full runs (cause not isolated; suspect existing timing-sensitive test).
- `policy_check` CLI: exit 0; output in the evidence folder.
- Not run: Django suite (Django not installed locally; no Django files changed),
  any native/live probe, any Phase 15 case.

## Not claimed

- No native OpenClaw wiring per customer cell (memory plugin, skill dirs, goal
  tools, scheduler) — unprobed; do not guess config fields.
- Customer schedules, ACP review, Claude Code for customers: inactive.
- Heavy/paid cases remain in Phase 15: P15-RESEARCH, -NATIVE-BUILD, -DEBUG,
  -MEMORY, -DURABLE, -SCHEDULE, -SKILLS, -RETENTION-MEMORY.

## Cost, unknowns, blockers, rollback

Cost: zero provider spend. Unknowns: native goal/scheduler behavior, Claude Code
launch mechanism and confinement. Blockers: metered Claude route for builder/reviewer (confirm),
customer cell boundary (Phase 4). Rollback: code-only; migrations 0009/0010 are
additive new tables, so reverting code leaves unused tables.

Evidence: `evidence/product/phase-10/20261009T120000Z/manifest.json`.
