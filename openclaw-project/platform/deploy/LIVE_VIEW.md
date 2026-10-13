# Live view (watch and hop in on browser tasks)

What it is: the Lumina **Live view** page shows a running browser task as a live picture (about 5-8 frames a second), and a customer can
**hop in** (Lumina finishes its current step, then waits) to click, type and scroll, and hand the page back.

## How it stays smooth for the rest of the site
* The web app (one synchronous gunicorn worker) is **never** held open for video. It only mints a short-lived ticket (one tiny request per minute).
* Frames come from a small server inside the **browse service** (`agentai_platform/live/gateway.py`, its own threads, loopback port 18801).
  Each viewer asks "newest frame, if it changed since X"; the server holds the question about 2.5 s. Slow viewers skip frames; nothing queues.
* The browser stage only captures while someone is watching (a `watching` marker the gateway refreshes). No viewer, no screencast, no cost.
  A hidden browser tab stops asking, so capture stops within about 6 s. Only the newest frame is kept (`out/live.jpg`).
* The gateway is limited to 12 simultaneous waiting viewers; more get "try again".

## Privacy
* Tickets are HMAC-signed, expire in 2 minutes, are bound to one account and one task, and are **view only**. Controlling the page still needs the
  signed-in session (`/v1/browse/<id>/pause|resume|control`). Pausing does not store anything you type; the record keeps only "you typed".
* Frames live in the same 0700 job folder as screenshots and are deleted with it after 24 hours. The gateway runs inside the browse service
  because only that process may read those folders; no folder permissions were loosened.

## One-time setup on the server (not done by the repo)
1. Create the shared secret, readable by root only (the browse service) and by the web app's group:
   `head -c 48 /dev/urandom | base64 > /etc/agentai-platform/live.secret; chown root:agentai-platform /etc/agentai-platform/live.secret; chmod 0640 /etc/agentai-platform/live.secret`
2. Web app environment (`accounts.env`): `AGENTAI_LIVE_SECRET_FILE=/etc/agentai-platform/live.secret`. Restart the app service.
3. Restart `agentai-browse` (it starts the gateway when the secret file exists; without it, live view is simply off and the page shows snapshots).
4. Caddy: install the new `@liveframe` block from `caddy/Caddyfile.getlumina`, `caddy validate`, then reload. It allows exactly `/live/<32 hex>/frame`.
5. Vercel: redeploy `deploy/vercel` (adds the same single path to the output routes).
6. Ship the new Lumina bundle with `bin/deploy-lumina.py --apply` (and the new runner: `/opt/agentai-browse/runner/runner.mjs`).
   The stage image does not need to change: the screencast uses Chrome's built-in protocol.

Roll back: remove `AGENTAI_LIVE_SECRET_FILE` and restart the app (the page falls back to snapshots), or `mv ui.prev ui` for the page itself.

## Not covered yet
* Coding and computer tasks: the Terminal and Files views follow the agent's tool events (about 1.5 s behind, output trimmed and redacted).
  A true live terminal or a full desktop (with hop-in) needs new runtime support inside the agent's cell and is a separate piece of work.
* The browse service runs one browser stage at a time on this server; live view does not change that.
