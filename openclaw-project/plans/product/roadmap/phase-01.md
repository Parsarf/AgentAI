# Roadmap Phase 1 - stabilize execution and recovery

**Status (2026-11-15): PASS.** All eleven features, and the engines behind #78 and #79, are built, tested and live; the exit gate was run on the real server and passed. Customer-facing schedules (Phase 7) stay behind the owner switch `customer_schedules`, off.

## What passed (live), with evidence
Run on the server with the owner's test account and a disposable second account that had its own cell (`deploy/phase1_live.py`, results in the run's journal). Model spend of the whole proof: about $7.

| Gate | Result |
|---|---|
| **Two accounts at the same time** | `P1-PARALLEL` PASS: both accounts ran a 200-word task at the same moment on their own cells (two cells running at once, two requests running at once), both completed, each charged once and settled (`P1-PARALLEL-CHARGE`), neither visible to the other (`P1-PARALLEL-ISOLATION`). |
| **Full host waits instead of failing** | `P1-QUEUE` PASS: with the ceiling set to one cell, the second customer's request waited in line (and said "waiting for a free assistant"), then finished when room was made. Nothing failed. |
| **Kill the worker mid-run** | `P1-KILL-WORKER` PASS: restarting the request worker during a run: one run, one receipt, the reply delivered. |
| **Kill the cell mid-run** | `P1-KILL-CELL` PASS: restarting the assistant's container during a run: one run, one receipt, the reply delivered. |
| **Rate limit** | `P1-RATE-LIMIT` PASS: with the account's model key limited to 2 requests a minute, a task that needed several model calls waited, said so in its timeline, and completed (no failure on a 429). |
| **Large tasks, three times each** | `P1-LARGE-REPORT` (a 50-page Word report), `P1-LARGE-APP` (a multi-file web app, zipped) and `P1-LARGE-SHEET` (a 2,000-row workbook) each finished **3 of 3**. |
| **Parallel phases** | `P1-LANES` PASS: two independent phases of one plan ran at the same moment in separate lanes on the real cell and the plan completed; every cent of the key's spend between their marks was charged to a phase. |
| **Version stamps** | `P1-VERSION-STAMP`, `P1-VERSION-ALL` PASS: every request of the last two hours carries release, rules, tools, runtime and model. |
| **Tier A blocks merges, Tier B follows every deploy** | 17 acceptance cases run in CI (blocking); after each deploy the workflow runs `accept`: the server checks the new release live and **rolls the previous release back by itself** if one check fails (`deploy/acceptance_live.py`, `agentai-deploy accept`). |

