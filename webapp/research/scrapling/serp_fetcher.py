from __future__ import annotations

from urllib.parse import quote_plus

from .page_fetcher import FetchResult, _page_to_html, _looks_blocked, _get_fetcher_class

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def build_search_url(provider: str, query: str) -> str:
    encoded = quote_plus(query)
    if provider == "google":
        return f"https://www.google.com/search?q={encoded}&num=10"
    return f"https://www.bing.com/search?q={encoded}"


def _fetch_serp_with_scrapling(url: str, timeout_seconds: int) -> FetchResult:
    """Fetch a SERP page using Scrapling's curl-cffi Fetcher.

    Plain requests.get is blocked by search engines.  Scrapling's Fetcher
    uses curl-impersonate TLS fingerprints that pass bot detection.
    """
    try:
        Fetcher = _get_fetcher_class()
    except ImportError as exc:
        return FetchResult(
            url=url, html="", status="unavailable",
            error=f"{exc}. Scrapling is optional; install with: pip install -r requirements-scrapling.txt",
        )

    try:
        page = Fetcher().get(url, timeout=timeout_seconds)
    except Exception as exc:
        return FetchResult(
            url=url, html="", status="failed",
            error=f"Scrapling Fetcher error: {str(exc)[:200]}",
        )

    html = _page_to_html(page)
    if not html or len(html) < 100:
        return FetchResult(
            url=url, html="", status="failed",
            error="Search page returned empty or too-short HTML",
        )
    if _looks_blocked(html):
        return FetchResult(
            url=url, html="", status="failed",
            error="Search page returned blocked or verification HTML",
        )
    return FetchResult(url=url, html=html)


def fetch_serp(provider: str, query: str, *, fetcher: str, timeout_seconds: int) -> FetchResult:
    """Fetch search engine result page HTML.

    Uses Scrapling Fetcher (curl-cffi) directly — no plain-requests first-try
    because search engines universally block requests' TLS fingerprint.
    """
    url = build_search_url(provider, query)
    result = _fetch_serp_with_scrapling(url, timeout_seconds)
    if result.status == "ok" and result.html:
        return result

    # Fallback: try alternate fetchers (dynamic/stealthy) only if explicitly
    # configured, since they launch headless browsers and are expensive.
    from .page_fetcher import fetch_html
    if fetcher not in ("auto", "fetcher"):
        fallback = fetch_html(url, fetcher=fetcher, timeout_seconds=timeout_seconds)
        if fallback.status == "ok" and fallback.html:
            return fallback
        if fallback.status == "unavailable":
            return FetchResult(
                url=url, html="", status="failed",
                error=f"Scrapling Fetcher failed: {result.error}; fallback unavailable: {fallback.error}",
            )
        return FetchResult(
            url=url, html="", status="failed",
            error=f"Scrapling Fetcher failed: {result.error}; fallback failed: {fallback.error}",
        )

    # No fallback configured — return the original error
    return result
