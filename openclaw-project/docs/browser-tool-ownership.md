# Browser tool ownership, protocol 2

Protocol 2 replaces the transcript-based matcher introduced in `ef2a8ac`. The production YoungLA and restaurant runs showed that valid calls could be refused while their admitted task was still active. The original failure logs did not distinguish the failed internal predicate, so the exact original race remains unproven. The replacement removes transcript timing and live-placement snapshots from authorization entirely.

## Request path

1. OpenClaw's supported, awaited `before_tool_call` hook receives host-provided `sessionKey`, `runId` and `toolCallId` for the actual nested Lumina MCP tool. Missing identity blocks the call.
2. The hook generates a random nonce, atomically writes a private bounded receipt, and overwrites `_lumina_origin` in the outgoing tool parameters. Model-supplied values never choose that nonce. A receipt binds the exact arguments, tool name and runtime identity.
3. The authenticated MCP relay sends the nonce and arguments to the root bridge for the calling account. The bridge opens only that account's receipt directory, rejects redirects, hard links, malformed/expired proofs and argument changes, then consumes the receipt atomically. Concurrent requests and restarted relays cannot reuse it.
4. The relay matches the verified session/run to a conversation and delivery of an active, uncancelled, funded request. It strips the transport field before invoking the browser or progress handler. There is no account-only fallback.
5. The runtime's `after_tool_call` hook removes any unconsumed receipt. Startup does not clear other in-flight receipts; abandoned ones expire. No new signing or provider credentials are introduced.

The cell runtime remains trusted to supply identity for its own account. The host enforces account isolation, admission, reservation and cancellation. This is not a boundary against a compromised cell runtime forging its own state.

Progress reporting has a separate concurrency lane from browsing, so a long browser call cannot block its checklist update. Browser actions remain serialized per account. Existing payment, consent, public-network and spending rules are unchanged. Native SQLite active-turn inventory remains in use for orphan draining; it is no longer a source of tool-call authority.

## Diagnostics and compatibility

Refusals log only a registered tool name and a fixed reason: missing/consumed, invalid, expired or unavailable proof; argument mismatch; unavailable origin service; or admission mismatch. Tool arguments, nonce values, credentials and page contents are not logged.

This hook integration is verified against pinned OpenClaw 2026.9.6. A runtime upgrade must repeat real-gateway acceptance, including streamed parallel calls and nested `browser_step` execution. Unupgraded cells fail closed rather than using the old transcript heuristic.

## Deployment and rollback

Deploy matching platform/supervisor modules, the hook source and the cell plugin configuration together while execution is idle. Restart both the request worker and the lifecycle worker: stopping the native supervisor also stops its dependent lifecycle worker. New and existing cells install/configure the hook before starting; that wiring does not depend on the provider model allow-list refresh succeeding. Preserve other installed plugins and their configuration.

No database migration is added. Rollback must restore both release links and the prior cell configuration/plugin files. Rolling back only the MCP relay leaves an incompatible protocol pair.

## Evidence

`../evidence/browser-ownership/20261028/` records unit, hook, real-gateway, canary, deployment and owner acceptance results. Deterministic tests cover identity mismatch, forged model nonce replacement, replay prevention, parallel progress/browser calls, malformed/expired/symlink proofs, browser-step handoffs and old-session rejection. The owner acceptance uses only example.com through normal admission and existing spending limits; it performs no booking, purchase or external write.

Deployed release: `20261028T212308Z-tool-origin-v2`. Both release trees were verified against the saved source manifests. Health and readiness probes returned 200. The dependent lifecycle worker was restored after the coordinated service restart.

Live owner acceptance passed: progress discovery, browser startup and browser-step completion all succeeded with the matching runtime run ID. The browser returned “Example Domain”; the task completed and its reservation settled. Provider charge: $0.188126. No pending proofs remained. The backend suite ran 1,011 tests with two skips; the final proof tests and hook tests also passed.
