# AgentAI to OpenClaw migration decisions

Status: draft for Phase 0 review, 2026-09-24. The existing Python service is
untouched and must remain runnable while the new system is built and checked.
No data has been migrated or archived.

| AgentAI component | Decision for single-owner system | Reason or follow-up |
|---|---|---|
| `core/orchestrator.py`, Claude SDK loop | Replace | Use OpenClaw's agent runtime. Do not port the loop. |
| `core/router.py`, model-key routing | Replace | Use documented model/provider routing and native Codex harness where suitable. |
| `tools/base.py`, tool registry | Replace | Use OpenClaw tool policy and native/verified plugin tools. |
| `core/approvals.py` | Replace | Use OpenClaw exec/tool approval surfaces; verify each action class. |
| `gateway/telegram_bot.py`, web chat | Replace | Use owner-paired Telegram and Control UI/WebChat. |
| `tools/browser.py`, `tools/web.py` | Replace | Use documented browser/web tools in restricted workers. |
| `core/scheduler_service.py`, watcher | Replace | Use cron/background tasks only after durable resume and approval checks. |
| `tools/memory.py`, database-backed memory | Replace | Use OpenClaw memory; export selected owner facts only after review. |
| `core/secrets_vault.py` | Replace | Use OpenClaw secret/auth mechanisms; never copy the master key into the new config. |
| `core/auth.py`, sessions, signup, tenancy | Drop | New gateway is one owner's trust boundary. Do not carry multi-user accounts. |
| `core/billing.py`, Stripe subscriptions | Drop | No multi-user product billing in this plan. Retain old billing records under the old service's retention policy. |
| `core/purchases.py`, `tools/payments.py` | Drop | Purchase execution is unfinished and disabled. Do not import or enable it. |
| `core/events.py` | Replace | Use OpenClaw's native task/event delivery as documented. |
| `sandbox/*` | Replace | Use OpenClaw sandboxing once a supported container runtime is available. |
| `tests/*`, backup scripts | Keep as historical evidence | Do not copy the pytest stack; carry over useful test scenarios and require disposable restore proof. |

## Data and rollback

The old repo has uncommitted work and a local PostgreSQL-backed app. Do not
archive, delete, reset, migrate, or push it automatically. First enumerate
owner-specific memories, tasks, projects, credentials and exports through
read-only tools; redact secrets; let the owner choose what to retain. Preserve
the old database and code until the OpenClaw acceptance workflow succeeds and
the owner approves retirement. A git tag alone is not a database backup.

## Open decisions

- Provision an always-on server; the Mac is staging only and must not be
  required for uptime.
- Enforce the chosen Anthropic API spending ceilings of $2/day and $25/month
  before making paid requests.
- Supply owner-only Telegram and optional Google/GitHub connections through
  documented secret flows, never through this repository.
- Verify a Docker sandbox and private remote access on the server.
