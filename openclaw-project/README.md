# OpenClaw server deployment

This directory holds the existing owner runtime, configuration and evidence
used by the replacement [customer-platform Phase 1–19 plan](../phase-prompts/openclaw/README.md).
The owner OpenClaw deployment runs on the always-on IONOS VPS with LiteLLM
and PostgreSQL; the Mac is not a runtime dependency. Restricted Brave search
and browser paths, native worker/coding/integration bases, operator tools and
the owner dashboard/live viewer are reusable starting points. Read the latest
[BUILD_LOG](BUILD_LOG.md) for actual status; many acceptance gates remain partial.
Product Phases1–2 now deliver the [customer contract](../product/CONTRACT.md)
and [secure private foundation](platform/README.md), verified by14 targeted
checks and an actual resource-bounded server smoke (cleaned up). Customer
accounts/provisioning/chat/billing remain subsequent product phases.

The [coverage ledger](../phase-prompts/openclaw/coverage-ledger.md) maps every
old prompt and pending test to its new home. Historical plans/evidence keep
old numbers. New work uses `plans/product/` and `evidence/product/` to avoid
collisions. Full/paid testing and owner-deferred account setup remain deferred
until explicitly resumed. Prompt replacement changes the plan, not the server.

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

Product Phase3 account build and targeted private boundaries now pass.
[Phase3 record](plans/product/phase-03.md) distinguishes this from real TLS/mail/
tenant activation and full acceptance. Next implementation phase4.
