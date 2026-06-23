"""OfficialSiteAdapter — 官网采集适配器，封装 OfficialAgent 爬虫逻辑。

Wraps OfficialAgent crawl logic via standard SourceAdapter interface.
Fixed crawl of 5 key paths: /, /about, /pricing, /customers, /blog.
Max 5 URLs, 15s timeout per URL.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import requests
from urllib.parse import urljoin

from research.source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY
from research.scrapling.page_fetcher import fetch_html
from research_agents.agents.official_agent import _extract_text_from_html

logger = logging.getLogger(__name__)

# ── 适配器配置 ────────────────────────────────────────────────────────────────

ADAPTER_PATHS = ["/", "/about", "/pricing", "/customers", "/blog"]

PATH_INTENT_MAP: dict[str, str] = {
    "/": "company_overview",
    "/about": "company_overview",
    "/pricing": "pricing_detail",
    "/customers": "customer_detail",
    "/blog": "news_and_content",
}

MAX_CHARS_PER_PAGE = 5000
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

ANTIBOT_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "verify you are human",
    "checking your browser",
    "cf-chl-",
    "/cdn-cgi/challenge-platform",
)


def _looks_antibot_html(html: str) -> bool:
    body = (html or "")[:8000].lower()
    if any(marker in body for marker in ANTIBOT_MARKERS):
        return True
    if "cloudflare" not in body:
        return False

    visible = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html or "")
    visible = re.sub(r"(?is)<[^>]+>", " ", visible)
    visible = re.sub(r"\s+", " ", visible).strip()
    return len(visible) < 120


def _extract_content_text(html: str) -> str:
    text = ""
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
        )
        if extracted:
            text = extracted
    except Exception:
        pass

    if not text:
        text = _extract_text_from_html(html)

    if len(text) > MAX_CHARS_PER_PAGE:
        text = text[: MAX_CHARS_PER_PAGE - 3].rstrip() + "..."
    return text


# ── OfficialSiteAdapter ──────────────────────────────────────────────────────

class OfficialSiteAdapter(SourceAdapter):
    """官网采集适配器。

    Wraps OfficialAgent crawl logic. Max 5 URLs, 15s timeout per URL.
    Collects from /, /about, /pricing, /customers, /blog paths.

    Usage:
        adapter = OfficialSiteAdapter(timeout_seconds=15, max_documents=5)
        docs = adapter.collect(
            company_identity={"display_name": "Anthropic", "website_host": "anthropic.com"},
            field_targets=["company_description", "products", "funding"],
            budget={"max_documents": 5, "timeout_seconds": 15},
        )
    """

    source_family = "official_site"
    timeout_seconds: int = 15
    scrapling_timeout_seconds: int = 60  # Cloudflare 求解+network_idle 需 30-60s
    max_documents: int = 5

    # ── 核心采集 ──

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行官网抓取，返回 SourceDocument 列表。

        Args:
            company_identity: 公司身份信息，至少包含 website_host 或 website_url。
            field_targets: 目标字段键列表（当前用于日志，未来可用于动态选择路径）。
            budget: 预算约束 dict，可包含:
                - max_documents: 最大返回文档数（上限 5）
                - timeout_seconds: 单页请求超时秒数

        Returns:
            SourceDocument 列表，不超过 max_documents。
            采集失败时返回空列表（不抛异常）。
        """
        ctx = self._build_identity_context(company_identity)
        website_host = ctx["website_host"]
        display_name = ctx["display_name"]

        if not website_host:
            logger.warning(
                "OfficialSiteAdapter: missing website_host in company_identity"
            )
            return []

        base_url = f"https://{website_host}"

        # Budget 覆盖
        max_docs = min(
            budget.get("max_documents", self.max_documents),
            len(ADAPTER_PATHS),
        )
        timeout = budget.get("timeout_seconds", self.timeout_seconds)

        paths = ADAPTER_PATHS[:max_docs]
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents: list[SourceDocument] = []
        blocked_urls: list[SourceDocument] = []  # (url, path) 待浏览器回退
        http_statuses: list[int] = []
        cf_detected: bool = False

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        for path in paths:
            url = urljoin(base_url, path)

            try:
                resp = session.get(url, timeout=timeout, allow_redirects=True)

                if resp.status_code != 200:
                    http_statuses.append(resp.status_code)
                    body = (resp.text or "")[:2000].lower()
                    cf_markers_found = any(m in body for m in ANTIBOT_MARKERS)
                    if cf_markers_found:
                        cf_detected = True
                    is_blocked = (
                        resp.status_code in (401, 403, 429, 503)
                        and cf_markers_found
                    )
                    if not is_blocked and resp.status_code == 403:
                        is_blocked = True
                    if is_blocked:
                        blocked_urls.append((url, path, resp.status_code))
                        logger.warning("Blocked %s (HTTP %s), queued for browser fallback", url, resp.status_code)
                    continue

                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    continue

                html = resp.text
                if not html:
                    continue

                if _looks_antibot_html(html):
                    cf_detected = True
                    blocked_urls.append((url, path, resp.status_code))
                    logger.warning("Blocked by anti-bot page %s, queued for browser fallback", url)
                    continue

                text = _extract_content_text(html)
                if not text.strip():
                    continue

                documents.append(
                    self._build_document(
                        url=url, path=path, display_name=display_name,
                        website_host=website_host, fetched_at=fetched_at,
                        text=text,
                    )
                )

            except requests.Timeout:
                logger.debug("OfficialSiteAdapter: %s timeout (%ss)", url, timeout)
            except requests.ConnectionError:
                logger.debug("OfficialSiteAdapter: %s connection failed", url)
            except Exception:
                logger.warning("OfficialSiteAdapter: %s error", url, exc_info=True)

        # 批量浏览器回退：所有被 CF 拦截的 URL 共用一个浏览器会话
        if blocked_urls:
            browser_docs = self._collect_blocked_urls_with_browser(
                blocked_urls=blocked_urls,
                display_name=display_name,
                website_host=website_host,
                fetched_at=fetched_at,
                timeout=timeout,
                cf_detected=cf_detected,
            )
            documents.extend(browser_docs)

        if not documents and blocked_urls:
            raise RuntimeError(
                "Official site blocked by anti-bot protection "
                f"({len(blocked_urls)}/{len(paths)} URLs, HTTP {http_statuses[0] if http_statuses else 403})"
            )

        logger.info(
            "OfficialSiteAdapter: %d/%d pages from %s",
            len(documents),
            len(paths),
            website_host,
        )
        return documents

    def _collect_with_scrapling(
        self,
        *,
        url: str,
        path: str,
        display_name: str,
        website_host: str,
        fetched_at: str,
        timeout: int,
        fetcher: str,
        http_status: int,
        skip_fetcher: bool = False,
    ) -> Optional[SourceDocument]:
        # 级联策略：
        # 1. Scrapling Fetcher（curl-cffi, 快）— 可被 skip_fetcher 跳过
        # 2. Scrapling StealthyFetcher（Playwright + Cloudflare 求解, 慢）
        # 3. 直接用 Playwright（Scrapling 不可用时）
        if fetcher in ("stealthy", "auto", None, ""):
            if skip_fetcher:
                fetchers_to_try = ("stealthy",)
            else:
                fetchers_to_try = ("fetcher", "stealthy")
        else:
            fetchers_to_try = (fetcher,)

        for try_fetcher in fetchers_to_try:
            try:
                result = fetch_html(url, fetcher=try_fetcher, timeout_seconds=self.scrapling_timeout_seconds)
            except (ImportError, ModuleNotFoundError):
                logger.warning("Scrapling unavailable, trying direct Playwright: %s", url)
                return self._collect_with_playwright(
                    url=url, path=path, display_name=display_name,
                    website_host=website_host, fetched_at=fetched_at,
                    timeout=timeout, http_status=http_status,
                )
            except Exception as e:
                logger.warning("Scrapling error: %s fetcher=%s %s", url, try_fetcher, e)
                continue

            if result.status != "ok" or not result.html:
                logger.warning("Scrapling fallback FAILED: %s fetcher=%s status=%s error=%s", url, try_fetcher, result.status, result.error[:120] if result.error else "")
                continue
            logger.info("Scrapling fallback OK: %s fetcher=%s html=%s bytes", url, try_fetcher, len(result.html))
            if _looks_antibot_html(result.html):
                logger.warning("Scrapling fallback STILL BLOCKED: %s fetcher=%s", url, try_fetcher)
                continue

            text = _extract_content_text(result.html)
            if not text.strip():
                logger.warning("Scrapling fallback EMPTY TEXT: %s fetcher=%s", url, try_fetcher)
                continue

            return self._build_document(
                url=url, path=path, display_name=display_name,
                website_host=website_host, fetched_at=fetched_at,
                text=text,
                metadata_extra={
                    "scrapling_fallback": True,
                    "scrapling_fetcher": try_fetcher,
                    "http_status": http_status,
                },
            )

        # All Scrapling fetchers failed — try direct Playwright as last resort
        return self._collect_with_playwright(
            url=url, path=path, display_name=display_name,
            website_host=website_host, fetched_at=fetched_at,
            timeout=timeout, http_status=http_status,
        )

    def _collect_with_playwright(
        self,
        *,
        url: str,
        path: str,
        display_name: str,
        website_host: str,
        fetched_at: str,
        timeout: int,
        http_status: int,
    ) -> Optional[SourceDocument]:
        """使用 Playwright 直接抓取（不依赖 Scrapling 封装）"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright not available: %s", url)
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    bypass_csp=True,
                )
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    window.chrome = {runtime: {}};
                """)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=min(timeout * 1000, 30000))
                # 给 SPA/SSR 页面留水合时间（Astro/Next.js/React 等）
                page.wait_for_timeout(2000)
                html = page.content()
                context.close()
                browser.close()
        except Exception as e:
            logger.warning("Playwright fallback FAILED: %s %s", url, e)
            return None

        if not html or _looks_antibot_html(html):
            logger.warning("Playwright fallback STILL BLOCKED: %s", url)
            return None

        text = _extract_content_text(html)
        if not text.strip():
            logger.warning("Playwright fallback EMPTY TEXT: %s", url)
            return None

        logger.info("Playwright fallback OK: %s html=%s bytes", url, len(html))
        return self._build_document(
            url=url, path=path, display_name=display_name,
            website_host=website_host, fetched_at=fetched_at,
            text=text,
            metadata_extra={
                "playwright_fallback": True,
                "http_status": http_status,
            },
        )

    def _collect_blocked_urls_with_browser(
        self,
        *,
        blocked_urls: list[tuple[str, str, int]],
        display_name: str,
        website_host: str,
        fetched_at: str,
        timeout: int,
        cf_detected: bool,
    ) -> list[SourceDocument]:
        """批量浏览器回退：单个 StealthyFetcher 实例处理所有被拦截 URL。

        Cloudflare Turnstile 求解后 cookie 在同一浏览器会话内持久化，
        第一个 URL 求解 CF 后，后续 URL 直接通过。
        """
        documents: list[SourceDocument] = []
        if not blocked_urls:
            return documents

        # 方案 A：单个 StealthyFetcher 实例处理所有 URL（cookie 共享）
        try:
            from scrapling.fetchers import StealthyFetcher
            fetcher = StealthyFetcher()
            logger.info("Batch StealthyFetcher: %d URLs with shared session", len(blocked_urls))

            for url, path, http_status in blocked_urls:
                try:
                    page = fetcher.fetch(
                        url, headless=True, network_idle=True,
                        solve_cloudflare=True, timeout=60000,
                    )
                    html = str(page.html_content) if hasattr(page, 'html_content') else str(page)
                except Exception as e:
                    logger.warning("StealthyFetcher error: %s %s", url, e)
                    continue

                if _looks_antibot_html(html):
                    logger.warning("StealthyFetcher STILL BLOCKED: %s", url)
                    continue

                text = _extract_content_text(html)
                if not text.strip():
                    logger.warning("StealthyFetcher EMPTY TEXT: %s", url)
                    continue

                logger.info("StealthyFetcher OK: %s html=%d bytes text=%d chars", url, len(html), len(text))
                documents.append(self._build_document(
                    url=url, path=path, display_name=display_name,
                    website_host=website_host, fetched_at=fetched_at,
                    text=text,
                    metadata_extra={
                        "scrapling_fallback": True,
                        "scrapling_fetcher": "stealthy",
                        "http_status": http_status,
                    },
                ))
            return documents
        except ImportError:
            pass

        # 方案 B：直接 Playwright（Scrapling 不可用时）
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright not available for batch fallback")
            return documents

        logger.info("Batch Playwright: %d URLs with shared session", len(blocked_urls))
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    bypass_csp=True,
                )
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    window.chrome = {runtime: {}};
                """)

                for url, path, http_status in blocked_urls:
                    page = context.new_page()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(3000)
                        title = page.title()
                        if "just a moment" in title.lower():
                            try:
                                page.wait_for_function(
                                    "document.title.toLowerCase().indexOf('just a moment') === -1",
                                    timeout=15000,
                                )
                                page.wait_for_timeout(2000)
                            except Exception:
                                logger.warning("CF solve timeout: %s", url)
                        html = page.content()
                        page.close()

                        if _looks_antibot_html(html):
                            logger.warning("Playwright STILL BLOCKED: %s", url)
                            continue

                        text = _extract_content_text(html)
                        if not text.strip():
                            logger.warning("Playwright EMPTY TEXT: %s", url)
                            continue

                        logger.info("Playwright OK: %s html=%d bytes text=%d chars", url, len(html), len(text))
                        documents.append(self._build_document(
                            url=url, path=path, display_name=display_name,
                            website_host=website_host, fetched_at=fetched_at,
                            text=text,
                            metadata_extra={
                                "playwright_fallback": True,
                                "http_status": http_status,
                            },
                        ))
                    except Exception as e:
                        page.close()
                        logger.warning("Playwright error: %s %s", url, e)
                        continue

                context.close()
                browser.close()
        except Exception as e:
            logger.warning("Batch Playwright failed: %s", e)

        return documents

    def _build_document(
        self,
        *,
        url: str,
        path: str,
        display_name: str,
        website_host: str,
        fetched_at: str,
        text: str,
        metadata_extra: Optional[dict] = None,
    ) -> SourceDocument:
        title = f"{display_name or website_host}{path}"
        intent = PATH_INTENT_MAP.get(path, "company_overview")
        metadata = {
            "path": path,
            "website_host": website_host,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        return SourceDocument(
            source_family=self.source_family,
            source_url=url,
            title=title,
            content=text,
            raw_text=text,
            intent=intent,
            trust_tier="high",
            source_score=0.95,
            entity_score=0.95,
            fetched_at=fetched_at,
            metadata=metadata,
        )

    # ── 成本估算 ──

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算官网抓取成本。

        HTTP 请求无 API 费用；token 估算基于预期页面内容量。
        """
        max_docs = budget.get("max_documents", self.max_documents)
        return {
            "estimated_tokens": max_docs * 3000,
            "estimated_queries": max_docs,
            "source_family": self.source_family,
        }


# ── 注册到全局注册表 ──

ADAPTER_REGISTRY["official_site"] = OfficialSiteAdapter
