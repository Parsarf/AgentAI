# Steps to do by hand when this branch is deployed

Nothing here has been done on the server. Everything in the release is behind owner switches that are **off**, so deploying the code changes nothing a customer sees
until a switch is turned on. The migrations (0044 to 0047) only add; the previous release runs against them.

## With the deploy (roadmap Phase 2 and 3)

1. **Read the prepared privacy-policy change and decide.** `deploy/vercel/public/privacy.html` now states the retention limits the sweeper enforces: the step-by-step
   activity record of a task 30 days (and for chats older than 90 days), security records and account email records 180 days. The page is published by the Vercel build from
   `main`, so merging this branch publishes it. The reviewed record (`privacy/facts.json`, last `review_log` line) says what changed and why. If you do **not** want these
   limits enforced, do not install the retention timer (step 3) and put the two policy rows back before merging.
2. **Install the connector key file** (custody for connected services' tokens): one line `k1:<base64 of 32 random bytes>`, readable by the app user ONLY. The code
   refuses a key file that anyone else can read (mode must be 0600), and custody then stays off:

       python3 -c "import secrets,base64;print('k1:'+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))" > /var/lib/agentai-platform/connector.key
       chown agentai-platform:agentai-platform /var/lib/agentai-platform/connector.key && chmod 0600 /var/lib/agentai-platform/connector.key

   Put it where the vault key file is kept if that is somewhere else (same rule, same owner). Then add `AGENTAI_CONNECTOR_KEY_FILE=<that path>` to `accounts.env` and
   restart the app, the request worker and the tool relay. **Back this file up with
   the other keys**: without it the sealed tokens cannot be opened (connections would have to be made again).
3. **Install and enable the three timers** (unit files are in `platform/deploy/`):

       cp agentai-retention.{service,timer} agentai-account-jobs.{service,timer} agentai-connector-refresh.{service,timer} /etc/systemd/system/
       systemctl daemon-reload && systemctl enable --now agentai-retention.timer agentai-account-jobs.timer agentai-connector-refresh.timer

   `manage.py retention_sweep --dry-run` prints the table and deletes nothing. The first real run deletes activity records older than 30 days and security records older
   than 180 days: this cannot be taken back (backups keep them for up to 30 days).
4. Record the facts the switches need (the ops dashboard's facts file): `connector_custody_ready` after step 2, `data_jobs_timer` after step 3.
5. **Run the live proof** with the test-only switch on, then turn it off again:

       # switches synthetic_connector and connector_writes ON, then:
       sudo systemd-run --wait --pipe --collect --property=User=agentai-platform --property=EnvironmentFile=/etc/agentai-platform/accounts.env \
           --property=WorkingDirectory=/opt/agentai-platform/current /opt/agentai-platform/current/.venv/bin/python deploy/phase23_live.py --hour
       # switch synthetic_connector OFF

   It makes one disposable account, proves the eight gates and deletes the account. It costs nothing (no model call). Without `--hour` the handoff gate waits a few
   seconds instead of an hour and says so.
6. Decide the switches (all off after the deploy): `connector_writes` (no real connector exists until Phase 5, so it changes nothing yet), `account_self_service`
   (export, delete a chat, close the account: publish the policy wording for it first).

## Already in this branch from the Phase 0-1 review

No server step. The request worker, the app, the tool relay and the lifecycle worker restart with the deploy as usual.

## Rollback

Switch the release back with `release.py` (or let the live acceptance do it). The new tables and columns stay and are ignored by the previous release. Before rolling
back, turn `connector_writes`, `synthetic_connector` and `account_self_service` off and disable the three timers, so nothing of the new code is half in use.

## The mail and calendar dashboard (branch `mail-calendar-dashboard`, not merged)

Built so far: the provider-neutral model, the background sync, the reading routes (`/v1/hub/...`) and the owner switch `mail_calendar_dashboard` (off). No real provider
is registered yet, so turning the switch on today would show two empty pages. When this is deployed:

1. **Migration 0048** only adds tables (`hub_*`). The previous release ignores them.
2. **Install and enable the sync timer**: `agentai-hub-sync.service` and `agentai-hub-sync.timer` from `platform/deploy/` (it runs `manage.py hub_sync` every minute and is
   idle while the switch is off). Then record the fact `hub_sync_timer` in the switch facts file.
3. **Privacy policy before the switch**: the policy must describe the copy Lumina keeps (mail headers and previews for 90 days, opened messages for 90 days after they were
   last opened, events from one month back to twelve months ahead) and where it comes from. The retention table already holds these rows (`mail_headers`, `mail_bodies`,
   `calendar_events`) and the sweeper enforces them. The public page and `privacy/facts.json` are **not** changed yet.
4. **A provider**: the sign-in app for each mail and calendar service (an owner item) and that service's review, before any customer can connect one.
