"""字段驱动采集计划器 — 根据 field_manifest + card_schema 生成 SourcePlan。

SPEC Section 7.1: FieldDrivenSourcePlanner 是研究主链路的第三步，
接收 company_identity + field_targets，输出按字段需求分派的 SourceAdapter 调用计划。

P1 核心变更：
- D 类字段不进入搜索类 adapter（仅进入 OfficialSiteAdapter）
- 按 manifest 的 source_priority 分配 adapter
- 按 adapter 预算控制查询数
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class SourcePlan:
    """采集计划 — 描述哪些 adapter 采集哪些字段"""
    adapters: list[dict] = field(default_factory=list)
    # 每个 adapter 条目: {adapter_family, field_targets, budget, priority}
    field_to_source_map: dict[str, list[str]] = field(default_factory=dict)
    # field_key -> [source_family, ...]
    total_estimated_queries: int = 0
    total_estimated_tokens: int = 0
    total_estimated_cost: float = 0.0
    d_class_fields_skipped: list[str] = field(default_factory=list)


# ── source_family 到 adapter 模块的映射 ──
ADAPTER_FAMILY_MAP = {
    "official_site": "official_site_adapter",
    "tavily_search": "tavily_search_adapter",
    "tavily_extract": "tavily_extract_adapter",
    "github": "github_adapter",
    "producthunt": "producthunt_adapter",
    "youtube": "youtube_transcript_adapter",
    "sec": "sec_adapter",
    "openbb": "openbb_adapter",
    "companieshouse": "companieshouse_adapter",
    "builtwith": "builtwith_adapter",
}

# ── 字段类别到默认 source 的映射 ──
CATEGORY_DEFAULT_SOURCES = {
    "A": ["official_site", "tavily_search"],
    "B": ["official_site", "tavily_search"],
    "C": ["tavily_search", "openbb"],
    "D": ["official_site"],  # 仅官网自愿披露
    "E": [],                 # 不适配，不采集
}

# ── 默认 adapter 预算（可被 config 覆盖）──
DEFAULT_ADAPTER_BUDGETS = {
    "official_site": {"max_urls": 5, "max_documents": 5, "timeout_seconds": 30},
    "tavily_search": {"max_queries": 14, "max_documents": 20, "timeout_seconds": 30},
    "tavily_extract": {"max_urls": 20, "max_documents": 20, "timeout_seconds": 30},
    "github": {"max_queries": 3, "max_documents": 3, "timeout_seconds": 15},
    "producthunt": {"max_queries": 3, "max_documents": 3, "timeout_seconds": 15},
    "youtube": {"max_queries": 3, "max_documents": 3, "timeout_seconds": 20},
    "sec": {"max_queries": 5, "max_documents": 5, "timeout_seconds": 20},
    "openbb": {"max_queries": 5, "max_documents": 5, "timeout_seconds": 20},
    "companieshouse": {"max_queries": 5, "max_documents": 5, "timeout_seconds": 20},
    "builtwith": {"max_queries": 5, "max_documents": 5, "timeout_seconds": 20},
}


class FieldDrivenSourcePlanner:
    """字段驱动采集计划器。

    输入 field_manifest 和 card_schema，为每个 A/B/C 类字段分配合适的 source adapter。
    D 类字段仅分配 OfficialSiteAdapter（公司自愿披露）。
    E 类字段不分配任何采集。
    """

    def __init__(self, manifest: dict | None = None, card_schema_version: str = "v3"):
        self.manifest = manifest or {}
        self.card_schema_version = card_schema_version

    def plan(
        self,
        company_identity: dict,
        field_targets: list[str],
        adapter_budgets: dict | None = None,
    ) -> SourcePlan:
        """为给定公司 + 字段目标生成采集计划。

        Args:
            company_identity: {company_key, canonical_name, aliases, official_domain, country_hint}
            field_targets: 需要采集的 field_key 列表
            adapter_budgets: 可选，覆盖默认 adapter 预算

        Returns:
            SourcePlan with adapter assignments and field-to-source mapping
        """
        budgets = adapter_budgets or DEFAULT_ADAPTER_BUDGETS
        plan = SourcePlan()

        # 1. 按字段类别分组
        category_groups: dict[str, list[str]] = {"A": [], "B": [], "C": [], "D": [], "E": []}
        for fk in field_targets:
            entry = self.manifest.get(fk, self.manifest.get("_default", {}))
            cat = entry.get("category", "A")
            category_groups[cat].append(fk)

        # 2. D 类字段 — 仅官方站点（公司自愿披露）
        for fk in category_groups.get("D", []):
            plan.field_to_source_map[fk] = ["official_site"]
        plan.d_class_fields_skipped = category_groups.get("D", [])

        # 3. E 类字段 — 跳过
        # (no adapter assigned)

        # 4. A/B/C 类字段 — 按 source_priority 分配
        adapter_field_groups: dict[str, list[str]] = {}

        for cat in ("A", "B", "C"):
            for fk in category_groups.get(cat, []):
                entry = self.manifest.get(fk, self.manifest.get("_default", {}))
                source_priority = entry.get("source_priority", [])
                if not source_priority:
                    source_priority = CATEGORY_DEFAULT_SOURCES.get(cat, ["tavily_search"])

                for source_family in source_priority:
                    if source_family not in adapter_field_groups:
                        adapter_field_groups[source_family] = []
                    if fk not in adapter_field_groups[source_family]:
                        adapter_field_groups[source_family].append(fk)
                    plan.field_to_source_map.setdefault(fk, []).append(source_family)
                    break  # 只分配到第一个可用 source

        # 5. 构建 adapter 计划
        total_queries = 0
        for source_family, fields in adapter_field_groups.items():
            budget = budgets.get(source_family, {})
            adapter_entry = {
                "adapter_family": source_family,
                "field_targets": fields,
                "budget": budget,
                "priority": (
                    "high" if source_family in ("official_site", "tavily_search")
                    else "medium"
                ),
            }
            plan.adapters.append(adapter_entry)
            total_queries += budget.get("max_queries", budget.get("max_urls", 5))

        plan.total_estimated_queries = total_queries
        # Rough token estimate: 2000 chars per document * number of documents
        plan.total_estimated_tokens = total_queries * 2000 // 2  # ~1000 tokens per doc

        logger.info(
            "SourcePlan: %d adapters, %d queries, %d fields (D-class skipped: %d)",
            len(plan.adapters),
            plan.total_estimated_queries,
            len(field_targets),
            len(plan.d_class_fields_skipped),
        )

        return plan

    def get_adapter_for_field(self, field_key: str) -> list[str]:
        """返回字段对应的推荐 adapter family 列表。"""
        entry = self.manifest.get(field_key, self.manifest.get("_default", {}))
        cat = entry.get("category", "A")
        source_priority = entry.get("source_priority", [])
        if source_priority:
            return source_priority
        return CATEGORY_DEFAULT_SOURCES.get(cat, ["tavily_search"])


def build_source_plan(
    company_identity: dict,
    field_targets: list[str],
    manifest: dict | None = None,
    card_schema_version: str = "v3",
) -> SourcePlan:
    """便捷函数：构建采集计划。"""
    if manifest is None:
        try:
            from research.field_status import _load_manifest
            manifest = _load_manifest()
        except Exception:
            manifest = {}

    planner = FieldDrivenSourcePlanner(manifest, card_schema_version)
    return planner.plan(company_identity, field_targets)
