# Cleanup plan (NOT executed)

> **Approved cleanup, 2026-10-29:** [CLEANUP_REVIEW.md](CLEANUP_REVIEW.md) records the owner decisions and completed A/B/C work; [CLEANUP_INVENTORY.json](CLEANUP_INVENTORY.json) preserves the original per-file proposal and execution ledger. Batch D is explicitly unchanged. The rebuilt [current architecture index](../../openclaw-project/docs/architecture/README.md) replaces the superseded main reports. These original plan tables remain a historical snapshot; use [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) for completed work and deployment status.

> **UPDATE 2026-10-29:** production was verified over SSH after this document was written. Statements below that production is "unverified" are superseded for the items in [PRODUCTION_VERIFICATION_2026-10-29.md](PRODUCTION_VERIFICATION_2026-10-29.md) (live host is Hostinger `179.236.71.203`; IONOS is dead; IS-002 and the tool-origin v2 drift confirmed; IS-004 resolved; M-01 latent, not observed).

Audit date 2026-10-29. Nothing in this plan has been run. It is dependency-aware and ordered; every item cites master IDs from `TECHNICAL_DEBT.md`. Production is UNVERIFIED, so anything that changes deployed behavior waits for Phase 2 (VPS checklist in `DEPLOYMENT_AUDIT.md`). The uncommitted tool_origin / tool_relay / cell_bridge / cell_config work is IN PROGRESS and is the owner's to finish; this plan only sequences it.

Owner priority: customer privacy first. This plan adds no new task limits (memory: privacy over task guardrails); fail-closed bookkeeping fixes (M-01, AG-007) are correctness repairs, not new guardrails.

Class legend: **A** safe cleanup, **B** consolidation/refactor, **C** product decision, **D** bug fix, **E** architecture change, **F** security/reliability fix, **G** preserve.

## Phase overview and sequence

| Phase | Theme | Gate to enter | Items |
|---|---|---|---|
| 0 | No-code hygiene | none | ignore rules, move key, commit in-progress work, tag releases, push decision |
| 1 | Security and reliability fixes | Phase 0 done; tests green locally | M-01, M-02 decision, M-04, BE-004, BE-005, AG-005, AG-007 |
| 2 | Verify production | owner unblocks access (DEPLOYMENT_AUDIT section 7) | VPS read-only checklist; resolve L-01; replace UNVERIFIED labels |
| 3 | Consolidation | Phase 2 results | CI coverage, docs, env example, dedupe wiring, dead-code, repo clutter |
| 4 | Architecture | product decisions | browser engine cutover, genui unification, lumina-character, single lane, migrations |

Dependencies that drive the order: Phase 0 commit of tool_origin work must precede any release tagging (GH-005) and any deploy; M-01 fix touches `chat_driver.py` (the only settler) so coordinate with Phase 1 AG-007; CI expansion (M-10) should precede Phase 3 refactors so changes are tested; browse consolidation (M-08) waits for the engine decision and Phase 2 knowledge of which engine runs.

## Phase 0: no-code hygiene (do first, minutes each)

| Item | Master IDs | Depends on | Expected benefit | Potential regressions | Validation | Order |
|---|---|---|---|---|---|---|
| Add `ssk-key*`, `*_key`, `id_*`, root-level `*.tar.gz`, `*.zip`, `.claude/`, screenshots patterns to root `.gitignore`; change `node_modules/` to `node_modules` | M-03, GH-002, OP-002, ST-004 | none | Removes the one-command key leak; clears `git status` noise | None | `git check-ignore -v ssk-key`; `git status` clean of `??` clutter | 0.1 |
| Move `ssk-key` out of the repo to `~/.ssh` (owner action); rotate only if ever shared | M-03, L-02 | owner confirms purpose | Key custody | Breaks any script using the repo-root path (none found) | `git ls-files` and `ls` | 0.2 |
| Relocate or ignore `lumina-cost-audit/` (owner browsing logs) | M-03 (OP-003) | 0.1 | Privacy | none | `git status` | 0.3 |
| Commit the in-progress tool_origin work (code + tests + `tool_origin_plugin/` + docs) after owner review | AG-006, AG-008, AG-019 | owner finishes | Source of truth equals what docs say is deployed; rollback possible | Commit of unfinished code | `unittest tests.test_tool_origin tests.test_browser_tool`; `node --test tool_origin_plugin.test.mjs` | 0.4 |
| Tag untagged releases: d95b796 (native browser + safety + character split) and the commit actually deployed as native1-4/safety1; record hashes in `RELEASE_NOTES.md` | GH-001, GH-005 | owner knows deploy commits (Phase 2 can confirm) | Traceability | none | `git tag -l`, notes updated | 0.5 |
| Decide pushing 47 unpushed commits and whether `main` should fast-forward to `product-phases-6-11` | GH-013, IS-017 | owner confirms remote status | Remote backup of work; fixes PR base | Triggers CI on a large set | `git rev-list --count origin/..` | 0.6 |
| Dry-run inventory of the 14 worktrees for uncommitted files and branches (read-only), then prune | M-03 (GH-014, OP-013), GH-006 | 0.1 | -573 MB, clears search noise | Lose unmerged work if skipped check | `git worktree list`, `git -C <wt> status` per tree | 0.7 |

