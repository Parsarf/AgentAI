# Incomplete and in-progress features

Audit date 2026-10-29, branch `product-phases-6-11`, HEAD `03662de`. Production UNVERIFIED (no SSH/network; repo runbooks target IONOS 69.48.206.62 while the owner's SSH config names a different host, L-01). Feature IDs refer to `FEATURE_INVENTORY.md`.

For each feature: what exists, what is missing, the decision needed from the owner, and blockers. Owner priority recorded in memory: customer privacy and data-leak prevention over new task limits; items are ordered with that in mind where relevant.

## Summary

| # | feature | inventory | state | priority hint |
|---|---|---|---|---|
| 1 | Browser question UI + vault / saved-info UI | F-022, F-023 | UI missing in shipping app | High (customer-visible stall, conditional) |
| 2 | Native browser rollout | F-040, F-039 | built, gated off by default | High (privacy, reliability) |
| 3 | Tool-origin v2 | F-041, F-038 | IN-PROGRESS, uncommitted, claimed deployed | High (provenance) |
| 4 | Consent gate for browser optimisation (TypeSafe) | F-031, F-037 | gate built, not wired | High (privacy, M-02) |
| 5 | Telegram | F-025 | broken wiring | Medium |
| 6 | Connectors / OAuth | F-026 | inert | Low until product commits |
| 7 | Billing UI and live payments | F-015, F-016 | backend in test mode | Medium |
| 8 | Calendar / automations / schedules / memory / watchers / skills | F-029, F-028, F-030 | locked or orphaned | Product decision |
| 9 | Retention | (BE-011) | command exists, never scheduled | Medium (privacy) |
| 10 | SSE task stream | F-034 | built, unused, risky | High if left reachable |
| 11 | Operator API | F-027 | unreachable by design | Low |
| 12 | Phases 16-19 | OP-014 | not started | Owner go needed |
| 13 | Release marking / provenance | F-056 | tags stopped | Low effort |
| 14 | Other open threads | various | see end | |

## 1. Browser question UI and vault UI (FE-002, FEAT-FE-05/06, GH-009)

- Exists: backend routes `/v1/browse/<id>/answer`, `/v1/vault`, `/v1/vault/add`, `/v1/vault/<id>/delete`, `/v1/saved`, `/v1/saved/<field>/forget`; `ASK_SECONDS` 300 and pause/takeover limits in `browse/service.py:93,384-386,292`; vault AES-GCM with per-account HKDF key and AAD-bound rows (`vault.py`); `0023_saved_choices.sql`; server-side memory/vault labels injected into prompts (`chat_driver.py:262-278`). Full UI exists only in `lumina-character` (`useBrowseQuestion.ts:10-23`, `Live.tsx:84`, `SavedInfo.tsx`, `AskBox`, `QuestionPanel`).
- Missing: any caller in `lumina/src` (`grep answer`, `vault`, `saved` empty); the shipping `Live.tsx:129` and `lib/live.ts` have no answer path. A browser run that stops to ask the customer has no screen (assuming the backend still reaches `asking`; reconciliation rates impact HIGH but confidence MEDIUM). Switch `credentialed_browsing` also needs fact `login_flow` ("not yet").
- Decision needed: (a) port `useBrowseQuestion` + `AskBox` into `lumina` (class D), or (b) make the backend stop emitting the state, or (c) retire `/v1/vault*` and `/v1/saved*` (C). Is vault/saved-info coming back (FE open question 3)?
- Blockers: no test that confirms the `asking` state is reachable; VPS not verified. `PARK_LIMIT` does not end a parked run (AG-005), so a stalled question holds the global slot until the browse service times out (about 300 s / 600 s).
- Preserve until decided: do not delete the backend routes or the fork's components.

## 2. Native browser rollout (AG-013, GH-004, IS-012, M-08)

- Exists: `native_runner.py` (435 lines), `native_scripts.py`, bridge `browser.*` methods (`cell_bridge.py` BROWSER_METHODS), per-account gate `/etc/agentai-supervisor/browse-engine.json` (default `runner`; `service_main.py:92-101`), `native-wiring.example.json` (`native_browser:false`), plan `docs/architecture/native-browser-plan.md`, e2e tests (`tests/e2e/test_native_browser.py`, need Chrome). Repo evidence on 27 Oct: an OOM canary reverted an account to the runner (`evidence/deployments/20261027T114539Z-cancel-e700e33/deployment.json`).
- Missing: the eval gate and cutover; deletion of `runner.mjs`, the host stage and `stage_argv`; CI coverage of e2e (needs OpenClaw package + Chrome; skips on Linux CI, AG-017/ST-017); a shared test vector for the SSRF policy (DUP-01); the `native_runner.py` docstring still says the runner is "retired" (AG-016).
- Decision needed: who owns the eval gate and the cutover date; which accounts (if any) run native in production (UNVERIFIED); keep both engines long term or not.
- Blockers: VPS read of `browse-engine.json`; sustained memory behaviour of the native browser (OOM canary); IS-013 root-unit hardening not yet done for browse/bridge.

## 3. Tool-origin v2 (IN-PROGRESS, uncommitted) (AG-006, AG-008, AG-019, FEAT-AG-20)

- Exists (working tree, not committed): modified `tool_relay.py`, `commands/tool_relay.py`, `lifecycle/{cell_bridge,cell_config,tool_origin}.py`, `tests/e2e/{harness,stub_model,test_native_e2e}.py`, `test_browser_tool.py`, `test_tool_origin.py`; new `lifecycle/tool_origin_install.py`, `lifecycle/tool_origin_plugin/`, `tests/tool_origin_plugin.test.mjs`, `docs/browser-tool-ownership.md`, `evidence/browser-ownership/`. The untracked doc says release `20261028T212308Z-tool-origin-v2` is live and verified by manifest.
- Missing: a commit; CI coverage of `tool_origin_plugin.test.mjs`; a differentiated refusal message (transient bridge errors currently tell the model "Do not retry this call in another task", AG-008); an event when hook install fails (`cell_config.py:183-188` swallows on restart, `:309` is unguarded on creation); `docs/browser-reliability.md` "Trust boundary" still describes the superseded reader. Optional hardening: proof-file owner check (AG-019, LOW).
- Decision needed: commit and tag the deployed tree; confirm what is actually running (AG-006 open question 4).
- Blockers: production state unknown; if the claim is true, production runs code without a commit and rollback depends on a manifest outside git. This audit did not judge the diff.

## 4. Browser optimisation consent gate (AG-002, AG-003, IS-014, M-02)

- Exists: owner switch `browser_optimization` ("page text and element labels are sent to TypeSafe", `switches.py:42-49`, needs fact `browser_route_deployed` "not yet"); four-layer `OptimizationGate` (`optimization.py`, header says DISABLED); `personal_data_scrub` switch; text scrub in `privacy.scrub`. Live browse path uses TypeSafe if the key file exists and `--jev-mode live` (`service_main.py:37,52,72-77`); only `browse_tasks` stops it.
- Missing: the gate is not on the live path; images (base64 JPEG screenshots) are sent on every step whenever `look.shot` is set (`loop.py:208-216`, `ladder.py:333,397,606`) and pixels cannot be scrubbed; the switch text and `plans/product/privacy.md:17` mention only text/labels; trace files keep up to 400 chars of raw model answer (`ladder.py:623`).
- Decision needed (class C): wire `browser_optimization` into `jev_for`, or send images only for pages with no listed controls or on opt-in, or document and obtain customer terms; retire the switch if abandoned. Whether the TypeSafe key exists in production is UNVERIFIED.
- Blockers: changes JEV accuracy on covered pages; enforcing the switch may disable JEV until the owner confirms.

## 5. Telegram (BE-007, FEAT-BE-13, FEAT-FE-15)

- Exists: `telegram.py` ingress/outbox, `accounts/telegram.py` bindings/link/unlink/webhook (shared-secret header, `hmac.compare_digest`), `telegram_worker --drain/--check`, `bin/activate-telegram.py` (registers webhook only), settings for token/secret/username (names only), tests that inject `FixedRoute`.
- Missing: shared `ChatService` factory with pricer/gateway/service limit (so messages currently wait unfunded and fail); a relay of the assistant's result to Telegram (`rg telegram chat_driver.py` = 0 hits); a unit or timer for `telegram_worker --drain`; any React UI (only a type declaration, `lib/api.ts:44`); real bot linking deferred (phase 7 F5).
- Decision needed: ship (needs factory fix DUP-02, result relay, drain unit) or hide behind the switch and remove the dead UI hooks. Same question applies to ops alerts (Telegram token for `/etc/agentai-ops/telegram-token` is a separate path, IS).
- Blockers: owner decision; real bot token/webhook secret (names only recorded); the privacy implication of sending assistant output to a third party.

## 6. Connectors / OAuth (BE-008, FEAT-BE-14, FEAT-FE-12)

- Exists: `connectors.py` (544 lines; PKCE, custody, drafts for Gmail, Calendar, Drive, GitHub), good tokens-in-custody design, `accounts/connections.py` list endpoint, switch `connectors_linking`.
- Missing: providers (service built with none and `DisabledCustody`, so link answers 503); `link()` discards `authorize_url` and returns `connector_not_configured`; `callback` is a stub; callback URL hard-coded to `https://getlumina.pro` instead of `PUBLIC_ORIGIN`; `ssrf.check_url` does not pin the resolved address; no connect/disconnect UI (read-only list in `Info.tsx`); phase 11 is "build complete offline, all services DISCONNECTED".
- Decision needed: whether and when connectors become a product feature (class C; preserve per BE-008). `bin/phase6/authorize-google.py` imports undeclared `mcp` (ST-006).
- Blockers: OAuth client credentials, scopes review (read-only Google scopes are the stated default), SSRF address pinning, UI.

## 7. Billing UI and live payments (FE-014, BE-004, BE-005, FEAT-BE-06)

- Exists: Stripe client, webhook inbox with signature check (300 s tolerance, dedup, canonical re-fetch, dead-letter backoff), checkout/portal with idempotency keys, 30 s sweep timer, access state machine, open-access sync, server-rendered `/account/billing/`. Plan data in `product/plan.json`.
- Missing: React checkout/portal UI (only a label); a daily `billing_worker --reconcile` timer (unit runs without the flag); exemption of `/v1/billing/webhook` and `/v1/telegram/webhook` from the 8192-byte body cap (`middleware.py:23`; a 413 makes Stripe retry then disable the endpoint); Stripe account and keys not created (LAUNCH.md item 2); phase 13 acceptance NOT_RUN; status wording in `plan.json`/`CONTRACT.md:3` ("not a live offer"); billing env names undocumented (BE-015).
- Decision needed: payments go-live date; UI scope; whether contract text should say "private beta".
- Blockers: owner Stripe setup; a >8 KB webhook test through the full middleware stack.

## 8. Calendar, automations, schedules, memory, watchers, skills, objectives (FEAT-FE-13, FEAT-BE-16/17, BE-014, AG-009)

- Exists: UI placeholders ("Soon") in `Info.tsx`; `/v1/schedules|memory|controls|integrations|exports|streams` return 503 `capability_not_enabled`; backend modules `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py`; tables in SQL migrations and `ops/restore.py:20` list; locked switch `customer_schedules`; owner-side `config/skills`, workspace templates, phase fixtures (hand-installed? UNKNOWN).
- Missing: wiring (no importer), UI, entry points, activation facts. Lumina-side memory/summarisation is not wired; conversation context lives in the OpenClaw session.
- Decision needed (class C): which are roadmap and which removable (BE open question 7). Do not remove while tests, tables and restore lists reference them.
- Blockers: product definition; scheduling needs a worker unit and the same privacy review as other background processing.

## 9. Retention (BE-011, privacy)

- Exists: `retention_accounts` management command that deletes `RateBucket`, expired `Session`, `ActionToken`, 180-day audit rows and 30-day `events`; browse screenshot purge at 24 h (documented).
- Missing: any unit/timer scheduling it (`deploy/README.md:83-85`: "No schedule/worker was installed this phase"); a real contract for `chat_messages` and `conversations` (never deleted; the help text promises "90-day product chat projection retention"; the 90-day cutoff uses `conversations.created_at`, so events of a still-active old conversation are removed); rate-bucket table grows without bound if no out-of-repo cron exists (UNVERIFIED).
- Decision needed (class C then F): define the retention contract; privacy is an owner priority. Also decide off-server backup (F1, a launch blocker) and key custody (IS-016).
- Blockers: VPS check for an out-of-repo cron.

## 10. SSE task stream (BE-002, FEAT-BE-18)

- Exists: `streams.stream` authenticated SSE generator (up to 45 s) and `/v1/tasks/<id>/events` cursor API (used by React).
- Missing: a client; a worker model that tolerates it (gunicorn `workers=1, class=sync, threads=1, timeout=15`; one SSE connection blocks the only worker and is killed at 15 s; the "3 streams per account" cap never applies because requests are serialized).
- Decision needed: remove or isolate `/stream`, or build SSE/WebSocket properly (class C/E). Quick win: visibility-pause polling (FE-007). Sonar flags it as `@csrf_exempt` (`accounts/streams.py:68`).
- Blockers: confirm no external client; check SQLite write contention (BE-013).

## 11. Operator API (BE FEAT-BE-15)

- Exists: `/internal/accounts/<a>/{invite,revoke,suspend,audit}` and deployment operations; requires TOTP-confirmed operator plus per-account grants; Caddy forwards only `/account /auth /v1 /app`, so it is loopback only. `export` and `impersonate` are always 403.
- Missing: a caller; the working operator path is the host CLI `account_admin` (and `signup_admin`, `onboard_trial`, `seed_trial`, `lifecycle_status`).
- Decision needed: keep as an internal API for a future console or retire it (class C). No exposure risk as configured. Preserve.

## 12. Phases 16-19 (OP-014)

- Phase 16 (optional optimisation evaluation): NOT started; paid benchmark needs owner go. Phase 17 (private beta), 18 (launch): NOT started per LAUNCH.md. Phase 19 (optional purchases): NOT started; browser purchasing locked (`credentialed_browsing`, F3; `final_phase.md`). No `plans/product/phase-16..19.md` exist; prompts live in `phase-prompts/` only.
- Phase 15 acceptance is PARTIAL (21 PASS, 2 BLOCKED, 7 NOT_RUN). Phases 10-11 activation BLOCKED/DISCONNECTED; phase 12 adapters DISABLED while docs disagree on JEV switch state (OP-015).
- Decisions needed: paid benchmark go, private-beta cohort and criteria, launch scope, purchases policy. `final_phase.md` lists deferred items F1-F13 (off-server backup F1, Claude Code agent F2, purchases F3, JEV routing F4, Telegram F5, others).
- Blockers: Stripe, off-server backup, privacy decisions (items 4, 9), VPS verification (L-01).

## 13. Release marking and provenance (GH-001, GH-005)

- Exists: tags `release/live1..live8`, `ui-pre-film`, `ui-parchment-v1`, `lumina-character-final`; `evidence/deployments/*`.
- Missing: tags for native1-4 and safety1; commit hashes in `RELEASE_NOTES.md`; `d95b796` is a 4,929-file commit so blame is lost; `BUILD_LOG.md` has no entry after 2026-10-12; `origin/product-phases-6-11` is 47 commits behind and `main` is stale (GH-013). Source custody: GitHub account suspended 14 Oct per `RELEASE_NOTES.md:151-155`; current status unknown (IS-017).
- Decision needed: confirm push status; tag deployed commits going forward; decide whether `origin/main` is what Vercel/CI deploys from.

## 14. Other open threads

| thread | what is missing | refs |
|---|---|---|
| Request leak on cancel of a WAITING request | settle reservation + close task in `RequestQueue.cancel`, revoked path, unfunded failure, plus sweep; test (M-01, HIGH, MEDIUM-HIGH confidence); blocks cell sleep and handover (AG-004) | BE-001, AG-001, BE-006 |
| Per-IP rate limits global behind Vercel (M-04) | real client IP at Caddy from a trusted source | BE-003, IS-009 |
| Observability | redacted structured logging (exception class, module, request id only) | BE-010, IS-008, ST-010 |
| CI | frontend, browse, `.mjs` tests, remaining about 53 platform modules not run; switch to `unittest discover` plus a lumina job (M-10) | ST-001, OP-009 |
| Monitor gaps | add `agentai-browse` to `REQUIRED_UNITS`; unit-vs-doc consistency test | IS-003, IS-024 |
| Cap on model calls/tool rounds | none; `_over_budget` fails open if the LiteLLM snapshot fails | AG-007 |
| Host hardening for root units (browse, bridge, supervisor-native) | `ProtectHome`, `PrivateTmp`, review `CAP_DAC_OVERRIDE` | IS-013 |
| Password SSH to root | key login not adopted; `sshd -T` unchecked | IS-002 (L-01 makes the target itself uncertain) |
| `/app/gen-gallery` in production bundle | gate behind a dev flag | FE-011 |
| Settings theme test deleted | restore a theme-default test | GH-015 |
| Frontend-only privacy items | verify mermaid `securityLevel` and markdown link filter | FE-010 |
| Unenforced plan limits | steps, model calls, searches, storage constants not found | OP-008 |
| Frontend: `AppInfo.features` keys `chat`, `telegram`, `requests`, `usage` declared but unused | confirm backend still emits them | FE |

## Evidence caveats

Nothing in this file has been verified against the running system. Coverage gaps: gateway/events/artifacts/storage/genui/routing/ops internals not deep-audited (BE); VPS state unseen (AG, IS); frontend tests not run (FE); the diff of the uncommitted work was read but not judged.
