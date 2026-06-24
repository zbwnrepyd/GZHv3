from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class SearchResult:
    provider: str
    query: str
    rank: int
    title: str
    url: str
    snippet: str = ""


SEARCH_HOSTS = {
    "google.com", "www.google.com", "webcache.googleusercontent.com",
    "bing.com", "www.bing.com", "go.microsoft.com",
}
SEARCH_HOST_SUFFIXES = (
    ".google.com",
    ".googleusercontent.com",
    ".bing.com",
)


def _clean_google_url(raw: str) -> str:
    if not raw:
        return ""
    if raw.startswith("/url?"):
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        raw = qs.get("q", [""])[0]
    return unquote(raw).strip()


def _decode_bing_u(value: str) -> str:
    value = unquote(value or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("a1"):
        value = value[2:]
    try:
        padded = value + ("=" * (-len(value) % 4))
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", "ignore")
        if decoded.startswith(("http://", "https://")):
            return decoded
    except Exception:
        return ""
    return ""


def _clean_bing_url(raw: str) -> str:
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.path.startswith("/ck/a"):
        qs = parse_qs(parsed.query)
        if qs.get("u"):
            decoded = _decode_bing_u(qs["u"][0])
            if decoded:
                return decoded
    return unquote(raw).strip()


def _clean_search_url(provider: str, raw: str) -> str:
    provider = (provider or "").lower()
    if provider == "google":
        return _clean_google_url(raw)
    if provider == "bing":
        return _clean_bing_url(raw)
    return unquote(raw or "").strip()


def _is_organic_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    host = urlparse(url).netloc.lower()
    if not host:
        return False
    if host in SEARCH_HOSTS or any(host.endswith(suffix) for suffix in SEARCH_HOST_SUFFIXES):
        return False
    if any(part in url for part in ("/aclick?", "/pagead/", "adurl=", "/ads/")):
        return False
    return True


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _fallback_link_results(provider: str, html: str, query: str = "") -> list[SearchResult]:
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        url = _clean_search_url(provider, link.get("href", ""))
        if not _is_organic_url(url) or url in seen:
            continue
        title = _text(link)
        if not title:
            continue
        parent = link.find_parent(["li", "div", "article", "section"])
        snippet = _text(parent.select_one("p")) if parent else ""
        seen.add(url)
        results.append(SearchResult(
            provider=provider,
            query=query,
            rank=len(results) + 1,
            title=title,
            url=url,
            snippet=snippet,
        ))
    return results


def parse_bing_results(html: str, query: str = "") -> list[SearchResult]:
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[SearchResult] = []
    for item in soup.select("li.b_algo"):
        link = item.select_one("h2 a[href]") or item.select_one("a[href]")
        if not link:
            continue
        url = _clean_bing_url(link.get("href", ""))
        if not _is_organic_url(url):
            continue
        title = _text(link)
        snippet = _text(item.select_one("p"))
        results.append(SearchResult(
            provider="bing",
            query=query,
            rank=len(results) + 1,
            title=title,
            url=url,
            snippet=snippet,
        ))
    return results or _fallback_link_results("bing", html, query=query)


def parse_google_results(html: str, query: str = "") -> list[SearchResult]:
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[SearchResult] = []
    containers = soup.select("div.g")
    if not containers:
        containers = soup.select("div[data-sokoban-container]")
    for item in containers:
        link = item.select_one("a[href]")
        if not link:
            continue
        url = _clean_google_url(link.get("href", ""))
        if not _is_organic_url(url):
            continue
        heading = item.select_one("h3")
        title = _text(heading) or _text(link)
        if not title:
            continue
        snippet = _text(item.select_one(".VwiC3b")) or _text(item.select_one("[data-sncf]"))
        results.append(SearchResult(
            provider="google",
            query=query,
            rank=len(results) + 1,
            title=title,
            url=url,
            snippet=snippet,
        ))
    return results or _fallback_link_results("google", html, query=query)


def parse_duckduckgo_results(html: str, query: str = "") -> list[SearchResult]:
    """解析 DuckDuckGo HTML 搜索结果。DDG 使用 /l/?uddg= 重定向包装 URL。"""
    from urllib.parse import parse_qs, unquote

    soup = BeautifulSoup(html or "", "html.parser")
    results: list[SearchResult] = []
    for item in soup.select(".result__body"):
        link = item.select_one(".result__a")
        if not link:
            continue
        raw_url = link.get("href", "")
        # DDG 重定向: //duckduckgo.com/l/?uddg=<encoded_url>
        url = raw_url
        if "/l/?uddg=" in raw_url or "uddg=" in raw_url:
            parsed = urlparse(raw_url)
            qs = parse_qs(parsed.query)
            uddg = qs.get("uddg", [""])[0]
            if uddg:
                url = unquote(uddg).strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        if not _is_organic_url(url):
            continue
        title = link.get_text(" ", strip=True)
        snippet_tag = item.select_one(".result__snippet")
        snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
        results.append(SearchResult(
            provider="duckduckgo",
            query=query,
            rank=len(results) + 1,
            title=title,
            url=url,
            snippet=snippet,
        ))
    return results


def parse_serp(provider: str, html: str, query: str = "") -> list[SearchResult]:
    provider = (provider or "").strip().lower()
    if provider == "bing":
        return parse_bing_results(html, query=query)
    if provider == "google":
        return parse_google_results(html, query=query)
    if provider in ("duckduckgo", "ddg"):
        return parse_duckduckgo_results(html, query=query)
    return []
