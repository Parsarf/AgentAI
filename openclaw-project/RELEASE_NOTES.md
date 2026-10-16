# Release notes: 13-14 October 2026

Latest: **live7** (16 Oct, JEV-first browser agent, JEV mode **live**). Before it: **live6** (14 Oct, evening). Sections marked *(live5)* and *(live6)* below are newer than the live1-live4 table.

Everything below is **live** (verified: the server's 260 backend files and the live site's 4,509 frontend files are byte-identical to the committed code).
GitHub suspended the owner's account on 14 Oct 2026 (after 00:51), so none of this has reached GitHub; see "Where the code is kept".

## What changed

### Chat layout and scrolling
- **Composer stays put.** The chat pane is exactly one screen tall, so the message box sits at the same place whether you scroll, the chat is short or long, or the
  box grows with several lines of text. It never covers the last message. (Earlier the page was 80 px too tall, which made the box drift.)
- **Home alignment.** Greeting, composer, feature cards and Recent Tasks share the same left and right edges; the column is centred between the sidebar and the
  Activity panel. The composer's buttons wrap deliberately on narrow screens. A long task title no longer makes Home scroll sideways on phones.
- **Smoother scrolling.** Measured on a real GPU: GPU load while scrolling fell 28% to 5%, idle GPU 30% to 8%. Causes fixed: the planet drew 60 times a second behind
  everything (now 15, paused while you scroll or type, and off when hidden); blur effects behind panels were recomputed every frame (removed; panels have a denser tint);
  every chat refresh re-parsed every message (now only new text is processed); far-away messages skip layout and painting until you near them.

### Look and feel
- **Thinking orbs** (the MIT `thinking-orbs` library, vendored in `lumina/src/vendor/thinking-orbs`): a calm dotted ring on an empty chat; while Lumina works, an orb
  and a short label showing what it is doing (Searching, Browsing, Writing, Analysing, Planning, Running a command, Waiting for your approval...). All orbs and the planet
  run from one shared 15 fps clock. **Reduce motion** (top-right wave icon) freezes them; it starts from the system setting and is the one switch for both.
- **The "Working" task card in chat is gone.** A pending reply is the orb plus its label on the assistant's side; Stop and Activity are in the chat header.
- **The planet no longer shows on an open conversation** (it still shows on Home and other pages).
- **OpenMoji emoji.** Emoji in replies, in your own messages and in table and comparison cards are drawn as OpenMoji pictures (4,495 unmodified SVGs in
  `lumina/public/openmoji`, CC BY-SA 4.0, credited in Settings > Credits, `lumina/CREDITS.md` and `OPENMOJI-LICENSE.txt`). Code stays literal; 22 emoji on a page cost
  5 requests. Helpers: `emojiToFile`, `emojiUrl`, `searchEmoji` in `lumina/src/lib/openmoji.ts`.
- **JSON blocks become real cards.** A chart, table or comparison written as JSON in a reply now shows as a card, not raw text. The reported spicy-food table failed because
  the frontend required a column `type` that the server treats as optional; the frontend now uses the server's defaults.

### Live view (replaces the Browser page)
- One page to watch what Lumina is doing: **Screen** (a live picture of its browser), **Terminal** and **Files** (from its tool activity), plus the activity list.
  **Take control** lets you click, type and scroll in its browser; **Return to browser** hands it back. Typed text is masked by default and sent in order. An abandoned
  take-over hands the browser back by itself after 10 minutes; time you hold the wheel does not count against the task's limit. `/browser` links redirect here.
