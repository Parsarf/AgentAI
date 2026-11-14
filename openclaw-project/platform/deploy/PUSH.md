# Push gateway (task state streamed to open tabs)

What it is: `agentai_platform/live/push.py`, a small read-only server beside the web app. An open Lumina tab holds one `text/event-stream`
connection to it and is told the moment a task changes (status, tool use, a permission prompt, the reply being written). The web app is one
synchronous worker and is never held open: it only mints a ticket (`POST /v1/work/ticket`, about once a minute per tab).

Nothing here is deployed by a release on its own. Until the steps below are done, `POST /v1/work/ticket` answers 404 and the app polls
`/v1/work` and `/v1/work/<id>` (the same code, so nothing looks different except that updates are a second or two later and replies arrive whole).

## Turn it on
1. The shared secret is the Live view's: `/etc/agentai-platform/live.secret` (32+ random bytes, readable by `agentai-platform`). If Live view is
   already on, it exists.
2. Install and start the unit: `deploy/agentai-push.service` (loopback port 18803, user `agentai-platform`, reads the platform database, asks the cell
   bridge for reply drafts). The `agentai-platform` user must be allowed on the cell bridge socket (it already is: the request worker uses it).
3. Caddy: add the block marked "Task state stream" from `deploy/caddy/Caddyfile.getlumina` (it must come before the general `/v1` rule) and reload.
4. Web app environment (`accounts.env`): `AGENTAI_PUSH_PATH=/v1/push`, then restart the app.
5. Check: open a chat, start a task, and look at the Network tab for one `push?...` request of type eventsource that stays open about 45 s and is
   replaced by the next one. `curl -s localhost:18803/v1/push?t=x` answers 403.

Vercel forwards `/v1/*` to this host. A streamed response must not be buffered on the way: the gateway sends `X-Accel-Buffering: no` and
`Cache-Control: no-store`, and Caddy is told `flush_interval -1`. If a proxy in front buffers anyway, the tab notices that no `hello` arrived and falls
back to polling by itself; nothing breaks, it is just slower. Verify step 5 from the public address, not only from the server.

## Limits and cost
* One thread per open tab; 6 tabs per account, 96 in all, then tabs are told to poll (429).
* Each stream asks SQLite one cheap question four times a second (`PRAGMA data_version`) and reads task rows only when something was committed.
* A stream lasts 45 s, then the tab reconnects with a fresh ticket and its cursors. Signing out or revoking sessions therefore ends streaming within
  about two minutes (one ticket lifetime plus one window) without any session lookups in the gateway.
* Reply drafts are asked of the cell's relay only while a tab is focused on a running task. Set `PUSH_DRAFTS=0` to turn drafts off and keep the rest.

## Privacy
* A ticket is HMAC-signed, lasts 90 s, names one account and one member, and is read-only. Every read re-checks that member against the database.
* The gateway never writes, never logs request lines (the query holds the ticket), and keeps nothing between connections.
* A draft is the visible reply text of the focused task's own run (the run id is derived from the task id and checked). It is never stored; the saved
  message replaces it. Tool use shown in the timeline still comes from Lumina's own redacted records, not from the runtime's event text.

## Roll back
Remove `AGENTAI_PUSH_PATH` and restart the app: every tab polls. Then `systemctl disable --now agentai-push` and remove the Caddy block.
