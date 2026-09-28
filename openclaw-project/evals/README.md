# Evals — acceptance case harness (Phase 7 build; NOT executed here)

This directory contains the versioned, repeatable acceptance suite for the
deferred gates from Phases 1–6 plus operations/restore cases. Per the build
contract, **nothing here runs during build phases**: no model probes, no
attack runs, no restore drill, no paid cases. Execution happens in Phase 10
only when the owner explicitly resumes testing, within approved budgets.

## Contents

- `cases.yaml` — every case with: id, capability, gate, setup, input/seed,
  assertions, forbidden_effects, evidence oracle, timeout, retry bound,
  cost allocation, cleanup, and current status
  (`ready` / `blocked:<reason>` / `owner-deferred`).
- `run.py` — manager for the suite:

```sh
python3 evals/run.py list                 # table of cases + status
python3 evals/run.py validate             # schema-check cases.yaml (free)
python3 evals/run.py show T10-INJECTION-NO-EFFECT
```

## Execution rules (enforced later, stated now)

- Paid cases (`cost.free: false`) require an explicit `--enable-paid` flag on
  the future Phase 10 runner; build-time `run.py` refuses them outright.
- `blocked:` cases report BLOCKED with the precise reason (e.g. reviewer
  admission, owner account login) instead of failing silently.
- Owner-deferred connections stay disconnected; their cases assert the
  fail-closed denial, not the connected behavior.
- Fixtures are synthetic and isolated; no real secrets (canaries only).
- Dashboard cases are added in Phase 8; browser-optimization comparison
  cases in Phase 9. This suite is not silently shrunk after failures.
