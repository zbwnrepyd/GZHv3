"""Tavily Search SourceAdapter — 封装 Tavily 搜索 API，含 Key 轮转。

Max 14 queries standard / 18 deep。使用 config.TAVILY_API_KEYS 多 Key 轮流，
配额耗尽自动切换下一个 Key。返回 SourceDocument 列表，source_family=tavily_search。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from research.source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY
from pipeline import _search_tavily_query
from search_plan import build_search_plan, TavilyQuery
from config import config

logger = logging.getLogger(__name__)


# ── TavilySearchAdapter ──────────────────────────────────────────────────────

class TavilySearchAdapter(SourceAdapter):
    """Tavily 搜索 API 适配器。

    封装 Tavily search endpoint，通过 build_search_plan 生成查询计划，
    使用 _search_tavily_query 执行单次查询（含 Key 轮转、缓存、代理）。

    来源可信度默认 medium（第三方搜索命中，非一手官方数据）。
    """

    source_family = "tavily_search"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # ── 核心接口 ──

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行 Tavily 搜索采集。

        Args:
            company_identity: 公司身份信息，至少包含 display_name / website_host。
            field_targets: 目标字段键列表（用于未来按字段优先级排序，当前保留兼容）。
            budget: 预算约束 dict，可包含:
                - max_documents: 最大返回文档数
                - max_queries: 最大 Tavily API 查询次数
                - timeout_seconds: 超时控制（预留，由底层 search 函数内 timeout 处理）

        Returns:
            SourceDocument 列表。查询全部失败时返回空列表（不抛异常）。
        """
        try:
            identity = self._build_identity_context(company_identity)
            display_name = identity.get("display_name", "")
            root_domain = identity.get("root_domain", "")
            website_host = identity.get("website_host", "")
            aliases = identity.get("aliases", [])

            if not display_name and not website_host:
                logger.warning(
                    "TavilySearchAdapter: no display_name or website_host in "
                    "company_identity=%s", company_identity
                )
                return []

            # 从 budget 提取约束
            max_queries = budget.get("max_queries", self.max_documents)
            max_docs = budget.get("max_documents", self.max_documents)

            # 生成搜索计划
            plan = build_search_plan(
                display_name=display_name or website_host,
                root_domain=root_domain,
                website_host=website_host,
                aliases=aliases,
            )
            queries: list[TavilyQuery] = plan.tavily_queries[:max_queries]

            if not queries:
                logger.warning(
                    "TavilySearchAdapter: build_search_plan returned 0 queries "
                    "for display_name=%s", display_name
                )
                return []

            logger.info(
                "TavilySearchAdapter: starting collection — %d queries, "
                "max_docs=%d, company=%s",
                len(queries), max_docs, display_name,
            )

            # 逐查询执行
            docs: list[SourceDocument] = []
            seen_urls: set[str] = set()
            failed_queries = 0

            for q in queries:
                if len(docs) >= max_docs:
                    break

                try:
                    batch = _search_tavily_query(q.query)
                except Exception as exc:
                    failed_queries += 1
                    logger.warning(
                        "TavilySearchAdapter: query failed [%d/%d] — "
                        "intent=%s query=%.80s error=%s",
                        failed_queries, len(queries),
                        q.intent, q.query, exc,
                    )
                    continue

                if not batch or batch.get("error"):
                    failed_queries += 1
                    err = batch.get("error", "empty result") if batch else "None response"
                    logger.warning(
                        "TavilySearchAdapter: query returned error [%d/%d] — "
                        "intent=%s query=%.80s error=%s",
                        failed_queries, len(queries),
                        q.intent, q.query, err,
                    )
                    continue

                results = batch.get("results", [])
                if not results:
                    continue

                for item in results:
                    url = (item.get("url") or "").strip()
                    if not url:
                        continue
                    # 去重：同一 URL 只保留第一条
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    doc = self._result_to_source_document(item, q.intent)
                    if doc:
                        docs.append(doc)

                    if len(docs) >= max_docs:
                        break

            logger.info(
                "TavilySearchAdapter: collection complete — %d docs, "
                "%d/%d queries ok, company=%s",
                len(docs), len(queries) - failed_queries, len(queries),
                display_name,
            )

            return self._truncate_list(docs)

        except Exception as exc:
            logger.error(
                "TavilySearchAdapter.collect: unhandled error — %s", exc,
                exc_info=True,
            )
            return []

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算本次 Tavily 搜索成本。

        每次 Tavily API 调用免费额度内，估算 token 消耗（返回文本字数 * 1.3）。
        """
        max_queries = budget.get("max_queries", 14)
        # 每个 query 返回约 5 条结果，每条 ~500 tokens
        estimated_tokens = max_queries * 5 * 500
        return {
            "estimated_tokens": estimated_tokens,
            "estimated_queries": max_queries,
            "source_family": self.source_family,
        }

    # ── 内部方法 ──

    def _result_to_source_document(
        self,
        item: dict,
        intent: str,
    ) -> Optional[SourceDocument]:
        """将 Tavily search API 单条命中转为 SourceDocument。

        Tavily 返回结构:
            {
                "title": str,
                "url": str,
                "content": str,
                "score": float (0.0–1.0),
                "raw_content": str | None,
            }
        """
        url = (item.get("url") or "").strip()
        if not url:
            return None

        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        raw = (item.get("raw_content") or "").strip()
        score = item.get("score")

        # 可信度：搜索命中统一 medium，除非显式低质域名
        trust = "medium"
        if url and self._is_low_trust_domain(url):
            trust = "low"

        # source_score 使用 Tavily 返回的 score（0–1），标准化后兜底
        source_score = 0.5
        if isinstance(score, (int, float)) and 0.0 <= float(score) <= 1.0:
            source_score = round(float(score), 4)
        elif raw:
            # 有 raw_content 的命中质量更高
            source_score = 0.6

        # 时间戳
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return SourceDocument(
            source_family=self.source_family,
            source_url=url,
            title=title,
            content=content,
            raw_text=raw,
            intent=intent or "",
            trust_tier=trust,
            source_score=source_score,
            entity_score=0.5,  # 初始默认值，后由 evidence_ranker 校准
            fetched_at=now_iso,
            metadata={
                "publisher": self._guess_publisher(url),
                "search_score": source_score,
            },
        )

    @staticmethod
    def _is_low_trust_domain(url: str) -> bool:
        """检查是否属于低可信度域名。"""
        low_trust_patterns = (
            "reddit.com", "twitter.com", "x.com",
            "facebook.com", "instagram.com", "tiktok.com",
            "quora.com", "zhihu.com",
            "medium.com",  # 个人博客平台
        )
        url_lower = url.lower()
        return any(p in url_lower for p in low_trust_patterns)

    @staticmethod
    def _guess_publisher(url: str) -> str:
        """从 URL 提取发布者域名作为 publisher。"""
        if not url:
            return ""
        try:
            # 简化的域名提取
            s = url
            for prefix in ("https://", "http://"):
                if s.startswith(prefix):
                    s = s[len(prefix):]
                    break
            for sep in ("/", "?", "#"):
                idx = s.find(sep)
                if idx >= 0:
                    s = s[:idx]
            return s.strip().lower()
        except Exception:
            return ""


# ── 注册到 ADAPTER_REGISTRY ──

ADAPTER_REGISTRY[TavilySearchAdapter.source_family] = TavilySearchAdapter
