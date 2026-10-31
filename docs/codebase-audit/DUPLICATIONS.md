# Duplicated and overlapping implementations

Audit date 2026-10-29, branch `product-phases-6-11`, HEAD `03662de`. Production UNVERIFIED. Uncommitted tool_origin / tool_relay / cell_bridge / cell_config work is IN-PROGRESS and not judged.

Class labels (inferred from the findings): A = safe cleanup after verification, B = consolidate, C = product decision, D = targeted repair, E = architecture change, F = fix/harden, G = preserve/document. All "consolidation" suggestions below are class B unless stated and carry the prerequisite that tests exist first. Several duplicates are deliberate isolation (owner tooling versus customer platform, per the privacy priority); those are called out and should not be merged.

## Index

| ID | duplication | divergence risk | consolidation class | main findings |
|---|---|---|---|---|
| DUP-01 | Private-address / SSRF policy x4 (plus page-side logic x2) | High (security) | B after E | AG-010 |
| DUP-02 | `ChatService` factory x4+ | High (already caused Telegram breakage) | B | BE-007, BE-024 |
| DUP-03 | Two schema migration systems | Medium (tables only in Django migrations) | E | BE-012, GH-016 |
| DUP-04 | Three generative-UI generations | Medium | C then B | FE-004, GH-007 (M-07) |
| DUP-05 | `lumina` versus `lumina-character` | Medium | C | FE-001, ST-002, GH-012 (M-06) |
| DUP-06 | Genui registry/catalog in frontend and backend | Medium (prompt drift) | E | FE-005 |
| DUP-07 | `runner.mjs` versus `native_scripts.py` / `native_runner.py` | High (security-sensitive) | E | AG-010, GH-004 (M-08) |
| DUP-08 | Plan constants versus `product/plan.json` | Medium | B | OP-008 |
| DUP-09 | Task-limit sets: `routing/config.py` versus `plan.json` | Medium | C | OP-008 #10 |
| DUP-10 | `deploy/litellm.yaml` versus `config/litellm.example.yaml` | Low | A/B | IS-015, IS-023 |
| DUP-11 | Env loaders and two hand-rolled `.env` parsers | Low-Medium | B (limited) | ST-011 |
| DUP-12 | Env names and defaults: live secret, Telegram token, SSH, switches path, origins | Medium | B | BE-015, IS-007 (M-09) |
| DUP-13 | HTTP clients, time formats, atomic writes, raw sqlite | Low | B only where it reduces risk | ST-011 |
| DUP-14 | View/service boilerplate (store+service wiring, auth preamble, rate calls) | Low-Medium | B | BE-024 |
| DUP-15 | Frontend overlapping pollers and raw `fetch` bypassing `api()` | Medium (load) | B | FE-006, FE-007, FE-008, FE-009 |
| DUP-16 | `ui-reference/app.js` versus `lumina/src/lib/api.ts` | Low | C | FE-018 |
| DUP-17 | Two tool-ownership mechanisms (transcript matcher versus proof hook) | In-progress | G | AG-006 |
| DUP-18 | Owner dashboard helpers versus platform helpers | Low (intentional) | G, do not merge | ST-008 |
| DUP-19 | Duplicate settings and ignore entries | Low | A | BE-021, ST-020 |

## DUP-01. Private-address / SSRF policy (AG-010)

- Locations: `browse/runner.mjs` (`privateIp`, line ~18); `browse/native_runner.py:34-60` (`private_ip`, `url_allowed`); `agentai_platform/ssrf.py` (`check_url` resolves but does not pin the address, its docstring admits this; BE-008); `lifecycle/netpolicy.py:18` (`PRIVATE_RANGES`). Page-side logic is also written twice: `runner.mjs` and the named scripts in `native_scripts.py` (182 lines) must stay behaviour-equal for the two engines.
- Tests are separate: `browse/test/runner.test.mjs:226`, `tests/test_native_runner.py:97`, `e2e/test_native_browser.py:235`.
- Divergence risk: any rule change (example given: CGNAT 100.64/10) must land in all places; a missed copy is a SSRF gap. `/v1/browse/<id>/control` forwards customer-typed `goto` URLs (up to 2048 chars) over the socket and relies on the browse service's policy (BE cross-scope).
- Consolidation: one source of ranges (generated or a JSON vector) consumed by `ssrf.py`, `netpolicy.py`, `native_runner.py`; `runner.mjs` consumes the same vector until retired. Until the engine decision (DUP-07), add a shared test vector only.
- Prerequisites: engine decision (LEGACY_CODE L2); the shared vector test must pass in all three languages first. Risk: medium (security-sensitive); do not refactor without the vector.