## Phase 1: security and reliability fixes (code; one PR each)

| Item | Master IDs | Depends on | Expected benefit | Potential regressions | Validation | Order |
|---|---|---|---|---|---|---|
| Release reservation and close task in `RequestQueue.cancel` for WAITING requests, in the revoked-author claim path and `failed_unfunded`; add a sweep for active reservations whose request is terminal | M-01 (also BE-006) | none (read `ledger.settle` semantics) | Stops silent allowance loss and "queue full"; lets cells sleep | Double-settle if a request is cancelled then claimed; ledger invariants | New tests: cancel waiting, then `_holds`/`max_queued_tasks`; run `test_request_queue`, `test_chat`, `test_native_run`, `test_budget*`; two-account stall scenario (AG-004) | 1.1 |
| Admit-before-claimable (insert paused, flip in admit transaction) | BE-006 | 1.1 | Removes orphan reservations | Race changes in `ChatService.send` | Concurrency test with injected tick | 1.2 |
| Screenshot egress decision, then gate: send images only when no controls are listed, or only on opt-in; wire `browser_optimization` into `jev_for`; update switch text and `privacy.md` | M-02 | owner decision (C); Phase 2 tells whether TypeSafe key is installed | Closes main customer-data egress | JEV accuracy on picture pages (`modes.choose_mode`); switching on enforcement disables JEV until consent | `test_browse*`, `test_routing`; add test asserting no `assets` image in request when gate off | 1.3 |
| Real client IP: derive at Caddy from Vercel's forwarded header (trust Vercel ranges or shared-secret header) | M-04 (BE-003, IS-009) | Phase 2 confirms peers (can precede with doc-only mitigation) | Per-IP limits become per-client | IP spoofing if trust is too broad | Caddy test config + `check_account_http.py`; Phase 2 log sample | 1.4 |
| Exempt `/v1/billing/webhook` and `/v1/telegram/webhook` from the 8192 cap; add middleware-level test | BE-004, ST-018 | none | Stripe retries stop failing | Larger bodies reach handlers (they self-limit at 262144) | New test pushing 9 KB through full stack; `accounts/test_billing.py` | 1.5 |
| Daily `billing_worker --reconcile` timer | BE-005 | none | Dead-lettered events repaired | Stripe rate use | Dry-run in test mode; `systemctl list-timers` after deploy | 1.6 |
| PARK_LIMIT expiry calls stop path (abort run, stop browser job, close) | AG-005 | none | Bounded park | Ending a run the customer still wants | Update `test_native_run.py:198` to assert outcome, not string | 1.7 |
| Fail-open spend guard: repeated snapshot failure alerts or stops | AG-007 | 1.1 (same file) | Spend guard survives LiteLLM errors | Aborts healthy runs when LiteLLM flaky | Fake `usage_snapshot` raising N times | 1.8 |
| Remove or isolate `/v1/tasks/<id>/stream` | BE-002 | confirm no client | Removes app-wide stall vector | Hidden consumer | `rg stream`, route test | 1.9 |
| Add `agentai-browse` to `REQUIRED_UNITS`; Host allowlist for dashboard; unit consistency test | IS-003, IS-011, IS-024 | none | Alerting; hardening | Test asserts tuple | `tests/test_ops_monitor*` | 1.10 |
| Tighten `0o777` browse out dir and `/tmp` staging name | OP-011, OP-012 | none | Local-user screenshot exposure | Stage uid mismatch | `browse/test`, canary | 1.11 |

## Phase 2: verify production (read-only)

| Item | IDs | Depends on | Benefit | Regressions | Validation | Order |
|---|---|---|---|---|---|---|
| Unblock access (DEPLOYMENT_AUDIT section 7), identify the real host, run the one-script checklist | L-01, L-02, L-03 | owner | Converts UNVERIFIED to observed | none (read-only) | saved output reviewed by owner | 2.1 |
| Record: which engine runs, TypeSafe key present, switch states, sshd password/root login, units enabled, cron for retention/reconcile, nft doors, deployed release ids | M-08, M-02, IS-002, IS-004, IS-005, BE-011 | 2.1 | Re-rate Phase 1 and 3 items | none | per-ID note in TECHNICAL_DEBT | 2.2 |
| Update runbooks and README to the correct host | L-01, ST-014 | 2.1 | Ends target drift | none | grep for old IP | 2.3 |
| Key-only SSH, then disable password and root-password login | IS-002 | 2.2 | Largest privacy risk in scope | Lockout; keep console | second session test before disable | 2.4 |

