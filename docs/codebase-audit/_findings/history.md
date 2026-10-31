# Findings: Git history and legacy reconstruction (scope GH)

## Scope & method

Covered: all 132 commits on `product-phases-6-11` (HEAD 03662de), 16 local branches, 9 `origin/*` refs, 14 linked worktrees, 12 tags, path histories for replaced features, and a pattern-only secret scan of history.
Commands used (read-only): `git log --format --reverse`, `git log --diff-filter=A|D --name-status`, `git show --stat`, `git branch -a -vv`, `git tag -l`, `git worktree list`, `git rev-list --left-right --count`, `git grep`, `git log -p -G<pattern>` piped through a script that prints only commit, file and variable NAME.
An earlier audit exists at `docs/orchestration-audit/06-history-and-legacy.md` (written at 122 commits); this file re-verifies against 132 commits and adds branch, tag, secret and working-tree items.
NOT checked: production/VPS state (unverified everywhere below); contents of untracked top-level folders (`jev-browser/`, `jev-window-core/`, tarballs) beyond existence; stash list; reflog; whether the deployed server matches any tag.
Uncommitted in-progress work (tool_origin, tool_relay, cell_bridge, cell_config, e2e harness, `tool_origin_plugin/`, `experiments/`, `docs/browser-tool-ownership.md`) is noted, not judged.

Caveat on a project instruction: `CLAUDE.local.md` says `ServiceRouter.choose` exists. It does not exist at HEAD (see GH-003).

## Timeline (eras)

| Era | Dates | Commits | What happened |
|---|---|---|---|
| E1 Legacy AgentAI | 23-27 Sep | 4cb60d0, 5e6f3fa | `agent/` multi-user system (orchestrator, vault, purchases, Telegram gateway, Jinja web app, 40+ tests). Fully deleted in 8298602 ("retire legacy AgentAI"): 100+ files under `agent/`, `BUILD_NOTES.md`, `agent-build-spec-multiuser.md`. |
| E2 OpenClaw owner runtime | 27-28 Sep | 63da739, 8298602, 2aaadf2, b7dee28, f4ee27f, f853609, a31997e | OpenClaw deployment, phase plans/evidence, memory, Phase 7-9 builds, Phase 4A Jev preflight, owner dashboard v2/v3 (`dashboard/`). `phase-prompts/openclaw/phase-0..12-*.md` created. |
| E3 Customer platform foundation | 30 Sep - 4 Oct | e59532e .. 3c6ed08 (15 commits) | Stdlib platform + serial queue, getlumina.pro HTTPS, Gmail invites, activation, CLI handoff, supervisor custody, Fleet driver, disposable-cell verification. e59532e deleted the 13 old `phase-0..12` prompts (renumbered later to `phase-01..19`). `main` stops here (3c6ed08, 4 Oct). |
| E4 Product phases | 9-12 Oct | 3cefc3c .. 0cb58b6 | One giant commit builds product phases 6-11 (3cefc3c), phase 12 adapters (disabled), new 15 GiB server, phase 4 cell lifecycle, phase 13 billing, free-access mode, phase 14 ops, customer execution path, live chat on prod (0cb58b6). |
| E5 Lumina web app | 12-13 Oct | 5339ca8 (JEV router) .. 4d62e7b | JEV routing shadow, `/app` shell, Lumina app phases 1-3, generative UI v0 (forms/plans, ac3cd9a), chatbot-style chat, plan runner, web search, Browser agent core (dae8ad9) and browse service (2efca1f), Activity window, files, privacy hardening. |
| E6 Hardening + launch features | 13-14 Oct | 055032d .. 90c5277 | Browser hardening, acceptance harness (febecb9), self-service signup, owner console/dashboard redesign, Live view (3e32beb), orbs, OpenMoji (4,495 SVGs), release branch + tags live1-live6. Merges: 35117f8, 358a555, 88bdc26. |
| E7 JEV-first browse ladder | 15-19 Oct | d59e59d .. f6ce2e3 | Browse ladder: one JEV call per step, Claude hand-off, traces, picture mode (JEV 1.14). Tags live7, live8, ui-pre-film (825ecee). Also 2725903 task control center, 65b15c7 service-choice tuning. |
| E8 Character film + parchment | 23-25 Oct | 46554f1, 033127f, 5b9f28e, 5596eda, 4bdf03c, 5db9636 | Chat background film synced to assistant state; parchment look (tag ui-parchment-v1); dark restored as default (tag lumina-character-final, 5db9636). 5db9636 also silently deleted `routing/services.py` (GH-003). |
| E9 Consolidation mega-commit | 27 Oct | d95b796 ("Remaining pending work"), 4929 files | Moves the film UI to `lumina-character/`, reverts `lumina/` to non-film app plus Safety menu and `ui/Menu`, adds native browser (`browse/adapter.py`, `native_runner.py`), 7 docs under `docs/architecture/`, 9 under `docs/orchestration-audit/`, rewrites `chat.py`/`gateway.py`/`cell_bridge.py`, RELEASE_NOTES (native1-4, safety1). |
| E10 Gen UI v1 -> registry | 27 Oct | b1439f8, a6371bc, a7bdfae, 07fd6b9, 10efb73, a2bb53b | Generative UI built, then replaced within hours by registry + durable artifacts. |
| E11 Reliability / ops | 27-28 Oct | e700e33, 2612e41, 42cb3fd, ef2a8ac, 03662de | Container reconcile, browser OOM recovery, $5->$15 daily limit, Tools menu popover. HEAD. |

