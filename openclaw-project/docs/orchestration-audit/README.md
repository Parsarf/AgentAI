# Lumina orchestration audit

> **Historical.** This page describes the code before the move to native OpenClaw execution (26 Oct 2026): the `lumina-step` protocol, JEV tool choice, Pursuit, the
> round loop and transcript polling no longer exist. The current description is [native-execution.md](../architecture/native-execution.md). Kept for the record.


A read-only, evidence-based audit of everything in this repository that orchestrates agent work: current, alternate, legacy, disabled, unreachable, experimental, and recoverable from Git.
Inspected 25 Oct 2026 on branch `product-phases-6-11` (HEAD `5db9636`, plus the uncommitted working tree). Nothing was changed, run, deployed or installed in the project; only files under `docs/orchestration-audit/` were created. An earlier, narrower map of the main request path is in [`../architecture/`](../architecture/README.md); where the two differ, this audit is the later and more complete one (one correction is listed at the end).

Paths are relative to `openclaw-project/`. Line numbers are from the working tree and will drift; symbol names are durable.

## Contents
| File | What it answers |
|---|---|
| [02-path-registry.md](02-path-registry.md) | The 45 orchestration paths (P01 to P45), each with status, entry, chain, decision owner, models and tools, state, completion, failure and recovery, relations, evidence |
| [03-entry-points.md](03-entry-points.md) | Every way work can enter (customer, owner, operator, dormant) and whether entries share an engine |
| [04-current-orchestration.md](04-current-orchestration.md) | Diagrams 1 to 7: landscape, end-to-end flow, planning and decisions, model and tool routing, execution loop and replanning, queue/worker/cell/concurrency, approvals and cancellation |
| [05-state-events-persistence.md](05-state-events-persistence.md) | Diagrams 8 and 9: task states and recovery; persistence, events, polling and frontend updates; state and event catalogs |
| [06-history-and-legacy.md](06-history-and-legacy.md) | Diagram 10: evolution and replacement map; commit and branch table; legacy implementations |
| [07-registries.md](07-registries.md) | Decision ownership matrix, tool and model registry, configuration matrix |
| [08-inconsistencies.md](08-inconsistencies.md) | Confirmed defects, risks, hypotheses, unknowns |
| [09-coverage-ledger.md](09-coverage-ledger.md) | What was inspected, excluded, unavailable, unresolved |
| [`svg/`](svg/) | All 11 diagrams rendered to SVG (`<file>-<block>.svg`); open in a browser |

## Executive overview
**How orchestration actually works.** A customer message becomes one row in `customer_requests`. Admission checks identity, rate limits, a queue cap of three, and reserves a budget. A single worker claims one request at a time across **all** customers and hands the message, prefixed with instructions, to the customer's own assistant. That assistant is the OpenClaw runtime inside an isolated cell; it plans, answers, and uses its own tools, and **Lumina does not contain that loop**. Lumina only polls its transcript, mirrors it, enforces time and money limits, and recognises one structured request: a fenced `lumina-step` block. When the assistant asks for a website, Lumina's code (and optionally JEV, a third-party classifier) picks the browser or search; the browser agent is a separate Lumina-written loop with a ladder of deciders (JEV, Claude Haiku, Claude Sonnet) under code rules that stop at payments, sign-ins and human checks. Results go back into the same session; at the end Lumina collects files, validates cards, settles spend and marks the request `completed`, `failed` or `cancelled`.

The loop is **assistant-first** since 20 Oct 2026. Before that a `ServiceRouter` let JEV choose a service before the assistant answered (14 to 20 Oct), and before that the assistant answered alone. A much older multi-user agent (23 to 27 Sep) was retired and is recoverable from Git. A great deal of other implemented code (schedules, memory, skills, watchers, durable objectives, optimization gates, a worker broker, an optimized browser route) is **not connected to any caller**.

## The 45 paths by status
| Status | Count | Paths |
|---|---|---|
| Current and reachable | 6 | P16 P18 P19 P21 P22 P23 |
| Reachable under specific configuration | 13 | P01 P02 P03 P04 P05 P06 P09 P10 P11 P13 P14 P17 P20 |
| Implemented but disabled | 4 | P07 P15 P27 P28 |
| Apparently unreachable | 6 | P08 P29 P30 P31 P32 P33 |
| Legacy but still partially active | 2 | P12 P34 |
| Superseded | 1 | P35 |
| Deleted but recoverable from history | 2 | P36 P37 |
| Experimental or prototype | 2 | P38 P39 |
| Test-only or mock | 2 | P41 P42 |
| Documentation-only | 1 | P40 |
| External and not inspectable | 3 | P24 P43 P44 |
| Uncertain | 3 | P25 P26 P45 |
| **Total** | **45** | |

## Most significant findings (details and evidence in [08-inconsistencies.md](08-inconsistencies.md))
1. **The running orchestration is uncommitted.** The assistant-first protocol, tool decider, pursuit, safety/vault and about 20 tests exist only in the working tree; releases live9 to live24 were deployed from it. HEAD still contains the router-era call site while HEAD itself deleted the router module (I-15, I-16).
2. **UI controls that only edit text.** The Tools menu and Home tiles never reach the backend; only the Respond mode does (I-05).
3. **Advertised capabilities with no execution:** automations and schedules, calendar, file attachments (and uploads feeding the agent), connectors for the agent, credentialed browsing (I-06).
4. **A cancelled-while-waiting request is never settled**: its reservation and `queued` task row stay, with plausible effects on allowances and idle sleep (I-12, R-04; needs a run to confirm).
5. **A legacy entry point that can only fail:** `POST /v1/requests` has no reservation and ends "unfunded" (I-10).
6. **One global request slot** across all customers, with a 900 s run limit and 1800 s abandon time (R-01, R-02).
7. **Four overlapping flag systems; four switches with no effect** (I-01, I-02).
8. **No approval flow for the assistant's own tools**: the `approval_request` event is declared and mapped to an orb state but never emitted (I-09).
9. **Completion is formatting, not verification**, in chat and in Browse mode (a handoff counts as completed) (I-21, I-22).
10. **Telegram runs without the tool protocol and results are not sent back** (I-08).

## Validation
- **Diagram syntax:** 11 of 11 diagrams in this folder parse with `mermaid.parse` (mermaid 11.4.1 under jsdom). The 14 diagrams of the earlier `docs/architecture/` also parse.
- **Rendering:** all 11 were rendered in Chrome and saved as SVG in `svg/`; the landscape (diagram 1) is large (about 4100 by 3200 px), so view the SVG zoomed.
- **Registry reconciliation:** every identifier P01 to P45 appears in the registry and in the landscape diagram (script check). Edges without direct code evidence are drawn dashed and labelled `?`, `cfg` or `hist`.
- **Source references:** 485 file references in these documents were checked; every cited file exists except files that live only in Git history or outside the repository (legacy `agent/` tree, `routing/services.py` and its two tests, the server path of `routing.json`, the OpenClaw package docs and short basenames used in prose). No cited line number is past the end of its file. About 60 symbol-to-line pairs were spot-checked against the code earlier in this work.
- **Not done:** tests were not run (1,191 test functions in 95 files were counted, not executed); no server, external service or running process was inspected; OpenClaw's bundled source was not traced.

## Correction to the earlier map
`docs/architecture/system-overview.md` showed the live-frame gateway as a separate privileged service. `platform/deploy/LIVE_VIEW.md` states it is a thread inside the browse service (port 18801); the earlier diagram and table were corrected and re-rendered.
