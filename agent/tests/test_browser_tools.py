"""Browser tools against the local test site: snapshot numbering, acting by
ref, the secret-typing path, and login success/failure."""

from __future__ import annotations

import json
import re

from core import secrets_vault as sv
from tests.browser_site import PASSWORD, USERNAME
from tests.p2_conftest import task_context
from tools.base import call_tool


def _ref_for(snapshot: str, pattern: str) -> str:
    """Find the [ref] of the first snapshot line containing `pattern`."""
    for line in snapshot.splitlines():
        if pattern in line:
            m = re.match(r"\[(\d+)\]", line)
            if m:
                return m.group(1)
    raise AssertionError(f"no ref for {pattern!r} in snapshot:\n{snapshot}")


async def test_open_snapshot_and_act_by_ref(pro_users, browser_env, login_site):
    alice, _ = pro_users
    with task_context(str(alice.id), "t-a"):
        opened = await call_tool("browser_open", {"url": login_site.origin})
        assert opened.ok, opened.error
        snapshot = opened.data
        assert "Sign in" in snapshot
        assert "<input type=password>" in snapshot

        user_ref = _ref_for(snapshot, "<input type=text>")
        submit_ref = _ref_for(snapshot, "<button")

        typed = await call_tool("browser_type", {"ref": user_ref, "text": USERNAME})
        assert typed.ok, typed.error
        # The typed NON-secret value is fine to show; the point is refs work.
        clicked = await call_tool("browser_click", {"ref": submit_ref})
        # Submitting without a password re-shows the form (with error text).
        assert clicked.ok
        assert "Bad credentials" in clicked.data or "Sign in" in clicked.data


async def test_login_success_via_secret_path(pro_users, browser_env, login_site):
    alice, _ = pro_users
    origin = login_site.origin
    await sv.store_credential(
        str(alice.id), origin,
        json.dumps({"username": USERNAME, "password": PASSWORD}),
    )

    with task_context(str(alice.id), "t-a"):
        result = await call_tool("browser_login", {"site": origin})
    assert result.ok, result.error
    assert "Welcome back" in result.data  # post-login snapshot
    assert PASSWORD not in result.data    # secret never in the output


async def test_browser_type_secret_flag_fills_without_showing(pro_users, browser_env, login_site):
    alice, _ = pro_users
    origin = login_site.origin
    await sv.store_credential(
        str(alice.id), origin,
        json.dumps({"username": USERNAME, "password": PASSWORD}),
    )

    with task_context(str(alice.id), "t-a"):
        opened = await call_tool("browser_open", {"url": origin})
        snapshot = opened.data
        pass_ref = _ref_for(snapshot, "<input type=password>")
        typed = await call_tool(
            "browser_type", {"ref": pass_ref, "text": origin, "secret": True}
        )
        assert typed.ok, typed.error
        assert PASSWORD not in typed.data

        user_ref = _ref_for(typed.data, "<input type=text>")
        await call_tool("browser_type", {"ref": user_ref, "text": USERNAME})
        submit_ref = _ref_for(typed.data, "<button")
        clicked = await call_tool("browser_click", {"ref": submit_ref})
        assert "Welcome back" in clicked.data


async def test_login_failure_reports_without_values(pro_users, browser_env, login_site):
    alice, _ = pro_users
    origin = login_site.origin
    await sv.store_credential(
        str(alice.id), origin,
        json.dumps({"username": USERNAME, "password": "definitely-wrong-pw"}),
    )

    with task_context(str(alice.id), "t-a"):
        result = await call_tool("browser_login", {"site": origin})
    assert not result.ok
    assert "login failed" in result.error
    assert "definitely-wrong-pw" not in result.error  # never echo values


async def test_login_without_stored_credential_refused(pro_users, browser_env, login_site):
    alice, _ = pro_users
    with task_context(str(alice.id), "t-a"):
        result = await call_tool("browser_login", {"site": login_site.origin})
    assert not result.ok
    assert "no stored credential" in result.error


async def test_scroll_and_back_smoke(pro_users, browser_env, login_site):
    alice, _ = pro_users
    with task_context(str(alice.id), "t-a"):
        opened = await call_tool("browser_open", {"url": login_site.origin})
        assert opened.ok
        down = await call_tool("browser_scroll", {"direction": "down"})
        assert down.ok and "Sign in" in down.data
        up = await call_tool("browser_scroll", {"direction": "up"})
        assert up.ok
        # Navigate away, then back returns to the site.
        await call_tool("browser_open", {"url": "about:blank"})
        back = await call_tool("browser_back", {})
        assert back.ok and "127.0.0.1" in back.data


async def test_list_available_accounts_lists_own_sites(pro_users, browser_env, login_site):
    alice, bob = pro_users
    await sv.store_credential(str(alice.id), "only-alice.example", "v")
    with task_context(str(alice.id), "t-a"):
        mine = await call_tool("list_available_accounts", {})
        assert mine.ok and "only-alice.example" in mine.data
    with task_context(str(bob.id), "t-b"):
        theirs = await call_tool("list_available_accounts", {})
        assert theirs.data == []
