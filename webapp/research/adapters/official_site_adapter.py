"""OfficialSiteAdapter — 官网采集适配器，封装 OfficialAgent 爬虫逻辑。

Wraps OfficialAgent crawl logic via standard SourceAdapter interface.
Fixed crawl of 5 key paths: /, /about, /pricing, /customers, /blog.
Max 5 URLs, 15s timeout per URL.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import requests
from urllib.parse import urljoin

from research.source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY
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

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        for path in paths:
            url = urljoin(base_url, path)

            try:
                resp = session.get(url, timeout=timeout, allow_redirects=True)

                if resp.status_code != 200:
                    logger.debug(
                        "OfficialSiteAdapter: %s HTTP %s",
                        url,
                        resp.status_code,
                    )
                    continue

                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    logger.debug(
                        "OfficialSiteAdapter: %s non-HTML (%s)",
                        url,
                        content_type[:60],
                    )
                    continue

                html = resp.text
                if not html:
                    logger.debug("OfficialSiteAdapter: %s empty body", url)
                    continue

                # 正文提取: trafilatura 优先，回退到简单 HTML 清洗
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

                # 单页截断
                if len(text) > MAX_CHARS_PER_PAGE:
                    text = text[: MAX_CHARS_PER_PAGE - 3].rstrip() + "..."

                # 构建 SourceDocument
                title = f"{display_name or website_host}{path}"
                intent = PATH_INTENT_MAP.get(path, "company_overview")

                doc = SourceDocument(
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
                    metadata={
                        "path": path,
                        "website_host": website_host,
                    },
                )
                documents.append(doc)

            except requests.Timeout:
                logger.debug(
                    "OfficialSiteAdapter: %s timeout (%ss)", url, timeout
                )
            except requests.ConnectionError:
                logger.debug(
                    "OfficialSiteAdapter: %s connection failed", url
                )
            except Exception:
                logger.warning(
                    "OfficialSiteAdapter: %s error",
                    url,
                    exc_info=True,
                )

        logger.info(
            "OfficialSiteAdapter: %d/%d pages from %s",
            len(documents),
            len(paths),
            website_host,
        )
        return documents

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
