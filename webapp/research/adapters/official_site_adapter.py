"""OfficialSiteAdapter — 官网采集适配器，封装 OfficialAgent 爬虫逻辑。

Wraps OfficialAgent crawl logic via standard SourceAdapter interface.
Multi-source discovery: fixed key paths + sitemap.xml + homepage internal links.
Max 10+ URLs, 20s timeout per URL. Anti-bot fallback via Scrapling StealthyFetcher → Playwright.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import requests
from urllib.parse import urljoin, urlparse

from research.source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY
from research.scrapling.page_fetcher import fetch_html
from research_agents.agents.official_agent import _extract_text_from_html

logger = logging.getLogger(__name__)

# ── 适配器配置 ────────────────────────────────────────────────────────────────

ADAPTER_PATHS = [
    "/", "/about", "/pricing", "/customers", "/blog",
    "/products", "/team", "/docs", "/technology",
]

PATH_INTENT_MAP: dict[str, str] = {
    "/": "company_overview",
    "/about": "company_overview",
    "/pricing": "pricing_detail",
    "/customers": "customer_detail",
    "/blog": "news_and_content",
    "/products": "product_detail",
    "/team": "team_detail",
    "/docs": "documentation",
    "/technology": "technology_detail",
}

# 常见 sitemap 路径
SITEMAP_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/wp-sitemap.xml"]

# 路径关键词 → 意图映射（用于 sitemap 发现的未知路径）
_PATH_KEYWORD_INTENT: dict[str, str] = {
    "product": "product_detail",
    "feature": "product_detail",
    "pricing": "pricing_detail",
    "plan": "pricing_detail",
    "customer": "customer_detail",
    "case": "customer_detail",
    "testimonial": "customer_detail",
    "about": "company_overview",
    "team": "team_detail",
    "career": "team_detail",
    "blog": "news_and_content",
    "news": "news_and_content",
    "press": "news_and_content",
    "doc": "documentation",
    "guide": "documentation",
    "tech": "technology_detail",
    "platform": "technology_detail",
    "api": "technology_detail",
    "solutions": "product_detail",
    "use-case": "customer_detail",
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


def _discover_sitemap_urls(base_url: str, timeout: int = 15, limit: int = 20) -> list[str]:
    """尝试从 sitemap.xml 发现更多页面路径。"""
    import xml.etree.ElementTree as ET

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for sitemap_path in SITEMAP_PATHS:
        try:
            sitemap_url = urljoin(base_url, sitemap_path)
            resp = session.get(sitemap_url, timeout=timeout, allow_redirects=True)
            if resp.status_code != 200:
                continue

            content_type = resp.headers.get("Content-Type", "")
            if "xml" not in content_type and not resp.text.strip().startswith("<?xml"):
                continue

            root = ET.fromstring(resp.text)
            # 支持标准 sitemap 和 sitemap index
            ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            urls = []

            # 先尝试获取 <url> 元素
            locs = root.findall(".//ns:url/ns:loc", ns)
            if not locs:
                # 可能是 sitemap index — 获取子 sitemap
                locs = root.findall(".//ns:sitemap/ns:loc", ns)

            for loc in locs:
                if loc.text:
                    full_url = loc.text.strip()
                    # 提取相对路径
                    parsed = urlparse(full_url)
                    if parsed.netloc and parsed.netloc != urlparse(base_url).netloc:
                        continue  # 跳过外部链接
                    path = parsed.path or "/"
                    if path not in ("/", "") and path not in urls:
                        urls.append(path)
                    if len(urls) >= limit:
                        break

            if urls:
                logger.info("Sitemap %s: found %d URLs", sitemap_path, len(urls))
                return urls[:limit]
        except Exception:
            continue

    return []


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
    timeout_seconds: int = 20
    scrapling_timeout_seconds: int = 60  # Cloudflare 求解+network_idle 需 30-60s
    max_documents: int = 10

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
                - max_documents: 最大返回文档数（上限 10）
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
        max_docs = budget.get("max_documents", self.max_documents)
        timeout = budget.get("timeout_seconds", self.timeout_seconds)

        # ── 路径发现：固定路径 + Sitemap + 首页链接 ──
        paths = list(ADAPTER_PATHS)

        # Sitemap 发现
        sitemap_urls = _discover_sitemap_urls(base_url, timeout=timeout)
        if sitemap_urls:
            logger.info("Sitemap discovered %d URLs for %s", len(sitemap_urls), website_host)
            paths.extend(sitemap_urls)

        # 去重并限制
        seen = set()
        unique_paths = []
        for p in paths:
            norm = p.rstrip("/") or "/"
            if norm not in seen:
                seen.add(norm)
                unique_paths.append(p)
        paths = unique_paths[:max_docs]
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents: list[SourceDocument] = []
        blocked_urls: list[SourceDocument] = []  # (url, path) 待浏览器回退
        http_statuses: list[int] = []
        cf_detected: bool = False
        consecutive_cf_blocks = 0  # 连续 CF 拦截计数，>=3 时跳过剩余 requests 路径
        MAX_BLOCKED_FALLBACK = 5  # 批量浏览器回退最多处理 5 个 URL

        # 优先使用 Scrapling Fetcher（curl-cffi 模拟 Chrome TLS 指纹，绕过基础 CF 检测）
        _use_scrapling = True
        try:
            fetch_html("about:blank", fetcher="auto", timeout_seconds=1)
        except (ImportError, ModuleNotFoundError):
            _use_scrapling = False
            logger.info("Scrapling Fetcher unavailable, falling back to requests")

        for path in paths:
            # 快速路径：连续 CF 拦截 >= 3，判定全站反爬，停止尝试
            if consecutive_cf_blocks >= 3:
                url = urljoin(base_url, path)
                blocked_urls.append((url, path, 403))
                logger.debug("OfficialSiteAdapter: skipping %s (site-wide CF detected)", path)
                continue

            url = urljoin(base_url, path)

            try:
                if _use_scrapling:
                    # curl-cffi Fetcher（模拟 Chrome TLS）— 比 plain requests 更能穿透 CF
                    result = fetch_html(url, fetcher="auto", timeout_seconds=timeout)
                    if result.status == "unavailable":
                        _use_scrapling = False
                        resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                                          timeout=timeout, allow_redirects=True)
                        html_text = resp.text
                        http_status = resp.status_code
                    elif result.status != "ok":
                        http_statuses.append(403)
                        body = (result.error or "")[:2000].lower()
                        cf_markers_found = any(m in body for m in ANTIBOT_MARKERS)
                        if cf_markers_found:
                            cf_detected = True
                            consecutive_cf_blocks += 1
                        else:
                            consecutive_cf_blocks = 0
                        if result.status == "failed":
                            blocked_urls.append((url, path, 403))
                            logger.warning("Blocked %s (scrapling %s), queued for browser fallback", url, result.status)
                        continue
                    else:
                        html_text = result.html or ""
                        http_status = 200
                else:
                    resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                                      timeout=timeout, allow_redirects=True)
                    html_text = resp.text or ""
                    http_status = resp.status_code

                if http_status != 200:
                    http_statuses.append(http_status)
                    body = (html_text or "")[:2000].lower()
                    cf_markers_found = any(m in body for m in ANTIBOT_MARKERS)
                    if cf_markers_found:
                        cf_detected = True
                        consecutive_cf_blocks += 1
                    else:
                        consecutive_cf_blocks = 0
                    is_blocked = (
                        http_status in (401, 403, 429, 503)
                        and cf_markers_found
                    )
                    if not is_blocked and http_status == 403:
                        is_blocked = True
                        consecutive_cf_blocks += 1
                    if is_blocked:
                        blocked_urls.append((url, path, http_status))
                        logger.warning("Blocked %s (HTTP %s), queued for browser fallback", url, http_status)
                    continue

                consecutive_cf_blocks = 0  # 成功获取，重置计数器

                if not html_text:
                    continue

                if _looks_antibot_html(html_text):
                    cf_detected = True
                    consecutive_cf_blocks += 1
                    blocked_urls.append((url, path, http_status))
                    logger.warning("Blocked by anti-bot page %s, queued for browser fallback", url)
                    continue

                text = _extract_content_text(html_text)
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

        # 限制批量回退 URL 数量：反爬站点只尝试关键页面
        if blocked_urls:
            blocked_urls = blocked_urls[:MAX_BLOCKED_FALLBACK]

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
            logger.warning(
                "Official site fully blocked by anti-bot protection "
                "(%d/%d URLs, HTTP %s)",
                len(blocked_urls), len(paths),
                http_statuses[0] if http_statuses else 403,
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

        CF 求解有 30s 硬超时（避免内部无限重试），失败后跳过后续求解。
        """
        import concurrent.futures

        documents: list[SourceDocument] = []
        if not blocked_urls:
            return documents

        # 方案 A：StealthyFetcher（浏览器指纹绕过基础反爬，不做 CF 求解避免死循环）
        # 策略：只取前 3 个关键路径（/, /about, /pricing），30s 硬超时
        try:
            from scrapling.fetchers import StealthyFetcher
            fetcher = StealthyFetcher()
            key_urls = blocked_urls[:3]  # 只尝试前 3 个关键 URL
            logger.info("Batch StealthyFetcher: %d key URLs (solve_cloudflare=False)", len(key_urls))

            for url, path, http_status in key_urls:
                try:
                    def _fetch():
                        return fetcher.fetch(
                            url, headless=True, network_idle=True,
                            solve_cloudflare=False, timeout=60000,
                        )
                    future = concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(_fetch)
                    page = future.result(timeout=30)
                    html = str(page.html_content) if hasattr(page, 'html_content') else str(page)
                except concurrent.futures.TimeoutError:
                    logger.warning("StealthyFetcher TIMEOUT (30s): %s", url)
                    continue
                except Exception as e:
                    logger.warning("StealthyFetcher error: %s %s", url, e)
                    continue

                if _looks_antibot_html(html):
                    logger.warning("StealthyFetcher still blocked (no CF solve): %s", url)
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

        # 方案 B：直接 Playwright（Scrapling 不可用时/StealthyFetcher 未获取到文档）
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright not available for batch fallback")
            return documents

        # 限制 3 个关键 URL，避免全量超时
        pw_urls = blocked_urls[:3]
        logger.info("Batch Playwright: %d key URLs with shared session", len(pw_urls))
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

                for url, path, http_status in pw_urls:
                    page = context.new_page()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=15000)
                        page.wait_for_timeout(2000)
                        title = page.title()
                        if "just a moment" in title.lower():
                            try:
                                page.wait_for_function(
                                    "document.title.toLowerCase().indexOf('just a moment') === -1",
                                    timeout=10000,
                                )
                                page.wait_for_timeout(1000)
                            except Exception:
                                logger.warning("CF wait timeout: %s", url)
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
        intent = PATH_INTENT_MAP.get(path)
        if not intent:
            # 从路径推断意图
            for keyword, fallback_intent in _PATH_KEYWORD_INTENT.items():
                if keyword in path.lower():
                    intent = fallback_intent
                    break
            if not intent:
                intent = "company_overview"
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
