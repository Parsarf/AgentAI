# Registries: decisions, tools and models, configuration

Path identifiers refer to [02-path-registry.md](02-path-registry.md). Secrets and key values are not listed; only variable and file names.

## Decision ownership matrix

"Owner" is who actually makes the decision in code: **C** customer, **A** application code (deterministic), **M** the assistant model (OpenClaw in the cell), **J** JEV (TypeSafe) answering a fixed question, **B** browser-agent models (Haiku, Sonnet), **O** the owner (switches and settings), **X** external system.

| Decision | Owner | Inputs | Where implemented | Paths |
|---|---|---|---|---|
| Who may call the API | A | session cookie, identity epoch, membership, CSRF | `accounts/middleware.py:44-66`, `accounts/views.py:customer`, `endpoint()` | all |
| Whether work may run at all | O, A | `customer_execution` switch + facts file; entitlement and plan; budget | `switches.py:SwitchStore.is_on`, `accounts/chat.py:30-55`, `budget.py:admit` | P01 to P11 |
| Request intent (chat, plan, browse) | C | Respond mode only | `chat.py:send` (`kind`), UI `Composer.tsx:67` | P01 to P04 |
| Whether Browse mode is honoured | O, A | `browse_tasks` switch | `chat.py:send`, `Composer.tsx` filter | P04 |
| Which request runs next | A | oldest `waiting`, not paused, account active, cell state | `request_queue.py:126-148` | all |
| Whether a request is funded | A | active reservation | `request_worker.py:_tick`, `budget.py` | all |
| Wake or stop a cell | A | waiting requests, idle times, one-cell slot | `lifecycle/sleep.py:wake_plan`, `worker.py:enqueue_wakes` | P17 |
| Prompt precedence | A | workspace `AGENTS.md` rules (written at each cell start) then per-message preamble then the customer's text | `cell_config.py:38-139`, `agent_protocol.py:163`, `genui/runtime.py:outgoing` | P01 |
| Which history the assistant sees | M (own session) / A (bounded 20 messages, 12 000 chars for a new session or browser job) | session history; `chat_messages` | `genui/runtime.py:30-48` | P01, P05 |
| Whether to answer, ask, plan or use a tool | M | message, rules, preamble | OpenClaw inside the cell | P01 |
| Whether a step request is acceptable | A | JSON shape, bounds, site pattern, neutralised text | `agent_protocol.py:clean` (44) | P05, P06 |
| Browser or search for a step | A (site named); J (`jev_services` on, confidence >= 0.6, 8 s); A (keyword rules) | step text, site | `routing/tools.py:ToolDecider.choose` | P05, P06 |
| Whether to use the browser if unavailable | A | `browse_tasks` and factory | `routing/tools.py:choose`, `chat.py:browser_possible` | P05 |
| Whether another browser session is allowed | A (without pursuit: one per message; with pursuit: `next_action`) ; budget share 60% | plan state, budget, no-progress counter | `chat.py:_answer_step`, `_pursue_step`, `pursuit.py:592` | P05, P07 |
| Next browser action | J (tier 1), B Haiku (tier 2), B Sonnet (tier 3, max 2 per run) | page snapshot, candidates, history, picture | `browse/ladder.py:573-780` | P05 |
| Whether a browser action is allowed | A | payment, sign-in, human-check, sensitive flag, denied domains, `Policy.read_only` | `browse/loop.py:54-59,152-173,302` | P05 |
| Whether to ask the customer | A (rules, sensitive fields), B/J ("needs user") | form fields, question building | `browse/loop.py:416-466`, `ladder.py:build_question` | P05 |
| Whether to hand off | A (code rules); J can add a hand-off, never remove one | page state | `browse/loop.py:253,201` | P05 |
| Progress review and replan | A rules first, J one question, A validates | ledger signals | `browse/review.py`, `pursuit.py:435-505` | P07 |
| Whether a result is verified | A | success criteria, step rows, checks, artifacts | `pursuit.py:538` | P07 |
| Plan approval and phase order | C approves; A enforces dependencies | plan JSON, `requiresApproval`, dependsOn | `genui/runner.py:72-131`, `genui/schema.py:validate_plan` | P03 |
| Whether a reply becomes cards | A | schema validation of `lumina` fenced JSON | `genui/data.py:validate_data`, `genui/store.py:attach_cards` | P16 |
| Layout of plain replies | J (fixed list), off by default | reply text, scrubbed | `routing/display.py` | P15 |
| Recommended route of a request | J, recorded only | first 2000 chars, scrubbed | `routing/shadow.py`, `classifier.py`, `policy.py` | P14 |
| When a run times out | A | 900 s, 1.5 s polls | `chat.py:_poll` | P01 |
| Cancellation | C requests; A enforces; X (runtime) aborts | `cancel_requested` flag | `request_queue.py:86`, `chat.py:_poll`, `gateway.abort` | P01 |
| Retry | C chooses; A creates the new request | failed or cancelled request | `chat.py:405` | P09 |
| Duplicate-action prevention | A | idempotency key, fence, lease, no resend of uncertain delivery | `request_queue.py:42,126,172`, `chat.py:_start_delivery`, `reconcile` | P01, P18 |
| Spend settlement | A (reads X: LiteLLM key spend) | before/after spend snapshot; fallback reserved bound | `chat.py:521-575` | P19 |
| Completion status text | A | last agent row; browse-mode text built from the final state | `chat.py:737-741`, `_browse_message` (1194) | P01, P04 |
| Which model answers | O (provisioning constant) | `DEFAULT_MODEL`, key allow-list | `lifecycle/cell_config.py:15-16`, `litellm_admin.py` | P01 |
| Tools the assistant may use | X (OpenClaw defaults) | Lumina sets only model, sandbox mode, heartbeat, search plugin | `cell_config.py:20-31,200-239` | P24 |
| Owner agent delegation | M (owner `main`) under config limits | spawn caps (3, 900 s) | `config/skills/orchestration/SKILL.md`, `config/openclaw.example.json` | P25 |

