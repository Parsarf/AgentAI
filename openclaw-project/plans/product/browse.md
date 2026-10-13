# Browser agent (search → browse → guarded ordering): status

Plan: see the approved plan "Lumina browsing and ordering" (phases P0–P7). **Status 2026-10-13: P0–P2 core built and verified; nothing is connected to customers yet.**

## Built (all offline-tested; runner also verified in the real server stage)
| Piece | Where | Notes |
|---|---|---|
| Runner ("hands") | `browse/runner.mjs`, pinned `playwright-core@1.49.1` (Node 18 compatible, installed with `--ignore-scripts`) | JSON-lines protocol: `open`, `snapshot`, `act` (click/type/select/press/scroll/back), `screenshot`. Public http/https only (private ranges, loopback, `file:`, credentials in URLs refused; every sub-request checked), downloads off, ≤3 tabs, 500-char values, only Enter/Tab/Escape keys, exact **stale check** (an element that moved, was renamed or re-rendered is not clicked) |
| Mock shop + tests | `browse/fixtures/site.mjs`, `browse/test/runner.test.mjs` (6 tests, real Chrome) | includes a page with hidden "ignore all rules" text, a popup, checkout |
| Candidates | `platform/agentai_platform/browse/candidates.py` | same line format and sensitive-control rule as `browser-opt/jev_adapter.py`; payment-page detector |
| Decider ladder | `browse/ladder.py` | JEV chooses among ≤20 candidates (strict response validation), Haiku supplies typed values and handles abstentions, Sonnet only after failures or a loop (capped); every answer validated by code; every paid call goes through `admit` |
| Loop + policy | `browse/loop.py` | observe → decide → policy → act → record; **read-only policy stops before any sensitive control or payment step** ("handoff"); deny-listed domains; step/time limits; loop detection; budget refusal stops the run |
| Session client | `browse/session.py` | JSON lines over a process (local Node now, `docker exec` into the stage later) with deadlines |
| Tests | `platform/tests/test_browse.py` (12 incl. a real-Chrome run against the mock shop: add to cart, then handoff at Checkout, never reaching Place order) | |
| Stage check | server, 2026-10-13 | the runner runs in the existing `openclaw-sandbox-browser:phase4-2026.9.6` stage under gVisor (read-only root, no caps, 1.5 GiB, bind-mounted ro, no new image needed): opened example.com, produced a host-format snapshot and a screenshot, refused `http://10.0.0.5/`. One real bug found and fixed there (EOF closed the browser before queued work finished) |

## Built and live on the server (2026-10-13, switch `browse_tasks` OFF)
| Piece | Where | Notes |
|---|---|---|
| Browse service | `agentai_platform/browse/service.py`, `service_main.py`, unit `deploy/agentai-browse.service` | root service on `/run/agentai-browse/browse.sock` (peer-uid checked, group `agentai-platform`); one stage at a time; per-account model key from custody; JEV key at `/var/lib/agentai-supervisor-secrets/_shared/typesafe-key`; JEV runs in **shadow** (asked beside the real decision, agreement recorded); runner bundle read-only at `/opt/agentai-browse/runner`; jobs in `/var/lib/agentai-browse/jobs` |
| Request path | `chat.py` `_execute_browse`, `request_queue.py`, `lifecycle/worker.py` | mode `browse` / auto-detected interactive goals (only when the switch is on); no cell wake; steps mirrored to `browse_runs`/`browse_steps` (migration 0019) and the task timeline; usage reconciled from key spend; stop = cancel |
| Endpoints | `accounts/browse.py` | `GET /v1/browse`, `GET /v1/browse/{id}?since=`, `GET …/shot/{file}`, `POST …/control` (click/type/key/scroll, only after a hand-off, 10-minute window), `POST …/release` |
| UI | `lumina/src/pages/Browser.tsx` | live steps + screenshot, click-to-act takeover mapped to 1280×800, "Watch live" on the task strip, "Browse" mode chip when enabled |
| Switch | `switches.py` `browse_tasks` (needs fact `browse_ready`, confirmation `browse_cost`) | `browse_ready` fact is set on the server |

Live check (real stage, public read-only site `books.toscrape.com`): direct service call and a full chat request both returned the correct cheapest book (£13.99) in about 15 seconds; estimated model cost 0.28 cents per task. Bug found by the live run: the chat driver probed the assistant cell's gateway even for browser tasks (the cell is stopped) and failed; fixed. Not yet done: a run that reaches a payment hand-off on a real site, and real takeover clicks (covered by tests and mock shop only).

## Not built yet (next, in order)
1. Calibration/benchmark (P5): Haiku-only vs JEV→Haiku→Sonnet vs Claude-first on identical fixtures (needs the owner's go; tens of dollars). JEV is in shadow only until then.
2. Guarded ordering (P6) behind the locked `credentialed_browsing` switch: takeover-login profile, approval cards, hard spend limit, real purchases only in the owner's test account.
3. Hardening (P7): prompt-injection corpus, log redaction, capacity test, monitor checks.

## Decisions still open (from the plan)
Captcha policy (stop and hand over, never defeat), first release = stop at checkout, ordering via takeover login rather than stored passwords, browse spend caps, a dedicated customer Brave key.
