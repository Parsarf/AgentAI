# Frontend audit (SCOPE FE)

Branch product-phases-6-11. Read-only audit. Production state UNVERIFIED throughout.

## Scope & method

Covered: `lumina/` (src, tests, scripts, package.json, vite/tsconfig, .impeccable, dev-mock.mjs, AGENTS/DESIGN/PRODUCT), `lumina-character/` (same), `platform/ui-reference/`. `lumina/public` (22 MB: openmoji SVGs, earth.jpg), `lumina-character/public` (61 MB: 31 scene mp4s, jpgs, openmoji, earth.jpg) and `lumina/src/vendor/thinking-orbs` (vendored, MIT-style LICENSE, 5 files) only noted.

Run: `rg/grep`, `git log/show/ls-files/tag`, `tsc --noEmit` in both apps (installed binary, no emit; both exit 0), a Python `-I` static script for unimported modules and unused exports, and a Python script that normalised every `/v1`, `/auth` literal in the frontend against `path(...)` strings in `platform/accounts/urls.py`.
Not run: vitest (writes caches, not needed), `vite build`, the `tests/preview_*.py` browser fixtures (start servers), `npm audit` (network). Not checked: what is actually deployed at getlumina.pro, how `AGENTAI_UI_BUNDLE_DIR` is populated, runtime behaviour of any page. Export "unused" results are name-based greps, so treat them as leads (checked: dynamic `lazy(import())`, route table, test imports).

Size picture: no god files by LOC. Largest TS/TSX source file is ~250 lines; `Chat.tsx` 122 lines, `Composer.tsx` 115, `Shell.tsx` 91. But lines are very dense (Chat.tsx is 11.8 KB in 122 lines, many >250 chars; `Composer.tsx` 11.3 KB in 115). `styles/app.css` is 416 lines / 41 KB. The "god" risk is density and the single global stylesheet, not line count.

## File/module map

### lumina/ (the live app, built to `lumina/dist`, served by the Django backend at `/app/`)

