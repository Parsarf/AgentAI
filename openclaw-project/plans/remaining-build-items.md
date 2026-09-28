# Remaining build items — inventory (Phase 7, 2026-09-27)

Fields per requirement: requirement / existing evidence / implementation gap /
chosen native mechanism / dependencies / status / later test case.
Statuses: DONE, PARTIAL, GAP (implementation missing), DEFERRED-OWNER,
PENDING-OWNER (decision/credential), BOUND (documented limit, not a gap).

## 1. Independent review path (ACP reviewer)

- Requirement: independent harness reviews build snapshots without builder
  context.
- Evidence: cached ACP Claude adapter/SDK present on server (phase 4 log);
  no paid review has run.
- Gap: reviewer route admission + isolation not activated; reviewer auth
  route (proxy vs saved profile) undecided at activation time.
- Mechanism: `openclaw acp` bridge with claude-cli backend; reviewer gets
  read-only snapshot + separate scratch; fresh session per review.
- Dependencies: owner resume of testing (budget), reviewer admission probe.
- Status: **GAP** (config prepared, not activated).
- Test: `T10-INDEPENDENT-ACP-REVIEW`.

## 2. Native coding / browser worker

- Evidence: main delegated native board build, 7 tests + smoke pass; debug
  ID-0 regression reproduced/fixed 4/4 (phase 4, owner-preserved artifacts
  at `work/phase4/`); pinned browser sidecar built; isolation probes passed.
- Gap: real browser-worker flows on the built app and independent review
  unrun (owner deferred); ChatGPT quota was exhausted at the time.
- Mechanism: existing native Codex harness + browser sidecar; no new build.
- Status: **PARTIAL** (implementation present, verification deferred).
- Tests: `T10-NATIVE-BUILD-BOARD`, `T10-BROWSER-FLOWS`,
  `T10-INDEPENDENT-ACP-REVIEW`.

## 3. Memory, goals, cancellation, durable conventions

- Evidence: phase 5 applied 15 config paths — main-only memory + native goal
  tools, worker denials, explicit owner timezone; attributed memory
  rules/note files exist.
- Gap: selective recall/correction/deletion and cancel/resume conventions
  never exercised; no managed workflow controller exists in this runtime —
  autonomous resume is explicitly NOT configured (owner-driven only).
- Mechanism: native memory/goal tools + session state; receipts stay in
  native session/session-state records. No second scheduler built.
- Status: **PARTIAL** (config live, behavior unverified).
- Tests: `T10-MEMORY-SELECTIVE-RECALL`, `T10-MEMORY-CORRECTION-DELETION`,
  `T10-DURABLE-RESUME-CANCELLATION`.

## 4. Scheduler limits and admission boundaries

- Evidence: scheduler capacity is fixed at 8 in the installed runtime;
  a concurrency-1 setting was tested and is **unsupported** (phase 5).
  Currently 4 enabled weekly jobs.
- Gap: none implementable without patching the runtime (refused).
  No exactly-once effect is claimed anywhere.
- Status: **BOUND** (documented).
- Test: `T10-SCHEDULING-ADMISSION`.

## 5. Personal integrations (Phase 6 base)

- Evidence: connector manager on VPS (`integrations/manage-connectors.py`) +
  Mac `bin/connect-tool` + `CONNECT_TOOLS.md`; Google (read-only
  Gmail/Calendar/Drive) and GitHub (read-only) adapters registered, both
  **disabled pending authentication**; workspace-mcp image pinned.
- Gap: owner account sign-in deliberately deferred; nothing to implement.
  Protected sign-in instructions = `CONNECT_TOOLS.md` (owner performs).
- Status: **DEFERRED-OWNER** (base DONE, auth pending).
- Tests: `T10-INTEGRATION-AUTH-FAIL-CLOSED` (disabled connectors deny),
  owner sign-in acceptance belongs to owner setup + Phase 10.

## 6. Backup & recovery operations (this phase)

- Evidence: historical pre-change archives (324 MB, 0700) + one LiteLLM
  dump; no schedule, no freshness reporting, no isolated-restore tooling
  before this phase.
- Implemented now: nightly native-verified archive + LiteLLM pg_dump, host
  systemd timer, freshness report, isolated restore/rollback entry points.
- Gap: **off-host encrypted retention pending owner** (destination +
  key custody); restore drill + scheduled-fire observation are Phase 10.
- Status: **DONE** (build) / `T10-OPS-*` tests pending; off-host
  **PENDING-OWNER**.

## 7. Runtime housekeeping observations (no action this phase)

- Two old sandbox containers report `unhealthy` (image `62832668e3e5`, up
  22 h) and five more idle sandboxes — runtime-managed; candidate for a
  later cleanup pass only, not required for operations.

## 8. Unrun checks that are NOT implementation gaps

Gate 1–3 pending checks, budget-cap live denials, DB-outage fail-closed,
security/budget proof suites: implementation exists and is config-verified;
the checks are deferred to Phase 10 by owner direction. Tracked as eval
cases, not build items.

## 9. Browser optimization transport + TypeSafe account (added Phase 9)

- Requirement: let the disabled Jev adapter receive calls from the
  browser-worker flow without weakening worker isolation.
- Evidence: adapter + tests + fixtures built and green offline
  (`browser-opt/`); no provider account exists.
- Gap: (a) transport — workers are sandboxed without network and main is
  web-denied, so a host service / bridge-IP allowlist / native plugin path
  needs its own isolation review; (b) owner TypeSafe account, data-handling
  decision and separate spend controls (Anthropic proxy and ChatGPT do not
  cover it).
- Mechanism: keep adapter server-side; wire transport after review.
- Status: **PENDING-OWNER** (account) / **GAP** (transport review).
- Tests: `T11-*` cases in `evals/cases.yaml`.

## 10. Search for researcher (added 2026-09-28)

- Requirement: give the Claude researcher working web search.
- Evidence: Brave is rejected as a native `web_search` provider in this build.
  The owner selected Brave MCP. The official pinned MCP image is connected via
  the Phase 6 base, exposes only `brave_web_search`, and reads a private mounted
  key file. MCP doctor, direct API search, and a researcher agent turn passed;
  the agent receipt names `brave-search__brave_web_search`.
- Status: **DONE** for researcher search. Native `web_search` remains a
  separate unsupported Brave path in this build.
- Later test: T10 research case with discovery by Brave MCP search.