## DUP-02. ChatService factory (BE-007, BE-024)

- Locations: `accounts/chat.service()` (the only factory that wires `pricer` and `gateway_factory`); re-implemented in `accounts/telegram.py:26-31`, `accounts/files.py`, `accounts/views.projects`, and `telegram_worker.py:20-21`. `AccountStore(connection.settings_dict['NAME'])` plus service wiring is repeated in about 12 view modules.
- Divergence already realised: the Telegram factory builds `ChatService(...)` without `pricer`, `gateway_factory` or a service limit, so `UnmeasuredRoute` raises `CapabilityUnavailable` and Telegram requests wait unfunded and fail. Only tests inject `FixedRoute` (`tests/test_telegram.py:43`, `accounts/test_telegram.py:60`), so tests mask the production defect.
- Consolidation: one `build_chat_service(store, ...)` in `accounts/` used by chat, telegram, files, projects and the worker; plus a test that every entry point constructs a service with a real pricer. Classes B (factory) and D (Telegram finish).
- Prerequisites: decision to ship or hide Telegram (INCOMPLETE_FEATURES). `BE-020` (the factory also builds two switch reads and a `Coordinator` per call) should be considered in the same change.

## DUP-03. Two migration systems (BE-012, GH-016)

- Locations: 30 checksummed SQL files `platform/migrations/0001..0030_*.sql` applied by `Store.initialize()` (authoritative, checksum in `schema_migrations`; editing any file breaks `Store.ready()` and `/readyz`); Django migrations `accounts/migrations/0000..0015` where `0000`, `0004`, `0008-0012` are six near-identical shims that re-run the SQL adopter, and `0013_signup_token.py`, `0014`/`0015` are real.
- Divergence: `safety_overrides` and `safety_access` exist only in Django migrations 0014/0015, not in the SQL dir, so `Store(path).initialize()` (used by about 10 test modules and `server.py --migrate`) yields a DB without them; `services._rate_limits_off` hides the resulting error behind `except Exception: return False`. `makemigrations --check` is clean (models match). SQL numbering has no duplicates on this branch; branch `worktree-product-images` would collide on `0023`.
- Consolidation (class E): pick one source of truth; minimum step is moving the two safety tables into SQL. Document which system owns which tables.
- Prerequisites: a test that `Store.initialize()` yields every table the code reads; checksums must not change for applied files. Do not delete the six shims: they are idempotent and checksum-verified (BE "looks bad but is fine" 5).

## DUP-04. Three generative-UI generations (FE-004, GH-007, M-07)

- Locations: v0 `src/lib/genui/*` + `src/components/genui/*` (form, task_plan, table, chart, comparison; own zod specs and `useAutosave` on `/v1/blocks/<id>/{state,live}`); v1/v2 `src/gen/*` (document renderer, `BlockView.tsx:12-13`); adapter `gen/legacy.tsx` invoked from `components/genui/Cards.tsx:4`, so `BlockView` -> `Cards` -> `gen/legacy` -> `gen/Renderer` for historical cards. Server: `genui/schema.py`, `document.py`, `artifacts.py`, `gen_registry.json`.
- Divergence: two `Block`-ish type families, two sets of tests (`components/genui/blocks.test.tsx`, `gen/*.test.*`), double zod validation; every genui change must be made or checked twice.
- Consolidation: C (target path), then migrate `form` and `task_plan` into `gen/` and keep only the legacy adapter (class B/E).
- Prerequisites: confirm no new v0 cards are being created; backend `/v1/blocks/*` contract and stored customer cards must keep rendering; plan editing/launch semantics test coverage. Medium risk.

