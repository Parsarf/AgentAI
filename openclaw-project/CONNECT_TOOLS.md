# Connect tools later

The connection base is installed on the VPS. It uses OpenClaw's native MCP
registry, protected auth and tool policy. Your Google and GitHub templates are
already registered and disabled; account setup is deliberately left for later.

From this repository on your Mac:

```sh
./openclaw-project/bin/connect-tool list

# Register an HTTPS MCP service with only its chosen read tools.
./openclaw-project/bin/connect-tool add my-service \
  --url https://your-service.example/mcp \
  --tools search,read_item --oauth

# Connect its account, then enable and check the tool catalog.
./openclaw-project/bin/connect-tool login my-service
./openclaw-project/bin/connect-tool enable my-service
./openclaw-project/bin/connect-tool check my-service

# Disconnect tool access without deleting account data.
./openclaw-project/bin/connect-tool disable my-service
```

Use the actual endpoint and exact read tool names from the service's docs.
`add` automatically sets up the restricted reader's native permissions and
backs up existing config. The new connection stays disabled. The manager never
reads your account, creates a subscription, calls a model or adds a schedule.
`check` connects to the MCP service to inspect tools; normal provider/API limits
still apply. Some services require their own client registration or paid plan.

For an installed stdio MCP adapter:

```sh
./openclaw-project/bin/connect-tool add local-reader \
  --command /path/on/the/vps/to/mcp-adapter \
  --arg=--read-only --tools search,read_item
```

Executables and files must exist on the VPS/Gateway, since it runs independently
of your Mac. Install a maintained adapter first for services without MCP support.
An arbitrary HTTP API URL alone is not an MCP server. Stdio adapters are trusted
operator-installed code; use a restricted container like the prepared Google
adapter when they handle sensitive credentials. Never put tokens into arguments.

For an existing protected bearer profile, replace `--oauth` with
`--auth-profile <profile-id>`. New credentials are entered only through the
provider/native protected flow, never this command's flags or chat. HTTP OAuth
login prints its native browser flow in the trusted terminal; for a remote
callback, forward the exact printed callback port with SSH. Keep login alive
until consent completes. `logout` clears native shared OAuth state; provider
consent/token revocation remains a separate provider operation.

For a browser-based path, use the existing private Control UI → Settings → MCP.
It has Add server, Sign in, enable/disable and tool filters. Connections added
directly there also need the researcher's explicit native tool policy; the
command helper handles that policy step for newly registered services. Use
the Control UI scoped editor/native configure commands for advanced changes.

Only researcher can consume new connectors; main receives summaries and links.
Choose read-only provider credentials/adapter mode and read tools. The manager
does not infer tool safety from a name or enforce approvals for arbitrary API
writes. Send/delete/share/push tools need a separately configured supported
authorization path. Existing worker messaging, scheduling, shell and policy
denials remain in force. Draft proposals stay in the local workspace.

Google-specific sign-in and selected-repository GitHub credentials are covered
in [RUNBOOK.md](RUNBOOK.md#phase6--account-connection-and-read-only-operation).
No accounts need to be connected to finish this base. Heavy acceptance is
deferred; [setup evidence](evidence/phase-6/20260927T200739Z/manifest.json)
distinguishes installed/configured features from unverified provider behavior.
