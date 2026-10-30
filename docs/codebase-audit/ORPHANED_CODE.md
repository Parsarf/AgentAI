# Orphaned code and configuration (no verified caller)

Audit date 2026-10-29, branch `product-phases-6-11`, HEAD `03662de`. Production UNVERIFIED.

## Rules applied

- "Orphaned" here means no caller found by static search. It is a lead, never a deletion order. Per the audit rules, nothing is recommended for deletion on static evidence alone.
- Every item gets one of two dispositions: PRESERVE (product intent, test/evidence dependency, or unknown host-side use) or CANDIDATE-FOR-REMOVAL-AFTER-VERIFICATION (list the verification still owed).
- Dynamic entry-point checks are what the investigators actually recorded. Where a check was not recorded it is listed under "not checked", not assumed clean. Known graph blind spots (from `CLAUDE.local.md`): Django `urls.py` route -> view edges, dynamic dispatch through injected objects, cross-process hops, and string registries are invisible to the code graph.
- Confidence uses the investigators' words (HIGH / MEDIUM / LOW).

## 1. Python product modules with no non-test importer (M-05: BE-014 = AG-009)

Method (BE): stdlib `ast` import graph over `platform/`, then grep of docs and entry points. Method (AG): `rg` for imports, class names (`ScheduleService`, `MemoryService`, `SkillService`, `WatcherService`, `ObjectiveService`, `OptimizationGate`), `urls.py`, `platform/deploy/*.service`, `bin/`, management commands, `importlib` and string registries. `docs/orchestration-audit/02-path-registry.md:184-190` reached the same conclusion. Cleared as NOT orphaned by BE: `ops/probe_models.py`, `routing/bench.py` (`python -m` CLIs), `routing/report_cli.py` (called by `dashboard/app.py:1305`), `ops/cli.py` and `server.py` (systemd entries).

| module | evidence of orphan status | dynamic-entry checks done | still depends on it | confidence | disposition |
|---|---|---|---|---|---|
| `durable.py` (objectives) | zero non-test importers | AST graph, rg class names, urls, units, bin, commands, registries | tests; tables in SQL migrations; `ops/restore.py:20` table list | MEDIUM (BE) / HIGH (AG) | PRESERVE (class C/G): unfinished product feature |
| `memory.py` | same; `views.py` routes `memory` to `disabled` | same | tests, migration `0010`/`0012`-era tables, restore list, locked switch | MEDIUM / HIGH | PRESERVE. Not wired for summarisation (AG context note) |
| `schedules.py` | same; `customer_schedules` switch locked | same | tests, tables | MEDIUM / HIGH | PRESERVE |
| `watchers.py` | same | same | tests, tables | MEDIUM / HIGH | PRESERVE |
| `skills.py` | same | same | tests, tables | MEDIUM / HIGH | PRESERVE |
| `optimization.py` | no importer outside tests; only `switches.py:254` adapter, itself unused (AG-003). Header says DISABLED. Docstring `MODEL='jev-1.13.0'` (`optimization.py:20`) differs from live `jev-1.14.0` | same + rg over `agentai_platform`, `accounts` | tests; switch `browser_optimization` (needs fact `browser_route_deployed` "not yet") | HIGH | PRESERVE. High-priority decision C: the live browse path sends data to TypeSafe without this gate (M-02, AG-003). Wire the gate or retire switch and gate together |
| `policy_check.py` | has `main()` at `:83`; no entry point or unit calls it | rg, units, bin | tests | HIGH (AG) | PRESERVE until owner confirms it is not run by hand; then a removal candidate |
| `genui/intent.py` | zero non-test importers (BE) | AST graph | tests | MEDIUM | PRESERVE; check against `docs/generative-ui` plans |
| `ops/rotation.py` | no CLI hook found (BE) | AST graph, grep of docs | tests | MEDIUM | PRESERVE; may be an operator procedure |
| `lifecycle/broker.py` (199 lines) | imported only by tests and `platform/deploy/p4_broker_check.py:10` | rg, deploy scripts | `p4_broker_check.py`, tests | HIGH | PRESERVE (dormant by design, AG-009) |

