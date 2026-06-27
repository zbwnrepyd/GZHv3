"""Derivation Pass — 从已确认文本字段推导缺失的文本/枚举字段。

- 非阻断：每个字段独立 try/except
- 只推导 parsed 中尚未有有效值的字段（避免覆盖已有好数据）
- 枚举类字段验证合法性后写入；文本类字段不超过 200 字
"""
from __future__ import annotations
import json
import re

MISSING_SENTINELS = {"", "暂缺", "null", "None", "N/A", "n/a"}

# 枚举合法值白名单（与 competitive_scoring.py 保持一致）
ENUM_VALID = {
    "data_flywheel": {"yes", "partial", "no"},
    "proprietary_data_asset": {"yes_core", "yes_supplementary", "no"},
    "incumbent_direct_competitor": {"openai", "google", "multiple", "microsoft", "other", "none"},
    "workflow_integration_level": {"system_of_record", "workflow_embedded", "plugin_addon", "standalone_tool"},
}

# 只推导尚未有有效值的字段
def _is_missing(val) -> bool:
    return val is None or str(val).strip() in MISSING_SENTINELS


def _llm_derive(api_key: str, system_prompt: str, user_content: str,
                max_tokens: int = 200) -> str:
    """单次 LLM 推导调用，返回原始文本。"""
    from deepseek_client import call_deepseek
    return call_deepseek(
        api_key,
        system_prompt,
        user_content,
        temperature=0.1,
        max_tokens=max_tokens,
        timeout=45,
    )


def _extract_json_field(text: str, field: str) -> str | None:
    """从 LLM 输出的 JSON 中提取单个字段值。"""
    try:
        match = re.search(r"\{[\s\S]*\}", text or "")
        if match:
            obj = json.loads(match.group(0))
            return obj.get(field)
    except Exception:
        pass
    return None


# ── 各字段推导函数 ──

def _derive_switching_cost(api_key: str, moat: str) -> str | None:
    if not moat or len(moat) < 50:
        return None
    result = _llm_derive(
        api_key,
        "你是商业分析专家。从下方护城河分析文本中，提取并总结「迁移成本」相关内容，输出 1-2 句中文（≤80字），不含标题前缀。",
        moat,
        max_tokens=150,
    )
    val = result.strip() if result else None
    return val if val and len(val) > 10 else None


def _derive_differentiation_strategy(api_key: str, diff_opp: str) -> str | None:
    if not diff_opp or len(diff_opp) < 30:
        return None
    result = _llm_derive(
        api_key,
        "将下方「差异化机会」分析改写为一句「差异化策略」（≤60字，动词开头，中文），"
        "输出 JSON: {\"differentiation_strategy\": \"...\"}",
        diff_opp,
        max_tokens=100,
    )
    return _extract_json_field(result, "differentiation_strategy")


def _derive_ideal_customer_profile(api_key: str, customer_segment: str) -> str | None:
    if not customer_segment or len(customer_segment) < 30:
        return None
    result = _llm_derive(
        api_key,
        "将下方客户细分描述改写为一段 ICP（理想客户画像）格式文本（≤100字，中文，包含公司类型、规模、痛点、购买决策者），"
        "输出 JSON: {\"ideal_customer_profile\": \"...\"}",
        customer_segment,
        max_tokens=200,
    )
    return _extract_json_field(result, "ideal_customer_profile")


def _derive_product_pain_points(api_key: str, highlight: str, advantages: str) -> str | None:
    source = "\n".join(filter(None, [highlight, advantages]))
    if not source or len(source) < 50:
        return None
    result = _llm_derive(
        api_key,
        "从下方产品亮点和竞争优势文本中，反推该产品解决的核心客户痛点（2-3条，中文 Markdown 列表），"
        "输出 JSON: {\"product_pain_points\": \"...\"}",
        source,
        max_tokens=200,
    )
    return _extract_json_field(result, "product_pain_points")


def _derive_revenue_model(api_key: str, pricing_strategy: str, pricing_summary: str) -> str | None:
    source = "\n".join(filter(None, [pricing_strategy, pricing_summary]))
    if not source or len(source) < 30:
        return None
    result = _llm_derive(
        api_key,
        "根据下方定价策略文本，提炼公司盈利方式（≤60字，中文，格式：'主要收入来源为…，辅以…'），"
        "输出 JSON: {\"revenue_model\": \"...\"}",
        source,
        max_tokens=120,
    )
    return _extract_json_field(result, "revenue_model")


def _derive_technical_barrier(api_key: str, tech_stack: str, moat: str) -> str | None:
    source = "\n".join(filter(None, [tech_stack, moat]))
    if not source or len(source) < 50:
        return None
    result = _llm_derive(
        api_key,
        "从下方技术栈和护城河文本中，提炼技术壁垒（≤80字，中文，聚焦竞争对手难以复制的技术点），"
        "输出 JSON: {\"technical_barrier\": \"...\"}",
        source,
        max_tokens=150,
    )
    return _extract_json_field(result, "technical_barrier")