Observation: 107 of 132 commits are dated 12-27 Oct. d95b796 alone changes 4929 files / +133k lines (mostly 4,495 OpenMoji SVGs in `lumina-character/`), so `git blame` for the native browser, safety menu and chat rewrite points to one commit (GH-001).

## Branches, tags, worktrees

Ahead/behind below is against `product-phases-6-11` (P) as `behind/ahead` of that branch, and against local `main` (M).

| Ref | HEAD | vs P (P-only / ref-only) | vs M | Unique work worth keeping |
|---|---|---|---|---|
| main (local) | 3c6ed08 (4 Oct) | 107 / 0 | 0/0 | None. Pure ancestor of P. Stale by 107 commits. |
| origin/main | 515fdde | 87 / 1 | main behind 21 | Only the PR #1 merge commit (merge of P as of 9d11041, 12 Oct). No content P lacks. Production deploy tooling may still assume main (UNVERIFIED). |
| origin/product-phases-6-11 | 3b2fdbb (13 Oct) | 47 / 0 | | P is 47 commits unpushed. Remote backup of work is 2 weeks old. |
| worktree-botcheck | 84d7ec6 | 38 / 0 | | None (ancestor of P). Tagged release/live5-browse. |
| worktree-emoji-jev | 7dcc3fe | 45 / 0 | | None. origin copy 9ff48d7 also ancestor. Tag release/live3. |
| worktree-fastclick | f8658ee | 35 / 0 | | None. Tag release/live6. |
| worktree-jev-tune | 1ba204a | 43 / 0 | | None. |
| worktree-live-view | 3e32beb | 59 / 0 | | None (merged via 88bdc26). origin copy identical. |
| worktree-lumina-layout-stability | 92fa542 | 63 / 0 | | None (merged via 35117f8). |
| worktree-notes | e4cf975 | 41 / 0 | | None. |
| worktree-notes2 | b2115cb | 33 / 0 | | None. |
| worktree-openmoji | 323027a | 52 / 0 | | None. |
| worktree-orbs | 80ecd02 | 54 / 0 | | None. |
| worktree-product-images | b956e68 (20 Oct) | 18 / 1 | | One unique commit b956e68 "Comparison cards: server-fetched, same-origin product pictures" (16 files, +1033). Content was re-landed in d95b796 (`genui/images.py`, `accounts/media.py`, `test_card_images.py`) with migration renumbered 0023 -> `0025_card_images.sql`. Branch copy is superseded; not an unmerged feature, but its commit message and OPERATIONS.md note are not on P. See GH-006. |
| worktree-release | 5d8664b | 49 / 0 | | None. Tag release/live1. |
| worktree-smooth-scroll | 394bbeb | 58 / 0 | | None (merged via 358a555). |
| worktree-thinking-branch | acfd9f8 | 40 / 0 | | None. Tag release/live5. |

Worktrees: 14 linked worktrees live under `/Users/parsa/AgentAI/.claude/worktrees/*` (inside the repo tree; `.claude/` is untracked). 13 of 14 hold no unique commit; all are stale and prunable after confirming no uncommitted files inside them (not checked: dirty state of each worktree).

