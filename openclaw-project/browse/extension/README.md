# Lumina browser extension (development build)

A third kind of "hands" for the browse service, next to the Docker stage (`../runner.mjs`) and the cell's own browser (`platform/agentai_platform/browse/native_runner.py`):
it does the **same runner protocol** (`open`, `snapshot`, `act`, `xy`, `view`, `probe`, `screenshot`, `close`) in a new tab of the customer's own Chrome.
The platform decides; the extension performs one validated step at a time and answers with the runner's fields.

```
platform (job, consent) --WebSocket--> src/background.js --> src/executor.js --chrome.debugger--> tab in a "Lumina" group
```

| File | Does |
|---|---|
| `manifest.json` | MV3. Permissions: `debugger`, `tabGroups`, `storage`. No host permissions: it can only act on tabs it opened itself. `externally_connectable`: the Lumina page only. |
| `popup.html`, `src/popup*.js` | The toolbar popup: status, pairing code box, Turn on / off. |
| `src/config.js` | The production address, the Lumina page origin, the pairing-code format. |
| `src/executor.js` | The runner's commands over the DevTools protocol, behind a small `host` interface (so tests drive it with Playwright). |
| `src/background.js` | The Chrome side: the tab group, `chrome.debugger`, popups, the WebSocket link, the on/off button. |
| `panel.html`, `src/panel*.js`, `src/panel.css` | The side chat beside a Lumina tab: activity trail, chat, Send and Stop. `panel-model.js` is the pure part (what to show, what may be sent); `panel-link.js` holds the ticket in the service worker and makes the calls, so the page never sees it. |
| `src/page.js` | Page-side helpers. `describe`, `hitAt`, `focusActive`, `fingerprint`, `ready` are copied from `../runner.mjs` and a test fails if they drift. |
| `src/rules.js` | Address policy and limits, checked against `../runner.mjs` by a test. |
| `dev/ws-server.mjs`, `dev/drive.mjs` | A dependency-free bridge and a scripted demo (no model). |

Tests (from `browse/`): `node --test test/extension-*.test.mjs`
- `extension-panel`: the side chat's model, ticket link, popup choice of tab and the worker's wiring (fake `chrome`).
- `extension-panel-page`: `panel.html` in real Chrome with a scripted worker (text stays text, one key per send, Send only while a task runs).
- `extension-executor`: the executor against real Chrome (Playwright as the host) on the mock shop.
- `extension-parity`: page helpers, address policy and limits equal the runner's.
- `extension-bridge`: the dev WebSocket server.
- `extension-worker`: `background.js` against a fake `chrome` API.

## Loading the folder in Chrome ("Load unpacked")
Chrome refuses a folder that contains any file or folder whose name starts with `_` (it says "Filenames starting with "_" are reserved"). The usual culprit is Python's `__pycache__`. If you see that error, delete it: it is only a cache. Tests here run Python with `-B` so they no longer create it, and `test/extension-package.test.mjs` fails if one appears. A cleaner alternative is to unzip `dist/lumina-browser-<version>.zip` (made by `python3 package.py`) and load that: it holds only what the extension needs.

## Try it by hand
Branded Chrome (137+) ignores `--load-extension`, so load it from the page:
1. `node extension/dev/drive.mjs` (starts the mock shop and the bridge on `ws://127.0.0.1:8765/device`).
2. `chrome://extensions` -> Developer mode -> Load unpacked -> `browse/extension`.
3. In the extension's service worker console: `chrome.storage.local.set({ bridge: 'ws://127.0.0.1:8765/device', token: 'dev', devAllowLoopback: true })` (loopback is for this demo only; the extension connects to production unless the stored address is this computer).
4. Click the toolbar button, then "Turn on". A "Lumina" tab opens, the script browses the shop, pictures land in `$TMPDIR/lumina-ext`.
Chrome shows "Lumina is debugging this browser" on those tabs. **Cancel on that bar is the stop button**: the session ends and its tabs close.

The platform side (device gateway, pairing, the `local` engine) is in `platform/agentai_platform/browse/`; see `platform/deploy/DEVICE_BROWSER.md`.
`dev/device-sim.mjs` plays this extension (the real executor in headless Chrome) for `platform/tests/e2e/test_device_extension.py`.
Pairing: Lumina → Settings → Your browser → Connect gives a code; type it in the extension's popup (or, with the Web Store build, the page hands it over itself: `chrome.runtime.sendMessage(<extension id>, { type: 'pair', code })`, accepted only from `https://getlumina.pro`, and it carries nothing but the code). The extension always connects to production (`src/config.js`); a stored address is honoured only if it is this computer, so no page can point it elsewhere.
An unknown, revoked or replaced device (close codes 4401 / 4403 / 4409) switches the extension off with a red "!" instead of retrying forever.

## Privacy
The store listing's privacy policy is `platform/deploy/vercel/public/privacy.html`. What this extension is allowed to do and keep (`manifest.json` permissions, the storage keys, the servers it reaches, the page-text and control limits) is pinned in `platform/privacy/facts.json`; a change here fails `platform/tests/test_privacy_policy.py` until the policy has been reviewed. See `platform/privacy/README.md`.

## Not done yet (later steps)
- Per-site consent with an expiry.
- Live view (screencast frames into `live.jpg`), download blocking, and denying page permissions (camera, location...).
- Subrequests are filtered by address (`Fetch.requestPaused`); a public-looking name that resolves to a private address (wildcard DNS) is not caught here, and a popup's very first request can race the filter. `declarativeNetRequest` session rules scoped to the session's tabs would close both.
- The tab is shown at 1280x800 (device-metrics override) so pictures and points match the runner; it is letterboxed in a bigger window.
- A restart of Chrome's service worker ends the session (it comes back switched off).
