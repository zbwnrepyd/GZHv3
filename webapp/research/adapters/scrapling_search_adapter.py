"""Scrapling-backed HTML search SourceAdapter.

This adapter is optional. It only runs when SCRAPLING_ENABLED=1 and the
separate Scrapling dependency is installed in a Python 3.10+ environment.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from firecrawl_local import scrape_url

from ..source_adapter import ADAPTER_REGISTRY, SourceAdapter, SourceDocument
from ..scrapling.config import load_config
from ..scrapling.query_builder import build_field_queries
from ..scrapling.serp_fetcher import fetch_serp
from ..scrapling.serp_parser import SearchResult, parse_serp
from ..scrapling.page_fetcher import fetch_html
from ..scrapling.source_family import classify_source
from ..scrapling.url_dedupe import dedupe_urls


def _bounded_workers(value: int, total: int) -> int:
    return max(1, min(int(value or 1), total or 1))


def _norm_text(value: str) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").replace("_", " ").split())


def _identity_terms(company_identity: dict) -> tuple[str, str, str]:
    display = _norm_text(
        company_identity.get("display_name")
        or company_identity.get("canonical_name")
        or company_identity.get("company_name")
        or ""
    )
    official_host = (
        company_identity.get("website_host")
        or company_identity.get("official_domain")
        or ""
    ).lower().removeprefix("www.")
    root = _norm_text(company_identity.get("root_domain") or official_host.split(".")[0])
    return display, official_host, root


def _result_relevance_score(result: SearchResult, company_identity: dict) -> int:
    display, official_host, root = _identity_terms(company_identity)
    parsed = urlparse(result.url or "")
    host = parsed.netloc.lower().removeprefix("www.")
    path = _norm_text(parsed.path)
    haystack = _norm_text(f"{result.title} {result.snippet} {host} {path}")

    score = 0
    if official_host and host == official_host:
        score += 100
    if official_host and host.endswith("." + official_host):
        score += 90
    if display and display in haystack:
        score += 40
    if root and root in haystack:
        score += 30
    if display and display.replace(" ", "") in haystack.replace(" ", ""):
        score += 20
    if root and root in host:
        score += 15
    return score


def _filter_relevant_results(
    results: list[SearchResult],
    company_identity: dict,
    *,
    limit: int,
) -> list[SearchResult]:
    scored = [
        (result, _result_relevance_score(result, company_identity))
        for result in results
    ]
    relevant = [(result, score) for result, score in scored if score > 0]
    if not relevant:
        relevant = scored
    relevant.sort(key=lambda item: (-item[1], item[0].rank))
    return [result for result, _ in relevant[:limit]]


def _extract_text(html: str) -> str:
    if not html:
        return ""
    try:
        import trafilatura
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        if extracted and extracted.strip():
            return extracted.strip()
    except Exception:
        pass
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _extract_title(html: str, fallback: str = "") -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.find("title")
    text = title.get_text(" ", strip=True) if title else ""
    return text or fallback


_ANTIBOT_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "verify you are human",
    "checking your browser",
    "cf-chl-",
    "/cdn-cgi/challenge-platform",
)


def _looks_antibot(html: str) -> bool:
    """检测反爬页面（Cloudflare / JS Challenge 等）。"""
    body = (html or "")[:4000].lower()
    return any(m in body for m in _ANTIBOT_MARKERS)


def _fetch_page_content(
    url: str,
    *,
    fallback_fetcher: str,
    timeout_seconds: int,
) -> tuple[str, str, dict]:
    """多级回退页面抓取：requests → Scrapling Fetcher → StealthyFetcher → Playwright。"""
    # 第1层：requests + trafilatura（最快）
    local = scrape_url(url, timeout=timeout_seconds)
    markdown = (local.get("markdown") or "").strip()
    if not local.get("error") and len(markdown) >= 200:
        if not _looks_antibot(markdown):
            return (
                markdown,
                local.get("title") or "",
                {
                    "page_fetch_method": "requests",
                    "page_fetch_error": "",
                },
            )

    # 第2层：Scrapling Fetcher（curl-cffi，模拟浏览器 TLS）
    for fetcher in ("fetcher", "stealthy"):
        try:
            page = fetch_html(url, fetcher=fetcher, timeout_seconds=max(timeout_seconds, 60))
        except (ImportError, ModuleNotFoundError):
            if fetcher == "fetcher":
                continue
            # StealthyFetcher 不可用，跳到 Playwright
            break
        except Exception:
            continue

        if page.status != "ok" or not page.html:
            continue
        if _looks_antibot(page.html):
            continue

        content = _extract_text(page.html)
        if len(content) >= 200:
            return (
                content,
                _extract_title(page.html),
                {
                    "page_fetch_method": f"scrapling_{fetcher}",
                    "page_fetch_error": local.get("error") or "",
                    "scrapling_status": page.status,
                    "scrapling_error": page.error or "",
                },
            )

    # 第3层：直接 Playwright（最后手段）
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                bypass_csp=True,
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}};
            """)
            page_obj = context.new_page()
            page_obj.goto(url, wait_until="domcontentloaded", timeout=min(timeout_seconds * 1000, 30000))
            page_obj.wait_for_timeout(2000)
            html = page_obj.content()
            context.close()
            browser.close()

            if html and not _looks_antibot(html):
                content = _extract_text(html)
                if len(content) >= 200:
                    return (
                        content,
                        _extract_title(html),
                        {
                            "page_fetch_method": "playwright",
                            "page_fetch_error": "",
                        },
                    )
    except ImportError:
        pass
    except Exception:
        pass

    return (
        "",
        "",
        {
            "page_fetch_method": "failed",
            "page_fetch_error": local.get("error") or "all fetch methods failed",
        },
    )


