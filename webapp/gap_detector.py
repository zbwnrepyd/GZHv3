"""缺口检测 — L0 后检查关键字段缺失，生成定向补采 query。

P0 变更：读取 field_manifest.yaml，只对 A/B/C 类字段生成补采 query。
D 类（私有指标）和 E 类（B2B 不适配）不再默认补采。
"""
from __future__ import annotations

# ── P0: 读取 field_manifest 来判断字段是否可补采 ──

_manifest_cache: dict = {}
_manifest_loaded = False


def _load_manifest() -> dict:
    global _manifest_cache, _manifest_loaded
    if _manifest_loaded:
        return _manifest_cache
    try:
        import yaml
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "references" / "field_manifest.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            _manifest_cache = raw.get("fields", {}) if isinstance(raw, dict) else {}
    except Exception:
        _manifest_cache = {}
    _manifest_loaded = True
    return _manifest_cache


def _field_category(field_key: str) -> str:
    """返回字段的 A/B/C/D/E 类别，未在 manifest 中定义的默认 A。"""
    manifest = _load_manifest()
    entry = manifest.get(field_key, manifest.get("_default", {}))
    return entry.get("category", "A")


def _is_refetchable(field_key: str) -> bool:
    """字段是否可补采：仅 A/B/C 类。"""
    return _field_category(field_key) in ("A", "B", "C")


# 保留 CRITICAL_GAPS 作为意图→字段映射（现有逻辑兼容）
# P0: 这些意图中的 D/E 字段在 build_gap_queries 时会被过滤
CRITICAL_GAPS: dict[str, list[str]] = {
    "founders": ["founder_name", "founder_edu", "founder_bg",
                 "founder_achievement"],
    "funding": ["funding_info"],
    "pricing": ["pricing_model", "revenue_model"],
    "competitors": ["competitors"],
    "timeline": ["timeline_events"],
    "product": ["main_product_name", "main_product_def",
                "main_product_achievement"],
    "gtm": ["gtm_strategy", "cold_start", "customer_segment"],
    "market_size": [
        "tam", "sam", "som", "market_cagr",
        "market_size_value", "market_size_currency", "market_size_year",
        "tam_value", "tam_currency", "tam_year",
    ],
    "revenue_metrics": ["arr", "mrr", "revenue_metrics"],
    "user_metrics": ["registered_users", "active_users", "paying_users",
                     "growth_metrics"],
    "retention_metrics": ["retention_rate", "churn_rate"],
    "unit_economics": ["cac", "ltv", "ltv_cac_ratio", "gross_margin"],
    "capital_efficiency": ["burn_rate", "runway_months"],
    # v3 新增缺口意图
    "customers": ["customer_names", "customer_selection_reasons", "customer_choice_evidence"],
    "pricing_details": ["pricing_summary", "pricing_tiers", "pricing_strategy"],
    "competitive_position": ["competitors_top3", "competitive_position", "competitive_advantages"],
    "differentiated_opportunity": ["differentiated_opportunity"],
    "company_profile_v3": ["founded_date", "core_business", "core_competency",
                            "funding_rounds", "company_achievements", "industry_positioning"],
    "product_v3": ["product_pain_points", "product_core_features", "product_usage_playbook",
                   "product_tech_stack", "regional_market_focus", "mau", "mau_as_of",
                   "retention_definition"],
    "gtm_v3": ["acquisition_channels"],
}