## DUP-05. `lumina` versus `lumina-character` (M-06)

- Locations: `openclaw-project/lumina/` (live) and `openclaw-project/lumina-character/` (fork; 4,697 versus 4,701 tracked files; 88 `diff -rq` differences in `src/`; both have `AGENTS.md`, `DESIGN.md`, `.impeccable/`). Version drift: zod 4.6.5 vs 4.6.7, vite 8.3.1 vs 8.3.5, vitest 5.0.2 vs 5.0.5. Vendored `thinking-orbs` and 4,495 OpenMoji SVGs are duplicated, plus 61 MB of film assets only in the fork.
- Divergence: fixes may land in the wrong copy; fork's pins are untested because `tsc` ran against `lumina/node_modules` through an untracked symlink; `AGENTS.md` copies drift (FE-017).
- Consolidation: C (promote, archive via tag `lumina-character-final`, or extract needed pieces such as `useBrowseQuestion` and `AskBox` back into `lumina`), not B until decided.
- Prerequisites: owner decision; verify `bin/deploy-lumina.py` and `release.py` build only `lumina` (ST cross-scope link); confirm Caddy `/var/www/lumina-scenes` usage (GH-018).

## DUP-06. Registry/catalog in two places (FE-005)

- Locations: frontend `gen/registry.ts`, `gen/manifest.ts`, `gen/catalog.ts` (`modelCatalog()/compactCatalog()` "only implemented entries are shown to the model"); backend `GET /v1/genui/registry` (`urls.py:59`, `gen.component_registry`) which the frontend never calls; backend also validates documents (commit `a7bdfae`).
- Divergence: model prompt drift between the catalog the model sees and the schemas the server accepts; no cross-check test found.
- Consolidation (class E): one source (generated JSON consumed by both) or a test diffing backend schema list against `gen/schemas.ts IMPLEMENTED_TYPES`.
- Prerequisites: lead diff of the two lists; decide whether the frontend should consume `/v1/genui/registry`.

## DUP-07. `runner.mjs` versus native engine (M-08, AG-010, GH-004)

- Locations: `browse/runner.mjs` (345 lines, default engine) versus `browse/native_runner.py` (435), `native_scripts.py` (182, page-side scripts); the uncommitted tool_origin v2 is a third layer. Planned deletion of the runner after an eval gate (`native-browser-plan.md:131`).
- Divergence: behaviour parity between page-side scripts, SSRF logic (DUP-01), tests in three places; the VPS copy `/opt/agentai-browse/runner/runner.mjs` is hand-synced (five `.bak-live*`), so repo and host can differ (IS-006).
- Consolidation (class E, after C): finish the cutover; remove the loser. Until then add the shared test vector and a script to sync/verify the VPS copy (sha256 compare, IS checklist D).
- Prerequisites: owner picks cutover; eval gate; VPS `browse-engine.json` read. Risk: high.

## DUP-08. Plan constants versus `product/plan.json` (OP-008)

- Locations: loaded from plan.json: prices, `daily_provider_cost_usd`, `max_task_cost_usd`, `max_queued_tasks` (`billing.py:190-193`, `budget.py:80`). Hard-coded duplicates: `MAX_PROJECTS=10` (`accounts/chat.py:27`, `accounts/api.py:79`), `max_message_characters` 16000 (`accounts/chat.py:165`, `accounts/requests.py:18`, `telegram.py:220`), upload 10 MiB and batch 25 MiB / 10 files (`agentai_platform/files.py:21-23`, `accounts/files.py:25`), stream connections 3 (`events.py:25`), `ops/monitor.py:30 max_running_cells: 1`.
- Divergence: editing plan.json does not change the duplicated ones; claims `max_task_steps` 60, `max_model_calls` 30, `max_search_requests` 20, storage 2 GiB, zip 250 MiB, artifact 100 MiB were NOT found enforced by grep (UNVERIFIED; only `browse/adapter.py:76 MAX_STEPS = 12`).
- Consolidation (class B): a single `plan` accessor read from `plan.json` (as billing already does) used by all listed sites; enforce or remove the unenforced limits (C).
- Prerequisites: tests pinning each limit; decide which stated limits are real product promises.

