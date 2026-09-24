"""Account linking: single-use, expiring codes; chat re-linking; plus a web
app flow test driven over ASGI (same event loop as the pool, no portal)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from core import db
from gateway import account_linking


async def test_code_single_use_and_expiring(users_a_b):
    alice, bob = users_a_b
    code = await account_linking.generate_link_code(alice.id)

    linked = await account_linking.redeem_link_code(code, "555000111")
    assert linked == str(alice.id)
    assert await account_linking.user_for_chat("555000111") == str(alice.id)

    # Replay refused:
    with pytest.raises(ValueError, match="invalid or expired"):
        await account_linking.redeem_link_code(code, "555000222")

    # Forged/garbage refused with the SAME message (no existence leak):
    with pytest.raises(ValueError, match="invalid or expired"):
        await account_linking.redeem_link_code("AAAAAAAA", "555000333")

    # A chat can be re-linked to a different account (single chat, one owner):
    code2 = await account_linking.generate_link_code(bob.id)
    await account_linking.redeem_link_code(code2, "555000111")
    assert await account_linking.user_for_chat("555000111") == str(bob.id)


async def test_expired_code_rejected(users_a_b):
    import hashlib

    alice, _ = users_a_b
    code_hash = hashlib.sha256(b"OLDCODE1").hexdigest()
    past = datetime.now(UTC) - timedelta(minutes=1)
    await db.create_link_code(code_hash, alice.id, past)
    with pytest.raises(ValueError, match="invalid or expired"):
        await account_linking.redeem_link_code("OLDCODE1", "777")


async def test_web_signup_verify_login_submit(db_pool, monkeypatch):
    """Full web flow over ASGITransport: signup → verify → login → CSRF'd task."""
    from core import events
    from gateway.web_app import app

    captured_email: list[dict] = []
    published: list[tuple[str, dict]] = []

    async def fake_send(to, subject, html):
        captured_email.append({"to": to, "subject": subject, "html": html})

    async def fake_publish(event_name, payload):
        published.append((event_name, payload))

    monkeypatch.setattr(auth_module(), "_send_email", fake_send)
    monkeypatch.setattr(events, "publish", fake_publish)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        # signup
        r = await client.post(
            "/signup",
            data={"email": "webuser@example.com", "password": "long enough password 1"},
        )
        assert r.status_code == 200

        # verify (token arrives in the captured email)
        token = captured_email[0]["html"].split("token=")[1].split('"')[0]
        r = await client.get(f"/verify?token={token}")
        assert r.status_code == 200

        # login sets the session cookie
        r = await client.post(
            "/login",
            data={"email": "webuser@example.com", "password": "long enough password 1"},
        )
        assert r.status_code == 303 and r.headers["location"] == "/chat"

        # CSRF from a page, then submit a task
        page = (await client.get("/chat")).text
        csrf = page.split('name="csrf" value="')[1].split('"')[0]
        r = await client.post("/tasks", data={"request_text": "hello from the web", "csrf": csrf})
        assert r.status_code == 303 and "/tasks/" in r.headers["location"]

        # the task was published for THIS user only
        task_events = [p for name, p in published if name == events.TASK_REQUESTED]
        assert len(task_events) == 1
        user = await db.get_user_by_email("webuser@example.com")
        assert task_events[0]["user_id"] == str(user.id)
        tasks = await db.list_tasks(user.id)
        assert len(tasks) == 1 and tasks[0].request == "hello from the web"

        # wrong CSRF refused
        r = await client.post("/tasks", data={"request_text": "x", "csrf": "bad"})
        assert r.status_code == 403

        # another user cannot see the first user's task page
        r = await client.post(
            "/signup", data={"email": "intruder@example.com", "password": "long enough password 1"}
        )
        token2 = captured_email[-1]["html"].split("token=")[1].split('"')[0]
        await client.get(f"/verify?token={token2}")
        await client.post(
            "/login", data={"email": "intruder@example.com", "password": "long enough password 1"}
        )
        r = await client.get(f"/tasks/{tasks[0].id}")
        assert r.status_code == 404


def auth_module():
    from core import auth

    return auth
