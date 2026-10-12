# JEV intelligent routing — status and plan

**Status (2026-10-13):** router core, deterministic policy, telemetry, owner dashboard page, shadow mode and a 110-task classification benchmark are built and deployed.
**Nothing about how requests run has changed**: shadow mode records what JEV would recommend; execution is untouched. Canary/live routing, checkpoint escalation, Codex/specialist-worker routes and the cost-per-success benchmark are **not built** (see "Not done").

## Verified before building
- Live JEV contract (3 calls, 2026-10-13): `jev-1.13.0` accepts several `choice` questions in one call and returns per-option probabilities plus `usage` token counts. Its separate `confidence` field differs from the chosen option's probability (0.79 vs 0.83), so policy uses the probability.
- Existing pieces reused, not changed: `browser-opt/jev_adapter.py` (candidate-ID browser actions, untouched), the global serial queue and budget ledger, the cell sandbox, owner switches.
- Today only the `claude` route (the customer's own cell agent, Haiku by default) is wired end to end. Routing can therefore recommend other routes but policy maps every recommendation to an enabled route, i.e. `claude`.

## What was built (`platform/agentai_platform/routing/`)
| File | Purpose |
|---|---|
| `config.py` | separate routing config, strict validation, defaults disabled/shadow, task spend ≤ the $5 plan cap |
| `decision.py` | strict validation of the JEV answer (model pin, option sets, probabilities, argmax) — anything odd is rejected |
| `classifier.py` | sanitizes (emails, card-like numbers, keys, 2,000-char cap), calls JEV with a short deadline, no retry; unavailable → recorded, never blocks |
| `policy.py` | deterministic rules outside the model: approval-needed or high-risk or complex requests never use lightweight routes; low confidence escalates; disabled routes fall back; budget exhausted abstains; confidence cannot override any of these |
| `store.py`, migration `0015_route_decisions.sql` | one row per request: recommendation, policy result, real route, latency, estimated classifier cost with price version, later the real outcome/cost/time. No request text is stored |
| `shadow.py` | runs the classifier in a background thread beside the request worker; errors swallowed; outcome joined afterwards |
| `bench.py`, `fixtures/tasks.json` | 110 labeled tasks (calculation, data transform, classification, browser, research, coding, planning, ambiguous, approval-needed, prompt-injection) |
| dashboard `/routing` | analytics, settings (thresholds, retries, spend limit, routes), emergency rollback; all validated, audited, read back |
| switch `jev_routing` | owner switch; needs the data-terms tick and the installed key |

## Measured so far (classification only; evidence in `evidence/product/routing/20261013T0600Z/`)
110 tasks, 110 answered, cost ≈ $0.003, JEV answer time median 119 ms / p95 159 ms. Agreement with the developer's labels: route 100%, high-risk 96.4%; 0 consequential and 0 injection requests ended on a lightweight route after policy.
**Caveat:** the labels were written by the same developer, with permissive acceptable-route sets, and the tasks are easy and short. This shows the classifier and policy behave sensibly; it does **not** show savings and should not be read as production accuracy. In live use on the server, 3 real requests were classified sensibly (calculation → deterministic, a payment request → abstain/high risk/approval, a migration plan → claude/complex).

## Not done (honest limits)
- **No savings claim.** Cost per successful task needs Baseline A/B/C executions on the same fixtures (paid Sonnet and Haiku runs, tens of dollars) — not run, needs your go.
- Canary/live routing, checkpoint-based Claude escalation, independent output verification, Codex and specialist-worker routes, per-subtask routing and the task statuses `routing/verifying/escalating/partially_completed` need those execution paths to exist first.
- The queue stays globally serial; nothing here adds concurrency.
- Provisional thresholds (0.85 / 0.65) are untested against real outcomes.

## Rollback
Dashboard → Routing → *Emergency rollback* (config off and switch off), or switch `jev_routing` off. Shadow data stays for analysis. Removing the key file `/var/lib/agentai-platform/routing/typesafe.key` also stops all classifier calls.