class ScraplingSearchAdapter(SourceAdapter):
    source_family = "scrapling_search"
    timeout_seconds = 10
    max_documents = 20

    def __init__(self):
        self.last_summary: dict = {}

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        cfg = load_config()
        self.last_summary = {
            "status": "collecting",
            "count": 0,
            "query_count": 0,
            "serp_ok_count": 0,
            "parsed_url_count": 0,
            "fetched_url_count": 0,
            "failed_url_count": 0,
            "detail": "采集中...",
        }
        if not cfg.enabled and not budget.get("enabled"):
            self.last_summary.update({"status": "disabled", "detail": "Scrapling 未启用"})
            return []

        max_documents = int(budget.get("max_documents") or self.max_documents)
        queries = build_field_queries(company_identity, field_targets)
        if not queries:
            self.last_summary.update({"status": "empty", "detail": "没有可搜索字段"})
            return []
        queries = queries[:cfg.max_queries_per_company]
        self.last_summary["query_count"] = len(queries) * max(1, len(cfg.providers))

        search_results: list[SearchResult] = []
        serp_ok_count = 0
        serp_failed_count = 0
        serp_tasks = [
            (provider, field_query.query)
            for field_query in queries
            for provider in cfg.providers
        ]
        with ThreadPoolExecutor(
            max_workers=_bounded_workers(cfg.max_concurrency, len(serp_tasks))
        ) as executor:
            futures = {}
            for provider, query in serp_tasks:
                futures[executor.submit(
                    fetch_serp,
                    provider,
                    query,
                    fetcher=cfg.fetcher,
                    timeout_seconds=cfg.timeout_seconds,
                )] = (provider, query)
                if cfg.search_delay_seconds > 0:
                    time.sleep(cfg.search_delay_seconds)

            for future in as_completed(futures):
                provider, query = futures[future]
                serp = future.result()
                if serp.status == "unavailable":
                    raise RuntimeError(f"Scrapling unavailable: {serp.error or 'dependency not installed'}")
                if serp.status != "ok":
                    serp_failed_count += 1
                    continue
                serp_ok_count += 1
                search_results.extend(parse_serp(provider, serp.html, query=query))
        self.last_summary["serp_ok_count"] = serp_ok_count

        search_results = _filter_relevant_results(
            search_results,
            company_identity,
            limit=cfg.max_urls_per_company,
        )
        urls = dedupe_urls([r.url for r in search_results], limit=cfg.max_urls_per_company)
        if not urls:
            detail = (
                f"SERP成功 {serp_ok_count}/{len(serp_tasks)}，"
                f"解析URL 0；失败SERP {serp_failed_count}"
            )
            self.last_summary.update({
                "status": "empty",
                "detail": detail,
                "serp_failed_count": serp_failed_count,
            })
            return []
        self.last_summary["parsed_url_count"] = len(urls)

        by_url = {r.url: r for r in search_results}
        official_host = (
            company_identity.get("website_host")
            or company_identity.get("official_domain")
            or ""
        )
        docs: list[SourceDocument] = []
        failed_url_count = 0
        fetch_errors: dict[str, int] = {}
        with ThreadPoolExecutor(
            max_workers=_bounded_workers(cfg.max_concurrency, len(urls))
        ) as executor:
            futures = {
                executor.submit(
                    _fetch_page_content,
                    url,
                    fallback_fetcher=cfg.fetcher,
                    timeout_seconds=cfg.timeout_seconds,
                ): url
                for url in urls
            }
            for future in as_completed(futures):
                url = futures[future]
                content, page_title, fetch_metadata = future.result()
                if not content:
                    failed_url_count += 1
                    err = (fetch_metadata.get("page_fetch_error") or "empty")[:80]
                    fetch_errors[err] = fetch_errors.get(err, 0) + 1
                    continue
                result = by_url.get(url)
                source_family, trust_tier, source_score = classify_source(url, official_host)
                title = page_title or (result.title if result else "")
                docs.append(SourceDocument(
                    source_family=self.source_family,
                    source_url=url,
                    title=title,
                    content=content[:50000],
                    raw_text=content,
                    intent=(result.query if result else "scrapling_search"),
                    trust_tier=trust_tier,
                    source_score=source_score,
                    entity_score=0.7,
                    metadata={
                        "provider": result.provider if result else "",
                        "rank": result.rank if result else None,
                        "snippet": result.snippet if result else "",
                        "classified_source_family": source_family,
                        "domain": urlparse(url).netloc.lower(),
                        **fetch_metadata,
                    },
                ))
                if len(docs) >= max_documents:
                    break
        self.last_summary.update({
            "status": "ok" if docs else "empty",
            "count": len(docs),
            "fetched_url_count": len(docs),
            "failed_url_count": failed_url_count,
            "detail": (
                f"SERP成功 {serp_ok_count}/{len(serp_tasks)}，"
                f"解析URL {len(urls)}，有效文档 {len(docs)}"
                + (f"，失败 {failed_url_count}，主要原因：{next(iter(fetch_errors))}" if fetch_errors else "")
            ),
            "serp_failed_count": serp_failed_count,
        })
        return docs

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        cfg = load_config()
        max_queries = min(
            len(field_targets) * 2 * max(1, len(cfg.providers)),
            cfg.max_queries_per_company * max(1, len(cfg.providers)),
        )
        return {
            "estimated_tokens": 0,
            "estimated_queries": max_queries,
            "source_family": self.source_family,
        }


ADAPTER_REGISTRY["scrapling_search"] = ScraplingSearchAdapter
