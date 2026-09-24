# Always-on server deployment plan

Status: prepared, not deployed. The owner requires the agent to keep working
while the Mac is off. SSH authentication is pending.

## Chosen host

The owner already has an IONOS VPS at `69.48.206.62` with Ubuntu 24.04,
2 vCPUs, 4 GiB RAM, and a 120 GiB disk. TCP port 22 responds. The current
ED25519 host key matches the key already recorded on this Mac (fingerprint
`SHA256:HBaF3x2ux+XYjWcTUFIuCHzueudk5GK0Gbe65zctehY`), but public-key
authentication for `root` failed. Obtain the private initial password through
the owner-provided mode-0600 intake file, inspect existing services and free
resources first, then install a dedicated SSH key. No new VPS purchase is
needed. Four GiB may constrain concurrent browser and sandbox sessions; cap
concurrency at one until measured, and add swap if the host lacks it.

Do not expose OpenClaw's Gateway, bridge, or Teams ports publicly. Reach the
Control UI through an SSH tunnel or a private authenticated network.

The official OpenClaw Docker image and Compose file from the pinned v2026.9.6
source tag are the proposed runtime. The browser image is
`ghcr.io/openclaw/openclaw:2026.9.6-browser`; the Docker sandbox must be built
and verified on the server. The official Compose file publishes three ports by
default, so bind all three to `127.0.0.1` on the host before starting it:

```dotenv
OPENCLAW_GATEWAY_PORT=127.0.0.1:18789
OPENCLAW_BRIDGE_PORT=127.0.0.1:18790
OPENCLAW_MSTEAMS_PORT=127.0.0.1:3978
```

Inspect `docker compose config` and `ss -lnt` to verify the effective host
bindings. Do not rely on a host firewall alone: Docker's published ports can
bypass ordinary firewall rules.

## Production gates

1. Authenticate to the existing VPS and inspect its current services, memory,
   free disk, Docker Engine and Compose. Preserve unrelated workloads. Pin the
   OpenClaw release and browser image; do not use `latest`.
2. Create private persistent state, workspace, and backups on the server. Move
   only the Anthropic API key and Telegram bot token needed for this agent over
   SSH into OpenClaw's protected store. The Mac's staging state is not a
   production backup. Configure SecretRefs and run `secrets audit --check`.
3. Set the Anthropic workspace's monthly spend limit to $25, then route **all**
   model traffic through an admission control that enforces $2/day and
   $25/month. OpenClaw usage reports alone do not enforce limits. A candidate
   is a local LiteLLM proxy with PostgreSQL, budget reservation, concurrent
   daily/monthly windows, and fail-closed enforcement; its exact OpenClaw
   provider route and deny behavior must be tested before a paid call. The
   versioned OpenClaw config template selects only `litellm/*` models and
   expects a private `LITELLM_API_KEY` SecretRef. Put the real Anthropic key
   only in LiteLLM's server-side secret environment. Configure a dedicated
   virtual key with `budget_limits` for `24h`/`2.00` and `30d`/`25.00`, keep
   budget reservation enabled, and set `fail_closed_budget_enforcement: true`.
   Verify a request is rejected at each cap and when the budget database is
   unavailable.
4. Resolve the existing Telegram polling conflict for `@Keighobad_bot`, set a
   numeric owner `allowFrom` and `commands.ownerAllowFrom`, and keep groups
   disabled. Verify that a different account cannot reach the agent.
5. Build the Docker tool sandbox and browser image, then verify effective
   containment, tool denials, approval timeouts, and injection resistance.
6. Run a low-cost model reply, browser and coding workflow, independent
   review, scheduled recovery, backup restore, security audit, and a server
   restart. Confirm the bot still works with the Mac shut down.

The existing Python AgentAI service stays intact until these gates pass and
the owner chooses to retire it. Running both with the same Telegram token
causes polling conflicts; do not launch the new poller until the old one is
located and stopped or a dedicated token is chosen.

## Sources checked

- [OpenClaw Docker deployment](https://docs.openclaw.ai/install/docker)
- [OpenClaw v2026.9.6 Compose file](https://raw.githubusercontent.com/openclaw/openclaw/v2026.9.6/docker-compose.yml)
- [OpenClaw Docker sandbox](https://docs.openclaw.ai/install/docker/sandbox-and-troubleshooting)
- [LiteLLM budget windows and fail-closed reservation](https://docs.litellm.ai/docs/proxy/users)
- [OpenClaw LiteLLM provider route](https://docs.openclaw.ai/providers/litellm)
- [Anthropic workspace spending limits](https://support.claude.com/en/articles/9796807-creating-and-managing-workspaces-in-the-claude-console)
