"""Evaluator validation and exit statuses cannot turn missing evidence green."""

from __future__ import annotations

import pytest

from tests import run_evals


def _row(severity="critical", profile="local"):
    return {
        "id": "case",
        "test": "tests/test_run_evals.py::test_manifest_rejects_code",
        "severity": severity,
        "category": "safety",
        "profile": profile,
    }


def test_manifest_rejects_code(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "- id: bad\n  test: 'tests/test_run_evals.py::test_x; rm x'\n"
        "  severity: critical\n  category: safety\n  profile: local\n"
    )
    with pytest.raises(ValueError):
        run_evals.load_scenarios((path,))


def test_missing_critical_evidence_fails():
    code, rows = run_evals.summarize([_row()], "local", {}, 4)
    assert code == 1
    assert rows == [("case", "missing")]


def test_skipped_required_check_is_not_pass():
    row = _row("high")
    code, _ = run_evals.summarize([row], "local", {row["test"]: "skipped"}, 0)
    assert code == 2


def test_optional_profile_stays_visible():
    row = _row(profile="container")
    code, rows = run_evals.summarize([row], "local", {}, 0)
    assert code == 2  # zero local collection is not green
    assert "not-run" in rows[0][1]


def test_exact_pass_only():
    row = _row()
    code, _ = run_evals.summarize([row], "local", {row["test"]: "passed"}, 0)
    assert code == 0
