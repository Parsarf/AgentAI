"""Phase 3 e2e: two users each create a recurring job + a watcher through
the real tools; a simulated clock advances; each user gets exactly their own
firings; watchers stay quiet until their check output changes. Also: plan
floors (free tier) and create_job validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core import db, skills
from tests.p2_conftest import task_context
from tools.base import call_tool


async def test_free_tier_cannot_create_jobs(users_a_b):  # noqa: F811
    alice, _ = users_a_b  # free tier: autonomous_jobs off, max_active_jobs 0
    with task_context(str(alice.id), "t-free"):
        result = await call_tool(
            "create_job", {"kind": "recurring", "schedule": "*/5 * * * *",
                           "instruction": "should be refused"}
        )
    assert not result.ok
    assert "not enabled" in result.error


async def test_create_job_validation(pro_users):  # noqa: F811
    alice, _ = pro_users
    with task_context(str(alice.id), "t-val"):
        cases = [
            ({"kind": "recurring", "schedule": "bogus", "instruction": "x"}, "cron"),
            ({"kind": "recurring", "schedule": "*/5 * * * *", "instruction": ""}, "instruction"),
            ({"kind": "watcher", "schedule": "*/5 * * * *", "instruction": "x",
              "check_mode": "on_change"}, "check_script"),
            ({"kind": "watcher", "schedule": "*/5 * * * *", "instruction": "x"}, "on_change"),
            ({"kind": "recurring", "schedule": "*/5 * * * *", "instruction": "x",
              "check_script": "print(1)"}, "recurring"),
        ]
        for args, needle in cases:
            result = await call_tool("create_job", args)
            assert not result.ok, f"expected refusal: {args}"
            assert needle in result.error
    assert await db.list_jobs(alice.id) == []


async def test_two_users_a_day_of_jobs_produce_only_their_own_firings(
    pro_users, scheduler, fired, fake_sandbox  # noqa: F811
):
    alice, bob = pro_users
    job_ids: dict[str, str] = {}

    # Each user creates a recurring job and a watcher via the real tools.
    for user, tag in ((alice, "alice"), (bob, "bob")):
        with task_context(str(user.id), f"task-{tag}"):
            recurring = await call_tool(
                "create_job",
                {"kind": "recurring", "schedule": "* * * * *",
                 "instruction": f"{tag}: hourly digest"},
            )
            watcher = await call_tool(
                "create_job",
                {"kind": "watcher", "schedule": "* * * * *",
                 "instruction": f"{tag}: watch the feed",
                 "check_mode": "on_change",
                 "check_script": f"print('sig-{tag}')"},
            )
        assert recurring.ok and watcher.ok, (recurring.error, watcher.error)
        job_ids[recurring.data["job_id"]] = f"{tag}: hourly digest"
        job_ids[watcher.data["job_id"]] = f"{tag}: watch the feed"
        fake_sandbox.script_outputs[f"check-{watcher.data['job_id']}"] = (0, f"sig-{tag}", "")

    # Simulated clock jumps a day in one hop.
    t1 = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=1)
    await scheduler.tick(t1)
    await scheduler.drain()

    # Exactly 2 firings per user: 1 recurring (catch-up collapses the ~1440
    # missed minutes into one) + 1 watcher (first baseline observation).
    by_user: dict[str, list[dict]] = {str(alice.id): [], str(bob.id): []}
    for p in fired:
        by_user[p["user_id"]].append(p)
    assert {uid: len(ps) for uid, ps in by_user.items()} == {
        str(alice.id): 2, str(bob.id): 2,
    }
    for uid, ps in by_user.items():
        expected_tag = "alice" if uid == str(alice.id) else "bob"
        kinds = sorted(p["kind"] for p in ps)
        assert kinds == ["recurring", "watcher"]
        for p in ps:
            assert job_ids[p["job_id"]].startswith(expected_tag)  # never the other's
        watcher_fire = next(p for p in ps if p["kind"] == "watcher")
        assert watcher_fire["check_output"] == f"sig-{expected_tag}"

    # A minute later: recurring fires again (2×); watchers stay quiet.
    t2 = t1 + timedelta(minutes=1)
    await scheduler.tick(t2)
    await scheduler.drain()
    assert len(fired) == 6  # 4 + one more recurring per user

    # Bob's feed changes → only Bob's watcher escalates (the recurring jobs
    # also fire on their own cadence, hence +2 recurring +1 watcher).
    bob_watcher_id = next(
        jid for jid, instr in job_ids.items() if instr == "bob: watch the feed"
    )
    alice_watcher_id = next(
        jid for jid, instr in job_ids.items() if instr == "alice: watch the feed"
    )
    fake_sandbox.script_outputs[f"check-{bob_watcher_id}"] = (0, "sig-bob-CHANGED", "")
    await scheduler.tick(t2 + timedelta(minutes=1))
    await scheduler.drain()
    assert len(fired) == 9
    bob_watcher_fires = [p for p in fired if p["job_id"] == bob_watcher_id
                         and p["kind"] == "watcher"]
    assert len(bob_watcher_fires) == 2
    assert bob_watcher_fires[-1]["check_output"] == "sig-bob-CHANGED"
    # Alice's watcher only ever fired once (its baseline) — quiet ever since.
    assert len([p for p in fired if p["job_id"] == alice_watcher_id
                and p["kind"] == "watcher"]) == 1

    # Alice's recurring job only ever fired for Alice, never for Bob.
    alice_recurring_id = next(
        jid for jid, instr in job_ids.items() if instr == "alice: hourly digest"
    )
    owners = {p["user_id"] for p in fired if p["job_id"] == alice_recurring_id}
    assert owners == {str(alice.id)}


async def test_settings_page_jobs_and_skills_routes(pro_users):
    """The dashboard shows the user's own jobs/skills; pause/delete work and
    never touch another user's job."""
    import httpx

    from gateway.web_app import app

    alice, bob = pro_users
    job_a = await db.create_job(
        alice.id, "recurring", "* * * * *", "always", "alice web job",
        next_run_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await db.create_job(
        bob.id, "recurring", "* * * * *", "always", "bob web job",
        next_run_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await skills.save_skill(
        str(alice.id), "webtool", "made via web test",
        {"type": "object"}, "safe", {"instructions.md": "do the thing"},
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        r = await client.post(
            "/login", data={"email": "alice@example.com", "password": "correct horse battery"}
        )
        assert r.status_code == 303
        page = (await client.get("/settings")).text
        assert "alice web job" in page
        assert "webtool" in page
        assert "bob web job" not in page  # other users' jobs invisible
        csrf = page.split('name="csrf" value="')[1].split('"')[0]

        # Pause then delete alice's own job.
        r = await client.post(f"/settings/jobs/{job_a.id}/pause", data={"csrf": csrf})
        assert r.status_code == 303
        assert (await db.get_job(alice.id, job_a.id)).active is False
        r = await client.post(f"/settings/jobs/{job_a.id}/delete", data={"csrf": csrf})
        assert r.status_code == 303
        assert await db.get_job(alice.id, job_a.id) is None

        # Bob's job id is a 404 for alice (existence never leaked either way).
        bob_job = (await db.list_jobs(bob.id))[0]
        r = await client.post(f"/settings/jobs/{bob_job.id}/pause", data={"csrf": csrf})
        assert r.status_code == 404
        assert (await db.get_job(bob.id, bob_job.id)).active is True