## DUP-09. Two task-limit sets (OP-008 #10)

- `product/plan.json` (`max_task_cost_usd` 5.00, `max_task_duration_seconds` 3600) versus `routing/config.py:21` (default 1800 s, $1.00) and `chat_driver.py` `RUN_TIMEOUT` 900 s, `PARK_LIMIT` 1800 s, `cell_config` backstop 1200 s (layered on purpose per AG "looks bad but is fine" 6).
- Divergence: unclear which is authoritative at runtime (not verified). Class C decision, then B.

## DUP-10. LiteLLM config (IS-015c, IS-023)

- `deploy/litellm.yaml` duplicates `config/litellm.example.yaml`; not mounted by compose; referenced only by `tests/test_phase10_assets.py:50`; `deploy/README.md` says the `config/` file is canonical.
- Risk: low; someone edits the wrong file. Consolidation: delete the duplicate after repointing the test and confirming the VPS mount (class A/B). Check on the VPS that `turn_off_message_logging: true` and `fail_closed_budget_enforcement: true` are in the live file (IS checklist E).

## DUP-11. Env loaders and `.env` parsers (ST-011)

- Two hand-rolled parsers: `bin/owner-console.py:45 load_env` and `platform/deploy/release.py:40 read_env`; five `bin/*.py` scripts use `python-dotenv` (`requirements-local.txt`); platform settings use `os.environ` (39 reads in `accounts/settings.py`).
- Risk: low-medium (differences in quoting/comment handling). Consolidation: B only for the two parsers if it reduces risk; keep owner tooling separate from customer platform on purpose.

## DUP-12. Env names, defaults, naming (BE-015, IS-007, M-09)

- `accounts.env.example` documents 8 of about 42-45 `AGENTAI_*` names; 23 appear in no example/unit/README/OPERATIONS/RUNBOOK; 2 documented but unread (`AGENTAI_CARD_IMAGES`, `AGENTAI_BRAVE_IMAGE_KEY_FILE`).
- Same concept under several names: live secret = `AGENTAI_LIVE_SECRET_FILE` (app, `settings.py:120`) versus `LIVE_SECRET_FILE` / `AGENTAI_LIVE_SECRET` (gateway, `live/gateway.py:144-145`) versus `--live-secret-file` flag (browse service, reads with different permission rules, `service_main.py:33-35`). Telegram token = `AGENTAI_TELEGRAM_BOT_TOKEN` (app) versus `OPENCLAW_TELEGRAM_BOT_TOKEN` (owner tooling). SSH = `OPENCLAW_SSH_*` versus `OPENCLAW_NEW_SSH_*` selected by `OPENCLAW_SERVER` (default "new", `bin/ssh-server:19`). Names only; no values recorded.
- Diverging defaults: switches file path `''` in `settings.py:105` but `/opt/openclaw-production/feature-switches/switches.json` in `browse/service_main.py:49` and the lifecycle-worker unit; `AGENTAI_PUBLIC_ORIGIN` default `https://localhost` versus `AGENTAI_BILLING_PUBLIC_ORIGIN` default `https://getlumina.pro` (`settings.py:10,133`).
- Consolidation (class B): extend `accounts.env.example` with a commented full list generated from `settings.py`, and a test asserting every `os.environ` name in settings appears there. Keep the Telegram app/owner split unless the owner wants one bot.

## DUP-13. HTTP clients, time, atomic writes, sqlite (ST-011)

- Only 5 files call `urlopen` (telegram, dashboard, `bin/activate-telegram`, `release`, `prepare_native_cli`) plus `routing/classifier.py` using `http.client`; 11 hard-coded `%Y-%m-%dT%H:%M:%S` formats in 5 files, `dashboard.now_iso`, `billing._now`; 17 files use `os.replace` with helpers only in `storage.write_private` and `switches._write`; raw `sqlite3.connect` in 12 modules besides Django (`ops/*`, `lifecycle/*` open their own).
- Risk low; some of it is intentional isolation (privacy memory). Consolidate only where it reduces risk; do not couple the dashboard to the platform.
- Related: 126 `except Exception` sites, about 39 with a bare `pass`, and 7 modules using `logging` versus 17 using `print` (ST-010, BE-010, M-12): any shared logger must be redaction-aware (class B/C; never log customer text).

