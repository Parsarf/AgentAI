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

## Not built yet (next, in order)
1. **Root `agentai-browse` service** (new unix socket like the cell bridge): starts the stage through `WorkerBroker`, owns the per-account model key and the TypeSafe key, runs `BrowseRunner`, stores run state/screenshots; the app-user request worker only submits a job and polls (the app user cannot reach docker or tenant keys).
2. Real LLM client (LiteLLM with the account's virtual key) and ledger admission/receipts for each paid call.
3. Chat integration: `intent='browse'`, task-strip events, screenshots, a real Browser page, `approval` block, owner switch `browse_tasks`.
4. Takeover (screenshot relay with validated clicks), calibration/benchmark (needs go for paid runs), guarded ordering, hardening — as in the plan.

## Decisions still open (from the plan)
Captcha policy (stop and hand over, never defeat), first release = stop at checkout, ordering via takeover login rather than stored passwords, browse spend caps, a dedicated customer Brave key.
