# Legacy and superseded code

Audit date 2026-10-29, branch `product-phases-6-11`, HEAD `03662de`. Production is UNVERIFIED for every item (no SSH or network access succeeded; see L-01..L-03 in `_findings/00_RECONCILIATION.md`).

Class labels (as used by the investigators, inferred): A = safe cleanup after verification, B = consolidate, C = product decision, D = targeted repair, E = architecture change, F = fix/harden, G = preserve/document. Rule for this file: "recommended class" is a recommendation to the owner, never an instruction to delete. Git history and tags make most of these recoverable, but nothing here should be removed before the VPS comparison (IS checklist) and an owner decision.

## Summary

| # | legacy item | replaced by | superseding commit | recommended class | risk of touching |
|---|---|---|---|---|---|
| L1 | `ServiceRouter` / `routing/services.py` | browser as native tool; JEV only shadow + display + classifier | `5db9636` | C then G (docs fix) | Low (code gone); docs/ops drift |
| L2 | Host Docker `browse/runner.mjs` engine | native cell browser (`native_runner.py`) | `d95b796` (native engine added); deletion not done | C, E (do not delete before gate) | High (default engine) |
| L3 | Old genui v0 -> v1 -> registry | `src/gen/*` + server registry/artifacts | `07fd6b9` (v1 by `b1439f8`, `a7bdfae`) | B after C | Medium (stored cards) |
| L4 | `lumina-character` skin / film / parchment | dark default in `lumina/`; fork kept | `d95b796` (move), `5db9636` (dark default) | C, G | Medium |
| L5 | `agentai-supervisor.service` | `agentai-supervisor-native.service` | native migration (26-27 Oct) | A after VPS check | Medium |
| L6 | Platform control server (`server.py --service control`) | Django app + gunicorn | foundation to Django move (Oct) | C then A | Low-Medium |
| L7 | `platform/ui-reference/` | `lumina/` SPA served at `/app/` | d95b796 era | C | None |
| L8 | `jev-browser/`, `jev-window-core/`, four tarballs | `browse/` package + hosted TypeSafe JEV | none (never tracked) | C, G | None to platform; hygiene risk |
| L9 | SonarQube report items | none (report never acted on) | none | F for 2 items, rest G | Low |
| L10 | Old docs and banners | `docs/architecture/native-execution.md` etc. | various | G | None |
| L11 | Legacy AgentAI `agent/` | OpenClaw runtime then customer platform | `8298602` | G | None |
| L12 | Old phase plans / three "phase" numbering schemes | `plans/product/*`, `phase-prompts/openclaw/phase-01..19` | `e59532e` | G, C | None |
| L13 | Superseded branches, tags, worktrees | `product-phases-6-11` line | n/a | A after check | Low |

## L1. ServiceRouter and JEV service choice

- What it was: per-message JEV service choice (`routing/services.py`, 160 lines, class `ServiceRouter`) plus `test_services.py` (134 lines) and `test_service_handoff.py` (238 lines). Captured as deployed by tags `release/live3` (7dcc3fe) and `release/live4` (d67d15e); tuned in 65b15c7 (GH-003, FEAT-GH-06, FEAT-AG-24).
- Superseded by: browser access as a native tool (`lumina_browser`) and JEV limited to shadow routing (`routing/shadow.py`), display chooser (`routing/display.py`), classifier, policy. No per-request model router exists; one model per cell (`cell_config.py:18`).
- Removed in `5db9636`, a commit titled "Dark look is the default again; parchment..." whose message does not mention it. Lead verified no `ServiceRouter` in code and `routing/services.py` absent (M-11).
- Still referenced by (docs/config only): `CLAUDE.local.md` (lists `ServiceRouter.choose` as a blind spot and names `test_service_handoff.py`), `docs/orchestration-audit/04-current-orchestration.md`, `06-history-and-legacy.md`, `08-inconsistencies.md`, `docs/architecture/findings.md` (F-13), `agent-execution.md` (GH-003, AG-016).
- Risk of touching: code none. If prod still runs live3/live4-era code, prod and repo differ (UNVERIFIED).
- Recommendation: C (confirm retirement was intended; GH open question 1), then G: update the docs and `CLAUDE.local.md`; keep tags. Deleted tests (GH-015) leave no replacement; consider a regression test only if a router returns.
- Class: C, G.

