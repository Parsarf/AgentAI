#!/usr/bin/env python3
"""Manager for the acceptance case suite (evals/cases.yaml).

Build-phase scope (Phase 7): list, validate, show. This tool intentionally
cannot execute cases; the Phase 10 acceptance runner will execute them under
owner-resumed budgets. Paid cases are never runnable from this file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

REQUIRED = {
    "id", "capability", "gate", "setup", "input", "assertions",
    "forbidden_effects", "oracle", "timeout_s", "retries", "cost",
    "cleanup", "status",
}
ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases.yaml"


def load():
    if yaml is None:
        sys.exit("PyYAML required (pip install pyyaml)")
    with CASES.open() as fh:
        cases = yaml.safe_load(fh)
    if not isinstance(cases, list) or not cases:
        sys.exit("cases.yaml must be a non-empty list")
    return cases


def validate(cases) -> list[str]:
    errors, seen = [], set()
    for c in cases:
        cid = c.get("id", "<missing-id>")
        if cid in seen:
            errors.append(f"{cid}: duplicate id")
        seen.add(cid)
        missing = REQUIRED - set(c)
        if missing:
            errors.append(f"{cid}: missing fields {sorted(missing)}")
        cost = c.get("cost") or {}
        if not isinstance(cost, dict) or "free" not in cost or "route" not in cost:
            errors.append(f"{cid}: cost needs free+route")
        if not isinstance(c.get("forbidden_effects") or [], list):
            errors.append(f"{cid}: forbidden_effects must be a list")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["list", "validate", "show"])
    ap.add_argument("case_id", nargs="?")
    args = ap.parse_args()
    cases = load()

    if args.command == "validate":
        errors = validate(cases)
        if errors:
            print("INVALID:")
            for e in errors:
                print(" -", e)
            return 1
        paid = sum(1 for c in cases if not c["cost"]["free"])
        print(f"OK: {len(cases)} cases valid ({paid} paid, "
              f"{len(cases) - paid} free). Execution is Phase 10 scope.")
        return 0

    if args.command == "list":
        for c in cases:
            tag = "paid" if not c["cost"]["free"] else "free"
            print(f"{c['id']:<34} gate{c['gate']:<2} {tag:<5} {c['status']}")
        return 0

    if args.command == "show":
        if not args.case_id:
            sys.exit("show requires a case id")
        for c in cases:
            if c["id"] == args.case_id:
                for k in sorted(c):
                    v = c[k]
                    if isinstance(v, list) and v and isinstance(v[0], (str,)):
                        print(f"{k}:")
                        for item in v:
                            print(f"  - {item}")
                    else:
                        print(f"{k}: {v}")
                return 0
        sys.exit(f"no case {args.case_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
