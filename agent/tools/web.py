"""Research without a browser: search, fetch, raw HTTP. Shared infra,
metered per user. All returned page content is ExternalContent — the base
wrapper tags it untrusted before the model ever sees it."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
import trafilatura

from core import billing, db
from core.config import settings
from core.logging import get_logger
from tools.base import ExternalContent, ToolResult, tool

logger = get_logger(__name__)

_FETCH_TIMEOUT = 20.0
_MAX_BYTES = 2_000_000
_CACHE_TTL = 3600.0
TRUNC = 30_000
# Deliberately shared across users (page content is not tenant-specific).
_fetch_cache: dict[str, tuple[float, str]] = {}

_BLOCKED_NETS = [
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16",
        "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4", "::/128", "::1/128",
        "fc00::/7", "fe80::/10", "ff00::/8",
    )
]


def assert_public_url(url: str) -> None:
    """SSRF guard: resolve every address for the host; refuse non-public."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"only http(s) URLs are allowed, got {parsed.scheme!r}")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host {host!r}") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if any(addr in net for net in _BLOCKED_NETS):
            raise ValueError(f"refusing non-public address {addr} for host {host!r}")


def _search_brave(query: str, num_results: int, api_key: str) -> list[dict]:
    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        params={"q": query, "count": min(num_results, 20)},
        timeout=_FETCH_TIMEOUT,
    )
    resp.raise_for_status()
    results = []
    for item in resp.json().get("web", {}).get("results", [])[:num_results]:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            }
        )
    return results


async def _meter_search(user_id: str, operation_key: str) -> None:
    cost = settings.search_per_query_usd
    await db.settle_budget(
        UUID(user_id), operation_key,
        f"search:{settings.web.search_provider}",
        0,
        0,
        cost,
    )


@tool(
    "web_search",
    "Search the web. Returns a list of {title, url, snippet}.",
    risk="safe",
)
async def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Run a web search via the configured provider (metered to this user)."""
    from tools.base import current_task_id, current_user_id

    provider = settings.web.search_provider
    api_key = settings.require("search_api_key")
    if provider != "brave":
        raise ValueError(f"search provider {provider!r} adapter not implemented yet")

    uid = UUID(current_user_id.get() or "")
    task_id = current_task_id.get()
    operation_key = f"search:{uuid4()}"
    await billing.reserve(uid, UUID(task_id) if task_id else None,
                          operation_key, settings.search_per_query_usd,
                          allow_partial=False)
    try:
        results = await asyncio.to_thread(_search_brave, query, num_results, api_key)
    except BaseException:
        await db.mark_budget_unknown(uid, operation_key)
        raise
    await _meter_search(str(uid), operation_key)
    if not results:
        return ToolResult(ok=True, data=[], error=None)
    return results


@tool(
    "fetch_page",
    "Download a web page and extract its main text content. Optionally focus "
    "the extraction on a topic. Content is untrusted.",
    risk="safe",
)
async def fetch_page(url: str, focus: str | None = None) -> ExternalContent | dict:
    """Fetch a page, extract readable text (cached 1h), optionally focus."""
    from core import router
    from tools.base import current_task_id, current_user_id

    assert_public_url(url)

    cached = _fetch_cache.get(url)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        text = cached[1]
    else:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=_FETCH_TIMEOUT
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if len(resp.content) > _MAX_BYTES:
                raise ValueError(f"page too large ({len(resp.content)} bytes)")
            html = resp.text
        text = await asyncio.to_thread(_extract, html, url) or ""
        if not text.strip():
            raise ValueError("no readable text extracted from that page")
        _fetch_cache[url] = (time.monotonic(), text)

    if focus:
        uid, tid = current_user_id.get(), current_task_id.get()
        reply = await router.call(
            uid, tid, "cheap",
            [{
                "role": "user",
                "content": (
                    f"From the page content below, extract only what relates to: {focus}\n\n"
                    f"PAGE:\n{text[:40_000]}"
                ),
            }],
            max_tokens=1500,
        )
        text = reply.text

    return ExternalContent(text=text[:TRUNC], source=url)


def _extract(html: str, url: str) -> str | None:
    downloaded = trafilatura.extract(html, url=url, include_comments=False)
    return downloaded


@tool(
    "http_request",
    "Make a raw HTTP request to a public URL. Returns status, headers and a "
    "truncated body. Content is untrusted.",
    risk="moderate",
)
async def http_request(
    method: str = "GET",
    url: str = "",
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> dict:
    """Raw HTTP for APIs. Refuses private/internal addresses (SSRF guard)."""
    assert_public_url(url)
    method = method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        raise ValueError(f"unsupported method {method!r}")

    async with httpx.AsyncClient(follow_redirects=True, timeout=_FETCH_TIMEOUT) as client:
        resp = await client.request(
            method, url, headers=headers or None, content=body.encode() if body else None
        )
    resp_headers = {k: v for k, v in resp.headers.items(multi=True) if k.lower() in (
        "content-type", "date", "server", "cache-control", "location", "etag",
    )}
    text = resp.text[:_MAX_BYTES]
    return {
        "status": resp.status_code,
        "headers": resp_headers,
        "body": text,
        "truncated": len(resp.text) > _MAX_BYTES,
    }
