"""字段状态标记 — 根据 field_manifest.yaml 给 research_fields 打 resolution_status

P0 变更：
- 统一状态枚举：confirmed, derived, proxy, industry_avg, llm_extracted,
  manual_needed, unavailable, not_applicable, conflict, draft, hidden
- confirmed 必须绑定 evidence（传入 evidence_span_ids 参数）
- private_metric 有 LLM 值不再自动 confirmed，改为 llm_extracted 除非有证据
- market_model 有值标 proxy（而非 confirmed）
- 新增 LTV/CAC 四级降级：confirmed → proxy → industry_avg → unavailable
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional

# 加载 manifest（模块级缓存）
_manifest: dict = {}
_manifest_loaded = False

# ── P0: 统一状态枚举 ──
VALID_STATUSES = {
    "confirmed",       # 有直接证据确认
    "derived",         # 由已确认字段计算得出
    "proxy",           # 基于同类公司或市场报告估算
    "industry_avg",    # 使用行业平均值（必须注明不代表公司披露）
    "llm_extracted",   # LLM 提取但未绑定证据
    "manual_needed",   # 需要人工判断
    "unavailable",     # 公开不可得
    "not_applicable",  # 不适用
    "conflict",        # 多来源冲突
    "draft",           # 待定稿
    "hidden",          # 不展示
}

# D 类私有指标：即使 LLM 有值也不得 confirmed，除非绑定证据
_PRIVATE_METRIC_FIELDS = {
    "arr", "cac", "ltv", "churn_rate", "retention_rate",
    "gross_margin", "burn_rate", "runway_months",
    "revenue_metrics", "growth_metrics",
}

# LTV/CAC 行业均值（SaaS 基准，需注明不代表公司披露）
_LTV_CAC_INDUSTRY_BENCHMARKS = {
    "ltv": "6:1–8:1（SaaS 行业中位数，不代表公司披露）",
    "cac": "$500–$5,000（SaaS 行业区间，不代表公司披露）",
    "ltv_cac_ratio": "3:1–5:1（SaaS 行业健康基准，不代表公司披露）",
    "gross_margin": "70%–80%（SaaS 行业中位数，不代表公司披露）",
    "churn_rate": "3%–7% 月（SaaS 行业区间，不代表公司披露）",
    "burn_rate": "不适用行业均值（公司差异极大）",
    "runway_months": "18–24 月（SaaS 行业参考，不代表公司披露）",
}


def _load_manifest() -> dict:
    global _manifest, _manifest_loaded
    if _manifest_loaded:
        return _manifest

    try:
        import yaml
        path = Path(__file__).resolve().parent.parent.parent / "references" / "field_manifest.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            _manifest = raw.get("fields", {}) if isinstance(raw, dict) else {}
    except Exception:
        _manifest = {}
    _manifest_loaded = True
    return _manifest


# 视为"暂缺"的值
MISSING_VALUES = {"", "暂缺", "unknown", "Unknown", "N/A", "n/a", "none", "None", "NULL"}


def is_missing(value: str | None) -> bool:
    if value is None:
        return True
    return str(value).strip() in MISSING_VALUES


def mark_field(field_key: str, field_value: str | None,
               evidence_ids: Optional[list] = None,
               is_b2b: bool = False) -> dict:
    """返回单个字段的分辨率标签。

    P0 变更：
    - evidence_ids 为空时，official_fact/private_metric 不得 confirmed
    - private_metric 有值但无证据 → llm_extracted
    - market_model 始终 proxy（不 confirmed）
    - E 类字段 B2B 时标 not_applicable
    """
    manifest = _load_manifest()
    entry = manifest.get(field_key, manifest.get("_default", {}))
    category = entry.get("category", "A")
    resolution_type = entry.get("resolution_type", "llm_extract")
    if_missing = entry.get("if_missing", "unavailable")
    has_evidence = bool(evidence_ids)

    val = str(field_value).strip() if field_value else ""

    # ── E 类：B2B 不适配 → not_applicable ──
    if category == "E" and is_b2b:
        return {
            "resolution_status": "not_applicable",
            "unavailable_reason": _b2b_unavailable_reason(field_key),
            "resolution_method": "b2b_remap",
        }

    if not is_missing(field_value):
        # ── 有值：根据 resolution_type + evidence 标记 ──
        if resolution_type == "official_fact":
            if has_evidence:
                status = "confirmed"
            else:
                status = "llm_extracted"  # P0: 无证据不得 confirmed
            return {
                "resolution_status": status,
                "unavailable_reason": None if has_evidence else f"{field_key}: 有LLM提取值但未绑定证据",
                "resolution_method": "official_fact" if has_evidence else "llm_extract_no_evidence",
            }

        elif resolution_type == "enum_extraction":
            # 枚举字段经过规则层+LLM投票+Pydantic验证，可 confirmed
            return {
                "resolution_status": "confirmed" if has_evidence else "llm_extracted",
                "unavailable_reason": None if has_evidence else f"{field_key}: 枚举提取未绑定证据",
                "resolution_method": "enum_extraction",
            }

        elif resolution_type == "private_metric":
            # P0: 私有指标有值也不得 confirmed，除非有证据绑定
            if has_evidence:
                return {
                    "resolution_status": "confirmed",
                    "unavailable_reason": None,
                    "resolution_method": "private_metric_confirmed",
                }
            else:
                return {
                    "resolution_status": "llm_extracted",
                    "unavailable_reason": f"{field_key}: 私有经营指标，LLM提取但无公开来源证据。"
                                         f"仅公司财报/投资人材料/创始人访谈/Latka等数据库可确认",
                    "resolution_method": "private_metric_no_evidence",
                }

        elif resolution_type == "derived":
            return {
                "resolution_status": "derived",
                "unavailable_reason": None,
                "resolution_method": "formula",
            }

        elif resolution_type == "market_model":
            # 市场字段始终 proxy（不 confirmed），除非有行业报告证据
            if has_evidence:
                return {
                    "resolution_status": "proxy",
                    "unavailable_reason": None,
                    "resolution_method": "market_model_with_report",
                }
            return {
                "resolution_status": "proxy",
                "unavailable_reason": f"{field_key}: 市场估算，来源为LLM推断或未确认报告",
                "resolution_method": "market_model",
            }

        elif resolution_type == "b2b_remap":
            if is_b2b:
                return {
                    "resolution_status": "not_applicable",
                    "unavailable_reason": _b2b_unavailable_reason(field_key),
                    "resolution_method": "b2b_remap",
                }
            return {
                "resolution_status": "confirmed" if has_evidence else "llm_extracted",
                "unavailable_reason": None,
                "resolution_method": "b2b_remap",
            }

        else:
            # llm_extract 或其他
            return {
                "resolution_status": "llm_extracted",
                "unavailable_reason": None,
                "resolution_method": resolution_type,
            }

    # ── 无值：根据 if_missing 标记 ──
    if if_missing == "unavailable":
        reason = _unavailable_reason(field_key, category)
        return {
            "resolution_status": "unavailable",
            "unavailable_reason": reason,
            "resolution_method": "marked_unavailable",
        }
    elif if_missing == "manual_needed":
        return {
            "resolution_status": "manual_needed",
            "unavailable_reason": f"{field_key} 需要人工估算或付费数据源",
            "resolution_method": "marked_unavailable",
        }
    elif if_missing == "not_applicable":
        return {
            "resolution_status": "not_applicable",
            "unavailable_reason": _b2b_unavailable_reason(field_key),
            "resolution_method": "marked_unavailable",
        }
    elif if_missing == "derived":
        return {
            "resolution_status": "derived",
            "unavailable_reason": "输入字段缺失，无法计算",
            "resolution_method": "formula",
        }
    else:
        return {
            "resolution_status": "unavailable",
            "unavailable_reason": f"{field_key} 暂缺",
            "resolution_method": "marked_unavailable",
        }


def _unavailable_reason(field_key: str, category: str) -> str:
    reasons = {
        "D": f"{field_key}: 私有经营指标，公开来源未披露",
        "C": f"{field_key}: 市场估算字段，需要市场报告或人工确认边界",
        "A": f"{field_key}: 公开信息中未找到",
    }
    return reasons.get(category, f"{field_key}: 未找到可靠来源")


def _b2b_unavailable_reason(field_key: str) -> str:
    remap = {
        "active_users": "B2B 企业不适用用户数口径，建议使用 account/logo 数",
        "registered_users": "B2B 企业不适用注册用户口径",
        "paying_users": "B2B 企业应使用 paying_customers",
    }
    return remap.get(field_key, f"{field_key}: B2B 业务模式不适用此字段")


def mark_all_fields(fields: dict[str, str | None],
                    evidence_map: Optional[dict[str, list]] = None,
                    is_b2b: bool = False) -> list[dict]:
    """批量标记字段。

    Args:
        fields: {field_key: value}
        evidence_map: {field_key: [evidence_span_ids]} 可选
        is_b2b: 是否 B2B 公司
    """
    evidence_map = evidence_map or {}
    results = []
    for key, val in fields.items():
        ev_ids = evidence_map.get(key)
        result = mark_field(key, val, evidence_ids=ev_ids, is_b2b=is_b2b)
        results.append({"field_key": key, "field_value": val, **result})
    return results


# ── P0: LTV/CAC 四级降级 ──

def resolve_ltv_cac_fallback(field_key: str, confirmed_value: Optional[str] = None,
                              proxy_value: Optional[str] = None,
                              industry_avg_value: Optional[str] = None) -> dict:
    """LTV/CAC 四级降级：confirmed → proxy → industry_avg → unavailable。

    返回 {"value": str, "status": str, "disclaimer": str}
    """
    if confirmed_value and not is_missing(confirmed_value):
        return {
            "value": confirmed_value,
            "status": "confirmed",
            "disclaimer": "",
        }
    if proxy_value and not is_missing(proxy_value):
        return {
            "value": proxy_value,
            "status": "proxy",
            "disclaimer": "基于同类公司推断",
        }
    if field_key in _LTV_CAC_INDUSTRY_BENCHMARKS:
        return {
            "value": _LTV_CAC_INDUSTRY_BENCHMARKS[field_key],
            "status": "industry_avg",
            "disclaimer": "行业平均，不代表公司披露",
        }
    return {
        "value": None,
        "status": "unavailable",
        "disclaimer": "公开来源未披露，无可信行业基准",
    }


def is_private_metric_field(field_key: str) -> bool:
    """判断是否为 D 类私有经营指标。"""
    manifest = _load_manifest()
    entry = manifest.get(field_key, {})
    return entry.get("category") == "D" or field_key in _PRIVATE_METRIC_FIELDS


def is_refetchable(field_key: str) -> bool:
    """判断字段是否可补采（仅 A/B/C 类）。"""
    manifest = _load_manifest()
    entry = manifest.get(field_key, manifest.get("_default", {}))
    category = entry.get("category", "A")
    return category in ("A", "B", "C")


# ── 字段按可获取难度分三类（acquisition tiers）──

TIER_CONFIG: dict[int, dict] = {
    1: {
        "label": "公开可采集",
        "strategy": "web_search + LLM 提取：搜索报告摘要/公司自述/投资机构博客",
        "category_match": {"C"},
        "resolution_match": {"market_model"},
        "default_confidence_level": "estimated",
        "can_be_verified": True,
    },
    2: {
        "label": "代理指标推算",
        "strategy": "proxy metrics：SimilarWeb/GitHub/ProductHunt 等多源代理信号 → 估算范围",
        "category_match": {"D"},
        "field_specific": {
            "mau", "mau_as_of", "active_users", "registered_users",
            "paying_users", "revenue_metrics", "growth_metrics",
        },
        "default_confidence_level": "estimated",
        "can_be_verified": False,
    },
    3: {
        "label": "估算/行业基准",
        "strategy": "estimation formulas + industry benchmarks："
                    "LTV≈定价×(1/流失率), CAC从招聘/广告反推，留存率用行业均值兜底",
        "category_match": {"D"},
        "field_specific": {
            "cac", "ltv", "ltv_cac_ratio", "churn_rate", "retention_rate",
            "retention_definition", "gross_margin", "burn_rate",
            "runway_months", "arr", "mrr", "ltv_cac_is_benchmark",
            "ltv_cac_benchmark_source",
        },
        "default_confidence_level": "benchmark",
        "can_be_verified": False,
    },
}


def classify_acquisition_tier(field_key: str, manifest_entry: dict | None = None) -> int:
    """根据 field_key 和 manifest 条目判断字段的采集难度层级。

    返回 1 (公开可采集), 2 (代理指标推算), 3 (估算/基准), 或 0 (未知/默认)。

    优先级：manifest category > field_specific 集合匹配
    Tier 1: C 类 market_model / A 类官方事实 / B 类公式计算
    Tier 2: D 类用户/MAU 字段 — 可通过 SimilarWeb/GitHub/PH 等代理信号估算
    Tier 3: D 类 LTV/CAC/留存字段 / E 类 B2B 不适配
    """
    if manifest_entry is None:
        manifest_entry = {}

    category = manifest_entry.get("category", "")

    # Category A/B → Tier 1 (官方事实/公式推导)
    if category in ("A", "B"):
        return 1

    # Category C → Tier 1 (市场估算, 公开可采集)
    if category == "C" or manifest_entry.get("resolution_type") == "market_model":
        return 1

    # Category E → Tier 3 (B2B 不适配)
    if category == "E":
        return 3

    # Category D → sub-classify by field_key
    if category == "D":
        t2_fields = TIER_CONFIG[2].get("field_specific", set())
        if field_key in t2_fields:
            return 2
        t3_fields = TIER_CONFIG[3].get("field_specific", set())
        if field_key in t3_fields:
            return 3
        return 0

    # No category — try field_specific matching anyway
    t2_fields = TIER_CONFIG[2].get("field_specific", set())
    if field_key in t2_fields:
        return 2
    t3_fields = TIER_CONFIG[3].get("field_specific", set())
    if field_key in t3_fields:
        return 3

    return 0


def get_tier_strategy(tier: int) -> dict:
    """获取指定 tier 的采集策略配置。"""
    return TIER_CONFIG.get(tier, {
        "label": "未知",
        "strategy": "待定义",
        "default_confidence_level": "unavailable",
        "can_be_verified": False,
    })


def get_default_confidence_level(field_key: str,
                                  manifest_entry: dict | None = None) -> str:
    """根据字段的采集难度层级返回默认 confidence_level。

    Tier 1 → estimated, Tier 2 → estimated, Tier 3 → benchmark, 未知 → unavailable
    """
    tier = classify_acquisition_tier(field_key, manifest_entry)
    cfg = get_tier_strategy(tier)
    return cfg.get("default_confidence_level", "unavailable")
