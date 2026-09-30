# AgentAI customer platform

The active runtime is [openclaw-project](openclaw-project/README.md), running
on the always-on VPS. The existing owner agent/dashboard is the starting point
for the customer platform: accounts, isolated deployments, dashboard/Telegram
work, project artifacts, live progress, enforceable usage and hosted billing.

## Publish from GitHub to Vercel

Import this repository into Vercel with root directory
`openclaw-project/platform/deploy/vercel`, framework **Other**, no build/install
command, and output directory **public**. It deploys a setup page immediately.
To connect customer login, configure the VPS HTTPS backend and Vercel's
`BACKEND_ORIGIN` environment variable. See the complete
[publication guide](openclaw-project/platform/deploy/vercel/README.md).

The private customer account backend is installed on the existing VPS. Verified
accounts, trial onboarding, scoped request intake and a persistent global serial
queue are implemented. The native agent adapter is still disabled: saved requests
wait. Website publication does not enable agents or paid signup. Full chat,
Telegram linking, artifacts, live events and billing remain later phase work.

The [offer and screen designs](product/CONTRACT.md),
[platform implementation](openclaw-project/platform/README.md) and
[Phase 6 status](openclaw-project/plans/product/phase-06.md) describe the scope.

Follow the replacement [Phase 1–19 plan](phase-prompts/openclaw/README.md).
It includes all unfinished earlier requirements and two optional optimization
phases. Old executable prompts were replaced; historical plans and evidence
retain their original labels. This planning update does not deploy features,
pass acceptance gates or resume deferred paid testing.

- [Requirement coverage and old-to-new mapping](phase-prompts/openclaw/coverage-ledger.md)
- [Execution rules and cost/capacity formulas](phase-prompts/openclaw/execution-contract.md)
- [Implementation status and evidence](openclaw-project/BUILD_LOG.md)
- [Connect tools](openclaw-project/CONNECT_TOOLS.md)
- [Operations and recovery](openclaw-project/RUNBOOK.md)

Local operator helpers use the ignored, mode0600 `openclaw-project/.env`.
To recreate their small Python environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r openclaw-project/requirements-local.txt
./openclaw-project/bin/connect-tool list
```

The retired multi-user Python application remains in Git history and is not
the new runtime. Production data, credentials, backups and current evidence
are preserved.
