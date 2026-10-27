# Plan: OpenClaw's native browser as the hands, JEV and the assistant as the brain

## Status (26 Oct 2026): built; rollout gated

Built and tested: bridge (admin connection, `browser.*`, fixed routes, named scripts, root-only), cell config, `NativeRunner` / `NativeTransport`, Live view frames, the assistant hand-over
(`lumina_browser_step`), removal of Haiku/Sonnet, sleep rule, per-account engine switch, docs. Real-browser tests: `platform/tests/e2e/test_native_browser.py`. Not done, by design: switching any
account to the native engine, deleting `runner.mjs` and the host stage, and the eval comparison on real models (those need the real cell image and real models; see `platform/OPERATIONS.md`,
"Browser engine"). The text below is the original plan; where it differs (it kept a ladder and JEV's tiers), Revision 2 and `docs/architecture/native-execution.md` are authoritative.

Written 26 Oct 2026. A plan for the complete build, not a prototype. Nothing here is implemented. Runtime facts come from the OpenClaw 2026.9.6 docs installed locally;
anything not read or run is listed under "Unverified" and is gated by a step in the build, not assumed.

## Revision 2 (26 Oct 2026, owner's direction): no ladder; JEV and the native agent share one browser

Direction: the Haiku/Sonnet tiers go away. A browser task is handled by JEV or by the OpenClaw native browser agent, and when JEV fails or meets logic it cannot handle, its
progress goes straight to the native agent, which continues in the same browser. Design decisions that follow:

1. **One browser, two drivers.** JEV (fast, ~$0.00003/step, no reasoning) and the native agent (a full model run with browser tools) act on the same tab and profile in the
   customer's cell. The handoff is therefore a context handoff, not a restart: goal, subgoal, step history with results, current URL/title, what JEV last saw and why it stopped.
2. **Routing is by signals, not by hardcoded task keywords.** Start with JEV. Hand over when: JEV says `too_complex`, `ask_user` that it cannot settle, misses repeatedly, a
   loop/no-progress is detected, or the page has no usable controls and no spot. An up-front choice is made only for tasks that plainly need open-ended reasoning
   (research across sites, comparing, writing as part of the task), and that choice is made by the native run itself reading the request, not by a keyword list.
3. **The gate stays between every driver and the page.** The native agent does NOT get the runtime's own `browser` tool (stays denied). It acts through Lumina's tool served over
   MCP (act/snapshot/…), which runs the same code rules and `Policy` (payment, sign-in, human check, saved-login consent, deny list) before calling the cell's browser. Otherwise
   handing a task to the native agent would bypass the safety stops.
4. **Hand back is optional.** First build: once the native agent takes over, it finishes the task. A later step may return control to JEV for repetitive sub-steps.
5. **Things the ladder did besides choosing, which need a new owner:** confirming `done` (was a Haiku read) → the native agent confirms, or a deterministic check when one
   exists; writing text for a field (was Haiku) → the native agent or text from the request; naming options for a customer question (was Haiku) → the native agent. Outcome
   verification stays Lumina's (`outcome.py`).
6. **Cost control** moves from "Sonnet at most 2 per run" to: the existing 60%-of-reservation cap on the browser tool, plus a turn/step budget on the native run.

Effect on the plan below: the session interface now needs to be served to the native agent as MCP tools as well as to JEV's loop (workstream 1b), `browse/ladder.py` Haiku/Sonnet
paths are deleted (workstream 11), and the eval gate (workstream 8) compares JEV→native-agent against the current ladder.

## Goal

Today the browse service on the host runs one Docker Chromium stage at a time and drives it with `browse/runner.mjs` (Playwright). The loop (`browse/loop.py`) observes, applies
Lumina's code rules, asks the ladder (JEV, then Haiku, then Sonnet) for the next step, passes the gate and acts. The only seam is the session object (`browse/session.py`:
open / snapshot / act / probe / view / screenshot).

Target: the browser itself is OpenClaw's, running **inside the customer's cell**, one profile per customer. The brain (rules, ladder, gate, hand-offs) stays Lumina's and keeps
deciding every step. Only the hands change.

## What the native browser gives us (read in the docs)

- Dedicated user-data dir and ports per Gateway, deterministic tab handles (`suggestedTargetId`, `t1`), actions open / navigate / tabs / snapshot / act / screenshot / text /
  console / requests / errors / pdf / download / upload / dialog / emulate.
