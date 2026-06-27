"""派生字段解析器 — 从已 confirmed 字段推导 infer 类字段

对 infer 类型的 unavailable 字段，不重新搜索，直接从已有 confirmed 字段
通过 LLM 抽取/改写/总结得出。

每条输出必须带 lineage(来源链路)，确保可追溯。

示例规则:
  switching_cost ← moat (llm_extract)
  data_flywheel ← growth_flywheel (llm_rewrite)
  gtm_motion ← gtm_strategy (enum_extract)
  revenue_model ← pricing_strategy + pricing_summary (llm_summarize)
  stack_layer ← ecosystem_niche (enum_extract)
  incumbent_direct_competitor ← market_landscape_top_players (llm_extract)
"""

from __future__ import annotations
import json
import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DerivedFieldResult:
    field_key: str
    value: str | None
    resolution_status: str = "derived"  # 派生字段标 derived
    confidence: str = "medium"
    method: str = ""
    source_fields: list[str] = field(default_factory=list)
    lineage: dict = field(default_factory=dict)  # {"from": [...], "method": "...", "prompt_hash": "..."}
    unavailable_reason: str = ""
    success: bool = False


# ── 派生规则库 ──
# 每条规则定义: source 字段 → method → target 字段
DERIVATION_RULES: dict[str, dict] = {
    "switching_cost": {
        "sources": ["moat"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下护城河(moat)描述中，提取与**切换成本(switching cost)**相关的信息。\n"
            "切换成本指：客户从该产品迁移到竞品需要付出的时间/金钱/数据/流程代价。\n"
            "用1-2句中文字描述。如果没有明确提到切换成本，返回'未明确提及'。\n\n"
            "护城河描述:\n{moat}\n\n"
            "切换成本:"
        ),
    },
    "data_flywheel": {
        "sources": ["growth_flywheel"],
        "method": "llm_rewrite",
        "prompt_template": (
            "从以下增长飞轮(growth_flywheel)描述中，提取与**数据飞轮**相关的部分。\n"
            "数据飞轮指：更多用户→更多数据→更好产品→更多用户的循环。\n"
            "用1-2句中文字描述。如果没有数据飞轮特征，返回'未明确提及'。\n\n"
            "增长飞轮描述:\n{growth_flywheel}\n\n"
            "数据飞轮:"
        ),
    },
    "gtm_motion": {
        "sources": ["gtm_strategy"],
        "method": "enum_extract",
        "prompt_template": (
            "从以下GTM策略描述中，判断公司的**GTM动议类型**。\n"
            "可选枚举值: product_led_growth(产品驱动增长) | sales_led(销售驱动) | "
            "community_led(社区驱动) | developer_led(开发者驱动) | content_led(内容驱动) | "
            "partnership_led(合作伙伴驱动)\n"
            "只返回枚举值，不要额外说明。如果无法判断，返回'unknown'。\n\n"
            "GTM策略描述:\n{gtm_strategy}\n\n"
            "GTM动议类型:"
        ),
    },
    "revenue_model": {
        "sources": ["pricing_strategy", "pricing_summary"],
        "method": "llm_summarize",
        "prompt_template": (
            "从以下定价信息中，总结公司的**收入模型**。\n"
            "用1-2句中文字描述收入模式（如：订阅制SaaS、按用量计费、Freemium+企业版等）。\n\n"
            "定价策略:\n{pricing_strategy}\n\n"
            "定价摘要:\n{pricing_summary}\n\n"
            "收入模型:"
        ),
    },
    "technical_barrier": {
        "sources": ["tech_stack", "moat"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下技术栈和护城河描述中，提取公司的**技术壁垒**。\n"
            "技术壁垒指：竞争对手难以复制的技术能力（如自研模型、专利算法、独特架构等）。\n"
            "用1-2句中文字描述。如果没有明确的技术壁垒，返回'未明确提及'。\n\n"
            "技术栈:\n{tech_stack}\n\n"
            "护城河:\n{moat}\n\n"
            "技术壁垒:"
        ),
    },
    "stack_layer": {
        "sources": ["ecosystem_niche"],
        "method": "enum_extract",
        "prompt_template": (
            "从以下生态位描述中，判断公司在技术栈中的**层级位置**。\n"
            "可选枚举值: application(应用层) | middleware(中间件层) | infrastructure(基础设施层) "
            "| model_layer(模型层) | vertical_application(垂直应用层)\n"
            "只返回枚举值，不要额外说明。如果无法判断，返回'unknown'。\n\n"
            "生态位描述:\n{ecosystem_niche}\n\n"
            "层级位置:"
        ),
    },
    "incumbent_direct_competitor": {
        "sources": ["market_landscape_top_players"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下市场头部玩家列表中，选出**最直接的大厂/头部竞品**。\n"
            "标准: 1) 来自大厂(Google/Microsoft/Amazon/Meta/Apple等)或头部创业公司; "
            "2) 产品功能重叠度高; 3) 目标客户群重叠。\n"
            "只返回1个竞品名称。如果没有明确的大厂竞品，返回'none'。\n\n"
            "市场头部玩家:\n{market_landscape_top_players}\n\n"
            "最直接的大厂竞品:"
        ),
    },
    "competitive_position": {
        "sources": ["competitors", "competitors_top3", "differentiated_opportunity"],
        "method": "llm_summarize",
        "prompt_template": (
            "从以下竞品信息中，用1-2句中文总结公司的**竞争定位**。\n"
            "包含: 相比竞品的核心差异、市场位置（领导者/挑战者/利基者）。\n\n"
            "竞品:\n{competitors}\n\n"
            "Top3竞品:\n{competitors_top3}\n\n"
            "差异化机会:\n{differentiated_opportunity}\n\n"
            "竞争定位:"
        ),
    },
    "differentiation_strategy": {
        "sources": ["differentiated_opportunity", "moat"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下差异化机会和护城河描述中，提取公司的**差异化策略**。\n"
            "用1-2句中文字描述。\n\n"
            "差异化机会:\n{differentiated_opportunity}\n\n"
            "护城河:\n{moat}\n\n"
            "差异化策略:"
        ),
    },
    "cold_start": {
        "sources": ["gtm_strategy", "growth_flywheel"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下GTM策略和增长飞轮描述中，提取公司的**冷启动策略**。\n"
            "冷启动指：在0用户/0数据时如何获得第一批用户和增长动力。\n"
            "用1-2句中文字描述。如果没有冷启动策略信息，返回'未明确提及'。\n\n"
            "GTM策略:\n{gtm_strategy}\n\n"
            "增长飞轮:\n{growth_flywheel}\n\n"
            "冷启动策略:"
        ),
    },
    "customer_segment": {
        "sources": ["ideal_customer_profile", "customer_segment_primary", "customer_segment_secondary"],
        "method": "llm_summarize",
        "prompt_template": (
            "从以下客户画像字段中，用1-2句中文总结公司的**客户细分**。\n\n"
            "理想客户画像:\n{ideal_customer_profile}\n\n"
            "主要客户细分:\n{customer_segment_primary}\n\n"
            "次要客户细分:\n{customer_segment_secondary}\n\n"
            "客户细分总结:"
        ),
    },
    "customer_selection_reasons": {
        "sources": ["customer_choice_evidence", "competitive_advantages"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下客户选择证据和竞争优势中，提取**客户选择该公司产品的主要原因**。\n"
            "用1-2句中文字描述。\n\n"
            "客户选择证据:\n{customer_choice_evidence}\n\n"
            "竞争优势:\n{competitive_advantages}\n\n"
            "客户选择原因:"
        ),
    },
    "product_core_features": {
        "sources": ["main_product_highlight", "main_product_definition"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下产品描述中，提取**核心功能列表**。\n"
            "用逗号分隔的短句列表，每条10字以内。3-5条即可。\n\n"
            "产品亮点:\n{main_product_highlight}\n\n"
            "产品定义:\n{main_product_definition}\n\n"
            "核心功能:"
        ),
    },
    "product_pain_points": {
        "sources": ["market_pain", "main_product_highlight"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下市场痛点和产品亮点中，提取**产品解决的核心痛点**。\n"
            "用1-2句中文字描述。\n\n"
            "市场痛点:\n{market_pain}\n\n"
            "产品亮点:\n{main_product_highlight}\n\n"
            "解决的痛点:"
        ),
    },
    "product_usage_playbook": {
        "sources": ["main_product_definition", "product_core_features"],
        "method": "llm_summarize",
        "prompt_template": (
            "从以下产品信息中，用1-2句中文描述**产品的典型使用场景/方式**。\n\n"
            "产品定义:\n{main_product_definition}\n\n"
            "核心功能:\n{product_core_features}\n\n"
            "使用场景:"
        ),
    },
    "main_product_achievement": {
        "sources": ["company_achievements", "main_product_highlight"],
        "method": "llm_extract",
        "prompt_template": (
            "从以下公司成就和产品亮点中，提取**主产品的关键成绩**。\n"
            "用1-2句中文字描述（如用户数、里程碑、行业认可等）。\n\n"
            "公司成就:\n{company_achievements}\n\n"
            "产品亮点:\n{main_product_highlight}\n\n"
            "主产品成绩:"
        ),
    },
}


