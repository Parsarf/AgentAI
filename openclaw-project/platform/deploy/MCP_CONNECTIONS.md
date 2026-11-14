# User-managed remote MCP connections

Integrations → MCP connections uses one connection path for presets and custom
servers. It supports public HTTPS Streamable HTTP servers with OAuth, a bearer
API token, a named API-key header, Basic authentication, or no authentication. Automatic detection is the default. Asana is the first preset:
`https://mcp.asana.com/v2/mcp`.

The implementation uses the official Python SDK, pinned to `mcp==2.3.0` with
hashed runtime dependencies in `requirements.lock`. Sources checked for this
implementation:

- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP authorization specification](https://modelcontextprotocol.io/specification/latest/basic/authorization)
- [Asana's MCP integration requirements](https://developers.asana.com/docs/integrating-with-asanas-mcp-server)

## The owner's switch (off until turned on)

Remote connections are **off for everyone** until the owner turns them on. The switch is the file `/var/lib/agentai-platform/mcp-connections.json` (owned by `agentai-platform`, mode 640; override the path with `AGENTAI_MCP_SWITCH_FILE`), read on every request:

```
{"mcp_connections": true}                    every account
{"mcp_connections": ["<account id>", ...]}   only those accounts (try it on the owner's own account first)
anything else, or no file                    nobody
```

What "off" does: the Integrations page does not show the section (`features.mcp` is false in `GET /v1/app`), every `/v1/account/mcp*` route answers `404 unavailable`, an OAuth callback that arrives is turned away, and the relay stops listing or running `lumina_mcp_discover`, `lumina_mcp_call` and the namespaced remote tools. Turning it off takes effect on the next request; connections, tools and approvals already stored are kept, not deleted. Tests: `tests/test_mcp_switch.py`, `accounts/test_mcp_connections.py`.

## Configuration before release

No production configuration was changed during implementation. Run the normal
hashed dependency installation and `manage.py migrate`; both the web service and
tool relay need this release. Publish the updated `deploy/vercel/public/privacy.html`
together with or before making MCP connections available. Do not expose OAuth
callback query strings, Authorization headers, provider bodies or tokens in proxy
or application logs. The checked-in Gunicorn/Caddy configuration has no access log;
application access events contain request IDs and status only.

| Variable | Purpose |
| --- | --- |
| `AGENTAI_PUBLIC_ORIGIN` | The canonical customer website origin, used for the exact OAuth redirect URI. |
| `AGENTAI_MCP_KEY_FILE` | Optional dedicated AES-GCM key file using the existing model-key keyring format/custody. Falls back to `AGENTAI_MODEL_KEY_FILE`, then a domain-separated key derived from `AGENTAI_SESSION_SECRET`. |
| `AGENTAI_MCP_OAUTH_CLIENTS_FILE` | Optional private regular JSON file, mode 0600, mapping exact server URLs to operator-registered OAuth clients. Maximum 64 KiB. Never put this file in the assistant workspace. |
| `ASANA_MCP_CLIENT_ID` | Client ID of a registered **Asana MCP OAuth app**. |
| `ASANA_MCP_CLIENT_SECRET` | Its client secret, supplied only to the host web service and tool relay. |

Use a stable encryption key. The current keyring does not automatically migrate
existing ciphertext when its configured key is replaced; retain the old key until
connections are deliberately reauthorized. Reconnecting a bearer connection can
replace its token; disconnect remains possible even if old ciphertext cannot open.

Register the exact callback URI:

```
${AGENTAI_PUBLIC_ORIGIN}/v1/account/mcp/callback
```

For the customer production origin this would be
`https://getlumina.pro/v1/account/mcp/callback`. Do not substitute the backend
hostname: the callback's browser binding cookie belongs to the customer website.
The main session remains SameSite=Strict. A random Secure, HttpOnly, SameSite=Lax
cookie binds the top-level OAuth return to the original, still-valid sign-in and
account. State and PKCE are encrypted/persisted, expire after ten minutes, and are
consumed once. Starting another authorization in the same browser replaces its
callback binding; complete one authorization at a time.

### Asana

Asana v2 requires a pre-registered MCP OAuth app in its developer console; it does
not offer dynamic client registration. Set its redirect URI above, client ID and
secret, and configure distribution/workspace access in Asana. The issuer is
`https://app.asana.com`. Users then sign in with their own Asana accounts; users do
not enter the shared OAuth app secret. Without these two environment variables,
Asana is shown as requiring operator setup and cannot falsely become connected.
A connection created before app setup can be tested again after configuration.

### Other OAuth servers

The SDK performs protected-resource and authorization-server discovery, PKCE,
issuer checks, supported dynamic client registration or Client ID Metadata
Documents, code exchange and token refresh. Arbitrary OAuth providers are **not**
guaranteed to work without a registered client. Configure one when required:

```json
{
  "https://tools.example.com/mcp": {
    "issuer": "https://identity.example.com",
    "client_id": "REGISTERED_CLIENT_ID",
    "client_secret": "HOST_ONLY_SECRET",
    "token_endpoint_auth_method": "client_secret_post"
  }
}
```

Supported pre-registered authentication methods are `none`, `client_secret_post`
and `client_secret_basic`. Optional `client_metadata_url` supplies an operator-hosted
HTTPS Client ID Metadata Document for providers that support it. That public
document must describe Lumina and its exact callback, and must contain no secrets.
Private-key JWT client authentication is not implemented. Reconnect after changing
an existing app registration. Token endpoints on another public origin are allowed only when explicitly bound to validated issuer metadata. Refresh rotations are saved encrypted, including when later discovery
fails. A per-connection database lease serializes refreshes across web/relay
processes.

## Authorization and runtime behavior

Connections and every tool selection are account scoped. Newly discovered tools
start disabled. Changed definitions are disabled until reviewed; removed tools
cannot be called. Schema checks run before approval and again against a fresh
paginated tool list immediately before execution. Reserved runtime proof fields
are refused. Supported input schemas are JSON Schema 2020-12 object schemas, with
bounded depth and local `$defs`/`definitions` references (one definition may refer to another).

**Servers just work; only the one tool that cannot be used safely is switched off.** A refused tool
never fails the connection: it is kept as a labelled stub ("Can't be used: <reason>", never callable,
no schema stored) and every other tool on the server carries on. A tool is refused only when it is
hostile or the model API that would be given its schema could not handle it:

| Refused | Why |
|---|---|
| A parameter named `_lumina_origin` | Spoofing the runtime's ownership proof. |
| A definition over 24 KB or nested over 20 levels | Memory and database bomb. |
| A schema that is not valid JSON Schema, not an object, or has no input schema | The model API would reject it, which can fail a customer's whole request. |
| A reference outside the schema (URL, `$dynamicRef`) or a cycle (`#`, a definition that leads back to itself) | Cannot be resolved by the model API. |
| A name that is not 1-128 of `A-Za-z0-9_.:-` | Cannot be addressed; dropped (a repeated name keeps the first). |

**How the assistant sees the tools.** However many tools are enabled, the assistant is given at most
eight as tools of their own (all of them while there are eight or fewer; otherwise the ones this account
has completed the most calls with in the last 90 days, most recent breaking ties; a tool never used is
never promoted). Everything else stays reachable on demand through the two generic tools:
`lumina_mcp_discover` returns a compact list (name, service, one line, `[direct]` marker; no schemas) and
accepts `{"query"}` to search or `{"tool"}` for one tool's exact parameters; `lumina_mcp_call` takes the full
name or, when only one service has it, the plain tool name. The two names are unchanged on purpose: the
runtime's ownership-proof plugin knows only them and the namespaced names.

Regular expressions (`pattern`, `patternProperties`) are **accepted**: the schema is stored and
shown exactly as sent, but Lumina never runs a server's expression (a hostile one could hang a web
worker). The server that owns the tool enforces them. Checking the model's arguments here is a
convenience (types, required fields, enums, ranges, with the path of the problem in the message so
the assistant can fix it before an approval is asked for); a schema Lumina cannot interpret never
blocks a call. A server with more than 100 tools keeps its first 100 instead of failing. The
operator log line `mcp_tools_refused` gives the counts per reason and the first tool names.

The cell receives no connection tokens, OAuth secrets or refresh tokens. Its
existing Lumina relay credential and one-use origin proof bind tool calls to an
admitted, funded, live task. Built-in browser and task-progress tools remain.
Remote tools use `lumina_mcp_<connection-id>_<tool-name-hash>`. Stable
`lumina_mcp_discover` and `lumina_mcp_call` also support runtimes that cache the
MCP tool list. Discovery refreshes stale connections without a deployment; actual
calls always check the current server definition. Existing cells need the updated
origin hook installed through normal cell configuration refresh/start.

Lumina's existing exact-target/payload/expiry authorization pattern applies to
**every** custom remote call. Remote `readOnlyHint` and other annotations never
grant permission. The agent first proposes an exact call; Integrations shows the
service, tool and arguments. Approval lasts ten minutes, dispatch consumes it
atomically, and decline blocks the same proposal within that task. Approval does
not itself execute anything: tell the assistant to continue. An identical completed
call within one task returns its saved result. A matching uncertain or abandoned
dispatch is blocked across tasks; inspect the provider before taking another action.
Authentication challenges after dispatch cannot cause SDK replay of the action.
There is no automatic write retry or UI button to clear uncertainty.

**Run without asking (opt-in, per tool).** An enabled tool can have "Run without asking"
turned on by the signed-in customer in Integrations (`auto` field of the connection
`update` action; it is not exposed to the assistant or derived from remote annotations).
Calls to that tool then record the same one-use approval row without waiting for a click,
so the audit trail is unchanged. It is cleared when the tool is disabled or its definition
changes, and turning off the connection withdraws it. Everything else still asks.

Descriptions/results are labeled untrusted data. Text, bounded structured content,
PNG/JPEG/WebP images and MCP error flags survive the relay. Remote HTML is escaped
as text, not rendered. Unsupported content blocks are omitted. Known stored
credentials are scrubbed from definitions/results; provider error bodies never
reach the UI/model or logs. Image pixels and deliberately transformed/encoded
secrets from a hostile provider cannot generally be inspected; connect only services
you intend to trust with authorized task data.

## Network, sessions and limits

- Only HTTPS public hostnames; no literal IPs, URL credentials/query tokens,
  local commands, stdio, Unix sockets or private-network setting.
- Every server-side resource, discovery, registration, token and revocation fetch
  uses the same checked transport. All DNS answers must be public. Connections
  use a checked literal IP while preserving original hostname TLS/SNI verification,
  blocking DNS rebinding. Private, loopback, metadata and IPv6 translation ranges
  are refused. Proxies are refused; same-origin discovery redirects and gzip/deflate responses are bounded.
- Bearer tokens go only to the original resource origin. Client secrets/refresh
  grants go only to the SDK-bound or operator-configured issuer origin.
- Ten connections/account, 200 enabled tools/account (an abuse guard only); the first 100 discovered tools
  (eight pages) are kept. At most two discoveries or two dispatches/account and
  one operation/connection; 16 outstanding approvals/account. API operations also
  use the existing per-account rate limits.
- Discovery/auth network work has a thirty-second total budget; calls 35 seconds;
  revocation five seconds. Connection leases expire after 45 seconds. Individual
  HTTP connect/pool timeouts are five/three seconds. SDK read timeout is 25 seconds.
- Raw response/event limit 2 MiB; individual tool definitions 24 KiB/depth 20;
  arguments 14 KiB; result content 32 blocks/1.4 MB, text blocks 100k characters,
  structured content 100k bytes. Oversized outcomes are uncertain after dispatch.
- Each operation initializes/negotiates a fresh SDK session, discovers paginated
  tools, and closes/DELETEs its session in cleanup. No transport sessions survive operations.
  While active, a generation/account/admission monitor closes sessions when the
  connection is disabled, disconnected or the task is stopped. Already received
  remote effects cannot be undone by cancellation.
- Disconnect deletes live credentials, choices and approvals first and disables
  access immediately. Supported same-issuer revocation is attempted afterward;
  `accepted`, `failed` or `not_supported` is reported honestly. Provider-side
  account settings may still need revocation. Backups are subject to existing
  expiry; restore treats these tables as live-only and never resurrects them.

Two pinned SDK internals are intentionally isolated: the HTTPX/httpcore backend
injection for checked-IP dialing, and the OAuth browser rendezvous override for
web-request persistence. Review these adapters and run fixture tests whenever
updating the SDK/HTTP libraries.

## Verification

From `platform`, with installed locked dependencies:

```sh
.venv/bin/python -m unittest tests.test_mcp_network tests.test_mcp_connections tests.test_privacy_policy
.venv/bin/python manage.py test accounts.test_mcp_connections
node --test tests/tool_origin_plugin.test.mjs
```

Set an ephemeral `AGENTAI_SESSION_SECRET` (48+ random characters) and temporary
`AGENTAI_STATE_DIR` for Django test commands. The real SDK fixture tests cover
paginated initialization, OAuth/DCR/PKCE/refresh/revocation, account boundaries,
secret custody, exact approvals, schema changes, images/structured errors,
cancellation and uncertain-write replay prevention. The transport fixture maps
**only** two synthetic public hostnames to a local HTTP server through constructor
injection in test code. No runtime environment variable/API can enable that
allowance in production.

For the complete production-bundle UI-to-relay-to-SDK flow:

```sh
# platform: prints an ephemeral HTTPS localhost origin and fixture-only login
.venv/bin/python tests/mcp_ui_fixture.py
# another terminal, from lumina, use the printed origin
npm run build
node tests/mcp-connections.mjs https://localhost:PRINTED_PORT
```

This test uses the actual Django session/CSRF API, temporary migrated database,
real MCP SDK and a synthetic admitted task with the real relay ownership proof.
It tests create/discover/enable, exact-call approval, agent result, disable, rename,
disconnect and Asana setup messaging at desktop/mobile widths. Screenshots are
written to `/tmp/lumina-mcp-ui`. No external tasks or production accounts are used.
Real Asana OAuth still requires the operator app registration above and a separate,
authorized provider smoke test. No deployment is part of this implementation.


## Automatic setup and agent discovery (13 November 2026)

The canonical production identity is `https://getlumina.pro/oauth/client-metadata.json`, published as static JSON by the Vercel build. `AGENTAI_MCP_CLIENT_METADATA_URL` overrides it for a separately hosted staging identity; never list staging callbacks in the production document. Existing registrations take precedence, followed by CIMD and SDK dynamic registration. The private registrations file is optional. A provider that requires pre-approved applications may still require its own registration.

Manual and agent creation use `ConnectionService.create`, deduplicate exact endpoints per account, and leave tools off. `lumina_mcp_search` searches the official known-provider list and the public MCP Registry; registry entries are untrusted leads. The assistant can use its existing web search to check provider documentation. `lumina_mcp_setup` cannot accept credentials or grant tool permissions. Unknown endpoints are stored with `setup_confirmed=0` and cannot be contacted until the customer reviews the address. The returned management link opens that same connection on Integrations. `lumina_mcp_connections` returns safe account-scoped statuses. All relay tools retain admitted-task ownership checks.

Custom setup defaults to automatic authentication. Explicit methods include OAuth, bearer, named API-key header, Basic authentication, and no authentication. A customer's own OAuth app can be configured with issuer, client ID, optional secret and `none`, `client_secret_post` or `client_secret_basic`. Credentials remain encrypted and never reach the agent. Updating credentials turns tools off, invalidates pending approvals and requires review again. OAuth reconnect rediscoveries discard SDK-issued client registrations, but retain explicitly customer-supplied clients. Scope challenges are saved for customer reauthorization; dispatched actions are never replayed automatically.

Transport negotiation tries Streamable HTTP, falling back to legacy SSE only for explicit HTTP transport-mismatch statuses during discovery, never for dispatched tool calls. Negotiated transport is saved. Discovery has a 30-second total deadline; calls remain 35 seconds. Gzip/deflate responses are bounded before and after decompression. Only same-origin discovery redirects preserving POST methods may be followed, with three hops maximum. Cross-origin resource redirects require entering the final endpoint. OAuth token endpoints on another public origin are accepted only when bound to validated issuer metadata. Local commands/stdio, private networks, token-in-URL endpoints and private-key JWT are unsupported.

The additive `0036_mcp_setup.sql` migration preserves original auth_method values; requested mode and provenance are separate columns. On binary rollback, disable rows whose requested_auth is `auto`, `header` or `basic` before old code handles them; preserve encrypted credentials and ask customers to reconnect after restoring the new release. Keep the public identity document available across rollback. Rollout remains controlled by the existing MCP account allowlist; deploying this code does not expand it.
