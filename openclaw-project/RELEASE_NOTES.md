# Safety menu: two scopes, granted access, 16 wired switches, terminal console (27 Oct 2026, deployed as `safety1`)

Read `platform/OPERATIONS.md` ("Safety menu") and `lumina/src/components/safety/README.md`.

- **Deployed 27 Oct 2026 (06:44 UTC) as `safety1`:** platform tree through `deploy/release.py` (dry run first: build, migrated copy, canary all passed; the previous release cannot read the new schema, so rollback of the app needs the backup), supervisor tree built from the same package, frontend through `bin/deploy-lumina.py --apply` (this shipped the uncommitted redesign in the working tree too), all seven services restarted, no warnings in any journal, probes 200/200/200/401/401/405.
  Host changes: `AGENTAI_SAFETY_OWNER_ACCOUNT` added to `/etc/agentai-platform/accounts.env`; `"safety_file"` added to `/etc/agentai-supervisor/native-wiring.json`. The snapshot file appears the first time the owner opens the menu.
  **Rollback:** frontend `cd /var/lib/agentai-platform && mv ui ui.bad && mv ui.prev ui`. Supervisor: `ln -sfn releases/native4 /opt/agentai-supervisor/current`, restore `/etc/agentai-supervisor/native-wiring.json.bak-safety1` (the old code rejects the new key), restart the supervisor services. App: stop `agentai-platform-app` and `agentai-request-worker`, restore `/var/lib/agentai-platform/backup-20261027T064400Z-premigrate-safety1.sqlite3` over `platform.sqlite3` (delete its `-wal`/`-shm`), `ln -sfn releases/native4 /opt/agentai-platform/current`, start them (this loses what happened after 06:44 UTC). Env: `/etc/agentai-platform/accounts.env.bak-safety1`.
