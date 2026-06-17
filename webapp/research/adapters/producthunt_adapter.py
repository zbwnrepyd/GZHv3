"""ProductHunt 来源适配器 — 查询 ProductHunt API 获取产品发布数据。

GET /v1/posts?search[company]=X，最多 3 条帖子。
trust_tier="medium"（社区驱动）。
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

from ..source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY

logger = logging.getLogger(__name__)

# ── 适配器配置 ────────────────────────────────────────────────────────────────

PRODUCTHUNT_API_BASE = "https://api.producthunt.com/v1"
MAX_POSTS = 3


class ProductHuntAdapter(SourceAdapter):
    """ProductHunt 来源适配器。

    通过 ProductHunt API v1 搜索公司相关的产品发布帖子，
    返回 source_family=producthunt 的 SourceDocument 列表。

    使用方式:
        adapter = ProductHuntAdapter(timeout_seconds=15, max_documents=3)
        docs = adapter.collect(
            company_identity={"display_name": "Notion", "website_host": "notion.so"},
            field_targets=["product_launch", "traction", "community_growth"],
            budget={"max_documents": 3, "timeout_seconds": 15},
        )
    """

    source_family: str = "producthunt"
    API_KEY_ENV_VAR: str = "PRODUCTHUNT_API_KEY"
    timeout_seconds: int = 15
    max_documents: int = 3

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.max_documents = kwargs.get("max_documents", MAX_POSTS)

    # ── collect ──────────────────────────────────────────────────────────────

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行 ProductHunt API 搜索采集。

        Args:
            company_identity: 公司身份信息，至少包含 display_name / website_host。
            field_targets: 目标字段键列表（用于日志）。
            budget: 预算约束 dict，可包含:
                - max_documents: 最大返回帖子数（上限 3）
                - timeout_seconds: 单次请求超时秒数

        Returns:
            SourceDocument 列表。API Key 缺失或采集失败时返回空列表。
        """
        api_key = os.environ.get(self.API_KEY_ENV_VAR, "")
        if not api_key:
            logger.warning(
                "ProductHuntAdapter not configured: set %s",
                self.API_KEY_ENV_VAR,
            )
            return []

        identity = self._build_identity_context(company_identity)
        display_name = identity.get("display_name", "")
        website_host = identity.get("website_host", "")
        root_domain = identity.get("root_domain", "")

        if not display_name and not root_domain:
            logger.warning(
                "ProductHuntAdapter: no display_name or root_domain in company_identity, skipping"
            )
            return []

        max_docs = budget.get("max_documents", self.max_documents)
        max_docs = min(max_docs, self.max_documents)
        timeout = budget.get("timeout_seconds", self.timeout_seconds)

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 搜索关键词: 优先用公司名，回退到域名
        search_term = display_name or root_domain

        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "AIStartupsResearch/1.0",
        })

        documents: list[SourceDocument] = []

        try:
            resp = session.get(
                f"{PRODUCTHUNT_API_BASE}/posts",
                params={"search[company]": search_term},
                timeout=timeout,
            )

            if resp.status_code != 200:
                logger.warning(
                    "ProductHuntAdapter: API returned HTTP %s for search term '%s'",
                    resp.status_code,
                    search_term,
                )
                return []

            data = resp.json()
            posts = data.get("posts", [])
            if not posts:
                logger.info(
                    "ProductHuntAdapter: no posts found for '%s'",
                    search_term,
                )
                return []

        except requests.Timeout:
            logger.warning(
                "ProductHuntAdapter: API timeout for search term '%s' (%ss)",
                search_term,
                timeout,
            )
            return []
        except requests.ConnectionError:
            logger.warning(
                "ProductHuntAdapter: connection failed for search term '%s'",
                search_term,
            )
            return []
        except requests.RequestException as e:
            logger.error(
                "ProductHuntAdapter: request error for '%s': %s",
                search_term,
                e,
            )
            return []
        except Exception as e:
            logger.error(
                "ProductHuntAdapter: unexpected error for '%s': %s",
                search_term,
                e,
                exc_info=True,
            )
            return []

        # ── 映射 API 响应 → SourceDocument ──
        for post in posts[:max_docs]:
            try:
                doc = self._map_post_to_source_document(
                    post, display_name, fetched_at
                )
                documents.append(doc)
            except Exception as e:
                logger.warning(
                    "ProductHuntAdapter: failed to map post for '%s': %s",
                    search_term,
                    e,
                )
                continue

        logger.info(
            "ProductHuntAdapter: collected %d posts for '%s'",
            len(documents),
            search_term,
        )
        return documents

    # ── estimate_cost ────────────────────────────────────────────────────────

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算 ProductHunt API 调用成本。

        ProductHunt API v1 开放免费使用；每次采集消耗 1 次搜索请求。
        """
        max_docs = budget.get("max_documents", self.max_documents)
        estimated_tokens = max_docs * 1500  # 每帖 tagline + description ~1500 tokens

        return {
            "estimated_tokens": estimated_tokens,
            "estimated_queries": 1,
            "source_family": self.source_family,
        }

    # ── 内部映射 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _map_post_to_source_document(
        post: dict,
        display_name: str,
        fetched_at: str,
    ) -> SourceDocument:
        """将 ProductHunt API 返回的 post 对象映射为 SourceDocument。

        ProductHunt API v1 post 字段:
            id, name, tagline, description, url, votes_count, comments_count,
            created_at, topics, makers, etc.

        Args:
            post: ProductHunt API 返回的帖子 dict。
            display_name: 公司展示名。
            fetched_at: 采集时间戳。

        Returns:
            填充完整的 SourceDocument 实例。
        """
        post_name = post.get("name", "")
        tagline = post.get("tagline", "")
        description = post.get("description", "")

        # 拼接 content: tagline + description
        content_parts = []
        if tagline:
            content_parts.append(tagline)
        if description:
            content_parts.append(description)
        content = "\n\n".join(content_parts)

        # title: "ProductHunt: {post_name}"
        title = f"ProductHunt: {post_name}" if post_name else "ProductHunt post"

        # source_url: ProductHunt 帖子链接，回退到 redirect_url
        source_url = post.get("url", "") or post.get("redirect_url", "")

        # published_at: PH 的 created_at
        published_at = post.get("created_at", "")

        # 提取 makers 名称作为 publisher
        makers = post.get("makers", [])
        maker_names = [m.get("name", "") for m in makers if m.get("name")]
        publisher = ", ".join(maker_names[:3]) if maker_names else "ProductHunt"

        # metadata 附加信息
        metadata = {
            "publisher": publisher,
            "display_name": display_name,
            "votes_count": post.get("votes_count", 0),
            "comments_count": post.get("comments_count", 0),
            "topics": [t.get("name", "") for t in post.get("topics", [])],
        }

        return SourceDocument(
            source_family="producthunt",
            source_url=source_url,
            title=title,
            content=content,
            raw_text=content,
            intent="product_launch",
            trust_tier="medium",  # 社区驱动
            source_score=0.6,     # 社区内容，中等可信度
            entity_score=0.5,     # 实体匹配分由 evidence_ranker 校准
            final_score=0.0,      # 综合得分由 evidence_ranker 计算
            published_at=published_at,
            fetched_at=fetched_at,
            metadata=metadata,
        )


# ── 注册到全局注册表 ──

ADAPTER_REGISTRY["producthunt"] = ProductHuntAdapter