Not checked for these: any host-side cron or hand invocation on the VPS (UNVERIFIED), and `gateway.py`, `events.py`, `artifacts.py`, `storage.py`, `genui/*`, `routing/*`, `ops/*` internals were not deep-audited by BE.

Related dead symbols (small, class A after a second grep): `GoalChain.limit` stored but never read (`goals.py:26`; the cap is enforced via `continue_goal` at `chat_driver.py:625`; `commands/request_worker.py:48` passes a decorative argument); `import hmac` unused in `tool_relay.py:14` (AG-015); vulture >=80% hits (ST-012): unused imports `accounts/middleware.py:7` (`RequestDataTooBig`, `TooManyFieldsSent`), `accounts/views.py:88` (`AnonymousUser`), `chat_driver.py:20` (`activity_mod`); unused variables `browse/service.py:146` (`start_picker`), `lifecycle/profiles.py:38` (`running_cells`), `accounts/delivery.py:5` (`email_messages`), `tool_origin_install.py:9` (`g`, in-progress). `activity_mod` and `RequestDataTooBig` may be re-export or patch targets in tests: grep before any removal. The 60% vulture run (241 lines) is almost all Django dynamic loading and Protocol classes: noise (ST).

## 2. Routes and HTTP surface with no frontend caller (FE-020; cross-ref BE section 6)

Method (FE): Python script normalising every `/v1` and `/auth` literal in `lumina/src` against `path(...)` strings in `platform/accounts/urls.py`; heuristic last-segment matching, so treat as leads. Method (BE): full route table from `urls.py`, openapi diff, route-to-test mapping by string match.

| route / endpoint | caller status | dynamic-entry checks | confidence | disposition |
|---|---|---|---|---|
| `v1/browse/<id>/answer` | only `lumina-character` calls it (`useBrowseQuestion.ts:23`) | grep `lumina/src` for `answer`; backend route and `ASK_SECONDS` confirmed | HIGH | PRESERVE. High impact (FE-002): the browser may ask a question with no UI in the shipping app |
| `v1/vault`, `/add`, `/<id>/delete`; `v1/saved`, `v1/saved/<f>/forget` | only fork (`SavedInfo`) | grep, urls | HIGH | PRESERVE (product decision C, FE open question 3) |
| `v1/assistant/presence`, `v1/media/<id>` | only fork (`v1/media` card images may be consumed by server-built cards) | grep | MEDIUM | PRESERVE; verify `media` use by `Cards.tsx` before any decision |
| `v1/genui/registry` | no caller in `lumina/src` (FE-005); frontend holds its own registry | grep `genui/registry` | HIGH | PRESERVE; part of duplication DUP-06 |
| `v1/tasks/<id>/stream` (SSE) | not used (React polls `/v1/tasks/:id/events`); no `EventSource` in either app | grep both apps; gunicorn config inspected | HIGH (unused), MEDIUM (prod flags) | CANDIDATE-FOR-REMOVAL-AFTER-VERIFICATION or isolate (BE-002 High). Verify no external client; owner question 2 |
| `auth/activate`, `auth/revoke-sessions` | no frontend caller | heuristic | MEDIUM | PRESERVE: email-link / session flows, covered by tests (`views.py`) |
| `v1/account/telegram[/link|/unlink]` | no frontend caller | grep | HIGH | PRESERVE (feature INCOMPLETE, BE-007) |
| `v1/account/connections/callback` | no frontend caller; backend callback is a stub | `connections.py:67-73` | HIGH | PRESERVE |
| `v1/account/billing[/checkout|/portal]` | no `lumina/src` caller; served by server-rendered `/account/billing/` | grep | HIGH | PRESERVE |
| `v1/me`, `v1/operations`, `v1/browse/<id>/{pause,resume,release,answer}` (BE list) | BE found no React caller for some; FE shows pause/resume/release ARE called (`Live.tsx:65`) | FE call map checked by hand | MEDIUM | investigators differ: treat `pause/resume/release` as used; `answer`, `me`, `operations` unverified |
| `v1/telegram/webhook`, `v1/billing/webhook` | not UI by design | secret header / Stripe signature | HIGH | KEEP (not orphans) |
| `/internal/accounts/<a>/*` operator routes | no frontend caller; Caddy forwards only `/account /auth /v1 /app` (`Caddyfile.getlumina:20`) so unreachable from the internet; loopback only | urls, Caddyfile | HIGH | PRESERVE; `account_admin` host CLI is the working operator path |
| `internal/accounts/<a>/export|impersonate` | routed, always 403; undocumented in openapi | urls | HIGH | PRESERVE (deliberate deny) |
| disabled kinds `v1/streams|exports|memory|schedules|integrations|controls`, `v1/tasks` list | 503 `capability_not_enabled`; in openapi | urls loop | HIGH | PRESERVE (G) |
| `lumina/src/gen/safety.ts:44` default base `/v1/files/content?path=` | not a backend route; function `safeAssetSrc` unused | grep, urls | HIGH | CANDIDATE-FOR-REMOVAL-AFTER-VERIFICATION of the dead default (FE-010b, class F); real asset route is `/v1/genui/artifacts/<id>/asset` |