## Phase 3: consolidation

| Item | IDs | Depends on | Benefit | Regressions | Validation | Order |
|---|---|---|---|---|---|---|
| CI: `unittest discover` for `platform/tests` with env skips; add `lumina` `npm ci && tsc --noEmit && vitest && build`, `browse` node tests, `tool_origin_plugin.test.mjs` | M-10 | Phase 0.4; run locally once | Billing/browse/ops regressions caught | Some of 53 modules may fail or need sandbox | Local full run first, then CI green | 3.1 |
| Reconcile doc drift: README/RUNBOOK/ARCHITECTURE status, ServiceRouter references in CLAUDE.local.md and docs, browser-reliability trust boundary, privacy.md door count, deploy README | ST-014, ST-013, M-11, IS-015, ST-015, AG-016, OP-015, OP-016, BE-023 | 2.2 | Correct current state | none | grep for stale terms | 3.2 |
| Generate `accounts.env.example` from `settings.py`; add test every env name appears; fix naming collisions; remove dead `DATA_UPLOAD_MAX_MEMORY_SIZE` | M-09, BE-021 | none | Config discoverability | none | new test | 3.3 |
| `ChatService` factory single wiring; decorator for `customer()`/`rate()` preamble; apply `task.create` to `chat_send`; fix Telegram or hide it | BE-024, BE-017, BE-007 | 3.1 | Removes omission class | Behavior change on send | existing chat tests | 3.4 |
| Switch `retention_accounts` into a timer with the decided retention contract | BE-011 | owner decision (C) | Bounded growth, privacy | Deleting data | dry-run count first | 3.5 |
| Dead-symbol cleanup (unused imports, `GoalChain.limit`, `hmac`, `Plus`, etc.) after grepping tests | ST-012, AG-015, FE-003 | 3.1 | Noise reduction | Test patch targets | full test run | 3.6 |
| Evict finished browse jobs; classify-once for `jev_routing`; reconcile-usage slot release; visibility-pause pollers; N+1 listing | AG-011, AG-012, AG-013, FE-007, FE-008, FE-009 | 3.1 | Resource hygiene | Poll freeze/scroll regressions | `Chat.test.tsx`, manual layout fixtures | 3.7 |
| Add tests: `state/data.tsx`, `ChatBridge`, middleware boundary, settings theme default | FE-015, ST-018, GH-015 | 3.1 | Coverage of hot files | none | vitest/unittest | 3.8 |
| Redacted exception logger (class, module, request id only) | M-12 | owner agrees (C) | Production forensics without customer text | Accidental text in logs | test asserting no message/URL | 3.9 |
| Archive `plans/phase-*`, one-off `bin/phase*` and `config/phase*` only into `archive/` with README | ST-009, ST-021, GH-008 | owner confirms | Clarity | Breaks evidence provenance if moved without redirects | grep evidence manifests | 3.10 |
| `git gc`; consider LFS or build-time fetch for emoji/film assets | GH-011 | none | Repo size | none for gc | `du .git` | 3.11 |
| Commit examples for hand-made server files (dashboard unit, drop-ins); sync script for `runner.mjs` | IS-006 | 2.2 | Drift becomes diffable | none | diff vs host | 3.12 |
| Root-unit systemd sandboxing on a canary | IS-013 | 2.2 | Limits root blast radius | browse/bridge break | canary run, `systemd-analyze security` | 3.13 |
| Delete stale nft sample or generate from `NetPolicy`; classify legacy units | IS-005, IS-004, IS-023 | 2.2 | Honest repo | Remove something still enabled | `is-enabled` checks | 3.14 |

## Phase 4: architecture (needs owner decisions)

