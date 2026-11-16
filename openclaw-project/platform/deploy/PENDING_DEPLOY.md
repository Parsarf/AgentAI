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

## The mail and calendar dashboard

**Done on 2026-11-16:** merged (pull request #50) and live; the sync timer is installed and its fact recorded; the Google client id and secret are in the server's
environment file; the owner turned `mail_calendar_dashboard` on that day (both confirmations recorded on their word; **the policy text for the copy is still to be written and
published**). `customer_uploads` is off. The steps below are kept as the record.

Built so far: the provider-neutral model, the background sync, the reading routes (`/v1/hub/...`) and the owner switch `mail_calendar_dashboard` (off). No real provider
is registered yet, so turning the switch on today would show two empty pages. When this is deployed:

1. **Migration 0048** only adds tables (`hub_*`). The previous release ignores them.
2. **Install and enable the sync timer**: `agentai-hub-sync.service` and `agentai-hub-sync.timer` from `platform/deploy/` (it runs `manage.py hub_sync` every minute and is
   idle while the switch is off). Then record the fact `hub_sync_timer` in the switch facts file.
3. **Privacy policy before the switch**: the policy must describe the copy Lumina keeps (mail headers and previews for 90 days, opened messages for 90 days after they were
   last opened, events from one month back to twelve months ahead) and where it comes from. The retention table already holds these rows (`mail_headers`, `mail_bodies`,
   `calendar_events`) and the sweeper enforces them. The public page and `privacy/facts.json` are **not** changed yet.
4. **Google, the first provider** (built: `agentai_platform/google_hub.py`, read only):
   - In the Google Cloud console, on the sign-in client whose id is in the local `.env`: add the authorized redirect address **`https://getlumina.pro/v1/hub/link/callback`**
     (exactly; it is `AGENTAI_PUBLIC_ORIGIN` plus `/v1/hub/link/callback`), enable the **Gmail API** and the **Google Calendar API**, and while the app is in testing add each
     address that will connect as a test user. The scopes asked for are `gmail.readonly` and `calendar.readonly` (plus `openid email`); Gmail read access is a restricted
     scope, so a public launch needs Google's verification.
   - On the server, add `AGENTAI_GOOGLE_CLIENT_ID` and `AGENTAI_GOOGLE_CLIENT_SECRET` to `/etc/agentai-platform/accounts.env` (root-only) and restart the app, the tool relay
     and nothing else. Without both, Google is simply not offered.
   - The connector refresh timer (already installed) renews Google access tokens; it now also runs while only the dashboard switch is on.
   - Proven against the real Google APIs on 2026-11-16 with the owner's own account, read only, from a one-off local check: sign-in and code exchange, the picker's list
     (labels and calendars), the first fill of mail, opening a message, Gmail history, mail limited to one label, older-mail search, the calendar list, a calendar's window with
     its sync token, changes since that token, and token renewal. **Not exercised by real data:** the conversion of real calendar events (the account's primary calendar had none
     in the window) and a message with attachments or markup. Check those with an account that has them before customers connect.
   - The Google project must have the **Google Calendar API** enabled (`calendar-json.googleapis.com`; not the Calendar MCP service) and the **Gmail API**.
   - The consent screen shows the Google project's app name. These credentials belong to the owner's ManagerAI project, so customers would see "ManagerAI": use a client of a
     Lumina project, or rename the app on the consent screen, before launch.
5. **Other providers** need their own sign-in app and that service's review before any customer can connect one.

### Live and complete (2026-11-16, the owner's decision)

- **Everything is copied, not 90 days.** Mail: headers and previews of all the mail in what the customer chose (bodies still only when opened). Calendars: every past event and
  two years ahead. The retention rows `mail_headers` and `calendar_events` now say "until you remove the account"; a number of days can be set there again and is honoured.
  **The policy text must say this** before anyone else is invited.
- **The sync is a service now, not a timer**: `agentai-hub-sync.service` runs `manage.py hub_sync --serve` for good. It asks each mailbox what changed every 20 seconds and
  each calendar every 60, and works through a first fill without pausing (about 100 messages every second or two). On a server that had the timer: `systemctl disable --now
  agentai-hub-sync.timer`, remove the timer unit, install the new service unit, `systemctl enable --now agentai-hub-sync.service`. The deploy program restarts it when it is
  running, so it runs the new code.
- **Open pages are live**: they ask `/v1/hub/pulse` every 8 seconds while visible and reload only when its mark changed.
- **Google is reached over IPv4 first.** The production host has no working IPv6 route and Google lists IPv6 addresses first: each request took about 25 seconds and the first
  sync never finished. Any future provider adapter on this host needs the same care.

## The UI remodel (branch `ui-remodel`, shipped together with #52)

No server step. The web app's layout changed (the workspace frame, one assistant panel, the command bar, Today, Activity as one table, Settings sections). Two routes were
added: `POST /v1/assistant/ask` (the assistant panel on any page; mail and calendar selections pass only while `mail_calendar_dashboard` is on) and `GET /v1/search` (the
command bar). Old app addresses redirect (`/app/tasks` to `/app/activity`, `/app/integrations` to `/app/settings/integrations`, `/app/automations` to `/app/activity`).
The #52 step above still applies: replace `agentai-hub-sync.timer` with `agentai-hub-sync.service`.

### Sync service memory (2026-11-16, after the deploy)

In its first minutes on production the service was killed by its own 384 MB cap while filling the owner's mailbox (three pages of 100 messages took it from 79 MB to
374 MB), and restarted in a loop with back-off. The unit now allows 1 GB and sets `MALLOC_ARENA_MAX=2`. When this release is live, copy the unit again and restart:
`cp /opt/agentai-platform/current/deploy/agentai-hub-sync.service /etc/systemd/system/ && systemctl daemon-reload && systemctl restart agentai-hub-sync.service`.
The cause of the growth during a fill is not found yet: the request path alone levels off at about 110 MB with eight requests in flight.
