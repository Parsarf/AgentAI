# AgentAI to OpenClaw migration decisions

## Customer-product scope update — 2026-09-29

The user now requested the customer platform and executed product Phases1–2.
Historical personal-only “Drop” rows below no longer prohibit new customer
identity/tenancy/billing services. Implement these around native OpenClaw using
the new phase plan; do not port retired Python loop/router/approval/vault code.
Accounts/deployment mapping/artifact/event/usage/billing metadata are separate
product services. [Platform ADRs](platform/ARCHITECTURE.md) document current
boundaries. Agent purchases stay disabled except a separately selected Phase19.
No retired database/code or live state was restored by this foundation work.

Status: migration map retained as design history. On2026-09-27 the owner
authorized deleting unnecessary legacy files. The old application’s working
tree, original prompts/spec/build notes and disposable Mac staging files were
removed. Local credentials moved intact to ignored mode0600
`openclaw-project/.env`; helpers now use a minimal python-dotenv environment.
Git history, current OpenClaw work/evidence, server databases and recovery
backups were preserved. Earlier phase acceptance gaps remain unpassed.

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
| `tests/*`, backup scripts | Retain in Git history | Do not copy the pytest stack; carry over useful test scenarios and require disposable restore proof. |

## Data and rollback

The user explicitly authorized obsolete-file cleanup after the old/current
project distinction was explained. Legacy application files had no pending
edits; tracked versions remain recoverable through Git. No database was dropped
or migrated, no server service stopped, and no provider credential revoked.
Current OpenClaw uncommitted work was preserved. Git history is not a database
backup; keep private recovery archives and server data.

## Continuing decisions

- The VPS is the runtime; the Mac provides operator helpers only.
- Preserve existing spending caps and private access boundaries.
- Finish account connections through protected flows when the owner is ready.
- Resume deferred acceptance checks only when explicitly directed.