## DUP-14. View and service boilerplate (BE-024, BE-020)

- `denied = customer(request); if denied: return denied` preamble and `rate('task.create', ...)` calls copy-pasted in 80+ views; the missing cap on `chat_send` (BE-017) is exactly the class of omission this causes. `SwitchStore(...).is_on` re-reads JSON files per call and is constructed repeatedly.
- Consolidation (class B): a decorator for auth+rate+service; cache switch reads per request. God-file check: `billing.py` (683), `connectors.py` (544), `chat.py` (505) are cohesive; do not split now.

## DUP-15. Frontend polling overlap and client bypass (FE-006..FE-009)

- While a task runs, `Chat.tsx` reloads messages + blocks + conversation + list every 2.5 s, `DataProvider` reloads `/v1/app` + `/v1/requests` + `/v1/conversations` every 3 s, `AgentThinking` polls events (2.5 s), `useActivity` (1.5 s), `Tasks` (4 s), `ActivityPanel` (2 s). `/v1/conversations` is requested from at least 3 paths. N+1 file listing at `Chat.tsx:71-72` and `Files.tsx:18-19`. Raw `fetch` bypasses `api()` (no CSRF, no 401 broadcast, no timeout) at `state/data.tsx:62`, `Login.tsx:17`, `gen/components/model.tsx:12`, `LiveScreen.tsx:33`. Only `data.tsx`, `LiveScreen` and `gen/components/context.tsx:96` pause when the tab is hidden.
- Estimated 5-8 req/s peak per active tab (estimate, not measured). With one sync gunicorn worker and SQLite (BE-002, BE-013) this is a throughput ceiling.
- Consolidation (class B): visibility-pause, one multiplexed poll or SSE (C/E), a single projects+files endpoint. Risk: freeze/scroll regressions noted at `Chat.tsx:21`.

## DUP-16. `ui-reference` client (FE-018)

- `platform/ui-reference/app.js` reimplements `api()`; not built, served or tested. Drifts silently if CSRF or error shape changes. Class C (document-only versus removal after verification).

## DUP-17. Two ownership mechanisms (AG-006, AG-008, AG "looks bad but is fine" 5)

- Older transcript/SQLite reader of tool-call ownership versus the new one-use proof hook (protocol 2, `tool_origin*.py`, plugin). This is a staged in-progress replacement, not accidental duplication. Risk: docs (`docs/browser-reliability.md` trust-boundary section) describe the superseded reader. Class G: commit the work, make docs match protocol 2.

## DUP-18. Dashboard helpers (ST-008)

- `dashboard/app.py` (1718 LOC) has its own `now_iso()` (`:98`), HMAC compare, cookies, because it is stdlib-only and separately deployed by design (`ARCHITECTURE.md:166-168`). Do not merge with the platform. Class G; if split, start with HTML templates.

## DUP-19. Minor duplicate entries (BE-021, ST-020, FE-014)

- `DATA_UPLOAD_MAX_MEMORY_SIZE` assigned twice (200000 at `settings.py:61`, then 31457280 at `:101`; the first is dead); `.env` appears twice in `openclaw-project/.gitignore` (harmless); `react-markdown` / `remark-gfm` use `^` ranges while everything else is pinned (also in the fork). Class A/B, low risk.

## Suggested order (by risk reduction, not effort)

1. DUP-02 (Telegram/other factory break) and DUP-01 + DUP-07 shared test vector (security-sensitive duplicates).
2. DUP-03 minimum step (two safety tables into SQL) and DUP-12 env documentation test.
3. DUP-08/DUP-09 after the owner states which limits are promises.
4. DUP-04/DUP-05/DUP-06 after the product decisions (all class C first).
5. DUP-14, DUP-15, DUP-13 opportunistically with tests.
