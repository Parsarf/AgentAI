# Side panel chat (mini chat beside the agent's tab in the customer's own Chrome)

What it is: while the assistant works in a tab of the customer's own Chrome (the `local` browser engine), Chrome's side panel next to that tab shows what it is doing and a small chat.
The customer can type to steer the running task, or press Stop. Messages go into the **same conversation** as the web chat (labelled "sent from this panel") and show there live.

```
panel page ─ runtime port ─ service worker ── HTTPS + ticket ──▶ Caddy /v1/panel/* ──▶ web app ──▶ ChatService / EventService
worker (app user) ─ mints ticket ─ BrowseRpc device_push ─▶ browse service ─ device WebSocket ─▶ extension (opaque relay)
```

Design notes and the threat model: `platform/THREAT_MODEL.md` ("Side panel"). Routes: `API_MATRIX.md`, `openapi.json`.

## Setup on the server
1. A signing key readable **only by the app user** (not by the browse service, which runs as root but never reads it, and must not be given a copy):
   `head -c 48 /dev/urandom | base64 > /etc/agentai-platform/panel.secret; chown agentai-platform: /etc/agentai-platform/panel.secret; chmod 0400 /etc/agentai-platform/panel.secret`
   (needs 32 bytes or more; a shorter file leaves the feature off).
2. Web app and request worker environment (`accounts.env`):
   `AGENTAI_PANEL_SECRET_FILE=/etc/agentai-platform/panel.secret`
   `AGENTAI_PANEL_ORIGINS=chrome-extension://<the extension id>` (comma separated for several: the store build and any development build). The id is on `chrome://extensions`; a store build keeps one id.
3. Migration `0032_chat_surface` (adds the nullable `chat_messages.surface` column): `deploy/release.py` or `manage.py migrate`.
4. Release the backend as usual and restart `agentai-request-worker`, `agentai-browse` (new `device_push` operation) and the web app. Caddy needs no change: `/v1/panel/*` rides the existing `/v1/*` rule to the web app.
5. Ship the extension (`python3 browse/extension/package.py`): version **0.2.0** adds the `sidePanel` permission. Existing installs update to it and keep working; the panel appears on the next task.

The owner switch for browser tasks (`browse_tasks`) is also the switch for this feature; there is no separate one. No key file, or no origin, means the feature is off everywhere (the routes answer 404).

## How a customer uses it
Turn Lumina on in the toolbar popup, start a browser task with "use my own browser" on, then press **Open chat beside the task** in the popup (Chrome only opens a side panel from a click).
Enter sends, Shift+Enter adds a line, Stop stops the run. When the task ends the panel shows how it ended and Send turns off; the chat continues in Lumina.

## Limits worth knowing
* Send steers a **running** task; it never starts one. After the run, writing happens in Lumina.
* The panel polls (state and activity about every 1.5 s while a task runs, 4 s otherwise, 10 s when hidden); there is no long-lived stream, so the web app's single worker is never held.
* A second computer taking over, the customer switching Lumina off, or the link dropping removes the panel's ticket at once; it shows "Reconnecting" or "off" and cannot send.
* Anonymous ingress limiting does not apply to `/v1/panel/*`; the panel meters itself (600 requests/min per address before a ticket is checked, then 240 reads or 30 writes per minute per account).

## Roll back
Remove `AGENTAI_PANEL_ORIGINS` (or the key file) and restart the app and worker: the routes answer 404 and no tickets are minted; panels already open show "Reconnecting" and can do nothing.
The migration is additive and can stay.
