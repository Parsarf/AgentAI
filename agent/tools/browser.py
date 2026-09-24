"""Real websites for the acting user — per-user sessions, secrets never shown.

Tenancy & isolation:
- Persistent Playwright profile per USER (and named profile): the profile dir
  is derived ONLY from the acting user id (same validator rules as sandbox
  workspaces: charset-validated ids, prefix confinement, realpath check), so
  one user's logged-in sessions can never appear in another user's context.
- Container mode (production): chromium runs in a per-user container on that
  user's own Docker network (Phase 2 isolation applies wholesale); the app
  drives it over CDP. Requires the playwright-enabled image
  (see sandbox/Dockerfile.playwright).
- Local mode (``browser.local_mode``, dev/tests ONLY, default off): a local
  chromium with the same per-user profile dirs. No host network isolation —
  never enable in production.

View model: text snapshots (visible text + numbered interactive elements,
``[12] <a> "Pricing"``). The model acts by ref. Page content is ALWAYS
returned wrapped as external content — it is data, never instructions.
Secrets (``browser_type(..., secret=True)``, ``browser_login``) are fetched
from the vault internally and typed via a path that never appears in
snapshots, tool results, or logs.

Lifecycle: sessions are refcounted per (user, profile, task) and closed when
the last using task finishes (``task.finished``); profiles persist — that is
the point.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from core import events
from core.config import settings
from core.logging import get_logger
from tools import sandbox
from tools.base import ExternalContent, ToolResult, current_task_id, current_user_id, tool

logger = get_logger(__name__)

_PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ELEMENTS_CSS = "a, button, input, select, textarea, [role=button], [onclick]"

_sessions: dict[str, BrowserSession] = {}
_events_wired = False


class BrowserUnavailable(Exception):
    """No usable browser backend — the tool surfaces an actionable message."""


def profile_root() -> Path:
    root = Path(settings.browser.profile_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def profile_dir(user_id: str, profile: str = "default") -> Path:
    """The ONLY way a profile path is ever constructed (sandbox rules)."""
    uid = sandbox.validate_id(user_id, "user")
    prof = profile if _PROFILE_RE.match(profile or "") else "default"
    path = (profile_root() / uid / prof).resolve()
    if not str(path).startswith(str(profile_root()) + os.sep):
        raise ValueError("profile path escaped the profiles root")
    path.mkdir(parents=True, exist_ok=True)
    real = Path(os.path.realpath(path))
    if not str(real).startswith(str(profile_root()) + os.sep):
        raise ValueError("symlink escape detected in profile path")
    return real


# --------------------------------------------------------------------------- #
# Sessions (context per user+profile; refcounted per task)
# --------------------------------------------------------------------------- #


class BrowserSession:
    def __init__(self, key: str, context: Any, container: Any = None) -> None:
        self.key = key
        self.context = context
        self.container = container  # Docker container in CDP mode
        self.page: Any = None
        self.refs: list[str] = []  # ref number -> element index within _ELEMENTS_CSS
        self.lock = asyncio.Lock()
        self.tasks: set[str] = set()

    async def current_page(self) -> Any:
        if self.page is None:
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        return self.page

    async def close(self) -> None:
        try:
            if self.context is not None:
                await self.context.close()
        except Exception:
            logger.exception("browser context close failed", extra={"session": self.key})
        if self.container is not None:
            def _rm():
                with contextlib.suppress(Exception):
                    self.container.remove(force=True)

            await asyncio.to_thread(_rm)
        _sessions.pop(self.key, None)


_pw: Any = None


async def _local_context(profile_path: Path) -> Any:
    global _pw
    if _pw is None:
        try:
            from playwright.async_api import async_playwright

            _pw = await async_playwright().start()
        except Exception as exc:
            raise BrowserUnavailable(
                "Playwright is not available: pip install playwright && "
                "playwright install chromium"
            ) from exc
    try:
        return await _pw.chromium.launch_persistent_context(
            str(profile_path), headless=settings.browser.headless
        )
    except Exception as exc:
        raise BrowserUnavailable(
            f"chromium could not start ({exc}). Run: playwright install chromium"
        ) from exc


async def _container_context(user_id: str, profile: str, profile_path: Path):
    """Launch the user's own playwright container and attach over CDP."""
    def _start():
        client = sandbox._client()
        network = sandbox._ensure_user_network(user_id)
        name = f"brw_{sandbox.validate_id(user_id, 'user')}_{profile}"
        try:
            old = client.containers.get(name)
            old.remove(force=True)
        except Exception:
            pass
        return client.containers.run(
            "agent-browser:latest",
            name=name,
            detach=True,
            network=network.name,
            volumes={str(profile_path): {"bind": "/data/profile", "mode": "rw"}},
            command=(
                "chromium --headless=new --no-sandbox --remote-debugging-address=0.0.0.0 "
                "--remote-debugging-port=9222 --user-data-dir=/data/profile"
            ),
            labels={"tenant": user_id, "browser": profile},
        )

    try:
        container = await asyncio.to_thread(_start)
    except sandbox.SandboxUnavailable:
        raise
    except Exception as exc:
        raise BrowserUnavailable(
            f"browser container failed to start ({exc}). Build it: "
            "docker build -t agent-browser:latest -f sandbox/Dockerfile.playwright ."
        ) from exc

    def _ip():
        network = sandbox._user_network_name(user_id)
        return container.attrs["NetworkSettings"]["Networks"][network]["IPAddress"]

    ip = await asyncio.to_thread(_ip)
    deadline = time.monotonic() + 15
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            browser = await _pw.chromium.connect_over_cdp(f"http://{ip}:9222")
            return browser.contexts[0] if browser.contexts else await browser.new_context(), container
        except Exception as exc:  # CDP not up yet
            last = exc
            await asyncio.sleep(0.5)
    raise BrowserUnavailable(f"browser container did not open CDP in time ({last})")