Tags (all are ancestors of HEAD; all lightweight or annotated pointing at P-line commits):

| Tag | Commit | Captured |
|---|---|---|
| release/live1 | 5d8664b | Web app + browser service; Live view frames via `/v1/live/<task>/frame` |
| release/live2 | 3b2fdbb | Chat/Live polish, JSON cards (same commit as origin/product-phases-6-11) |
| release/live3 | 7dcc3fe | JEV service choice per web message |
| release/live4 | d67d15e | JEV service question tuning |
| release/live5 | acfd9f8 | Thinking label on orb branch (also faster Live view) |
| release/live5-browse | 84d7ec6 | Verification-wall message (browse-only release) |
| release/live6 | f8658ee | Fast takeover click, wall handover |
| release/live7 | f435324 | JEV-first browser agent, live mode |
| release/live8 | 02877e4 | JEV miss diagnostics, one retry on non-JSON |
| ui-pre-film | 825ecee | UI before the Lumina film (19 Oct) |
| ui-parchment-v1 | 5596eda | Parchment look (23 Oct) |
| lumina-character-final | 5db9636 | Last commit where `lumina/` itself contained the film/character UI, dark default |

No tags exist for releases `native1`..`native4` or `safety1` (named in RELEASE_NOTES.md lines 1 and 18) or for any release after live8. Those deploys are traceable only to d95b796 or later (GH-005).

## File/module map (history-relevant locations)

| path | responsibility | consumers/entry | notes |
|---|---|---|---|
| `openclaw-project/lumina/` | Active React frontend (Vite) | `deploy` scripts, Caddy | Tracked 4,701 files incl. 4,498 `public/` emoji SVGs. `node_modules` is installed locally and ignored. |
| `openclaw-project/lumina-character/` | Fork/snapshot of the frontend with film (`SceneBackground.tsx`, `scene.ts`, `public/scenes/*.mp4`), ask/fields/question UI, richcards, obsidian.css | Nothing in `platform/` references it (checked by `git grep`); has its own `package.json` | 4,697 tracked files; `node_modules` is an untracked symlink to `../lumina/node_modules` (GH-002). |
| `openclaw-project/lumina/src/gen/` | Generative UI registry (v2) | `Chat.tsx`, `ChatBridge.tsx`, tests | `legacy.tsx` is a read-only adapter for old table/chart/comparison cards. |
| `openclaw-project/lumina/src/lib/genui/`, `components/genui/` | Generative UI v0 (form/plan blocks, data cards) | Still imported (e.g. `BlockView.tsx`, `Cards.tsx`) | Coexists with `gen/` (GH-007). |
| `openclaw-project/platform/agentai_platform/genui/` | Server-side validation/storage for blocks and artifacts | accounts/genui.py | `gen_registry.json`, `document.py`, `artifacts.py` (new); `data.py` deleted in 07fd6b9. |
| `openclaw-project/platform/agentai_platform/browse/` | Host browse service: `ladder.py` (JEV-first decider), `loop.py`, `service.py` (Docker Chromium stage + `browse/runner.mjs`), plus newer `adapter.py`, `native_runner.py`, `native_scripts.py` | `service_main.py` | Two engines coexist: host-stage runner and native cell browser (GH-004). |
| `openclaw-project/browse/` | `runner.mjs` Playwright runner, fixtures, tests | run inside Docker stage by `service.py:654` | `docs/architecture/native-browser-plan.md:131` says remove it after the native gate. |
| `openclaw-project/browser-opt/`, `research-opt/`, `research/`, `experiments/jev-full-page/` | Phase 9/12 optimisation adapters, rubric, JEV experiments | Standalone; `experiments/` untracked | Old-numbering phase artifacts (GH-008). |
| `openclaw-project/plans/phase-*.md`, `evidence/phase-*`, `../phase-prompts/openclaw/` | Three phase numbering schemes | docs only | GH-008. |
| `openclaw-project/platform/migrations/0001..0030` | SQL migrations | `accounts` | No duplicate numbers on P; b956e68 branch uses 0023 for card images, which collides with P's `0023_saved_choices.sql`. |
| repo root `jev-browser/`, `jev-window-core/`, `jev-browser-*.tar.gz`, `lumina-cost-audit/`, `sonarqube-export/`, `brag-output/`, `product/marketing/`, screenshots, zips | Untracked scratch / archives | none | Backup tarballs of an earlier JEV browser (pre-remodel, v2-complex, v3-before-reset, v4-with-playwright). Not in git. |
| repo root `ssk-key`, `ssk-key.pub` | Untracked OpenSSH private/public key pair | none | GH-009. |
| `openclaw-project/lumina/src/vendor/thinking-orbs` | Vendored MIT lib (ff92478) | `Orb.tsx` | Also duplicated in `lumina-character/src/vendor`. |

