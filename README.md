# OpenClaw personal agent

The active project is [openclaw-project](openclaw-project/README.md), running
on the always-on VPS. Its current increment is the Phase6 connection base;
account setup and heavy acceptance tests are deferred.

- [Connect tools](openclaw-project/CONNECT_TOOLS.md)
- [Operations and recovery](openclaw-project/RUNBOOK.md)
- [Implementation status and evidence](openclaw-project/BUILD_LOG.md)
- [Current phase plan](phase-prompts/openclaw/README.md)

Local operator helpers use the ignored, mode0600 `openclaw-project/.env`.
To recreate their small Python environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r openclaw-project/requirements-local.txt
./openclaw-project/bin/connect-tool list
```

The superseded multi-user Python AgentAI application, its prompts/spec/build
notes, and disposable Mac staging files were deleted at the owner's request.
Tracked historical code remains recoverable from Git history. Production data,
credentials, backups and current OpenClaw evidence were preserved.
