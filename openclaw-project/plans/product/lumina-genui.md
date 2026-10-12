# Lumina generative UI — audit, what is built, what is not

**Status (2026-10-13, updated):** foundation, requirements forms, the editable plan diagram, **phase-by-phase execution with real per-phase progress, approval gates, and editing of phases that have not started** are built, deployed and verified end to end with the real runtime. Advanced interfaces (comparison, workflow, file tree, result screens) are **not** built.

## 1. Audit (verified in code and on the server)
| Question | Finding |
|---|---|
| Chat architecture | `chat_messages` (customer/agent/system) + `customer_requests` queue + `tasks`/reservations; replies come from the account's own OpenClaw cell through the cell bridge. Messages were plain text |
| Streaming | task events (`/v1/tasks/{id}/events`, SSE) exist; Lumina polls |
| Planning / approvals | none existed. The runtime can ask for confirmation in text, but there were no approval objects |
| JEV / Claude | JEV: shadow classification only, not in the request path. Claude: the cell's model route. Neither was used for UI generation |
| Reuse | existing queue, admission/ledger, usage reconciliation, cell runtime, auth/CSRF, rate limiter, restore classification |
| New | tables `ui_blocks`, `plan_revisions`, `plan_launches`; `customer_requests.intent/context_json` (migration 0017) |

## 2. Architecture
`user message → deterministic intent (genui/intent.py) → text | requirements form (server template, no model call) | plan request (the runtime drafts JSON) → validate → block → user edits locally → autosave (optimistic version) → approve → launch → runtime executes the approved revision`
- Blocks are **data**: strictly validated specifications (Python `genui/schema.py` is authoritative, Zod mirror in `lumina/src/lib/genui/schema.ts`). Unknown keys, field types, actions, oversized or invalid values are rejected; the UI shows a read-only note for anything it cannot render.
- A block can do exactly four things, each a registered endpoint that re-authorizes and re-validates: list (`GET /v1/conversations/{id}/blocks`), save edits (`POST /v1/blocks/{id}/state`), submit a form (`…/submit`), launch a plan (`…/launch`). Blocks are created only by server code, never from a request body.
- Plan generation reuses the customer's own runtime and billing (no new model path): a prompt asks for one JSON object, the reply is validated, **one repair attempt** is made in the same session, then it falls back to plain text. The raw JSON is never shown; the chat shows "I drafted a plan…".
- Launch stores the approved revision (`plan_revisions` source `approved`) and creates one row per enabled phase (`plan_phase_runs`). **Each phase is its own request** (same chat, same runtime session) started by `genui/runner.py` through normal admission, one at a time in dependency order; the runtime is told to do only that phase and is given earlier phase results as context. The request worker advances plans after every tick; double clicks and retries return the same run.
- **Approval gates are real:** a phase marked "ask me first" is not started; its row waits in `awaiting_approval` until the user approves it (`POST /v1/blocks/{id}/phase`). Editing a gated phase voids an earlier approval.
- **Live edits:** phases that are pending or awaiting approval can be renamed, rewritten, reordered, toggled, added or removed (`POST /v1/blocks/{id}/live`); the server rejects any change to a phase that is running, done or failed. A failed phase stops the run until the user retries or skips it; "Stop plan" cancels the rest.
- Three kinds of change: local (toggles, sliders, conditional questions, rename/add/remove/reorder/undo — no network), server (debounced autosave, submit, launch — no model), reasoning (plan drafting and one repair — the only model calls).