## L2. Host Docker `runner.mjs` versus native browser

- Current status: `browse/runner.mjs` (345 lines, Playwright in a Docker stage via `stage_argv`, `service.py:647`) is the DEFAULT engine (`service_main.py:92-101`; `OPERATIONS.md` "Browser engine"). `native_runner.py` (435 lines) + `native_scripts.py` (182 lines) is the cell's own OpenClaw browser through bridge `browser.*`; rollout-gated per account by `/etc/agentai-supervisor/browse-engine.json` (default `runner`), example `platform/deploy/browse-engine.example.json`. A third layer is uncommitted tool-origin v2 (IN-PROGRESS).
- Plan: `docs/architecture/native-browser-plan.md:7,131` says remove `runner.mjs`, host stage and `stage_argv` after an eval gate. Only `browse/llm.py` was deleted so far (d95b796). `browser-opt/` and `research-opt/` adapters remain.
- Still referenced by: `service.py:647/654`, `service_main.py`, `browse/test/*.mjs`, `agentai-browse.service`, a hand-copied `/opt/agentai-browse/runner/runner.mjs` on the VPS (five `.bak-live*` copies, IS-006), `native_runner.py` module docstring wrongly calls it "retired" (AG-016).
- Evidence on prod: UNVERIFIED. Repo evidence only: an OOM canary on 27 Oct reverted an account to the runner (`evidence/deployments/20261027T114539Z-cancel-e700e33/deployment.json`).
- Risk of touching: HIGH (customer-facing browser feature; security logic duplicated across engines, AG-010).
- Recommendation: C (cutover decision and owner of the eval gate), E (architecture), do not delete before the gate and the VPS engine-file check. Fix the "retired" docstring (G).
- Class: C, E, G.

## L3. Generative UI: three generations

- v0: `src/lib/genui/*` + `src/components/genui/*` (form, task_plan, table, chart, comparison; commits ac3cd9a, 3686b5a, 3b2fdbb).
- v1: `src/gen/*` (b1439f8, a6371bc); v1 lived about 3 hours.
- v2 registry + durable artifacts: `07fd6b9` ("Replace generative UI with discoverable registry and durable artifacts"), backend validation `a7bdfae`, deployed per `a2bb53b`. Server `genui/data.py` removed in 07fd6b9; migrations `0017`, `0020`, `0027`, `0029`, `0030` all remain (additive, correct).
- Adapter: `gen/legacy.tsx` (read-only) renders old table/chart/comparison cards; chain `BlockView` -> `Cards.tsx:4` -> `gen/legacy` -> `gen/Renderer` is LIVE for stored conversations. Do not delete (FE "looks bad but is fine" 3).
- Still live on the old path: `form` and `task_plan` (PlanBlock, plan editing/launch) with `/v1/blocks/<id>/*`.
- Docs follow the registry (`docs/generative-ui/*` rewritten in 07fd6b9).
- Risk of touching: Medium; customer data contains historical cards; backend `/v1/blocks/*` contract.
- Recommendation: C (target path), then B: migrate form + task_plan into `gen/`, keep only the legacy adapter (FE-004, GH-007, M-07).
- Class: C then B/E.

## L4. `lumina-character`: skin, film, parchment

- What: tracked full fork of `lumina` (4,697 tracked files, 61 MB `public/` incl. 31 scene mp4/jpg, one commit `d95b796`, tag `lumina-character-final` = `5db9636`). Holds the film background (`SceneBackground.tsx`, `lib/scene.ts`), parchment/obsidian look, ask/fields/question UI (`AskBox`, `ChatQuestion`, `FieldsBox`, `SavedInfo`, `QuestionPanel`, `SafetyPanel`, `useBrowseQuestion`, `useTaskEvents`). 88 `diff -rq` differences in `src/` (ST-002).
- Superseded by: `lumina/` as the live app (dark default `5db9636`; film moved out `d95b796`; new Safety console and `ui/Menu`).
- Referenced by: only `docs/architecture/findings.md` and `docs/orchestration-audit/06-history-and-legacy.md`; not by deploy, CI or `release.py` (FE-001, ST-002; GH-012 notes the deploy-script check was not exhaustive). Untracked symlink `lumina-character/node_modules -> ../lumina/node_modules` (GH-002).
- Caddy may still serve `/var/www/lumina-scenes` (commit `4bdf03c`); not verified whether deploy scripts still refresh it (GH-018).
- It is the only holder at HEAD of the question/vault/saved-info UI that `lumina` lost (FE-002) and of the film components (the tag preserves them too).
- Risk of touching: Medium. The dependency pins are untested because tsc ran against `lumina`'s node_modules (FE-001).
- Recommendation: C (promote, archive as branch/tag then remove directory, or merge needed pieces back), G preserve until decided; add `node_modules` (no slash) to the ignore file (F, tiny).
- Class: C, G (F for the ignore pattern).

