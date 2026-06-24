from __future__ import annotations

from urllib.parse import quote_plus

from .page_fetcher import FetchResult, _page_to_html, _looks_blocked, _get_fetcher_class

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def build_search_url(provider: str, query: str, page: int = 1) -> str:
    """构建搜索引擎 URL。page 从 1 开始，每页约 10 条结果。"""
    encoded = quote_plus(query)
    if provider == "google":
        start = (page - 1) * 10
        return f"https://www.google.com/search?q={encoded}&num=30&hl=en&start={start}"
    if provider in ("duckduckgo", "ddg"):
        # DDG HTML 版，不需要 JS，对爬虫友好
        # s=偏移量，每页约 20-30 条
        offset = (page - 1) * 20
        return f"https://html.duckduckgo.com/html/?q={encoded}&s={offset}"
    # Bing: setmkt=en-US 强制英文市场结果（解决代理 IP 在中国被重定向到 cn.bing.com 的问题）
    first = (page - 1) * 10 + 1
    return f"https://www.bing.com/search?q={encoded}&setmkt=en-US&count=30&first={first}"


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


def _fetch_serp_with_requests(url: str, timeout_seconds: int) -> FetchResult:
    """对 Google 等封 curl-cffi 的引擎使用 requests + 代理。"""
    import requests as req
    import os
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"}
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    try:
        resp = req.get(url, headers=headers, timeout=timeout_seconds, proxies=proxies)
        if resp.status_code >= 400:
            return FetchResult(url=url, html="", status="failed",
                             error=f"HTTP {resp.status_code}")
        html = resp.text or ""
        # Google 专用封锁检测：只看 captcha/unusual traffic，不看 enablejs（noscript 中正常出现）
        body = (html or "")[:4000].lower()
        google_blocked = any(m in body for m in ("unusual traffic", "sorry/index", "captcha"))
        if google_blocked:
            return FetchResult(url=url, html="", status="failed",
                             error="Google blocked the request (captcha/unusual traffic)")
        return FetchResult(url=url, html=html)
    except Exception as e:
        return FetchResult(url=url, html="", status="failed", error=str(e)[:200])


def fetch_serp(provider: str, query: str, *, fetcher: str, timeout_seconds: int, page: int = 1) -> FetchResult:
    """Fetch search engine result page HTML.

    Google: 使用 requests + 代理（curl-cffi 被 Google 封锁）
    其他引擎: 使用 Scrapling Fetcher（curl-cffi，模拟 Chrome TLS）

    Args:
        page: 搜索结果页码（1 起），自动计算分页 offset
    """
    url = build_search_url(provider, query, page=page)

    # Google 封 curl-cffi，用 requests 直接请求
    if provider == "google":
        return _fetch_serp_with_requests(url, timeout_seconds)

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
