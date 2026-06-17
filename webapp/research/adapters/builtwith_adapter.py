"""BuiltWith 来源适配器 — 第三方技术栈分析。

通过 BuiltWith API 获取公司网站的技术栈信息（框架、CDN、分析工具等），
返回 source_family=builtwith 的 SourceDocument 列表。Max 5 docs。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

from ..source_adapter import SourceAdapter, SourceDocument

logger = logging.getLogger(__name__)


class BuiltwithAdapter(SourceAdapter):
    """BuiltWith 技术栈分析适配器。

    通过 BuiltWith API 查询目标公司网站的技术栈构成，
    将结果映射为统一的 SourceDocument 格式。

    使用方式:
        adapter = BuiltwithAdapter(timeout_seconds=15, max_documents=5)
        docs = adapter.collect(
            company_identity={"display_name": "Anthropic", "website_host": "anthropic.com"},
            field_targets=["tech_stack", "infrastructure"],
            budget={"max_documents": 5, "timeout_seconds": 15},
        )

    可信度: medium（第三方分析数据，非官方披露）
    """

    source_family: str = "builtwith"
    API_KEY_ENV_VAR: str = "BUILTWITH_API_KEY"

    # BuiltWith API endpoint
    API_BASE_URL: str = "https://api.builtwith.com/v21/api.json"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # BuiltWith 适配器默认最多 5 个文档
        self.max_documents = kwargs.get("max_documents", 5)
        self.timeout_seconds = kwargs.get("timeout_seconds", 15)

    # ── collect ──────────────────────────────────────────────────────────────

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行 BuiltWith 技术栈查询。

        Args:
            company_identity: 公司身份信息，至少包含 website_host。
            field_targets: 目标字段键列表（如 tech_stack、infrastructure 等）。
            budget: 预算约束 dict，可包含:
                - max_documents: 最大返回文档数（默认 5）
                - timeout_seconds: 单次 API 超时（默认 15）

        Returns:
            SourceDocument 列表。API Key 未配置或采集失败时返回空列表。
        """
        api_key = os.environ.get(self.API_KEY_ENV_VAR, "").strip()
        if not api_key:
            logger.warning(
                "Adapter not configured: set %s",
                self.API_KEY_ENV_VAR,
            )
            return []

        max_docs = budget.get("max_documents", self.max_documents)
        max_docs = min(max_docs, self.max_documents)
        timeout = budget.get("timeout_seconds", self.timeout_seconds)

        identity = self._build_identity_context(company_identity)
        website_host = identity.get("website_host", "")
        display_name = identity.get("display_name", "")
        root_domain = identity.get("root_domain", "")

        if not website_host and not root_domain:
            logger.warning(
                "BuiltwithAdapter: no website_host or root_domain in company_identity, skipping"
            )
            return []

        # 使用 root_domain 作为查询目标（BuiltWith 按域名查询）
        query_domain = root_domain or website_host

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        session = requests.Session()
        session.headers.update({
            "User-Agent": "AI-Startups-Research/1.0",
            "Accept": "application/json",
        })

        try:
            # ── 查询 BuiltWith Free API ──
            params = {
                "KEY": api_key,
                "LOOKUP": query_domain,
            }

            resp = session.get(
                self.API_BASE_URL,
                params=params,
                timeout=timeout,
            )

            if resp.status_code == 401:
                logger.warning(
                    "BuiltwithAdapter: unauthorized — invalid API key for %s",
                    query_domain,
                )
                return []

            if resp.status_code == 404:
                logger.info(
                    "BuiltwithAdapter: no data found for domain %s",
                    query_domain,
                )
                return []

            if resp.status_code == 429:
                logger.warning(
                    "BuiltwithAdapter: rate limited for %s, retry later",
                    query_domain,
                )
                return []

            if not resp.ok:
                logger.warning(
                    "BuiltwithAdapter: API error %d for %s: %s",
                    resp.status_code,
                    query_domain,
                    resp.text[:200],
                )
                return []

            data = resp.json()

        except requests.exceptions.Timeout:
            logger.warning(
                "BuiltwithAdapter: request timeout for %s after %ds",
                query_domain,
                timeout,
            )
            return []

        except requests.exceptions.ConnectionError as e:
            logger.warning(
                "BuiltwithAdapter: connection error for %s: %s",
                query_domain,
                e,
            )
            return []

        except requests.exceptions.RequestException as e:
            logger.warning(
                "BuiltwithAdapter: request failed for %s: %s",
                query_domain,
                e,
            )
            return []

        except Exception as e:
            logger.error(
                "BuiltwithAdapter: unexpected error for %s: %s",
                query_domain,
                e,
                exc_info=True,
            )
            return []

        finally:
            try:
                session.close()
            except Exception:
                pass

        if not data or not isinstance(data, dict):
            logger.info(
                "BuiltwithAdapter: empty or invalid response for %s",
                query_domain,
            )
            return []

        # ── 解析 BuiltWith 响应 ──
        docs: list[SourceDocument] = []

        try:
            # BuiltWith 返回结构:
            # {
            #   "Results": [{ "Paths": [...], "Groups": [...] }],
            #   "Errors": [...]
            # }
            results = data.get("Results", [])
            errors = data.get("Errors", [])

            if errors:
                logger.warning(
                    "BuiltwithAdapter: API returned errors for %s: %s",
                    query_domain,
                    errors,
                )

            if not results:
                logger.info(
                    "BuiltwithAdapter: no Results in response for %s",
                    query_domain,
                )
                return []

            # 每个 Result 对应一个域名路径，生成一个 SourceDocument
            for result in results[:max_docs]:
                doc = self._result_to_source_document(
                    result=result,
                    query_domain=query_domain,
                    display_name=display_name,
                    fetched_at=fetched_at,
                )
                if doc:
                    docs.append(doc)

        except Exception as e:
            logger.warning(
                "BuiltwithAdapter: failed to parse response for %s: %s",
                query_domain,
                e,
            )

        logger.info(
            "BuiltwithAdapter: collected %d tech stack docs for %s",
            len(docs),
            display_name or query_domain,
        )
        return self._truncate_list(docs)

    # ── estimate_cost ────────────────────────────────────────────────────────

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算 BuiltWith API 调用成本。

        BuiltWith API 免费层限制较严，单次查询消耗约 1 次 API 调用。

        Args:
            field_targets: 目标字段键列表。
            budget: 预算约束 dict。

        Returns:
            {"estimated_tokens": int, "estimated_queries": int, "source_family": str}
        """
        max_docs = budget.get("max_documents", self.max_documents)
        # BuiltWith 单次 API 调用返回完整技术栈数据
        estimated_queries = 1
        # 技术栈数据以结构化 JSON 为主，文本量较小
        estimated_tokens = max_docs * 1500

        return {
            "estimated_tokens": estimated_tokens,
            "estimated_queries": estimated_queries,
            "source_family": self.source_family,
        }

    # ── 内部方法 ──

    @staticmethod
    def _result_to_source_document(
        result: dict,
        query_domain: str,
        display_name: str,
        fetched_at: str,
    ) -> Optional[SourceDocument]:
        """将 BuiltWith API 单条 Result 转为 SourceDocument。

        BuiltWith Result 结构:
            {
                "Domain": str,
                "Paths": [{"Domain": str, "Url": str, "Technologies": [...]}],
            }
        或 Free API 扁平结构:
            {
                "Groups": [{"Name": str, "Categories": [...]}],
            }
        """
        domain = result.get("Domain", query_domain)

        # 提取技术栈文本
        tech_parts: list[str] = []

        # 路径级别技术
        paths = result.get("Paths", [])
        for path in paths:
            path_url = path.get("Url", "") or path.get("Domain", "")
            technologies = path.get("Technologies", [])
            for tech in technologies:
                tech_name = tech.get("Name", "") or tech.get("Tag", "")
                if tech_name:
                    tech_parts.append(f"{tech_name}")

        # 分组级别技术（Free API）
        groups = result.get("Groups", [])
        for group in groups:
            group_name = group.get("Name", "")
            categories = group.get("Categories", [])
            for cat in categories:
                cat_name = cat.get("Name", "")
                tech_list = cat.get("Technologies", [])
                for tech in tech_list:
                    tech_name = tech.get("Name", "") or tech.get("Tag", "")
                    if tech_name:
                        tech_parts.append(
                            f"{group_name}/{cat_name}/{tech_name}"
                        )

        # 构建文本内容
        if not tech_parts:
            # 无技术栈数据，跳过
            return None

        content_lines = [
            f"Technology stack detected for {domain}:",
        ]
        for i, tech in enumerate(tech_parts):
            content_lines.append(f"- {tech}")
            # 控制内容长度
            if i >= 50:
                content_lines.append(f"... and {len(tech_parts) - 50} more technologies")
                break

        content = "\n".join(content_lines)
        raw_text = content

        # 构建标题
        title = f"BuiltWith Technology Profile: {domain}"
        if display_name and display_name.lower() not in domain.lower():
            title = f"BuiltWith Technology Profile: {display_name} ({domain})"

        # 技术栈数据 URL（BuiltWith 公开页面）
        source_url = f"https://builtwith.com/{domain}"

        return SourceDocument(
            source_family="builtwith",
            source_url=source_url,
            title=title,
            content=content,
            raw_text=raw_text,
            intent="tech_stack",
            trust_tier="medium",  # 第三方分析数据
            source_score=0.70,    # BuiltWith 是专业第三方工具
            entity_score=0.85,    # 域名精确匹配，实体相关度高
            final_score=0.0,      # 由 evidence_ranker 计算
            published_at="",      # BuiltWith 不提供首次检测日期
            fetched_at=fetched_at,
            metadata={
                "publisher": "BuiltWith",
                "query_domain": query_domain,
                "display_name": display_name,
                "technology_count": len(tech_parts),
            },
        )