## L5. `agentai-supervisor.service` versus `-native`

- Older custody-only supervisor ("native effects disabled"), superseded by `agentai-supervisor-native.service`. Both declare `RuntimeDirectory=agentai-supervisor`, so they cannot both run (IS-023, FEAT-IS-11).
- Referenced by: unit file only; `supervisor_main` module; no caller in monitor.
- Risk: Medium. If a host still runs the old unit, removing the file changes nothing, but the VPS state must be checked first (`systemctl is-enabled agentai-supervisor ...`).
- Recommendation: A after VPS check; otherwise C.
- Class: A (after verification), G.

## L6. Platform control server

- `agentai_platform/server.py` (`--service control|app --migrate`) with `agentai-platform-control.service`; kept "solely for private foundation/control fixtures" (ST-015). Port 18801 is claimed by both the control config (`config.server.example.json:5`) and the live frame gateway (`service_main.py:54`, Caddy `@liveframe`), IS-004. Not in `ops/monitor.py` REQUIRED_UNITS. `server-smoke.json` (30 Sep) showed 18801 listening for control.
- Replaced by: Django app + gunicorn (`agentai-platform-app.service`). Note `server.py` is still the entry for `--migrate` used in tests; `security.log_request` is used only by `server.py`.
- Referenced by: unit file, `config.py:29` check, tests, `Store.initialize()` consumers (~10 test modules).
- Risk: Low-Medium. Removing the module would break `--migrate` callers.
- Recommendation: first verify on the VPS (`systemctl is-enabled agentai-platform-control`); if disabled, classify unit and entry as LEGACY (C product decision), move the port in config to remove the clash (D).
- Class: C, D, then A for the unit file.

## L7. `platform/ui-reference/`

- 94-line plain-JS client (sign-in, chat, clear, sign-out) referenced only by `platform/UI_CONTRACT.md:10`. Not built, not served, not tested (FE-018, FEAT-FE-19). Duplicates `api()`; will drift if CSRF or error shape changes.
- Replaced by: `lumina/` SPA.
- Risk: none for runtime.
- Recommendation: C (keep as documentation of the API contract, or remove after verification). UI_CONTRACT says "about 120 lines" (actual 94; FE-017).
- Class: C, G.

## L8. `jev-browser/`, `jev-window-core/`, tarball versions

