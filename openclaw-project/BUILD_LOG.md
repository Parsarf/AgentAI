# OpenClaw build log

## Phase 0 and isolated bootstrap — 2026-09-24 (in progress)

The owner clarified that production must run on an always-on server; this Mac
must not be required for availability. Earlier Mac selection is superseded.
The local installation below is a disposable staging environment only.
Its temporary Node and OpenClaw binaries were later removed to recover disk
space; the private staging state remains in the ignored directory. The server
template was validated against OpenClaw 2026.9.6 before removal.

- Created draft migration and architecture decisions in this directory.
- Read the current official OpenClaw install, Node compatibility, Codex
  harness, ACP, security, doctor and backup documentation. The new phase
  prompts require fresh documentation checks at execution time.
- Host inventory: macOS 15.3.1 arm64; system Node v23.10.0 and npm 10.9.2;
  system `openclaw` and `docker` commands absent. No `~/.openclaw` directory
  detected. Codex and Claude CLIs reported existing logins; Gemini CLI exists
  but its auth was not checked. None is connected to this OpenClaw instance.
- Existing AgentAI code and database were not modified, archived or reset in
  this phase. Its purchase execution remains disabled.

### Isolated work completed

- Staged Node 26.1.0 and OpenClaw 2026.9.6 in gitignored workspace folders.
  The system Node install remains 23.10.0. Created an isolated baseline state
  and workspace with `openclaw setup --baseline`.
- Disabled system-browser profile cookie import, Bonjour multicast discovery,
  automatic memory dreaming, recurring heartbeat, and elevated host exec in
  the isolated config. Generated a gateway token, moved it into OpenClaw's
  protected store, changed config to a store SecretRef, and removed temporary
  config backups from this new isolated state. The secrets audit reports zero
  plaintext, unresolved, shadowed, store-residue and legacy findings.
- A non-secret, versionable config example is in `config/openclaw.example.json`.
  The actual config and token stay in the ignored state directory.
- `config validate --json` passed for the active config and tracked template.
  Final `secrets audit --check` was clean. Final `security audit --json`
  reported zero critical and one conditional warning about reverse-proxy
  trust if the loopback UI is later proxied. Doctor reports the intentionally
  disabled browser cookie import and a node-onboarding URL warning because
  the gateway remains loopback-only.
- Started `gateway run --port 18790`; `/healthz` returned HTTP 200. Stopped it
  cleanly. It made no model, Telegram, Google, GitHub or payment call.
- `openclaw backup create --verify` produced a verified archive of the isolated
  state and workspace. `backup restore --target` succeeded into a fresh
  `restore-test/` directory without touching active state. The archive is
  gitignored and mode 0600 under a mode-0700 directory; it is **not encrypted**
  and must not be shared or treated as a secure off-site backup.

### Open gates

- Provision and access the always-on server, then perform the deployment and
  restart/recovery acceptance checks there.
- The owner supplied an existing IONOS Ubuntu 24.04 VPS at `69.48.206.62`
  (2 vCPU, 4 GiB RAM, 120 GiB disk). SSH port 22 responds and its ED25519
  host key matches this Mac's recorded key. Password-only SSH rejected the
  initial password displayed by IONOS; the same login failed at the IONOS
  remote console. An `ubuntu` key-based SSH login also failed. No server
  command or installation has run. The owner must provide a current sudo
  credential/authorized SSH key or complete IONOS's root recovery flow.
- Sandbox tests require the server's Docker runtime. Colima, Docker CLI and
  Lima were briefly installed on the Mac for a canceled local sandbox test,
  then uninstalled after the server clarification. Colima could not unpack
  its VM image because the Mac had less than 1 GiB free; its failed image was
  removed. No Mac container runtime is required for production.
- The owner selected the Anthropic API key route and Telegram. Both keys were
  found in `agent/.env` (mode 0600) and imported into the isolated OpenClaw
  secret store without displaying values. The config uses SecretRefs and
  validates. Sonnet 4.6 is the primary model, Haiku 4.5 the utility model,
  and the model picker is limited to those two Anthropic refs. No paid model
  request has been made.
- The Telegram token passed `getMe` for `@Keighobad_bot`. The staging config
  enables DM pairing and disables groups. A separate Telegram poller returns
  HTTP 409 to our `getUpdates` request, so the numeric owner ID and pairing
  cannot yet be verified. The owner has been asked for their numeric ID.
- A hard daily/monthly budget mechanism remains to be demonstrated. Usage
  visibility alone does not satisfy this gate. The owner chose $2/day and
  $25/month; production paid requests remain gated.

No paid model request was made. Only the Telegram `getMe`, `getWebhookInfo`,
and `getUpdates` endpoints were used to inspect the bot. Phase 0 review is not
complete, and later gates have not been run.