async def _get_session(profile: str) -> BrowserSession:
    global _events_wired
    uid = current_user_id.get() or ""
    tid = current_task_id.get() or ""
    key = f"{uid}:{profile or 'default'}"
    session = _sessions.get(key)
    if session is None:
        path = profile_dir(uid, profile)
        if settings.browser.local_mode:
            context, container = await _local_context(path), None
        else:
            context, container = await _container_context(uid, profile, path)
        session = BrowserSession(key, context, container)
        _sessions[key] = session
        if not _events_wired:
            await events.subscribe(events.TASK_FINISHED, _on_task_finished)
            _events_wired = True
    if tid:
        session.tasks.add(tid)
    return session


async def stop_playwright() -> None:
    """Tear down the module-global playwright driver (tests, shutdown)."""
    global _pw
    if _pw is not None:
        with contextlib.suppress(Exception):
            await _pw.stop()
        _pw = None


async def _on_task_finished(payload: dict) -> None:
    """Close a session when its last using task finished (profile persists)."""
    tid = str(payload.get("task_id") or "")
    for _key, session in list(_sessions.items()):
        if tid and tid in session.tasks:
            session.tasks.discard(tid)
        if not session.tasks:
            await session.close()


# --------------------------------------------------------------------------- #
# Snapshot: visible text + numbered interactive elements
# --------------------------------------------------------------------------- #

_SNAPSHOT_JS = """
() => {
  const els = Array.from(document.querySelectorAll("__ELEMENTS__"));
  const out = [];
  els.forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    const style = window.getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return;
    out.push({
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || "",
      text: (el.innerText || "").trim().slice(0, 80) ||
            el.getAttribute("aria-label") || "",
      placeholder: el.getAttribute("placeholder") || "",
      name: el.getAttribute("name") || "",
      href: el.tagName === "A" ? (el.getAttribute("href") || "") : "",
    });
  });
  return out;
}
""".replace("__ELEMENTS__", _ELEMENTS_CSS)


def _label(el: dict) -> str:
    for key in ("text", "placeholder", "name"):
        value = (el.get(key) or "").strip()
        if value:
            return value[:80].replace("\n", " ")
    return ""


async def _snapshot(session: BrowserSession) -> str:
    session.page = await session.current_page()
    page = session.page
    title = await page.title()
    url = page.url  # property, not a coroutine
    body = await page.evaluate("() => document.body ? document.body.innerText : ''")
    elements = await page.evaluate(_SNAPSHOT_JS)
    max_chars = settings.browser.snapshot_max_chars
    body = (body or "").strip()[:max_chars]
    lines = [f"page: {title} ({url})", "", body, "", "interactive elements:"]
    session.refs = []
    for el in elements:
        idx = len(session.refs)
        session.refs.append(idx)
        type_part = f" type={el['type']}" if el.get("type") else ""
        name_part = f" name={el['name']}" if el.get("name") and not el.get("text") else ""
        lines.append(f"[{idx}] <{el['tag']}{type_part}> {_label(el)!r}{name_part}")
    if not elements:
        lines.append("(none)")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[truncated]"
    return text


def _locator(session: BrowserSession, ref: str):
    try:
        idx = int(ref)
    except ValueError as exc:
        raise ValueError(f"ref must be a snapshot number, got {ref!r}") from exc
    if not 0 <= idx < len(session.refs):
        raise ValueError(f"ref {idx} is not on the current snapshot — take a new browser_snapshot")
    return session.page.locator(_ELEMENTS_CSS).nth(idx)


