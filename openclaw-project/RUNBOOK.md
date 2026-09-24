# OpenClaw operations runbook

Production belongs on the IONOS VPS and must work while the Mac is off. The
deployment plan is [SERVER_DEPLOYMENT.md](SERVER_DEPLOYMENT.md). The temporary
Mac Node/OpenClaw binaries were removed to recover disk space. Its private
staging state is retained only as historical evidence and must not be used as
the server's live state.

## Server checks after deployment

Run from the pinned OpenClaw Compose checkout on the VPS:

```sh
docker compose config
docker compose ps
docker compose run --rm openclaw-cli config validate
docker compose run --rm openclaw-cli secrets audit --check
docker compose run --rm openclaw-cli security audit
```

Check the host listener with `ss -lnt`; ports 18789, 18790 and 3978 must be
bound to `127.0.0.1` only. Check `/healthz` over the loopback listener and
verify Telegram from the owner's numeric account. Run a denial test from a
different account. Keep the model route disabled until the daily and monthly
spend gates have been verified.

## Backup and recovery

Use OpenClaw's `backup create --verify` on the server and keep the archive
private. It includes state and credentials and is not encrypted by default.
Restore into a fresh disposable directory, inspect the reported assets, and
verify that service restart recovers scheduled work. Never restore over live
state. Keep the old Python AgentAI service intact until OpenClaw acceptance
succeeds and the owner chooses retirement.