- Profiles: managed local (`openclaw`), named profiles, remote CDP. Persistent per profile, so a customer's logins live in their own cell.
- Navigation/SSRF policy enforced by the runtime on every read and action.
- A **screencast**: `POST /screencast` mints a single-use token for a live view of the selected tab (size 320–2000, quality settable). This is a candidate for the Live view.
- `browser.request` Gateway method; the Control UI and dashboards use it. Docs say to connect with `operator.admin`.
- No code-enforced payment stop, no consent before a saved login or card, no human-check hand-off, no customer takeover. Those stay ours, which is why the brain remains.

## Design

```
Customer UI ── Live view / takeover ──┐
                                       │
Cell OpenClaw run ── lumina_browser ──> relay ──> Browse job (host, brain: rules + ladder + gate + Policy)
                                                        │  session interface (open/snapshot/act/probe/view/screenshot)
                                                        ▼
                                          NativeBrowserSession ── bridge (browser.request, allow-listed) ──> cell Gateway browser plugin ──> cell Chromium
```

The `lumina_browser` tool, its budget limits (60% of the reservation), Stop, and the park/unpark path do not change. Only the session behind the browse job changes.

## Workstreams

### 1. `NativeBrowserSession` (host, `browse/native_session.py`)
Implements exactly the session interface the loop uses.
- `open` → profile start + tab open; `snapshot` → native snapshot mapped to the state text the ladder and `Policy` already consume (element refs become the click targets the
  ladder's heads name); `act` → native act with the same verbs (click, type, press, scroll, select, upload); `probe` → page text/URL/title/console for the code rules;
  `screenshot` → native screenshot; `view` → see workstream 4.
- A mapping table from the runner's action vocabulary to native actions, with a contract test per verb run against the real browser plugin.
- All native errors map to the loop's existing failure vocabulary so the ladder's retry/hand-off logic is untouched.

### 2. Bridge and scope
- New allow-listed bridge method `browser.request` with exact validators (method, path set, `target: "host"`, `query.profile` forced to the account's own profile, body size caps,
  no evaluate/eval route, no arbitrary URL for CDP attach). Nothing a caller sends may name another account or profile.
- Scope: the bridge's connection today has operator.read/write. Whether `browser.request` needs `operator.admin` or a narrower grant is **unverified**; step 1 of the build
  measures it. If admin is truly required, use a second, separate bridge connection used only for browser requests, so the existing connection never gains admin.
- The browse job reaches the bridge the same way the relay does (identity from the cell's own key via `cell.identify`).

### 3. Cell image and config (`lifecycle/cell_config.py`, cell image)
- Cell image variant with Chromium; `plugins.entries.browser.enabled` and `browser.enabled` true; headless; one managed profile per customer under the cell's persistent volume.
- Keep the agent's own `browser` tool **denied** (`tools.deny`): the runtime assistant must not drive it directly, only our job through the bridge.
- Navigation/SSRF policy set to block private ranges, the cell network, the bridge address and the relay port.
- Memory and CPU limits raised for cells that browse; cell wake time and sleep rules re-measured (Chromium must stop with the job so a sleeping cell holds no process).
- Existing cells take the new config at next start (same rule as the last migration).

### 4. Live view and takeover
- Frame source: the native screencast of the selected tab, fetched by the host through the bridge, re-served by the existing `live/gateway.py` and Caddy route so the customer UI
  (`live.ts`, `LiveScreen.tsx`) is unchanged. Falls back to periodic native screenshots if the screencast token flow cannot be proxied.
- Takeover input path (customer clicks/types): mapped to native act calls under the same code rules (a customer typing a card number is still never read by the model).
- Decision gate: if native screencast latency or fidelity is worse than the current ≤15 fps runner stream, keep the current frame path for the Live view only (Workstream 4 is
  independent of 1–3 for correctness).

### 5. Saved logins, card fill, human checks
- The vault fill offers and consent stay in `loop.py`/`Policy`; they call native `type`/`act` with the secret supplied host-side at the last moment and never placed in a
  snapshot, a log or a model prompt.
- Persistent native profile replaces the current per-job login storage; consent record, expiry and "forget" behavior unchanged and tested against the new store.
- Human-check and payment hand-offs unchanged (they are brain decisions on the snapshot).

### 6. Downloads and uploads
- Native download → saved into the account's artifacts via the existing workspace path; size, type and name rules as today. Uploads restricted to files already in the account's
  workspace.

### 7. Concurrency and capacity
- Drop the host's one-stage `Semaphore(1)` only after measuring cell memory under N concurrent browsing cells; replace with a capacity number tied to the host's memory budget
  and the existing request slot rules. Browser processes belong to the cell, so Lumina's admission and sleep logic already covers them.

### 8. Cost and reliability evaluation (gate before cutover)
- Use `evals/` (cases.yaml, run.py). Add the same cases for the native session and compare against the current runner on: task success, steps to done, ladder escalation rate,
  per-task model cost, wall time, crash/hang rate. Cutover requires the native path to meet or beat the current one on success and not exceed current cost.
- Real models and real sites are required; the scripted e2e cannot prove this.

### 9. Rollout and rollback
- Setting-gated per account, then percent of accounts, then default. This is a deployment switch for staged rollout and rollback, not a hidden fallback: a browse job runs on
  exactly one session type, recorded on the job, and a failed native session fails the job visibly; it never silently retries on the other one.
- Rollback = switch back; both session types ship together until parity is proven. Runner code is deleted only after a full release on native with the eval gate met.

### 10. Tests
- Unit: mapping table, bridge validators (every refused shape), profile forcing, size caps.
- Contract: each verb against a real cell browser plugin.
- E2E: extend `tests/e2e` with a real cell gateway that has the browser plugin and a local test site: navigate, form fill, download, payment stop, sign-in hand-off, Stop mid-action,
  cell restart mid-job, two customers isolated (profile A's cookies never visible to B), cell sleep with no browser process left.
- Frontend: Live view and takeover tests against the new frame source.

### 11. Docs and cleanup
- Update `native-execution.md` (the "Why the browser stayed an adapter" section), `SYSTEM_DESCRIPTION.md`, `platform/OPERATIONS.md`, `LIVE_VIEW.md`, ops dashboard.
- After the gate: remove `browse/runner.mjs`, the host Docker stage code (`stage_argv`), the host browse-stage service unit, its firewall/ufw rules and their tests.

## Order of work

1. Measure: `browser.request` scope, screencast proxying, Chromium memory in a cell, cell wake time. (Decides workstreams 2, 3, 4.)
2. Workstreams 2 and 3 (bridge, cell image/config) with tests.
3. Workstream 1 against the contract tests.
4. Workstreams 5, 6 (logins, downloads).
5. Workstream 4 (Live view/takeover).
6. Workstream 8 (evals on real models) — the cutover gate.
7. Workstreams 7, 9 (capacity, staged rollout), then 11 (cleanup).

## Risks

- Native snapshot format differs from what JEV was trained/tuned on (`_state()` text, click targets); ladder accuracy could drop. Mitigation: the state mapper in step 1 and the
  eval gate; this is the largest quality risk.
- Chromium per cell raises memory per customer; sleeping cells must really release it.
- Granting any admin-scoped path is a security cost; mitigated only by the separate connection and exact validators.
- Screencast token flow may not proxy cleanly through the bridge.

## Unverified (to be measured in step 1, not assumed)

- Required scope for `browser.request` on 2026.9.6 and whether a narrower grant works.
- Whether the browser plugin runs in the current cell image/gVisor setup at all.
- Screencast latency/fps versus the current runner stream.
- Native snapshot quality for the ladder, cost versus current, concurrent-cell memory.

## Step 1 measurements (26 Oct 2026, local Mac, OpenClaw 2026.9.6, Google Chrome headless; not the production cell image)

- **Scope: measured.** `browser.request` with `operator.read`+`operator.write` fails on every route with `FORBIDDEN missing scope: operator.admin`. With `operator.admin` all routes
  worked. So workstream 2's separate admin-scoped connection is required, not optional. Whether a narrower scope exists was not found.
- Cold start of the profile's Chrome took about 10.7 s on this machine; tab open and snapshot of example.com took 341 ms (snapshot is an accessibility-tree text with `[ref=eN]`
  handles). Production figures in a gVisor cell are not measured.
- **Screencast:** the token is minted by `POST /screencast` through `browser.request`, then a websocket at `/browser/screencast?token=…` on the cell's gateway sends a JSON `ready`
  message and then frames (6 messages in 6 s over a mostly static page, so the frame rate under motion is NOT measured). The websocket is on the gateway port, so the host
  would need a path to it (bridge relay only carries RPC today).
- Not yet measured: the browser plugin inside the real cell image under gVisor, Chromium memory per cell, frame rate under motion, snapshot quality for JEV.