| Item | IDs | Depends on | Benefit | Regressions | Validation | Order |
|---|---|---|---|---|---|---|
| Browser engine cutover or freeze: after eval gate delete `runner.mjs`, `stage_argv`, host stage; share one private-range test vector first | M-08 | 2.2, 3.1 | One engine; SSRF rules in fewer places | High, customer-facing | per `docs/architecture/native-browser-plan.md` gate | 4.1 |
| Generative UI: migrate `form` and `task_plan` to `src/gen`, keep only legacy adapter; single registry source | M-07 | 3.1 | Halves genui change surface | Plan editor semantics; historical cards | `blocks.test.tsx`, `gen.test.ts`, backend genui tests | 4.2 |
| `lumina-character`: promote, archive (tag already exists), or delete | M-06, FE-002 | owner decision | -61 MB, no wrong-copy fixes | Loss of only film/ask UI copy at HEAD | tag check | 4.3 |
| Port browser question/vault UI or retire the routes | FE-002 | 2.2 (is `asking` reachable) | No stalls | Customer-visible | Live tests | 4.4 |
| Single lane vs fair scheduling (let `claim` serve holder's own request; count only started tasks in `can_sleep`) | AG-004, BE-013 | 1.1 | Throughput, fairness | Core invariant | two-account scenario test | 4.5 |
| Pick one migration source of truth (move safety tables into SQL) | BE-012, GH-016 | 3.1 | Consistent test DBs | Schema change | `makemigrations --check`, `Store.ready()` | 4.6 |
| Split `loop._run` safety floor into pure function; split `chat_driver.py` by concern | AG-014, ST-008 | 3.1 | Reviewability | Medium | existing suites | 4.7 |
| Decide orphaned modules: wire, hide, or park | M-05 | owner | Clarity | Removing breaks tests/restore list | n/a (decision) | 4.8 |

## Class G: must be preserved (do not delete or "tidy")

| Item | IDs | Why |
|---|---|---|
| Orphaned product modules: `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py`, `optimization.py`, `policy_check.py`, `genui/intent.py`, `ops/rotation.py`, `lifecycle/broker.py`, disabled `/v1/streams|exports|memory|schedules|integrations|controls` stubs | M-05, FEAT-BE-16/17 | Unfinished product features with tables, tests, locked switches and restore lists |
| `gen/legacy.tsx` + `components/genui/Cards.tsx` legacy adapter | M-07 | Only path rendering stored historical table/chart/comparison cards |
| `lumina-character/` until the owner decides; tag `lumina-character-final` | M-06 | Only copy of film UI and ask/vault components at HEAD |
| `jev-browser/`, `jev-window-core/`, 4 tarballs, `experiments/jev-full-page/` | OP-004, OP-005, OP-017, ST-005 | Design history and prototypes; move out of tree, do not delete |
| Connectors OAuth / custody design | BE-008 | Tokens-in-custody design is good; inert, not broken |
| `routing/*` (shadow, display, classifier, policy, bench, report_cli) | M-11 | Live behind switches; `report_cli` used by dashboard |
| Branch/tag history: `release/live1..live8`, `ui-pre-film`, `ui-parchment-v1`, `lumina-character-final` | GH-005 | Only record of earlier deploys |
| `agentai-supervisor.service`, `agentai-platform-control.service`, `deploy/litellm.yaml`, `Caddyfile.example` | IS-023, IS-004 | Delete only after VPS comparison |
| `config/phase*`, `p4_*_check.py`, `p15_acceptance.py`, `plans/phase-*` | ST-009, ST-021 | Cited by evidence manifests |
| `dashboard/app.py` stdlib-only structure | ST-008 | Deliberate isolation of owner tooling |
| `SyntheticGateway`, `DRILL_FAIL`, skipUnless tests | AG, IS, ST-017 | Test hooks, not dead code |
| Positives in `SECURITY_AND_RELIABILITY.md` (webhook verification, uniform 404, fail-closed switches, cell isolation, age backups, privacy-first logging) | - | Do not weaken while refactoring |

## Do-not-do list

1. Do not delete `routing/*` (not just `services.py`): shadow, display and classifier modules are live behind switches.
2. Do not merge `worktree-product-images` as-is: it adds migration `0023_card_images.sql`, which collides with `0023_saved_choices.sql`; its payload already landed in d95b796 as `0025_card_images.sql` (GH-006).
3. Do not run `git add -A` / `git add .` at the repo root until Phase 0.1 is done (M-03).
4. Do not delete `lumina-character/`, the orphaned product modules, or `gen/legacy.tsx` without an owner decision.
5. Do not edit any file under `platform/migrations/*.sql` (checksummed; editing breaks `Store.ready()` and `/readyz`).
6. Do not remove `browse/runner.mjs` or the host stage before the native gate and Phase 2 confirm which engine runs.
7. Do not "fix" `except Exception` / `NullHandler` by logging messages, URLs or bodies; privacy posture is intentional (M-12).
8. Do not add new per-task limits or guardrails as part of these fixes (owner priority).
9. Do not clean up `.bak` files or old configs on the server before reviewing them: they may hold the only copy of a deployed config (IS-006).
10. Do not rewrite history or force-push; `git gc` and a push decision are enough.
11. Do not treat Sonar's 28 vulnerabilities as a to-do list; fix the two privacy-relevant items only (OP-012).
12. Do not rely on the code graph for ServiceRouter, Django route-to-view edges or driver injection (known blind spots in CLAUDE.local.md; ServiceRouter no longer exists).
13. Do not deploy anything while the tool_origin work is uncommitted.
