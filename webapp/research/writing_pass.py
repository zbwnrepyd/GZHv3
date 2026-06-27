"""写作生成器 — 从已确认的研究字段生成钩子文案

hook_paragraph_1/2/3 不是采集字段，应从研究结果中生成。

输入字段:
  - company_name
  - one_liner
  - main_product_highlight
  - market_pain
  - competitive_advantages
  - growth_flywheel
  - funding_info

输出:
  - hook_paragraph_1 (公司定位钩子，40-80字)
  - hook_paragraph_2 (产品/市场亮点，40-80字)
  - hook_paragraph_3 (增长/投资逻辑，40-80字)

规则:
  - 不新增事实
  - 不写未证实数据
  - 用于卡片首页或开头导语
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WritingResult:
    field_key: str
    value: str | None
    success: bool = False
    resolution_status: str = "derived"  # writing 字段标 derived
    method: str = "writing_pass"
    source_fields: list[str] = field(default_factory=list)
    error: str = ""


# ── Prompt 模板 ──

HOOK_1_SYSTEM = (
    "你是一个科技媒体编辑。根据提供的公司信息，写一段40-80字的公司定位钩子文案。"
    "规则: 1) 只用已有事实，不编造数据; 2) 突出公司做什么、为什么重要; "
    "3) 简洁有力，适合做卡片开头导语; 4) 直接返回文案，不要前缀。"
)

HOOK_1_TEMPLATE = """请根据以下信息写一段40-80字的公司定位钩子:

公司: {company_name}
一句话定位: {one_liner}
公司定义: {company_def}

钩子文案:"""

HOOK_2_SYSTEM = (
    "你是一个科技媒体编辑。根据提供的产品信息，写一段40-80字的产品/市场亮点钩子。"
    "规则: 1) 只用已有事实; 2) 突出产品解决了什么痛点、为什么用户选它; "
    "3) 直接返回文案，不要前缀。"
)

HOOK_2_TEMPLATE = """请根据以下信息写一段40-80字的产品/市场亮点钩子:

公司: {company_name}
主产品: {main_product}
产品亮点: {main_product_highlight}
市场痛点: {market_pain}
竞争优势: {competitive_advantages}
客户选择理由: {customer_choice_evidence}

钩子文案:"""

HOOK_3_SYSTEM = (
    "你是一个科技媒体编辑。根据提供的增长和融资信息，写一段40-80字的增长/投资逻辑钩子。"
    "规则: 1) 只用已有事实; 2) 突出增长飞轮、融资进展、市场机会; "
    "3) 不写未披露的ARR/收入数字; 4) 直接返回文案，不要前缀。"
)

HOOK_3_TEMPLATE = """请根据以下信息写一段40-80字的增长/投资逻辑钩子:

公司: {company_name}
增长飞轮: {growth_flywheel}
融资信息: {funding_info}
GTM策略: {gtm_strategy}
市场机会: {market_opportunity}