- Built to stay light: frames come from a small server inside the browse service (own threads, never the web app's single worker), only while someone watches, newest frame only,
  hidden tabs stop it. Watch tickets are signed, expire in 2 minutes, view-only and bound to one account and task. Frames travel on `/v1/live/<task>/frame`.

### Browser agent and smarter routing
- **Browser agent hardened.** Production showed three "order the spiciest food" runs failing: two never started (a 2,000-character limit rejected requests carrying chat
  history) and one gave up because the quoted history was mixed into its instructions. Now the current request is kept separate from history, the limit is 48,000
  characters, there is no silent fallback to Bing, failures say why, and URL checks are stricter.
- **JEV picks the service ("Smart services" switch, now ON).** For web-related messages JEV (TypeSafe) chooses browser, web search, or neither; the chosen service runs first and
  its output goes to the assistant, which writes the reply. Details: a local check keeps JEV off messages that cannot need the web (coding, writing, chat); JEV sees only scrubbed
  text (1,500 characters + 500 of the previous message); a slow or unsure JEV falls back to keyword rules and never fails a request; the browser may use at most 60% of the task's
  money and stops before any payment; Text mode is never routed; messages that clearly act on a named site still go straight to the browser. The wording of the question was
  measured against the live JEV: "search for the spiciest food around me" went from 59% web to 100% browser. JEV adds about 6 s to web-related messages.
- Every routed turn tells the assistant not to use its built-in browser tool (it fails inside the customer cell with `rename without replacement: Invalid argument`; not fixed, routed around).

### Faster Live view and sites that block browsers *(live5, live6)*
- **Thinking label** hangs lower-left of the orb on a small curved branch (frontend only).
- **Clicks in Live view are immediate.** Before, every click you made while driving waited for the page to finish loading (up to about 8 seconds) before the next
  input was accepted, and each click also triggered a screenshot. Now input returns the moment it is delivered, the pointer moves to the spot before it clicks, and a
  ring appears under your cursor straight away. The saved snapshot (used only when live frames are unavailable) is taken at most every 4 seconds.
- **A steadier, sharper picture.** 15 frames per second (was 8) at full size 1280x800 (was 960x600), and watching is noticed in a quarter of a second (was one second).
  A frame that arrived too soon used to be discarded, which could freeze the picture on an old state (a spinner, a ticked box); it is now held and shown.
- **Sites that ask "verify you are human"** (for example DoorDash): the browser waits a few seconds in case the check clears, then stops without guessing, and the
  assistant takes over: it finds and ranks options from other sources, gives links, and tells you to finish the order on the site yourself. Nothing is claimed as
  ordered. Lumina does not try to disguise its browser to get past such checks. Payment steps still end with you finishing them.
- Failed model replies in the browser agent now say why ("the assistant gave no usable next step (...)") instead of "no valid decision (ValueError)".

### Security and quality
- SonarQube cleanups; **CSRF is now enforced on file upload and download-ticket POSTs** (Lumina already sends the token).
- A test that failed on busy machines (and blocked deploys) now waits longer.

### Owner tools
- **Owner Console** (`bin/owner-console.py`): one private launcher with a button for each owner view and a clipboard-only dashboard password.
- **Owner dashboard redesign** (Overview, Customers, Features, light/dark, phone layout).
- **Dashboard can save switches again.** It was sandboxed read-only for the switches folder, so every save failed with "could not save (OSError)". Fixed on the server (below) and in `bin/update-ops-dashboard.py`.

## Releases and the exact code behind each (git tags `release/*`)
| Release | Commit | Contents |
|---|---|---|
| live1 | `5d8664b` | Live view (backend, browser runner, proxy route, frontend) |
| live2 | `3b2fdbb` | Browser hardening, Live view polish, inline JSON cards |
| live3 | `7dcc3fe` | OpenMoji emoji, JSON-card defaults fix, JEV service routing |
| live4 | `d67d15e` | Sharper JEV service wording |
| live5 | `84d7ec6` | Verification-wall handoff in the browser agent; thinking-label branch (frontend `acfd9f8`) |
| live6 | `f8658ee` | Instant takeover clicks, faster frames, verification-wall handover to the assistant |
| live7 | `f435324` | JEV decides each browser step (one call: what to do, which element, which option, which text); sign-in pages and password fields go to the user before any model; hand-off ladder JEV -> Haiku -> Sonnet; per-run counts. Browser service and request worker only (`/opt/agentai-supervisor/current`); runner updated. **Running release.** Browse service runs `--jev-mode live` |
Up to live4 the web app and browser service ran the same code. live5 and live6 changed only the browser service and request worker (`/opt/agentai-supervisor/current`);
the web app (`/opt/agentai-platform/current`) is still on live4, which is fine because nothing it runs changed. Release tags: `release/live5` (frontend), `release/live5-browse`, `release/live6`. Frontend files live in `/var/lib/agentai-platform/ui`.

## Changes made by hand on the server (not in git)
- `/etc/agentai-platform/live.secret` (root:agentai-platform, 0640): the live-view ticket secret. `AGENTAI_LIVE_SECRET_FILE` added to `/etc/agentai-platform/accounts.env` (backup `accounts.env.bak-live1`).
- `/etc/caddy/Caddyfile`: new `@liveframe` rule before the general `/v1` rule (backup `Caddyfile.bak-live1`; same text as `platform/deploy/caddy/Caddyfile.getlumina`).
- `/opt/agentai-browse/runner/runner.mjs` updated for live frames (backup `runner.mjs.bak-live1`).
- `/etc/systemd/system/openclaw-dashboard.service.d/feature-switches.conf`: lets the dashboard write `/opt/openclaw-production/feature-switches` only.
- Owner switch `jev_services` turned ON with both confirmations recorded as given by the owner in chat on 2026-10-14 (`switches.json.bak-*` in the same folder).
- `/opt/agentai-browse/runner/runner.mjs` replaced again for live6 (previous copy: `runner.mjs.bak-live5`; the one before: `runner.mjs.bak-live1`).
- Dashboard files refreshed (backup `/opt/openclaw-production/dashboard.bak-20261014T081251Z`).
- live7 (16 Oct 2026): `/opt/agentai-browse/runner/runner.mjs` replaced (previous copy `runner.mjs.bak-live7`); `/etc/systemd/system/agentai-browse.service.d/jev.conf` sets `--jev-mode live` (delete it for the old `shadow` default); `/opt/agentai-supervisor/current` -> `releases/live7`. The new six-question JEV request format was NOT test-called before the switch (the check was blocked); if TypeSafe rejects it every step counts as a JEV miss and Haiku/Sonnet decide as before. Read `stats` in the closing `status` row of `browse_steps` to see who decided the steps.

## How to roll back
- **Web app + request worker:** point `/opt/agentai-platform/current` at the previous release (`releases/live3` etc.) and `systemctl restart agentai-platform-app agentai-request-worker`.
  Database backups from before each release: `/var/lib/agentai-platform/backup-*-premigrate-liveN.sqlite3` (the old release can still read the new schema).
- **Browser service and request worker:** point `/opt/agentai-supervisor/current` at the previous release (`releases/live6`, then `live5`, `live4`) and `systemctl restart agentai-browse agentai-request-worker`. Also restore `runner.mjs.bak-live5` over `runner.mjs`.
- **Frontend:** `mv /var/lib/agentai-platform/ui.prev /var/lib/agentai-platform/ui` (one step back only).
- **Smart services:** switch it off in the owner dashboard (Feature switches).
- **Live view only:** remove `AGENTAI_LIVE_SECRET_FILE` from `accounts.env` and restart the app; the page falls back to snapshots.

## Where the code is kept (GitHub is suspended)
- The repository on the owner's Mac (`/Users/parsa/AgentAI`), branch `product-phases-6-11`, with the release tags above.
- Verified full backups (a copy of each also sits in `/root/` on the server, root-only): `/Users/parsa/AgentAI-backups/*.bundle` (restore with `git clone <file>.bundle <folder>`) (copy one off this Mac too).
- Not yet on GitHub: every commit since `d21e6b5` (13 Oct). When the account is restored: `gh auth login`, then `git push --all && git push --tags`.

## Known limits and open items
- GitHub account suspended; appeal at support.github.com.
- Hop-in works on browser tasks only; coding tasks get the Terminal and Files views about 1.5 s behind their activity.
- Sites that block automated browsers (DoorDash and similar) cannot be ordered from by Lumina; it ranks options and you order on the site.
- The web app release is behind the browser service by design (see releases table).
- Two stale `queued` rows from earlier failed browser runs remain in `browse_runs` (harmless).
- `accounts.test_streams` and `tests.test_chat_history` fail on a clean checkout (older issues, unrelated to the above).
