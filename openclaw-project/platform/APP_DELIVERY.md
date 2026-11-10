# Runnable app delivery

Application output now has a dedicated player, separate from read-only structured answers.
The cell’s shared `AGENTS.md` workspace rules contain delivery guidance for both ordinary turns and native goals: choose an interactive browser app for a small tool; honor explicit source-language requests while offering a usable entry point; preserve project source; report unsupported environments honestly. Native goals keep their exact customer objective. App guidance is not prepended to every user message. `CellProvisioner.write_rules` installs it during the existing cell preparation/start lifecycle. Already running production cells need the updated rules installed before this guidance takes effect; verify a fresh runtime session loads them during rollout.

An assistant can emit a `lumina-app` fenced JSON object:

```json
{"version":1,"title":"Calculator","runtime":"html","code":"<button onclick=\"this.textContent=2+3\">Calculate</button>"}
```

Supported runtime values: `html`, `python`, `javascript`. Maximum source size: 512 KiB UTF-8; title: 1–120 characters. Invalid manifests stay literal code. Ordinary HTML/programming fences remain examples.

Chat and Files also offer **Open app** for nonempty `.html`, `.py`, and `.js` artifacts within the 512 KiB player limit. Larger files retain their download action. Source is fetched through `GET /v1/artifacts/{id}/versions/{version}/app`, which rechecks the signed-in account and the immutable artifact version, bounds the actual storage read, and checks the content hash. Missing, corrupt, oversized and unavailable storage return distinct errors. Downloads retain their ticket authorization. In chat, files appear once at the final assistant message of their request. Inline app deliveries remain visible even if a later summary arrives. Completed intermediate progress messages can fold normally; app replies do not offer unrelated table/chart transformations. Apps start only after Open app; console programs also require Run. Closing/restarting destroys the execution environment; changing the source or immutable file version also creates a fresh environment. Closing returns keyboard focus to Open app.

`GET /v1/apps/player` serves an authenticated, CSP-sandboxed frame. Even direct navigation has no same-origin authority. HTML executes in a second sandbox with inline assets and dynamic JavaScript evaluation allowed inside that isolated document only and no network, forms, popups, downloads or top navigation. Camera, microphone, geolocation, payment, USB and clipboard capabilities are denied. Source never runs in Lumina's document. HTML exceptions and unhandled promise rejections surface as bounded app errors instead of an empty preview. Do not add `allow-same-origin` or API/tool credentials.

Python uses pinned Pyodide 0.27.7 from jsDelivr in a dedicated worker. It downloads on first Run; a network failure is visible and retryable. Python standard library and browser JavaScript are supported. Input is provided as newline-separated lines before Run, then EOF. Output is buffered in the worker and capped at 100,000 characters, execution at 30 seconds after startup, runtime initialization at 90 seconds. Stop terminates the worker, including infinite loops. Events from stopped or older workers cannot overwrite terminal state. A Python runtime download failure is reported separately from a program error. Each run is fresh; state is not persisted.

Browser UI fonts and colors come from Lumina’s existing theme tokens through the parent message; the isolated shell uses system colors as a fallback. No account data or credentials are passed to an app.

This player does **not** host Node servers, databases, native desktop windows, arbitrary compiled languages, or pip/npm projects. Larger projects need a bundled self-contained browser entry point or a separately provisioned isolated hosting service. A source archive or passing tests is not proof of a running full-stack app. There is no generic server runtime/proxy in this change. Keep runnable standalone HTML at the workspace root: the existing file collector excludes build/ and dist/.

## Verification

- `cd openclaw-project/lumina && npm test`
- `cd openclaw-project/lumina && npm run build`
- From the platform with disposable test state and a synthetic session secret: `.venv/bin/python manage.py test accounts.test_apps.AppHTTPChecks --noinput`
- `PYTHONPATH=openclaw-project/platform openclaw-project/platform/.venv/bin/python -m unittest tests.test_gen_document tests.test_native_run`
- After building, start `python3 tests/preview_apps.py` in lumina, then `node tests/apps-browser.mjs`. Uses the production player HTML and exact production CSP. Verifies actual Python/JS execution, HTML controls and isolation, restart/close, desktop/mobile and both motion settings.
- Existing chat regression: `python3 tests/preview_chat.py` then `node tests/chat-activity.mjs`.

Ship backend routes, `accounts/app_player.html`, the lifecycle workspace rules and the frontend bundle together. The app shell adds `frame-src 'self'`; its script policy remains self-only. No production deployment was performed as part of this implementation.