## Features (historical versions, old -> current)

| ID | name | primary status | flags | frontend | backend | entry/flow evidence | prod verified? | notes |
|---|---|---|---|---|---|---|---|---|
| FEAT-GH-01 | Legacy AgentAI multi-user agent | LEGACY | deleted | Jinja `agent/gateway/templates` | `agent/core/*` | Deleted wholesale in 8298602; created 4cb60d0, 5e6f3fa | unknown | Not in tree; recover with `git show 8298602^:agent/...`. Concepts (vault, purchases, approvals) reappear in `ops`, phase 19 prompt. |
| FEAT-GH-02 | Owner dashboard | ACTIVE (owner-only) | | `dashboard/` | `platform/...` | b7dee28 v2 -> a31997e v3 -> 84a0e1c switches -> 07fd... d21e6b5 console -> 07dae45 redesign | unknown | Single Flask-style app, iterated 6 times. |
| FEAT-GH-03 | Generative UI v0 (forms/plans) -> v1 -> v2 registry | DUPLICATED | partially superseded | `lib/genui` + `components/genui` (v0, ac3cd9a, 3686b5a) -> `src/gen` (v1 b1439f8, a7bdfae) -> registry/artifacts (07fd6b9) | `genui/` ; `data.py` deleted 07fd6b9 | `gen/legacy.tsx` adapts old cards; v0 files still imported | unknown (a2bb53b says deployed) | Three generations alive. v1 lived about 3 hours (b1439f8 -> 07fd6b9). |
| FEAT-GH-04 | Browser agent: host Docker stage + `runner.mjs` + JEV ladder -> native cell browser | INCOMPLETE | DUPLICATED, in-progress uncommitted | `Live.tsx` | `browse/ladder.py`, `service.py`, `native_runner.py`, `adapter.py` | dae8ad9 core -> 2efca1f service -> 9dc1f9b/8d8fafe ladder -> 825ecee picture mode -> d95b796 native engine -> working tree `tool_origin*` | unknown | `docs/architecture/native-browser-plan.md` describes a gate then deletion of `runner.mjs`; not yet done. |
| FEAT-GH-05 | Browser page -> Live view | ACTIVE | | `Browser.tsx`+test deleted in 3e32beb; `Live.tsx`, `LiveScreen.tsx` | `live/gateway.py` | 17e88a4 -> 3e32beb -> 5d8664b frames via `/v1/live/<task>/frame` -> 90c5277 instant clicks | unknown | Old page fully replaced; `LiveScreen` and `Live` pages present at HEAD. |
| FEAT-GH-06 | JEV service choice (ServiceRouter-first) | ORPHANED | deleted code, stale docs | none | `routing/services.py` deleted | 7dcc3fe (live3) -> d67d15e -> 65b15c7; DELETED in 5db9636 with `test_services.py`, `test_service_handoff.py` | unknown (live3/4 tags captured it) | Routing now only has shadow, display, classifier, policy (`routing/` dir listing). GH-003. |
| FEAT-GH-07 | Chat background: plain -> film stage -> removed from `lumina` | LEGACY | moved | `SceneBackground.tsx`, `scene.ts` now only in `lumina-character/` | none | 46554f1 -> 033127f -> 5b9f28e -> 4bdf03c (Caddy `/var/www/lumina-scenes`) -> d95b796 move | unknown | Caddy/deploy may still serve scenes; frontend deploy no longer has them in `lumina/public`. |
| FEAT-GH-08 | Look: dark obsidian -> parchment -> dark default (parchment switchable) | ACTIVE | | `settings.tsx`, `tokens.css` | | 5596eda (tag ui-parchment-v1) -> 5db9636 (tag lumina-character-final); d95b796 deletes `obsidian.css`, adds `ui.css` | unknown | Parchment code path exists behind a setting in both frontends. |
| FEAT-GH-09 | Chat questions: AskBox / ChatQuestion / FieldsBox / SavedInfo / QuestionPanel | LEGACY | deleted from `lumina`, kept in `lumina-character` | | | Deleted in d95b796; `0023_saved_choices.sql` migration remains | unknown | Server-side saved-choices table has no frontend consumer in `lumina` (not verified in depth). |
| FEAT-GH-10 | Thinking indicator: TaskStrip card -> orbs | ACTIVE | | `AgentThinking.tsx`, `Orb.tsx` | | 1bc28ab removed `TaskStrip.tsx`; ff92478, 80ecd02, acfd9f8 | unknown | |
| FEAT-GH-11 | Comparison card product images | ACTIVE | superseded branch | `Cards.tsx` | `genui/images.py`, `0025_card_images.sql` | b956e68 (branch) -> d95b796 | unknown | See GH-006. |
| FEAT-GH-12 | Release/deploy marking | INCOMPLETE | | | `deploy/`, RELEASE_NOTES | tags live1-live8 then none | unknown | GH-005. |
| FEAT-GH-13 | Phase 12 optimisation adapters (browser-opt, research-opt) | EXPERIMENTAL | disabled | | `optimization.py` | 22db0e7 | unknown | |
| FEAT-GH-14 | Phase 13 billing | ACTIVE (test mode) | free-access mode | | `billing.py` | 476a8ce, 36c8609, 0eaaab3 | unknown | Payments off per 36c8609 message. |

