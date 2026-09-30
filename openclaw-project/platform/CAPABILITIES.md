# Installed capability matrix — observed 2026-09-29

[Live runtime/CLI inventory](../plans/product/runtime-inventory.json) and
[sanitized policy/source inventory](../plans/product/capability-inventory.json)
are exact source records. Both are read-only and include no chats/credentials.
Local Python3.14.4; observed server Python3.12.3/SQLite3.45.1. Proxy LiteLLM
1.102.1; PostgreSQL16.10. OpenClaw2026.9.6 (eb377ac), custom SDK-peer image
`sha256:de9b14d86157547f83ddcf52414fa749417f9de6bb43d02c89a8d532c541a444`.
Proxy/database digests remain exactly those in runtime-inventory.json.

| Capability | Exact observed path | Verified boundary / unresolved proof |
|---|---|---|
| Runtime/config | `node dist/index.js --version`; `config validate --json` | Live valid schema/no warnings; no config change |
| Agent roles | Native `agents.entries` contains main/researcher/browser-worker/critic/codex-builder/codex-debugger | Main mode off; builder/debugger all; worker inheritance recorded; config metadata is not full effective runtime denial proof |
| Gateway diagnostics | `gateway health/probe/call` in installed help | Private WebSocket Gateway; product client not activated or authenticated-probed |
| Native session send/history/abort | Installed `/app/dist` contains `chat.send`, `chat.history`, `chat.abort` names (6/6/4 matching JS files) | Source advertisement only; request/response scopes/live completion/cancel semantics remain Phase6 probes |
| Session event subscription | Source contains `sessions.subscribe`, `sessions.messages.subscribe` (7/1 files) | Candidate supported path; not a customer-scoped stream proof |
| Stored session operations | `sessions list/tail/archive/compact/delete/export-trajectory` in help | Do not export/list private bodies for inventory; reuse owner evidence only where applicable |
| Fleet lifecycle | `fleet create/start/stop/restart/status/list/logs/backup/restore/upgrade/rm/doctor` | Advertised experimental host-local mechanism; no customer cell was created; not remote VM/cloud orchestration proof |
| Native backups | `backup` advertised, operator timer active | Scheduled archive success/restore/RPO/RTO not inferred from active timer |
| Memory/goals/schedules | `memory`/`automations` advertised; native setup in historical plans | Selective behavior/controller/unattended policy pending product adaptation/proof |
| Browser/Brave | Global browser enabled; worker allow/deny metadata in inventory, existing live evidence | Current customer-node/credential isolation not established by owner proof |
| Coding/ACP | Existing native code/plugin/harness artifacts and historical builder probes | Commercial metering, actual reviewer confinement/auth and final accepted workflow missing |
| Proxy caps | Historical $2/24h+$25/30d deny/store-outage proof | Inventory did not expose key or live budget rows; owner backstops do not prove all customer routes |
| Dashboard live/files | Owner dashboard unit active; 8B sources/evidence | Customer identity/event scoping/artifact capture and intermediate-file-race proof need future work |
| Foundation app/control | Actual unprivileged private smoke in server-smoke.json | Readiness true/API401,128MiB/no swap caps; customer execution remains false |

Official current documentation is ahead of or may differ from installed
behavior. [Session control](https://docs.openclaw.ai/gateway/protocol/rpc-session-control)
and [event bootstrap](https://docs.openclaw.ai/gateway/protocol/rpc-bootstrap-and-events)
are implementation entry points; method names do not imply exact request schema
or auth compatibility. `fixtures/gateway-capabilities.json` marks all live
adapter capabilities unverified/disabled. Product Phase6 must freeze/probe exact
installed contract before send/history/events/abort. Do not invent HTTP session
URLs based on the unverified prior viewer branch.

The installed Fleet advertises an experimental cell supervisor. [Tenant docs](https://docs.openclaw.ai/gateway/multi-tenant-hosting)
require complete per-tenant runtimes and explain trust/host-local/egress limitations.
Use a separate VM customer boundary; do not infer hostile tenant isolation from
session routing or install/remove experimental cells in the owner host.
