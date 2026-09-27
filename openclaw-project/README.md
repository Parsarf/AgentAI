# OpenClaw server deployment

This directory holds configuration and evidence for the
[personal-agent plan](../phase-prompts/openclaw/README.md). OpenClaw 2026.9.6
is running on the owner's IONOS VPS at `69.48.206.62`, with LiteLLM and
PostgreSQL under `/opt/openclaw-production`. The Mac is not a runtime dependency.
Phase 1's budget and security probes passed; owner access checks are pending.
Docker tool sandboxing and later phases have not passed their gates.

The temporary local OpenClaw and Node binaries were removed after validating
the server template to recover disk space. Private staging state remains
gitignored and is not a production dependency.
The tracked [config template](config/openclaw.example.json) contains SecretRef
names, never credential values. The local Gateway was smoke-tested on loopback
port 18790 and stopped. The owner chose Anthropic API access and Telegram;
their keys were read from `agent/.env` into the private staging store without
printing them. The staging bootstrap made no paid call; the live server has
paid usage, recorded in the latest build-log entry.

Read [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[MIGRATION_DECISIONS.md](MIGRATION_DECISIONS.md), and
[BUILD_LOG.md](BUILD_LOG.md) before continuing. The
[RUNBOOK.md](RUNBOOK.md) covers live access, checks and recovery. The existing Python
AgentAI service remains intact.

Phase 1 now has a [deployment bundle](deploy/README.md), fresh-state preparation
and native CLI wrappers. See the latest build-log entry for live evidence and
the remaining owner checks before Gate 1 can pass.
