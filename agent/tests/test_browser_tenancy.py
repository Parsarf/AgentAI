"""Browser tenancy: A's logged-in session is invisible to B; profile paths
are structurally user-confined; free-tier users can't even reach the tools."""

from __future__ import annotations

import json

import pytest

from core import secrets_vault as sv
from tests.browser_site import PASSWORD, USERNAME
from tests.p2_conftest import task_context
from tools import browser as tbrowser
from tools.base import call_tool


def test_profile_paths_are_user_confined(monkeypatch, tmp_path):
    """The path builder only ever derives a path from the acting user id —
    traversal, absolute paths, and foreign-profile guesses all collapse."""
    from core.config import settings

    monkeypatch.setattr(settings.browser, "profile_root", str(tmp_path / "profiles"))
    root = tbrowser.profile_root()
    a = tbrowser.profile_dir("userA", "default")
    b = tbrowser.profile_dir("userB", "default")
    assert a != b
    assert str(a).startswith(str(root) + "/userA/")
    assert str(b).startswith(str(root) + "/userB/")

    with pytest.raises(ValueError):
        tbrowser.profile_dir("../../userB", "default")
    with pytest.raises(ValueError):
        tbrowser.profile_dir("", "default")

    # Odd profile NAMES fall back to "default" (never create odd dirs);
    # traversal in the USER id is what raises.
    assert tbrowser.profile_dir("userA", "../../escape") == a
    assert tbrowser.profile_dir("userA", "../../bob") == a


async def test_sessions_do_not_cross_users(pro_users, browser_env, chromium, login_site):
    alice, bob = pro_users
    origin = login_site.origin
    await sv.store_credential(
        str(alice.id), origin, json.dumps({"username": USERNAME, "password": PASSWORD})
    )

    # A logs in for real:
    with task_context(str(alice.id), "t-a"):
        result = await call_tool("browser_login", {"site": origin})
        assert result.ok, result.error
        assert "Welcome back" in result.data

    # B opens the SAME site with the SAME profile name and sees a logged-OUT
    # state — never A's session:
    with task_context(str(bob.id), "t-b"):
        opened = await call_tool("browser_open", {"url": origin})
        assert opened.ok
        assert "Welcome back" not in opened.data
        assert "Sign in" in opened.data  # the login form
        assert "<input type=password>" in opened.data


async def test_profile_dirs_are_distinct_on_disk(pro_users, browser_env, chromium, login_site):
    alice, bob = pro_users
    with task_context(str(alice.id), "t-a"):
        await call_tool("browser_open", {"url": login_site.origin})
    with task_context(str(bob.id), "t-b"):
        await call_tool("browser_open", {"url": login_site.origin})

    root = tbrowser.profile_root()
    assert (root / str(alice.id) / "default").exists()
    assert (root / str(bob.id) / "default").exists()
    # Each profile belongs to exactly one tenant prefix:
    assert str(root / str(alice.id)) not in str(root / str(bob.id))


async def test_free_tier_cannot_reach_browser_tools(users_a_b):
    """Plan floor: browser tools aren't available below the tier that pays
    for them (approvals denies; export_for_sdk omits them)."""
    from core.approvals import check
    from tools.base import registry

    alice, _ = users_a_b  # free tier
    decision = await check(alice.id, "browser_open", {"url": "https://example.com"},
                           "moderate", task_source="user")
    assert decision.action == "deny"

    exported = registry.export_for_sdk("free", "user")
    assert all(not t["name"].startswith("browser_") for t in exported)


async def test_job_sourced_browser_use_requires_approval(pro_users):
    """Autonomous mode floor: browser tools are moderate ⇒ approval, even
    though the user's own rules would auto-log interactive use."""
    from core.approvals import check

    alice, _ = pro_users
    interactive = await check(alice.id, "browser_open", {"url": "https://example.com"},
                              "moderate", task_source="user")
    autonomous = await check(alice.id, "browser_open", {"url": "https://example.com"},
                             "moderate", task_source="job")
    assert interactive.action == "auto_and_log"
    assert autonomous.action == "require_approval"
