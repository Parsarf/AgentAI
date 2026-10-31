# Building a new front end (UI contract)

The classic pages under `/account/` are server-rendered HTML. **Everything they do is also available as JSON** under `/v1` and `/auth`.
A completely different dashboard needs no backend change: write it against this contract and drop it in.

## Quick start
1. Build any static single-page app (React, Svelte, plain JS…). Output: `index.html` + assets that use **absolute `/app/...` paths**.
2. Copy the build into `/var/lib/agentai-platform/ui/` on the server (`index.html` at the top level; owner `agentai-platform`, read-only is fine).
   It is live immediately at `https://getlumina.pro/app/`. The classic UI keeps working at `/account/`. To roll back, delete the folder.
3. A working example is in `ui-reference/` (about 120 lines of plain JS: sign-in, chat, clear, sign-out). Copy its `api()` helper.

Rules of the shell: scripts and styles must be **separate files from the same origin** (no inline `<script>`/`<style>`, no CDN, no `eval`).
Images and fonts: same origin or `data:`. Calls go to the same origin only (`connect-src 'self'`). Everything is HTTPS-only.

## Talking to the API
- **JSON in, JSON out.** `Content-Type: application/json` on POST. Errors are `{"error": "<code>"}` with an HTTP status.
- **CSRF:** `GET /v1/csrf` → `{"csrf_token", "api_version"}`. Send the token as `X-CSRFToken` on every POST. Cookies are `Secure; HttpOnly; SameSite=Strict`, so use `credentials: 'same-origin'`.
- **Sign in:** `POST /auth/login {email, password}` → 200 and a session cookie (operators get an MFA step; customers do not). `POST /auth/logout`. Recovery: `POST /auth/recovery {email}` then `POST /auth/reset {code, password}`; activation: `POST /auth/activate {code, password}`. After login fetch a **new** CSRF token (it rotates).
- **Never send account, tenant or session ids.** The server derives them from the session; requests that try (`account`, `tenant_id`, `session_id`… in query or headers) are rejected with `routing_override_denied`. Responses do not contain them either.
- **Idempotency:** `send` takes a client-chosen `key`; repeating it never creates a second task. Generate one per message.
- **Limits:** message ≤ 16,000 characters; 10 projects; 10 active conversations per project; 30 new tasks/hour; 3 live streams; 240 reads and 30 writes per minute per user (block autosave 90/min); login 5 attempts per 15 min per address. Rate limits answer `429` with `Retry-After`.
- Machine-readable spec: `openapi.json` (kept in step with the routes by a test). Version marker: `api_version` in `/v1/csrf` and `/v1/app`.

## Start-up sequence for any shell
1. `GET /v1/app` → `401` means show sign-in. Otherwise:
```json
{"api_version":"2026-10-13","user":{"email":"…","role":"customer"},"assistant":{"state":"ready|stopped|not_provisioned|…"},
 "features":{"chat":true,"execution":true,"files":false,"uploads":false,"telegram":false,"connectors":false,"billing_mode":"open","requests":true,"usage":true},
 "limits":{"max_message_chars":16000,"max_projects":10,"max_conversations_per_project":10},"links":{"classic_ui":"/account/","sign_out":"/auth/logout"}}
```
`features` is the **only** thing that should decide which screens and buttons exist. `execution:false` means messages are saved and wait. `billing_mode`: `invite_only` | `open` (free access) | `paid_required`.

