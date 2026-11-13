# Code map: who owns what, and where a new feature goes

Written 12 November 2026 against the checked-in source, after the consolidation described at the end. It is about the code's shape: which module owns each
responsibility, the rules several features share, and the steps to add a feature without re-creating a second copy of something. For what runs where and the
trust boundaries, read [system overview](system-overview.md); for the request path, [native execution](native-execution.md); for persistence,
[state and recovery](state-and-recovery.md). If this page and the code disagree, the code is right and this page needs fixing.

## The shape in one paragraph

Lumina is one Python codebase that runs as several processes. `platform/agentai_platform/` holds the product logic as plain services that take a database
handle and their collaborators as arguments; nothing in it reads Django settings. `platform/accounts/` is the Django application: it authenticates the
customer, turns settings into wired services in exactly one module (`accounts/wiring.py`), and exposes them as HTTP routes and worker commands. The React app
in `lumina/src` talks only to the `/v1` routes. Root-owned host services (cell bridge, browse service, supervisor) are separate processes reached over Unix
sockets, never imported by the web app.

```
lumina/src (React)  ──HTTPS /v1──▶  accounts/  (Django: identity, routes, error mapping)
                                        │  accounts/wiring.py  ← the only place services are built
                                        ▼
                                   agentai_platform/  (services: chat, queue, budget, events, files, genui, ...)
                                        │ unix sockets                    │ SQLite (one file)
                     ┌──────────────────┼──────────────────┐
                     ▼                  ▼                  ▼
               cell bridge         browse service      supervisor         (root; own entry points under agentai_platform/*/…_main.py)
                     ▼
              customer cell (OpenClaw) ──MCP──▶ tool relay (app user: browser, progress, location, memory, remote MCP, own-model relay)
```

## Layers and the one rule between them

