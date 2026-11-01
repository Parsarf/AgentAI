# The customer's own Chrome (the `local` browse engine)

What it is: instead of the host's Docker stage or the account's cell browser, a browse task can run in a **tab of the customer's own Chrome**, through the Lumina
extension (`browse/extension/`). Same runner protocol, same loop, same safety rules; only the hands differ. Status (2026-10-31): released for a trial that only the owner's account can use (`"local": [<owner account id>]` in `browse-engine.json`); the server code, the pairing API and the website's browser icon are live. The `/v1/device` route is installed in `/etc/caddy/Caddyfile` (backup `Caddyfile.bak-device-20261031T221954Z`; undo: copy it back and `systemctl reload caddy`), and the owner's extension has paired and connected. The extension has not yet been tried by hand in a real Chrome (see `browse/extension/README.md`). To open it to everyone: publish the extension, then delete the `local` line from `browse-engine.json`.

## Pieces (all inside the browse service, `agentai_platform/browse/`)
| File | Does |
|---|---|
| `devices.py` | Pairing codes, device tokens (only a hash is kept, `devices.json`, 0600), the hub of live connections (one per account, newest wins), the command line. |
| `ws.py` | A strict standard-library WebSocket server side (masked client frames, text only, 8 MB cap, no extensions). No new dependency. |
| `device_gateway.py` | `wss://backend.../v1/device` on loopback port 18802: Origin check, login in the first message within 10 s, global failed-login limit, idle drop (75 s), sweep for revoked devices. |
| `device_transport.py` | The runner protocol over a link; writes `shot-NNN.jpg` from the extension's base64 pictures and refuses anything that is not a small JPEG. |
| `service.py` / `service_main.py` | `Job.engine == 'local'`, `local_spawn`, `pick_engine`. The engine is fixed per job and never switches mid-run. |

## How it is switched on
It is for everyone; each customer decides for themselves.
1. **The customer's switch** is the browser icon at the top of every chat (existing conversations and new ones). It stores "use my own browser" per account in `devices.json` (`POST /v1/devices/use`). It starts off. The icon is hidden until the browse service answers `GET /v1/devices` with `available: true`.
2. **A task runs in their Chrome only when all three hold:** the switch is on, the Lumina extension is on and connected right now, and the feature is not off for everyone. Otherwise the task runs in the hosted browser as before; the icon says which (off / on but no browser paired / on and waiting for the extension / live).
3. **Who may use it** is set in `browse-engine.json` (read at every job start): no `local` line = everyone; `"local": false` = nobody (pairing and the switch answer "not available" and the icon disappears); `"local": ["<account id>", ...]` = only those accounts, which is how it is tried out before it is opened up. (`"native"` and `"default"` in that file are unchanged and apply when the customer's own Chrome is not used.)
4. **Pairing a computer:** Settings → Your browser → Connect a browser. The page asks `POST /v1/devices/pair`, shows the code (`ABCD-2345`, 10 minutes, one use), and, if the extension's id is built into the page (`VITE_LUMINA_EXTENSION_ID`), hands it over by itself; otherwise the customer types it in the extension's popup. From the command line: `python -m agentai_platform.browse.devices pair --account <id>`. `devices list|revoke --account <id> [--device <id>]` also work. A revoked device's connection is dropped within 15 seconds.
5. **Proxy:** `Caddyfile.getlumina` routes `/v1/device` to 127.0.0.1:18802. Service flags: `--device-port` (0 = off), `--device-store`, `--device-origin chrome-extension://<id>` (repeatable; without it any extension origin may knock, the token is still required).

## What a task on this engine does differently
* No host memory check and no shared stage: the only wait is for the same account's previous browser job (the customer has one Chrome).
* No live view: the customer watches the real tab. Pictures for the loop and the hand-over come through `view` / `screenshot` as usual.
* If the extension is not connected when the task starts: the task ends with "your browser is not connected" (it does not quietly use the host's browser). If Chrome closes mid-task the task ends with an error; the customer pressing Cancel on Chrome's debugging bar ends it too.

## Privacy and risk notes (feed into THREAT_MODEL.md at the security review)
* **The public privacy policy covers this engine** (`deploy/vercel/public/privacy.html`). Changing the extension's permissions, what it stores or sends, which servers it reaches, or any retention time makes `tests/test_privacy_policy.py` fail on purpose: review the policy before you fix the test (`platform/privacy/README.md`).
* The extension acts only on tabs it opened, asks for no host permissions, and refuses private/loopback/link-local addresses and non-http(s) schemes itself, whatever the platform sends.
* The device token is a bearer secret in the customer's Chrome profile storage; it is shown once (over TLS) and stored hashed here. Revoke on loss.
* Pictures and page text from the customer's computer are customer data: they follow the same retention (`screenshot_retention`) and purge as every other engine's job folder.
* Sensitive clicks (pay, delete, send, passwords), payment pages, denied sites and human-check stops are decided by the browse loop, which does not depend on the engine, so they apply here too.
* Customer routes (`accounts/devices.py`): `GET /v1/devices`, `POST /v1/devices/use` (a real true/false only), `POST /v1/devices/pair` (10 per 10 minutes), `POST /v1/devices/<id>/revoke`; pair, revoke and the switch are audited (the code is never written to the audit trail). The extension never lets a web page choose where it connects; the page can hand over a pairing code and nothing else.
* **Consent model (decided 2026-10-30): one switch.** While the extension is on, the agent may work on any site it is sent to; the loop's own stops still apply. There is no per-site approval list. The mitigation is a separate Chrome profile for Lumina, which the Settings card and the popup both recommend. Per-site approvals with an expiry (enforced in the extension, first visit pausing the task with a question) were considered and deferred until the extension has been tried in a real Chrome.
* Not yet: download and permission blocking in the extension.