- **New:** a tab bar at the top of the menu: "My account" and "All users" (owner only). "All users" sets the default for every account; an account's own setting wins, and an account can exempt itself from an "off for everyone".
- **New:** the owner can grant other accounts the menu by email ("Who can open this menu"). A granted account sees only its own switches. Revoking also clears the switches it set.
- **New:** switches are now `gate` (changeable), `shared` (server-wide) or `core`; the privacy ones cannot be switched off for everyone. The menu shows the locked ones disabled, with the reason.
- **Changed:** "off for everyone" for `rate_limits` reaches account-keyed limits only; sign-in, sign-up, recovery, token and anonymous limits and the menu's own stay on.
- **Needs a migration:** `0014_safety_overrides` and `0015_safety_access` (use `deploy/release.py`, or run `manage.py migrate`). `safety_overrides` and `safety_access` are never restored from a backup.
- **Wired:** 16 switches are now read by code (`budget_caps`, `rate_limits`, `queue_limit`, `project_chat_limits`, `upload_limits`, `secret_redaction`, `vault_notice`, `payment_stop`, `sensitive_approval`, `denied_sites`, `untrusted_page_text`, `personal_data_scrub`, `assistant_output_cleaning`, `ssrf_guard`, `tool_ceilings`, `screenshot_retention`); a test fails if a switch says wired and nothing reads it. See OPERATIONS.md for where.
- **Not wired, on purpose:** `routing_policy`, `confirmations` and `web_limits` describe protections that are not in the live code (they say so). `message_length_limit` and `cell_limits` can't be a per-account switch (a database constraint; a whole-host protection) and are now `shared`; `session_epochs` and `block_validation` are now `core`.
- **New switches:** `screenshot_retention` (privacy; wired) and three server-wide ones shown read-only: `bridge_restrictions`, `cell_key_limits`, `cell_firewall`.
- **How the browse service and supervisor see the switches:** the app writes `safety-switches.json` after every change (see OPERATIONS.md). Deploy: add `"safety_file": "/var/lib/agentai-platform/safety-switches.json"` to `native-wiring.json` (the browse service's default already points there).

# Browser: JEV, then the assistant; the cell's own browser as the hands (26 Oct 2026, deployed 26-27 Oct as `native1`..`native4`; the relay-secret fix is in `native4`)

Read `docs/architecture/native-execution.md` ("The browser: hands and brain") and `platform/OPERATIONS.md` ("Browser engine").

- **Removed:** the Haiku and Sonnet tiers of the browse ladder, the browse service's model client (`browse/llm.py`) and its start-page guess, shadow mode. The browse service calls one model: JEV.
- **New:** when JEV cannot take a step (too complex, two misses, a loop, no JEV) the job hands the page, its numbered controls and a picture of the window to the customer's own assistant, which
  answers with the new tool `lumina_browser_step`; for one-off needs (text for a field, confirming "done", an open choice) it hands over a single step. Every step still passes the code rules.
  `lumina_browser` now requires `site`.
- **New, off until switched on:** the `native` browser engine: a job's hands are the cell's own OpenClaw browser, reached through the cell bridge's new admin-scoped connection (root callers only;
  fixed routes; the cell's own profile; named page scripts). Cell config switch `native_browser`; per-account `browse-engine.json`. Cells with a live browser job or an open hand-off window are not
  slept. The host Docker stage stays the default and stays in the tree until the native engine is measured on real cells and models.
- **Fixed after the first canary (27 Oct 2026):** the cell's browser could not start because the sandbox rejects the plugin's atomic write of its extension relay secret. The host now writes that secret before every start (`ensure_browser_relay_secret`), the image's Chromium path is pinned in the cell config, and a failed browser command leaves its error code in the job trace (`detail`).
- **To deploy (nothing changes for customers until the last step):** release both trees; restart bridge, browse service, tool relay, request worker, app; later `native_browser` and
  `browse-engine.json` for a canary account. `--jev-mode` is now `off` or `live` (default `live`; `shadow` is retired and runs as `live`). Not verified: the real cell image/gVisor, memory, real models.

# Native execution (26 Oct 2026, not yet deployed)

OpenClaw now owns each customer run end to end; Lumina admits, supervises and settles it. Read `docs/architecture/native-execution.md`.

- **Removed:** the `lumina-step` text protocol, JEV tool choice and search nudges, the round loop, transcript polling, Pursuit (and its switch and report), the browser's progress review,
  the unused `HttpGateway`, the `jev_services` switch. Migration `0028` drops `pursuit_state` and rebuilds `chat_deliveries`.
- **New:** steering (a message sent while a task runs joins that run), Stop confirmed by the runtime, "Keep working until complete" on the runtime's own goals, honest outcomes
  (completed / partial / blocked / failed / cancelled, plus verified / unverified), requests that wait for a person give up the running slot, recovery after a cell restart with one run and
  one charge, the browser as a native tool (`agentai-tool-relay`, port 4100).
- **Fixed on the way:** the runtime's seeded `SOUL.md`/`BOOTSTRAP.md`/`IDENTITY.md`/`USER.md` were offered to customers as downloads; a stopped cell is now woken for Browse mode.
- **To deploy:** install `agentai-tool-relay.service`, set `tool_relay_port` in `native-wiring.json`, run `cells-docker/agentai-cells-routes.sh`, restart the lifecycle and request workers,
  then restart cells (they take the new config at their next start). Not yet verified: a real model, real cells, real Chromium.

# Release notes: 13-14 October 2026

Latest: **live8** (16 Oct, adds diagnostics and one retry to live7). Before it: **live7** (16 Oct, JEV-first browser agent, JEV mode **live**), **live6** (14 Oct, evening). Sections marked *(live5)* and *(live6)* below are newer than the live1-live4 table.

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
| live7 | `f435324` | JEV decides each browser step (one call: what to do, which element, which option, which text); sign-in pages and password fields go to the user before any model; hand-off ladder JEV -> Haiku -> Sonnet; per-run counts. Browser service and request worker only (`/opt/agentai-supervisor/current`); runner updated. Browse service runs `--jev-mode live` |
| live8 | `02877e4` | Browse service logs why JEV missed (error and HTTP status, or confidence per question) and why a model reply failed (length, finish reason), without page text; a reply with no JSON is asked for once more. Same backend scope as live7. **Running release.** Read the journal: `journalctl -u agentai-browse \| grep 'browse:'` |
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
- live7 (16 Oct 2026): `/opt/agentai-browse/runner/runner.mjs` replaced (previous copy `runner.mjs.bak-live7`); `/etc/systemd/system/agentai-browse.service.d/jev.conf` sets `--jev-mode live` (delete it for the old `shadow` default); `/opt/agentai-supervisor/current` -> `releases/live7` (then `live8` the same day). The new six-question JEV request format was NOT test-called before the switch (the check was blocked); if TypeSafe rejects it every step counts as a JEV miss and Haiku/Sonnet decide as before. Read `stats` in the closing `status` row of `browse_steps` to see who decided the steps.

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

---

## live18, deployed 21 Oct 2026 00:56 UTC: pursuit (plans, supervision, verification, resume)

Deployed as one release, `live18`, from the working tree on the owner's Mac (branch `product-phases-6-11`; **not committed or tagged**, like live9 to live17). The web app went out through `deploy/release.py`
(canary on a database copy, backup, migration `0026_pursuit.sql`, switch, probes: all passed); the request worker and the browse service were restarted afterwards (`/opt/agentai-platform/current` and
`/opt/agentai-supervisor/current` both point at `releases/live18`). The browser runner and the Lumina UI were already current and were not redeployed. The `pursuit` owner switch is **off**.
See `plans/pursuit-architecture.md` for the design and `plans/pursuit-validation.md` for how it is checked.

**What it adds, behind the owner switch `pursuit` (off by default):**
- The assistant's plan is stored with success criteria; a task that needs several websites can run several browser sessions in one message.
- A progress review of each browser run (rules first, one JEV question when they cannot decide) that can change approach or ask for a new plan.
- A result counts as done only when it is checked against the plan's criteria; every ending is described as `Checked`, `Done, but I couldn't confirm`, or `Stopped`.
- Retry carries on from what was already done. `python -m agentai_platform.ops.pursuit_report --db <app db>` reports verified completion and cost per verified success.

**Rollback:** the previous release cannot read the new schema, so rolling back the web app means restoring `/var/lib/agentai-platform/backup-20261021T005635Z-premigrate-live18.sqlite3` over `platform.sqlite3`
(stop `agentai-platform-app` and `agentai-request-worker`, delete `platform.sqlite3-wal`/`-shm`, point `/opt/agentai-platform/current` at `releases/live16`, start both), which loses what customers did after the release.
The browse service alone rolls back by pointing `/opt/agentai-supervisor/current` at `releases/live17` and restarting `agentai-browse`. Turning the `pursuit` switch off needs no rollback.
**Before turning the switch on:** run `plans/pursuit-smoke-test.md` and the model probe, on the owner's own account first.

**(Original release plan, kept for reference)** Needs: migration `0026_pursuit.sql` on the web app's database before the new code runs; both the web app and the browse service/worker updated together; then turn the switch on for the owner's own account first.
**Also fixed (applies with the switch off):** a plain follow-up question no longer re-runs the previous turn's browser step.

---

## live19, deployed 21 Oct 2026: product and place pictures

Pictures reach the chat only on a comparison card (the page behind each option's `link` supplies the picture). In production only a handful of cards had ever been made, so almost nothing showed a picture. live19 tells
the assistant to show any 2 to 6 products, places or similar things as a comparison card, however it found them (its search, pages it read, or a browser result), with a real link per option taken from its results
(never a search-results page, never an invented address). Changed files: `agentai_platform/agent_protocol.py` (sent with every message, effective at once) and `agentai_platform/lifecycle/cell_config.py` (the assistant's rules
file, rewritten each time the assistant starts). No migration. Web app through `deploy/release.py` (canary and probes passed; the previous release can still read the database, so a rollback is only the link switch);
request worker, lifecycle worker and supervisor restarted; the browse service was left running. Deployed from the working tree (not committed or tagged).
Rollback: point `/opt/agentai-platform/current` and `/opt/agentai-supervisor/current` back at `releases/live18` and restart `agentai-platform-app agentai-request-worker agentai-lifecycle-worker agentai-supervisor-native`.
Not changed: sites that block automated fetches (for example Yelp) still give no picture; an image-search fallback needs a Brave image key (`AGENTAI_BRAVE_IMAGE_KEY_FILE`).

---

## live20, deployed 21 Oct 2026: interactive follow-ups on cards

Replaces the hard-coded "Find the cheapest reliable place to order this" button with follow-ups the assistant writes per card and per option (details in `platform/CHAT.md`). Changed: `genui/data.py` (accepts and cleans `actions`),
`lumina/` (new `FollowUps` component, schema, styles, tests), `cell_config.py` (rules), `agent_protocol.py` (per-message instructions). No migration. Deploy order: the UI first, then the web app, worker and lifecycle services
(done in that order: all probes passed; the previous release can still read the database). Rollback is `ui.prev` for the UI and the `live19` links for the code. Deployed from the working tree (not committed or tagged).

---

## live21, deployed 21 Oct 2026 02:02 UTC: answers laid out for what they are

New cards (places, products, steps, answer, choice, callout, timeline, sources), a presentation guide for the assistant, the fixed "Show as table / chart / compare" chips removed, and a JEV layout fallback for
plain-text replies behind the owner switch `jev_display` (off). Details in `platform/CHAT.md`. **Migration `0027_more_cards.sql`** (data_blocks rebuilt to accept the new kinds; existing cards copied unchanged): after the
release the previous code cannot read the database, so rolling the web app back means restoring the pre-migration backup. Deployed in that order (UI, web app with migration, worker, lifecycle services); all probes passed and the 11 existing cards were kept. Pre-migration backup: `/var/lib/agentai-platform/backup-20261021T020249Z-premigrate-live21.sqlite3`. `jev_display` is off. Deployed from the working tree (not committed or tagged).

---

## live22 (UI only), deployed 21 Oct 2026: a card no longer shows twice

The chat cached a reply while it arrived and never re-read it, so after the server moved the card's data out of the reply (into a stored card) the stale text drew the card a second
time, and a closing line added afterwards stayed hidden until a reload. Now the chat re-reads a task's messages once when the task finishes (`lumina/src/lib/conversations.ts`
`refreshFinished`), and a reply whose card is stored never draws it again from its own text (`AgentResponse` `cardsStored`). No restart, no database change. Undo: `mv ui ui.bad && mv ui.prev ui`.

---

## live23, deployed 21 Oct 2026: places and products shown once, in their card

The assistant sometimes listed the same places or products as bullets above their card, so they showed twice (once without pictures). When a reply stores a places, products or comparison
card, bullet lines naming two or more of its items are now removed from the text (`genui/data.py` `trim_repeats`; intro and closing sentences kept, a single mention never touched), and the
assistant is told to write one or two sentences above such a card instead. No migration, UI unchanged; all probes passed. Rollback: point both `current` links back at `releases/live21`.
Answers given before this release keep their text. Deployed from the working tree (not committed or tagged).


---

## live24 (browse only), deployed 21 Oct 2026 05:38 UTC: Sonnet backup works again, cart panels get listed

Every Sonnet call from the browser failed with HTTP 400 (`claude-sonnet-5-5` accepts no `temperature` but its default), so a run that needed the backup tier stopped with "the assistant gave
no usable next step". Sonnet is now sent no temperature (`browse/llm.py` `TEMPERATURE`; Haiku keeps 0), and a 400 turns pictures off only when the same question without the picture succeeds.
Only the first 20 controls in page order were listed, so a panel added at the end of the page (a cart drawer, a dialog) never made the list and the run clicked covered controls until it stopped;
now on-screen controls with nothing on top take the place of covered ones, page order kept (`browse/candidates.py` `_within`). `releases/live24` is `live23` with these two files; only
`/opt/agentai-supervisor/current` was switched and only `agentai-browse` restarted (`/opt/agentai-platform/current` stays on `live23`). Rollback: point `/opt/agentai-supervisor/current` back at
`releases/live23` and restart `agentai-browse`. Deployed from the working tree (not committed or tagged).
