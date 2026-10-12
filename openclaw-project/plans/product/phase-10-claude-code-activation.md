# Claude Code (Sonnet 5.5) activation runbook — PREPARED, NOT APPLIED

Nothing below has been run on the server. Apply only after the owner says so,
and only inside a verified customer cell for any customer use. Owner-runtime
use for the Phase 15 build cases still needs the steps up to 5.

1. **Back up first** (native `backup` + SQLite snapshots per RUNBOOK) *before*
   stopping anything.
2. **LiteLLM route:** `deploy/litellm.yaml` now lists `claude-sonnet-5-5`
   (`anthropic/claude-sonnet-5-5`). Recreate the proxy, then confirm the route
   with one harmless 1-token call under the owner virtual key and confirm the
   $2/24h and $25/30d backstops still deny. Add a verified price/upper bound for
   this model to the budget ledger before any customer route uses it.
3. **Image:** build `deploy/Dockerfile.claude-code` with reviewed pins; record
   digests in `platform/runtime.lock.json`. Install the acpx plugin with pinned
   version (`openclaw plugins install @openclaw/acpx@<version>`); acpx fetches the
   Claude ACP adapter via `npx` at first use, so pre-seed it in the image/home
   and verify no unreviewed network fetch happens at runtime.
4. **Preflight batch:** `openclaw config set --batch-file
   config/phase10-claude-code-preflight.batch.json --dry-run`, then apply. It adds
   the catalog row (context 200000/max 4096 are conservative placeholders —
   confirm Sonnet 5.5's real limits) and leaves acpx/ACP **disabled**.
5. **Probe** (harmless): `models list` shows `litellm/claude-sonnet-5-5`;
   `claude --version` in the Gateway container; a one-turn `claude-cli` smoke with
   a throwaway workspace and tools disabled.
6. **Activation batch:** `config/phase10-claude-code-activation.batch.json` adds
   `claude-builder`, `claude-debugger`, `claude-reviewer` (ACP, oneshot, read-only
   tools) and enables acpx with `permissionMode: deny-all`,
   `nonInteractivePermissions: deny`, both MCP bridges off, `allowedAgents:
   ["claude"]`. Dry-run, apply, validate.

## Open metering question (blocks customer use)

`claude-cli` and ACP `claude` run Claude Code, which calls Anthropic itself.
The docs describe only a login or an OpenClaw-managed Anthropic API-key profile,
**not** routing through the LiteLLM proxy. Unless Claude Code can be pointed at
the proxy with a per-account virtual key (not documented; do not assume
`ANTHROPIC_BASE_URL` is honored), its spend bypasses the proxy caps and the
budget ledger. Until proven, owner-runtime use is bounded only by the Anthropic
key's own limits and customer use stays blocked (NATIVE-02).

## Rollback

Disable agents/acpx via config (`plugins.entries.acpx.enabled=false`,
`acp.enabled=false`, remove `claude-*` agents), revert the image tag, remove the
proxy route. Config backups from step 1 restore the prior state.