| Layer | Lives in | May import | Must not |
|---|---|---|---|
| Product services | `platform/agentai_platform/` | the standard library, pinned packages, each other | import `accounts` or `django`; read environment or settings; build their own collaborators |
| Composition | `platform/accounts/wiring.py`, `accounts/store.py` | settings, services | hold request logic or authenticate |
| HTTP surface | `platform/accounts/<feature>.py` (views), `urls.py`, `middleware.py` | `wiring`, `views.endpoint`/`customer`, `services.rate`/`audit` | construct stores, switch readers, RPC clients or services |
| Worker commands | `platform/accounts/management/commands/` | `wiring`, services | the same (`test_wiring.py::WorkerWiring` assembles the request worker and tool relay for real) |
| Host services | `agentai_platform/lifecycle/*_main.py`, `browse/service_main.py`, `live/gateway.py` | services; their own argparse configuration | import `accounts` (they run as root, without the web app's settings) |
| Web client | `lumina/src` | the `/v1` API through `lib/api.ts` | know about queues, cells or switches beyond `/v1/app` `features` |

A test (`accounts/test_wiring.py::OneHomeForWiring`) fails when a view or command builds its own database handle, switch reader, chat service, ledger, queue,
RPC client, file store or request principal again.

## Composition root: `accounts/wiring.py`

Everything is built per call from current settings and files, so an owner switch, a rotated key or a changed rollout file takes effect on the next request,
and `override_settings` works in tests. Nothing is cached.

| Need | Call | Notes |
|---|---|---|
| Database handle on Django's connection | `wiring.store()` | `accounts/store.py` `AccountStore`; a service's writes join the request's transaction |
| The verified customer of a request | `wiring.principal(request)` | only after `views.customer(request)` let it through |
| Chat (web, panel, generated UI, plan phases, goal turns) | `wiring.chat_service()` | follows `customer_execution`: off = record only; on = priced, needs the cell, can steer |
| Chat that can only record | `wiring.intake_chat_service()` | Telegram today; never funds or starts anything (see "Open decisions") |
| Queue, ledger, events | `wiring.request_queue()`, `wiring.ledger(funded=…)`, `wiring.event_service()` | only a `funded` ledger can admit |
| Files, artifacts | `wiring.file_service()`, `wiring.artifact_service()`, `wiring.storage_ready()`, `wiring.uploads_on()` | |
| Other processes | `wiring.browse_rpc(account)`, `wiring.cell_rpc(account)`, `wiring.cell_gateway(account)` | Unix-socket clients; no secrets |
| Feature services | `wiring.billing_service()`, `telegram_service()`, `mcp_service()`, `memory_service()`, `model_key_store()` | `memory_service()` is `None` until fully configured |
| Private files | `wiring.read_private(path, minimum)`, `read_text(path)`, `live_secret()`, `panel_secret()`, `vault_keyring()` | `read_private` refuses symlinks and group/world-readable files |

A view module keeps a thin `service()` (or `_rpc(request)`) that calls the wiring function. That name is the seam tests patch; it must not grow logic.

## Three kinds of "is it on?", each with one owner

| Question | Owner | Stored in | Default | Ask with |
|---|---|---|---|---|
| Has the owner switched this capability on for the service? | `agentai_platform/switches.py` (`SwitchStore`, with preconditions and confirmations) | JSON file written by the ops dashboard | off | `wiring.switch_on('customer_execution')` |
| Is this protection in force for this account? | `agentai_platform/safety.py` | `safety_overrides` table, with expiry | **on**, fails closed | `wiring.safety_on(account, 'upload_limits')` or `safety.is_on(con, account, key)` inside a service |
| Is this feature rolled out to this account? | `agentai_platform/rollout.py` | one JSON file per feature: `{"<key>": true \| [account ids]}` | off | `wiring.own_model_on / mcp_on / memory_on(account)` |

They are deliberately not merged: a global capability switch with preconditions, a per-account protection that must fail closed, and an allowlist for a
staged rollout have different failure directions. What is shared is the reader of each. `switches.py` and `safety.py` stay standard-library-only because the
ops dashboard ships a copy of `switches.py` and the browse service imports `safety.py`.

The browser engine choice (`browse-engine.json`, `browse/service_main.py` `pick_engine`/`local_enabled`) is a fourth, different question (which engine, with
`local` on by default) and stays with the browse service.

## Rules that several features share (one implementation each)

| Rule | Owner | Used by |
|---|---|---|
| Request states and their groups (`ACTIVE`, `CLAIMED`, `LIVE`, `FINAL`) | `agentai_platform/request_states.py` (the state machine itself is `request_queue.py`, the only writer) | chat, queue, model-key lock, restore, sign-up admin; `lumina/src/lib/tasks.ts` mirrors the groups as `REQUEST_ACTIVE/CLAIMED/LIVE` |
| "A run a tool may act for": state is live, not `closing`, not `cancel_requested` (`live_run()`, `live_runs()`, `run_ended()`), optionally `funded` and `active_account` | `request_states.py` | browser tool, task progress, location, tool-origin proof, own-model relay admission, steering |
| "Is this address on the public internet?" and the rules for a hostname as typed | `agentai_platform/netsafe.py` | own-model endpoints (`model_keys.is_public`), remote MCP (`mcp_connections/network.py`), connector fetches (`ssrf.py`) |
| Browser job states (`LIVE`, `WAITING`, `FINAL`, `OVER`, `interrupted`) and writing a job's record | `agentai_platform/browse/job_states.py` | browse service, tool adapter, web routes, chat driver; `lumina/src/lib/live.ts` mirrors `LIVE` |
| Who a rollout file opens a feature to | `agentai_platform/rollout.py` | own model keys, remote MCP, long-term memory |
| Message length (`MAX_MESSAGE_CHARS`) | `agentai_platform/request_queue.py` | chat, driver, Telegram, HTTP field limits, `/v1/app` `limits` |
| Project and conversation limits | `agentai_platform/chat.py` (`MAX_PROJECTS`, `MAX_CONVERSATIONS_PER_PROJECT`) | chat service, `/v1/app` `limits` |
| Redaction of stored events | `agentai_platform/events.py` `redact` | events, activity |
| Scrubbing text sent to third parties | `agentai_platform/privacy.py` `scrub` | browser deciders, routing classifier |
| HTTP input shape, error-to-status mapping, audit of denials, what a classic form post gets back | `accounts/views.py` `endpoint` | every JSON route. `Denied` and `NotFound` both become the same audited 404, so a route cannot reveal whether another account's object exists. A form post's result is declared with `form=` on the route |
| Rate limits | `accounts/services.py` `rate` (+ the per-request limits in `middleware.py`) | views |

The customer's *browser* has its own destination rule (`browse/native_runner.py` `url_allowed`), on purpose: it decides which pages may be opened, allows
loopback in tests, and is governed by the `ssrf_guard` safety switch.

## Feature homes

Each feature has one service module (or package) in `agentai_platform/` and one view module in `accounts/`.

| Feature | Service | HTTP surface | Notes |
|---|---|---|---|
| Identity, sessions, operators, sign-up | `accounts/services.py`, `accounts/models.py` | `accounts/views.py`, `signup.py`, `middleware.py` | Django auth; the only feature whose logic lives in `accounts/` |
| Projects, conversations, sends, steering, goals | `chat.py`, `goals.py` | `accounts/chat.py`, `requests.py` | |
| Queue and serial slot | `request_queue.py`, `request_worker.py` | command `request_worker` | |
| One run of a request | `chat_driver.py`, `gateway.py`, `outcome.py`, `activity.py` | (worker only) | |
| Budget | `budget.py` | `accounts/usage.py` | |
| Task timeline | `events.py`, `task_progress.py` | `accounts/streams.py` | |
| Files and artifacts, runnable apps | `files.py`, `artifacts.py`, `storage.py`, `apps.py` | `accounts/files.py`, `app_views.py` | |
| Generated UI (documents, forms, plans) | `genui/` | `accounts/genui.py`, `media.py` | client: `lumina/src/gen` (renderer) + `lib/genui`, `components/genui` (stored blocks, plan editor) |
| Browser tasks | `browse/` | `accounts/browse.py`, `devices.py`, `panel.py`; `live/` | the browse service is its own root process |
| Tools served to cells | `tool_relay.py`, `browse/adapter.py`, `location.py`, `task_progress.py`, `longterm_memory.py`, `mcp_connections/relay.py` | command `tool_relay` | |
| Own model keys | `model_keys.py`, `model_catalog.py` | `accounts/model_key.py` | |
| Remote MCP connections | `mcp_connections/` | `accounts/mcp_connections.py` | |
| Long-term memory | `longterm_memory.py` | `accounts/longterm.py` | |
| Saved logins, saved choices | `vault.py`, `saved.py` | `accounts/vault.py`, `browse.py` | |
| Location sharing | `location.py` | `accounts/location.py` | |
| Billing | `billing.py` | `accounts/billing.py`, command `billing_worker` | |
| Telegram | `telegram.py` | `accounts/telegram.py`, command `telegram_worker` | |
| Connectors (OAuth, read-only) | `connectors.py`, `ssrf.py` | `accounts/connections.py` | |
| Safety switches | `safety.py` | `accounts/safety.py` | |
| Cells and their lifecycle | `lifecycle/` | `accounts/lifecycle.py`; host entry points | |
| Backups, monitoring, restore | `ops/` | CLI only | |
| JEV routing and display observers | `routing/` | (worker only) | |
| Parked product modules, kept on purpose | `durable.py`, `memory.py`, `schedules.py`, `watchers.py`, `skills.py`, `optimization.py`, `policy_check.py`, `lifecycle/broker.py` | disabled routes in `urls.py` | schema-backed and tested; not wired to a customer surface |

## Adding a feature

1. **Service.** Put the logic in `agentai_platform/<feature>.py` as a class that takes `store` and its collaborators. Scope every query by `account_id`;
   take a `Principal` where a person acts. Do not read settings there.
2. **Gate.** Pick the one question that applies (table above). A staged rollout: add a `*_FILE` setting, call `rollout.enabled(path, '<key>', account)`
   from a `wiring.<feature>_on(account)` function. Never add a fourth switch mechanism.
3. **Wiring.** Add one `wiring.<feature>_service()` that builds it from settings. If a worker needs it too, the worker calls the same function.
4. **Routes.** Add `accounts/<feature>.py`: views wrapped in `@endpoint`, starting with `denied = customer(request)`, calling the service through a
   module-level `service()` that returns `wiring.<feature>_service()`. Raise or let through `NotFound`; do not write a per-route 404. Register in `urls.py`.
5. **Tool for the assistant** (if any): act only for a live run. Use `request_states.is_live_run(con, account, request, funded=…, active_account=…)`;
   register the tool in `tool_relay.py` and the builder in `commands/tool_relay.py`.
6. **Outbound connection for a customer** (if any): resolve, check every address with `netsafe.is_public_address`, connect to the checked address, never
   follow redirects without re-checking.
7. **Schema.** New numbered file in `platform/migrations/` (never edit an existing one: they are checksummed).
8. **Client.** Call `/v1/...` through `lib/api.ts`; read availability from `/v1/app` `features`; use `lib/tasks.ts` for anything about a request's state.
9. **Tests.** Service tests in `platform/tests/`, route tests in `platform/accounts/test_<feature>.py`. Patch the view module's `service` name to stub it.

## What the consolidation of 12 November 2026 changed, and why

| Before | Now | Why it matters |
|---|---|---|
| Five differently wired `ChatService` constructions (web, Telegram view, Telegram worker, files, project creation); only one could price or steer. `files.py` built one it never used. | `wiring.chat_service()` everywhere; the record-only variant is explicit and named (`intake_chat_service`). | A surface can no longer silently get a weaker service; the Telegram limitation is a visible decision instead of an accident. |
| `SwitchStore(settings…)` rebuilt in seven places; `AccountStore(connection.settings_dict['NAME'])` about fifty times; six copies of "the request's principal". | `wiring.switch_on`, `wiring.store`, `wiring.principal`. | One place to change how any of them is built. |
| The database adapter lived in a view module (`accounts/lifecycle.py`). | `accounts/store.py`. | Views and the adapter no longer depend on each other. |
| Three copies of the rollout-file reader with small differences. | `rollout.py`; each feature keeps its file, key and helper. | Same answer for the same file; adding a rollout is three lines. |
| Three "public address" rules. Own-model endpoints accepted NAT64 addresses (an internal IPv4 host inside a global-looking IPv6 address) that remote MCP refused. | `netsafe.is_public_address`, the strictest of the three, for all. | A deliberate security correction: one answer to "may Lumina's servers connect there for a customer". |
| The "live run" condition written out in eight queries, some checking the reservation or the account and some not. | `request_states.live_run()` plus named `funded` / `active_account` conditions. Each caller's conditions are unchanged. | The rule has a name; the differences between callers are visible instead of accidental. |
| `/v1/app` reported `max_conversations_per_project: 10` while the server enforces 100; the message limit was the literal `16000` in seven places. | Both read the owning constant. | The client contract tells the truth. |
| A route had to remember `except NotFound: raise Denied()`; forgetting it produced a 500. | `endpoint` maps both to the same audited 404. | Uniform-404 enumeration defence no longer depends on each route. |
| `endpoint` chose the result of a classic form post from the view function's name (`chat_*`, `cancel`, `link`, `ticket`, ...), so a new view named `cancel` inherited another feature's redirect. | Each route declares it: `@endpoint([...], form='chat')`. An unknown value fails at import. | No behaviour hidden in a function name. |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` assigned twice in settings (the first value was dead). | One assignment. | No false impression of a 200 kB limit. |

Behaviour was otherwise kept: routes, payloads, file formats and locations, schema, switch semantics and the worker processes are unchanged. No file under
`platform/migrations/` was touched.

## Deliberate non-changes (tradeoffs)

- **`agentai_platform/` stays a flat package of ~45 modules.** Regrouping it into sub-packages would improve first-read navigation but breaks every import,
  the systemd `-m agentai_platform.…` entry points, `bin/push-release.py` file overlays and `bin/update-ops-dashboard.py` (which copies `switches.py` by
  path), for no change in behaviour. The table above is the map instead.
- **Dense one-line style in older modules** (`request_queue.py`, `budget.py`, `views.py`) is left alone; it is consistent within those files and they are the
  money and identity paths.
- **Three encryption keyrings** (`model_keys.ModelKeyring`, `vault.Keyring`, `lifecycle/secrets_custody.py`) are not merged: each binds stored ciphertext to
  its own key derivation labels, so merging risks making stored customer secrets unreadable for a cosmetic gain.
- **Two socket RPC clients** (`bridge_client.BridgeRpc`, `browse/client.BrowseRpc`) stay separate: different wire shape, timeouts and error meaning.
- **The classic server-rendered pages** (`/account/...`, `accounts/templates`) remain beside the React app (see open decisions).

## Open decisions and known rough edges

These were found or re-confirmed while reading the code for this work. None was changed, because each needs an owner decision or touches the money path.

1. **Telegram messages are stored but never run.** `intake_chat_service()` has no price and no admitting ledger, so a Telegram message waits unfunded.
   Finishing it means using `chat_service()` there and delivering results back; hiding it means removing the ingress. (Register: BE-007.)
2. **The `budget_caps` safety switch does not do what the app says it does.** The Safety page tells the owner that with it off "tasks start with no limit
   check and no money held". In the code, admission is written twice in `chat.py`: `send` never reads the switch (limits still apply), and `_admit` (plan
   phases, goal turns, retries) reads it and then skips the reservation, after which the driver refuses the task as "not admitted", so it never starts.
   Nothing tests the switch. Fixing it means one admission function and a decision about what "caps off" funds a task with; the obvious mechanism (the
   nominal unmetered reservation own-key tasks use) collides with the own-model relay, which reads that amount to tell whose model a task runs on.
   Left unchanged: it is the money path and needs an owner decision.
3. **The classic server-rendered pages** (`/account/...`) still exist beside the React app and share the JSON routes through `endpoint(form=…)`.
   Whether to retire them is a product decision; until then every route that a classic form posts to must declare its `form` result.
4. **Waiting-cancel and the claim/admission race** (register M-01 / BE-006), the park limit (AG-005) and unreadable-usage policy (AG-007) are unchanged:
   see [current findings](findings.md).
5. **`tests/test_privacy_policy.py` has a known-gap deadline of 2026-11-11 that has passed**: deploy the fix it names, run `platform/privacy/check_server.py`,
   then delete `server.known_gap` from `platform/privacy/facts.json`.