## Findings

**ID**: GH-001 | **Category**: consistency rot / provenance | **Severity**: Medium | **Confidence**: HIGH | **Effort**: M
d95b796 "Remaining pending work in openclaw-project" (27 Oct) bundles 4929 files / +133,002 / -3,273: renames `lumina/public/scenes` and the film UI into `lumina-character/`, deletes ask/question/safety-panel components and `obsidian.css`, adds Safety menu, native browser engine, `chat.py` rewrite (873 lines changed), `gateway.py`, `cell_bridge.py`, 7 architecture docs, 9 orchestration-audit docs and RELEASE_NOTES for native1-4/safety1.
Evidence: `git show --stat d95b796`; `git show -M --name-status d95b796 -- lumina/src`. Impact: blame/bisect/rollback granularity is lost for the three largest recent subsystems; the commit message does not describe contents. Action: G preserve; record in a doc that d95b796 is the native-browser + safety + character-split commit, and tag it (see GH-005). Risk: none (docs).

**ID**: GH-002 | **Category**: repo hygiene | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
`node_modules` committed once as a symlink (90c5277 added `openclaw-project/lumina/node_modules`; removed by c0c7844). Cause: `.gitignore` entries are `node_modules/` (trailing slash), which matches directories only, not symlinks. The same trap is live now: `lumina-character/node_modules` is an untracked symlink to `../lumina/node_modules` (visible in `git status` as `??`), and `platform/node_modules` exists on disk too. A careless `git add -A` would commit it again.
Evidence: `ls -ld lumina-character/node_modules` shows `lrwxr-xr-x ... -> ../lumina/node_modules`; `.gitignore` line `node_modules/`; `git log --diff-filter=A -- '*node_modules*'`. Action: F; change ignore to `node_modules` (no slash) in root `.gitignore`. Risk: low.

**ID**: GH-003 | **Category**: silent removal / doc drift | **Severity**: High | **Confidence**: HIGH | **Effort**: M
`routing/services.py` (JEV service choice, 160 lines, `ServiceRouter`) and its two test files (`test_services.py` 134 lines, `test_service_handoff.py` 238 lines) were deleted in 5db9636, a commit titled "Dark look is the default again; parchment..." whose message does not mention it. No importer remains (`git grep -n "routing.services\|ServiceRouter" -- platform` returns only docs). Tags release/live3, live4 capture the feature as deployed. Docs still describe it: `docs/orchestration-audit/04-current-orchestration.md`, `06-history-and-legacy.md`, `08-inconsistencies.md`, `docs/architecture/findings.md`, `agent-execution.md`; and `/Users/parsa/AgentAI/CLAUDE.local.md` ("ServiceRouter.choose shows 0 callers", "test_service_handoff.py") is stale. Possibly intentional (browser now a native tool, JEV only shadow/display) but the intent is undocumented in the commit.
Evidence: `git show --stat 5db9636` (3 deletions); `ls platform/agentai_platform/routing`. Runtime impact: if prod still runs live3/4-era code, prod and repo differ (UNVERIFIED). Action: C product decision (confirm retirement) then update docs; G keep tags. Risk: low.

