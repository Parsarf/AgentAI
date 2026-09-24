"""web tools: SSRF guard table test, cache behavior, metering (search mocked)."""

from __future__ import annotations

import pytest

from tools.web import assert_public_url, fetch_page


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x",
    "http://10.0.0.5/admin",
    "http://172.16.1.1/",
    "http://192.168.1.20/",
    "http://169.254.169.254/latest/meta-data/",
    "http://100.64.0.7/",
    "http://[::1]/",
    "http://[fe80::1]/",
    "http://[fc00::123]/",
    "file:///etc/passwd",
    "ftp://example.com/",
    "http://user:pass@example.com/",
])
def test_ssrf_guard_blocks(url):
    with pytest.raises(ValueError):
        assert_public_url(url)


@pytest.mark.parametrize("url", [
    "https://example.com/page",
    "https://docs.python.org/3/library/asyncio.html",
])
def test_ssrf_guard_allows_public(url):
    assert_public_url(url)  # does not raise


async def test_fetch_uses_cache_within_ttl(monkeypatch):
    calls = {"n": 0}

    def fake_extract(html, url):
        return "extracted text"

    class FakeResp:
        status_code = 200
        content = b"<html>page</html>"
        text = "<html>page</html>"

        def raise_for_status(self): ...

    async def fake_get(self, url):
        calls["n"] += 1
        return FakeResp()

    import httpx as _httpx

    monkeypatch.setattr(_httpx.AsyncClient, "get", fake_get)
    import tools.web as tw

    monkeypatch.setattr(tw, "_extract", fake_extract)

    result1 = await fetch_page(url="https://example.com/cached")
    await fetch_page(url="https://example.com/cached")
    assert calls["n"] == 1  # second fetch hit the cache
    assert "extracted text" in result1.text
    assert isinstance(result1, tw.ExternalContent)