| path | responsibility | consumers / entry | notes |
|---|---|---|---|
| `src/main.tsx`, `App.tsx` | boot, `canonical()` redirect to `/app/`, router (`basename="/app"`) | Vite entry (`index.html`) | auth gating is a status switch in App, not a route guard |
| `src/state/data.tsx` | `DataProvider`: status/app/requests/chats, polling, signIn/out, `/readyz` probe | every page via `useData` | single global store, no external state lib; no test file |
| `src/state/settings.tsx` | reduced motion / compact / sidebar in localStorage | `SettingsProvider` | |
| `src/lib/api.ts` | the only HTTP client (`api()`, CSRF, `ApiError`, 401 broadcast) | all pages/components; 3 raw `fetch` exceptions (see FE-006) | |
| `src/pages/` Chat, Home, History, Tasks, Live, Files, Login, Info(Calendar/Automations/Integrations/Settings) | route screens | `App.tsx` | Info.tsx bundles 4 screens; Calendar/Automations are "Soon" placeholders |
| `src/components/` Shell, Sidebar, Rail, Composer, ChatList, ChatActions, ActivityPanel, AgentThinking, LiveScreen, LiveTerminal, Orb, Globe, Backdrop, Menu/Toggle (ui/), Credits, Icons, Emoji | layout and chat UI | pages | Globe uses three + R3F |
| `src/components/response/` | markdown answer renderer (react-markdown + remark-gfm) | Chat | `safeResponseUrl` link filter |
| `src/components/safety/` + `lib/safety*.ts`, `useSafety.ts`, `styles/safety.css` | Safety console dialog opened from Sidebar (`SafetyButton`) | `Sidebar.tsx:4` only | has README.md and a 403-line test |
| `src/components/genui/` + `lib/genui/` | OLD block system: form, task_plan (PlanBlock), table/chart/comparison cards, autosave | `BlockView` from `Chat.tsx` | zod specs in `lib/genui/schema.ts` |
| `src/gen/` (protocol, schemas, extendedSchemas, registry, manifest, catalog, variants, constraints, actions, drafts, diagnostics, safety, ChatBridge, Gallery, legacy, fixtures, components/*) | NEW generative-UI document system: zod protocol, 60-ish block renderers, registry that also feeds the model catalog | `BlockView` lazy-imports `gen/ChatBridge` for `kind:'document'`; Gallery route `/app/gen-gallery` | ~2.9k lines incl. tests |
| `src/vendor/thinking-orbs/` | vendored orb engine | `components/Orb.tsx` | not audited |
| `styles/` tokens, ui, safety, app.css, `gen/gen.css`, `response/response.css` | CSS | `main.tsx`, `Renderer.tsx` | no CSS modules; one global sheet |
| `tests/` | `browser-layout.js`, `audit-genui.mjs`, `launch-genui.mjs`, `preview_*.py` | manual real-browser harnesses (need a server) | not wired into `npm test` |
| `scripts/` | `check-design.mjs` (runs in `npm run build`), `build-openmoji-index.mjs` | build | |
| `dev-mock.mjs`, `.impeccable/`, `DESIGN.md`, `PRODUCT.md` | local mock API, design review artefacts, docs | dev only | |
| `dist/` | build output, gitignored | backend `AGENTAI_UI_BUNDLE_DIR` (platform/accounts/uishell.py) | |

### lumina-character/ (see FE-001)

Frozen fork of the previous Lumina UI ("character" skin: parchment/obsidian theme, `SceneBackground` film scenes, `Live`, vault/saved-info, browser-question UI, safety panel). One commit (d95b796, 2026-10-27) plus tag `lumina-character-final`. Same structure as lumina minus `src/gen/`, minus new `safety/` console, minus `pages/Chat` goal/answer-style features; plus `SavedInfo`, `FieldsBox`, `AskBox`, `ChatQuestion`, `QuestionPanel`, `SafetyPanel`, `SceneBackground`, `useBrowseQuestion`, `useTaskEvents`, `lib/scene.ts`. 160 tracked non-public files, ~60 test files.

### platform/ui-reference/ (14+76+4 lines)

Plain-JS reference client (sign-in, chat, clear, sign-out) referenced by `platform/UI_CONTRACT.md:10`. Not built, not served by anything I found (grep for `ui-reference` outside itself hits only UI_CONTRACT.md).

## Features

| ID | name | status | flags | frontend | backend | evidence | prod verified? | notes |
|---|---|---|---|---|---|---|---|---|
| FEAT-FE-01 | Sign-in / sign-up / verify / logout | ACTIVE | cookie session | `pages/Login.tsx`, `state/data.tsx:70-76` | `/auth/login`, `/auth/signup`, `/auth/signup/verify`, `/auth/logout`, `/v1/signup/config` | all in urls.py | unknown | honeypot field `website` sent on signup (`Login.tsx:32`) |
| FEAT-FE-02 | Chat (send, history, rename, archive/restore, search) | ACTIVE | `features.execution` gates Composer | `Chat.tsx`, `Composer.tsx:84`, `History.tsx`, `ChatActions.tsx` | `/v1/conversations*` | `App.tsx` index + `chat/:id` | unknown | 2.5 s poll while working (FE-008) |
| FEAT-FE-03 | Tasks (pause/resume/cancel/retry/goal) | ACTIVE | | `pages/Tasks.tsx:22-44` | `/v1/requests/<id>/{cancel,pause,resume,retry}`, `/v1/conversations/<id>/goal`, `/v1/tasks/<id>` | | unknown | |
| FEAT-FE-04 | Live browser view + takeover | ACTIVE | `features.browse` | `pages/Live.tsx`, `LiveScreen.tsx:30-33` | `/v1/browse/<id>` `/live` `/control` `/pause` `/resume` `/release` `/shot/` | route `live/:id` | unknown | frame stream = repeated long fetch, not SSE/WebSocket (FE-007) |
| FEAT-FE-05 | Browser "asking" question UI (answer a question the browser run raised) | ORPHANED in lumina; ACTIVE only in the frozen fork | | only `lumina-character` (`useBrowseQuestion.ts:23`, `Live.tsx:84`) | `/v1/browse/<id>/answer` exists | grep: no `answer` caller in `lumina/src` | unknown | see FE-002 |
| FEAT-FE-06 | Vault / saved form values UI | ORPHANED (fork only) | | `lumina-character/.../SavedInfo.tsx` | `/v1/vault`, `/v1/vault/add`, `/v1/vault/<id>/delete`, `/v1/saved`, `/v1/saved/<f>/forget` | no `vault`/`saved` in `lumina/src` | unknown | product decision (FE-002) |
| FEAT-FE-07 | Safety console | ACTIVE | | `SafetyButton` in `Sidebar.tsx:4` | `/v1/safety`, `/safety/change`, `/safety/access`, `/safety/access/change` | | unknown | new in lumina, fork has the older `SafetyPanel` |
| FEAT-FE-08 | Generative UI (document blocks) | ACTIVE | answer style setting (`lib/answerStyle.ts`) sent as `ui` on send | `BlockView.tsx:12-13` -> `gen/ChatBridge.tsx` | `/v1/conversations/<id>/blocks`, `/v1/genui/artifacts/<id>/{state,events,asset,diagnostics}`, `/v1/blocks/<id>/phase` | | unknown | coexists with old block system (FE-004) |
| FEAT-FE-09 | Old block system (form, task_plan, table, chart, comparison) | LEGACY / DUPLICATED | | `components/genui/*` | `/v1/blocks/<id>/{state,live,submit,launch,phase,stop}` | `BlockView.tsx:15-27` | unknown | history rendering + plan editor still live here |
| FEAT-FE-10 | Files (list, download ticket, zip bundle) | ACTIVE | `features.files` | `pages/Files.tsx` | `/v1/projects`, `/v1/projects/<id>/files`, `/bundle`, `/v1/artifacts/<id>/versions/<v>/ticket` | | unknown | N+1 (FE-009) |
| FEAT-FE-11 | Settings / usage / answer style | ACTIVE | | `Info.tsx:Settings` | `/v1/costs` | | unknown | "Classic view" links to `/account/` |
| FEAT-FE-12 | Integrations list | INCOMPLETE | `features.connectors` | `Info.tsx:Integrations` | `/v1/account/connections` | | unknown | read-only list; no connect/disconnect UI though `connections/callback` exists in backend |
| FEAT-FE-13 | Calendar, Automations | INCOMPLETE | | `Info.tsx:Calendar/Automations` ("Soon" component) | none called | text says schedule engine "built but locked" | unknown | product decision |
| FEAT-FE-14 | Billing / subscription UI | INCOMPLETE | `billing_mode` | only a text label in Sidebar/Settings | backend has `/v1/billing/webhook` | no checkout/portal call in `lumina/src` | unknown | |
| FEAT-FE-15 | Telegram link/unlink | INCOMPLETE | `features.telegram` | declared in `AppInfo` type only (`lib/api.ts:44`) | `/v1/account/telegram/unlink` exists | grep: no caller | unknown | |
| FEAT-FE-16 | Component gallery `/app/gen-gallery` | EXPERIMENTAL | | `gen/Gallery.tsx` | none (sandbox host) | `App.tsx:28` | unknown | reachable by any signed-in customer (FE-011) |
| FEAT-FE-17 | `Home` dashboard | ACTIVE | | `pages/Home.tsx`, nav `/home` | `/v1/requests` | `App.tsx` | unknown | but `/` renders Chat (FE-012) |
| FEAT-FE-18 | Scene film background, parchment theme | ORPHANED (fork only) | | `lumina-character/SceneBackground.tsx` | `/v1/assistant/presence` | not in `lumina/src` | unknown | 61 MB of assets in git |
| FEAT-FE-19 | `platform/ui-reference` | LEGACY / reference | | `app.js` | `/v1/csrf` etc. | referenced only by UI_CONTRACT.md | unknown | |

## Findings

**FE-001** | Architecture / duplication | Medium | HIGH | M
`lumina-character/` is a second full copy of the SPA (fork, one commit d95b796, tag `lumina-character-final`), not a workspace package, not imported by `lumina`, not referenced by any deploy/config file I found. `grep -rIl lumina-character` outside itself hits only `docs/architecture/findings.md` and `docs/orchestration-audit/06-history-and-legacy.md`. It builds to its own `dist` (untracked/ignored locally) but nothing consumes it. `lumina-character/node_modules` is an untracked SYMLINK to `../lumina/node_modules` (`ls -ld`; shows as `?? lumina-character/node_modules` in git status because the `.gitignore` pattern `node_modules/` does not match a symlink). Consequence: its `tsc` pass (exit 0) was done against lumina's dependency versions, so its own `package.json` pins (vite 8.3.1, vitest 5.0.2, zod 4.6.5) are untested and drift from lumina's (8.3.5, 5.0.5, 4.6.7). It also carries 61 MB of tracked public assets (31 mp4 scenes).
Files: `lumina-character/package.json`, `lumina-character/.gitignore`. Git: d95b796.
Impact: none at runtime if undeployed (production UNVERIFIED); repo weight and confusion; a future `git add -A` could commit the symlink.
Action: C product decision (is the parchment/scene skin coming back?) and G preserve the code; at minimum add `node_modules` (no slash) to its .gitignore. Risk: low.

**FE-002** | Feature regression / broken integration | High | HIGH | M
Browser "asking" question UI, vault and saved-info UI were removed from `lumina` in d95b796 and kept only in the fork. Backend still serves `/v1/browse/<id>/answer`, `/v1/vault*`, `/v1/saved*`. In `lumina`, `Live.tsx:129` and `lib/live.ts` have no answer path (`grep answer lumina/src` has no API caller). Consistent with `docs/architecture/findings.md` F-17. A browser run that stops to ask the customer therefore has no screen in the shipping app (assuming the backend can still reach that state; backend scope).
Files: `lumina/src/pages/Live.tsx`, `lumina-character/src/lib/useBrowseQuestion.ts:10-23`, `lumina-character/src/pages/Live.tsx:84`.
Evidence: endpoint diff script output (answer/vault/saved/presence/media only used by `lumina-character`).
Action: C product decision, then D repair (port `useBrowseQuestion` + `AskBox` into lumina) or have the backend stop emitting the state. Risk: customer-visible stalls if the state is reachable.

**FE-003** | Dead code | Low | MEDIUM | S
Name-based unused exports in `lumina/src` (checked not imported anywhere including tests, not used dynamically): `components/Icons.tsx:Plus`, `gen/components/visuals.tsx:Visuals`, `gen/manifest.ts:implementedTypes`, `gen/registry.ts:rendererKeys`, `gen/safety.ts:safeAssetSrc`, `gen/schemas.ts:Layout,RawDocument`, `gen/variants.ts:LAYOUT,STATES,RESPONSIVE,Emphasis,Expansion,Interaction`. About 40 more exports are used only by tests (e.g. `registry.ts:modelCatalog/compactCatalog/schemaSummary/OFFERED`, `protocol.ts:splitReply/parseFence/EnvelopeStream/initialStream`, `lib/safety.ts:canSet/requestBody`). Several of those (the `protocol.ts` envelope stream, `modelCatalog`) look like backend/model-prompt plumbing waiting for a caller (see FE-005).
Action: A for the truly unused after a second grep; C for the test-only protocol pieces. Risk: low.

**FE-004** | Duplication / consistency rot | Medium | HIGH | L
Two generative-UI stacks run side by side. Old: `components/genui/*` + `lib/genui/*`, dispatched per block kind in `BlockView.tsx:15-27` (form, table, chart, comparison, task_plan) with its own zod specs, its own `useAutosave` (`/v1/blocks/<id>/{state,live}`). New: `src/gen/*` document renderer (`BlockView.tsx:12-13`, kind `document`). `gen/legacy.tsx` is a read-only adapter that renders old table/chart/comparison cards through the new registry, invoked from `components/genui/Cards.tsx:4`, so `BlockView` -> `Cards` -> `gen/legacy` -> `gen/Renderer` is a three-hop chain for historical cards. Both are live (task_plan and form still use the old path). Two `Block`-ish type families, two sets of tests (`components/genui/blocks.test.tsx`, `gen/*.test.*`).
Git: 07fd6b9 "Replace generative UI with discoverable registry and durable artifacts", ef2a8ac.
Impact: every genui change must be made twice or checked in both; double zod validation.
Action: E/B plan to migrate form + task_plan to `gen` and keep only the legacy adapter. Risk: medium (plan editing/launch semantics; backend `/v1/blocks/*` contract).

**FE-005** | Contract duplication | Medium | MEDIUM | M
The block/component registry exists in the frontend (`gen/registry.ts`, `gen/manifest.ts`, `gen/catalog.ts`, header comment says "Only `implemented` entries are ever shown to the model" and `modelCatalog()/compactCatalog()` exist) and the backend exposes `GET /v1/genui/registry` (`urls.py:59`, `gen.component_registry`) which the frontend never calls (`grep genui/registry lumina/src` is empty). Backend also validates documents server-side (commit a7bdfae). Two sources of truth for schemas/catalog with no cross-check in the frontend tests that I could find.
Action: lead to diff backend `genui` schema list against `gen/schemas.ts` `IMPLEMENTED_TYPES`; E (single source). Risk: model prompt drift.

**FE-006** | Duplicate client / consistency | Low | HIGH | S
Raw `fetch` bypassing `api()` (no CSRF, no 401 broadcast, no timeout): `state/data.tsx:62` (`/readyz` probe, fine), `pages/Login.tsx:17` (`/v1/signup/config`, fine), `gen/components/model.tsx:12` (GLB fetch, `credentials:'same-origin'`), `components/LiveScreen.tsx:33` (frame fetch, `credentials:'omit'`, ticket in query string). A 401 in the GLB or frame fetch will not sign the user out. Also `api.ts:14-17` `token()` does not check `res.ok` and caches `csrf_token` even if undefined (re-fetched next call, header sent as "undefined" once); `resetCsrf()` is only called on login/logout/signup, so there is no CSRF-failure retry. LOW confidence this matters (depends on backend CSRF rotation).
Files: `lumina/src/lib/api.ts:12-30`.
Action: B/F minor hardening. Risk: low.

**FE-007** | Streaming design | Informational/Medium | HIGH | -
There is no SSE/WebSocket/EventSource anywhere (`grep EventSource` empty in both apps). All "streaming" is polling: chat thread 2.5 s while working (`Chat.tsx` effect with `setInterval(...,2500)`), global `/v1/app`+`/v1/requests`+`/v1/conversations` every 3 s when any task is active else 15 s (`state/data.tsx:50-54`), per-task events `after=<cursor>` at 2.5 s (`AgentThinking.tsx:33`), 1.5 s (`lib/useActivity.ts:23`), 4 s (`Tasks.tsx:19`), 2 s (`ActivityPanel.tsx:27`), plus `/readyz` every 30 s. Live view is a loop of long-poll `fetch` of JPEG frames with a short-lived ticket (`LiveScreen.tsx:27-45`), decoded via `createImageBitmap` to a canvas, falls back to `<img>` snapshots after repeated failure. The cursor-based events API is sound; only `data.tsx`, `LiveScreen` and `gen/components/context.tsx:96` pause when the tab is hidden. `AgentThinking`, `useActivity`, `Tasks`, `ActivityPanel`, `Chat` polling continue in background tabs.
Impact: request volume per active tab is roughly 5-8 req/s peak across overlapping pollers (my estimate from the intervals; not measured). Action: C/E (SSE or a single multiplexed poll), cheap win is visibility-pause. Risk: low for the pause.

**FE-008** | Performance (client + backend load) | Medium | HIGH | S
Overlapping pollers fetch the same data: while a task runs, `Chat.tsx` reloads `messages` + `blocks` + `conversations/<id>` + the list every 2.5 s AND `DataProvider` reloads `/v1/app`+`/v1/requests`+`/v1/conversations` every 3 s AND `AgentThinking` polls events. `Chat.reload()` also calls the provider `refresh()` and `refreshChats()` (`Chat.tsx` `reload = ... loadThread; loadList; refresh`), so `/v1/conversations` is requested by at least 3 paths. `Chat.tsx` uses `JSON.stringify` compare (`same()`) on the whole task/block arrays every tick.
Action: B consolidate. Risk: low-medium (freeze/scroll regressions noted in the comment at `Chat.tsx:21`).

**FE-009** | Performance | Low | HIGH | S
N+1 file listing: `Chat.tsx:71-72` and `Files.tsx:18-19` call `GET /v1/projects` then `GET /v1/projects/<id>/files` for every project, and `Chat.tsx` repeats this every time `msgs.length` or `working` changes (effect deps at `Chat.tsx:76`). Limit is `max_projects` from `/v1/app`. Action: ask backend for a single endpoint. Risk: low.

**FE-010** | Security hygiene (positive + residual) | Low | MEDIUM | -
Auth is a same-origin cookie session; CSRF token held only in a module variable (`api.ts:2`), never in storage. localStorage holds only UI prefs (`lumina.reducedMotion/compact/sidebar`, `lumina.<answer style key>`; fork adds theme, film pause, card ticks); sessionStorage holds message drafts under `lumina:draft:*` and is cleared on 401/logout (`state/data.tsx:36,75`; `lib/drafts.ts`). No `dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function`, `window.open` in `lumina/src` (grep, excluding vendor/tests; `window.location.assign` for downloads at `gen/ChatBridge.tsx:58`). Generated content is filtered in `gen/safety.ts` (no HTML-ish text, no bidi/control chars, http(s) only without credentials, internal route allow-list, relative file paths); GLB loader blocks external resources (`model.tsx:15`). Residual: (a) live-frame ticket and `?path=` are in URLs (query strings end up in access logs; ticket is short-lived) `LiveScreen.tsx:33`, `ChatBridge.tsx:58-59`; (b) `safeAssetSrc` default base `/v1/files/content?path=` has no backend route (urls.py has no `files/content`) and the function is unused, so the safe path for assets is the `genui/artifacts/<id>/asset` route instead; (c) markdown link filter `safeResponseUrl` is in `AgentResponse.tsx` and only self-used; reviewed names only, not the regex. Mermaid `securityLevel` setting not found by grep (`gen/components/mermaid.tsx`); LOW confidence, should be confirmed.
Action: F verify mermaid config and remove `safeAssetSrc`'s dead default. Risk: low.

**FE-011** | Exposure of internal tooling | Low | HIGH | S
`/app/gen-gallery` (`App.tsx:28`) ships in the production bundle (lazy chunk) and is reachable by any signed-in customer. Uses a sandbox host, no network, so privacy risk is low, but it is a dev surface and exposes the full block inventory including `planned`/`unsupported` entries.
Action: C (gate behind env/feature or dev flag). Risk: none.

**FE-012** | UX consistency rot | Low | HIGH | S
Index route `/` renders `Chat`, while the nav item "Home" points to `/home` (`Sidebar.tsx:10`). The placeholder pages (`Info.tsx:12`) link "Back to Home" to `/`, which is Chat, not Home. `Shell.tsx:52` shows the Rail only on `/home` and `/tasks*`. `Home.tsx` carries four marketing-style capability cards (`CAPS`) that are static. Also `Info.tsx` mixes four screens in one file and uses `any` for connections and usage.
Action: C. Risk: none.

**FE-013** | Type debt | Low | HIGH | S
`tsc --noEmit` passes in both apps. `as any`/`: any` is concentrated in the gen layer: `gen/components/extended.tsx` (27 occurrences), `gen/protocol.ts` (10), `gen/components/visuals.tsx` (9), `context.tsx` (6), `Gallery.tsx` (6), `constraints.ts` (5), `Renderer.tsx` (5), plus `createContext<...>(null as any)` in both providers and `api<T = any>` defaulting to `any` (`api.ts:19`), so every untyped `api()` call returns `any` (e.g. `Chat.tsx sent = (r: any)`, `Info.tsx useState<any>`). `@ts-ignore/@ts-expect-error/eslint-disable`: 5 occurrences in `lumina/src` (e.g. react-hooks disable at `gen/ChatBridge.tsx:39`). No ESLint or Prettier config exists in either package (no lint script in package.json), so hook-dependency mistakes rely on review.
Action: B/E incremental. Risk: low.

**FE-014** | Dependency debt | Low | HIGH | S
Declared vs imported: every dependency in `lumina/package.json` is imported (react-markdown/remark-gfm in AgentResponse and gen text, katex in gen math, mermaid in gen mermaid, three + R3F in Globe and gen model, zod, router, inter font). `@types/katex` used. In `lumina-character`, katex/mermaid are absent (matching its older code). Drift: `react-markdown` and `remark-gfm` use `^` ranges while everything else is exact-pinned; fork versions differ from lumina (see FE-001). `three/examples/jsm` loaders import via `gen/components/model.tsx` (lazy?) not verified. Bundle: Vite `chunkSizeWarningLimit: 900` (`vite.config.ts:8`) suggests large chunks (three + mermaid + katex); `sourcemap: false`. Action: B. Risk: low.

**FE-015** | Test coverage vs churn | Medium | MEDIUM | M
Counted since 2026-09-01 (46 commits touching `lumina/`): hottest files are `styles/app.css` (29 commits), `pages/Chat.tsx` (21), `Composer.tsx` (11), `Shell.tsx` (10), `pages/Info.tsx` (8), `lib/api.ts` (8), `pages/Home.tsx` (7). Chat, Composer, Shell, api, Live, Tasks, Sidebar, Rail have test files. Untested by name match: `state/data.tsx` (the global store with auth/401/poll logic), `App.tsx` routing, `pages/Info.tsx` (Settings, Integrations), `pages/Home.tsx`, `pages/Login.tsx`, `pages/Files.tsx`, `pages/History.tsx`, `components/ActivityPanel.tsx`, `LiveTerminal.tsx`, `Globe.tsx`, `gen/ChatBridge.tsx` (the bridge to ~9 backend endpoints), `components/genui/useAutosave.ts` and `FormBlock.tsx`. Many `gen/` and `genui/` files are covered by aggregate test files (`gen.test.ts`, `gen.components.test.tsx`, `blocks.test.tsx`, `Safety.test.tsx`) so name-matching undercounts. No `skip`/`todo` tests found in `src` or `tests`. Layout is verified only by manual Python/Playwright fixtures (`AGENTS.md` says jsdom is insufficient). I did not run the suite, so pass state is UNVERIFIED.
Action: B add tests for `state/data.tsx` and `ChatBridge`. Risk: none.

**FE-016** | God-component risk (density) | Low | MEDIUM | M
No file exceeds ~250 TS lines, but `Chat.tsx` (21 commits, 11.8 KB) owns thread loading, caching, polling, scroll stick, activity panel, file chips, rename, regenerate chips, and block anchoring in one component with 15+ refs/state hooks; `Composer.tsx` (11.3 KB) holds template menus, respond-mode menus, goal toggle, attach, draft storage. `app.css` is a single 41 KB sheet edited in 29 commits (merge-conflict magnet), alongside `ui.css`, `tokens.css`, `safety.css`, `gen.css`. Action: E split when next touched. Risk: low.

**FE-017** | Docs drift | Low | MEDIUM | S
`lumina/AGENTS.md` and `lumina-character/AGENTS.md` are near-identical (same UI rules, same `tests/preview_chat.py` fixture), and the fork copy still describes things lumina removed. `platform/UI_CONTRACT.md:10` calls `ui-reference` "about 120 lines"; actual is 94 lines (minor). `lumina/src/components/safety/README.md` is the only per-module README. `docs/architecture/findings.md` F-17 says "the reverted Lumina app": the working tree has since re-added a safety console but not the question/vault UI (FE-002). Action: G.

**FE-018** | Reference client | Low | HIGH | S
`platform/ui-reference/app.js` is a standalone plain-JS client that duplicates `api()`; if the backend CSRF or error shape changes it will drift silently because nothing builds or tests it. Backend `uishell` only serves a bundle dir, and nothing points to `ui-reference`. Action: C (keep as docs, or delete after verification). Risk: none.

**FE-019** | Uncommitted / in-progress overlap | Informational | HIGH | -
`git status` shows no modified files under `lumina/`, `lumina-character/` or `platform/ui-reference/` (in-progress work is backend: tool_origin, tool_relay, cell_bridge, e2e harness). Only untracked item in scope is the `lumina-character/node_modules` symlink.

**FE-020** | Backend routes with no frontend caller in `lumina` (leads for the lead) | Informational | MEDIUM | -
Heuristic (last path segment not found in `lumina/src` source): `auth/activate`, `auth/revoke-sessions`, `v1/saved/<f>/forget`, `v1/assistant/presence`, `v1/account/telegram/unlink`, `v1/account/connections/callback`, plus webhooks and `internal/accounts/*` (expected: not UI). `/v1/genui/registry` (FE-005) and `/v1/browse/<id>/answer`, `/v1/vault*`, `/v1/saved*`, `/v1/media/<id>` are only called from the fork. See Cross-scope links. Crude name matching; confirm each.

## Looks bad but is fine

1. `api<T = any>` and `null as any` contexts look sloppy but `tsc` passes and the contexts are always provided by `main.tsx`; the real exposure is untyped responses (FE-013), not a crash.
2. 15 empty `catch { /* keep last list */ }` blocks in pages/components: each is an intentional "keep the last good data" for polling reads (comment on the line); writes use `setErr(...)` instead. Not swallowed errors in the harmful sense.
3. `gen/legacy.tsx` and `Cards.tsx` indirection looks like dead adapter code but it is the live path for rendering old stored table/chart/comparison blocks in existing conversations (`Cards.tsx:4`); do not delete.
4. `canonical()` in `lib/path.ts` redirecting any non-`/app` path looks hacky but exists because the edge can serve the app at `/` while the router has `basename="/app"`; documented in the comment and tested (`lib/path.test.ts` is in the fork; lumina covers via `main.tsx` call).
5. Two copies of nearly every file between `lumina` and `lumina-character` look like accidental duplication; it is an intentional frozen snapshot (tag `lumina-character-final`).
6. `credentials:'omit'` on the live frame fetch: deliberate, the frame endpoint authenticates with a ticket in the query string, so cookies are not sent.
7. `data.tsx` polls `/readyz` from the browser; it is a cheap health badge, not a leaked internal endpoint (proxied in `vite.config.ts:9`).

## Cross-scope links

- Frontend `/v1/...` and `/auth/...` call map (method, caller). All paths below matched a `path()` in `platform/accounts/urls.py` by my normalising script, except where noted.
  - GET `/v1/csrf` `lib/api.ts:15` (also `ui-reference/app.js`); GET `/v1/app` and `/v1/requests` `state/data.tsx:31`; GET `/v1/conversations` `state/data.tsx:43`, `History.tsx:15,22` (q, archived, limit, offset); POST `/v1/conversations` `Composer.tsx:25`; GET `/v1/conversations/<id>` `Chat.tsx:44`; GET `.../<id>/messages?after=` `lib/conversations.ts:9`; GET `.../<id>/blocks` `Chat.tsx:43`, `gen/ChatBridge.tsx:45`; POST `.../<id>/send` `Composer.tsx:84`, `Chat.tsx:83`, `ChatBridge.tsx:54` (body: message, key, mode, ui, goal); POST `.../<id>/{rename,archive,restore}` `ChatActions.tsx:11`, `Chat.tsx:79`; POST `.../<id>/goal` `Tasks.tsx:39`.
  - GET `/v1/tasks/<id>` `Tasks.tsx:44`; GET `/v1/tasks/<id>/events?after&limit` `AgentThinking.tsx:23`, `useActivity.ts:17`, `Tasks.tsx:18`; GET `/v1/requests/<id>` `ChatBridge.tsx:71`; POST `/v1/requests/<id>/{cancel,pause,resume,retry}` `Chat.tsx:77`, `Tasks.tsx:22-32`, `Live.tsx:76`, `ChatBridge.tsx:56`.
  - Browse: GET `/v1/browse/<id>?since` `Live.tsx:29`, `ActivityPanel.tsx:24`; POST `/v1/browse/<id>/live` (ticket) `LiveScreen.tsx:30`; then GET `<ticket.path>?t&after&now` (path supplied by backend; returns 200 JPEG with `X-Seq`, 204 none, 403 expired) `LiveScreen.tsx:33`; POST `/v1/browse/<id>/control` `Live.tsx:56`; POST `/v1/browse/<id>/{pause,resume,release}` `Live.tsx:65`; GET `/v1/browse/<id>/shot/<file>` `Live.tsx:79`, `ActivityPanel.tsx:26`. Chain crosses browse runner -> live gateway -> Caddy per CLAUDE.local.md.
  - Blocks: POST `/v1/blocks/<id>/{state,live}` `useAutosave.ts:19`; `/{submit}` `FormBlock.tsx:42`; `/{launch,phase,stop}` `PlanBlock.tsx:114-122`, `ChatBridge.tsx:55`. GenUI artifacts: POST `/v1/genui/artifacts/<id>/state` `ChatBridge.tsx:52`; `/events` `:53`; `/diagnostics` `diagnostics.ts:10`; GET `/v1/genui/artifacts/<id>/asset?path=` (`ChatBridge.tsx:58-59`, navigation/img src).
  - Files: GET `/v1/projects` `Files.tsx:18`, `Chat.tsx:71`; GET `/v1/projects/<id>/files` `Files.tsx:19`, `Chat.tsx:72`; POST `/v1/projects/<id>/bundle` `Files.tsx:26`; POST `/v1/artifacts/<id>/versions/<v>/ticket` `Files.tsx:9`.
  - Safety: GET `/v1/safety[?scope=all]` `lib/safety.ts:58`; POST `/v1/safety/change` `:63`; GET `/v1/safety/access` `:67`; POST `/v1/safety/access/change` `:70`.
  - Account: GET `/v1/account/connections` `Info.tsx:23`; GET `/v1/costs` `Info.tsx:35`; GET `/v1/signup/config` `Login.tsx:17`; POST `/auth/login` `data.tsx:71`, `/auth/logout` `:75`, `/auth/signup` `Login.tsx:32`, `/auth/signup/verify` `:20`; GET `/readyz` `data.tsx:62`.
  - Not matched in urls.py: `/v1/files/content` (`gen/safety.ts:44`, default arg of unused `safeAssetSrc`). Everything else flagged "MISS" by my script was a template-literal artefact and verified by hand against the route list (`blocks/<id>/{live,state,stop,phase,launch,submit}`, `browse/<id>/{pause,resume,release}`, `conversations/<id>/{archive,restore,rename}`, `requests/<id>/{pause,resume}`, `messages`).
- Fork-only calls (not made by lumina): `/v1/browse/<id>/answer`, `/v1/vault`, `/v1/vault/add`, `/v1/vault/<id>/delete`, `/v1/saved`, `/v1/saved/<f>/forget`, `/v1/assistant/presence`, `/v1/media/<id>`.
- Frontend `AppInfo.features` flags consumed: `execution`, `browse`, `files`, `uploads`, `connectors`, `billing_mode`. Declared but unused in lumina: `chat`, `telegram`, `requests`, `usage` (`lib/api.ts:44`). Backend should confirm these keys still exist in `/v1/app`.
- Response-shape contracts the frontend relies on that backend scope should confirm: `/v1/conversations/<id>/messages` -> `{messages, tasks}`; `/v1/browse/<id>` -> `{events,status,question?}`; live ticket -> `{ticket,path,expires_in}`; error JSON `{error,category,detail,field_errors}`; block `{id,kind,schema_version,status,run_status,anchor_message_id,version,spec}`.
- Static serving: `vite.config.ts` `base:'/app/'`, built to `lumina/dist`, backend `platform/accounts/uishell.py` serves `AGENTAI_UI_BUNDLE_DIR` at `/app/` (header comment). Where that dir is populated in deploy was not checked (outside scope).
- Dev proxy targets `127.0.0.1:18800` for `/v1`, `/auth`, `/readyz`.

## Open questions for the maintainer

1. Is `lumina-character` ever deployed, or is it purely an archive? Should the 61 MB of scene assets stay in the main repo history?
2. Does the backend still put browser runs into an `asking` state for the customer? If yes, who answers it now that `lumina` has no UI for `/v1/browse/<id>/answer` (FE-002)?
3. Is vault/saved-info (`/v1/vault*`, `/v1/saved*`) coming back in `lumina`, or should the backend routes be retired?
4. Which generative-UI path is the target: finish migrating `form` and `task_plan` into `src/gen`, or keep both (FE-004)? Is `/v1/genui/registry` meant to be consumed by the frontend?
5. Should `/app/gen-gallery` be reachable by customers in production?
6. Are Calendar/Automations/billing/Telegram UIs planned (backend routes exist) or deliberately backend-only for now?
7. Is polling an accepted long-term streaming design, or is SSE planned?
8. Mermaid `securityLevel` and the markdown link filter: has either been security-reviewed (I only read names)?
