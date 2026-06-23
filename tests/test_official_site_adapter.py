import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP = os.path.join(ROOT, "webapp")
if WEBAPP not in sys.path:
    sys.path.insert(0, WEBAPP)


class FakeResponse:
    status_code = 403
    text = "<html><title>Just a moment...</title>Cloudflare</html>"
    headers = {"Content-Type": "text/html; charset=UTF-8"}


class FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, timeout, allow_redirects=True):
        return FakeResponse()


def test_official_site_adapter_reports_antibot_block(monkeypatch):
    from research.adapters.official_site_adapter import OfficialSiteAdapter
    import research.adapters.official_site_adapter as official_site_adapter
    from research.scrapling.page_fetcher import FetchResult

    monkeypatch.setattr(official_site_adapter.requests, "Session", FakeSession)
    monkeypatch.setattr(
        official_site_adapter,
        "fetch_html",
        lambda url, *, fetcher, timeout_seconds: FetchResult(url=url, html="", status="failed", error="blocked"),
    )

    adapter = OfficialSiteAdapter()
    with pytest.raises(RuntimeError, match="anti-bot protection"):
        adapter.collect(
            {"display_name": "Ideogram", "website_host": "ideogram.ai"},
            ["company_name"],
            {"max_documents": 2, "timeout_seconds": 1},
        )


def test_official_site_adapter_uses_scrapling_fallback_for_antibot(monkeypatch):
    from research.adapters.official_site_adapter import OfficialSiteAdapter
    import research.adapters.official_site_adapter as official_site_adapter
    from research.scrapling.page_fetcher import FetchResult

    monkeypatch.setattr(official_site_adapter.requests, "Session", FakeSession)

    def fake_fetch_html(url, *, fetcher, timeout_seconds):
        return FetchResult(
            url=url,
            html=(
                "<html><title>Ideogram About</title>"
                "<main>Ideogram is an AI image generation platform for creators and teams.</main>"
                "</html>"
            ),
        )

    monkeypatch.setattr(official_site_adapter, "fetch_html", fake_fetch_html)

    adapter = OfficialSiteAdapter()
    docs = adapter.collect(
        {"display_name": "Ideogram", "website_host": "ideogram.ai"},
        ["company_description"],
        {"max_documents": 1, "timeout_seconds": 1, "scrapling_fetcher": "auto"},
    )

    assert len(docs) == 1
    assert docs[0].source_family == "official_site"
    assert "AI image generation platform" in docs[0].content
    assert docs[0].metadata["scrapling_fallback"] is True


def test_official_site_antibot_detection_does_not_reject_real_content_with_cloudflare_asset():
    from research.adapters.official_site_adapter import _looks_antibot_html

    html = """
    <html>
      <head><script src="https://static.cloudflareinsights.com/beacon.min.js"></script></head>
      <body>
        <main>
          Ideogram is an AI image generation platform for creators, designers, and teams.
          The product offers text rendering, Magic Fill, Canvas, image remixing, and paid plans.
        </main>
      </body>
    </html>
    """

    assert _looks_antibot_html(html) is False


def test_official_site_adapter_cascades_fetcher_and_stops_after_homepage(monkeypatch):
    from research.adapters.official_site_adapter import OfficialSiteAdapter
    import research.adapters.official_site_adapter as official_site_adapter
    from research.scrapling.page_fetcher import FetchResult

    monkeypatch.setattr(official_site_adapter.requests, "Session", FakeSession)
    calls = []

    def fake_fetch_html(url, *, fetcher, timeout_seconds):
        calls.append((url, fetcher))
        return FetchResult(
            url=url,
            html=(
                "<html><title>Ideogram</title>"
                "<main>Ideogram creates AI images with reliable text rendering for teams.</main>"
                "</html>"
            ),
        )

    monkeypatch.setattr(official_site_adapter, "fetch_html", fake_fetch_html)

    adapter = OfficialSiteAdapter()
    docs = adapter.collect(
        {"display_name": "Ideogram", "website_host": "ideogram.ai"},
        ["company_description"],
        {"max_documents": 2, "timeout_seconds": 1},
    )

    assert len(docs) == 1
    # 默认 fetcher="stealthy" → 级联策略：先尝试 "fetcher"（curl-cffi），成功即止
    assert calls == [("https://ideogram.ai/", "fetcher")]
