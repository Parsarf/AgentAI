"""Shared fixtures: disposable test database, pool per test, user factory.
Phase 3 adds: pro-plan users, isolated skills root, fake sandbox execution
(no Docker), a per-test scheduler service, and event loggers."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

import asyncpg
import pytest
import pytest_asyncio

# Importing registers the @tool specs in the global registry (production
# does this via auto_discover()).
import tools.browser  # noqa: F401
import tools.credentials  # noqa: F401
import tools.scheduler  # noqa: F401
import tools.skills_tools  # noqa: F401

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://agent_test_runner@localhost:5432/agent_test"
)

# Make the agent/ package importable regardless of pytest invocation dir.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402


def _check_disposable_dsn(dsn: str) -> None:
    """Refuse schema-reset tests unless the target is a separate test DB."""
    from core.config import settings

    target = urlparse(dsn)
    app = urlparse(settings.secrets.database_url)
    database = unquote(target.path.lstrip("/"))
    app_database = unquote(app.path.lstrip("/"))
    if (target.scheme not in ("postgres", "postgresql") or not target.hostname
            or not target.username or target.query or target.fragment
            or "/" in database or not database.endswith("_test")):
        raise RuntimeError("TEST_DATABASE_URL must target a dedicated *_test database")
    if database == app_database or target.username == app.username:
        raise RuntimeError("test database and role must differ from the application")
    def location(parsed):
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1"):
            host = "loopback"
        return host, parsed.port or 5432, parsed.path.lstrip("/")
    if location(target) == location(app):
        raise RuntimeError("TEST_DATABASE_URL resolves to the application database")


def _check_disposable_connection(dsn: str) -> None:
    async def _check() -> None:
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                """SELECT current_database() AS database, current_user AS role,
                          r.rolsuper, r.rolcreatedb
                   FROM pg_roles r WHERE r.rolname=current_user"""
            )
            parsed = urlparse(dsn)
            if (row is None or row["database"] != unquote(parsed.path.lstrip("/"))
                    or row["role"] != unquote(parsed.username or "")
                    or row["rolsuper"] or row["rolcreatedb"]):
                raise RuntimeError("test connection must use its own non-superuser, non-createdb role")
            owner = await conn.fetchval(
                "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='test_run'"
            )
            if owner != row["role"]:
                raise RuntimeError("test_run schema must exist and belong to the test role")
            search_path = await conn.fetchval("SELECT current_schema()")
            if search_path != "test_run":
                raise RuntimeError("test role search_path must start with test_run")
        finally:
            await conn.close()

    asyncio.run(_check())


def _reset_schema(dsn: str) -> None:
    async def _reset() -> None:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("DROP SCHEMA test_run CASCADE; CREATE SCHEMA test_run;")
        finally:
            await conn.close()

    asyncio.run(_reset())


def _migrate(dsn: str) -> None:
    asyncio.run(db.apply_migrations(dsn))


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """One schema reset + migration pass per pytest session."""
    _check_disposable_dsn(TEST_DATABASE_URL)
    _check_disposable_connection(TEST_DATABASE_URL)
    _reset_schema(TEST_DATABASE_URL)
    _migrate(TEST_DATABASE_URL)
    yield


@pytest_asyncio.fixture
async def db_pool(_test_database):
    """A fresh pool per test (bound to the test's event loop), closed after.
    Tenant tables are truncated so tests never see each other's rows."""
    await db.open_pool(TEST_DATABASE_URL, force=True)
    await db._require_pool().execute("TRUNCATE users CASCADE")
    yield db
    await db.close_pool()


async def _make_user(email: str, password: str = "correct horse battery") -> db.User:
    from core import auth

    return await db.create_user(
        email, password_hash=auth._hash_password(password), status="active"
    )


@pytest_asyncio.fixture
async def users_a_b(db_pool):
    """Two activated users, alice and bob — the tenancy test cast."""
    alice = await _make_user("alice@example.com")
    bob = await _make_user("bob@example.com")
    return alice, bob


# --------------------------------------------------------------------------- #
# Phase 3 — scheduling & skills
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def p3_isolation(monkeypatch, tmp_path):
    """Fresh event bus per test + skills root pointed at a temp dir (never
    the repo's real skills/)."""
    from core import events, skills

    events.clear_all()
    monkeypatch.setattr(skills, "SKILLS_ROOT", tmp_path / "skills")
    yield
    events.clear_all()


@pytest_asyncio.fixture
async def pro_users(users_a_b):
    """alice + bob on the 'pro' plan (autonomous jobs enabled, cap 20)."""
    alice, bob = users_a_b
    for u in (alice, bob):
        await db.update_user(u.id, plan_tier="pro")
    return alice, bob


@dataclass
class FakeSandbox:
    """Records service/tool sandbox usage; stands in for Docker."""

    calls: list[dict] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    script_outputs: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    fail_task_ids: set[str] = field(default_factory=set)

    def output_for(self, task_id: str) -> tuple[int, str, str]:
        if task_id in self.fail_task_ids:
            return 1, "", "boomed (exit 1)"
        return self.script_outputs.get(task_id, (0, "default-output", ""))


@pytest.fixture
def fake_sandbox(monkeypatch, tmp_path):
    """Patch sandbox lifecycle + run_files with an in-memory fake."""
    from tools import sandbox

    fake = FakeSandbox()

    async def fake_start(user_id: str, task_id: str):
        fake.started.append(task_id)
        ws = tmp_path / "sandboxes" / str(user_id) / str(task_id)
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    async def fake_stop(task_id: str) -> None:
        fake.stopped.append(task_id)

    async def fake_run_files(task_id, files, entry, argv=None, timeout=None):
        fake.calls.append(
            {"task_id": str(task_id), "files": dict(files), "entry": entry, "argv": list(argv or [])}
        )
        return fake.output_for(str(task_id))

    monkeypatch.setattr(sandbox, "start_task_sandbox", fake_start)
    monkeypatch.setattr(sandbox, "stop_task_sandbox", fake_stop)
    monkeypatch.setattr(sandbox, "run_files", fake_run_files)
    return fake


@pytest_asyncio.fixture
async def scheduler():
    """A fresh SchedulerService wired to the per-test-cleaned event bus."""
    from core.scheduler_service import SchedulerService

    svc = SchedulerService()
    svc.start()
    yield svc
    await svc.stop()


@pytest_asyncio.fixture
async def fired():
    """Records job.fired events."""
    from core import events

    log: list[dict] = []

    async def _rec(payload: dict) -> None:
        log.append(payload)

    await events.subscribe(events.JOB_FIRED, _rec)
    yield log
    await events.unsubscribe(events.JOB_FIRED, _rec)


@pytest_asyncio.fixture
async def notify_log():
    """Records notify.user deliveries (for the owner-only audit)."""
    from core import events

    log: list[dict] = []

    async def _rec(payload: dict) -> None:
        log.append(payload)

    await events.subscribe(events.NOTIFY_USER, _rec)
    yield log
    await events.unsubscribe(events.NOTIFY_USER, _rec)


# --------------------------------------------------------------------------- #
# Phase 4 — browser + vault
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def chromium():
    """Skip cleanly when Playwright/Chromium isn't usable on this machine."""
    import contextlib

    try:
        from playwright.async_api import async_playwright
    except Exception:
        pytest.skip("playwright is not installed")
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
    except Exception:
        with contextlib.suppress(Exception):
            await pw.stop()
        pytest.skip("chromium browser is not installed (playwright install chromium)")
    await browser.close()
    await pw.stop()
    yield


@pytest_asyncio.fixture
async def browser_env(monkeypatch, tmp_path):
    """Local-mode browser with a per-test profile root (dev/test only mode).
    Pair with the ``chromium`` fixture when the test drives a real page."""
    from core.config import settings
    from tools import browser as tbrowser

    monkeypatch.setattr(settings.browser, "local_mode", True)
    monkeypatch.setattr(settings.browser, "profile_root", str(tmp_path / "profiles"))
    yield tbrowser
    for session in list(tbrowser._sessions.values()):
        await session.close()
    tbrowser._sessions.clear()
    tbrowser._events_wired = False
    await tbrowser.stop_playwright()


@pytest.fixture
def login_site():
    from tests.browser_site import LoginSite

    site = LoginSite().start()
    yield site
    site.stop()
