# Resumed file cleanup review — 29 October 2026

**Owner-approved cleanup completed.** A: delete. B: rebuild current main
reports/diagrams and retire the superseded set. C: restore. D: no action.

## Approved execution

| Batch | Result |
|---|---|
| A | Three obsolete prompts removed in `8c10824`. |
| B | Four main current reports plus index and seven rendered SVGs replace the old set in `d9e4e9d`. Twenty-one obsolete files were removed; `findings.md` was rewritten in place so retained historical links still resolve. |
| C | Four task-progress evidence files restored exactly from HEAD and checked against the prior recovery hashes. |
| D | All 14 files left untouched, verified by SHA-256. |

Start at the [current architecture index](../../openclaw-project/docs/architecture/README.md).
Validation checked 115 local links (98 in the main reports), seven Mermaid/SVG pairs, restored file hashes
and the untouched Batch D files. All seven diagrams were visually inspected.
There are no application/runtime source changes, production access or deployment
in this cleanup. Existing recovery archives and Git history are preserved.

The sections below preserve the original review inventory and disposition
reasoning; the decisions above supersede its proposed actions.

## Evidence and scope

- Baseline commit: `3bbc3e98802be6e767f9054313ebc3083dcdc485`. This includes the recorded webhook deployment; the cleanup review changes no production state.
- Inventoried all **244 tracked Markdown paths**: **229 present**, **15 already absent**.
- Checked lexical path references in **1091 tracked source/config/document files**, last Git change per Markdown path, existing route/test/deploy wiring and the earlier audited feature classifications.
- Also recorded 10 additional existing untracked/ignored Markdown paths without opening their contents. Seven private analysis Markdown paths are counted at directory level only. Dependencies, worktrees, runtime state and private logs are excluded.
- **29 tracked files were already deleted in the working tree before this review. Every one has an archive copy whose SHA-256 matches its HEAD version.** All are also recoverable from Git.
- References are lexical evidence, not a complete dynamic call graph. No negative reference count by itself is used to justify deleting a file.
- No additional production access, paid evaluation, customer-data scan or mutating project script was used. No runtime tests are needed for this report-only change.

Full per-file decisions, references, recovery hashes and exact proposed archive destinations are in [CLEANUP_INVENTORY.json](CLEANUP_INVENTORY.json).

## Original recommendation (superseded by owner decisions)

1. Finalize only the **three already-removed obsolete prompts** in Batch A first, after approval.
2. Keep the historical report removals in Batch B only with archive recovery and the listed live-reference repairs.
3. **Restore** the four task-progress evidence files in Batch C: the feature still exists. Do not treat these screenshots as retired functionality.
4. Optionally archive the 14 existing historical docs in Batch D after link/provenance repair. This is not a source-code cleanup.
5. Preserve feature code, runtime instructions and the 19-phase roadmap pending the specific product decisions below.

## Batch A — three obsolete prompts, already absent

These are superseded executable instructions, not live runtime prompt templates. No code/test/config path reference or inbound Markdown link was found for them in this scan. Current continuation uses HANDOFF.md and IMPLEMENTATION_PROGRESS.md. The approved Git deletions are now saved in `8c10824`; Git history and the recovery archives remain available.

- `openclaw-project/plans/product/CLI_HANDOFF.md`
- `openclaw-project/prompt-analysis-2026-10-15.md`
- `openclaw-project/prompt.md`

## Batch B — 22 historical report/diagram files, already absent

The newer codebase audit supersedes these reports for current navigation. Preserve both recovery archives and Git history. These are not customer runtime files. The main reports were rebuilt and this batch is complete in `d9e4e9d`. `findings.md` now contains a current replacement, resolving the links below without editing Batch D.