**ID**: GH-004 | **Category**: partially completed refactor | **Severity**: High | **Confidence**: MEDIUM | **Effort**: L
Three browser execution designs coexist: (1) host Docker Chromium stage driven by `browse/runner.mjs` through `browse/service.py:654` with `ladder.py`/`loop.py`; (2) native cell browser (`native_runner.py`, `native_scripts.py`, `adapter.py`, d95b796); (3) uncommitted tool-origin/tool-relay work (working tree). `docs/architecture/native-browser-plan.md:7,131` plans to delete `runner.mjs`, the host stage and `stage_argv` after an eval gate. Deleted so far: `browse/llm.py` (d95b796). Not removed: runner, stage argv, `browser-opt/`, `research-opt/` adapters. Action: C product decision on cutover; E architecture; do not delete before gate. Risk: high (browser feature is customer-facing; prod state UNVERIFIED).

**ID**: GH-005 | **Category**: release traceability | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
Tags stop at release/live8 (15 Oct, 02877e4). RELEASE_NOTES.md documents later deployments `native1`..`native4` (26-27 Oct) and `safety1` (27 Oct) and "native execution ... not yet deployed", but no tag or commit hash is recorded for them. release/live5 (acfd9f8) and release/live5-browse (84d7ec6) are parallel releases that both lie on the P line. Action: G; tag deployed commits going forward, and add hashes to RELEASE_NOTES. Risk: none.

**ID**: GH-006 | **Category**: branch hygiene | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
`worktree-product-images` (b956e68) is the only local branch with a commit not in P. Its payload was re-landed in d95b796 with the migration renumbered (0023 -> `0025_card_images.sql`). Remaining differences: the OPERATIONS.md paragraph (+10 lines) and commit message. Merging the branch as-is would re-introduce `0023_card_images.sql` and collide with `0023_saved_choices.sql`. Action: A after confirming OPERATIONS.md text is present on P; do not merge. Risk: low.

**ID**: GH-007 | **Category**: duplication | **Severity**: Medium | **Confidence**: HIGH | **Effort**: L
Generative UI exists in three generations at HEAD: v0 `src/lib/genui/*` + `src/components/genui/*` (ac3cd9a, 3686b5a, 3b2fdbb), v1/v2 `src/gen/*` (b1439f8, 07fd6b9) and the read-only adapter `gen/legacy.tsx`. Server: `genui/schema.py`, `genui/document.py`, `genui/artifacts.py`, `gen_registry.json`; `genui/data.py` removed in 07fd6b9 while migrations `0017_generative_ui`, `0020_data_blocks`, `0027_more_cards`, `0029_document_blocks`, `0030_gen_artifact_events` all remain (schema is additive, which is correct for existing rows). `docs/generative-ui/*` was rewritten in 07fd6b9 so the docs follow the registry. Action: B consolidate after confirming no stored v0 cards are being created; C product decision. Risk: medium (historical cards in customer data).

**ID**: GH-008 | **Category**: naming collisions | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
"Phase N" has at least four meanings: (a) `plans/phase-4..10.md` and `evidence/phase-4..10` (old owner-runtime numbering, Sep); (b) `phase-prompts/openclaw/phase-01..19-*.md` (product numbering, rewritten in e59532e after old `phase-0..12` prompts were deleted; there both "phase-06" and old "phase-6" exist); (c) commit subjects "Phase 8B", "Phase 4A", "phase 14" (ops), "product phase 4"; (d) Lumina app "phases 1-3" (ed0dc7c) and "Lumina phase 4" (2725903). `evidence/phase-4` (old: Fleet/cell?) and "product phase 4" (85c83a4: isolated cell lifecycle) refer to different work. Also three directories hold phase evidence: `evidence/`, `plans/`, `docs/`. Action: C; adopt a prefix (e.g. `owner-p4`, `product-p4`) in a README. Risk: none.

