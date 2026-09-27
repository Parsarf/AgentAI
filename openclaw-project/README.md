# OpenClaw server deployment

This directory holds configuration and evidence for the
[personal-agent plan](../phase-prompts/openclaw/README.md). OpenClaw 2026.9.6
is running on the owner's IONOS VPS at `69.48.206.62`, with LiteLLM and
PostgreSQL under `/opt/openclaw-production`. The Mac is not a runtime dependency.
Phase6 integration setup is now applied: a pinned read-only Google connector
image and disabled native Google/GitHub definitions, restricted to researcher.
Account authentication and selected GitHub repositories remain required.
Heavy/paid acceptance tests are deferred by owner direction. Earlier phases
have substantial runtime evidence but their outstanding gates remain unpassed.
See the latest [build log](BUILD_LOG.md) and [Phase6 plan](plans/phase-6.md).
The reusable [Connect tools guide](CONNECT_TOOLS.md) covers adding a tool
service, account sign-in, enable/disable and native tool catalog checks.

The temporary local OpenClaw and Node binaries were removed after validating
the server template to recover disk space. Disposable Mac staging state, workspace, restore clone and compile cache
were removed during owner-authorized cleanup. Recovery backups and current
execution evidence remain.
The tracked [config template](config/openclaw.example.json) contains SecretRef
names, never credential values. The local Gateway was smoke-tested on loopback
port 18790 and stopped. The owner chose Anthropic API access and Telegram;
their keys were originally read from the former `agent/.env` into staging without
printing them. The staging bootstrap made no paid call; the live server has
paid usage, recorded in the latest build-log entry.

Read [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[MIGRATION_DECISIONS.md](MIGRATION_DECISIONS.md), and
[BUILD_LOG.md](BUILD_LOG.md) before continuing. The
[RUNBOOK.md](RUNBOOK.md) covers live access, checks and recovery. Legacy AgentAI code/docs are removed. Current local credentials live in the
ignored mode0600 `openclaw-project/.env`; helpers require only
[requirements-local.txt](requirements-local.txt). Production services and
databases were not changed.

Phase 1 now has a [deployment bundle](deploy/README.md), fresh-state preparation
and native CLI wrappers. See the latest build-log entry for live evidence and
the remaining owner checks before Gate 1 can pass.
