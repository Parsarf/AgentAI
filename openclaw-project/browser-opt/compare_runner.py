#!/usr/bin/env python3
"""Paired-route comparison runner scaffold (Phase 9 build; execution Phase 11).

Refuses to run the optimized route while the master kill switch
(config.json "enabled") is false or --enable-optimized is absent. Never
handles credentials: the TypeSafe key lives server-side behind the
protected secret path. The 30-scenario paid benchmark is Phase 11 scope and
is refused here entirely.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

USAGE_DIR = HERE / "usage"


def load_yaml_min(path: Path) -> dict:
    """Minimal loader for the flat fixture file (no PyYAML dependency)."""
    data = {"dev": [], "heldout": []}
    section = None
    cur = None
    for raw in path.read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("dev:") or raw.startswith("heldout:"):
            section = raw.split(":")[0]
            continue
        if raw.startswith("  - id:"):
            cur = {"id": raw.split(":", 1)[1].strip()}
            data[section].append(cur)
            continue
        if cur is not None and raw.startswith("    "):
            k, _, v = raw.strip().partition(" ")
            k = k.rstrip(":")
            cur[k] = v.strip()
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--route", choices=["baseline", "optimized"], required=True)
    ap.add_argument("--scenario", help="fixture scenario id")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--enable-optimized", action="store_true",
                    help="explicit operator intent; the config kill switch "
                         "must ALSO be enabled")
    args = ap.parse_args()

    cfg = json.loads((HERE / "config.json").read_text())
    fixtures = load_yaml_min(HERE / "fixtures.yaml")

    if args.list:
        for section in ("dev", "heldout"):
            for s in fixtures[section]:
                print(f"{section:>7} {s['id']}")
        return 0

    if args.route == "baseline":
        if not args.scenario:
            ap.error("--scenario required")
        scen = next((s for sec in ("dev", "heldout") for s in fixtures[sec]
                     if s["id"] == args.scenario), None)
        if scen is None:
            sys.exit(f"unknown scenario {args.scenario}")
        trace = uuid.uuid4().hex[:12]
        record = {"trace": trace, "route": "baseline", "scenario": scen["id"],
                  "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "status": "planned",
                  "note": "executed via existing browser-worker path in "
                          "Phase 10/11; this build only plans and logs"}
        USAGE_DIR.mkdir(exist_ok=True)
        with (USAGE_DIR / f"trace-{trace}.json").open("w") as f:
            json.dump(record, f, indent=1)
        print(f"planned baseline run of {scen['id']} (trace {trace}); "
              f"goal: {scen.get('goal')}")
        return 0

    # optimized route — disabled unless BOTH switches are on
    if not args.enable_optimized or not cfg.get("enabled"):
        reason = ("config kill switch is OFF (enabled=false)"
                  if not cfg.get("enabled") else
                  "--enable-optimized flag missing")
        print(f"REFUSED: optimized route unavailable: {reason}", file=sys.stderr)
        return 3
    cred = None  # runner never holds credentials; transport resolves them
    if cred is None:
        print("REFUSED: no server-side credential path wired in this build; "
              "Phase 11 wires and authorizes it", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
