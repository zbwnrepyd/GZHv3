import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP = os.path.join(ROOT, "webapp")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if WEBAPP not in sys.path:
    sys.path.insert(0, WEBAPP)


def test_build_field_queries_prioritizes_high_value_fields():
    from webapp.research.scrapling.query_builder import build_field_queries

    queries = build_field_queries(
        {"display_name": "Anthropic", "website_host": "anthropic.com"},
        ["funding_info", "founder_edu", "ltv"],
        max_queries_per_field=2,
    )

    assert any(q.field_key == "funding_info" and "funding" in q.query.lower() for q in queries)
    assert any(q.field_key == "founder_edu" and "founder" in q.query.lower() for q in queries)
    assert not any(q.field_key == "ltv" for q in queries)
    assert all(q.provider_intent for q in queries)


def test_build_field_queries_generates_generic_public_field_queries():
    from webapp.research.scrapling.query_builder import build_field_queries

    queries = build_field_queries(
        {"display_name": "Anthropic", "website_host": "anthropic.com"},
        ["product_tech_stack", "regional_market_focus", "ltv"],
    )

    query_texts = [q.query for q in queries]
    assert "Anthropic product tech stack" in query_texts
    assert "Anthropic regional market focus" in query_texts
    assert not any(q.field_key == "ltv" for q in queries)


def test_parse_bing_results_extracts_organic_links():
    from webapp.research.scrapling.serp_parser import parse_bing_results

    html = """
    <html><body>
      <li class="b_algo">
        <h2><a href="https://example.com/about">Example About</a></h2>
        <p>Company overview snippet.</p>
      </li>
      <li class="b_algo">
        <h2><a href="https://www.bing.com/aclick?u=https%3A%2F%2Fad.example">Ad</a></h2>
      </li>
    </body></html>
    """

    results = parse_bing_results(html, query="Example funding")

    assert len(results) == 1
    assert results[0].title == "Example About"
    assert results[0].url == "https://example.com/about"
    assert results[0].rank == 1
    assert results[0].snippet == "Company overview snippet."


def test_parse_bing_results_falls_back_to_encoded_ck_links():
    from webapp.research.scrapling.serp_parser import parse_bing_results

    html = """
    <html><body>
      <main>
        <a href="/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS90ZWFt&ntb=1">Example Team</a>
      </main>
    </body></html>
    """

    results = parse_bing_results(html, query="Example founder")

    assert len(results) == 1
    assert results[0].url == "https://example.com/team"
    assert results[0].title == "Example Team"


def test_parse_google_results_extracts_organic_links():
    from webapp.research.scrapling.serp_parser import parse_google_results

    html = """
    <html><body>
      <div class="g">
        <a href="/url?q=https://example.com/pricing&sa=U&ved=abc">Pricing</a>
        <h3>Example Pricing</h3>
        <div class="VwiC3b">Pricing snippet.</div>
      </div>
      <div class="g">
        <a href="https://webcache.googleusercontent.com/search?q=cache">Cache</a>
      </div>
    </body></html>
    """

    results = parse_google_results(html, query="Example pricing")

    assert len(results) == 1
    assert results[0].title == "Example Pricing"
    assert results[0].url == "https://example.com/pricing"
    assert results[0].rank == 1
    assert results[0].snippet == "Pricing snippet."


def test_parse_google_results_falls_back_to_search_result_links():
    from webapp.research.scrapling.serp_parser import parse_google_results

    html = """
    <html><body>
      <a href="/url?q=https%3A%2F%2Fexample.com%2Fcustomers&sa=U">Customers</a>
      <a href="https://webcache.googleusercontent.com/search?q=cache">Cache</a>
    </body></html>
    """

    results = parse_google_results(html, query="Example customers")

    assert len(results) == 1
    assert results[0].url == "https://example.com/customers"
    assert results[0].title == "Customers"