钩子文案:"""


def _call_llm(system_prompt: str, user_prompt: str) -> str | None:
    """调用 LLM 生成文案。"""
    try:
        from config import config
        from deepseek_client import call_deepseek
        result = call_deepseek(
            config.DEEPSEEK_API_KEY,
            system_prompt,
            user_prompt,
            temperature=0.3,
            max_tokens=300,
        )
        return result.strip() if result else None
    except Exception as e:
        print(f"[writing_pass] LLM call failed: {e}")
        return None


def _safe_get(fields: dict[str, str], key: str, default: str = "暂无信息") -> str:
    val = fields.get(key, default)
    if not val or str(val).strip() in ("", "暂缺", "N/A", "None"):
        return default
    return str(val).strip()


def generate_hook_1(fields: dict[str, str]) -> WritingResult:
    """生成 hook_paragraph_1: 公司定位钩子。"""
    sources = ["company_name", "one_liner", "company_def"]
    prompt = HOOK_1_TEMPLATE.format(
        company_name=_safe_get(fields, "company_name"),
        one_liner=_safe_get(fields, "one_liner"),
        company_def=_safe_get(fields, "company_def", _safe_get(fields, "core_business")),
    )

    # 有效性检查：至少需要公司名和基本描述
    if _safe_get(fields, "one_liner") == "暂无信息" and _safe_get(fields, "company_def") == "暂无信息":
        return WritingResult(
            field_key="hook_paragraph_1",
            value=None,
            success=False,
            source_fields=sources,
            error="缺少 one_liner 或 company_def，无法生成定位钩子",
        )

    result = _call_llm(HOOK_1_SYSTEM, prompt)
    return WritingResult(
        field_key="hook_paragraph_1",
        value=result,
        success=bool(result),
        source_fields=[s for s in sources if _safe_get(fields, s) != "暂无信息"],
        error="" if result else "LLM 生成失败",
    )


def generate_hook_2(fields: dict[str, str]) -> WritingResult:
    """生成 hook_paragraph_2: 产品/市场亮点钩子。"""
    sources = ["company_name", "main_product", "main_product_highlight",
               "market_pain", "competitive_advantages", "customer_choice_evidence"]
    prompt = HOOK_2_TEMPLATE.format(
        company_name=_safe_get(fields, "company_name"),
        main_product=_safe_get(fields, "main_product", _safe_get(fields, "main_product_name")),
        main_product_highlight=_safe_get(fields, "main_product_highlight"),
        market_pain=_safe_get(fields, "market_pain"),
        competitive_advantages=_safe_get(fields, "competitive_advantages"),
        customer_choice_evidence=_safe_get(fields, "customer_choice_evidence"),
    )

    # 有效性检查
    has_product = (
        _safe_get(fields, "main_product") != "暂无信息"
        or _safe_get(fields, "main_product_name") != "暂无信息"
    )
    if not has_product:
        return WritingResult(
            field_key="hook_paragraph_2",
            value=None,
            success=False,
            source_fields=sources,
            error="缺少主产品信息，无法生成产品钩子",
        )

    result = _call_llm(HOOK_2_SYSTEM, prompt)
    return WritingResult(
        field_key="hook_paragraph_2",
        value=result,
        success=bool(result),
        source_fields=[s for s in sources if _safe_get(fields, s) != "暂无信息"],
        error="" if result else "LLM 生成失败",
    )


def generate_hook_3(fields: dict[str, str]) -> WritingResult:
    """生成 hook_paragraph_3: 增长/投资逻辑钩子。"""
    sources = ["company_name", "growth_flywheel", "funding_info",
               "gtm_strategy", "market_opportunity"]
    prompt = HOOK_3_TEMPLATE.format(
        company_name=_safe_get(fields, "company_name"),
        growth_flywheel=_safe_get(fields, "growth_flywheel"),
        funding_info=_safe_get(fields, "funding_info"),
        gtm_strategy=_safe_get(fields, "gtm_strategy"),
        market_opportunity=_safe_get(fields, "market_opportunity"),
    )

    # 有效性检查：至少需要增长飞轮或融资信息之一
    has_content = (
        _safe_get(fields, "growth_flywheel") != "暂无信息"
        or _safe_get(fields, "funding_info") != "暂无信息"
    )
    if not has_content:
        return WritingResult(
            field_key="hook_paragraph_3",
            value=None,
            success=False,
            source_fields=sources,
            error="缺少增长飞轮或融资信息，无法生成投资逻辑钩子",
        )

    result = _call_llm(HOOK_3_SYSTEM, prompt)
    return WritingResult(
        field_key="hook_paragraph_3",
        value=result,
        success=bool(result),
        source_fields=[s for s in sources if _safe_get(fields, s) != "暂无信息"],
        error="" if result else "LLM 生成失败",
    )


def run_writing_pass(confirmed_fields: dict[str, str]) -> dict[str, WritingResult]:
    """运行完整写作生成流程。

    Args:
        confirmed_fields: {field_key: value} 所有可用字段（含 confirmed/derived/proxy）

    Returns:
        {hook_paragraph_N: WritingResult}
    """
    results = {}

    for i, generator in enumerate([
        (generate_hook_1, "hook_paragraph_1"),
        (generate_hook_2, "hook_paragraph_2"),
        (generate_hook_3, "hook_paragraph_3"),
    ], 1):
        gen_fn, field_key = generator
        result = gen_fn(confirmed_fields)
        results[field_key] = result

        if result.success:
            print(f"[writing] {field_key}: ✓ ({len(result.value or '')} chars)")
        else:
            print(f"[writing] {field_key}: ✗ {result.error}")

    success_count = sum(1 for r in results.values() if r.success)
    print(f"[writing] generated {success_count}/3 hook paragraphs")
    return results
