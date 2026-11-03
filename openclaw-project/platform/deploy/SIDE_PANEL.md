# Side chat in the customer's own Chrome (a Lumina chat beside any tab)

What it is: Chrome's side panel on **any tab** is a chat with Lumina, like the ChatGPT and Claude browser extensions. Opening it is a **new session**: a new conversation (titled "Browser extension" in Lumina), the
customer's assistant woken up if it is asleep, and nothing carried over from the last time. A message starts a task (it steers one only if a run is already going). The work can happen **in a new tab**
(the way browse jobs always have: a tab Lumina opens itself in a "Lumina" group), **in the tab the customer is on**, or **in another open tab**: the last two only after the customer pressed *Allow Lumina to use
this tab*. The messages are in the same conversation list as the web chat (labelled "sent from this panel").

```
panel page ─ runtime port ─ service worker ── HTTPS: device token ──▶ Caddy /v1/panel/session ─▶ web app ─▶ browse service (device_auth) · ChatService (new conversation) · prewarm (wakes the cell)
                                           └─ HTTPS: panel ticket ──▶ Caddy /v1/panel/*       ─▶ web app ─▶ ChatService.send / EventService
browse job (the assistant's browser tool) ─ BrowseRpc start(tab=g1) ─▶ browse service ─ device WebSocket ─▶ extension: `attach` to the allowed tab (or `open` in a new one)
```

Two ways the panel gets its ticket: **its own session** (above; the extension signs in with its paired-device token, which only the browse service can check) and, as before, a ticket the request worker hands over
on the device link while a **web-chat task** runs in the customer's Chrome (offered in a banner; the panel switches to it only when the customer presses the button).

Design notes and the threat model: `platform/THREAT_MODEL.md` ("Side panel"). Routes: `API_MATRIX.md`, `openapi.json`.

## Setup on the server
1. A signing key in the web app's own state directory (`/etc/agentai-platform` is root-only, so the app cannot read a key placed there), readable **only by the app user** (not by the browse service, which runs as root but never reads it, and must not be given a copy):
   `head -c 48 /dev/urandom | base64 > /var/lib/agentai-platform/panel.secret; chown agentai-platform: /var/lib/agentai-platform/panel.secret; chmod 0400 /var/lib/agentai-platform/panel.secret`
   (needs 32 bytes or more; a shorter file leaves the feature off).
2. Web app and request worker environment (`accounts.env`):
   `AGENTAI_PANEL_SECRET_FILE=/var/lib/agentai-platform/panel.secret`
   `AGENTAI_PANEL_ORIGINS=chrome-extension://<the extension id>` (comma separated for several: the store build and any development build). The id is on `chrome://extensions`; a store build keeps one id.
3. Migration `0032_chat_surface` (adds the nullable `chat_messages.surface` column): `deploy/release.py` or `manage.py migrate`.
4. Release the backend as usual and restart `agentai-request-worker`, `agentai-browse` (new `device_push` and `device_auth` operations; `start` takes an optional `tab`) and the web app. Caddy needs no change: `/v1/panel/*` rides the existing `/v1/*` rule to the web app.
5. Ship the extension (`python3 browse/extension/package.py`): version **0.3.0** is a new interface. It adds the permissions `tabs`, `scripting` and `contextMenus`, an **optional** all-sites permission (asked for only inside the panel, by the customer), a keyboard shortcut, and removes the toolbar popup (the button opens the panel). Chrome asks existing users to approve the new permissions when it updates. Publish `privacy.html` first (`platform/privacy/README.md`).

The owner switch for browser tasks (`browse_tasks`) is also the switch for this feature; there is no separate one. No key file, or no origin, means the feature is off everywhere (the routes answer 404).

## How a customer uses it
Pair the browser once (Lumina, Settings, Your browser, Connect; or type the code in the panel). Then click the Lumina button, press Ctrl+Shift+L (Command+Shift+L on a Mac), or right-click selected text and choose
*Ask Lumina*: the panel opens beside whatever tab they are on, switches Lumina on if it was off, and starts a new session. Enter sends, Shift+Enter adds a line, Stop stops the run.

* **Where to work:** *New tab* (default; Lumina opens its own tab), *This tab* or *Another tab* (a picker of the window's tabs). The last two need *Allow Lumina to use this tab* first; *Stop allowing* withdraws it.
* **Browse or Chat:** Browse uses the browser; Chat answers (it may still use tools). Working in an allowed tab always browses.
* **Page awareness:** the panel sends the title and address of the tab, and, if the customer allowed reading pages (Chrome's own prompt, from the panel's settings), the selected text (4,000 characters) and the page text
  (20,000), unless they untick *Include what is on the page*. Quick actions (summarize, explain the selection, key facts, draft a reply, translate, research) and the customer's own saved prompts are one press.
* **The assistant waking:** the session start and every send wake a sleeping assistant; the panel shows "Waking your assistant" until it is up (about a minute the first time).

## Limits worth knowing
* A panel session is one conversation. Closing the panel ends it; opening it again starts a new one (the old one stays in Lumina's chat history).
* The panel polls (state and activity about every 1.5 s while a task runs, 4 s otherwise, 10 s when hidden); there is no long-lived stream, so the web app's single worker is never held.
* A second computer taking over, the customer switching Lumina off, or the link dropping removes every panel's ticket at once; it shows "Connecting" or "off" and cannot send.
* An allowed tab is attached (Chrome shows its "debugging this browser" bar on it) only while a task works in it, and let go of afterwards; it is never closed by Lumina and keeps its own size. Pressing Cancel on
  that bar stops everything. Chrome's own pages, other extensions' pages and the Web Store cannot be allowed.
* Rate limits: 600 requests/min per address before a ticket is checked, then 240 reads or 30 writes per minute per account; 40 new sessions per 10 minutes per account.

## Roll back
Remove `AGENTAI_PANEL_ORIGINS` (or the key file) and restart the app and worker: the routes answer 404 and no tickets are minted; panels already open show "Reconnecting" and can do nothing.
The migration is additive and can stay.
