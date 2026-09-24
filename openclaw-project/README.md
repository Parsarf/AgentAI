# OpenClaw server deployment

This directory holds server deployment planning and a private local staging
record for the [new personal-agent plan](../phase-prompts/openclaw/README.md).
The final product must run on an always-on server; this Mac is not a required
runtime host. Server access, spending enforcement, sandbox verification, and
end-to-end acceptance are pending.

The temporary local OpenClaw and Node binaries were removed after validating
the server template to recover disk space. Private staging state remains
gitignored and is not a production dependency.
The tracked [config template](config/openclaw.example.json) contains SecretRef
names, never credential values. The local Gateway was smoke-tested on loopback
port 18790 and stopped. The owner chose Anthropic API access and Telegram;
their keys were read from `agent/.env` into the private staging store without
printing them. No paid model call has been made.

Read [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[MIGRATION_DECISIONS.md](MIGRATION_DECISIONS.md), and
[BUILD_LOG.md](BUILD_LOG.md) before continuing. The
[RUNBOOK.md](RUNBOOK.md) covers staging checks and backup. Production deployment
requires an accessible server and verified spending caps. The existing Python
AgentAI service remains intact.