Also `/app/gen-gallery` is a reachable dev surface, not an orphan (FE-011).

## 3. Frontend components, exports and apps

| item | evidence | dynamic checks done | confidence | disposition |
|---|---|---|---|---|
| Unused exports in `lumina/src` (FE-003): `Icons.tsx:Plus`, `gen/components/visuals.tsx:Visuals`, `gen/manifest.ts:implementedTypes`, `gen/registry.ts:rendererKeys`, `gen/safety.ts:safeAssetSrc`, `gen/schemas.ts:Layout,RawDocument`, `gen/variants.ts:LAYOUT,STATES,RESPONSIVE,Emphasis,Expansion,Interaction` | name-based grep, no importer incl. tests | dynamic `lazy(import())`, route table, test imports checked | MEDIUM | CANDIDATE-FOR-REMOVAL-AFTER-VERIFICATION (class A after a second grep) |
| About 40 exports used only by tests (`registry.ts:modelCatalog/compactCatalog/schemaSummary/OFFERED`, `protocol.ts:splitReply/parseFence/EnvelopeStream/initialStream`, `lib/safety.ts:canSet/requestBody`) | tests only | same | MEDIUM | PRESERVE: look like model-prompt plumbing waiting for a caller (FE-005, class C) |
| `lumina-character/` whole app (M-06) | no deploy/CI/config reference; docs only | `grep -rIl lumina-character` outside itself; deploy scripts not checked exhaustively (GH-012) | HIGH | PRESERVE (class C/G); see LEGACY_CODE L4 |
| `platform/ui-reference/` | only `UI_CONTRACT.md:10` | grep | HIGH | PRESERVE or C; see LEGACY_CODE L7 |
| `gen/legacy.tsx`, `components/genui/Cards.tsx` indirection | looks dead but is the live path for stored cards | traced | HIGH | KEEP, not an orphan |
| `lumina/tests/` (`preview_*.py`, `browser-layout.js`, `audit-genui.mjs`, `launch-genui.mjs`) | not wired into `npm test`; manual harnesses | not run | HIGH | PRESERVE |
| `AppInfo.features` keys `chat`, `telegram`, `requests`, `usage` | declared, unused in `lumina` (`lib/api.ts:44`) | grep | MEDIUM | PRESERVE; confirm backend `/v1/app` still emits them |
| `lumina/src/vendor/thinking-orbs/` | used by `Orb.tsx` | n/a | HIGH | KEEP (vendored, LICENSE) |

## 4. Deploy artifacts, units, configs

Method (IS): `rg` for each name in units, tests, docs, bin scripts (IS-023). "Do not delete before the VPS comparison" is the investigator's own rule.

