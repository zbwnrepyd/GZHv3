"""不可得字段分流器 — 将 unavailable 字段按处理策略分为五类

五类处理类型:
  discard     — 私有经营数据，公开不可得，保持空值
  infer       — 可由已有 confirmed 字段推导，进入 DerivedFieldResolver
  search_once — 公开信息可能存在，最多补搜一轮
  compute     — 依赖公式或规则生成，等依赖字段齐全后计算
  write       — 写作类字段，进入 WritingPass 生成

核心原则: 不要把「58 个不可得字段」当成采集失败处理，而是纳入字段治理流程。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── 处理类型枚举 ──
VALID_RESOLUTION_TYPES = {"discard", "infer", "search_once", "compute", "write"}


@dataclass
class ClassifiedField:
    field_key: str
    resolution_type: str  # discard | infer | search_once | compute | write
    reason: str
    source_fields: list[str] = field(default_factory=list)  # infer/compute 的源字段
    method: str = ""  # llm_extract | llm_rewrite | enum_extract | llm_summarize | formula
    category: str = ""  # A/B/C/D/E from field_manifest
    current_status: str = "unavailable"


# ── 分类规则 ──

# D 类私有指标 → discard (禁止补搜，公开不可得)
_DISCARD_FIELDS: set[str] = {
    "arr", "mrr", "mau", "mau_as_of", "cac", "ltv", "ltv_cac_ratio",
    "churn_rate", "retention_rate", "retention_definition",
    "gross_margin", "burn_rate", "runway_months",
    "revenue_metrics", "growth_metrics",
    "ltv_cac_is_benchmark", "ltv_cac_benchmark_source",
    "active_users", "registered_users", "paying_users",
    # 私有指标且无代理来源
    "company_revenue", "company_profit",
}

# 公式字段 → compute (等依赖字段齐全后计算)
_COMPUTE_FIELDS: set[str] = {
    "funding_stage_score",  # 依赖 funding_stage
    "score_defensibility", "score_incumbent_attention", "score_value_capture",
}

# 写作类字段 → write (进入 WritingPass 生成)
_WRITE_FIELDS: set[str] = {
    "hook_paragraph_1", "hook_paragraph_2", "hook_paragraph_3",
}

# 可由 confirmed 字段推导 → infer
# key: target_field, value: {source: [...], method: ...}
_INFER_RULES: dict[str, dict] = {
    "switching_cost": {
        "source": ["moat"],
        "method": "llm_extract",
        "description": "从 moat 字段中提取切换成本相关内容",
    },
    "data_flywheel": {
        "source": ["growth_flywheel"],
        "method": "llm_rewrite",
        "description": "从 growth_flywheel 改写为数据飞轮描述",
    },
    "gtm_motion": {
        "source": ["gtm_strategy"],
        "method": "enum_extract",
        "description": "从 gtm_strategy 提取 GTM 动议类型",
    },
    "revenue_model": {
        "source": ["pricing_strategy", "pricing_summary"],
        "method": "llm_summarize",
        "description": "从定价策略和定价摘要总结收入模型",
    },
    "technical_barrier": {
        "source": ["tech_stack", "moat"],
        "method": "llm_extract",
        "description": "从技术栈和护城河提取技术壁垒描述",
    },
    "stack_layer": {
        "source": ["ecosystem_niche"],
        "method": "enum_extract",
        "description": "从 ecosystem_niche 抽取值: application/middleware/infrastructure/model_layer",
    },
    "incumbent_direct_competitor": {
        "source": ["market_landscape_top_players"],
        "method": "llm_extract",
        "description": "从市场头部玩家中选出最直接的大厂/头部竞品",
    },
    "competitive_position": {
        "source": ["competitors", "competitors_top3", "differentiated_opportunity"],
        "method": "llm_summarize",
        "description": "从竞品信息总结竞争定位",
    },
    "differentiation_strategy": {
        "source": ["differentiated_opportunity", "moat"],
        "method": "llm_extract",
        "description": "从差异化机会和护城河提取差异化策略",
    },
    "cold_start": {
        "source": ["gtm_strategy", "growth_flywheel"],
        "method": "llm_extract",
        "description": "从 GTM 策略和增长飞轮提取冷启动策略",
    },
    "customer_segment": {
        "source": ["ideal_customer_profile", "customer_segment_primary", "customer_segment_secondary"],
        "method": "llm_summarize",
        "description": "从客户画像字段总结客户细分",
    },
    "customer_selection_reasons": {
        "source": ["customer_choice_evidence", "competitive_advantages"],
        "method": "llm_extract",
        "description": "从客户选择证据和竞争优势提取客户选择理由",
    },
    "product_core_features": {
        "source": ["main_product_highlight", "main_product_definition"],
        "method": "llm_extract",
        "description": "从主产品亮点和定义提取核心功能",
    },
    "product_pain_points": {
        "source": ["market_pain", "main_product_highlight"],
        "method": "llm_extract",
        "description": "从市场痛点和产品亮点提取产品解决的痛点",
    },
    "product_usage_playbook": {
        "source": ["main_product_definition", "product_core_features"],
        "method": "llm_summarize",
        "description": "从产品定义和核心功能总结使用场景",
    },
    "main_product_achievement": {
        "source": ["company_achievements", "main_product_highlight"],
        "method": "llm_extract",
        "description": "从公司成就和产品亮点提取主产品成就",
    },
}

# A/C 类公开可采集字段 → search_once (最多一轮补搜)
_SEARCH_ONCE_FIELDS: set[str] = {
    "tam", "sam", "som", "market_cagr",
    "product_core_features",
    "acquisition_channels",
    "cold_start",
    "regional_market_focus", "regional_markets",
    "pricing_tiers",
    "product_tech_stack",
    "customer_names",
    "company_achievements", "company_achievement",
    "competitors", "competitors_top3",
    "customer_choice_evidence",
    "ideal_customer_profile",
    "customer_segment_primary", "customer_segment_secondary",
    "timeline_events",
    "data_confidence",
}


def classify_field(field_key: str, confirmed_fields: set[str] | None = None,
                   manifest_entry: dict | None = None) -> ClassifiedField:
    """将单个 unavailable 字段分类到处理类型。

    Args:
        field_key: 字段名
        confirmed_fields: 当前已 confirmed 的字段集合（用于判断 infer 是否可行）
        manifest_entry: field_manifest.yaml 中的字段条目

    Returns:
        ClassifiedField with resolution_type and metadata
    """
    entry = manifest_entry or {}
    category = entry.get("category", "")
    confirmed = confirmed_fields or set()

    # 1. 写作类 → write
    if field_key in _WRITE_FIELDS:
        return ClassifiedField(
            field_key=field_key,
            resolution_type="write",
            reason=f"{field_key}: 写作类字段，应从研究结果生成而非采集",
            category=category,
        )

    # 2. 公式字段 → compute
    if field_key in _COMPUTE_FIELDS:
        return ClassifiedField(
            field_key=field_key,
            resolution_type="compute",
            reason=f"{field_key}: 公式派生字段，等依赖字段齐全后计算",
            method="formula",
            category=category,
        )

    # 3. D/E 类私有指标 → discard
    if field_key in _DISCARD_FIELDS or category in ("D", "E"):
        return ClassifiedField(
            field_key=field_key,
            resolution_type="discard",
            reason=f"{field_key}: 私有经营数据或不适配字段，公开不可得，保持空值",
            category=category,
        )

    # 4. 可推导字段 → infer (需检查源字段是否 confirmed)
    if field_key in _INFER_RULES:
        rule = _INFER_RULES[field_key]
        sources = rule["source"]
        available_sources = [s for s in sources if s in confirmed]
        if available_sources:
            return ClassifiedField(
                field_key=field_key,
                resolution_type="infer",
                reason=f"{field_key}: 可由已确认字段推导 (sources: {available_sources})",
                source_fields=available_sources,
                method=rule.get("method", "llm_extract"),
                category=category,
            )
        else:
            # 源字段也未确认 → 降级为 search_once 或 discard
            return ClassifiedField(
                field_key=field_key,
                resolution_type="search_once",
                reason=f"{field_key}: 推导源字段 ({sources}) 也未确认，尝试补搜",
                source_fields=sources,
                method=rule.get("method", "llm_extract"),
                category=category,
            )

    # 5. B 类公式字段 → compute
    if category == "B" or entry.get("resolution_type") == "derived":
        return ClassifiedField(
            field_key=field_key,
            resolution_type="compute",
            reason=f"{field_key}: 公式派生字段",
            method="formula",
            category=category,
        )

    # 6. 在补搜名单中 → search_once
    if field_key in _SEARCH_ONCE_FIELDS:
        return ClassifiedField(
            field_key=field_key,
            resolution_type="search_once",
            reason=f"{field_key}: A/C 类公开可采集字段，尝试一轮补搜",
            category=category,
        )

    # 7. A/C 类默认 → search_once
    if category in ("A", "C"):
        return ClassifiedField(
            field_key=field_key,
            resolution_type="search_once",
            reason=f"{field_key}: {category}类公开可采集字段",
            category=category,
        )

    # 8. 兜底 → discard
    return ClassifiedField(
        field_key=field_key,
        resolution_type="discard",
        reason=f"{field_key}: 无明确处理策略，标记为 discard",
        category=category,
    )


def classify_all(unavailable_fields: dict[str, str | None],
                 confirmed_fields: set[str] | None = None,
                 manifest: dict | None = None) -> dict[str, ClassifiedField]:
    """批量分类所有 unavailable 字段。

    Args:
        unavailable_fields: {field_key: current_value} (仅 resolution_status='unavailable' 的字段)
        confirmed_fields: 已 confirmed 的字段名集合
        manifest: field_manifest

    Returns:
        {field_key: ClassifiedField}
    """
    if manifest is None:
        from research.field_status import _load_manifest
        manifest = _load_manifest()
    confirmed = confirmed_fields or set()

    result: dict[str, ClassifiedField] = {}
    for fk in unavailable_fields:
        entry = manifest.get(fk, manifest.get("_default", {}))
        result[fk] = classify_field(fk, confirmed, entry)

    return result


def get_classification_summary(classified: dict[str, ClassifiedField]) -> dict:
    """生成分类摘要，用于日志和调试。"""
    summary = {"discard": [], "infer": [], "search_once": [], "compute": [], "write": []}
    for fk, cf in classified.items():
        summary.setdefault(cf.resolution_type, []).append(fk)
    return {
        rt: {"count": len(fields), "fields": fields}
        for rt, fields in summary.items()
    }
