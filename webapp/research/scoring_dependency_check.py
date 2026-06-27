"""评分依赖检查 — 评分前校验依赖字段，缺依赖则 blocked_by

规则: 评分前先做依赖检查。缺依赖则不打分，输出 blocked_by: ["field_key"]，
      不要让 LLM 猜分。

优先补齐两个阻塞字段:
  - stack_layer ← ecosystem_niche (用于 incumbent_attention 的 stack layer 映射)
  - incumbent_direct_competitor ← market_landscape_top_players (用于 incumbent_attention)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── 评分函数依赖定义 ──
# key: 评分字段名, value: {required: [...], optional: [...]}
SCORING_DEPENDENCIES: dict[str, dict] = {
    "score_defensibility": {
        "required": [
            "data_lock_in", "workflow_lock_in", "technical_uniqueness",
            "distribution_lock", "brand_or_community",
        ],
        "optional": ["moat", "competitive_advantages", "ecosystem_niche"],
    },
    "score_incumbent_attention": {
        "required": [
            "incumbent_overlap", "market_size",
            "strategic_dependency", "user_visibility",
        ],
        # 这些字段影响评分结果但不是硬性阻断
        "optional": ["stack_layer", "incumbent_direct_competitor", "customer_segment_type"],
    },
    "score_value_capture": {
        "required": [
            "pricing_power", "gross_margin",
            "workflow_lock_in", "customer_budget_level",
        ],
        "optional": ["pricing_model", "inference_cost_exposure"],
    },
    "funding_stage_score": {
        "required": ["funding_stage"],
        "optional": ["funding_info"],
    },
}

# 评分字段的子依赖 — 这些字段本身可能依赖其他字段
# key: 子字段, value: 替代来源
SUB_DEPENDENCIES: dict[str, list[str]] = {
    "incumbent_overlap": ["incumbent_direct_competitor", "competitors_top3"],
    "stack_layer": ["ecosystem_niche"],
    "pricing_power": ["pricing_model", "pricing_strategy"],
    "customer_budget_level": ["customer_segment_type", "customer_segment_primary"],
    "market_size": ["market_size_v3", "tam"],
    "data_lock_in": ["moat", "proprietary_data_asset"],
    "workflow_lock_in": ["workflow_integration_level", "ecosystem_niche"],
    "technical_uniqueness": ["moat", "technical_barrier", "tech_stack"],
    "distribution_lock": ["acquisition_channels", "gtm_strategy"],
    "brand_or_community": ["competitive_advantages", "growth_flywheel"],
    "strategic_dependency": ["ai_model_dependency", "stack_layer"],
    "user_visibility": ["customer_segment_primary", "customer_segment_type"],
    "gross_margin": ["pricing_strategy", "inference_cost_exposure"],
    "funding_stage": ["funding_info"],
}


@dataclass
class DependencyCheckResult:
    score_field: str
    passed: bool
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    available_fields: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)  # 根本原因字段


def _is_field_available(field_key: str, field_pool: dict[str, str]) -> bool:
    """检查字段是否有可用值。

    可用条件: field_pool 中存在且非空/非占位。
    """
    val = field_pool.get(field_key, "")
    if not val:
        return False
    val_str = str(val).strip()
    if val_str in ("", "暂缺", "unknown", "Unknown", "N/A", "n/a", "none", "None", "NULL"):
        return False
    return True


def _find_root_missing(field_key: str, field_pool: dict[str, str],
                       visited: set | None = None) -> list[str]:
    """递归追溯缺失的根因字段。

    如果 field_key 可用的子依赖都不在 field_pool 中，
    返回推荐的补全路径。
    """
    if visited is None:
        visited = set()
    if field_key in visited:
        return []
    visited.add(field_key)

    # 如果字段本身可用，不需要追溯
    if _is_field_available(field_key, field_pool):
        return []

    # 查找子依赖
    subs = SUB_DEPENDENCIES.get(field_key, [])
    if not subs:
        return [field_key]

    # 检查是否有子依赖可用
    for sub in subs:
        if _is_field_available(sub, field_pool):
            return []  # 有可用的替代来源，不算阻断

    # 递归追溯
    root_missing = []
    for sub in subs:
        root_missing.extend(_find_root_missing(sub, field_pool, visited))

    return list(set(root_missing)) if root_missing else [field_key]


def check_score_dependencies(score_field: str,
                              field_pool: dict[str, str],
                              ) -> DependencyCheckResult:
    """检查单个评分字段的依赖是否满足。

    Args:
        score_field: 评分字段名 (score_defensibility / score_incumbent_attention / ...)
        field_pool: {field_key: value} 所有字段的值池（含已解析状态）

    Returns:
        DependencyCheckResult with blocked_by root causes
    """
    deps = SCORING_DEPENDENCIES.get(score_field, {})
    required = deps.get("required", [])
    optional = deps.get("optional", [])

    missing_required = []
    missing_optional = []
    available = []
    blocked_by_set: set[str] = set()

    # 检查 required 字段
    for fk in required:
        if _is_field_available(fk, field_pool):
            available.append(fk)
        else:
            missing_required.append(fk)
            # 追溯根因
            roots = _find_root_missing(fk, field_pool)
            blocked_by_set.update(roots)

    # 检查 optional 字段
    for fk in optional:
        if _is_field_available(fk, field_pool):
            available.append(fk)
        else:
            missing_optional.append(fk)

    passed = len(missing_required) == 0

    # 优先标注两个关键阻塞字段
    priority_blockers = {"stack_layer", "incumbent_direct_competitor"}
    blocked_by = sorted(blocked_by_set, key=lambda x: (x not in priority_blockers, x))

    return DependencyCheckResult(
        score_field=score_field,
        passed=passed,
        missing_required=missing_required,
        missing_optional=missing_optional,
        available_fields=available,
        blocked_by=blocked_by,
    )


def check_all_scores(field_pool: dict[str, str]) -> dict[str, DependencyCheckResult]:
    """检查所有评分字段的依赖。

    Returns:
        {score_field: DependencyCheckResult}
    """
    results = {}
    for sf in SCORING_DEPENDENCIES:
        results[sf] = check_score_dependencies(sf, field_pool)
    return results


def format_blocked_checks(results: dict[str, DependencyCheckResult]) -> dict:
    """格式化为可供下游使用的 dict。

    Returns:
        {
            "can_score": bool,
            "scores": {score_field: {"passed": bool, "blocked_by": [...]}},
            "summary": str,
        }
    """
    can_score = all(r.passed for r in results.values())
    scores_detail = {}
    blocked_summary = []

    for sf, r in results.items():
        scores_detail[sf] = {
            "passed": r.passed,
            "blocked_by": r.blocked_by,
            "missing_required": r.missing_required,
        }
        if not r.passed:
            blocked_summary.append(
                f"{sf}: blocked by {r.blocked_by} "
                f"(missing: {r.missing_required})"
            )

    return {
        "can_score": can_score,
        "scores": scores_detail,
        "summary": "; ".join(blocked_summary) if blocked_summary else "all scores ready",
    }


def prioritize_resolution(blocked_by: list[str],
                           all_fields: dict[str, str],
                           ) -> list[dict]:
    """为阻塞字段生成优先级解析建议。

    Returns:
        [{field_key, suggested_source, suggested_method, priority}]
    """
    suggestions = []
    priority_map = {
        "stack_layer": {
            "source": "ecosystem_niche",
            "method": "enum_extract",
            "priority": 1,
        },
        "incumbent_direct_competitor": {
            "source": "market_landscape_top_players",
            "method": "llm_extract",
            "priority": 1,
        },
        "funding_stage": {
            "source": "funding_info",
            "method": "enum_extract",
            "priority": 2,
        },
    }

    for fk in blocked_by:
        if fk in priority_map:
            suggestions.append({
                "field_key": fk,
                "suggested_source": priority_map[fk]["source"],
                "suggested_method": priority_map[fk]["method"],
                "priority": priority_map[fk]["priority"],
                "source_available": _is_field_available(
                    priority_map[fk]["source"], all_fields
                ),
            })
        else:
            # 通用建议
            suggestions.append({
                "field_key": fk,
                "suggested_source": "targeted_search",
                "suggested_method": "search_once",
                "priority": 3,
                "source_available": False,
            })

    suggestions.sort(key=lambda x: (x["priority"], x["field_key"]))
    return suggestions
