# Lumina — architecture report and status

Source of the design: the reference dashboard screenshot and the Lumina transformation specification (2026-10-13).
**Status:** Spec phases 1–3 delivered (audit, design system, functional dashboard on live data); phase 4 built but not deployed (2026-10-17); phases 5–10: see "Not built" (that table is older than the code: plan builder, generative UI, browser workspace and JEV browsing have since been built).

## 1. Audit result (verified against code and the live server, not documentation)

| Question | Finding |
|---|---|
| Frontend | None before this work: server-rendered Django templates (`platform/accounts/templates`), plus a 120-line reference JS client. Lumina is the first SPA: React 19 + TypeScript + Vite in `openclaw-project/lumina/`, served by the account app at `/app/` |
| Backend | Django 5 account app (gunicorn) + `agentai_platform` library (SQLite, WAL), lifecycle/request/billing/ops workers, host supervisor and cell bridge (root), owner dashboard (stdlib, private) |
| Auth | Django sessions, invite-only, CSRF, MFA for operators; JSON login works; `/v1/csrf` and `/v1/app` added for SPAs |
| Agent architecture | **C**: one OpenClaw Gateway per customer cell, one runtime per account, several model routes through LiteLLM (haiku default). No independent "agents"; browser/coding stages are broker containers (tools), not agents. Global serial queue: one running customer task |
| JEV | A choice/classification API (`jev-1.13.0`), verified live: several choice questions per call with probabilities. Not a generator. Used for routing recommendations in shadow mode only (`plans/product/routing.md`) |
| Claude | Anthropic models behind the cell's LiteLLM virtual key; the cell agent decides tool use |
| Tasks | `customer_requests` (+`tasks`, reservations, events). List/read/cancel exist (`/v1/requests`, `/v1/tasks/{id}/events|stream|cancel`). No pause/resume, no plan objects, no retry endpoint |
| Streaming | SSE per task and an events endpoint (polling is what Lumina uses today) |
| Files | Built and tested, **switched off** on the server (`features.files=false`) |
| Browser | Isolated Chromium stage exists in the broker (tested); no live-view/takeover path to a UI |
| Calendar / schedules / automations | Schedule engine built but locked for customers; no calendar connection (Google/Microsoft not registered) |
| Billing | Free-access mode live; Stripe test mode built, not configured |
| Tests | 471 platform, 90 Django, 46 dashboard, 11 Lumina |

## 2. Reused vs new vs missing (for this spec)

- **Reused as-is:** auth/session/CSRF, `/v1/requests`, task events, conversations/messages/send/archive, usage, connections, telegram link API, billing summary, budgets/admission, the cell agent runtime, shadow routing.
- **New (this work):** `lumina/` front end; design tokens; shell with sidebar/top bar/command search/notifications; Home (greeting, composer, capability cards, recent tasks, Active Task / Today / System Status rail); Chat; Tasks list + detail drawer with activity and cancel; honest status pages for Browser, Calendar, Automations, Files, Integrations; Settings (appearance, usage); NASA-textured monochrome rotating planet (lazy, adaptive, reduced-motion, static fallback); `bin/deploy-lumina.py`; backend `/v1/csrf`, `/v1/app`, `/app/` shell.
- **Modified:** `/v1/requests` now reports the real execution flag; CSP is set per response so `/app/` can run scripts.
- **Missing (needs backend first):** plan/plan-revision objects, task pause/resume/retry, approval requests as first-class objects, generative-UI specification store, automations API, browser session API, calendar connection, file screen data, model-usage breakdown per task.

## 3. Honest design decisions
- **No fabricated data.** Active Task shows real events and elapsed time ("Working…"), never a percentage: the runtime reports none. Today shows "Calendar is not connected". System Status rings count real requests; the health text comes from `/readyz`.
- **Capability chips are not agents.** They pre-fill an editable sentence; nothing else changes. "Use Files" is disabled until uploads are enabled; pasted files get an explanation.
- **Display name:** no profile name exists in the backend, so the first part of the email is used ("Parsa"). A real display-name setting needs a backend field.
- **Reference vs delivered:** the reference shows a moon-like crescent; the spec asks for Earth, so the planet uses NASA Blue Marble imagery in a monochrome shader (near-black ocean, grey land, bright limb), 150 s per turn. No preview thumbnails on recent tasks (no screenshots are stored). The sun icon in the reference is replaced by a reduce-motion toggle because there is no light theme.
- **Where it runs:** `https://<site>/app/` beside the classic UI at `/account/`. The edge needs one `git push` to forward `/app/`.

## 4. Verification
- Typecheck clean; 11 UI tests (formatting, state mapping, composer: CSRF + idempotent send, budget refusal text, empty input, file paste).
- Built bundle (main 93 KB gzip; planet chunk 243 KB gzip, lazy) served by the real backend under its strict `/app/` policy: sign-in screen renders, no CSP violations.
- Screens checked in Chrome against a local mock API (desktop 1512 px and 390 px phone width): Home, task detail drawer, mobile navigation. The signed-in screens on the live server were **not** checked (no password available to the developer), and WebGL is unavailable in the test browser, so the 3D planet itself was checked only through a CPU render of the same shader; the static fallback was seen in the browser.

## 5. Not built (spec phases 4–10) and what each needs
| Spec phase | Status | Needs |
|---|---|---|
| 4 Task control center (pause/resume/retry, queue view, persistence) | **built 2026-10-17, not yet deployed**: list, detail, cancel, live status; queue position ("N ahead"); pause/resume of a task that has not started (held in the queue, keeps its place and budget reservation, never wakes the assistant); retry of a failed or cancelled task as a new task (fresh budget reservation, idempotent); the queue and the held state are durable in the database (migration 0022) | a task that is already running cannot be paused: the assistant has no safe stopping point mid-run (browser tasks keep their own "hop in" pause). Deploy order: web app release first (applies migration 0022), then the supervisor release, then the Lumina bundle |
| 5 Interactive plan builder | not started | plan + revision tables, dependency validator, LLM plan generation (paid), approval flow |
| 6 Generative UI | not started | versioned Zod schemas, component registry, renderer, template store, repair loop |
| 7 JEV cost optimization | shadow classification done (`routing.md`); cost-per-success benchmark not run | owner go for paid runs; canary and escalation |
| 8 Browser workspace | not started | live viewport transport from the broker browser stage, takeover protocol |
| 9 Automations / integrations | not started | enable schedule engine, calendar provider registration |
| 10 Hardening | partial | end-to-end browser tests against a real stack, accessibility audit, load tests |