# --------------------------------------------------------------------------- #
# Tools (all moderate; all output = external content)
# --------------------------------------------------------------------------- #


def _ids() -> tuple[str, str]:
    return current_user_id.get() or "", current_task_id.get() or ""


async def _tool_snapshot(session: BrowserSession) -> ExternalContent:
    page = await session.current_page()
    text = await _snapshot(session)
    return ExternalContent(text, source=f"page:{page.url}")


@tool(
    "browser_open",
    "Open a URL in this user's browser session and get a text snapshot with "
    "numbered interactive elements. Act on elements by their [ref] numbers.",
    risk="moderate",
)
async def browser_open(url: str, profile: str = "default") -> ExternalContent:
    uid, _ = _ids()
    if not settings.browser.local_mode:
        from tools.web import assert_public_url

        assert_public_url(url)  # container mode still refuses internal targets
    session = await _get_session(profile)
    async with session.lock:
        page = await session.current_page()
        await page.goto(url, timeout=settings.browser.default_timeout_ms, wait_until="domcontentloaded")
        return await _tool_snapshot(session)


@tool(
    "browser_snapshot",
    "Take a fresh text snapshot of the current page (refs may have changed "
    "after actions).",
    risk="moderate",
)
async def browser_snapshot(profile: str = "default") -> ExternalContent:
    session = await _get_session(profile)
    async with session.lock:
        return await _tool_snapshot(session)


@tool(
    "browser_click",
    "Click the element with the given [ref] number from the latest snapshot.",
    risk="moderate",
)
async def browser_click(ref: str, profile: str = "default") -> ExternalContent:
    session = await _get_session(profile)
    async with session.lock:
        await session.current_page()
        try:
            await _locator(session, ref).click(timeout=settings.browser.default_timeout_ms)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        await session.page.wait_for_load_state("domcontentloaded")
        return await _tool_snapshot(session)


@tool(
    "browser_type",
    "Type text into the element with the given [ref]. For a PASSWORD, do not "
    "pass it here: call with secret=true and text=<site name> to type the "
    "stored credential value — it will never appear in snapshots or logs.",
    risk="moderate",
)
async def browser_type(
    ref: str, text: str, secret: bool = False, profile: str = "default"
) -> ExternalContent | ToolResult:
    uid, _ = _ids()
    session = await _get_session(profile)
    async with session.lock:
        await session.current_page()
        try:
            loc = _locator(session, ref)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        if secret:
            from tools.credentials import get_credential_for_user, secret_password

            secret_value = await get_credential_for_user(uid, text)
            if secret_value is None:
                return ToolResult(ok=False, error=f"no stored credential for {text!r}")
            await loc.fill(
                secret_password(secret_value), timeout=settings.browser.default_timeout_ms
            )
        else:
            await loc.fill(text, timeout=settings.browser.default_timeout_ms)
        return await _tool_snapshot(session)


@tool(
    "browser_select",
    "Choose an option in a <select> element by its visible label or value.",
    risk="moderate",
)
async def browser_select(ref: str, option: str, profile: str = "default") -> ExternalContent | ToolResult:
    session = await _get_session(profile)
    async with session.lock:
        await session.current_page()
        try:
            loc = _locator(session, ref)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        try:
            await loc.select_option(label=option, timeout=settings.browser.default_timeout_ms)
        except Exception:
            await loc.select_option(option, timeout=settings.browser.default_timeout_ms)
        return await _tool_snapshot(session)


@tool("browser_scroll", "Scroll the page: 'up', 'down', 'top' or 'bottom'.", risk="moderate")
async def browser_scroll(direction: str, profile: str = "default") -> ExternalContent | ToolResult:
    session = await _get_session(profile)
    async with session.lock:
        page = await session.current_page()
        if direction == "up":
            await page.keyboard.press("PageUp")
        elif direction == "down":
            await page.keyboard.press("PageDown")
        elif direction == "top":
            await page.evaluate("() => window.scrollTo(0, 0)")
        elif direction == "bottom":
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        else:
            return ToolResult(ok=False, error="direction must be up|down|top|bottom")
        return await _tool_snapshot(session)


@tool("browser_back", "Go back one page in this session's history.", risk="moderate")
async def browser_back(profile: str = "default") -> ExternalContent | ToolResult:
    session = await _get_session(profile)
    async with session.lock:
        page = await session.current_page()
        await page.go_back(timeout=settings.browser.default_timeout_ms)
        return await _tool_snapshot(session)


