"""Phase 1 smoke test — the "done when" scenario, end to end, in one run.

Defaults to the TEST database (TEST_DATABASE_URL, default
postgresql://agent@localhost:5432/agent_test) and wipes its schema.
It refuses to run against DATABASE_URL unless --i-know-this-wipes is passed.

Usage:  python scripts/smoke_phase1.py [--i-know-this-wipes]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import auth, db  # noqa: E402
from core.config import settings  # noqa: E402
from core.events import clear_all, publish, subscribe  # noqa: E402
from core.logging import _redact, register_secret  # noqa: E402

results: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    results.append((bool(condition), label))
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")


async def main(dsn: str) -> bool:
    print(f"smoke_phase1 against {dsn}\n")

    # -- reset the disposable test schema, then migrate ------------------------
    print("migrations:")
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await conn.close()
    applied = await db.apply_migrations(dsn)
    check(len(applied) >= 1, f"applied {len(applied)} migration(s): {applied}")
    again = await db.apply_migrations(dsn)
    check(again == [], "re-run applies nothing (idempotent)")
    await db.open_pool(dsn)

    # -- two users, tenant isolation ----------------------------------------
    print("tenancy:")
    alice = await db.create_user("smoke-alice@example.com", "x" * 60, None, status="active")
    bob = await db.create_user("smoke-bob@example.com", "y" * 60, None, status="active")
    a_task = await db.create_task(alice.id, "alice task", source="user")
    await db.create_task(bob.id, "bob task", source="user")
    check(await db.get_task(bob.id, a_task.id) is None, "bob cannot read alice's task")
    check(
        await db.update_task(bob.id, a_task.id, status="done") is None,
        "bob cannot update alice's task",
    )
    check((await db.get_task(alice.id, a_task.id)).status == "pending", "alice's task unchanged")
    bob_by_email = await db.get_user_by_email("smoke-bob@example.com")
    check(bob_by_email is not None and bob_by_email.id == bob.id, "lookup by email works")

    embedding = [0.2] * settings.embeddings.dimensions
    await db.add_memory(alice.id, "alice secret fact", "general", embedding, 0.9)
    await db.add_memory(bob.id, "bob secret fact", "general", embedding, 0.9)
    a_recall = await db.search_memories(alice.id, embedding, limit=10)
    check(all(m.user_id == alice.id for m in a_recall) and len(a_recall) == 1,
          "memory search returns only the caller's rows")

    # -- events ---------------------------------------------------------------
    print("events:")
    seen: list[str] = []
    await subscribe("notify.user", lambda p: _collect(seen, p, "alice"))
    await publish("notify.user", {"user_id": str(alice.id), "message": "hi"})
    try:
        await publish("notify.user", {"message": "missing user"})
        check(False, "user-scoped event without user_id rejected")
    except ValueError:
        check(True, "user-scoped event without user_id rejected")
    check(seen == ["alice"], "subscriber only saw its own user's event")
    clear_all()

    # -- logging redaction ----------------------------------------------------
    print("logging:")
    register_secret("smoke-secret-value-xyz")

    check("[REDACTED]" in _redact("contains smoke-secret-value-xyz here"),
          "registered secret redacted in log output")

    # -- auth flow (email mocked) ---------------------------------------------
    print("auth:")
    sent: list[dict] = []

    async def fake_send(to, subject, html):
        sent.append({"to": to, "subject": subject, "html": html})

    auth._send_email = fake_send  # type: ignore[method-assign]

    user = await auth.signup("smoke-carol@example.com", "long enough password 1")
    check(user.status == "email_unverified", "signup starts unverified")
    try:
        await auth.login("smoke-carol@example.com", "long enough password 1")
        check(False, "login blocked before verification")
    except auth.AuthError:
        check(True, "login blocked before verification")

    html = next(m["html"] for m in sent if m["subject"] == "Verify your account")
    token = re.search(r"token=([A-Za-z0-9_.\-]+)", html).group(1)
    check((await auth.verify_email(token)).status == "active", "verification activates account")
    try:
        await auth.verify_email(token)
        check(False, "verification link single-use")
    except auth.AuthError:
        check(True, "verification link single-use")

    login = await auth.login("smoke-carol@example.com", "long enough password 1")
    check(str(login.user_id) == str(user.id), "login resolves to the right user")
    check(await auth.verify_session(login.token) == user.id, "session resolves")
    check(await auth.verify_session("forged-garbage") is None, "forged session rejected")

    await auth.request_password_reset("smoke-carol@example.com")
    reset_html = next(m["html"] for m in sent if m["subject"] == "Reset your password")
    reset_token = re.search(r"token=([A-Za-z0-9_.\-]+)", reset_html).group(1)
    await auth.reset_password(reset_token, "brand new password 99")
    check(await auth.verify_session(login.token) is None, "reset invalidates old sessions")
    check((await auth.login("smoke-carol@example.com", "brand new password 99")).user_id == user.id,
          "new password works")

    await db.close_pool()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return passed == len(results)


async def _collect(store: list, payload: dict, tag: str) -> None:
    store.append(tag)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--i-know-this-wipes", action="store_true",
        help="run against DATABASE_URL, wiping its schema (destructive!)",
    )
    args = parser.parse_args()

    test_dsn = os.environ.get("TEST_DATABASE_URL", "postgresql://agent@localhost:5432/agent_test")
    if args.i_know_this_wipes:
        dsn = settings.secrets.database_url
        print("WARNING: wiping the real DATABASE_URL schema\n")
    else:
        dsn = test_dsn

    ok = asyncio.run(main(dsn))
    sys.exit(0 if ok else 1)