GAP_QUERY_TEMPLATES: dict[str, list[str]] = {
    "founders": [
        '"{display_name}" founder LinkedIn education background',
        '"{display_name}" founder interview biography',
    ],
    "funding": [
        '"{display_name}" "{website_host}" funding investors raised',
        '"{display_name}" seed round series valuation',
    ],
    "pricing": [
        "site:{website_host} pricing",
        '"{display_name}" pricing plans subscription',
    ],
    "competitors": [
        '"{display_name}" competitors alternatives vs',
        '"{root_domain}" market map competitors',
    ],
    "timeline": [
        '"{display_name}" launch history timeline founded',
        '"{display_name}" announcement rebrand acquisition milestone',
    ],
    "product": [
        '"{display_name}" product features screenshot demo',
        '"{display_name}" use cases customer review',
    ],
    "gtm": [
        '"{display_name}" go to market growth strategy',
        '"{display_name}" Product Hunt launch users',
    ],
    "market_size": [
        '"{display_name}" TAM SAM SOM market size CAGR',
        '"{display_name}" total addressable market serviceable obtainable market',
    ],
    "revenue_metrics": [
        '"{display_name}" ARR MRR revenue annual recurring revenue',
        '"{display_name}" revenue run rate financial metrics',
    ],
    "user_metrics": [
        '"{display_name}" registered users active users MAU DAU paying users',
        '"{display_name}" customers users adoption growth metrics',
    ],
    "retention_metrics": [
        '"{display_name}" retention rate churn rate cohort retention',
        '"{display_name}" user retention engagement churn metrics',
    ],
    "unit_economics": [
        '"{display_name}" CAC LTV LTV CAC gross margin payback period',
        '"{display_name}" customer acquisition cost lifetime value unit economics',
    ],
    "capital_efficiency": [
        '"{display_name}" burn rate runway cash runway gross margin',
        '"{display_name}" operating metrics burn runway funding efficiency',
    ],
    "customers": [
        '"{display_name}" customers case study enterprise clients testimonials',
        '"{display_name}" customer success stories client list logos',
    ],
    "pricing_details": [
        "site:{website_host} pricing plans",
        '"{display_name}" pricing tiers detailed breakdown subscription',
    ],
    "competitive_position": [
        '"{display_name}" competitive advantage differentiation market position',
        '"{display_name}" vs competitors comparison analysis alternatives',
    ],
    "differentiated_opportunity": [
        '"{display_name}" market gap opportunity niche blue ocean',
        '"{display_name}" differentiation strategy competitive white space',
    ],
    "company_profile_v3": [
        '"{display_name}" founded date year headquarters location',
        '"{display_name}" core business mission company overview achievements',
    ],
    "product_v3": [
        '"{display_name}" product features tech stack architecture MAU',
        '"{display_name}" product usage pain points core functionality pricing',
    ],
    "gtm_v3": [
        '"{display_name}" acquisition channels marketing SEO social media growth',
        '"{display_name}" go to market distribution channels user acquisition',
    ],
}


def is_missing(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text in ("", "暂缺", "未知", "无可信信息")


def detect_gaps(parsed_data: dict) -> dict[str, list[str]]:
    """返回 {intent: [missing_field_names], ...}，每类至少一半字段缺失。"""
    gaps: dict[str, list[str]] = {}
    for intent, fields in CRITICAL_GAPS.items():
        missing = [f for f in fields if is_missing(parsed_data.get(f))]
        if len(missing) >= max(1, len(fields) // 2):
            gaps[intent] = missing
    return gaps


def build_gap_queries(display_name: str, website_host: str,
                      root_domain: str,
                      gaps: dict[str, list[str]]) -> list[dict]:
    """为缺失意图生成 Tavily 补采 query。

    P0: 读取 field_manifest，仅对 A/B/C 类字段生成补采 query。
    D 类（CAC/LTV/gross_margin/burn_rate 等）和 E 类（active_users 等）不补采。
    """
    queries: list[dict] = []
    for intent in gaps:
        # P0: 过滤掉 D/E 类字段
        refetchable_fields = [f for f in gaps[intent] if _is_refetchable(f)]
        if not refetchable_fields:
            continue
        templates = GAP_QUERY_TEMPLATES.get(intent, [])
        for tmpl in templates[:2]:
            q = tmpl.format(display_name=display_name,
                            website_host=website_host,
                            root_domain=root_domain)
            queries.append({"query": q, "intent": intent,
                           "fields": refetchable_fields})
    return queries


def get_skipped_gap_fields(gaps: dict[str, list[str]]) -> dict[str, list[str]]:
    """返回因 D/E 类别被跳过的字段列表（用于日志/审计）。"""
    skipped: dict[str, list[str]] = {}
    for intent, fields in gaps.items():
        non_refetchable = [f for f in fields if not _is_refetchable(f)]
        if non_refetchable:
            skipped[intent] = non_refetchable
    return skipped