**ID**: GH-009 | **Category**: security hygiene | **Severity**: High | **Confidence**: HIGH | **Effort**: S
Untracked OpenSSH private key file `ssk-key` (and `ssk-key.pub`) sits at the git root (`git status` shows `?? ssk-key`). Root `.gitignore` ignores `*.pem` and `*.key` but not this name. It has never been committed (`git log --all -- ssk-key ssk-key.pub` is empty). Risk: one `git add .` pushes a private key to GitHub (origin is on GitHub, PR #1 exists). Action: F; add `ssk-key*` to .gitignore or move the file outside the repo; confirm the key is not the production VPS key (not checked). Value not printed.

**ID**: GH-010 | **Category**: secrets in history | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
Pattern scan across all refs (`-G` on key-like prefixes: `sk-`, `AKIA`, `BEGIN ... PRIVATE KEY`, `xox[bp]-`, `ghp_`, `BSA...`, `AIza...`, excluding SVG and lockfiles) returned no added lines. A second scan for `password|secret|api_key|token` assigned a 12+ char quoted literal (excluding tests, fixtures, and obvious placeholders) also returned none. Tracked env-like files are only `*.env.example` (`deploy/litellm.env.example`, `deploy/postgres.env.example`, `platform/deploy/accounts.env.example`). Limits: base64/hex secrets without known prefix, and binary files, are not covered; tests and fixtures were excluded from scan 2. Action: G; consider running gitleaks locally (not installed here). Risk: none.

**ID**: GH-011 | **Category**: repo size / hygiene | **Severity**: Medium | **Confidence**: HIGH | **Effort**: M
`.git` is 351 MB with a 5 MB pack, i.e. mostly loose objects; the working tree tracks 4,498 emoji SVGs under `lumina/public` and 4,495 in `lumina-character/public`-related paths, plus 31 `.mp4/.jpg` scene assets in `lumina-character/public/scenes`, and `lumina-character/src/lib/openmoji/*.json` indices. `CLAUDE.local.md` says `lumina/public` emoji are not indexed, consistent. Action: A/E; `git gc`, consider git-lfs or fetch-at-build for emoji and film assets; not urgent. Risk: low (history rewrite not required for `git gc`).

**ID**: GH-012 | **Category**: duplication / legacy | **Severity**: Medium | **Confidence**: HIGH | **Effort**: M
`lumina-character/` is a full second copy of the frontend (134 src files incl. vendor, 38 tests, own package.json/lockfile, `.impeccable` design review PNGs, `dev-mock.mjs`). It is the only holder of the film UI and the ask/fields/question components. Nothing under `platform/` or `deploy/` references it (a `git grep lumina-character` over platform/ and deploy/ was not run exhaustively; only docs were seen mentioning it; deploy scripts not verified). The tag lumina-character-final (5db9636) preserves the same code with `lumina/` as the path. Action: C product decision: keep as an archive branch/tag and delete the directory, or make it the real home of the film feature; G preserve either way. Risk: medium (only copy of film components at HEAD, though tag keeps them).

**ID**: GH-013 | **Category**: remote hygiene | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
Remote state lags: `origin/product-phases-6-11` is at 3b2fdbb (13 Oct), 47 local commits unpushed; `origin/main` holds only a PR #1 merge of P at 9d11041 (12 Oct) and local `main` is 21 commits behind it (3c6ed08, 4 Oct). `main` is therefore both the documented PR base and the stalest ref. Release tags (all local-only? remote tags not checked). Action: C; decide whether `main` should be fast-forwarded to P; push. Risk: low.

**ID**: GH-014 | **Category**: worktree hygiene | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
14 linked worktrees in `.claude/worktrees/` (untracked inside the repo). 13 branches are fully merged ancestors of P; 4 have a remote copy that is identical or older. They duplicate working copies of the whole project (including node_modules where installed). Action: A (`git worktree remove` / `git branch -d`) only after checking each for uncommitted files; none checked. Risk: low.

**ID**: GH-015 | **Category**: test gap from history | **Severity**: Medium | **Confidence**: MEDIUM | **Effort**: M
Deleted tests with no replacement found: `lumina/src/state/settings.test.tsx` (deleted d95b796 although settings.tsx is edited in 5db9636 to add parchment/dark persistence), `Browser.test.tsx` (replaced by `Live.test.tsx`, fine), `test_services.py`/`test_service_handoff.py` (feature removed, GH-003), `Home.test.tsx` (deleted d95b796; kept only in `lumina-character`), `richcards.test.tsx`, `SafetyPanel.test.tsx` (replaced by `safety/Safety.test.tsx`). Action: C/D; restore a settings test (theme default). Risk: low.

**ID**: GH-016 | **Category**: migration numbering | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
SQL migrations 0001-0030 are contiguous with no duplicate prefixes on P. Branch worktree-product-images used 0023 (collision with `0023_saved_choices.sql`, see GH-006). Django `accounts/migrations/` also exists (e.g. `0013_signup_token.py`) alongside `platform/migrations/*.sql`, two migration systems with independent numbering. Action: C; document which owns which tables. Risk: low.

**ID**: GH-017 | **Category**: doc drift | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
`docs/orchestration-audit/06-history-and-legacy.md` states "all 122 commits"; HEAD has 132. Its P36 "ServiceRouter-first" item is marked as deleted legacy (consistent with GH-003) but `CLAUDE.local.md` still lists ServiceRouter and `test_service_handoff.py` as live blind spots. Action: update docs. Risk: none.

**ID**: GH-018 | **Category**: orphan assets | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
Caddy serves the film from `/var/www/lumina-scenes` (4bdf03c: "the frontend deploy refreshes that folder"), but `lumina/public/scenes` was removed in d95b796; whether deploy script and Caddyfile still reference the folder was not exhaustively checked here. Action: D verify `deploy/` scripts and `platform/deploy/caddy/Caddyfile.getlumina` for `lumina-scenes`. Risk: low.

## Looks bad but is fine

1. 14 `worktree-*` branches look like unmerged feature work, but 13 are strict ancestors of P (0 unique commits); merges 35117f8, 358a555, 88bdc26 plus fast-forward history absorbed them. Only `worktree-product-images` has an extra commit and it was re-landed.
2. `main` being 107 commits behind looks like divergence, but it is a pure ancestor: nothing on `main` is missing from P (`rev-list --left-right` shows 0 on the main side).
3. `agent/` legacy deletion (8298602) with 100+ files looks like data loss; it is intentional ("retire legacy AgentAI") and fully recoverable from 4cb60d0..63da739.
4. Deleted `phase-prompts/openclaw/phase-0..12-*` in e59532e looks like lost plans; the replacement `phase-01..19-*` set exists and is current, the old ones are in history only.
5. d95b796 deleting `lumina/public/scenes/*.mp4` is a rename (R100) to `lumina-character/`, not loss; and the tags keep the earlier layout.
6. Duplicate-looking tags live5 and live5-browse are different commits (acfd9f8 frontend, 84d7ec6 browse service) and were separate deploys.
7. No deleted-then-resurrected files were found (checked all A/D sequences outside emoji assets).

## Cross-scope links

- `lumina-character/` and `lumina/` duplicate frontend: affects frontend scope audits (do not count both).
- `routing/services.py` removal (GH-003): backend routing scope and chat_driver scope should confirm no runtime caller, and the docs scope should fix stale docs.
- `browse/runner.mjs` and `platform/.../browse/service.py:654` host stage vs native engine (GH-004): browser scope and deploy scope (systemd `agentai-browse.service`, OPERATIONS.md:173).
- Caddy `/var/www/lumina-scenes` (GH-018): deploy/Caddy scope.
- `0023_saved_choices.sql` has no `lumina` frontend consumer after d95b796 (FEAT-GH-09): API/frontend contract scope should check `accounts/` saved-choices endpoints.
- `ssk-key` (GH-009): security/infra scope to confirm which host it belongs to.

## Open questions for the maintainer

1. Was removal of `routing/services.py` in 5db9636 intentional, and is production still on a live3/live4-style router?
2. Should `lumina-character/` be the home of the film feature, or archived (the tag lumina-character-final already preserves it)?
3. Which commit was actually deployed as native1-native4 and safety1? Can they be tagged?
4. Is `ssk-key` a live server key? If so rotate/relocate it.
5. Is `origin/main` (PR #1 merge of 12 Oct) what Vercel/CI deploys from, given P has moved 87 commits since?
6. Is the host Docker browse stage to be retired after the native gate, and who owns the eval gate in `native-browser-plan.md`?
7. Are `phase-N` names meant to be reused for the product numbering, or should old `plans/phase-4..10` be renamed?
