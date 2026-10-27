# Entry points: every way work can enter the system

Each row traces trigger to terminal outcome. "Same engine as P01" means the request is a row in `customer_requests` and is run by `RequestWorker` → `ChatDriver.execute`. Paths refer to [02-path-registry.md](02-path-registry.md).

## Customer-facing entry points

| # | Trigger | Route and handler | Creates | Engine | Terminal outcome | Path |
|---|---|---|---|---|---|---|
| E1 | Message typed in the Composer (Auto) | `POST /v1/conversations/<id>/send` → `accounts/chat.py:chat_send` (162) → `ChatService.send` (`agentai_platform/chat.py:224`) | request `waiting`, message, reservation, task `queued` | P01 engine | `completed` / `failed` / `cancelled` with last agent message | P01 |
| E2 | Same, Respond = Text | same route, `mode=text` → `context={'mode':'text'}` | same | P01 engine, no tool protocol | same | P02 |
| E3 | Same, Respond = Plan | same route, `mode=plan` → intent `plan` | same | P01 engine with plan prompt | plan block attached (request `completed`), then phases | P03 |
| E4 | Same, Respond = Browse | same route, `mode=browse` (only if `browse_tasks`) → intent `browse` | same | `_execute_browse` | reply written by code; or assistant takes over after a verification wall | P04 |
| E5 | Tools menu or Home tile | Client-side only: `Composer.tsx:57` sets text from `TEMPLATES` | nothing | none | none: only prefilled text; submit then follows E1 to E4 | n/a (UI-only) |
| E6 | Block action "launch plan" | `POST /v1/blocks/<id>/launch` → `accounts/genui.py:block_launch` → `ChatService.launch_plan` (322) → `PlanRunner.start/advance` | one request per enabled phase (intent `phase`) | P01 engine | each phase `completed`/`failed`; plan `launched` | P03 |
| E7 | Block action "submit form" | `POST /v1/blocks/<id>/submit` → `ChatService.submit_block` (297) → `_spawn` intent `plan` | plan request | P01 engine | plan block | P08 |
| E8 | Plan phase approve/retry/skip/stop | `POST /v1/blocks/<id>/phase`, `/stop` → `PlanRunner` (`genui/runner.py:159-188`) | phase state changes, new request on approve/retry | P01 engine | phase `completed`, `skipped`, `cancelled` | P03 |
| E9 | Live plan edit | `POST /v1/blocks/<id>/live` → `block_live` | edits to unstarted phases | none | stored revision | P03 |
| E10 | Stop | `POST /v1/tasks/<id>/cancel` → `chat_cancel` → `RequestQueue.cancel` (86) | `cancelled` (waiting) or `cancel_requested=1` | worker poll aborts | `cancelled` | P01 |
| E11 | Pause / Resume | `POST /v1/requests/<id>/pause|resume` → `chat_pause/resume` → `RequestQueue._hold` | `paused` flag | none | held until resumed | P01 |
| E12 | Retry | `POST /v1/requests/<id>/retry` → `chat_retry` (rate limit 30 per hour, line 241) → `ChatService.retry` (405) → `_spawn` | new request, `retry_of` | P01 engine; pursuit resume if on | as E1 | P09 |
| E13 | Classic chat page form | `/account/chat/` posts to `chat_send` | as E1 | P01 engine | as E1 | P11 |
| E14 | Classic Requests page | `POST /v1/requests` → `accounts/requests.py:requests` → `RequestQueue.submit` | request `waiting`, **no reservation, no conversation** | worker claims, fails unfunded | `failed`: "could not be funded or started" | P12 |
| E15 | Telegram message | `POST /v1/telegram/webhook` → `accounts/telegram.py` → `TelegramService` → `ChatService.send(provenance='telegram')` (`telegram.py:298`) | as E1 | P01 engine, **no tool protocol** (`chat.py:873`) | reply stored in chat; **not pushed back to Telegram** | P10 |
| E16 | Browser takeover and answers | `/v1/browse/<id>/{control,pause,resume,release,answer}` → `accounts/browse.py` → `BrowseRpc` → `BrowseService` | control actions on a running job | browse service | job resumes or ends | P13 |
| E17 | Reading progress | `GET /v1/tasks/<id>`, `/events`, `/stream`, `/v1/conversations/<id>/messages`, `/v1/browse/<id>` | none | none | none | P20 |