## 3. Delivered features
- **Response types:** plain text; compact requirements form (website template with conditional questions); editable plan. Composer has Auto / Text / Plan to override the automatic choice.
- **Form components:** select, segmented, radio, toggle/checkbox, slider, number, text, textarea, conditional `showIf`, defaults, required, help, autosave with a visible save status, conflict detection across tabs.
- **Plan diagram:** rows by dependency (parallel phases side by side), rename, instructions, enable/disable, optional, approval gate flag, "runs after" with loop prevention, add before/after/at end, duplicate, remove with dependents warning (reconnect or drop link), move up/down and drag and drop, undo/redo (bounded 50), reset to the AI plan, live validation (cycle, missing or switched-off prerequisite, empty plan), launch disabled until valid.
- **Persistence:** drafts and the AI original survive refresh; revisions `ai` → `user` → `approved`; launched plans are frozen.
- **Limits:** 30 form fields, 25 phases, 64 KiB per specification or state, autosave 90/min, block actions 60/hour. The general API limits were raised from 60/10 to 240/30 per minute (a live dashboard polls).

## 4. Verified
- Backend: 12 new tests (schemas, intent, flows incl. repair and fallback, approved-revision execution, isolation across tenants) + HTTP tests (CSRF, conflicts, bad input, other tenant 404, idempotency). 488 platform / 128 Django tests pass.
- Front end: 21 new tests for plan logic and the form/plan components (conditional questions locally, one debounced save, no model call, dependency warning and reconnect, launch version, read-only after launch). 32 pass.
- **Live, real model (2026-10-13):** "Build me a landing page website for a small bakery" → form without a model call → answers saved and submitted → the runtime drafted a valid 8-phase plan with parallel branches → edited to a 2-phase plan → launched → the runtime executed that approved plan (slogan drafted, length checked). Cost about 4 cents. Visual check of the form and diagram in Chrome against a mock API.

## 5. Spec scenarios
| # | Scenario | Result |
|---|---|---|
| 1 | Simple question stays text | built, unit-tested (`What is React?` → text) |
| 2 | Requirements interface, conditional, persisted | built for **websites only**; other build requests go straight to a plan or text |
| 3 | Editable plan (add/delete/rename/reorder/disable/dependencies) | built and tested |
| 4 | Launch creates real tasks from the approved version | built, verified live; **per-phase** status, results, approval gates and stop/retry/skip |
| 5 | Modify future phases during execution | built: future phases editable, started/finished phases locked, approvals voided by edits, tested at API, component and live levels |
| 6 | Comparison with local sort/filter | **not built** |
| 7 | Invalid AI output → validate, bounded repair, safe fallback | built for plans (one repair, then text). Forms are templates, not AI-generated |
| 8 | Refresh keeps the draft, no duplicate launch | built, tested |
| 9 | Unauthorized action rejected with no side effect | built, tested (only four registered operations; ownership and state checks) |
| 10 | Model failure → fallback, no fabrication | partly: a failed or unreachable run is handled by the existing recovery; the reply degrades to text. JEV is not in this path |

## 6. Not built (and what each needs)
Percentage progress inside a phase (the runtime reports none; phases show Running with elapsed time) · parallel phase execution (the queue is serial, so independent phases run one after another) · comparison, workflow builder, file-tree preview, in-chat approval cards, cost estimator and result interfaces (each a new component set plus a server action) · AI-generated form specifications and template selection by JEV (needs the routing work to leave shadow mode) · template/specification caching and the full metrics set (model calls per task, validation failure rate, abandonment) · accessibility audit and phone-width test of the blocks · more requirement templates beyond websites.

## 7. Known limitations
- A first plan can take about a minute when the assistant has to wake up. The page shows "Working…".
- Reordering changes order within a row; dependencies decide what must finish first (stated in the UI).
- Estimated cost per phase is not available; each phase is its own request under the $5 task cap and the plan allowance. A plan of N phases makes N model turns (plus one for drafting), each a few cents on the default model.
- Phases share the chat's runtime session, so later phases see earlier ones; they run strictly one after another.
- Plan quality depends on the model; the user is expected to edit before launching.

## 8. Live run check (2026-10-13)
A three-phase plan with an approval gate on phase 2 ran on the server with the real model: phase 1 ran (about 2 minutes including the assistant waking up), the run paused with `awaiting_approval`, approving started phase 2, phase 3 followed, and the chat received a "Plan finished" message. Each phase's own result was stored and shown in the diagram.