| artifact | evidence | checks done | not checked | confidence | disposition |
|---|---|---|---|---|---|
| `platform/deploy/cells-docker/agentai_cells.nft.generated` (15 lines, tracked since `85c83a4`) | stale sample; its `input` chain has no doors for 4000/4100 while `lifecycle/netpolicy.py:68-71` emits them; nothing in the repo reads it (only the unit and `agentai-cells-routes.sh` mention the name) (IS-005) | rg across units/tests/docs/bin | actual `/etc/agentai-cells/agentai_cells.nft` content on the VPS | MEDIUM | CANDIDATE-FOR-REMOVAL-AFTER-VERIFICATION: regenerate from `NetPolicy(..., 4000, tool_relay_port=4100)` or delete after `nft list table inet agentai_cells` is compared (class A/D) |
| `deploy/litellm.yaml` | duplicate of `config/litellm.example.yaml`; not mounted; referenced only by `tests/test_phase10_assets.py:50`; README says canonical is the `config/` one (IS-015c, IS-023) | rg units/tests/docs/bin | VPS compose mounts | MEDIUM | CANDIDATE-FOR-REMOVAL-AFTER-VERIFICATION: change the test reference first (class B) |
| `platform/deploy/Caddyfile.example` | design only; no consumer | rg | none | MEDIUM | PRESERVE or A after owner confirms it is not an install template |
| `platform/deploy/agentai-supervisor.service` | superseded by `-native`; both bind `RuntimeDirectory=agentai-supervisor` | rg units, tests | `systemctl is-enabled` on VPS | MEDIUM | CANDIDATE-FOR-REMOVAL-AFTER-VERIFICATION (see LEGACY_CODE L5) |
| `platform/deploy/agentai-platform-control.service` + `server.py --service control` | no caller in monitor or Caddy; port 18801 clash (IS-004); not in `REQUIRED_UNITS` | rg | VPS enabled state | MEDIUM | PRESERVE until VPS check (LEGACY_CODE L6) |
| `config/skills`, `config/workspace-templates`, `config/phase{4,10,11}-fixtures`, `config/*.batch.json` | no runtime consumer; only `test_phase10_assets.py`, `bin/phase6/*`, evidence manifests (AG-009, AG-026, ST-009) | rg tests, bin, evidence | hand-installed into owner cells on the VPS | LOW-MEDIUM | PRESERVE: evidence manifests cite them as acceptance records; moving breaks provenance |
| `platform/deploy/p4_*_check.py`, `p15_acceptance.py`, `signup_live_check.py`, `capture_fleet_probe.py`, `check_native_fs.mjs`, `prepare_native_cli.py` | run by hand on the server; no unit references them (IS-019) | units, rg | operator shell history | HIGH (no unit) | PRESERVE (they are operator tools); IS-019 notes they mutate live state |
| `bin/phase4/build-sdk-image.sh`, `bin/phase6/prepare-server.py` (171 LOC) | zero references anywhere (ST-009) | `git grep -F basename` excluding audit docs | owner shell history | MEDIUM | UNKNOWN: may be run by hand; ask owner |
| `bin/phase6/authorize-google.py` imports undeclared `mcp` | not an orphan, a dependency gap (ST-006) | read | | HIGH | declare the dependency (class D) |
| `deploy/Dockerfile.{sandbox,claude-code,sdk-peer}` | used by `bin/phase4/build-*.sh` | read headers only | content not read in depth (IS) | LOW | PRESERVE |
| Unit files absent from repo but required: `openclaw-dashboard.service` (+ `feature-switches.conf` drop-in), `agentai-browse.service.d/jev.conf`, `openclaw-ops-backup.*` (IS-006) | referenced by code (`monitor.REQUIRED_UNITS`), no repo copy | rg | VPS | HIGH | inverse of orphan (code with no repo config): commit examples (class B/G) |
| Undocumented units (ST-013): `agentai-billing-worker`, `-ops-backup`, `-ops-monitor`, `-platform-app`, `-platform-control`, `-supervisor`, `-tool-relay` not named in OPERATIONS/RUNBOOK/deploy README | partly grep artefact via timers | grep | | MEDIUM | documentation fix (G) |
| `agentai-platform-mail`, `retention_accounts`, `telegram_worker --drain/--check` | `retention_accounts` and `telegram_worker` are management commands that NOTHING in the repo schedules (`deploy/README.md:83-85`: "No schedule/worker was installed this phase") (BE-011, BE-007) | systemd units and timers listed | a host cron outside the repo | MEDIUM | PRESERVE; they may be run by an out-of-repo cron (owner question). `retention_accounts` is privacy-relevant (class F/C) |
| `billing_worker --reconcile` | supported but the unit runs it without the flag (BE-005) | unit text | | HIGH | feature exists but is never invoked: class D |
| Env vars documented but read by no code: `AGENTAI_CARD_IMAGES`, `AGENTAI_BRAVE_IMAGE_KEY_FILE` (BE-015) | grep | | | HIGH | doc cleanup (A/G) |
| Dev helper `dev_local_ui.py` | Sonar-flagged; loopback preview tool (OP-011, "looks bad but is fine" 5) | not checked whether it is deployed | | MEDIUM | PRESERVE |

