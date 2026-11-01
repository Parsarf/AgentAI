# Automatic deploys from GitHub

A push to `main` that passes **Lumina CI** is deployed to the server by `.github/workflows/deploy.yml`. The website on Vercel deploys itself from `main` as before and is not part of this.

```
merge to main -> Lumina CI passes -> "Deploy to server" builds the web app
  -> one upload over SSH -> /usr/local/sbin/agentai-deploy (this folder: agentai-deploy)
       1. app tree through release.py: canary on a COPY of the database, probes, atomic switch, automatic rollback
       2. supervisor tree: copy of the live one with the new files laid over, atomic switch
       3. web app bundle (/var/lib/agentai-platform/ui, previous kept as ui.prev)
       4. restart agentai-cell-bridge, agentai-browse, agentai-tool-relay, agentai-request-worker and check they are active
```

Database migrations run automatically (step 1, on a copy first, then live with a pre-migration backup; if the old code cannot read the new schema, a rollback restores the backup).

## What the key can do

GitHub holds one SSH key. On the server it sits in `/root/.ssh/authorized_keys` as

```
restrict,command="/usr/local/sbin/agentai-deploy" ssh-ed25519 AAAA... github-deploy
```

so it can run only that program: no shell, no forwarding, no other command. The program accepts exactly `deploy <40-hex commit>` or `deploy-dry <40-hex commit>`, refuses archives that could write outside their folder, takes a lock so only one deploy runs, and does nothing for a commit that is already deployed. It never touches customer data, secrets or cells. It does run as root, because the releases and services are root's: **anyone who can merge to `main` can change what runs as root**. Keep `main` protected.

## Switching it on and off

- Off by default. It deploys only when the repository variable `AUTO_DEPLOY_ENABLED` is `true` (Settings → Secrets and variables → Actions → Variables). Set it to anything else to stop all automatic deploys.
- **Run workflow** (Actions → Deploy to server → on `main`) always works. It defaults to a **dry run**: build, canary and probes, then stop with nothing live changed. Untick "Dry run" to deploy that commit by hand.
- If `main` has moved on by the time a run starts, the older run skips itself; the newer commit's own run deploys.

## Secrets (Settings → Secrets and variables → Actions)

`DEPLOY_SSH_KEY` (private key), `DEPLOY_KNOWN_HOSTS` (the server's host key line, so GitHub checks it is talking to the real server), `DEPLOY_HOST`, `DEPLOY_USER`. They are available to the `production` environment's job only.

## Install on the server (once)

```
install -m 0755 -o root -g root platform/deploy/agentai-deploy /usr/local/sbin/agentai-deploy
# add the restrict,command="..." line above to /root/.ssh/authorized_keys
```

Update the program itself by installing it again; it is not replaced by its own deploys.

## Undo

- Supervisor tree: `ln -sfn <previous release> /opt/agentai-supervisor/current && systemctl restart agentai-cell-bridge agentai-browse agentai-tool-relay agentai-request-worker` (the log line of the deploy names it).
- App tree: `release.py` already rolled back by itself when the live probes failed. Otherwise point `/opt/agentai-platform/current` at the previous folder in `releases/` and restart `agentai-platform-app`; if a migration ran and the old code cannot read it, restore the `backup-*-premigrate-*.sqlite3` it took.
- Web app: `cd /var/lib/agentai-platform && mv ui ui.bad && mv ui.prev ui`.
- Log of every deploy: `/var/lib/agentai-deploy/deploys.log`; last deployed commit: `/var/lib/agentai-deploy/last`; `release.py` also writes `/var/lib/agentai-ops/releases.log`.

## Not covered

The browse runner in `/opt/agentai-browse` (`openclaw-project/browse`), Caddy, systemd unit files, environment files and the cell images. Those still need a manual step.
