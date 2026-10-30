# CLAUDE.md (PROPOSED, not installed)

Proposed for the git root `/Users/parsa/AgentAI/`. Based on the 2026-10-29 read-only audit (`docs/codebase-audit/`). Production is UNVERIFIED; do not state production facts as true.

## What this is
Lumina (getlumina.pro): hosted AI assistant. Customer SPA (`openclaw-project/lumina`) -> Django app (`openclaw-project/platform/accounts`) -> serial queue/worker -> OpenClaw cell (gVisor) -> relays for tools/browser. Overview: `docs/codebase-audit/SYSTEM_OVERVIEW.md`.

## Safety rules (read first)
- Privacy over new task guardrails. Focus security work on data leakage and customer privacy.
- Never print, cat, read, or copy secret values (`.env`, `ssk-key*`, `*.key`, `/etc/*` secret files, key files). Names and modes only.
- Never `git add -A` or `git add .` at the root until `ssk-key*` is ignored. About 800 MB untracked clutter and `lumina-cost-audit/` (owner browsing logs) sit un-ignored. Stage by explicit path.
- Production is unverified. Repo docs name an IONOS host; the owner's SSH config names a different one (L-01). Do not SSH or deploy without the owner's explicit say-so.
- Uncommitted tool_origin / tool_relay / cell_bridge / cell_config work is IN PROGRESS. Do not "fix" or revert it.
- Do not delete orphan modules (see debt); they are unfinished product features (class C/G).
- Do not touch `platform/migrations/*.sql` once applied (checksummed; edits break `/readyz`). Add a new numbered file.

## Canonical structure
- `openclaw-project/platform/accounts/` Django HTTP layer; `urls.py` is the route table.
- `openclaw-project/platform/agentai_platform/` all services (chat, request_queue, budget, billing, browse/, lifecycle/, genui/, ops/, routing/).
- `openclaw-project/lumina/` the ONLY live frontend. `lumina-character/` is a frozen fork: never edit it for product work.
- `openclaw-project/browse/runner.mjs` browser hands (Docker stage). `platform/deploy/` units, Caddy, cells.
- `product/plan.json` + `CONTRACT.md` are the plan/limits source; `dashboard/` and `bin/` are owner tools.
- Full map: `docs/codebase-audit/FILE_MAP.md`.

## Entry points
- HTTP: `accounts.wsgi` via gunicorn. Workers: `manage.py request_worker`, `billing_worker`, `tool_relay`. Root: `lifecycle.cell_bridge_main`, `lifecycle.supervisor_main`, `browse.service_main`.
- Agent loop: `accounts/chat.py:166` -> `chat.py:203` -> `request_queue.py:61` -> `request_worker.py:32` -> `chat_driver.py:141` -> `gateway.py:119` -> cell bridge. Diagram: `ARCHITECTURE.md`.

## Boundaries to respect
- Tenant id comes from the session (`customer_scope`), never from request params. Every SQL is scoped by `account_id`.
- Only two doors from a cell to the host: model relay :4000, tool relay :4100. Root units (bridge, browse, supervisor) use method allowlists; do not widen them.
- Browser safety floor lives in `browse/loop.py:162-196`. Do not move rules into prompts.
- Screenshots/pixels cannot be scrubbed; anything sent to TypeSafe (JEV) is a privacy decision (M-02). Do not add new egress.
- Dashboard (`dashboard/app.py`) stays stdlib and separate from platform helpers on purpose.

## Locating features
- Route -> view -> service: grep the path in `platform/accounts/urls.py`, open the view in `accounts/<name>.py`, then the matching `agentai_platform/<name>.py`. (cbm graph does not link Django routes.)
- UI page -> API: pages in `lumina/src/pages/`; every call goes through `lumina/src/lib/api.ts`; grep the `/v1/...` literal. Backend routes with no SPA caller are listed in `_findings/frontend.md` (FE-020).
- Owner switches: `agentai_platform/switches.py` (catalog) + files on host. Limits: `product/plan.json` read at `billing.py:190-193`; some constants are duplicated in code (OP-008), update both.
- Env vars: read in `accounts/settings.py`; only 8 documented (M-09). Add any new var to `platform/deploy/accounts.env.example`.

## Where detailed docs live
`docs/codebase-audit/`: `SYSTEM_OVERVIEW.md`, `ARCHITECTURE.md`, `EXECUTION_FLOWS.md`, `FILE_MAP.md`, `DEPENDENCIES.md`; raw findings and master dedupe in `_findings/` (`00_RECONCILIATION.md` is authoritative). Current native design: `openclaw-project/docs/architecture/native-execution.md`. `docs/orchestration-audit/` is historical.

## Known debt (do not worsen; IDs in the audit)
- M-01 cancelling a WAITING request leaks reservation + queued task. Fix in `RequestQueue.cancel` plus a test.
- M-02 screenshots to TypeSafe; `browser_optimization` switch is not wired to live egress.
- M-04 shared client IP behind Vercel; BE-002 SSE `/stream` can block the single worker; BE-004 webhooks over 8 KB get 413.
- M-05 orphans: durable, memory, schedules, watchers, skills, optimization, policy_check, genui/intent, ops/rotation, lifecycle/broker.
- M-06 lumina-character fork; M-07 three genui generations (`gen/` is the target; `components/genui` still serves form/task_plan); M-08 three browser designs.
- M-10 CI runs about 20 of 73 platform tests and no frontend: run the relevant tests locally (`manage.py test accounts`, `python -m unittest`, `npm test`, `node --test` in `browse/`).
- FE-002 browser question/vault UI missing in `lumina`; ST-013/IS-006 server files not in repo.

## Rules to avoid new duplication
- Before adding a client, parser, SSRF check, time or env helper, grep for the existing one (ST-011, AG-010); extend it.
- One service factory: reuse `accounts/chat.service()`; do not rebuild `ChatService` in new views (BE-007, BE-024).
- Generative UI: add new block types to `src/gen/` and the backend registry together; never to `components/genui`.
- New SQL tables go in `platform/migrations/NNNN_*.sql` (next free number), not only in Django migrations (BE-012).
- Do not create phase-numbered folders or docs; "phase N" already has four meanings (GH-008).
- New tests must be reachable by CI: add them to `.github/workflows/platform.yml` or switch it to discovery.
- Logging must be redaction-safe: class/module/request id only, never URLs, bodies, or message text (M-12).

## Working agreements
- Run `lumina-index status` before using the cbm graph; refresh after branch switches.
- Read source before claiming behaviour; graph edges are hints.
- Commit only when asked; tag deployed commits and record the hash in RELEASE_NOTES (GH-005).

## Stale lines in CLAUDE.local.md
The "Known blind spots" entries about `ServiceRouter.choose` and `platform/tests/test_service_handoff.py` are stale (M-11): `routing/services.py`, `ServiceRouter` and both tests were deleted in commit `5db9636`. Also stale: it calls `evidence/` unindexed, but 183 files there are tracked (IS-018). Remove or update those lines.