- `jev-browser/` (24 MB, UNTRACKED): bare-loop prototype (goal, screenshot, TypeSafe JEV picks action, repeat), ~2.2 kLOC Python + Node CDP runner. `jev-window-core/` (268 KB, UNTRACKED): extraction driving a macOS window (Swift `Window.swift`, 295 LOC). Neither is imported by `platform/`, `lumina/`, `browse/` or `bin/` (OP-004, ST-005). Production JEV is the hosted TypeSafe model called from `browse/`, `routing/`, `browser-opt/`, `optimization.py:20` (`jev-1.13.0`), `service_main.py:19` (`jev-1.14.0`).
- Tarball versions (listing only, OP-005): `pre-remodel` (Oct 19 16:23, 110 KB, server-based app with `engine/` package: trace, goals, untrusted, session, loop, candidates, ladder), `v2-complex` (17:15, 71 KB, planner/budget/policy-heavy flat modules), `v3-before-reset` (17:32, 192 KB, same plus run data), `v4-with-playwright` (18:50, 29 KB, reduced to jev/log/browser/dashboard/loop/goal plus `runner/_probe.mjs`). Current dir (20:15) = v4 minus `_probe.mjs`. Naming overlap between the `pre-remodel` `engine/*` files and platform `browse/{goals,session,trace,untrusted,ladder,candidates,loop}.py` suggests lineage (observation only, derivation not proven).
- Also three JEV prototypes in three places: `jev-browser/`, `jev-window-core/`, `openclaw-project/experiments/jev-full-page/` (OP-017).
- State inside the dirs: `jev-browser/.venv` 13 MB, `logs` 10 MB (26 jsonl with live-browsing page data), `.env` files (ignored by their own `.gitignore`, OP-006, OP-018), compiled `.build/jev-window`.
- Risk: none to the platform; hygiene risk is accidental `git add -A` (not ignored at root; M-03/ST-004/OP-002).
- Recommendation: C (move outside the repo, add ignore rules, or commit under `experiments/` or `archive/`), G keep as design history. Class A (delete `.venv`, logs, build products) only after owner confirms (OP-018).
- Class: C, G (A for build state, later).

## L9. SonarQube report items

