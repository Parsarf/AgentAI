"""Small manifest-to-pytest evaluator; no dynamic code or second fixture layer."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = (ROOT / "tests/test_tasks.yaml", ROOT / "tests/trap_tests.yaml")
PROFILES = {"local", "container", "provider"}
SEVERITIES = {"critical", "high", "normal"}
FIELDS = {"id", "test", "severity", "category", "profile"}


def load_scenarios(paths: tuple[Path, ...] = MANIFESTS) -> list[dict[str, str]]:
    scenarios = []
    ids = set()
    for path in paths:
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, list):
            raise ValueError(f"{path.name}: expected a list")
        for row in data:
            if not isinstance(row, dict) or set(row) != FIELDS:
                raise ValueError(f"{path.name}: scenario must have exactly {sorted(FIELDS)}")
            if not all(isinstance(value, str) and value for value in row.values()):
                raise ValueError(f"{path.name}: scenario values must be nonempty strings")
            node = row["test"]
            if (
                row["id"] in ids
                or row["profile"] not in PROFILES
                or row["severity"] not in SEVERITIES
                or not node.startswith("tests/test_")
                or ".py::test_" not in node
                or node.count("::") != 1
                or any(ch in node for ch in " \t\n;&|$`")
            ):
                raise ValueError(f"{path.name}: invalid scenario {row['id']!r}")
            module = ROOT / node.split("::", 1)[0]
            if not module.is_file():
                raise ValueError(f"{path.name}: test file does not exist: {node}")
            ids.add(row["id"])
            scenarios.append(row)
    if not scenarios:
        raise ValueError("no scenarios")
    return scenarios


def read_junit(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    statuses = {}
    for case in root.iter("testcase"):
        file = case.get("file")
        if not file:
            file = case.get("classname", "").replace(".", "/") + ".py"
        node = f"{file}::{case.get('name', '')}"
        statuses[node] = (
            "error"
            if case.find("error") is not None
            else "failed"
            if case.find("failure") is not None
            else "skipped"
            if case.find("skipped") is not None
            else "passed"
        )
    return statuses


def summarize(
    scenarios: list[dict[str, str]], profile: str, statuses: dict[str, str], pytest_exit: int
) -> tuple[int, list[tuple[str, str]]]:
    selected_profiles = {"local", profile}
    output = []
    critical_bad = False
    other_bad = False
    selected = 0
    for row in scenarios:
        if row["profile"] not in selected_profiles:
            output.append((row["id"], f"not-run ({row['profile']} profile)"))
            continue
        selected += 1
        status = statuses.get(row["test"], "missing")
        output.append((row["id"], status))
        if status != "passed":
            if row["severity"] == "critical":
                critical_bad = True
            else:
                other_bad = True
    if selected == 0 or pytest_exit != 0:
        other_bad = True
    return (1 if critical_bad else 2 if other_bad else 0), output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(PROFILES), default="local")
    args = parser.parse_args(argv)
    try:
        scenarios = load_scenarios()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2
    selected = [row["test"] for row in scenarios if row["profile"] in {"local", args.profile}]
    with tempfile.TemporaryDirectory(prefix="agent-evals-") as directory:
        report = Path(directory) / "junit.xml"
        command = [sys.executable, "-m", "pytest", "-q", f"--junitxml={report}", *selected]
        result = subprocess.run(command, cwd=ROOT, check=False)
        try:
            statuses = read_junit(report)
        except ET.ParseError:
            statuses = {}
        exit_code, rows = summarize(scenarios, args.profile, statuses, result.returncode)
    print("SCENARIO                         RESULT")
    for name, status in rows:
        print(f"{name:<32} {status}")
    print(f"profile={args.profile} pytest_exit={result.returncode} eval_exit={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