## Feature table
| # | Feature | Label was right? | State now | Switch | Tests / evidence |
|---|---|---|---|---|---|
| 1 | Rate-limit handling | P: yes | Lumina's route and the customer's own key wait for a busy provider (Retry-After, then 2, 4, 8, 16, 30 s with jitter, at most 90 s a call); a budget or quota refusal is never waited for; one `RouteLimiter` per (account, route) shares what the provider said between concurrent calls and is reusable by connectors; the wait is added to the run's time limit; the timeline says whose limit it is. | none (always on) | `tests/test_rate_limits.py`, `P1-RATE-LIMIT` |
| 2 | Large-task execution | P: yes | The assistant writes large files in parts and checkpoints (skill text in `agent_rules.FILES`); a reply cut off at the model's output limit is detected from the runtime's recorded stop reason (`length`) and carried on in the same task, at most three times, and the timeline says so. | none | `tests/test_output_cutoff.py`, real-runtime e2e, `P1-LARGE-*` |
| 3 | Capability evaluation | P: yes | 17 executable acceptance cases against the synthetic runtime (Tier A) plus the quick live gate and the wider live proof (Tier B). | none | `deploy/acceptance.py`, `deploy/acceptance_live.py`, `deploy/phase1_live.py` |
| 4 | Regression detection | P: yes | CI runs Tier A and compares with the committed baseline; every deploy runs Tier B and rolls back on failure. | none | `tests/test_acceptance.py`, `tests/test_auto_deploy.py` |
| 5 | Tool and workflow versioning | P: yes | Every request stamped once (release, rules and skills hash, tools hash, runtime, model route). | none | `A-VERSION-STAMP`, `P1-VERSION-*` |
| 6 | Durable objectives | P: yes | Every goal chain is an objective with a checkpoint per turn, restart recovery, resume policy, sticky cancel; the web app lists jobs with their checkpoints. | none | `tests/test_goal_objectives.py`, `LongJobs.test.tsx` |
| 7 | Long-running workflow management | P: yes | A visible budget (turns, time) the customer can raise, pause reason, "Stop for good"; Activity page shows it. | none | same |
| 8 | Parallel task execution | M: yes | Slot pools (`request_slots`, `cell_slots`, migration 0040); admission by the host's live capacity (memory, shared CPU, disk, processes, running cells deducted), requests beyond it wait in a fair queue; a request worker thread per account; the host supervisor's own ceiling is a policy setting. On this server about three cells at once by memory; a bigger server admits more with no code change. | owner setting `max_running_cells` (absent = by capacity) | `tests/test_parallel_requests.py`, `P1-PARALLEL`, `P1-QUEUE` |
| 9 | Time and resource estimation | M: yes | Median and 90th percentile of finished tasks of the same kind, shown as a range with "based on N tasks" on plan phases; nothing when there is too little history. | none | `tests/test_estimates.py`, `Estimate.test.tsx` |
| 10 | Dependency management for plans | P: yes | `dependsOn` already validated; now phases run when their prerequisites are done, independent ones at the same time in lanes (hidden child conversations with their own session) under two background slots per account; a plan with no dependencies stays sequential; the plan says why a phase is waiting; exact cost sharing between overlapping requests (`spend_marks`). | none | `tests/test_lanes.py`, `tests/test_spend_share.py`, real-runtime e2e, `P1-LANES` |
| 11 | Plan adaptation | P: yes | A failed phase, a changed result or the customer's wish leads to a proposal shown as a difference; finished phases never change (a failed one may only be replaced); the customer applies it, or chose automatic revision (at most twice, still checked). | none | `tests/test_replan.py`, `PlanAdaptation.test.tsx`, HTTP tests |
| 78e | Scheduled execution (engine) | P: yes | `schedule_engine.py`: one run per schedule per local day, a missed run follows the schedule's own policy and is never back-filled, the customer's grant expires, the run carries its own time and spending limit and never waits for a person. `ENFORCEMENT_PROVEN` is true and rests on the tests. | `customer_schedules` (off) | `tests/test_schedule_engine.py` (18 cases) |
| 79e | Change monitoring (engine) | P: yes | A watcher-gated schedule runs only when the watcher saw a change; an unchanged check costs no model call; a change notifies once across restarts. | same | same |

## Decisions taken
- **The runtime's history delta is not used.** Measured on 2026.9.6: a delta page can come back empty while the final reply exists. The mirror instead runs every other slice after two minutes.
- **A reply cut off at the output limit** is recognised from the stop reason the runtime records on the assistant message (`stopReason: "length"`), not from `agent.wait`, which does not carry it.
- **Estimates and long-job controls are informational / the customer's own**: an estimate never limits or delays a task; the job budget is theirs to raise.
- **Parallel phases need exact accounting**, so concurrent requests of one account share the key's running total by marks, equally between those running in each stretch (a request alone is charged exactly as before).
- **The host supervisor** kept its one-running-cell rule as a configurable ceiling (`max_running`, now 4 here); only starting a cell counts against it, never creating, backing up or stopping.
- **Live proof tooling cleans up completely**: a cell the proof makes is removed through the runtime's own registry (`fleet rm`), its network, volume, key and custody record (a first attempt left registry entries that made the next creation fail; found and fixed during the proof).

## Needs the owner
Nothing blocks Phase 1. Open questions that are business decisions, not engineering: whether to raise `max_accounts` (still 2 customers) and the host ceilings, and turning `AUTO_DEPLOY_ENABLED` on so merges deploy without the manual run (the workflow, the deploy program and Tier B are ready; the setting is the owner's).

## Cost, unknowns, rollback
Cost of the live proof about $7. Unknown: the real number of customers one 16 GiB host carries before CPU becomes the limit; the memory per customer cell has not been measured under load (the capacity model charges the full 2 GiB cap, so it errs on the safe side). Rollback: each migration (0040 to 0043) only adds; the previous release runs against it. Before rolling the app back set `max_running_cells` to 1 so two cells never run under old code. Tier B does the rollback itself when a deploy fails live acceptance.
