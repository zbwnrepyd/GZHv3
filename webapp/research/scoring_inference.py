"""Post-L3 Scoring Inference — 读取 L3 合成文本，推断 v2 评分枚举字段。

输入: L3 已提取的文本字段 dict（来自 parsed）
输出: {field: enum_value} dict，覆盖写入 parsed
非阻断: 任何异常只记录，不影响主流程
"""
from __future__ import annotations

# ── 12 个 v2 新评分字段 ──
V2_SCORING_FIELDS = [
    "incumbent_overlap",      # 巨头直接竞争重叠
    "workflow_lock_in",       # 工作流锁定强度
    "data_lock_in",           # 数据锁定强度
    "technical_uniqueness",   # 技术独特性
    "distribution_lock",      # 分发渠道锁定
    "brand_or_community",     # 品牌或社区护城河
    "market_size",            # 目标市场规模
    "strategic_dependency",   # 客户战略依赖程度
    "user_visibility",        # 用户侧可见度
    "pricing_power",          # 定价权
    "gross_margin",           # 毛利率水平
    "customer_budget_level",  # 客户预算层级
]

# 各字段合法枚举值（与 competitive_scoring.py 保持一致）
VALID_VALUES: dict[str, list[str]] = {
    "incumbent_overlap":    ["none", "adjacent", "partial_overlap", "direct_overlap"],
    "workflow_lock_in":     ["system_of_record", "workflow_embedded", "plugin_addon", "standalone_tool"],
    "data_lock_in":         ["strong", "moderate", "weak"],
    "technical_uniqueness": ["strong", "moderate", "weak"],
    "distribution_lock":    ["strong", "moderate", "weak"],
    "brand_or_community":   ["strong", "moderate", "weak"],
    "market_size":          ["large", "medium", "small"],
    "strategic_dependency": ["high", "medium", "low"],
    "user_visibility":      ["high", "medium", "low"],
    "pricing_power":        ["outcome_based", "enterprise_contract", "subscription", "usage_based", "freemium", "free"],
    "gross_margin":         ["high", "medium", "low"],
    "customer_budget_level":["b2b_enterprise", "developer_api", "b2b2c", "b2b_smb", "b2c"],
}

# 从 L3 parsed 中读取用于推断的文本字段（越丰富越好）
SOURCE_TEXT_FIELDS = [
    "moat",
    "ecosystem_niche",
    "competitive_position",
    "competitive_advantages",
    "core_competency",
    "pricing_strategy",
    "pricing_summary",
    "growth_strategy",
    "customer_segment",
    "company_type",
    "tech_stack",
    "data_flywheel",         # 旧字段，可辅助推断 data_lock_in
    "workflow_integration_level",   # 旧字段，可辅助推断 workflow_lock_in
    "funding_info",
]


def _build_context(parsed: dict) -> str:
    """从 parsed 中提取源文本字段，拼成推断上下文。"""
    parts = []
    for field in SOURCE_TEXT_FIELDS:
        val = parsed.get(field)
        if val and str(val).strip() not in ("", "暂缺", "null", "None"):
            parts.append(f"## {field}\n{val}")
    return "\n\n".join(parts) if parts else ""


