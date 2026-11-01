# Continuation, 2026-11-01

Written at the end of a long session. Read this first; it supersedes nothing in `CONTINUATION_2026-10-31.md`, it adds to it.

## What is live in production

| Piece | State |
|---|---|
| Backend | Release `20261101T015217Z-6e0a5b3` (both trees). Undo: `python3 openclaw-project/bin/push-release.py --rollback`. Services restarted: tool relay, supervisor-native, platform-app. |
| Model proxy (LiteLLM) | Sonnet 5.5 and Haiku 5.5 only (Sonnet 4.6 and Haiku 4.5 removed). Backup of the old config: `/opt/openclaw-production/config/litellm.yaml.bak-haiku55-20261031T235337Z`. |
| Website | Deployed with `bin/deploy-lumina.py --apply`: "Your own model" card, folded "Show the steps", chat side-room fix. |
| Privacy policy | Live at https://getlumina.pro/privacy (prebuilt Vercel deploy), mentions the own-model recipient. |
| Git | PR #5 merged `product-phases-6-11` into `main` (merge commit `1ac44d4`, feature commit `4f6e39c`). It was merged while CI was still running. |
| Own model switch | `/var/lib/agentai-platform/own-model-keys.json` = `{"own_model_keys": ["f40a5f6b9ab8437cbd0f7459f0ecaa71"]}` (the owner's account only). Customer keys: `/var/lib/agentai-platform/model-keys.json` (encrypted). |

## Open items

1. **Open the own-model feature to everyone** only when the owner says so: set `{"own_model_keys": true}` in the switch file (file must stay owned by `agentai-platform`, mode 640). Kill switch: `false`.
2. **After 03:40 UTC on 2026-11-01:** `python3 openclaw-project/platform/privacy/check_server.py` (expect 3 pre-update database copies left), then delete `server.known_gap` from `platform/privacy/facts.json`. `test_a_known_gap_cannot_outlive_its_deadline` fails on 2026-11-11.
3. **CI on main:** check the "Lumina CI" result for the merge and what `.github/workflows/deploy.yml` ("Deploy to server", triggers after CI on main) did. It was not read closely.
4. **Not yet tested end to end:** a browser task on the owner's own model after the browsing-budget fix. Before the fix, every own-key browser task stopped after about 20 s with "the spending limit was reached (jev)".
5. **Left out of the commit on purpose:** `docs/plan-history/` (4 MB zip) and `output/reports/`. Ask the owner.

### Added 2026-10-31 evening: MCP connections release (open to everyone, no gate; owner's choice)
Done locally, uncommitted: MCP tests green; prompt split in `cell_config.py` fixed; one-use proof claim changed from `unlink` to exclusive-create `<nonce>.claimed` (unlink let two callers both win on macOS), plugin prunes expired markers, new plugin test; UI end-to-end fixture passes at 1440 and 390 px.
6. ~~Four unnamed "Connection · connected" lines~~ Fixed: the old Gmail/Calendar/Drive/GitHub list read the wrong field names, so it printed "connected" for services that were not connected (existing bug, not MCP). Now lists only connected services by name; test in `lumina/src/pages/Integrations.test.tsx`.
7. **Linux check:** confirm the exclusive-create claim on Linux (CI/production); the `unlink` race was only shown on macOS.
8. Commit on a branch and open a PR (leave out `docs/plan-history/`, `output/reports/`); let CI finish before merging.
9. Owner runs on the server: `AGENTAI_PUBLIC_ORIGIN`, `ASANA_MCP_CLIENT_ID`, `ASANA_MCP_CLIENT_SECRET` in `/var/lib/agentai-platform` (not `/etc/agentai-supervisor`); Asana MCP app redirect URI exactly `https://getlumina.pro/v1/account/mcp/callback`.
10. Release: publish `privacy.html` first, push release (`mcp==2.3.0`), `manage.py migrate`, restart web service + tool relay, refresh cells (new origin hook), deploy website; then connect owner's Asana, make one approved call, disconnect.
11. Later: unattended reminders (standing grants + schedules); voice dictation in chat (see the design discussion).

## How the own-model feature works (short)

Settings → "Your own model" saves endpoint, model and key (`accounts/model_key.py`), tests it with one tiny request, stores it encrypted (`agentai_platform/model_keys.py`). At the next cell start `CellProvisioner` (`lifecycle/cell_config.py`, `own_model_reader`) points the assistant at the tool relay's `/byok/v1`, which forwards to the customer's endpoint over a pinned, public-IP-only HTTPS connection. The key never enters the cell. Details and limits: `openclaw-project/platform/deploy/BYOK.md`.

- Tasks on an own key reserve a nominal 1 µUSD and skip Lumina's allowances, but the browser still gets a real reserve (`OWN_KEY_BROWSE_RESERVE`, $1) because JEV is Lumina's cost (`browse/adapter.py`).
- JEV (TypeSafe) never uses the customer's key.
- Changes to a key apply when the assistant next starts.

## Gotchas learned

- The web app and tool relay run as `agentai-platform` and cannot read anything under `/etc/agentai-supervisor` (root-only). Config they need belongs in `/var/lib/agentai-platform`.
- The permission checker blocks writes to production config and the Lumina deploy unless the owner asked for them in so many words; give the owner the exact command (`!` prefix) instead of working around it.
- The privacy detector (`platform/privacy/derive.py`) fails when a new outside host or model recipient appears in code; update `facts.json` and `privacy.html` together, then publish the page (see `platform/privacy/README.md`).
- `push-release.py` ships individual files; it warns about uncommitted changes. Always include the files other services import.
- Do not read customers' message text from the database; the checker blocks it. Timing columns and counts are fine.

## Known problems, not fixed

- **Slow first reply after idle:** about 2 minutes. Cause seen in logs: the assistant's container was asleep. Start about 37 s after queueing, software start +47 s, ready +33 s, then about 40 s of agent set-up (memory over its 1 GB warning level). Also a roughly 50 s gap between one request's result and the next request starting, not explained.
- **Interactive UI with other models:** the assistant must read `lumina-ui/index.json` itself (its `AGENTS.md` says so). Weaker models may skip it or not produce a valid document.
- **Flaky test:** `tests/test_tool_origin.py::test_atomic_consumption_allows_only_one_parallel_caller` fails under full-suite load, passes alone. Possibly a real race.
- **Probing a key blocks one web worker** for up to about 22 s in the worst case.
- **Rotating the app `SECRET_KEY`** without `AGENTAI_MODEL_KEY_FILE` makes stored customer keys unreadable.
- **Offered but never built:** extension speed fixes (drop duplicate screenshot, avoid double settle, stop forcing 1280×800), popup stop reason and recovery after a service-worker restart, "new version available" banner, popup message when the server is unreachable, a clearer label than "Used memory search", a per-account request count for own-key traffic.
- **The Chat "Show the steps" folding** assumes earlier assistant messages of a finished request are the "thinking trail". Confirm with the owner against a real screenshot.

## Added later on 2026-11-01: merged to `main`, NOT deployed (read before your next deploy)
Three PRs are in `main` but not on the server (server `1ff1ef5`, `main` `1e8ed54` or later): #8 browser run waits for the customer at sign-in / password / human check and carries on, #9 `location_request` block, #10 UI answers are not chat bubbles and the component stays locked. The owner asked for them to be deployed by whoever deploys next, not now. Full note, files, pre-deploy cautions and after-deploy checks: `openclaw-project/platform/deploy/PENDING_DEPLOY.md` (also printed in the "Deploy to server" run log). Delete that file once deployed.