- `openclaw-project/docs/architecture/findings.md`
- `openclaw-project/docs/orchestration-audit/02-path-registry.md`
- `openclaw-project/docs/orchestration-audit/03-entry-points.md`
- `openclaw-project/docs/orchestration-audit/04-current-orchestration.md`
- `openclaw-project/docs/orchestration-audit/05-state-events-persistence.md`
- `openclaw-project/docs/orchestration-audit/06-history-and-legacy.md`
- `openclaw-project/docs/orchestration-audit/07-registries.md`
- `openclaw-project/docs/orchestration-audit/08-inconsistencies.md`
- `openclaw-project/docs/orchestration-audit/09-coverage-ledger.md`
- `openclaw-project/docs/orchestration-audit/README.md`
- `openclaw-project/docs/orchestration-audit/svg/04-current-orchestration-1.svg`
- `openclaw-project/docs/orchestration-audit/svg/04-current-orchestration-2.svg`
- `openclaw-project/docs/orchestration-audit/svg/04-current-orchestration-3.svg`
- `openclaw-project/docs/orchestration-audit/svg/04-current-orchestration-4.svg`
- `openclaw-project/docs/orchestration-audit/svg/04-current-orchestration-5.svg`
- `openclaw-project/docs/orchestration-audit/svg/04-current-orchestration-6.svg`
- `openclaw-project/docs/orchestration-audit/svg/04-current-orchestration-7.svg`
- `openclaw-project/docs/orchestration-audit/svg/05-state-events-persistence-1.svg`
- `openclaw-project/docs/orchestration-audit/svg/05-state-events-persistence-2.svg`
- `openclaw-project/docs/orchestration-audit/svg/05-state-events-persistence-3.svg`
- `openclaw-project/docs/orchestration-audit/svg/06-history-and-legacy-1.svg`
- `openclaw-project/reviews/readiness-2026-09-27.md`

Original broken links (now resolved by the in-place findings replacement):

| Source | Missing target | Proposed repair |
|---|---|---|
| `openclaw-project/docs/architecture/README.md:18` | `openclaw-project/docs/architecture/findings.md` | Link to the current technical-debt register or name the archived historical report explicitly; update links in any file moved by Batch D. |
| `openclaw-project/docs/architecture/agent-execution.md:77` | `openclaw-project/docs/architecture/findings.md` | Link to the current technical-debt register or name the archived historical report explicitly; update links in any file moved by Batch D. |
| `openclaw-project/docs/architecture/task-lifecycle.md:74` | `openclaw-project/docs/architecture/findings.md` | Link to the current technical-debt register or name the archived historical report explicitly; update links in any file moved by Batch D. |

The architecture index was rebuilt. The two historical source pages remain byte-for-byte unchanged as required by Batch D; their findings.md links now resolve. Immutable historical evidence/audit bodies were not rewritten.

## Batch C — four evidence files to restore, not delete

`task_progress.py`, its relay integration and `tests/test_task_progress.py` remain present; task progress is a live feature. These files document its prior desktop/mobile verification. All four are restored from HEAD and their hashes match the verified archive/HEAD snapshot. Old screenshots do not mean an old feature.

- `openclaw-project/evidence/task-progress/README.md`
- `openclaw-project/evidence/task-progress/direct-desktop.png`
- `openclaw-project/evidence/task-progress/plan-desktop.png`
- `openclaw-project/evidence/task-progress/plan-mobile.png`

## Batch D — owner deferred; all 14 files untouched

Proposed destination rule: `docs/archive/2026-10-cleanup/<original repository-relative path>`. The JSON inventory expands every source/destination pair. **Do not move anything yet:** source links, relative diagram links and historical/eval citations must be preserved or repaired as one change. Archive is preferable to deletion.

| Existing path | Reason |
|---|---|
| `openclaw-project/docs/architecture/agent-execution.md` | Explicit Historical banner; native-execution.md is the successor. Preserve referenced diagrams and update inbound links together. |
| `openclaw-project/docs/architecture/task-lifecycle.md` | Explicit Historical banner; native-execution.md is the successor. Preserve referenced diagrams and update inbound links together. |
| `openclaw-project/docs/architecture/tool-routing.md` | Explicit Historical banner; native-execution.md is the successor. Preserve referenced diagrams and update inbound links together. |
| `openclaw-project/lumina/.impeccable/critique/2026-10-23T20-20-08Z__src-pages-chat-tsx.md` | Dated UI critique, not live instructions or runtime code; keep a historical copy, move only with any paired review assets. |
| `openclaw-project/lumina/.impeccable/critique/2026-10-23T20-36-56Z__src-pages-chat-tsx.md` | Dated UI critique, not live instructions or runtime code; keep a historical copy, move only with any paired review assets. |
| `openclaw-project/plans/phase-10.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |
| `openclaw-project/plans/phase-4-manual-chrome.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |
| `openclaw-project/plans/phase-4.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |
| `openclaw-project/plans/phase-4a.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |
| `openclaw-project/plans/phase-5.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |
| `openclaw-project/plans/phase-6.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |
| `openclaw-project/plans/phase-7.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |
| `openclaw-project/plans/phase-8.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |
| `openclaw-project/plans/phase-9.md` | September owner-runtime phase plan; preserve as history rather than run as current instructions. Update plan/evidence links before moving. |

