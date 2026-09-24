"""Skill-library tenancy (spec accept): a skill saved by one user cannot be
listed or run by another — even by guessing the name; run_skill executes in
the RUNNER'S own sandbox; stats increment; needs_review flips after repeated
failures; path-traversal names are rejected."""

from __future__ import annotations

import json

import pytest

from core import db, skills
from tests.p2_conftest import task_context
from tools.base import call_tool

RUN_ADDER = (
    "import json, sys\n"
    "args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}\n"
    "print('sum:', sum(args.get('xs', [])))\n"
)


async def test_skill_saved_by_a_is_invisible_to_b(pro_users, fake_sandbox):  # noqa: F811
    alice, bob = pro_users
    saved = await skills.save_skill(
        str(alice.id), "summarizer", "Summarize a page of text",
        {"type": "object", "properties": {"url": {"type": "string"}}},
        "safe", {"instructions.md": "# steps\n1. fetch\n2. condense"},
    )
    assert saved["kind"] == "playbook"

    # B guesses the exact name:
    with task_context(str(bob.id), "t-bob"):
        listed = await call_tool("list_skills", {})
        assert listed.ok and listed.data == []
        ran = await call_tool("run_skill", {"skill_name": "summarizer"})
        assert not ran.ok and ran.error == "skill not found"
    assert await skills.load_skill(str(bob.id), "summarizer") is None

    # A sees and runs their own:
    with task_context(str(alice.id), "t-alice"):
        listed = await call_tool("list_skills", {})
        assert [s["name"] for s in listed.data] == ["summarizer"]
        ran = await call_tool("run_skill", {"skill_name": "summarizer"})
    assert ran.ok
    assert '<untrusted_content source="skill:summarizer instructions.md">' in ran.data
    assert "# steps" in ran.data


async def test_code_skill_runs_in_the_runners_own_sandbox(pro_users, fake_sandbox):  # noqa: F811
    alice, bob = pro_users
    await skills.save_skill(
        str(alice.id), "adder", "Sum numbers", {"type": "object"},
        "safe", {"run.py": RUN_ADDER},
    )

    with task_context(str(alice.id), "task-alice-1"):
        result = await call_tool("run_skill", {"skill_name": "adder", "args": {"xs": [1, 2, 3]}})
    assert result.ok
    call = fake_sandbox.calls[0]
    # The executing container slot is ALICE'S task (her own sandbox):
    assert call["task_id"] == "task-alice-1"
    assert call["entry"] == "skill/adder/run.py"
    assert call["argv"] == [json.dumps({"xs": [1, 2, 3]})]
    assert call["files"]["skill/adder/run.py"] == RUN_ADDER

    meta = await db.get_skill_meta(alice.id, "adder")
    assert meta.uses == 1 and meta.successes == 1 and meta.failures == 0

    # B running the same name executes NOTHING (they have no such skill):
    calls_before = len(fake_sandbox.calls)
    with task_context(str(bob.id), "task-bob-1"):
        refused = await call_tool("run_skill", {"skill_name": "adder", "args": {}})
    assert not refused.ok and refused.error == "skill not found"
    assert len(fake_sandbox.calls) == calls_before
    assert await db.get_skill_meta(bob.id, "adder") is None


async def test_code_skill_failure_recorded_and_reported(pro_users, fake_sandbox):  # noqa: F811
    alice, _ = pro_users
    await skills.save_skill(
        str(alice.id), "boomer", "always fails", {"type": "object"}, "safe",
        {"run.py": "raise SystemExit('nope')\n"},
    )
    fake_sandbox.script_outputs["task-alice-2"] = (1, "", "nope")
    with task_context(str(alice.id), "task-alice-2"):
        result = await call_tool("run_skill", {"skill_name": "boomer", "args": {}})
    assert result.ok  # the RUN was handled; the skill itself exited non-zero
    assert result.data["exit_code"] == 1
    meta = await db.get_skill_meta(alice.id, "boomer")
    assert meta.uses == 1 and meta.failures == 1


async def test_needs_review_flag_flips_and_clears(pro_users, fake_sandbox):  # noqa: F811
    alice, _ = pro_users
    await skills.save_skill(
        str(alice.id), "flaky", "flaky skill", {"type": "object"}, "safe",
        {"run.py": "pass\n"},
    )
    for ok in (False, False, False, True):  # 3 failures in 4 runs → 75% > 50%
        await db.record_skill_use(alice.id, "flaky", ok=ok)
    meta = await db.get_skill_meta(alice.id, "flaky")
    assert meta.reviewed is False  # flagged

    listed = await skills.list_skills(str(alice.id))
    assert listed[0]["needs_review"] is True
    # Flagged, never deleted:
    assert await skills.load_skill(str(alice.id), "flaky") is not None

    # Re-saving the skill clears the flag.
    await skills.save_skill(
        str(alice.id), "flaky", "flaky skill fixed", {"type": "object"}, "safe",
        {"run.py": "pass\n"},
    )
    listed = await skills.list_skills(str(alice.id))
    assert listed[0]["needs_review"] is False


@pytest.mark.parametrize("bad_name", [
    "../evil", "foo/bar", "Upper", "has space", "", "-lead", "x" * 80, ".hidden",
])
async def test_unsafe_skill_names_rejected(pro_users, bad_name):
    alice, _ = pro_users
    with pytest.raises(skills.SkillError):
        await skills.save_skill(
            str(alice.id), bad_name, "d", {"type": "object"}, "safe", {"run.py": "pass\n"}
        )


@pytest.mark.parametrize("bad_files", [
    {"../escape.py": "pass"},
    {"run.py": "pass", "/abs/path.py": "x"},
    {"run.py": "pass", "a/../../b.py": "x"},
])
async def test_path_traversal_in_files_rejected(pro_users, bad_files):
    alice, _ = pro_users
    with pytest.raises(skills.SkillError):
        await skills.save_skill(
            str(alice.id), "sneaky", "d", {"type": "object"}, "safe", bad_files
        )


async def test_skill_may_never_declare_high_risk(pro_users):
    alice, _ = pro_users
    with pytest.raises(skills.SkillError) as excinfo:
        await skills.save_skill(
            str(alice.id), "ambitious", "d", {"type": "object"}, "high", {"run.py": "pass\n"}
        )
    assert "never" in str(excinfo.value)


async def test_run_skill_risk_resolver_reads_declared_risk(pro_users):
    """The approval gate inherits the skill's declared risk (fail-closed)."""
    from tools.skills_tools import _run_skill_risk

    alice, bob = pro_users
    await skills.save_skill(
        str(alice.id), "gentle", "safe skill", {"type": "object"}, "safe", {"run.py": "pass\n"}
    )
    await skills.save_skill(
        str(alice.id), "spicy", "moderate skill", {"type": "object"}, "moderate", {"run.py": "pass\n"}
    )
    with task_context(str(alice.id), "t-a"):
        assert await _run_skill_risk({"skill_name": "gentle"}) == "safe"
        assert await _run_skill_risk({"skill_name": "spicy"}) == "moderate"
        assert await _run_skill_risk({"skill_name": "nope"}) == "moderate"  # unknown → fail closed
    # B resolving A's skill name gets the fail-closed fallback, never A's data:
    with task_context(str(bob.id), "t-b"):
        assert await _run_skill_risk({"skill_name": "gentle"}) == "moderate"
