# Phase 1 — Secure install and one owner agent

Build only after Gate 0 is accepted. Read the OpenClaw phase index,
`ARCHITECTURE.md`, `MIGRATION_DECISIONS.md`, `BUILD_LOG.md`, and current
official installation, gateway, Telegram, model/auth, usage and security docs.
Use documented commands for the installed version, not command guesses from
the brief. This is a new runtime; do not import AgentAI code or data by default.

## Work

1. Inventory existing state before changing it. Prepare a reversible backup
   of any OpenClaw state you will modify. Install or update only the components
   in the approved architecture on the owner's always-on IONOS Ubuntu VPS.
   Keep all published Gateway-related ports bound to host loopback and use an
   SSH tunnel or approved authenticated private access. Do not expose them
   publicly or depend on the Mac for uptime.
2. Configure one owner agent using the Anthropic API key via the reviewed
   spending proxy, owner-only Telegram
   pairing, Control UI and WebChat as available. Put declarative, non-secret
   configuration in git. Keep auth, tokens and provider keys in documented
   secret mechanisms; scan the tracked files before commit.
3. Configure usage visibility and a **real** $2/day and $25/month ceiling. Test the
   effective stop/admission behavior with a deliberately tiny temporary limit
   and a cheap request, then restore the approved limits. If OpenClaw cannot
   enforce the requested ceiling, document the gap and use an independently
   enforceable provider limit or a small reviewed guard; do not claim usage
   telemetry itself enforces a cap. Keep paid model calls blocked until the
   monthly provider cap and local daily/monthly admission control are verified.
4. Verify owner and non-owner access with safe accounts/test identities. Check
   the gateway bind and authentication. Run `openclaw doctor`, relevant channel
   and model health checks, `openclaw security audit`, and a redacted secret
   scan. Record commands/results and actual cost in `BUILD_LOG.md`.

## Gate 1

The owner can chat through Telegram and the Control UI; an unpaired sender
cannot. Usage is visible and the budget stop is demonstrated or the gate is
marked blocked with the precise missing control. Doctor and security findings
have dispositions. Stop at the gate and report the reviewable config diff.