def test_adapter_returns_empty_when_scrapling_disabled(monkeypatch):
    from webapp.research.adapters.scrapling_search_adapter import ScraplingSearchAdapter

    monkeypatch.setenv("SCRAPLING_ENABLED", "0")
    adapter = ScraplingSearchAdapter()

    docs = adapter.collect(
        {"display_name": "Anthropic", "website_host": "anthropic.com"},
        ["funding_info"],
        {"max_documents": 5},
    )

    assert docs == []


def test_scrapling_missing_dependency_message_mentions_python_runtime(monkeypatch):
    import builtins
    from webapp.research.scrapling.page_fetcher import fetch_html

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "scrapling.fetchers":
            raise ImportError("No module named 'scrapling.fetchers'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = fetch_html("https://example.com", fetcher="fetcher")

    assert result.status == "unavailable"
    assert "Python >=3.10" in result.error
    assert "requirements-scrapling.txt" in result.error


def test_scrapling_config_defaults_to_auto(monkeypatch):
    from webapp.research.scrapling.config import load_config

    monkeypatch.delenv("SCRAPLING_FETCHER", raising=False)
    monkeypatch.delenv("SCRAPLING_SEARCH_DELAY_SECONDS", raising=False)

    cfg = load_config()

    assert cfg.fetcher == "auto"
    assert cfg.search_delay_seconds == 0


def test_fetch_html_auto_uses_basic_fetcher_only(monkeypatch):
    """auto mode now resolves to 'fetcher' only — no speculative headless escalation."""
    from webapp.research.scrapling import page_fetcher

    calls = []

    def fake_fetch(url, fetcher, timeout_seconds):
        calls.append(fetcher)
        return page_fetcher.FetchResult(
            url=url,
            html="<html><main>Useful rendered company content for extraction.</main></html>",
        )

    monkeypatch.setattr(page_fetcher, "_fetch_with_named_fetcher", fake_fetch)

    result = page_fetcher.fetch_html("https://example.com", fetcher="auto", timeout_seconds=1)

    assert result.status == "ok"
    assert "Useful rendered" in result.html
    assert calls == ["fetcher"]  # auto → fetcher only, no escalation

def test_fetch_html_explicit_dynamic_uses_headless(monkeypatch):
    """Explicit fetcher='dynamic' should use DynamicFetcher."""
    from webapp.research.scrapling import page_fetcher

    calls = []

    def fake_fetch(url, fetcher, timeout_seconds):
        calls.append(fetcher)
        return page_fetcher.FetchResult(
            url=url,
            html="<html><main>JS-rendered content.</main></html>",
        )

    monkeypatch.setattr(page_fetcher, "_fetch_with_named_fetcher", fake_fetch)

    result = page_fetcher.fetch_html("https://example.com", fetcher="dynamic", timeout_seconds=1)

    assert result.status == "ok"
    assert "JS-rendered" in result.html
    assert calls == ["dynamic"]


def test_page_to_html_reads_scrapling_response_body_bytes():
    from webapp.research.scrapling.page_fetcher import _page_to_html

    class FakeScraplingResponse:
        body = b"<!doctype html><html><body>Example Domain</body></html>"

        def __str__(self):
            return "<200 https://example.com/>"

    html = _page_to_html(FakeScraplingResponse())

    assert "<html>" in html
    assert "Example Domain" in html


def test_fetch_serp_uses_scrapling_fetcher_directly(monkeypatch):
    """SERP fetching now uses Scrapling Fetcher directly — no plain requests first-try."""
    from webapp.research.scrapling import serp_fetcher
    from webapp.research.scrapling.page_fetcher import FetchResult

    calls = []

    def fake_fetch_with_scrapling(url, timeout_seconds):
        calls.append(("scrapling_fetcher", url))
        return FetchResult(
            url=url,
            html="<html><body><li class='b_algo'><h2>Result</h2>"
                 "<p>Search result snippet with enough HTML length for validation.</p>"
                 "</li></body></html>",
        )

    monkeypatch.setattr(serp_fetcher, "_fetch_serp_with_scrapling", fake_fetch_with_scrapling)

    result = serp_fetcher.fetch_serp("bing", "Anthropic funding", fetcher="auto", timeout_seconds=1)

    assert result.status == "ok"
    assert "b_algo" in result.html
    assert len(calls) == 1
    assert calls[0][0] == "scrapling_fetcher"


def test_fetch_serp_falls_back_when_scrapling_fetcher_blocked(monkeypatch):
    """When Scrapling Fetcher returns a blocked page, fallback to explicit fetcher."""
    from webapp.research.scrapling import serp_fetcher
    from webapp.research.scrapling.page_fetcher import FetchResult

    calls = []

    def fake_fetch_with_scrapling(url, timeout_seconds):
        calls.append(("scrapling_fetcher", url))
        return FetchResult(
            url=url, html="", status="failed",
            error="Search page returned blocked or verification HTML",
        )

    def fake_fetch_html(url, *, fetcher, timeout_seconds):
        calls.append(("scrapling_headless", url))
        return FetchResult(
            url=url,
            html="<html><body><li class='b_algo'>real result</li></body></html>",
        )

    monkeypatch.setattr(serp_fetcher, "_fetch_serp_with_scrapling", fake_fetch_with_scrapling)
    # fetch_html is lazily imported inside fetch_serp — patch the source module
    from webapp.research.scrapling import page_fetcher as pf
    monkeypatch.setattr(pf, "fetch_html", fake_fetch_html)

    # With fetcher="dynamic", it should fall back after scrapling fetcher fails
    result = serp_fetcher.fetch_serp("bing", "Anthropic funding", fetcher="dynamic", timeout_seconds=1)

    assert result.status == "ok"
    assert "real result" in result.html
    assert [call[0] for call in calls] == ["scrapling_fetcher", "scrapling_headless"]


def test_adapter_fetches_page_with_local_requests_before_scrapling(monkeypatch):
    from webapp.research.adapters import scrapling_search_adapter as adapter_module
    from webapp.research.adapters.scrapling_search_adapter import ScraplingSearchAdapter
    from webapp.research.scrapling.page_fetcher import FetchResult
    from webapp.research.scrapling.serp_parser import SearchResult

    calls = []

    monkeypatch.setenv("SCRAPLING_ENABLED", "1")
    monkeypatch.setattr(
        adapter_module,
        "build_field_queries",
        lambda company_identity, field_targets: [
            type("FieldQuery", (), {"query": "Anthropic funding"})()
        ],
    )
    monkeypatch.setattr(
        adapter_module,
        "fetch_serp",
        lambda provider, query, fetcher, timeout_seconds: FetchResult(
            url="https://www.bing.com/search?q=Anthropic+funding",
            html="<html>search</html>",
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "parse_serp",
        lambda provider, html, query="": [
            SearchResult(
                provider=provider,
                query=query,
                rank=1,
                title="Anthropic Funding",
                url="https://example.com/funding",
                snippet="Funding snippet",
            )
        ],
    )

    def fake_scrape_url(url, timeout):
        calls.append(("requests", url))
        return {
            "markdown": "Anthropic funding details. " * 20,
            "title": "Anthropic Funding",
            "error": None,
        }

    def fake_fetch_html(url, *, fetcher, timeout_seconds):
        calls.append(("scrapling", url))
        raise AssertionError("Scrapling should not run when local requests page fetch succeeds")

    monkeypatch.setattr(adapter_module, "scrape_url", fake_scrape_url)
    monkeypatch.setattr(adapter_module, "fetch_html", fake_fetch_html)

    docs = ScraplingSearchAdapter().collect(
        {"display_name": "Anthropic", "website_host": "anthropic.com"},
        ["funding_info"],
        {"max_documents": 1},
    )

    assert len(docs) == 1
    assert "Anthropic funding details" in docs[0].content
    assert [call[0] for call in calls] == ["requests"]


def test_adapter_filters_unrelated_serp_urls_before_fetching(monkeypatch):
    from webapp.research.adapters import scrapling_search_adapter as adapter_module
    from webapp.research.adapters.scrapling_search_adapter import ScraplingSearchAdapter
    from webapp.research.scrapling.config import ScraplingCrawlerConfig
    from webapp.research.scrapling.page_fetcher import FetchResult
    from webapp.research.scrapling.serp_parser import SearchResult

    fetched_urls = []

    monkeypatch.setattr(
        adapter_module,
        "load_config",
        lambda: ScraplingCrawlerConfig(
            enabled=True,
            fetcher="auto",
            providers=["bing"],
            search_delay_seconds=0,
            max_queries_per_company=1,
            results_per_query=10,
            max_urls_per_company=10,
            timeout_seconds=1,
            max_concurrency=1,
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "build_field_queries",
        lambda company_identity, field_targets: [
            type("FieldQuery", (), {"query": "Ideogram competitors alternatives"})()
        ],
    )
    monkeypatch.setattr(
        adapter_module,
        "fetch_serp",
        lambda provider, query, fetcher, timeout_seconds: FetchResult(
            url="https://www.bing.com/search?q=Ideogram+competitors",
            html="<html>search</html>",
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "parse_serp",
        lambda provider, html, query="": [
            SearchResult(
                provider=provider,
                query=query,
                rank=1,
                title="Les mémoires",
                url="https://www.bizique.be/nl/les-m%C3%A9moires",
                snippet="Unrelated local event page.",
            ),
            SearchResult(
                provider=provider,
                query=query,
                rank=2,
                title="Ideogram competitors and alternatives",
                url="https://example.com/ideogram-competitors",
                snippet="Ideogram alternatives include Midjourney and Adobe Firefly.",
            ),
        ],
    )

    def fake_fetch_page_content(url, *, fallback_fetcher, timeout_seconds):
        fetched_urls.append(url)
        return (
            "Ideogram competitors include Midjourney and Adobe Firefly. " * 10,
            "Ideogram competitors and alternatives",
            {"page_fetch_method": "requests", "page_fetch_error": ""},
        )

    monkeypatch.setattr(adapter_module, "_fetch_page_content", fake_fetch_page_content)

    docs = ScraplingSearchAdapter().collect(
        {"display_name": "Ideogram", "website_host": "ideogram.ai"},
        ["competitors_top3"],
        {"max_documents": 1},
    )

    assert fetched_urls == ["https://example.com/ideogram-competitors"]
    assert len(docs) == 1
    assert "Ideogram competitors" in docs[0].title


def test_adapter_fetches_serps_without_serial_sleep(monkeypatch):
    from webapp.research.adapters import scrapling_search_adapter as adapter_module
    from webapp.research.adapters.scrapling_search_adapter import ScraplingSearchAdapter
    from webapp.research.scrapling.config import ScraplingCrawlerConfig
    from webapp.research.scrapling.page_fetcher import FetchResult

    sleeps = []
    fetches = []

    monkeypatch.setattr(
        adapter_module,
        "load_config",
        lambda: ScraplingCrawlerConfig(
            enabled=True,
            fetcher="auto",
            providers=["bing", "google"],
            search_delay_seconds=0,
            max_queries_per_company=2,
            results_per_query=10,
            max_urls_per_company=0,
            timeout_seconds=1,
            max_concurrency=4,
        ),
    )
    monkeypatch.setattr(
        adapter_module,
        "build_field_queries",
        lambda company_identity, field_targets: [
            type("FieldQuery", (), {"query": "q1"})(),
            type("FieldQuery", (), {"query": "q2"})(),
        ],
    )

    def fake_fetch_serp(provider, query, fetcher, timeout_seconds):
        fetches.append((provider, query))
        return FetchResult(url=f"https://{provider}.example", html="<html></html>")

    monkeypatch.setattr(adapter_module, "fetch_serp", fake_fetch_serp)
    monkeypatch.setattr(adapter_module, "parse_serp", lambda provider, html, query="": [])
    monkeypatch.setattr(adapter_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    docs = ScraplingSearchAdapter().collect(
        {"display_name": "DemoCo", "website_host": "demo.example"},
        ["company_name"],
        {"max_documents": 1},
    )

    assert docs == []
    assert len(fetches) == 4
    assert sleeps == []