## Owner and operator entry points

| # | Trigger | Route or command | Effect on orchestration | Path |
|---|---|---|---|---|
| E20 | Owner toggles a feature | `dashboard/app.py` POST `/switch`, `/switch-confirm`, `/toggle`, `/jev-toggle` → `switches.SwitchStore` writes the switches file | Enables or disables P01 (`customer_execution`), P04/P05 (`browse_tasks`), P05 JEV (`jev_services`), P07 (`pursuit`), P14 (`jev_routing`), P15 (`jev_display`), P10 etc. Read per tick (`request_worker.py:build_worker`, `accounts/chat.py:30`) | P21 |
| E21 | Owner changes routing config | `/routing-save`, `/routing-rollback` → `routing_save()` writes `AGENTAI_ROUTING_CONFIG_FILE` | Config for P14, P05 tool choice, P15 | P21 |
| E22 | Owner approves, suspends customers | `/customer-action`, `/customer-limit` → `manage.py signup_admin` | Controls whether an account may run work | P21, P22 |
| E23 | Operator internal API | `internal/accounts/<id>/{invite,revoke,suspend,audit}`, `…/deployment/operations`, `…/operations/<op>/retry` (`accounts/views.py`, `accounts/lifecycle.py`; operator role + MFA + grant) | Queues cell `create|start|stop|upgrade|backup|restore|delete` operations → P17 | P22 |
| E24 | Host daemons | `systemd`: `agentai-request-worker`, `agentai-lifecycle-worker`, `agentai-supervisor[-native]`, `agentai-cell-bridge`, `agentai-browse`, `agentai-billing-worker.timer`, `agentai-platform-mail.timer`, `agentai-ops-backup/monitor.timer`, `agentai-model-proxy`, `agentai-platform-app` (gunicorn), `agentai-platform-control` (legacy stdlib server) | Run P01, P17, P05, P19, P33 | P22 |
| E25 | Operator CLIs | `lifecycle.enroll_cli`, `lifecycle.provision_cli`, `ops.cli {backup,monitor,watchdog,…}`, `ops.pursuit_report`, `ops.probe_models`, `routing.report_cli` (called by dashboard), `routing.bench` | Setup and reporting; none starts customer work | P22 |
| E26 | Local development | `lumina/dev-mock.mjs` (mock API), `platform/dev_local_ui.py` (loopback preview with a synthetic customer), `tests/preview_*.py` | None in production | P41 |

## Entry points that exist as documentation or schema only
| Trigger | Where it appears | Reality |
|---|---|---|
| Scheduled automation | Automations page copy (`lumina/src/pages/Info.tsx:17`), `/v1/schedules`, `schedules.py`, switch `customer_schedules`, tables 0010 | No route handler, no importer, switch locked and unread (P30) |
| Webhook-triggered agent work | Stripe webhook (`/v1/billing/webhook` → `bl.webhook`, billing only); Telegram webhook (E15) | Only Telegram starts chat work |
| Integration events (mail, calendar, GitHub) | `/v1/account/connections*`, `connectors.py` | Link, read-only fetch and draft proposals only; the agent loop never calls connectors (see `docs/architecture/findings.md` F-04) |
| Replay or resume from a durable objective | `durable.py` (objectives, checkpoints, sticky cancel), tables 0010 | No importer (P30). Resume exists only as retry with `retry_of` and the pursuit record (P09, P07) |
| Native sub-agent spawn by the customer assistant | OpenClaw `sessions_spawn`; owner `main` agent (P25) | Customer-cell availability unknown (P45) |

## Do similar entry points share an engine?
- **Shared:** E1, E2, E3 (plan draft), E4 (queue and worker only), E6, E8 (phases), E12, E13, E15 all become `customer_requests` rows processed by one `RequestWorker` and one `ChatDriver`. They differ only in `intent`, `context_json` and provenance.
- **Not shared:** E14 creates a row that bypasses admission and therefore always ends unfunded. Browser takeover (E16) talks to the browse service directly and not through the queue.
- **Two different "agents":** the customer assistant (OpenClaw in the cell, P24) and Lumina's browser agent (P05). They are connected only by text messages built by `agent_protocol.py`.