## 5. Experimental, research and prototype directories

| path | state | referenced by | checks done | confidence | disposition |
|---|---|---|---|---|---|
| `openclaw-project/browser-opt/`, `research-opt/` | Phase 9/12 adapters; run in CI (offline unit tests); standalone | tests only | read | HIGH | PRESERVE; part of the browser decision GH-004 |
| `openclaw-project/experiments/jev-full-page/` | UNTRACKED | none | listed | MEDIUM | PRESERVE; consolidate with other JEV prototypes (OP-017, class C) |
| `openclaw-project/evals/` | acceptance cases | tests only | | MEDIUM | PRESERVE |
| `jev-browser/`, `jev-window-core/`, `jev-browser-*.tar.gz` | UNTRACKED prototypes, no references (OP-004) | audit docs only | grep for `jev-browser|jev-window` across `openclaw-project` excluding node_modules/evidence | HIGH | PRESERVE as design history; relocate (class C) |
| `lumina-cost-audit/` | UNTRACKED analysis, no code consumer | audit docs | | HIGH | PRESERVE; contains owner browsing request logs, keep out of git (OP-003) |
| `brag-output/`, `product/marketing/`, `sonarqube-export/`, `SONARQUBE-*.md`, `lumina-environment-v3-clips.zip` (242 MB), `openmoji-svg-color.zip`, 6 loose PNGs | UNTRACKED artefacts, not referenced by the platform; the live app serves film from `/var/www/lumina-scenes` (4bdf03c) | OP listing only; PNGs not opened | | HIGH | PRESERVE; relocate or ignore (ST-004/OP-002, class A/C). `product/marketing/` was not examined |

## 6. Hygiene orphans that are a safety issue (not a cleanup)

- `ssk-key`, `ssk-key.pub` at repo root: untracked, NOT gitignored, purpose unknown, never in history, key body never read by any investigator (M-03, IS-001/OP-001/ST-003/GH-009). Reconciliation L-02: its public fingerprint differs from `~/.ssh/id_ed25519.pub` and it was rejected by 179.236.71.203. Action is protective (F: ignore rule or move out of the tree), not removal.
- `lumina-character/node_modules` untracked symlink (GH-002): fix the ignore pattern (`node_modules` without trailing slash).
- 14 stale worktrees under `.claude/worktrees` (573 MB): class A only after each is checked for uncommitted files (GH-014, OP-013).

## 7. Known coverage gaps

BE did not deep-audit `gateway.py`, `events.py`, `artifacts.py`, `storage.py`, `genui/*`, `routing/*`, `ops/*`. AG could not see the VPS (switch file, `browse-engine.json`, TypeSafe key, deployed release, cell image). FE did not run vitest or build, and its "unused" list is name-based. IS did not read `deploy/Dockerfile.*` or `config/*` in depth. `ssk-key` content, `product/marketing/` and all PNGs were not opened. These are gaps, not clean bills.
