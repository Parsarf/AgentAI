"""Event bus: user_id enforcement, subscriber isolation, wait_for."""

from __future__ import annotations

import asyncio

import pytest

from core import events


@pytest.fixture(autouse=True)
def _clean_bus():
    events.clear_all()
    yield
    events.clear_all()


async def test_user_scoped_events_require_user_id():
    with pytest.raises(ValueError, match="user_id"):
        await events.publish(events.TASK_FINISHED, {"task_id": "t1"})
    # system.stop is NOT user-scoped:
    await events.publish(events.SYSTEM_STOP, {})


async def test_subscribers_only_react_to_their_own_user():
    got_alice, got_bob = [], []

    async def alice_handler(p):
        if p["user_id"] == "u-alice":  # predicate lives with the subscriber,
            got_alice.append(p)        # mirroring what gateways do

    async def bob_handler(p):
        if p["user_id"] == "u-bob":
            got_bob.append(p)

    await events.subscribe(events.NOTIFY_USER, alice_handler)
    await events.subscribe(events.NOTIFY_USER, bob_handler)

    await asyncio.gather(
        events.publish(events.NOTIFY_USER, {"user_id": "u-alice", "message": "hi a"}),
        events.publish(events.NOTIFY_USER, {"user_id": "u-bob", "message": "hi b"}),
    )

    assert [p["user_id"] for p in got_alice] == ["u-alice"]
    assert [p["user_id"] for p in got_bob] == ["u-bob"]


async def test_broken_handler_does_not_crash_others():
    seen = []

    async def good_before(p):
        seen.append("before")

    async def broken(p):
        raise RuntimeError("boom")

    async def good_after(p):
        seen.append("after")

    await events.subscribe(events.JOB_FIRED, good_before)
    await events.subscribe(events.JOB_FIRED, broken)
    await events.subscribe(events.JOB_FIRED, good_after)

    await events.publish(events.JOB_FIRED, {"user_id": "u1"})
    assert seen == ["before", "after"]


async def test_wait_for_returns_matching_payload():
    async def replier():
        await asyncio.sleep(0.01)
        await events.publish(
            events.APPROVAL_DECIDED, {"user_id": "u1", "approval_id": "a1", "approved": True}
        )

    asyncio.get_running_loop().create_task(replier())
    payload = await events.wait_for(
        events.APPROVAL_DECIDED,
        lambda p: p["user_id"] == "u1" and p["approval_id"] == "a1",
        timeout=2,
    )
    assert payload is not None and payload["approved"] is True


async def test_wait_for_ignores_other_users_and_times_out():
    async def wrong_user():
        await asyncio.sleep(0.01)
        await events.publish(events.APPROVAL_DECIDED, {"user_id": "someone-else"})

    asyncio.get_running_loop().create_task(wrong_user())
    payload = await events.wait_for(
        events.APPROVAL_DECIDED, lambda p: p["user_id"] == "u1", timeout=0.05
    )
    assert payload is None
