# Roadmap Phase 1 - stabilize execution and recovery

**Status (2026-11-14): PARTIAL.** Five of the eleven features are built and tested against the synthetic runtime; none is proven on the live stack yet because nothing is deployed (Phase 0 is blocked on owner steps). Parallel execution (#8) is designed, not built: it needs the owner's hardware and database decision first.

## Built and tested (not yet live)
| # | Feature | Label was right? | What exists now | Tests |
|---|---|---|---|---|
| 3 | Capability evaluation | P, yes: `evals/cases.yaml` describes cases for the old personal-agent system and could not run them | **Tier A:** 13 executable acceptance cases through the real chat service, queue, worker and driver against the synthetic runtime, each asserting on facts (rows, receipts, runtime calls), never wording. `python deploy/acceptance.py list / run [--case ID]` | `tests/test_acceptance.py` |
| 4 | Regression detection | P | The runner compares with a committed baseline (`tests/acceptance_baseline.json`): a case that passed before and fails now exits 2, a case that disappeared exits 3. CI runs it as a blocking step | `RunnerChecks` |
| 1 | Rate-limit handling | P | The model relay waits for a busy provider (429, 503, 529) instead of passing the error on: the provider's `Retry-After` when given, else 2, 4, 8, 16, 30 s with jitter, at most 90 s per call; a budget refusal is never waited for; the customer's timeline says "Waiting a moment for the model provider" once per call; a task that still fails gets a plain sentence saying the provider was busy | `tests/test_rate_limits.py` |
| 5 | Tool and workflow versioning | P | Every request is stamped once with release commit, hash of the assistant rules and skills, hash of Lumina's tool names, runtime version and model route (`customer_requests.versions_json`, `versions.py`) | `A-VERSION-STAMP` |
| 6 | Durable objectives | P, yes: `durable.py` existed and was wired to nothing | Every "keep working until complete" chain is one durable objective: a checkpoint per finished turn (written once), continuation turns registered as children, state and a plain pause reason, sticky cancel when the goal is cleared, Stop pauses. Resume policy per job: `ask` (default) or `auto` (at most 3 automatic resumes after interrupted turns) | `tests/test_goal_objectives.py` |
| 7 | Long-running workflow management | P | A per-job budget the customer can see and change: turns (default 20, up to 500) and wall-clock time. Reaching it pauses the job with the reason, in the platform and in the runtime; raising it never resumes by itself. `GET /v1/objectives`, `GET/POST /v1/objectives/<id>`, `POST /v1/objectives/<id>/cancel` | same, plus `accounts/test_objectives.py` |
| 9 | Time and resource estimation | M, yes | `estimates.py`: median and 90th percentile of duration and cost of finished tasks of the same kind, the account's own history first (5 tasks), else all accounts (20), else nothing. `GET /v1/estimates/<kind>`. `hit_rate()` measures how often the upper bound held on recorded history | `tests/test_estimates.py` |

Suites after these changes: 576 platform tests in the blocking list (was 527), 354 account API tests, no report-only failures.

## Built, not yet proven
- **Live proof of everything above** (Tier B). Needs the deploy. The live acceptance script (`deploy/p15_acceptance.py`) was not extended or run.
- **Web app for long jobs and estimates.** The routes exist; no screen shows the checkpoint list, the budget, the resume policy or an estimate yet.
- **Rate limits for a customer's own model key and for connectors.** The waiting logic is on Lumina's own model route only.
- **Time a task waits for the provider does not yet extend its 900-second run limit.** The wait is bounded at 90 s per call.

## Not passed
- **NOT_BUILT #8 parallel task execution.** See the design and the decision below.
- **NOT_BUILT #2 large-task execution.** No change yet to how large files are written or how a reply cut off at the output limit continues.
- **NOT_BUILT #10 dependency management for plans, #11 plan adaptation.**
- **NOT_BUILT engines for #78 and #79.** `schedules.py` still refuses creation (`enforcement_proven` is false); no enforcement cases were written.
- **NOT_RUN Phase 1 exit gate.** Two accounts at once (needs #8 and a second enrolled account), kill-the-cell and kill-the-worker on the live stack, a week without a rate-limit failure.

## #8 parallel task execution: what was found, and the decision it needs

**The limit today is CPU, not memory.** Admission charges the enforced caps per running customer: 2.5 CPUs (cell 1.0, worker stage 1.5) and 3.5 GiB, with 0.5 CPU and 2.5 GiB held back. On the 4-CPU host that admits exactly one customer however much memory is free. Computed with `lifecycle/profiles.host_capacity`:

| Host | Customers running at once |
|---|---|
| 4 CPUs, 16 GiB (today) | 1 |
| 8 CPUs, 32 GiB | 3 |
| 16 CPUs, 32 GiB | 6 |
| 16 CPUs, 64 GiB | 6 (CPU-bound) |
| 32 CPUs, 64 GiB | 12 |

**So there are two separate changes**, and the first is useless without the second:

1. **Code:** replace the single `request_slot` row and the single `lifecycle_slot` row with pools. That touches `request_queue.py` (claim, finish, park, unpark, defer, the `ahead` count), `request_worker.py` (one uncertain request assumed), `lifecycle/coordinator.py` (seven places read `lifecycle_slot WHERE id=1`), `lifecycle/worker.py` and `sleep.py` (handover between accounts), `work.py`, the latency report and the lifecycle status command. Within one account, two conversations cannot run together today either: the driver defers a request while another conversation of the same cell has a run.
2. **Capacity:** a host with more CPUs, or lower per-customer CPU caps. Lowering the caps is free but makes each customer slower (a cell already takes about 16 s to start a run on 1 CPU).

**Recommendation.** A 16-CPU, 32 GiB host admits six customers at once with today's caps. Build the code change against the synthetic harness first with the pool size as a setting that defaults to 1 (so the release is behaviour-neutral), enroll a second test account, then raise the setting on the larger host. Keep SQLite until a second worker host is wanted; write new SQL portably.

**Why it was not built in this pass.** It rewrites the admission and lifecycle core, cannot be proven without a second enrolled account (blocked since Phase 15 as P15-TENANT-TWO-CELLS) and buys nothing on the current host. The prompt also asks for this decision before building.

## Decisions taken
- Evaluation cases live beside the tests they reuse (`tests/test_acceptance.py`), not in `evals/cases.yaml`, whose cases are prose for the earlier personal-agent system.
- A goal's durable record is kept by the code that already runs between turns (`GoalChain`), driven from the database, so a restart needs no special recovery step: the interrupted turn is recovered by the queue and recorded when it ends.
- Stop pauses a long job; only clearing the goal (or the new cancel route) cancels it for good.
- An estimate never limits or delays a task.

## Needs the owner
1. The Phase 0 server steps, so any of this can be proven live.
2. The host decision for #8 (table above), and a second test account.
3. Confirm the privacy-record entries for the new columns (`privacy/facts.json`, two entries dated 2026-11-14).

## Cost, unknowns, rollback
No spend. Unknown: how the runtime reports a reply cut off at its output limit (needed for #2); whether 90 s of waiting is within the runtime's own model-call timeout (if it is shorter, the runtime gives up first and retries by itself, which is harmless but makes the wait pointless: check the installed runtime's setting). Rollback: migrations 0038 and 0039 only add columns and indexes; the previous release runs unchanged against them.
