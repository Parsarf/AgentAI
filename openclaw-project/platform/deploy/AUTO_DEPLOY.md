# Automatic deploys from GitHub

> **If `PENDING_DEPLOY.md` exists in this folder, read it before you deploy:** it lists what is merged but not yet deployed and what to check afterwards.

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

so it can run only that program: no shell, no forwarding, no other command. The program accepts exactly `deploy <40-hex commit>`, `deploy-dry <40-hex commit>` or `accept <40-hex commit>`, refuses archives that could write outside their folder, takes a lock so only one deploy runs, and does nothing for a commit that is already deployed. It never touches customer data, secrets or cells. It does run as root, because the releases and services are root's: **anyone who can merge to `main` can change what runs as root**. Keep `main` protected.

## Live acceptance after every deploy (Tier B)

Right after `deploy`, the workflow sends `accept <commit>` (the third command the key may run). The server's deploy program then runs `deploy/acceptance_live.py` as the app user against what
was just deployed: the app is ready and every migration applied; the owner's test account gets one real answer, charged once and settled (a few cents of model time at most; its assistant is woken
if it sleeps); the request carries the version stamp of that commit; a second account cannot read it. **If one check fails the deploy program puts the previous release back by itself**
(both trees, the web bundle, the services, `last`) and exits 40, so the workflow run goes red. One exception: when the answer could not be checked for a reason that is not the release (the host had no room to wake the test account's assistant, the model provider was busy, the test account's allowance is used up, or the test account is missing) the release **stays** and the program exits 42. The run is still red, so somebody looks; run the workflow again when the cause is cleared. The result is kept in `/var/lib/agentai-deploy/tierb.json`; what the last deploy replaced is in
`previous.json`. A failure to roll back is said loudly in the log and needs a person (OPERATIONS.md, `release.py`). A second exception, since 2026-11-24: when the release that
failed has applied a database migration the previous release does not have, it is **not** rolled back and the program exits 43. A release starts only on a database whose schema is
exactly its own migrations, so the previous code would not start at all: that day a failed acceptance (the test account's first project was full, so the test chat could not be
made) was rolled back onto the migrated database and the site was down until a fix was deployed. A failed release that still serves is the better of the two; the fix goes forward. The wider proof (two accounts at once, killing the worker or the cell, rate limits,
large tasks) is `deploy/phase1_live.py` with `deploy/phase1_root.sh`: run it by hand before a launch or after a big change.

## Hand-made releases are never silently undone

`push-release.py` overlays single files on the live server. Before anything else, the deploy program checks the files those manual releases recorded (`source_sha256` in `RELEASE.json`, both trees) against the incoming code. If the server runs a file that the commit does not contain unchanged, the deploy **refuses** (exit 30) and lists them. Fix: commit and merge those files to `main`. Last resort: run the workflow by hand with "overwrite manual changes", which replaces them.

After a deploy finishes, the record of hand-released files is cleared from both trees (`forget_manual`): the server then holds exactly that commit, so the record describes nothing. Before this was added (November 2026) the record was never cleared, so every commit that touched a once hand-released file was refused and each deploy had to be rerun by hand with "overwrite manual changes". The deploy program is not updated by its own deploys: reinstall it (below) to get this behaviour.

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
- App tree: `release.py` already rolled back by itself when the live probes failed. Otherwise point `/opt/agentai-platform/current` at the previous folder in `releases/` and restart `agentai-platform-app`; if a migration ran, the old code will NOT start on the migrated database (it requires exactly its own migrations): deploy a fix forward instead. Restoring the `backup-*-premigrate-*.sqlite3` loses everything written since it was taken and is the last resort.
- Web app: `cd /var/lib/agentai-platform && mv ui ui.bad && mv ui.prev ui`.
- Log of every deploy: `/var/lib/agentai-deploy/deploys.log`; last deployed commit: `/var/lib/agentai-deploy/last`; `release.py` also writes `/var/lib/agentai-ops/releases.log`.

## Not covered

Caddy, systemd unit files, environment files and the cell images. Those still need a manual step. The browse runner itself is covered since 2026-11-22: each release carries `agentai_platform/browse/hosted_runner.mjs` and the browser service mounts it over the installed one; only the runner's `node_modules` in `/opt/agentai-browse/runner` are still installed by hand, when `browse/package.json` changes.

## Faster and safer (2026-11-16)

Four changes after a deploy that took three cycles of about twenty minutes each:

1. **A release proves itself before it goes live.** After the canary probes, `release.py` runs the release's own proof script (`deploy/phase23_live.py --copy`) against the
   migrated COPY of the production database. A failure stops the deploy with nothing live touched. Both faults found after going live on 2026-11-16 (a sign-in address that
   must be unique, a check that met a deleted account) depended on production-shaped data and would have stopped here.
2. **One command equals CI.** `openclaw-project/ci/run.sh all` runs every blocking part on a developer's machine, in parallel (about four minutes). CI runs the same script,
   one part per job, and a test keeps the workflow and the script equal. Run it before opening a pull request.
3. **No second run for the same files.** A pull request runs the checks once. The push to main that merges it skips them when the merged files are identical to what the
   pull request tested and that run was green (`ci/already-tested.sh`); the deploy then starts at once. A branch that was behind main gets the full checks. A branch push
   alone runs nothing.
4. **Parallel parts.** The account API tests run as three jobs and the platform tests as two, beside the acceptance cases, the small checks and the web app.