Two older plans are intentionally kept in place rather than included in this batch:

- `openclaw-project/plans/phase-8b.md`: Source provenance reference at platform/agentai_platform/storage.py:5 describes the fixed symlink race. Preserve in place until that reference is deliberately updated; this is a comment, not a runtime loader.
- `openclaw-project/plans/remaining-build-items.md`: evals/cases.yaml:169 still cites section 1 as the reviewer-admission blocker. Preserve the referenced plan with the frozen eval context; this is a status reference, not a Markdown execution path.

## Update/merge these 15 documents rather than delete them

Entry points, operational guidance and API/design contracts remain useful even when their status prose is stale. Existing audit/deployment records resolve production claims. Exact text changes should be a separate approved documentation task; this review does not silently apply them.

| Path | Finding |
|---|---|
| `README.md` | Entry point still says agent execution is pending; preserve and update current status. |
| `openclaw-project/ARCHITECTURE.md` | Architecture still names the old host; preserve design and correct current-state signposts. |
| `openclaw-project/README.md` | Entry point still describes IONOS, future customer accounts and next phase 4. |
| `openclaw-project/RELEASE_NOTES.md` | Keep release history; reconcile stale running-release/latest headers with the verified deployment record. |
| `openclaw-project/RUNBOOK.md` | Operator guide has stale foundation status and dead-host commands; retain and reconcile before use. |
| `openclaw-project/SERVER_DEPLOYMENT.md` | Historical deployment plan presented with stale operational assumptions; banner and point at current operations. |
| `openclaw-project/deploy/README.md` | Owner-stack guide has stale LiteLLM port prose; do not delete deployment guidance. |
| `openclaw-project/docs/SYSTEM_DESCRIPTION.md` | Useful current description; parked expiry and Telegram completion prose must be qualified against open findings. |
| `openclaw-project/docs/architecture/README.md` | Active index still links the already-missing findings.md; also references historical diagrams. |
| `openclaw-project/docs/architecture/native-execution.md` | Useful current map; reconcile parked-run guarantees with open AG-005 rather than deleting the document. |
| `openclaw-project/docs/architecture/system-overview.md` | Component map predates removal of the old loop; update or merge with native execution map, preserving history. |
| `openclaw-project/docs/browser-reliability.md` | Retain browser-fix history; old trust-boundary prose needs to point to protocol 2 ownership. |
| `openclaw-project/plans/product/privacy.md` | Reconcile statements with verified relay doors and existing screenshot policy; owner explicitly deferred egress behavior changes. |
| `openclaw-project/platform/UI_CONTRACT.md` | Active API guide; reference-client and advertised limits need review against actual routes before retiring the sample. |
| `openclaw-project/platform/deploy/README.md` | Foundation-era prose precedes later deployment information; distinguish historical steps from current release.py workflow. |

## Feature and roadmap decisions — preserve until decided