def _build_prompt(field_key: str, source_values: dict[str, str]) -> str | None:
    """根据派生规则构建 LLM prompt。"""
    rule = DERIVATION_RULES.get(field_key)
    if not rule:
        return None
    template = rule["prompt_template"]
    try:
        return template.format(**source_values)
    except KeyError as e:
        missing = str(e).strip("'")
        # 用 '暂无' 填充缺失的源字段
        safe_values = {k: source_values.get(k, "暂无") for k in rule["sources"]}
        return template.format(**safe_values)


def _compute_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def _call_llm(prompt: str, system_prompt: str = "") -> str | None:
    """调用 LLM 处理单条派生请求。"""
    try:
        from config import config
        from deepseek_client import call_deepseek
        result = call_deepseek(
            config.DEEPSEEK_API_KEY,
            system_prompt or (
                "你是一个商业分析师。请根据提供的上下文信息做精确提取，只返回结果，不要额外解释。"
                "如果信息不足，返回'未明确提及'或'unknown'。"
            ),
            prompt,
            temperature=0.1,
            max_tokens=200,
        )
        return result.strip() if result else None
    except Exception as e:
        print(f"[derived_field_resolver] LLM call failed for prompt: {e}")
        return None


def resolve_derived_field(field_key: str,
                           confirmed_fields: dict[str, str],
                           ) -> DerivedFieldResult:
    """解析单个派生字段。

    Args:
        field_key: 目标字段名
        confirmed_fields: {field_key: confirmed_value} 已确认字段池

    Returns:
        DerivedFieldResult with resolved value and lineage
    """
    rule = DERIVATION_RULES.get(field_key)
    if not rule:
        return DerivedFieldResult(
            field_key=field_key,
            value=None,
            success=False,
            unavailable_reason=f"{field_key}: 无派生规则定义",
            method="no_rule",
        )

    # 收集源字段值
    source_values: dict[str, str] = {}
    for src in rule["sources"]:
        val = confirmed_fields.get(src, "")
        if val and str(val).strip() not in ("", "暂缺", "N/A", "None"):
            source_values[src] = str(val).strip()

    if not source_values:
        return DerivedFieldResult(
            field_key=field_key,
            value=None,
            success=False,
            method=rule["method"],
            source_fields=rule["sources"],
            unavailable_reason=f"{field_key}: 所有源字段 ({', '.join(rule['sources'])}) 均为空",
        )

    # 构建 prompt
    prompt = _build_prompt(field_key, source_values)
    if not prompt:
        return DerivedFieldResult(
            field_key=field_key,
            value=None,
            success=False,
            method=rule["method"],
            source_fields=list(source_values.keys()),
            unavailable_reason=f"{field_key}: prompt 构建失败",
        )

    # 调用 LLM
    raw_result = _call_llm(prompt)
    if not raw_result or raw_result in ("未明确提及", "unknown", "none", "暂无"):
        return DerivedFieldResult(
            field_key=field_key,
            value=None,
            success=False,
            method=rule["method"],
            source_fields=list(source_values.keys()),
            unavailable_reason=f"{field_key}: LLM 派生结果为空或无法确定",
        )

    # 构建 lineage
    lineage = {
        "from": list(source_values.keys()),
        "method": rule["method"],
        "prompt_hash": _compute_prompt_hash(prompt),
    }

    return DerivedFieldResult(
        field_key=field_key,
        value=raw_result,
        resolution_status="derived",
        confidence="medium",
        method=rule["method"],
        source_fields=list(source_values.keys()),
        lineage=lineage,
        success=True,
    )


def resolve_all_derived(infer_fields: list[str],
                         confirmed_fields: dict[str, str],
                         progress_callback=None,
                         ) -> dict[str, DerivedFieldResult]:
    """批量解析所有 infer 类字段。

    Args:
        infer_fields: 待推导的字段名列表
        confirmed_fields: {field_key: confirmed_value}
        progress_callback: 进度回调

    Returns:
        {field_key: DerivedFieldResult}
    """
    results: dict[str, DerivedFieldResult] = {}
    total = len(infer_fields)

    for i, fk in enumerate(infer_fields):
        if progress_callback:
            progress_callback(i + 1, total, fk)

        result = resolve_derived_field(fk, confirmed_fields)
        results[fk] = result

        if result.success:
            print(f"[derived] {fk}: ✓ ← {result.source_fields} (method={result.method})")
        else:
            print(f"[derived] {fk}: ✗ {result.unavailable_reason}")

    success_count = sum(1 for r in results.values() if r.success)
    print(f"[derived] resolved {success_count}/{total} infer fields")
    return results
