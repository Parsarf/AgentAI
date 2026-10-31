# Structural baseline from CBM — 31 October 2026

Scope: local working tree on `product-phases-6-11`, HEAD `823465a`, including
existing modified and untracked application source. This is architectural
reconnaissance before structural changes, not a production verification or a
fresh runtime/test result. No application source was changed.

## Evidence and limits

Refreshed the existing index with `lumina-index refresh`; subsequent status was
FRESH. CBM project `Users-parsa-AgentAI-openclaw-project` reported 12,279 nodes,
50,213 relationships, 919 File nodes, 601 classes, and 73 Table nodes.
Used bounded `get_architecture overview`, class/symbol `search_graph`, and
outbound `trace_path` on `ChatDriver.execute` and `BrowseService._run`.
Read the relevant source to check the graph's application boundaries.

CBM indexes `openclaw-project`, not the entire workspace. Its exclusions include
secrets, dependencies, runtime data, evidence, public media, vendored UI source,
and research directories. Coverage metadata says `recording_status: truncated`
and directory coverage queries report `coverage_unavailable`; this does not
establish exhaustive indexing. Django route handlers, dependency injection,
cross-process calls, and graph name collisions require source inspection.
Root-level JEV prototypes and product/operational documents were inspected
outside the graph. No production state is inferred from the local checkout.

## Workspace map

| Location | Responsibility |
|---|---|
| `openclaw-project/lumina` | React/Vite customer UI: chat, tasks, live browser view, files, settings, generated UI. |
| `openclaw-project/platform/accounts` | Django authentication, tenant-scoped HTTP views, routing, settings, management commands. |
| `openclaw-project/platform/agentai_platform` | Product services: chat, queue, budget, events, artifacts, safety, vault, billing and integrations. |
| `platform/agentai_platform/lifecycle` | Provisioning, host supervisor, cell bridge, runtime configuration, isolation and receipts. |
| `platform/agentai_platform/browse` | Browser jobs, decision loop, native/device transports, handoff and live-view integration. |
| `platform/agentai_platform/genui` and `lumina/src/gen` | Server validation/state/plan execution and client rendering, respectively. |
| `openclaw-project/browse` | Hosted JavaScript browser runner plus the in-progress customer Chrome extension. |
| `openclaw-project/lumina-character` | Parallel character UI implementation; not the SPA imported by `lumina/src/App.tsx`. Preserve pending an explicit consolidation decision. |
| `openclaw-project/dashboard`, `bin`, `deploy`, `platform/deploy` | Owner dashboard, operator tools, deployment templates, edge configuration and release tooling. |
| `openclaw-project/browser-opt`, `research-opt`, `experiments` | Optional adapters/experiments; individual runtime connections need checking before removal. |
| `jev-browser` | Separate local screenshot-driven JEV browser prototype, with its own runner and dashboard. |
| `jev-window-core` | Separate macOS window-control prototype: Python loop/model plus Swift capture/input helper. |
| `product`, `phase-prompts` | Product contract, designs and historical/planned execution instructions. |
| `docs/codebase-audit`, `openclaw-project/docs/architecture` | Audits, current architecture reports and historical findings. |
| `output`, `lumina-cost-audit`, `backups`, evidence folders, archives | Generated work, operational records and preserved artifacts; not evidence of active application imports. |

Paths beginning `platform/` in the table are relative to `openclaw-project/`.

## Connected execution paths

1. `lumina/src/App.tsx` defines the `/app` SPA. `state/data.tsx` owns shared
   identity/request/chat state; `lib/api.ts` and page/components call HTTP APIs.
2. `platform/accounts/urls.py` maps requests to account views. `accounts/chat.py`
   builds the account store, queue, ledger, events and optional native gateway
   used by `ChatService`. Flags determine execution and browser availability.
3. `accounts/management/commands/request_worker.py:build_worker` constructs
   `RequestWorker`, `ChatDriver`, gateway factory, artifacts, generated UI,
   browser RPC and optional routing/display observers. The command calls ticks
   only while customer execution is enabled.
4. `RequestWorker` claims/reconciles/parks queued work and invokes the injected
   driver. `ChatDriver.execute` admits, begins or reasserts delivery, then
   supervises the native run. It also coordinates cancellation, usage,
   transcript/output capture and settlement through its other methods.
5. `NativeGateway` uses `BridgeRpc` to reach the cell bridge. Runtime browser
   tools enter the tool relay and browser service; these process boundaries
   cannot be reconstructed from CALLS edges alone.
6. `BrowseService._run` creates `Session`, `Ladder`, policy and `BrowseRunner`.
   `browse/service_main.py` wires hosted runner, cell-native browser and customer
   device transports. `pick_engine` considers configuration, account selection,
   customer preference and device connectivity. Available code is not proof
   that a backend is deployed.
7. Caddy routes customer HTTP to port 18800, live frames to 18801, and extension
   WebSocket `/v1/device` to 18802. Its scene-file handler serves public media
   separately. These are checked-in configuration values.
8. `genui/runner.py:PlanRunner` advances approved plan phases through normal
   chat requests rather than starting native runs directly. Worker follow-up
   also invokes goal continuation.

## Structural seams to use in the next change

- **Composition:** five production `ChatService(...)` construction sites exist
  in account chat, views, files, Telegram views and Telegram worker. Their
  arguments differ. A shared factory is a plausible first extraction, provided
  each entry point's current capabilities remain explicit.
- **Execution:** `ChatDriver` spans lines 51–901 in this snapshot. Delivery,
  native-run supervision, recovery, output handling and settlement are natural
  candidate boundaries. Preserve queue fences, request/delivery identities,
  reservations and transactional behavior through any extraction.
- **Browser:** distinguish the decision loop from job ownership and transport.
  Hosted runner, native-cell browser and customer extension already have
  different implementations. Root-level prototypes are separate products of
  experimentation, not interchangeable execution backends by default.
- **UI:** `App.tsx`, shared state, chat page, generated UI and live browser
  controls are separate concerns. Parallel character UI and stored legacy-card
  rendering need a feature inventory before consolidation.
- **Persistence:** raw SQL migrations under `platform/migrations` coexist with
  Django migrations. `AccountStore` adapts service queries to Django's
  connection/transactions. Existing SQL migrations are checksummed; moving
  modules must not rewrite their contents or accidentally change transaction
  ownership.
- **Verification:** CI has account tests, migration drift checks, a blocking
  platform list, report-only platform modules, UI checks/build, and report-only
  browser tests. A green CI run does not mean every execution/browser test is
  blocking. Run checks for the particular boundaries changed.

## Starting references

- [Current architecture index](../../openclaw-project/docs/architecture/README.md)
- [Native execution](../../openclaw-project/docs/architecture/native-execution.md)
- [State and recovery](../../openclaw-project/docs/architecture/state-and-recovery.md)
- [Account routes](../../openclaw-project/platform/accounts/urls.py)
- [Worker composition](../../openclaw-project/platform/accounts/management/commands/request_worker.py)
- [Chat driver](../../openclaw-project/platform/agentai_platform/chat_driver.py)
- [Browser composition](../../openclaw-project/platform/agentai_platform/browse/service_main.py)
- [CI](../../.github/workflows/platform.yml)

Current source takes precedence over older README status claims and audit
line numbers. Existing uncommitted UI/browser work was preserved. No tests,
paid model calls, server commands, deployments or cleanup were performed.