| Item | Current evidence | Recommended decision |
|---|---|
| `phase-prompts/` — 25 Markdown files | The replacement roadmap includes both previously built phases and incomplete/future acceptance, integrations, purchases and deferred work. Its index has stale “next phase 4” prose. | Keep as a versioned historical/unfinished roadmap. If retiring executable prompts, first name the successor roadmap and preserve unmet requirements; do not delete the entire directory as “done”. |
| `openclaw-project/lumina-character/` — 4,697 tracked files, 8 Markdown files | No current deploy/CI reference found. It retains unique film, question and vault UI that the shipping app lacks. | Decide whether to preserve those features. Recommended: retain the fork until needed components are ported, then archive it in a separate approved change. The inventory contains its exact tracked-file list. |
| `platform/ui-reference/` — `app.js`, `app.css`, `index.html` | Not the deployed SPA; explicitly recommended by `platform/UI_CONTRACT.md:10`. | Keep for now or retire the three-file example together with its contract reference. Exact paths are in the inventory. |
| `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py` | Unfinished/disabled product modules; tests and persisted tables remain; restore logic enumerates their data. | Park, rather than delete, unless the owner explicitly retires each product capability and its data contract is handled. |
| `optimization.py`, `policy_check.py`, `genui/intent.py`, `ops/rotation.py`, `lifecycle/broker.py` | Existing tests, switches, CLI/test/incident-response or historical fixture intent; no missing import by itself establishes retirement. | Preserve. Screenshot policy changes were explicitly deferred; cleanup must not change JEV behavior or toggle that gate. |
| `jev-browser/`, `jev-window-core/`, ignored `experiments/jev-full-page/` | Prototype/experiment source and design history; some untracked content may be the only local copy. | Keep or archive after private-state/source review; do not delete or commit their browsing logs. |
| `lumina-cost-audit/`, backups and private exports | Ignored private analysis/state, not application source. | Keep private; decide retention separately. This report does not inspect customer text, keys or archive state payloads. |

## Must keep

- `browse/runner.mjs`: the verified production browser engine, regardless of an old “legacy” label.
- `gen/legacy.tsx`, `components/genui/Cards.tsx`, forms/plan renderers: historical stored cards or current actions still depend on them.
- `config/skills/*/SKILL.md`: explicitly checked by `platform/tests/test_phase10_assets.py:21–26`.
- `config/phase10-fixtures/` Markdown: paths are loaded from cases.json and asserted to exist by the same test module. Other phase fixtures/templates may be host-installed; that is unresolved, not proof of retirement.
- SQL/Django migrations, restore table classifications, unit/release definitions, CI and tests: no blanket removal under the old-file cleanup.
- AGENTS.md, the existing local CLAUDE.local.md, design tokens/guides, CREDITS and vendor attribution: retain with their project/assets. CLAUDE.local.md changes remain proposals only.
- Current audit/handoff/progress/deployment records and immutable verification evidence. Older dates do not make recovery material disposable.

## Markdown disposition totals

| Disposition | Count |
|---|---|
| `archive_candidate` | 14 |
| `archive_existing_deletion` | 11 |
| `delete_candidate` | 3 |
| `keep` | 103 |
| `keep_history` | 64 |
| `owner_decision` | 33 |
| `restore_candidate` | 1 |
| `update_or_merge` | 15 |

These counts cover the 244 tracked Markdown paths, including the 15 already absent. The separate 29-file deletion ledger also includes 11 SVG diagrams and 3 PNG images. All paths and reference evidence are in the JSON inventory.

## Recovery archives verified

| Archive | Regular file entries | SHA-256 |
|---|---|
| `/Users/parsa/AgentAI-removed-20261029.tar.gz` | 59 | `c2a227ae2ef8da2e22c983ba69594410960a3e0304a23b9c22206dc449bdb24a` |
| `/Users/parsa/AgentAI-removed-handoffs-20261029.tar.gz` | 2 | `5d0962eb9e9a7d95689c593121973b891a3f196cad76b43aeacb4d1636495da0` |

The existing 29 deletions match their HEAD and archive bytes exactly. This is evidence of recoverability, not approval to delete additional files. Archive contents were hashed without extracting or executing them.

## What this review changed

The initial proposal created this review/inventory and a cleanup-plan link. The owner then approved A/B/C: prompt deletions and rebuilt main reports were committed, evidence was restored, and Batch D remained unchanged. Documentation links, SVG renders and file hashes were checked. No runtime tests, paid evaluations, production commands, pushes or deployments were performed for these documentation changes.

**Completed scope:** approved A/B/C only; D is deferred. No further feature retirement, production change, customer-data erasure, recovery-archive deletion or frontend-fork removal is authorized by these batches.