def _derive_timeline_events(api_key: str, funding_info: str) -> str | None:
    if not funding_info or len(funding_info) < 30:
        return None
    result = _llm_derive(
        api_key,
        "从下方融资信息中，提取关键里程碑事件，按时间顺序输出 JSON 数组（每项含 year 和 event 字段，中文），"
        "输出格式: {\"timeline_events\": [{\"year\": \"2021\", \"event\": \"...\"}, ...]}，"
        "最多 6 项，只写有明确时间的事件。",
        funding_info,
        max_tokens=300,
    )
    val = _extract_json_field(result, "timeline_events")
    if val and isinstance(val, list):
        return json.dumps(val, ensure_ascii=False)
    return None


def _derive_customer_segments(api_key: str, customer_segment: str) -> tuple[str | None, str | None]:
    """同时推导 primary 和 secondary，单次 LLM 调用。"""
    if not customer_segment or len(customer_segment) < 30:
        return None, None
    result = _llm_derive(
        api_key,
        "从下方客户细分文本中，识别主要客户群体（primary）和次要客户群体（secondary），"
        "输出 JSON: {\"primary\": \"...（≤40字）\", \"secondary\": \"...（≤40字）\"}",
        customer_segment,
        max_tokens=150,
    )
    try:
        match = re.search(r"\{[\s\S]*\}", result or "")
        if match:
            obj = json.loads(match.group(0))
            return obj.get("primary"), obj.get("secondary")
    except Exception:
        pass
    return None, None


def _derive_customer_selection_reasons(api_key: str, advantages: str, moat: str) -> str | None:
    source = "\n".join(filter(None, [advantages, moat]))
    if not source or len(source) < 50:
        return None
    result = _llm_derive(
        api_key,
        "从下方竞争优势和护城河文本中，提炼客户选择该产品的 2-3 个核心理由（中文 Markdown 列表），"
        "输出 JSON: {\"customer_selection_reasons\": \"...\"}",
        source,
        max_tokens=200,
    )
    return _extract_json_field(result, "customer_selection_reasons")


# ── 枚举推导（规则优先，规则不确定时才用 LLM）──

def _derive_incumbent_enum(market_players_text: str) -> str | None:
    """从 market_landscape_top_players 文本推断 incumbent_direct_competitor 枚举。"""
    text = str(market_players_text or "").lower()
    if not text or "暂缺" in text:
        return None
    for keyword in ["openai", "open ai"]:
        if keyword in text:
            return "openai"
    for keyword in ["google", "deepmind", "gemini"]:
        if keyword in text:
            return "google"
    for keyword in ["microsoft", "github copilot", "azure"]:
        if keyword in text:
            return "microsoft"
    # 检测多个巨头
    giants = sum(1 for kw in ["salesforce", "oracle", "sap", "aws", "ibm", "visa",
                               "mastercard", "stripe", "paypal"] if kw in text)
    if giants >= 2:
        return "multiple"
    if any(w in text for w in ["competitor", "竞争", "rival", "vs"]):
        return "other"
    return None


def _derive_gtm_motion(gtm_strategy: str) -> str | None:
    """从 gtm_strategy 文本提取简短 GTM 打法关键词（非 LLM，规则提取）。"""
    if not gtm_strategy or len(gtm_strategy) < 20:
        return None
    text = gtm_strategy.lower()
    motions = []
    if any(k in text for k in ["product-led", "plg", "产品驱动", "自助"]):
        motions.append("产品驱动增长（PLG）")
    if any(k in text for k in ["sales-led", "enterprise", "直销", "销售驱动"]):
        motions.append("企业直销")
    if any(k in text for k in ["partner", "合作伙伴", "ecosystem", "生态"]):
        motions.append("生态合作")
    if any(k in text for k in ["community", "社区", "open source", "开源"]):
        motions.append("社区驱动")
    return " + ".join(motions) if motions else None


def _derive_data_flywheel_enum(growth_flywheel_text: str) -> str | None:
    """从 growth_flywheel 文本推导 data_flywheel 枚举（旧公式回退路径）。"""
    text = str(growth_flywheel_text or "").lower()
    if not text or "暂缺" in text:
        return None
    strong = ["data flywheel", "data network effect", "data moat", "数据飞轮",
              "数据壁垒", "数据护城河", "数据网络效应"]
    partial = ["data", "数据", "user data", "用户数据", "training data", "训练数据"]
    if any(k in text for k in strong):
        return "yes"
    if any(k in text for k in partial):
        return "partial"
    return "no"


def _derive_proprietary_data_asset_enum(moat_text: str) -> str | None:
    """从 moat 文本推导 proprietary_data_asset 枚举（旧公式回退路径）。"""
    text = str(moat_text or "").lower()
    if not text or "暂缺" in text:
        return None
    core = ["proprietary data", "unique data asset", "专有数据", "独占数据",
            "proprietary dataset", "独家数据源", "唯一数据"]
    supp = ["data", "数据", "dataset", "数据源", "训练数据", "training data"]
    if any(k in text for k in core):
        return "yes_core"
    if any(k in text for k in supp):
        return "yes_supplementary"
    return "no"


