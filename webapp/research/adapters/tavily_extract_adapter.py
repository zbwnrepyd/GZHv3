"""Tavily Extract 适配器 — 通过 Tavily Extract API 获取网页原始内容。

与 tavily_search 不同，tavily_extract 直接对指定 URL 列表进行内容提取，
返回每个 URL 的 raw_content（全文正文）。最大支持 20 个 URL/次请求。

SPEC Section 8: Tavily Extract 适配器，source_family="tavily_extract"。
"""
from __future__ import annotations

import logging
import requests
from datetime import datetime, timezone

from ..source_adapter import SourceAdapter, SourceDocument

logger = logging.getLogger(__name__)

# Tavily Extract API endpoint
_TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

# 可信度高的页面路径关键词，用于自动提升 trust_tier
_HIGH_TRUST_PATH_KEYWORDS = ("/about", "/security", "/privacy", "/legal", "/compliance")


class TavilyExtractAdapter(SourceAdapter):
    """Tavily Extract 来源适配器。

    使用 Tavily 的 extract API 对指定 URL 列表进行批量内容提取。
    source_family = "tavily_extract"，返回的 SourceDocument 包含从
    每个 URL 提取的 raw_content 作为 content（经清洗后）。
    """

    source_family = "tavily_extract"

    # ── 默认值 ──
    timeout_seconds: int = 60
    max_documents: int = 20
    extract_depth: str = "basic"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.extract_depth = kwargs.get("extract_depth", "basic")
        self._session: requests.Session | None = None

    # ── 核心接口 ──

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """通过 Tavily Extract API 获取指定 URL 列表的全文内容。

        Args:
            company_identity: 公司身份信息，用于发现待提取 URL。
            field_targets: 目标字段键列表（用于调整提取优先级）。
            budget: 预算约束，可包含:
                - max_documents: 最大返回文档数（默认 20，上限 20）
                - max_queries: 最大 API 调用次数（每次可传 20 个 URL）
                - timeout_seconds: 请求超时秒数
                - urls: 显式指定要提取的 URL 列表

        Returns:
            SourceDocument 列表。采集失败时返回空列表（不抛异常）。
        """
        max_docs = min(budget.get("max_documents", self.max_documents), 20)
        timeout = budget.get("timeout_seconds", self.timeout_seconds)
        max_queries = budget.get("max_queries", 1)

        # 确定目标 URL 列表
        target_urls = self._discover_urls(company_identity, budget, max_docs)
        if not target_urls:
            logger.warning("TavilyExtract: 无可提取 URL")
            return []

        docs: list[SourceDocument] = []
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 每批最多 20 个 URL，按 max_queries 限制批次数
        batch_size = min(20, max_docs)
        for batch_idx in range(min(max_queries, (len(target_urls) + batch_size - 1) // batch_size)):
            batch_urls = target_urls[batch_idx * batch_size : (batch_idx + 1) * batch_size]
            if not batch_urls:
                break

            try:
                result = self._call_extract_api(batch_urls, timeout)
            except Exception as e:
                logger.error("TavilyExtract API 调用失败 (batch %d): %s", batch_idx + 1, e)
                continue

            # 解析成功提取的结果
            for item in result.get("results", []) or []:
                url = item.get("url", "")
                raw = item.get("raw_content", "")
                if not raw:
                    continue

                title = url.rstrip("/").split("/")[-1] or url
                doc = SourceDocument(
                    source_family=self.source_family,
                    source_url=url,
                    title=title,
                    content=raw[:50000],
                    raw_text=raw,
                    intent=self._infer_intent(url, field_targets),
                    trust_tier=self._trust_tier_for_url(url),
                    source_score=0.7,  # Tavily extract 来源质量默认较高
                    entity_score=0.5,  # 待 evidence_ranker 评分更新
                    fetched_at=fetched_at,
                    metadata={
                        "extract_depth": self.extract_depth,
                        "extracted_length": len(raw),
                    },
                )
                docs.append(doc)

            # 记录失败的 URL
            for fail in result.get("failed_results", []) or []:
                logger.warning(
                    "TavilyExtract 提取失败: %s — %s",
                    fail.get("url", ""),
                    fail.get("error", "未知错误"),
                )

        logger.info("TavilyExtract: %d/%d URL 提取成功", len(docs), len(target_urls))
        return self._truncate_list(docs)

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算本次提取的成本。

        Tavily Extract API 每次调用最多 20 个 URL，返回原文文本。
        预估 token 按每 URL 平均 3000 tokens 估算。
        """
        max_docs = min(budget.get("max_documents", self.max_documents), 20)
        max_queries = budget.get("max_queries", 1)
        url_count = min(max_docs, max_queries * 20)
        return {
            "estimated_tokens": url_count * 3000,
            "estimated_queries": max_queries,
            "source_family": self.source_family,
        }

    # ── 私有方法 ──

    def _discover_urls(self, company_identity: dict, budget: dict, max_docs: int) -> list[str]:
        """发现待提取的目标 URL 列表。

        优先级:
        1. budget 中显式传入的 urls 列表
        2. 从 company_identity 的 website 推导关键页面 URL
        """
        # 显式传入的 URL 优先
        explicit = budget.get("urls", [])
        if isinstance(explicit, list) and explicit:
            return explicit[:max_docs]

        # 从公司身份信息推导
        identity = self._build_identity_context(company_identity)
        website_host = identity["website_host"]
        if not website_host:
            return []

        scheme = "https"
        website_url = company_identity.get("website_url", "")
        if website_url.startswith("http://"):
            scheme = "http"

        # 核心页面路径
        sub_paths = [
            "",
            "/about",
            "/products",
            "/pricing",
            "/blog",
            "/careers",
            "/contact",
            "/security",
            "/company",
            "/team",
        ]

        urls = []
        for path in sub_paths[:max_docs]:
            urls.append(f"{scheme}://{website_host}{path}")
        return urls

    def _call_extract_api(self, urls: list[str], timeout: int) -> dict:
        """调用 Tavily Extract API，支持 API Key 轮换。"""
        keys = _get_tavily_keys()
        if not keys:
            return {"error": "TAVILY_API_KEYS not configured", "results": []}

        last_error = ""
        for index, api_key in enumerate(keys):
            try:
                session = self._get_session(timeout)
                body = {
                    "api_key": api_key,
                    "urls": urls,
                    "include_images": False,
                    "extract_depth": self.extract_depth,
                }
                resp = session.post(
                    _TAVILY_EXTRACT_URL,
                    json=body,
                    timeout=(30, timeout),
                )
                if resp.status_code >= 400:
                    last_error = _extract_error_text(resp)
                    if _is_quota_response(resp) and index < len(keys) - 1:
                        logger.info("TavilyExtract: Key #%d 额度耗尽，尝试下一个", index + 1)
                        continue
                    # 非额度错误不重试，直接返回
                    return {"error": last_error, "results": []}

                data = resp.json()
                return data

            except requests.exceptions.Timeout:
                last_error = f"请求超时 (batch={len(urls)} urls)"
                if index < len(keys) - 1:
                    logger.info("TavilyExtract: Key #%d 超时，尝试下一个", index + 1)
                    continue
            except requests.exceptions.ConnectionError:
                last_error = "无法连接到 Tavily Extract API"
                if index < len(keys) - 1:
                    continue
            except Exception as e:
                last_error = str(e)
                if index < len(keys) - 1:
                    continue

        return {"error": last_error or "Tavily Extract 请求失败", "results": []}

    def _get_session(self, timeout: int) -> requests.Session:
        """获取或创建复用的 requests.Session。"""
        if self._session is None:
            from pipeline import _tavily_proxy
            self._session = requests.Session()
            proxies = _tavily_proxy()
            if proxies:
                self._session.proxies.update(proxies)
        # 按需更新 timeout 设置（Session 本身不直接支持 timeout 属性，
        # 通过每个请求的 timeout 参数控制）
        return self._session

    @staticmethod
    def _infer_intent(url: str, field_targets: list[str]) -> str:
        """根据 URL 路径和 field_targets 推断采集意图。"""
        url_lower = url.lower()
        intent_map = {
            "/about": "company_overview",
            "/company": "company_overview",
            "/products": "product_detail",
            "/pricing": "pricing_details",
            "/blog": "news",
            "/careers": "company_overview",
            "/team": "founders",
            "/security": "company_overview",
            "/contact": "company_overview",
        }
        for path_key, intent in intent_map.items():
            if path_key in url_lower:
                return intent
        return "company_overview"

    @staticmethod
    def _trust_tier_for_url(url: str) -> str:
        """根据 URL 判断可信度层级。公司官网首页/About 等高可信度。"""
        url_lower = url.lower()
        for kw in _HIGH_TRUST_PATH_KEYWORDS:
            if kw in url_lower:
                return "high"
        return "medium"


# ── 模块级辅助函数 ──

def _get_tavily_keys() -> list[str]:
    """获取 Tavily API Key 列表（支持多 Key 轮换）。"""
    from config import config as cfg
    keys = getattr(cfg, "TAVILY_API_KEYS", None)
    if keys:
        return keys
    key = getattr(cfg, "TAVILY_API_KEY", "")
    return [key] if key else []


def _is_quota_response(resp) -> bool:
    """判断响应是否为额度耗尽错误。"""
    if resp.status_code in (429, 432):
        return True
    text = getattr(resp, "text", "") or ""
    try:
        data = resp.json()
        detail = data.get("detail", "")
        if isinstance(detail, dict):
            detail = str(detail.get("error", ""))
        text = f"{text} {detail}"
    except Exception:
        pass
    return any(kw in text.lower() for kw in ("usage limit", "quota", "rate limit"))


def _extract_error_text(resp) -> str:
    """从 Tavily Extract API 错误响应中提取错误信息。"""
    try:
        data = resp.json()
        detail = data.get("detail") if isinstance(data, dict) else None
        if isinstance(detail, dict):
            return str(detail.get("error") or detail)
        if detail:
            return str(detail)
    except Exception:
        pass
    return f"HTTP {resp.status_code}"
