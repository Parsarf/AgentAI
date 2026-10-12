# Execution activation — customer messages run on the live assistant

**Status (2026-10-13):** built, deployed and exercised on the production server; owner's own account only. Acceptance remains Phase 15.
Evidence: [`evidence/product/execution-activation/20261013T0300Z/manifest.json`](../../evidence/product/execution-activation/20261013T0300Z/manifest.json). Runbook: `platform/OPERATIONS.md` section 12.

## What changed

| Piece | What it does |
|---|---|
| `gateway.py` `NativeGateway`, `bridge_client.py` | Gateway protocol 4 client over an injected rpc; the app talks only to a private unix socket |
| `lifecycle/cell_bridge.py` (+ `_main`) | root service; maps account → cell, allowlisted/validated methods only, relays through `docker exec` into the cell's own loopback Gateway (the only path with operator scopes); `usage.snapshot` and `cell.status` |
| `lifecycle/cell_config.py`, `litellm_admin.py` | per-cell LiteLLM virtual key ($25 / 35 d, model allowlist, rate limits), Gateway model-route config, DNS after start |
| `chat.py` `ChatDriver` | deadline polling loop, lease heartbeat, timeout → abort + failed, usage reconciled from LiteLLM key spend (stored baseline survives crashes), reserved-amount fallback, clean failure of requests that never reached a runtime, `abandon` |
| `request_worker.py`, `manage.py request_worker` | claims one request, runs it, reconciles stuck ones |
| `lifecycle/worker.py`, `coordinator.py` | system `start` (wake) for waiting requests, short idle when another account waits, realign of cells whose container is gone, `host_create` for provisioning |
| `switches.py` | new owner switch `customer_execution` |
| `accounts/chat.py` + template | priced sends and a live status/auto-refresh only while the switch is on |
| `deploy/` | `agentai-model-proxy`, `agentai-cell-bridge`, `agentai-request-worker` units; cell engine without iptables management; firewall routes; loopback LiteLLM port |

## Decisions / assumptions to confirm
- The switch is ON after testing. Turn it off in the dashboard if you want to hold customer execution until acceptance.
- Per-message reservation $1 and service allocation $50 (2 x $25) are defaults, changeable in `accounts.env`.
- A cell's agent has shell and web tools inside its own sandbox (gVisor, capped volume, no private-network egress, only its own capped model key). Browser and coding stages (broker) are tested but not yet reachable from chat.