## Resources
| Screen | Endpoints |
|---|---|
| Projects | `GET/POST /v1/projects {name}` · `GET /v1/projects/{id}` |
| Conversations | `GET /v1/conversations[?project_id=&q=&archived=0|1&limit=100&offset=0]` → `{conversations:[{id,project_id,created_at,title,last_activity,preview,active,archived_epoch}],has_more,next_offset}` · `POST /v1/conversations {project_id}` → 201 · `GET /v1/conversations/{id}` · `POST /v1/conversations/{id}/archive {}` (hide, keeps history) · `POST /v1/conversations/{id}/restore {}` (restore; active quota still applies) |
| Transcript | `GET /v1/conversations/{id}/messages[?after=<message id>&limit=≤100]` → `{messages:[{id,request_id,provenance,content,created_at}], tasks:[{id,state,task_state,reservation_state,result,cancel_requested,created_epoch}], execution_enabled,has_more,next_after}` (read subsequent pages with `after=next_after` until `has_more=false`; `provenance`: `customer` · `agent` · `telegram`) |
| Send | `POST /v1/conversations/{id}/send {message, key}` → 202 `{request:{id,admission,execution_enabled,…}}`. Refusals: `402 {error:"budget_denied", category}` (`queue_full`, `task_allowance_exhausted`, `account_allowance_exhausted`, `service_allowance_exhausted`), `409 request_conflict`, `400 invalid_request` |
| Send options | `POST …/send` also accepts `mode`: `auto` (default; text, a form, or a plan), `text`, `plan`. The response's `request.response_type` is `text`, `plan`, or `interactive`; for `interactive`, `request.block` holds a requirements form |
| Interactive blocks | `GET /v1/conversations/{id}/blocks` → `{blocks:[{id, kind: form\|task_plan, spec, state, version, status: draft\|submitted\|launched, anchor_message_id, launched_request_id}]}` · `POST /v1/blocks/{id}/state {version, state}` (autosave; `409 version_conflict` if another window saved first) · `POST /v1/blocks/{id}/submit {version}` · `POST /v1/blocks/{id}/launch {version}`. Running plans: `POST /v1/blocks/{id}/live {version, plan}` (edit phases that have not started), `POST /v1/blocks/{id}/phase {phase_id, action: approve\|skip\|retry}`, `POST /v1/blocks/{id}/stop`; a launched block carries `run: {phase_id: {state, summary, attempts, approved, started_epoch, finished_epoch}}` and `run_status`. Chats can be renamed with `POST /v1/conversations/{id}/rename {title}`. Specs are validated data; a UI must render only the documented component set (see `plans/product/lumina-genui.md`) and show a read-only note for anything else |
| Task | `GET /v1/tasks/{id}` · `POST /v1/tasks/{id}/cancel {}` · timeline `GET /v1/tasks/{id}/events?after=&limit=` · live `GET /v1/tasks/{id}/stream` (Server-Sent Events, event `task_event`, resume with `Last-Event-ID`, max 3 per account) |
| Requests (queue view) | `GET /v1/requests` · `GET /v1/requests/{id}` · `POST /v1/requests/{id}/cancel {}` |
| Usage | `GET /v1/costs` → `{reported_microusd, held_microusd, period_remaining_microusd, period_limit_microusd, admission_eligible, usage_pending, currency}` (micro-dollars: divide by 1,000,000) |
| Billing | `GET /v1/account/billing` · `POST /v1/account/billing/checkout {}` / `portal {}` → hosted-page URL (cards are only ever entered on the provider's page) |
| Files | `GET/POST /v1/projects/{id}/files` · `GET …/files/{file}/preview` · `GET …/bundle` · `POST /v1/artifacts/{id}/versions/{n}/ticket {}` then `GET …/download?…` |
| Connections | `GET /v1/account/connections` · `POST …/link`, `…/disconnect`, `GET /v1/account/drafts` (only when `features.connectors`) |
| Telegram | `GET /v1/account/telegram` · `POST …/link {}` → `{link, expires_in}` · `POST …/unlink {chat_id}` (only when `features.telegram`) |

Task and request states you must render: `waiting` (queued) → `starting` → `running` → `completed` · `failed` · `cancelled`; `uncertain` means the system is reconciling and will resolve by itself. While any task is `waiting|starting|running|uncertain`, poll the transcript every ~4 s or use the SSE stream. A first reply after a pause takes ~30–40 s because the assistant wakes up.

## Design freedom, and what is not negotiable
Free: layout, navigation, brand, copy, theming, animations, mobile design, onboarding flow, empty states.
Fixed by the backend (a UI cannot change them): who may see what, budgets and admission, approvals, rate limits, which features exist (`features`), the strict content policy on every non-`/app/` response.
Never in a UI: provider keys, other accounts' data, raw model prompts. Display errors from the `error` code, not from raw text.

## Not served over JSON yet (classic UI only)
Nothing in the customer area; the only HTML-only flows are the CSRF-protected sign-in/recovery/activation **forms**, which also accept JSON (see above). The owner dashboard (`/` on the ops host) is a separate private app, not part of this contract.

## Changing the look of the classic UI instead
`accounts/static/ui.css` defines all colours, radii and spacing as CSS variables at the top (`--bg`, `--accent`, …) and the templates in `accounts/templates/accounts/` contain no inline styles or scripts, so a re-skin is a CSS-only change.

## Conversation-first navigation

`/app/` and `/app/chat` are the new-chat surface. `/app/history` searches titles and transcript text, pages through saved chats, and includes an Archived view. `/app/chat/{id}` restores the complete transcript and continues the same native session. Old `/app/tasks/{id}` links redirect to the owning conversation when one exists; unlinked legacy tasks keep their activity view. Request summaries now include `conversation_id`. `/app/home` retains the dashboard. Archive preserves tasks, messages, and runtime session; it does not cancel work. Restore is required before sending to an archived chat.

Drafts are session-local and scoped by signed-in account and conversation; they are cleared on logout or authorization loss. Failed sends retain their newly created conversation and retry key. Chat responses are rendered as Markdown. Activity remains available within the conversation.

## Self-service sign-up (owner approves each account)
Public, only while the owner switch `open_signups` is on (`GET /v1/signup/config` -> `{open}`):
- `POST /auth/signup {email, password, website=""}` -> always `202 {accepted:true}` (same answer for an address that already exists); `400 invalid_email|weak_password`, `403 signups_closed`, `429`, `503 signups_full`. Sends a 15-minute single-use link `…/app/verify?code=…`.
- `POST /auth/signup/verify {code}` -> `{state:"pending"}`; `404` for an unknown, expired or used code.
- `POST /auth/login` for a confirmed account that is not yet approved -> `403 pending_approval` (only after the correct password); `403 not_approved` if declined.
The owner approves, declines, suspends and resumes in the dashboard Customers page (`signup_admin`); approval activates the account, seeds its allowance, creates its assistant and emails the person.
