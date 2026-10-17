# Live view (watch and hop in on browser tasks)

What it is: the Lumina **Live view** page shows a running browser task as a live picture (up to 15 frames a second at 1280x800), and a customer can
**hop in** (Lumina finishes its current step, then waits) to click, type and scroll, and hand the page back.

## How it stays smooth for the rest of the site
* The web app (one synchronous gunicorn worker) is **never** held open for video. It only mints a short-lived ticket (one tiny request per minute).
* Frames come from a small server inside the **browse service** (`agentai_platform/live/gateway.py`, its own threads, loopback port 18801).
  Each viewer asks "newest frame, if it changed since X"; the server holds the question about 2.5 s. Slow viewers skip frames; nothing queues.
* The browser stage only captures while someone is watching (a `watching` marker the gateway refreshes). No viewer, no screencast, no cost.
  A hidden browser tab stops asking, so capture stops within about 6 s. Only the newest frame is kept (`out/live.jpg`).
* The gateway is limited to 12 simultaneous waiting viewers; more get "try again". A frame up to 3 MB is served (a busy page can pass 1 MB).
* A hand-off (the agent stopped and waits for you) keeps the browser for 10 minutes, but only 2 minutes once another browser task is waiting for it; a customer's own next task closes their idle hand-off at once. A customer who has the wheel (hopped in) is never cut off by a new task.
* If the browse service restarts, a running task is gone (it keeps no state): the request ends within seconds with "the browser session was lost" instead of holding the queue until its timeout.

## Cost to know about
While someone watches, the browser stage replaces `out/live.jpg` up to 15 times a second (roughly 3 MB/s of disk writes for a busy page; nothing accumulates, the file is replaced). That is a trade between smoothness and disk wear: the rate is `LIVE.fps` in `browse/runner.mjs` (lower it to 8 for about half the writes). Nothing is written when nobody watches.

## Privacy
* Tickets are HMAC-signed, expire in 2 minutes, are bound to one account and one task, and are **view only**. Controlling the page still needs the
  signed-in session (`/v1/browse/<id>/pause|resume|control`). Pausing does not store anything you type; the record keeps only "you typed".
* Frames live in the same 0700 job folder as screenshots and are deleted with it after 24 hours; the service checks every 15 minutes, whether or not any task is running. The gateway runs inside the browse service
  because only that process may read those folders; no folder permissions were loosened.

## Route
Frames are fetched from `/v1/live/<task>/frame`, which rides the `/v1` route that Vercel already forwards to the server: no Vercel change.
On the server, Caddy sends exactly that path shape to the gateway (`127.0.0.1:18801`) **before** its general `/v1` rule
(see `caddy/Caddyfile.getlumina`); everything else under `/v1` still goes to the web app.

## Setup on the server
1. Secret, readable by root (the browse service) and the web app's group:
   `head -c 48 /dev/urandom | base64 > /etc/agentai-platform/live.secret; chown root:agentai-platform /etc/agentai-platform/live.secret; chmod 0640 /etc/agentai-platform/live.secret`
2. Web app environment (`accounts.env`): `AGENTAI_LIVE_SECRET_FILE=/etc/agentai-platform/live.secret`.
3. Release the backend (`deploy/release.py`), put the same `agentai_platform` into a new `/opt/agentai-supervisor/releases/<id>` and switch its
   `current` link, restart `agentai-request-worker` and `agentai-browse` (the browse service starts the gateway when the secret file exists;
   without it, live view is simply off and the page shows snapshots).
4. Copy the new `browse/runner.mjs` to `/opt/agentai-browse/runner/` (each browser job mounts it fresh).
5. Caddy: add the `@liveframe` block, `caddy validate`, reload.
6. Ship the Lumina bundle with `bin/deploy-lumina.py --apply`.

Roll back: remove `AGENTAI_LIVE_SECRET_FILE` and restart the app (the page falls back to snapshots); `mv ui.prev ui` for the page itself;
`release.py` rolls the web app back on its own if the new release fails its probes; point the supervisor `current` link back and restart the browse service.

## Not covered yet
* Coding and computer tasks: the Terminal and Files views follow the agent's tool events (about 1.5 s behind, output trimmed and redacted).
  A true live terminal or a full desktop (with hop-in) needs new runtime support inside the agent's cell and is a separate piece of work.
* The browse service runs one browser stage at a time on this server; live view does not change that.