## Tool and model registry

### Models
| Model id | Registered in | Used by (caller) | Availability condition | Fallback |
|---|---|---|---|---|
| `litellm/claude-sonnet-5-5` (Claude Sonnet 5.5) | `lifecycle/cell_config.py:15-16` (cell primary); `deploy/litellm.yaml`; `config/litellm.example.yaml` | assistant in every customer cell (P01 to P04); browser tier 3 via `browse/llm.py:7` | key allow-list updated at every cell start (`CellProvisioner.before_start`) | none visible; a failed key update leaves the model unchanged |
| `claude-haiku-4-5` | same files; `browse/llm.py:7` | browser tier 2; utility model in owner config | same | none |
| `claude-sonnet-4-6` | `cell_config.py:15,28`; owner `config/openclaw.example.json` and worker batches | allowed in cells (reasoning true, not default); owner agents | same | none |
| `jev-1.13.0` | `routing/config.py:14`, `optimization.py`, `browser-opt/config.json`, `research-opt/adapter.py` | `ToolDecider` (P05), `ShadowRouter` (P14), `DisplayDecider` (P15), P27, P31, P26 | owner switches and the TypeSafe key file `AGENTAI_TYPESAFE_KEY_FILE`; response model must equal the pinned id | deterministic rules (never fails a request) |
| `jev-1.14.0` | `browse/service_main.py:20` | `JevChooser` and `browse/review.py` in the browser | key file `--jev-key-file`; `--jev-mode off|shadow|live` (default `shadow`; production `live` per release notes) | Haiku, then Sonnet |
| `jev-latest` | `browser-opt/config.json` ("deliberately not used") | none | n/a | n/a |
| `openai/gpt-6-sol` | `config/phase4-native-workers.batch.json` | owner Codex workers (P25, P28) | ChatGPT-profile authorisation (not visible) | none ("no fallback") |
| `claude-builder|reviewer|debugger|cli` | `config/phase10-claude-code-activation.batch.json`, `policy_check.py` | owner Claude Code workers (P28) | switch `claude_code_for_customers` is locked | none |

