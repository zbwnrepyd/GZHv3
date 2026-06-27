"""Hook Paragraph Writer — 生成微信公众号文章开篇段落。

- 只对 standard 版本生成，每次研究调用一次
- 依赖 L3 standard 版本 parsed 结果
- 非阻断：失败不影响主流程
"""
from __future__ import annotations

HOOK_FIELDS = ["hook_paragraph_1", "hook_paragraph_2", "hook_paragraph_3"]

# L3 中用于写作输入的字段
WRITING_INPUT_FIELDS = [
    "company_def",
    "company_type",
    "main_product_def",
    "main_product_highlight",
    "main_product_achievement",
    "core_competency",
    "competitive_advantages",
    "moat",
    "growth_metrics",
    "revenue_metrics",
    "funding_info",
    "company_achievement",
    "gtm_strategy",
    "customer_segment",
    "market_opportunity",
]


def _build_writing_context(parsed: dict) -> str:
    """从 parsed 中提取写作输入字段，拼成上下文。"""
    parts = []
    for field in WRITING_INPUT_FIELDS:
        val = parsed.get(field)
        if val and str(val).strip() not in ("", "暂缺", "null", "None"):
            parts.append(f"**{field}**: {val}")
    return "\n\n".join(parts)


def generate_hook_paragraphs(
    api_key: str,
    parsed: dict,
    prompt_text: str,
    progress_callback=None,
    job_id: str = None,
) -> dict:
    """
    生成 hook_paragraph_1/2/3，返回 {field: value} dict。

    Args:
        api_key: DeepSeek API Key
        parsed: L3 standard 版本的字段 dict
        prompt_text: layer_hook.md 的文本内容
        progress_callback: 进度回调
        job_id: 任务 ID

    Returns:
        {hook_paragraph_1: ..., hook_paragraph_2: ..., hook_paragraph_3: ...}
        或空 dict（失败时）
    """
    import json, re
    try:
        from deepseek_client import call_deepseek
    except ImportError:
        return {}

    context = _build_writing_context(parsed)
    if not context or len(context) < 100:
        return {}

    try:
        result = call_deepseek(
            api_key,
            prompt_text,
            context,
            temperature=0.6,   # 写作任务用较高温度
            max_tokens=800,
            timeout=90,
        )
    except Exception as e:
        print(f"[hook_writer] LLM call failed: {e}", flush=True)
        return {}

    # 解析 JSON
    try:
        match = re.search(r"\{[\s\S]*\}", result or "")
        if not match:
            return {}
        obj = json.loads(match.group(0))
    except Exception:
        return {}

    if not isinstance(obj, dict):
        return {}

    # 验证：每个字段必须是非空字符串，长度合理
    output: dict[str, str] = {}
    for field in HOOK_FIELDS:
        val = str(obj.get(field) or "").strip()
        if val and 20 < len(val) < 500:
            output[field] = val

    if output:
        print(f"[hook_writer] generated {len(output)}/3 hook paragraphs", flush=True)

    return output