def _derive_workflow_integration_enum(ecosystem_niche: str, moat: str) -> str | None:
    """从 ecosystem_niche + moat 推导 workflow_integration_level 枚举（旧公式回退路径）。"""
    text = str(ecosystem_niche or "").lower() + " " + str(moat or "").lower()
    if not text.strip() or "暂缺" in text:
        return None
    if any(k in text for k in ["system of record", "核心系统", "record system",
                                "database", "数据库", "infrastructure", "基础设施"]):
        return "system_of_record"
    if any(k in text for k in ["workflow", "工作流", "embedded", "嵌入",
                                "pipeline", "流程", "integration", "集成"]):
        return "workflow_embedded"
    if any(k in text for k in ["plugin", "插件", "addon", "附加", "extension", "扩展"]):
        return "plugin_addon"
    if any(k in text for k in ["standalone", "独立", "tool", "工具", "app", "应用"]):
        return "standalone_tool"
    return None


# ── 主入口 ──

def run_derivation_pass(
    api_key: str,
    parsed: dict,
    progress_callback=None,
    job_id: str = None,
) -> dict:
    """
    对 parsed 中缺失的文本字段进行推导，返回新推导出的字段 dict。

    Args:
        api_key: DeepSeek API Key
        parsed: L3 合并后的字段 dict
        progress_callback: 进度回调（可选）
        job_id: 任务 ID

    Returns:
        {field: value} dict，只包含新推导出的字段
        失败时返回已成功推导的部分结果
    """
    derived: dict[str, str] = {}
    errors: list[str] = []

    def _safe_derive(field: str, fn, *args):
        if not _is_missing(parsed.get(field)):
            return  # 已有值，跳过
        try:
            val = fn(*args)
            if val and not _is_missing(val):
                derived[field] = val
        except Exception as e:
            errors.append(f"{field}: {e}")

    # ── 纯规则推导（无 LLM，始终执行）──
    _safe_derive("gtm_motion", _derive_gtm_motion, parsed.get("gtm_strategy", ""))
    _safe_derive("incumbent_direct_competitor", _derive_incumbent_enum,
                 parsed.get("market_landscape_top_players", ""))
    _safe_derive("data_flywheel", _derive_data_flywheel_enum,
                 parsed.get("growth_flywheel", ""))
    _safe_derive("proprietary_data_asset", _derive_proprietary_data_asset_enum,
                 parsed.get("moat", ""))
    _safe_derive("workflow_integration_level", _derive_workflow_integration_enum,
                 parsed.get("ecosystem_niche", ""), parsed.get("moat", ""))

    # ── LLM 推导（有 API Key 时执行）──
    if not api_key:
        if errors:
            print(f"[derivation_pass] errors: {errors}", flush=True)
        return derived

    _safe_derive("switching_cost", _derive_switching_cost, api_key, parsed.get("moat", ""))
    _safe_derive("differentiation_strategy", _derive_differentiation_strategy,
                 api_key, parsed.get("differentiated_opportunity", ""))
    _safe_derive("ideal_customer_profile", _derive_ideal_customer_profile,
                 api_key, parsed.get("customer_segment", ""))
    _safe_derive("product_pain_points", _derive_product_pain_points,
                 api_key, parsed.get("main_product_highlight", ""),
                 parsed.get("competitive_advantages", ""))
    _safe_derive("revenue_model", _derive_revenue_model,
                 api_key, parsed.get("pricing_strategy", ""),
                 parsed.get("pricing_summary", ""))
    _safe_derive("technical_barrier", _derive_technical_barrier,
                 api_key, parsed.get("tech_stack", ""), parsed.get("moat", ""))
    _safe_derive("timeline_events", _derive_timeline_events,
                 api_key, parsed.get("funding_info", ""))
    _safe_derive("customer_selection_reasons", _derive_customer_selection_reasons,
                 api_key, parsed.get("competitive_advantages", ""), parsed.get("moat", ""))

    # customer_segment_primary / secondary（单次调用推导两个字段）
    if _is_missing(parsed.get("customer_segment_primary")) or \
       _is_missing(parsed.get("customer_segment_secondary")):
        try:
            primary, secondary = _derive_customer_segments(
                api_key, parsed.get("customer_segment", ""))
            if primary and _is_missing(parsed.get("customer_segment_primary")):
                derived["customer_segment_primary"] = primary
            if secondary and _is_missing(parsed.get("customer_segment_secondary")):
                derived["customer_segment_secondary"] = secondary
        except Exception as e:
            errors.append(f"customer_segment_primary/secondary: {e}")

    if derived:
        print(f"[derivation_pass] derived {len(derived)} fields: {list(derived.keys())}",
              flush=True)
    if errors:
        print(f"[derivation_pass] errors (non-blocking): {errors}", flush=True)

    return derived
