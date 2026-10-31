# Lumina

Lumina is a customer AI-assistant platform with chat, task controls, live browser
viewing, generated UI and project artifacts. The customer site is
**https://getlumina.pro**.

The customer UI is a React/Vite app. Django owns account authentication and
tenant-scoped APIs. A durable queue and budget ledger admit work; a worker
supervises native OpenClaw execution inside each account's own assistant cell.
The host uses gVisor and account-specific state and credentials. Model and
browser integrations remain part of the system's trust boundary.

## Current status

Automatic cell enrollment during account approval was deployed on 31 October
2026. A prompt wakes the account's existing cell; idle sleep preserves its
workspace. The current host permits one running customer cell at a time.
Deployment checks do not establish that every possible cross-account data leak
has been excluded: real new-user provisioning and two-live-cell adversarial
acceptance remain unrun for that release.

The repository also contains customer Chrome-extension/device-browser source,
parallel UI work, optional browser experiments, and separate local JEV
prototypes. Their presence in Git is not proof of production rollout or Chrome
Web Store publication. Consult the dated deployment records for live status.

See the [change description and chronological commit list](CHANGELOG.md) for
the GitHub catch-up since the previous working-branch push on 13 October.

## Code map

| Directory | Responsibility |
|---|---|
| `openclaw-project/lumina/` | Customer React app, chat, live view, generated UI and shared components. |
| `openclaw-project/platform/accounts/` | Django identity, routes, account APIs and management commands. |
| `openclaw-project/platform/agentai_platform/` | Chat, queue, budgets, events, files, integrations and product services. |
| `platform/agentai_platform/lifecycle/` | Host supervisor, cell provisioning, bridge, sleep/wake and recovery. |
| `platform/agentai_platform/browse/` | Browser orchestration, transports, device pairing and handover. |
| `openclaw-project/browse/` | Hosted browser runner and customer Chrome extension. |
| `openclaw-project/platform/deploy/` | Release, rollback, systemd, Caddy and Vercel configuration. |
| `jev-browser/`, `jev-window-core/` | Separate local browser and macOS window-control prototypes. |
| `output/`, `product/marketing/` | Reusable brand assets, animation sources and a proposed advertising brief. |

Paths beginning `platform/` in the table are relative to `openclaw-project/`.

## Architecture and operations

- [Current architecture reports](openclaw-project/docs/architecture/README.md)
- [CBM structural map](docs/codebase-audit/CBM_STRUCTURE_2026-10-31.md)
- [Automatic-cell rollout and rollback record](docs/codebase-audit/DEPLOYMENT_2026-10-31_AUTOMATIC_CELLS.md)
- [Automatic-cell host configuration](openclaw-project/platform/deploy/AUTOMATIC_CELLS.md)
- [Customer Chrome extension](openclaw-project/browse/extension/README.md)
- [Device-browser deployment](openclaw-project/platform/deploy/DEVICE_BROWSER.md)
- [Product contract](product/CONTRACT.md) and [implementation log](openclaw-project/BUILD_LOG.md)
- [Operations runbook](openclaw-project/RUNBOOK.md) and [release guide](openclaw-project/platform/deploy/README.md)
- [Vercel publication guide](openclaw-project/platform/deploy/vercel/README.md)

Older phase plans and readiness statements are historical. Current source and
dated deployment evidence take precedence. Production data, real environment
files, credentials, private backups and raw operational logs remain outside Git.