@tool(
    "browser_screenshot",
    "Fallback visual capture of the current page, saved to a file (returns "
    "the path, never inline image data).",
    risk="moderate",
)
async def browser_screenshot(profile: str = "default") -> dict:
    uid, tid = _ids()
    session = await _get_session(profile)
    async with session.lock:
        page = await session.current_page()
        shots_dir = profile_dir(uid, profile).parent / "_shots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        path = shots_dir / f"{tid or 'task'}-{int(time.time() * 1000)}.jpg"
        await page.screenshot(path=str(path), type="jpeg", quality=70, full_page=False)
        size = path.stat().st_size
        return {"path": str(path), "bytes": size, "note": "jpeg, viewport only"}


# --------------------------------------------------------------------------- #
# browser_login — the composite; the only consumer of raw credentials
# --------------------------------------------------------------------------- #


@tool(
    "browser_login",
    "Log this user into a site using their stored credential (site key from "
    "list_available_accounts). Fills the login form internally — the secret "
    "is never shown. Returns the post-login snapshot; on failure says "
    "'login failed' with the snapshot, never the values.",
    risk="moderate",
)
async def browser_login(site: str, profile: str = "default") -> ExternalContent | ToolResult:
    uid, _ = _ids()
    from tools.credentials import get_credential_for_user

    secret_value = await get_credential_for_user(uid, site)
    if secret_value is None:
        return ToolResult(ok=False, error=f"no stored credential for {site!r}")
    from tools.credentials import secret_password

    password = secret_password(secret_value)
    try:
        parsed = json.loads(secret_value.reveal())
        username = str(parsed.get("username", "")) if isinstance(parsed, dict) else ""
    except ValueError:
        username = ""

    session = await _get_session(profile)
    async with session.lock:
        page = await session.current_page()
        origin = site if "://" in site else f"https://{site}"
        if not settings.browser.local_mode:
            from tools.web import assert_public_url

            assert_public_url(origin)
        try:
            await page.goto(origin, timeout=settings.browser.default_timeout_ms,
                            wait_until="domcontentloaded")
        except Exception as exc:
            return ToolResult(ok=False, error=f"could not reach {site!r}: {type(exc).__name__}")

        password_loc = page.locator("input[type=password]").first
        try:
            await password_loc.wait_for(timeout=settings.browser.default_timeout_ms)
        except Exception:
            return ToolResult(ok=False, error=f"no login form found at {site!r}")

        # Username field: email input, common names, or the text input just
        # before the password field.
        user_loc = page.locator(
            "input[type=email], input[name*=user i], input[name*=email i], "
            "input[name*=login i], input[id*=user i], input[id*=email i]"
        ).first
        try:
            if await user_loc.count() == 0:
                user_loc = page.locator("input:not([type=password])").first
            if username:
                await user_loc.fill(username, timeout=settings.browser.default_timeout_ms)
        except Exception:
            pass  # single-field (password-only) forms are legitimate
        await password_loc.fill(password, timeout=settings.browser.default_timeout_ms)

        submitted = False
        for submit_loc in (
            page.locator("button[type=submit]").first,
            page.locator("input[type=submit]").first,
        ):
            try:
                if await submit_loc.count() > 0:
                    await submit_loc.click(timeout=settings.browser.default_timeout_ms)
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            await password_loc.press("Enter")

        try:
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(500)
        except Exception:
            pass

        # Verify: password field gone from the page ⇒ we left the login form.
        if await page.locator("input[type=password]").count() > 0:
            snapshot = await _snapshot(session)
            return ToolResult(
                ok=False,
                error="login failed (still on the login form). Page snapshot:\n" + snapshot,
            )
        logger.info("browser login ok", extra={"user_id": uid, "site": site})
        return await _tool_snapshot(session)


# --------------------------------------------------------------------------- #
# Maintenance: purge stale per-user profiles (wired into the scheduler sweep)
# --------------------------------------------------------------------------- #


async def purge_stale_profiles() -> int:
    """Remove per-user profile dirs unused for longer than the retention
    window. Walks ONLY inside the configured profiles root, tenant-agnostic
    by construction (every child belongs to exactly one user id)."""
    days = settings.browser.profile_retention_days
    if days <= 0:
        return 0
    root = profile_root()
    cutoff = time.time() - days * 86400
    removed = 0

    def _purge() -> int:
        count = 0
        for user_dir in root.iterdir():
            if not user_dir.is_dir() or user_dir.name == "_shots":
                continue
            for profile in user_dir.iterdir():
                try:
                    if profile.stat().st_mtime < cutoff:
                        import shutil

                        shutil.rmtree(profile, ignore_errors=True)
                        count += 1
                except FileNotFoundError:
                    continue
            with contextlib.suppress(OSError):
                user_dir.rmdir()  # remove empty user dirs
        return count

    removed = await asyncio.to_thread(_purge)
    if removed:
        logger.info("stale browser profiles purged", extra={"removed": removed})
    return removed