### Tools
| Tool | Registered where | Callers | Availability | Execution owner | Fallback |
|---|---|---|---|---|---|
| `lumina-step` request | `agent_protocol.py:19-23` (`PLAN_TOOLS = browser, search, user, answer`) | the assistant model | Auto mode, customer typed message only (`chat.py:873`) | Lumina driver | bad block → "answer with what you have" |
| Browser (Lumina) | `browse/service.py`, `runner.mjs` commands | P04, P05, P07 | `browse_tasks`, service up, memory guard | host browse service + Chromium stage | search (`ToolDecider` note), or finish |
| Search (assistant's `web_search`, `web_fetch`) | Brave plugin installed per cell (`cell_config.py:200-239`) plus rules text | the assistant | key from host custody; plugin pinned `2026.9.6` | OpenClaw in the cell | rules tell it to say so if unavailable |
| Assistant built-ins (`exec`, `read`, `write`, `edit`, `apply_patch`, `process`, `ask_user`, `message`, `cron`, `sessions_*`, …) | OpenClaw (docs `tools/index.md`) | the assistant | OpenClaw tool policy defaults; Lumina observes only through `activity.py:CATEGORY` | OpenClaw | n/a |
| Bridge RPC | `lifecycle/cell_bridge.py:26` `ALLOWED` | `NativeGateway` | app user via private socket | bridge | `CapabilityUnavailable` |
| Browser runner commands | `browse/runner.mjs`, `browse/session.py` (JSON lines) | `BrowseRunner` | per job | runner in the stage | job error |
| Vault and saved choices | `vault.py`, `saved.py` | browser loop and preamble | customer-created items | app | none |
| Connectors (Gmail, Calendar, Drive, GitHub) | `connectors.py` | `accounts/connections.py` only | `connectors_linking` | app | `WriteDisabled` on any write |
| Schedules, memory, skills, watchers, durable objectives | `schedules.py`, `memory.py`, `skills.py`, `watchers.py`, `durable.py` | **none** | **unrouted** | n/a | n/a |
| Worker broker | `lifecycle/broker.py` | **none** (checks only) | n/a | n/a | n/a |
| Owner workers (`researcher`, `browser-worker`, `critic`, `codex-*`) | owner OpenClaw config and workspace templates | owner `main` | owner runtime | OpenClaw sandboxes | re-spawn once, then report the gap |

## Configuration matrix

### Owner switches (`agentai_platform/switches.py`, file `AGENTAI_SWITCHES_FILE`, facts file `AGENTAI_SWITCH_FACTS_FILE`)
Code default: **every switch is off**. `is_on(key)` is true only if the file records it on **and** every `needs` fact is true **and** every confirmation is recorded (`switches.py:166-171`). Missing or unreadable files mean off.

| Switch | Needs (facts) | Effect when on | Readers |
|---|---|---|---|
| `customer_execution` | `execution_ready` | Customer messages run on the assistant; builds a priced `ChatService` and `RequestQueue(require_cell=True)`; worker ticks | `accounts/chat.py:30`, `lifecycle/worker_main.py`, `agentai_platform/config.py` |
| `browse_tasks` | `browse_ready` | Browse mode, browser steps; service kill-switch watcher | `accounts/chat.py`, `request_worker.py`, `browse/service_main.py` |
| `jev_services` | `routing_key_present`, `browse_ready` | JEV answers tool-choice questions | `request_worker.py:build_worker` |
| `jev_routing` | `routing_key_present` | Shadow routing recorded | `request_worker.py:build_worker`, dashboard |
| `jev_display` | `routing_key_present` | JEV layout choice for plain replies | `request_worker.py:build_worker` |
| `pursuit` | none (confirmation only) | Stored plan, several browser sessions, verification | `request_worker.py`, `chat.py`, `browse/service.py` |
| `connectors_linking` | `provider_registered`, `custody_backend` | Shows connect buttons | `accounts/connections.py` |
| `open_access` | none | Free access (no payment) | `accounts/billing.py`, `billing_worker` |
| `billing_checkout` | Stripe facts | Payment required | `accounts/billing.py` |
| `open_signups` | `mail_ready` | Sign-up form | `accounts/signup.py` |
| `research_optimization` | `typesafe_key_present`, `research_provenance` | Jev research plugin config | dashboard only |
| `browser_optimization` | `typesafe_key_present`, `browser_route_deployed` | none | **no reader** |
| `credentialed_browsing` | `custody_backend`, `login_flow` | none | dashboard display only |
| `customer_schedules` | locked | none | dashboard display only |
| `claude_code_for_customers` | locked | none | **no reader** |

### Per-account safety overrides (`agentai_platform/safety.py`, table `safety_overrides`, migration `accounts/migrations/0014`)
32 documented features in 9 groups; only `budget_caps` and `rate_limits` are marked `wired=True` (can be switched off for the owner account named by `AGENTAI_SAFETY_OWNER_ACCOUNT`). The rest are descriptive.

### Environment variables read by the platform (names only)
Application (`accounts/settings.py`): `AGENTAI_STATE_DIR`, `AGENTAI_SESSION_SECRET`, `AGENTAI_PUBLIC_ORIGIN`, `AGENTAI_SWITCHES_FILE`, `AGENTAI_SWITCH_FACTS_FILE`, `AGENTAI_CELL_BRIDGE_SOCKET` (default `/run/agentai-cell-bridge/bridge.sock`), `AGENTAI_BROWSE_SOCKET` (`/run/agentai-browse/browse.sock`), `AGENTAI_PURSUIT_MAX_ROUNDS` (12), `AGENTAI_CUSTOMER_RESERVATION_MICROUSD` (1 000 000), `AGENTAI_SERVICE_ALLOCATION_MICROUSD` (50 000 000), `AGENTAI_ROUTING_CONFIG_FILE` (`/var/lib/agentai-platform/routing/routing.json`), `AGENTAI_TYPESAFE_KEY_FILE` (default under `/var/lib/agentai-platform/routing/`), `AGENTAI_UI_BUNDLE_DIR` (`/var/lib/agentai-platform/ui`), `AGENTAI_UPLOADS_ENABLED` (off unless `1`), `AGENTAI_STORAGE_DIR`, `AGENTAI_ARTIFACT_SIGNING_KEY`, `AGENTAI_LIVE_SECRET_FILE`, `AGENTAI_LIVE_PATH` (`/v1/live`), `AGENTAI_VAULT_KEY_FILE`, `AGENTAI_SAFETY_OWNER_ACCOUNT`, `AGENTAI_TELEGRAM_BOT_TOKEN|BOT_USERNAME|WEBHOOK_SECRET`, `AGENTAI_MAIL_ENABLED`, `AGENTAI_SMTP_*`, `AGENTAI_BILLING_*`, `AGENTAI_BRAVE_IMAGE_KEY_FILE`, `AGENTAI_SIGNUP_SETTINGS_FILE`.
Host services: browse service arguments `--jev-key-file`, `--jev-mode {off,shadow,live}` (default `shadow`), `--jobs`; supervisor `--controller-user`, wiring file (`native-wiring.example.json`, keys listed in `lifecycle/native_wiring.py:19`); lifecycle worker `--db`, `--socket`, `--once`.
Not code-defined in this repository: LiteLLM master key and per-key budgets, OpenClaw per-cell base config, TypeSafe account limits, systemd drop-ins made by hand on the server (listed in `RELEASE_NOTES.md`, for example `agentai-browse.service.d/jev.conf` setting `--jev-mode live`).

### Other behaviour selectors
| Selector | Choices | Default in code | Effect |
|---|---|---|---|
| Respond mode (request field `mode`) | auto, text, plan, browse | auto | P01 to P04 |
| `ChatDriver` parameters | `poll_interval` 1.5, `run_timeout` 900, `usage_wait` 45, `pursuit_rounds` from env | `chat.py:431` | loop timing |
| Browse job caps | `max_steps` 25 (cap 40), `max_seconds` 600 (cap 900), `max_cost` from reservation × share | `browse/loop.py:79`, `service.py:179` | P05 |
| Ladder | `max_sonnet` 2 | `ladder.py:577` | P05 |
| Routing config JSON | `enabled` false, `routes` (only `claude` true), `escalation`, `pricing` | `routing/config.py:10-24` | P14 |
| Browser-opt config | `enabled` false | `browser-opt/config.json` | P27 |
| Cell config | `sandbox.mode off`, `heartbeat.every 0m`, default model, search plugin | `cell_config.py:20-31` | P24 |
| Profile capacity | trial profile; host capacity default 2 cells in `lifecycle/capacity.py`; sleep rules say one running cell | `lifecycle/capacity.py`, `sleep.py:1-8` | P17 |
| Legacy stdlib server | `Config.FEATURES` frozenset of 7 names, not the switch catalog | `agentai_platform/config.py:6` | P33 |

**Competing flag systems.** Four independent mechanisms select behaviour: owner switches (JSON file, with facts and confirmations), per-account safety overrides (database), the stdlib server's `FEATURES` set, and environment settings read at startup. `GET /v1/app` merges some of them into the `features` object the UI uses (`accounts/api.py`).
