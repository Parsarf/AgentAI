# HANDOFF — Lumina, state as of 2026-11-02

This is the ONLY handoff file. It replaces `docs/codebase-audit/HANDOFF.md`, `CONTINUATION_2026-10-31.md`, `CONTINUATION_2026-11-01.md` and `platform/deploy/PENDING_DEPLOY.md`, which were deleted. Older audit documents in `docs/codebase-audit/` still say "see HANDOFF.md": that means the deleted 2026-10-29 file, whose still-open tasks are carried into section 7 below. Read this top to bottom, then read the spec named in the task before changing anything.

Facts here were checked on 2026-11-01/02 unless marked **(unverified)**. Nothing was read from the production database (customer data); production reads by the agent were limited to service status and logs.

---

## 1. What Lumina is

A customer AI-assistant platform. Customers sign in to a Django web app, chat with an assistant that runs in a per-customer isolated container (a "cell": gVisor `runsc`, its own Docker engine, own LiteLLM key and budget) on the OpenClaw 2026.9.6 runtime. The assistant can browse (JEV + a sandboxed browser, or the customer's own Chrome through the extension), use MCP tools through a tool relay, and render interactive UI blocks in chat.

Repo: `/Users/parsa/AgentAI` (git, GitHub `Parsarf/AgentAI`, main branch `main`). Project folder: `openclaw-project/`.

| Part | Where |
|---|---|
| Core library | `openclaw-project/platform/agentai_platform/` (`chat`, `chat_driver`, `request_queue`, `request_worker`, `budget`, `model_keys`, `mcp_connections/`, `browse/`, `genui/`, `lifecycle/`, `live/`, `panel/`, `ops/`, `privacy`, `ssrf`, `vault`) |
| Django app | `openclaw-project/platform/accounts/` (views, urls, middleware, settings, per-feature modules, `test_*.py`) |
| SQL migrations | `openclaw-project/platform/migrations/` (checksummed; latest on main `0032_chat_surface.sql`) |
| Web app | `openclaw-project/lumina/` (TS/React; `src/pages`, `src/gen` = generative-UI catalog) |
| Browser runner + Chrome extension | `openclaw-project/browse/` (`runner.mjs`, `extension/`) |
| Deploy tooling | `bin/` (`push-release.py`, `deploy-lumina.py`), `platform/deploy/` (docs, Caddy, systemd), `.github/workflows/` (`platform.yml` = "Lumina CI", `deploy.yml` = "Deploy to server") |
| Architecture docs | `openclaw-project/ARCHITECTURE.md`, `platform/ARCHITECTURE.md`, `platform/OPERATIONS.md`, `docs/codebase-audit/` (2026-10-29 audit, partly superseded) |

Code index: the `cbm` MCP server (project `Users-parsa-AgentAI-openclaw-project`). Run `lumina-index status` first, `lumina-index refresh` after any checkout/pull (see `CLAUDE.local.md`).

---

## 2. Production

| Item | Value |
|---|---|
| Server | Hostinger VPS `srv2054170`, `ssh lumina` (alias in `~/.ssh/config`: root @ 179.236.71.203). The old IONOS IP in some docs is dead. |
| Site | https://getlumina.pro (Vercel, builds `main`), backend https://backend.getlumina.pro (Caddy on the VPS → web app on 127.0.0.1:18800) |
| Live release | `main` = `bafc121` deployed as `20261101T094510Z-bafc121` (Actions run 41294439754). Supervisor-tree undo: `ln -sfn /opt/agentai-supervisor/releases/20261101T071915Z-01a2e4a /opt/agentai-supervisor/current && systemctl restart agentai-cel…` (full line is at the end of that run's log). App-tree rollback: `python3 openclaw-project/bin/push-release.py --rollback` or the line printed in the deploy log. **The last two deploys cannot be rolled back by binary alone**: migrations 0031/0032 mean rollback = restore the pre-migration database backup (`binary_rollback_compatible: false`). |
| Web app unit | `agentai-platform-app` (gunicorn, runs as `agentai-platform`, EnvironmentFile `/etc/agentai-platform/accounts.env`) |
| Other units | `agentai-request-worker`, `agentai-lifecycle-worker`, `agentai-cell-bridge`, `agentai-browse`, `agentai-tool-relay`, `agentai-supervisor-native`, `agentai-model-proxy`, `agentai-cells-docker`, `agentai-cells-firewall` |
| Ports (Caddy) | 18800 web app, 18801 live-frame gateway (browse service), 18802 device WebSocket gateway (browse service) |
| Models | LiteLLM serves Sonnet 5.5 and Haiku 5.5 only (config backup `/opt/openclaw-production/config/litellm.yaml.bak-haiku55-20261031T235337Z`) |
| Auto deploy | `AUTO_DEPLOY_ENABLED=false` (repo variable). Merging to `main` does NOT deploy the server. The website on Vercel does rebuild from `main`. |

### What is live
- Browser run waits for the customer at sign-in/password/human check, with "I'm done, continue" in the Live view (#8). Payment pages and consequential buttons still end the run.
- `location_request` chat block (#9). Answers given in a UI box are not chat bubbles; the box stays locked (#10). These two reach an assistant only at its next start.
- User-managed remote MCP connections (#11) — **OFF** until `/var/lib/agentai-platform/mcp-connections.json` exists (`{"mcp_connections": true}` or a list of account ids; see `platform/deploy/MCP_CONNECTIONS.md`).
- Own model (BYOK) — **owner account only** (`/var/lib/agentai-platform/own-model-keys.json`; `true` opens it to everyone, `false` kills it). Details: `platform/deploy/BYOK.md`.
- Side panel in the customer's own Chrome (#13) — **switched ON** (set up 2026-11-01 ~10:00 UTC) for the unpacked extension ID `ombaehmckdiimdjpdlgfbbjehdblfaao`. Verified only at the HTTP edge: `/v1/panel/state` returns `401 ticket` for that origin and `403 origin_not_allowed` for others. **No extension had connected and no real panel session had been seen.**
- Privacy page https://getlumina.pro/privacy lists `/v1/panel` (Vercel production deployment is at `bafc121`).

### Server-side configuration made by hand (not in git)
- `/var/lib/agentai-platform/panel.secret` (65 bytes, mode 0400, owner `agentai-platform`) and in `/etc/agentai-platform/accounts.env`: `AGENTAI_PANEL_SECRET_FILE=/var/lib/agentai-platform/panel.secret`, `AGENTAI_PANEL_ORIGINS=chrome-extension://ombaehmckdiimdjpdlgfbbjehdblfaao`. To roll back: delete the origins line and restart `agentai-platform-app` + `agentai-request-worker` (routes answer 404).
- The store build of the extension will have a different ID; add it (comma-separated) to `AGENTAI_PANEL_ORIGINS`.
- Own-model and MCP switch files (above).

---

## 3. How to deploy (and the guardrails)

1. Merge to `main` through a PR; wait for **Lumina CI** (do not merge while it is running; on 2026-10-31 PR #5 was merged mid-run).
2. GitHub → Actions → **Deploy to server** → Run workflow on `main`. Run with **Dry run ticked first** (builds, migrates a COPY of the database, runs canary probes, stops). Then untick Dry run.
3. If it refuses with exit 30 ("files released by hand are not in this commit"), read the list. If the files are committed on `main` or are test files, rerun with "overwrite manual changes". The supervisor tree currently carries three hand-released test files (`tests/ci_blocking.txt`, `test_automatic_cells.py`, `test_cell_bridge.py`); they are overwritten by deploys and are not runtime code.
4. A real deploy restarts `agentai-cell-bridge`, `agentai-browse`, `agentai-tool-relay`, `agentai-request-worker`; a running browser task is cut off. Deploy when none is running (the owner's tests count).
5. After: `getlumina.pro/app/` answers 200; `/var/lib/agentai-deploy/last` is the new commit; check any feature-specific item.

The agent's permission layer blocks production deploys, production config writes and production database reads unless the owner has asked for exactly that. When blocked, give the owner the exact command with the `!` prefix instead of working around it. Never read customers' message text; timing columns and counts are fine.

`push-release.py` ships individual files and warns about uncommitted changes; always include files other services import. Prefer the Actions deploy.

---

## 4. Gotchas learned (do not relearn)

- `/etc/agentai-platform` is `root:root 0700`: the web app and tool relay (user `agentai-platform`) cannot read files there even if they own them. Any secret/config they read at runtime goes in `/var/lib/agentai-platform`. (`accounts.env` itself is read by systemd as root, so it can live in /etc.) `/etc/agentai-supervisor` is root-only too.
- `agentai-platform-app` is the unit name (not `platform-app`).
- The privacy detector (`platform/privacy/derive.py`) fails when new outside hosts/recipients/endpoints appear in code. Update `privacy/facts.json` and `deploy/vercel/public/privacy.html` together and publish the page (see `platform/privacy/README.md`).
- `platform/privacy/facts.json` has `server.known_gap`; `test_a_known_gap_cannot_outlive_its_deadline` fails on **2026-11-11** unless it is removed. Before removing: run `python3 openclaw-project/platform/privacy/check_server.py` and expect 3 pre-update database copies left.
- macOS `sed -i` needs `sed -i ''`. zsh errors on unquoted globs like `--include=*.py`.
- Chrome refuses an extension folder containing `_`-prefixed names (e.g. `__pycache__`). Load the unzipped `browse/extension/dist/lumina-browser-<version>/` (made by `python3 openclaw-project/browse/extension/package.py`, run from the repo root).
- A git worktree has no `node_modules`; browse tests that need Chrome are skipped there (they report OK with skips). Symlink `openclaw-project/browse/node_modules` before bisecting.
- Rotating the app `SECRET_KEY` without `AGENTAI_MODEL_KEY_FILE` makes stored customer own-model keys unreadable.
- Tasks on an own key reserve a nominal 1 µUSD but the browser still reserves a real $1 (`OWN_KEY_BROWSE_RESERVE`) because JEV is Lumina's cost; JEV never uses the customer's key.
- Do not use `git add -A`: `docs/plan-history/` (4 MB zip), `output/reports/` and `lumina-cost-audit/` (owner browsing logs) are intentionally untracked.

---

## 5. Tests (state on 2026-11-01, `bafc121`)

| Suite | Command | Result |
|---|---|---|
| Lumina | `cd openclaw-project/lumina && npx tsc --noEmit && npx vitest run` | typecheck clean, 432/432 |
| Platform (all) | `cd openclaw-project/platform && . .venv/bin/activate && python -m unittest discover -s tests -t . -p 'test_*.py'` | 1,225/1,226 (+2 skipped). CI runs only the blocking list `tests/ci_blocking.txt`; the rest is report-only. |
| Browse | `cd openclaw-project/browse && node --test --test-timeout=120000 test/` | 92/93 |

Known failures (not caused by the side panel):
- `tests.test_browse.RealRunner.test_a_scripted_jev_drives_the_real_runner_with_element_state_and_the_new_moves` — **stale test**. Broken by `a1592c0` (already live), which lowered `NOTHING_AFTER` from 3 to 2 in `browse/modes.py`, so the assistant is asked for a step the test did not script. Needs real Chrome, so CI never sees it. Fix: script an extra agent step or adjust the fixture/assertions.
- `browse/test/runner.test.mjs` "takeover address bar, back, forward and reload…" — **flaky** (reload step); failed once, passed on rerun; `runner.mjs` unchanged since 2026-10-27.
- `tests/test_tool_origin.py::test_atomic_consumption_allows_only_one_parallel_caller` — flaky under full-suite load, passes alone; possibly a real race.

---

## 6. Repo and branch state

- `main` = `origin/main` = `bafc121`. Every other branch is merged into `main` except `worktree-product-images` (one commit, superseded: card images already exist on `main` as migration 0025; merging would add a duplicate 0023 and conflict in `tests/test_card_images.py`). Keep it as a branch or delete it.
- Stale local branches, all in `main`, safe to delete: `ask-location`, `claude-takeover`, `close-browser-gaps`, `handoff-resume`, `mcp-connections`, `mcp-off`, `pending-deploy-note`, `product-phases-6-11`, `side-panel-chat`, `ui-answer-locked`, `ultrafast-picture-only`, `worktree-emoji-jev` (its remote copy is one commit behind), `worktree-fastclick`, `worktree-live-view`.
- Registered worktrees to prune: `.claude/worktrees/{fastclick,live-view,product-images}` (fastclick/live-view hold only an untracked `browse/node_modules`), and eight under `/private/tmp/claude-501/-Users-parsa-AgentAI/48662896-…/scratchpad/` from an earlier session (`base, gaps, handoff, location, locked, mcp, note, takeover`). That scratchpad also contains a file named `deploykey` and `full.txt` — never opened; remove them.
- On 2026-11-01 the main checkout was switched by another agent to branch `hindsight-memory` (see 7.A). Do not commit or checkout over it.

---

## 7. Open work

### A. Long-term memory ("Hindsight") — another agent's work, unfinished, NOT deployed
Uncommitted in the main checkout on branch `hindsight-memory`: `agentai_platform/longterm_memory.py`, `accounts/longterm.py`, `accounts/management/commands/memory_sweep.py`, migration `0033_longterm_memory.sql`, `lumina/src/components/MemoryNotes.tsx`, tests (`test_longterm.py`, `test_longterm_memory.py`, `live_hindsight.py`), `deploy/LONG_TERM_MEMORY.md`, plus edits to `tool_relay.py`, `tool_origin*`, `settings.py`, `urls.py`, `openapi.json`, `ops/restore.py`, `Info.tsx`, `privacy.html`, `privacy/facts.json`, `privacy/README.md`. Its own privacy entry says "written by Claude Code for the owner to review; not yet published". Needs, before any deploy: owner review; a Hindsight server on the same host/private network (local embeddings + reranker, API key file, `AGENTAI_HINDSIGHT_URL/KEY_FILE/BANK_SECRET_FILE`); privacy page published first; a `memory_sweep` timer; the switch file `long-term-memory.json`. Off for everyone until the owner turns it on. Ask the owner whether to finish it.

### B. Small follow-ups from the 2026-11-01/02 session
1. Fix the stale JEV test and mark/fix the flaky takeover test (section 5).
2. Commit the `platform/deploy/SIDE_PANEL.md` key-path fix (key lives in `/var/lib/agentai-platform/`, not `/etc/`).
3. Try the side panel for real: pair the extension (Lumina → Settings → Your browser → Connect; code into the popup; Turn on), start a task with "use my own browser" on, press "Open chat beside the task". If it shows "Reconnecting", read `journalctl -u agentai-platform-app | grep v1/panel` and the browse service's device lines.
4. Submit extension 0.2.0 to the Chrome Web Store (zip: `openclaw-project/browse/extension/dist/lumina-browser-0.2.0.zip`, sha256 `faf4f03a…953c`; draft answers in `docs/codebase-audit/CHROME_STORE_ANSWERS_2026-10-31.md`; the new `sidePanel` permission may trigger a fresh review). Then add the store ID to `AGENTAI_PANEL_ORIGINS`.
5. Prune the branches/worktrees in section 6.

### C. Speed: "wake up and run tasks takes minutes" (analysed, nothing changed)
Measured trace from 2026-11-01 (one sample): queued → start ≈37 s → software start +47 s → ready +33 s → ≈40 s agent set-up (memory over its 1 GB warning), plus an unexplained ≈50 s gap between one request's result and the next starting. Code causes found:
- `lifecycle/worker_main.py --interval 15` (lifecycle worker polls every 15 s) and `request_worker --interval 3`.
- Cell boot under gVisor + Gateway ready wait (`cell_bridge.ready_timeout=120`).
- `lifecycle/sleep.py IDLE_AFTER_SECONDS = 45*60`; the lifecycle worker's own CLI default `--idle-after 900` should be checked against the unit's actual arguments.
- One running request on the whole server: `request_slot` has a single row (`CHECK(id=1)`); another account's request waits and a handover costs about 60 s.
Plan (ranked): (1) start the cell when chat opens/typing begins, not on Send; (2) make the wake event-driven or cut the polls to ~1 s / ~0.5 s; (3) shrink boot and agent set-up (skills/memory/plugins), possibly a pre-built or snapshotted cell image; (4) add per-step timestamps to find the 50 s gap; (5) relax the single slot. Ship 1–2 behind a switch that can be turned off. Get a slow request's `journalctl -u agentai-lifecycle-worker -u agentai-request-worker` lines first (no message text in them).

### D. Capacity
Admission (`lifecycle/profiles.py`, host 4 vCPU / ~15.6 GiB, reserve 2.5 GiB + 500 m) charges each active tenant 3.5 GiB, 2500 m CPU, 10 GiB disk: CPU is the limit → **1 assistant running at a time**; ~13+ cells can sleep (disk). Measured: an idle cell uses ≈0.46 GiB, light Chromium ≈0.13 GiB; charged amounts are the enforced caps (cell 2 GiB / 1000 m, worker 1.5 GiB / 1500 m). More concurrency needs a load test of two cells, a changed per-tenant charge, and a design for the single `request_slot`; or a bigger host; or multi-host scheduling (does not exist).

### E. Owner-gated items still open from earlier handoffs
- **MCP release steps:** owner sets `AGENTAI_PUBLIC_ORIGIN`, `ASANA_MCP_CLIENT_ID`, `ASANA_MCP_CLIENT_SECRET` in `/var/lib/agentai-platform` (on 2026-11-01 `accounts.env` already had a `ASANA_MCP_CLIENT_SECRET` line — confirm the other two); Asana redirect URI exactly `https://getlumina.pro/v1/account/mcp/callback`; then connect the owner's Asana, make one approved call, disconnect. Confirm the one-use proof claim (exclusive-create `<nonce>.claimed`) on Linux (the `unlink` race was shown only on macOS).
- **Own model:** end-to-end browser task on the owner's own model after the browsing-budget fix is untested (before the fix, every own-key browser task stopped after ~20 s with "spending limit was reached (jev)").
- **Privacy:** `server.known_gap` check (section 4); the general retention job is still unscheduled and account deletion is manual — do not promise automatic deletion.
- **Security/ops (from the 2026-10-29 audit, status unverified):** disable SSH password/root-password login (IS-002); rotate the VPS root password printed in a session on 2026-10-30; automatic off-server backup + restore drill (IS-016, launch blocker); OS updates/reboot window; release/backup cleanup with an approved list; the gunicorn `Control server error: [Errno 13] Permission denied: '/home/agentai-platform'` in the app log (P2-5: `control_socket_disable=True`); tag deployed commits (`release/*`); `/v1/billing/webhook` + `/v1/telegram/webhook` body-cap exemption; billing `--reconcile` timer; `/v1/tasks/<id>/stream` flag-or-delete.
- **Money path (do not start without the owner):** M-01 — cancelling a waiting request / revoked-author path must release the reservation and close the task in one transaction; parked-run expiry must stop the run; repeated unreadable usage snapshot must stop (AG-007). Specs: `docs/codebase-audit/phases/PHASE_1A_RELIABILITY_AND_MONEY.md`.
- **Privacy/security gates:** screenshot egress to TypeSafe (M-02, per-account `picture_privacy`), restore resurrecting forgotten data (BG-008). Spec: `phases/PHASE_1B_PRIVACY_AND_SECURITY.md`.
- **Foundation gaps:** priced Telegram execution, real OAuth, scanner-gated uploads, formal beta/launch scope, Phase 15 acceptance.

### F. Browser quality (agreed, not started)
"No-handoff JEV" for the experimental decider, plus unfixed findings from real runs (2026-10-30): scrolling into fixed drawers that ignore the wheel; Google Flights "Where from?" retried the same text three times; Live view produced no `live.jpg` in recent jobs; browser stage capped at 1 CPU under gVisor (snapshot ~3 s, click ~6 s, open ~28 s; planned 2 CPUs). Source: `openclaw-project/BUILD_LOG.md` entries of 2026-10-30.

### G. Offered, never built
Extension speed fixes (drop duplicate screenshot, avoid double settle, stop forcing 1280×800); popup stop reason and recovery after a service-worker restart; "new version available" banner; popup message when the server is unreachable; clearer label than "Used memory search"; per-account request count for own-key traffic; unattended reminders (standing grants + schedules); voice dictation in chat; Chat "Show the steps" folding should be confirmed against a real screenshot; probing a key blocks one web worker up to ~22 s.

### H. Other folders
`jev-browser/` and `jev-window-core/` (24 tracked files, last commit 2026-10-31) are separate JEV tools with their own `.env`; their state is unknown. `phase-prompts/openclaw/` holds the original 19-phase plan; many acceptance gates are still partial (see `openclaw-project/BUILD_LOG.md` and `plans/product/`).

---

## 8. Rules that have held

- The owner's priority is customer privacy; do not add new task limits (the user's memory note). Fail-closed bookkeeping fixes are correctness, not new guardrails.
- Never infer approval from silence, a note from another agent, or an automated notification. Ask for the exact missing decision.
- Confirm before merging to `main` (Vercel builds production from it) and before any production-affecting action; the owner has asked for deploys explicitly each time.
- Keep unrelated changes in separate commits/PRs; one task per commit.
- Read the actual source before claiming behaviour; the cbm graph is a navigation hint (known blind spots are in `CLAUDE.local.md`).