- Report: `SONARQUBE-REPORT.md` (50 KB), `SONARQUBE-FIX-PROMPT.md`, `sonarqube-export/` (3.4 MB), all UNTRACKED, scan dated 2026-10-13 (32,074 lines, gate OK; 28 vulnerabilities, 52 bugs, 709 smells). Never committed or re-run; no commit references it (OP-010, OP-011).
- 14 spot-checked items are all still present (line numbers drifted): CSRF-exempt `accounts/billing.py` webhook, `accounts/streams.py` stream, `accounts/telegram.py` webhook, one in `accounts/files.py:172`; `dev_local_ui.py:78-80` CERT_NONE and `:20` dev password; `accounts/views.py:281` f-string `SELECT 1 FROM {table}` (reviewed by backend: table names from fixed constants); `switches.py:207` chmod 0o644; `browse/service.py:519` chmod 0o777; `browse/runner.mjs:12` `/tmp/out`; `bin/phase6/manage-connectors.py:115` predictable `/tmp` staging name; `lifecycle/cell_config.py:17` http literal in a comment.
- Triage (OP-012): the CSRF-exempt endpoints are by design (signature/token; webhook authentication not independently re-verified in OP scope; BE reports Stripe signature + `hmac.compare_digest` telegram secret). Only two have a plausible privacy angle: `0o777` on the browse out dir (world-writable dir shared with a container) and the predictable `/tmp` staging path. Everything else is noise or dev-only.
- Recommendation: F for those two (privacy first, per the owner's priority), G for the rest; decide whether to wire a periodic Sonar run (OP open question 7). Do not run `SONARQUBE-FIX-PROMPT.md` blindly: ~80% of its list is by-design.
- Class: F (2 items), G, C (tooling).

## L10. Old docs and banners

| doc | state | what is stale | reference |
|---|---|---|---|
| `docs/orchestration-audit/` (9 files) | bannered Historical (pre 26 Oct native migration) | still diagrams ToolDecider/Pursuit; says "all 122 commits" (HEAD has 132); ServiceRouter items | AG-016(6), GH-017 |
| `docs/architecture/` (most) | Historical banner; `native-execution.md` is current | F-17 says "reverted Lumina app", since changed | FE-017, AG |
| `docs/browser-reliability.md` | modified (uncommitted) | trust-boundary section still describes the superseded transcript/SQLite reader | AG-006, AG-016(4) |
| `README.md` (openclaw-project) | stale | "Product Phases 1-2 deliver...", "next phase 4" | ST-014 |
| `RUNBOOK.md:1-35`, `ARCHITECTURE.md:1-45` | stale headers | "no persistent platform listener installed", "next build phase4" | ST-014 |
| `BUILD_LOG.md` | last entry 2026-10-12 | work continued to 10-27 | ST-016 |
| `RELEASE_NOTES.md` | out of order | "Latest: live8" below newer sections; "Running release" stale; GitHub-suspended note 14 Oct unclear | IS-015(e), IS-017 |
| `SERVER_DEPLOYMENT.md` | stale | "Gate 1 still awaits owner access checks"; targets IONOS 69.48.206.62 (17 tracked files name it) vs owner's `lumina` host | IS-015(d), L-01 |
| `plans/phase-4..10.md`, `plans/remaining-build-items.md` | LEGACY (Sep, pre-product) | owner-runtime numbering | ST-021 |
| `plans/product/privacy.md` | drift | "only host door" (now 4000 and 4100); "server login key-only" vs password SSH | IS-015(a), IS-002 |
| `deploy/README.md` | drift | says LiteLLM has no published host port (published on 127.0.0.1:4000) | IS-015(b) |
| `agentai_platform/vault.py` header; `accounts/chat.py` docstring | drift | "root-only key file"; "execution disabled until host connects gateway" | BE-023 |
| `product/plan.json` `status`, `CONTRACT.md:3` | wording stale | "not a live offer" vs launch1 deployed | OP-008(14) |
| root `README.md` | last modified Oct 5, not reviewed in depth | LOW confidence | OP-016 |
| `CLAUDE.local.md` | ServiceRouter and `test_service_handoff.py` stale; says `evidence/` not indexed but 183 files are tracked | | M-11, IS-018 |

- Recommendation: G. Keep banners; add the correct banner to `docs/browser-reliability.md` and the README/RUNBOOK headers. Risk none.

## L11. Legacy AgentAI (`agent/`)

- Created 4cb60d0, 5e6f3fa (23-27 Sep); deleted wholesale in `8298602` ("retire legacy AgentAI"): 100+ files under `agent/`, `BUILD_NOTES.md`, `agent-build-spec-multiuser.md`. Recoverable via `git show 8298602^:agent/...`. Concepts (vault, purchases, approvals) reappear in `ops` and the phase 19 prompt (FEAT-GH-01).
- Class: G. Risk none.

## L12. Old phase plans and numbering

- Four meanings of "Phase N" (GH-008): old owner-runtime `plans/phase-4..10.md` + `evidence/phase-4..10`; product `phase-prompts/openclaw/phase-01..19` (rewritten in `e59532e`, which deleted the 13 old `phase-0..12` prompts); commit subjects ("Phase 8B", "Phase 4A", "phase 14"); Lumina app phases 1-3 (ed0dc7c) and "Lumina phase 4" (2725903). Evidence for historical phases is cited by acceptance manifests; moving it would break provenance (ST "looks bad but is fine" 4).
- Config/fixtures only referenced by evidence and CI-listed asset tests: `config/phase*.batch.json`, `phase4/10/11-fixtures`, `platform/deploy/p4_*_check.py`, `p15_acceptance.py` (ST-009). `bin/phase4/build-sdk-image.sh` and `bin/phase6/prepare-server.py` have zero references (UNKNOWN, may be run by hand).
- Recommendation: C (adopt a prefix in a README, e.g. owner-p4 versus product-p4), G; optional move to `archive/` after maintainer confirmation (A).
- Class: G, C, A.

## L13. Branches, tags, worktrees

- `main` local at 3c6ed08 (4 Oct) is a pure ancestor, 107 behind; `origin/main` holds only the PR #1 merge (12 Oct); `origin/product-phases-6-11` is 47 commits behind (GH-013). 14 linked worktrees under `.claude/worktrees/` (573 MB, untracked); 13 hold no unique commit; `worktree-product-images` has b956e68 whose payload was re-landed in d95b796 with migration renumbered 0023 -> `0025_card_images.sql`. Do not merge that branch (would collide with `0023_saved_choices.sql`) (GH-006, GH-014, OP-013).
- Recommendation: A for branch/worktree pruning only after checking each worktree for uncommitted files (not checked); C for the main/Vercel question (is `origin/main` what Vercel/CI deploys from?).
- Class: A (after check), C.

## Cross-cutting notes

- Provenance: `d95b796` bundles 4,929 files into one commit (native browser, safety menu, character split, `chat.py` rewrite), so blame/rollback granularity is lost (GH-001). Release tags stop at `live8`; native1-4 and safety1 have no tag (GH-005).
- Nothing in this file has been confirmed against the VPS. Re-run the IS checklist (sections A-I of `infra_security.md`) before removing any unit, config, or directory.