def _build_prompt() -> str:
    return """你是一个 AI 创业公司竞争分析专家。你将根据下方提供的公司分析文本，对公司的竞争评分维度进行枚举分类。

## 任务

从下方提供的公司研究文本中，推断以下 12 个评分字段的枚举值。每个字段从指定的枚举选项中选择**最接近的一个**，不可编造新选项。

## 字段定义与枚举选项

1. **incumbent_overlap** — 与大型巨头（微软、谷歌、OpenAI 等）的直接竞争重叠程度
   选项: none | adjacent | partial_overlap | direct_overlap

2. **workflow_lock_in** — 产品在客户工作流中的嵌入深度
   选项: system_of_record（核心记录系统） | workflow_embedded（嵌入日常流程） | plugin_addon（插件附加） | standalone_tool（独立工具）

3. **data_lock_in** — 数据壁垒与迁移成本强度
   选项: strong | moderate | weak

4. **technical_uniqueness** — 核心技术的不可复制性
   选项: strong | moderate | weak

5. **distribution_lock** — 分发渠道锁定（合作伙伴、生态、平台集成）
   选项: strong | moderate | weak

6. **brand_or_community** — 品牌认知或开发者/用户社区护城河
   选项: strong | moderate | weak

7. **market_size** — 目标市场总规模
   选项: large（>$10B TAM） | medium（$1B-$10B） | small（<$1B）

8. **strategic_dependency** — 客户对产品的战略依赖程度（难以替换）
   选项: high | medium | low

9. **user_visibility** — 产品在终端用户侧的直接可见度（B2C 高，纯 B2B 低）
   选项: high | medium | low

10. **pricing_power** — 定价主导权与收费模式的价值锚定
    选项: outcome_based | enterprise_contract | subscription | usage_based | freemium | free

11. **gross_margin** — 业务结构的毛利率水平
    选项: high（>70%） | medium（40-70%） | low（<40%）

12. **customer_budget_level** — 主要客户群体的预算层级
    选项: b2b_enterprise | developer_api | b2b2c | b2b_smb | b2c

## 重要原则

- 只根据提供的文本推断，不编造信息
- 如无法判断某字段，选择最保守的中间值（不要选极端值，除非有明确依据）
- 不要在 JSON 中解释原因，只输出分类结果

## 输出格式

输出严格 JSON，包含以上 12 个字段：

```json
{
  "incumbent_overlap": "...",
  "workflow_lock_in": "...",
  "data_lock_in": "...",
  "technical_uniqueness": "...",
  "distribution_lock": "...",
  "brand_or_community": "...",
  "market_size": "...",
  "strategic_dependency": "...",
  "user_visibility": "...",
  "pricing_power": "...",
  "gross_margin": "...",
  "customer_budget_level": "..."
}
```"""


def infer_v2_scoring_fields(
    api_key: str,
    parsed: dict,
    progress_callback=None,
    job_id: str = None,
) -> dict:
    """
    Post-L3 推断 12 个 v2 评分枚举字段。

    Args:
        api_key: DeepSeek API Key
        parsed: L3 已提取的字段 dict（含 moat、ecosystem_niche 等文本字段）
        progress_callback: 进度回调
        job_id: 任务 ID（用于日志）

    Returns:
        {field: enum_value} dict，只包含通过验证的字段
        失败时返回空 dict（非阻断）
    """
    import json
    try:
        from deepseek_client import call_deepseek
    except ImportError:
        return {}

    context = _build_context(parsed)
    if not context or len(context) < 100:
        # 上下文过少，跳过推断
        return {}

    try:
        result = call_deepseek(
            api_key,
            _build_prompt(),
            context,
            temperature=0.1,
            max_tokens=300,
            timeout=60,
        )
    except Exception as e:
        print(f"[scoring_inference] LLM call failed: {e}", flush=True)
        return {}

    # 解析 JSON
    try:
        import re
        json_match = re.search(r"\{[\s\S]*\}", result or "")
        if not json_match:
            return {}
        raw = json.loads(json_match.group(0))
    except (json.JSONDecodeError, AttributeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    # 验证：只保留合法枚举值
    validated: dict[str, str] = {}
    for field in V2_SCORING_FIELDS:
        val = str(raw.get(field) or "").strip()
        if val in VALID_VALUES.get(field, []):
            validated[field] = val
        # 非法值静默忽略（保留旧 FIELD_DEFAULTS 兜底）

    if validated:
        print(
            f"[scoring_inference] inferred {len(validated)}/12 v2 fields: "
            f"{list(validated.keys())}",
            flush=True,
        )

    return validated
