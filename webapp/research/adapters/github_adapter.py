"""GitHub 来源适配器 — 封装 GitHubAgent 搜索逻辑。

通过 GitHub REST API 搜索公司相关的开源仓库（README + description），
返回 source_family=github 的 SourceDocument 列表。
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from ..source_adapter import SourceAdapter, SourceDocument

logger = logging.getLogger(__name__)


class GithubAdapter(SourceAdapter):
    """GitHub 来源适配器。

    封装 GitHubAgent 的仓库搜索与详情获取逻辑，将结果映射为统一的
    SourceDocument 格式，供证据层链路消费。

    使用方式:
        adapter = GithubAdapter(timeout_seconds=20, max_documents=3)
        docs = adapter.collect(
            company_identity={"display_name": "Anthropic", "website_host": "anthropic.com"},
            field_targets=["tech_stack", "developer_adoption", "product_maturity"],
            budget={"max_documents": 3, "max_queries": 6, "timeout_seconds": 30},
        )
    """

    source_family: str = "github"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # GitHub 适配器默认最多 3 个仓库
        self.max_documents = kwargs.get("max_documents", 3)

    # ── collect ──────────────────────────────────────────────────────────────

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行 GitHub 仓库搜索与详情采集。

        Args:
            company_identity: 公司身份信息，至少包含 display_name / website_host。
            field_targets: 目标字段键列表（如 tech_stack、developer_adoption 等）。
            budget: 预算约束，可用键:
                - max_documents: 最大返回仓库数（默认 3）
                - max_queries: 最大 API 查询次数（默认 6）
                - timeout_seconds: 单次 API 超时（默认 20）

        Returns:
            SourceDocument 列表。采集失败时返回空列表。
        """
        max_docs = budget.get("max_documents", self.max_documents)
        # 确保不超过适配器上限
        max_docs = min(max_docs, self.max_documents)

        identity = self._build_identity_context(company_identity)
        display_name = identity.get("display_name", "")
        website_host = identity.get("website_host", "")

        if not display_name:
            logger.warning("GithubAdapter: no display_name in company_identity, skipping")
            return []

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            # 延迟导入，避免循环依赖
            from webapp.research_agents.agents.github_agent import (
                GitHubAgent,
            )

            agent = GitHubAgent()
            company_key = display_name.lower().replace(" ", "-")

            context = {
                "display_name": display_name,
                "website_host": website_host,
            }
            if field_targets:
                context["field_targets"] = field_targets

            result = agent.run(company_key, context)

            if result.status == "failed":
                logger.warning(
                    "GithubAdapter: GitHubAgent failed for %s: %s",
                    display_name,
                    result.note,
                )
                return []

            if result.status == "skipped":
                logger.info(
                    "GithubAdapter: GitHubAgent skipped for %s: %s",
                    display_name,
                    result.note,
                )
                return []

            if not result.documents:
                logger.info(
                    "GithubAdapter: no repos found for %s — %s",
                    display_name,
                    result.note,
                )
                return []

        except ImportError as e:
            logger.error("GithubAdapter: failed to import GitHubAgent: %s", e)
            return []
        except Exception as e:
            logger.error(
                "GithubAdapter: unexpected error running GitHubAgent for %s: %s",
                display_name,
                e,
            )
            return []

        # ── 映射 AgentResult.documents → SourceDocument ──
        docs: list[SourceDocument] = []
        for doc_dict in result.documents[:max_docs]:
            try:
                source_doc = self._map_agent_doc_to_source_document(
                    doc_dict, display_name, fetched_at
                )
                docs.append(source_doc)
            except Exception as e:
                logger.warning(
                    "GithubAdapter: failed to map doc for %s: %s",
                    display_name,
                    e,
                )
                continue

        logger.info(
            "GithubAdapter: collected %d repos for %s",
            len(docs),
            display_name,
        )
        return docs

    # ── estimate_cost ────────────────────────────────────────────────────────

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算 GitHub API 调用成本。

        GitHub REST API 免费层 60 req/h（无认证）或 5000 req/h（有认证）。
        每次采集消耗约 2 * max_repos 次 API 调用（搜索 + 详情）。

        Args:
            field_targets: 目标字段键列表。
            budget: 预算约束 dict。

        Returns:
            {"estimated_tokens": int, "estimated_queries": int, "source_family": str}
        """
        max_docs = budget.get("max_documents", self.max_documents)
        # 每个 repo: 1 次搜索（共享）+ 1 次详情 + 1 次 README + 1 次 releases + 1 次 issues ≈ 5 请求
        # 但搜索是共享的（2 次搜索查询），简化为 2 + 3*max_docs
        estimated_queries = min(2 + 3 * max_docs, 20)
        # GitHub API 不消耗 LLM token，仅估算文本量
        estimated_tokens = max_docs * 3000  # README + description 平均每个仓库 ~3000 tokens

        return {
            "estimated_tokens": estimated_tokens,
            "estimated_queries": estimated_queries,
            "source_family": self.source_family,
        }

    # ── 内部映射 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _map_agent_doc_to_source_document(
        doc_dict: dict,
        display_name: str,
        fetched_at: str,
    ) -> SourceDocument:
        """将 GitHubAgent 的 document dict 映射为 SourceDocument。

        GitHubAgent 输出的 document 字段:
            source_type, source_url, title, raw_text, trust_tier, intent

        Args:
            doc_dict: GitHubAgent 返回的文档 dict。
            display_name: 公司展示名（用于日志）。
            fetched_at: 采集时间戳。

        Returns:
            填充完整的 SourceDocument 实例。
        """
        raw_text = doc_dict.get("raw_text", "") or ""
        title = doc_dict.get("title", "") or ""
        source_url = doc_dict.get("source_url", "") or ""

        # raw_text 的前 10000 字符作为 content（已包含 README 前 3000 字符）
        content = raw_text[:10000] if raw_text else ""

        # trust_tier: GitHub 官方仓库 README 为 high
        trust_tier = "high"  # GitHub 仓库 README 是开源一手资料

        # intent 由 agent 提供或默认
        intent = doc_dict.get("intent", "") or "tech_signal"

        return SourceDocument(
            source_family="github",
            source_url=source_url,
            title=title,
            content=content,
            raw_text=raw_text,
            intent=intent,
            trust_tier=trust_tier,
            source_score=0.85,  # GitHub 官方仓库 README 默认高质量
            entity_score=0.5,    # 实体匹配分由 evidence_ranker 校准
            final_score=0.0,     # 综合得分由 evidence_ranker 计算
            published_at="",     # GitHub API 可提供，但 agent doc 不直接包含
            fetched_at=fetched_at,
            metadata={
                "publisher": "GitHub",
                "display_name": display_name,
            },
        )
