# Phase 1 deployment bundle

Status: fresh-deployment template. The existing VPS deployment has been
inspected and hardened through Phase 2; live evidence is in `../BUILD_LOG.md`.
Gate 1 awaits the remaining Telegram access checks, and Gate 2 awaits the
owner's live approval-card/denial interaction. Do not run the fresh-state
preparation script over the existing server deployment.
The owner's instruction on 2026-09-25 authorizes proceeding with Phase 1.

## Layout and activation

`docker-compose.production.yml` preserves the draft's three image digests.
Their version, architecture and provenance still require registry/image
inspection on the server. Do not substitute a moving tag.

- PostgreSQL uses a dedicated volume and an internal network. It receives only
  its own database credentials.
- LiteLLM receives the Anthropic key and its dedicated database URL. The
  canonical config is `../config/litellm.example.yaml`; the older
  `deploy/litellm.yaml` draft is not mounted. Its API has no published host port.
- Gateway activation requires explicitly selecting `openclaw-gateway` or the
  `agent` profile. All published ports bind to host loopback. A profile prevents
  accidental activation in ordinary Compose startup; it is not an access rule.
- The maintenance CLI shares a running Gateway's network namespace, matching
  the [pinned upstream Compose layout](https://raw.githubusercontent.com/openclaw/openclaw/v2026.9.6/docker-compose.yml).
  Before startup, use the offline wrapper instead.
- Phase 1's original chat-only policy has since been extended by the live
  Phase 2 policy below. The Gateway Docker socket is mounted only in the
  trusted Gateway container; never mount it into an agent sandbox.

## Phase 2 sandbox and approvals

Build the minimal sandbox image from the pinned Debian base in
`deploy/Dockerfile.sandbox`:

```sh
docker build -t openclaw-sandbox:bookworm-slim -f deploy/Dockerfile.sandbox deploy
```

Before enabling the Gateway Compose service, confirm `/usr/bin/docker` is the
Docker CLI for the installed Engine and set
`OPENCLAW_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)` in the private
Compose environment. The Gateway runs as the unprivileged `node` user and is
added to that numeric group. The read-only Docker CLI bind and socket mount are
required by OpenClaw's Docker sandbox backend. This grants the Gateway process
host Docker control, so keep Gateway access private and never mount the socket
inside a sandbox.

The live Phase 2 policy runs every agent session in its own Docker sandbox
with a writable session workspace, no network, a read-only root filesystem,
all Linux capabilities dropped, and bounded memory, CPU, and process count.
Only session status, workspace file tools and sandbox `exec`/`process` are
available. Browser, Gateway/configuration, messaging, plugins, node control,
automations and cron remain unavailable. Thus unattended runs cannot be
created through OpenClaw's automation tools in this phase.

Elevated execution is restricted to the Telegram owner ID and requires a
Gateway host approval for every command (`allowlist` + `ask: always`, with an
empty allowlist). If no connected approval UI is available or a request times
out, it is denied. The Control UI's Settings → Nodes → Exec approvals page
shows the host policy; connected Control UI operator clients receive pending
cards. Telegram approval delivery is not enabled by assumption. Verify it
separately before relying on chat approvals. See the official
[sandboxing](https://docs.openclaw.ai/gateway/sandboxing/docker-backend),
[exec approvals](https://docs.openclaw.ai/tools/exec-approvals), and
[elevated mode](https://docs.openclaw.ai/tools/elevated) references.

Run `openclaw sandbox explain --agent main`, `openclaw sandbox list`,
`openclaw doctor`, `openclaw secrets audit --check`, and
`openclaw security audit` after changing the live policy. Record both the
actual pending approval card behavior and the no-UI deny/expiry behavior in
`BUILD_LOG.md`; an approval configuration alone does not pass Gate 2.

## Prepare on the VPS

First inspect existing workloads, memory, disk, Docker and port occupancy.
Keep this checkout in a private directory on the VPS. For a fresh installation,
run from `openclaw-project/`:

```sh
python3 bin/prepare-phase1.py --telegram-owner-id YOUR_NUMERIC_USER_ID
```

The owner-ID variable is `TELEGRAM_USER_ID`. When it is exported into the
environment, the script accepts it without `--telegram-owner-id`.
Alternatively pass `--env-file /path/to/.env`; the script reads only that
numeric assignment and does not import provider or login credentials.

The script refuses existing state, creates private directories and writes a
config with Telegram disabled. It never copies credentials or starts services.
Before container commands, confirm the pinned image's user ID and assign
`deploy/openclaw-state` and `deploy/workspace` to that user on the server.

Create mode-0600 `deploy/secrets/postgres.env` and
`deploy/secrets/litellm.env` from their example files. The passwords must agree,
and the database URL must point to the `postgres` service. Generate a dedicated
LiteLLM master key. Do not give that master key or the Anthropic key to OpenClaw.
These env files use Compose's `raw` format: enter literal values without
wrapping quotes or interpolation. Preserve `LITELLM_SALT_KEY` during upgrades.
Private files and runtime state are gitignored. Do not print expanded
Compose configuration with credentials; use `docker compose config --quiet`.

Native OpenClaw command wrappers:

```sh
# Before starting the Gateway: no dependent service is started.
sh bin/openclaw-server offline config validate
sh bin/openclaw-server offline secrets store set OPENCLAW_GATEWAY_TOKEN
sh bin/openclaw-server offline secrets store set TELEGRAM_BOT_TOKEN
```

Use the native masked prompts. Store the dedicated virtual key later as
`LITELLM_API_KEY`. All three config credentials remain store SecretRefs.
See [Secrets CLI](https://docs.openclaw.ai/cli/secrets).

## Spending gate before live traffic

1. Confirm the Anthropic workspace's independent $25 monthly ceiling.
2. Start only `postgres` and `litellm`. Verify the proxy's installed version
   supports the configured reservation and fail-closed controls.
3. Create a dedicated virtual key through `/key/generate` using
   `openclaw-key.request.json`. Save the response privately; never log the key.
   The requested model allowlist excludes all other routes. Budget windows
   are $2 daily and $25 monthly, resetting in UTC; keep concurrency at one.
4. Prove daily denial and monthly denial independently with disposable keys
   and tiny temporary windows. Verify from provider/audit evidence that a
   denied request never reached Anthropic. Exercise the outage path after
   stopping only this bundle's budget database and allowing cached budget
   state to expire. An unverifiable budget must reject.
5. Test a bounded cheap request only after the independent provider ceiling
   and admission control are verified; record its actual cost. Confirm the
   production key retains $2/$25 limits, then import it into OpenClaw's store.

These are required runtime probes, not completed results. Current references:
[OpenClaw LiteLLM route](https://docs.openclaw.ai/providers/litellm) and
[LiteLLM budget enforcement](https://docs.litellm.ai/docs/proxy/users).

## Owner access and Gate 1 evidence

Resolve the existing Telegram polling conflict before enabling the channel.
The generated config has the owner's numeric `allowFrom` and
`commands.ownerAllowFrom`, disabled groups and a disabled channel. After the
spending gate, enable it with the native CLI and validate:

```sh
sh bin/openclaw-server offline config set channels.telegram.enabled true
sh bin/openclaw-server offline config validate
sh bin/openclaw-server offline secrets audit --check
sh bin/openclaw-server offline security audit
```

Start the Gateway explicitly only after those checks have passing dispositions.
Open the UI through an SSH tunnel from local port 18789 to the server's
127.0.0.1:18789. Keep normal token authentication and browser device pairing.
Use [Telegram's numeric owner controls](https://docs.openclaw.ai/channels/telegram/access-control).

Record all of the following in `BUILD_LOG.md` before marking Gate 1 passed:

| Check | Required evidence | Current state |
|---|---|---|
| Host and image identity | Resource inventory, pinned versions/digests | Pending |
| Private listeners | Effective Compose bindings and `ss -lnt` | Pending |
| Gateway auth | Owner UI/device succeeds; unauthenticated access denied | Pending |
| Telegram owner access | Owner reply; other identity denied; no polling conflict | Pending |
| Budget | Both caps deny; database outage rejects; actual spend | Pending |
| Diagnostics | `doctor`, secrets audit, security audit, channel/model checks | Pending |
| Reversibility | Private backup before changing existing state | Pending |

After startup, native checks use `sh bin/openclaw-server live ...`.
Do not run model probes with `--probe` until the spending gate is proven.
Inspect diagnostics privately and sanitize evidence before adding it to git.
Rollback stops this bundle's Gateway and retains its state and database volume;
never use `down --volumes` as rollback.
