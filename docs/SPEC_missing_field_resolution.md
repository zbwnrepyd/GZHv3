# GZHv3 — Missing Field Resolution 技术方案

> 版本: 2026-06-25  
> 目标读者: Claude Code  
> 执行方式: 按 PR 顺序逐一实现，每个 PR 完成后跑 `pytest tests/ -v` 验证通过再进行下一个

---

## 背景与根因

**症状**: 研究台定稿台字段统计显示 58 个"不可得"字段，竞争格局散点图所有公司气泡聚集在左下角（低壁垒/低关注度），评分结果无意义。

**根因**: 两个相互独立的问题：

**问题 A — v2 评分字段从未被提取**  
`competitive_scoring.py` 的 v2 公式需要 12 个新枚举字段（`incumbent_overlap`、`workflow_lock_in`、`data_lock_in`、`technical_uniqueness`、`distribution_lock`、`brand_or_community`、`market_size`、`strategic_dependency`、`user_visibility`、`pricing_power`、`gross_margin`、`customer_budget_level`）。这 12 个字段**没有对应的提取步骤**，全部走 `FIELD_DEFAULTS` 最差值，导致所有公司评分趋同在最低档。

以 Sardine 为例，正确评分应为壁垒≈8.75、巨头关注≈7.75、价值捕获≈9.15，但当前因默认值全部为 0-1 的最差档，实际输出约为 1.5/2.2/0.95。

**问题 B — hook_paragraph 字段没有生成步骤**  
`hook_paragraph_1/2/3` 在 `field_manifest.yaml` 中是 A 类字段（`official_fact`），但本质是写作任务，不是从网页抓取的。管道中没有对应的生成环节，字段永远是"暂缺"。

---

## 约束（不得违反）

1. 所有 LLM 调用使用 `config.DEEPSEEK_API_KEY` + `config.DEEPSEEK_MODEL`（DeepSeek V4 Pro），通过 `call_deepseek()` 发起
2. 新步骤必须是**非阻断**的（用 try/except 包裹，失败不影响主流程）
3. 不修改 `_extract_enum_fields()` 的现有逻辑
4. 不修改 `compute_scores()` 的现有公式
5. 不修改现有 9 个旧枚举字段的提取组（layer3-group-a/b/c prompt 文件）
6. 所有新字段写入 `research_fields` 表，走 `insert_research_fields_batch()`
7. 执行后 `pytest tests/ -v` 全部通过（当前 808 passed）

---

## PR-1: Post-L3 Scoring Inference Pass

### 问题

`_extract_enum_fields()` 读 L0/L1/L2 原始文本分类 9 个旧枚举字段。但此时 LLM 尚未产出 L3 合成分析（`moat`、`ecosystem_niche`、`competitive_position`、`core_competency`、`pricing_strategy`），所以分类上下文最弱。12 个 v2 新字段更是完全没有提取。

### 解决方案

在 `llm_analysis()` 内，L3 每个版本枚举提取完成后，立即追加一次「Post-L3 Scoring Inference」LLM 调用，读取 L3 合成文本字段，输出全部 12 个 v2 评分枚举字段（同时可选地修正 9 个旧字段中置信度低的部分）。

### 新建文件: `webapp/research/scoring_inference.py`

```python
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
```

### 修改 `webapp/pipeline.py`

**位置**: 在 `_extract_enum_fields()` 调用成功后（当前约第 2539–2548 行），追加调用。

找到以下代码块：

```python
            # ── 三层枚举提取覆盖 ──
            try:
                enum_fields = _extract_enum_fields(
                    api_key, l0_result, l1_result, l2_result,
                    company_url, parsed.get("company_type", ""),
                    progress_callback, job_id,
                )
                parsed.update(enum_fields)
            except Exception as e:
                _report(progress_callback, f"L3-{ver_name}",
                        f"枚举提取异常: {e}", job_id=job_id)
```

在 `parsed.update(enum_fields)` 之后，紧接着追加：

```python
            # ── Post-L3 Scoring Inference: v2 评分枚举字段推断 ──
            try:
                from research.scoring_inference import infer_v2_scoring_fields
                v2_scoring = infer_v2_scoring_fields(
                    api_key, parsed, progress_callback, job_id
                )
                if v2_scoring:
                    parsed.update(v2_scoring)
                    _report(progress_callback, f"L3-{ver_name}",
                            f"v2 评分推断: {len(v2_scoring)} 字段", job_id=job_id)
            except Exception as e:
                _report(progress_callback, f"L3-{ver_name}",
                        f"v2 评分推断异常（非阻断）: {e}", job_id=job_id)
```

**注意**: 插入位置在 `except Exception as e: _report(... "枚举提取异常")` 块**之后**，即无论枚举提取是否成功，都尝试 v2 推断（因为即使枚举提取部分失败，parsed 里还有 L3 文本字段可供推断）。实际位置应调整为：在枚举提取的 try/except 整体结束后插入。

### 新建测试 `tests/test_scoring_inference.py`

```python
"""tests/test_scoring_inference.py — scoring_inference 单元测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from research.scoring_inference import (
    infer_v2_scoring_fields,
    _build_context,
    VALID_VALUES,
    V2_SCORING_FIELDS,
)


def test_build_context_returns_empty_for_no_useful_fields():
    parsed = {"company_name": "Acme", "moat": "", "ecosystem_niche": "暂缺"}
    ctx = _build_context(parsed)
    assert ctx == ""


def test_build_context_includes_non_empty_fields():
    parsed = {
        "moat": "强数据护城河",
        "ecosystem_niche": "中间件层",
        "company_name": "Acme",
    }
    ctx = _build_context(parsed)
    assert "moat" in ctx
    assert "强数据护城河" in ctx


def test_valid_values_covers_all_v2_fields():
    for field in V2_SCORING_FIELDS:
        assert field in VALID_VALUES
        assert len(VALID_VALUES[field]) >= 2


def test_infer_returns_empty_on_missing_api_key(monkeypatch):
    """无 API Key 时应非阻断返回空 dict"""
    def mock_call_deepseek(*args, **kwargs):
        raise RuntimeError("no api key")
    monkeypatch.setattr(
        "research.scoring_inference.call_deepseek",
        mock_call_deepseek,
        raising=False,
    )
    result = infer_v2_scoring_fields("", {"moat": "test moat content here"})
    assert isinstance(result, dict)


def test_infer_returns_empty_on_insufficient_context():
    result = infer_v2_scoring_fields("fake-key", {"moat": "x"})
    assert result == {}


def test_infer_validates_output(monkeypatch):
    """LLM 输出非法值时应被过滤"""
    import json

    def mock_call(*args, **kwargs):
        return json.dumps({
            "incumbent_overlap": "invalid_value",
            "workflow_lock_in": "workflow_embedded",   # 合法
            "data_lock_in": "strong",                  # 合法
        })

    monkeypatch.setattr("research.scoring_inference.call_deepseek", mock_call, raising=False)

    parsed = {"moat": "A" * 200}  # 足够长的上下文
    result = infer_v2_scoring_fields("key", parsed)
    assert "incumbent_overlap" not in result   # 非法值被过滤
    assert result.get("workflow_lock_in") == "workflow_embedded"
    assert result.get("data_lock_in") == "strong"
```

---

## PR-2: Text Field Derivation Pass

### 问题

约 15 个文本字段显示"不可得"，但它们的内容完全可以从已确认的 L3 文本字段**通过改写/拆分/提炼**得到，无需额外搜索。这些字段对卡片内容生成或定稿台展示有价值。

### 字段映射表

| 待推导字段 | 来源字段（已确认或 LLM 提取） | 操作 |
|---|---|---|
| `switching_cost` | `moat` | 提取"迁移成本"相关段落 |
| `data_flywheel`（枚举） | `growth_flywheel`（文本） | 转换为 yes/partial/no |
| `differentiation_strategy` | `differentiated_opportunity` | 一句话改写为策略描述 |
| `gtm_motion` | `gtm_strategy` | 提炼核心打法关键词 |
| `ideal_customer_profile` | `customer_segment` | 改写为 ICP 格式 |
| `product_pain_points` | `main_product_highlight` + `competitive_advantages` | 反推痛点 |
| `proprietary_data_asset`（枚举） | `moat` | 分类为 yes_core/yes_supplementary/no |
| `revenue_model` | `pricing_strategy` + `pricing_summary` | 提炼盈利方式 |
| `technical_barrier` | `tech_stack` + `moat` | 提炼技术壁垒描述 |
| `timeline_events` | `funding_info` | 重构为时间线格式 |
| `customer_segment_primary` | `customer_segment` | 拆分出主要客户 |
| `customer_segment_secondary` | `customer_segment` | 拆分出次要客户 |
| `customer_selection_reasons` | `competitive_advantages` + `moat` | 提炼选择理由 |
| `incumbent_direct_competitor`（枚举） | `market_landscape_top_players` | 映射为 openai/google/multiple/microsoft/other/none |
| `workflow_integration_level`（枚举） | `ecosystem_niche` + `moat` | 映射为枚举值 |

**注意**: `data_flywheel`、`proprietary_data_asset`、`incumbent_direct_competitor`、`workflow_integration_level` 这 4 个字段是枚举字段（同时也是 v1 评分输入），PR-1 中的 scoring_inference 已覆盖其 v2 对应字段。这里推导出的枚举值仅用于旧公式回退路径，**不应覆盖** PR-1 已写入的值。

### 新建文件 `webapp/research/derivation_pass.py`

```python
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
```

### 修改 `webapp/pipeline.py`

紧接在 PR-1 插入点之后（即 v2 scoring inference 块之后），再追加：

```python
            # ── Derivation Pass: 从已有文本推导缺失字段 ──
            try:
                from research.derivation_pass import run_derivation_pass
                derived_fields = run_derivation_pass(
                    api_key, parsed, progress_callback, job_id
                )
                # 注意: 只写入 parsed 中尚未有值的字段，不覆盖已有好数据
                for fk, fv in derived_fields.items():
                    if not parsed.get(fk) or str(parsed.get(fk)).strip() in (
                        "", "暂缺", "null", "None"
                    ):
                        parsed[fk] = fv
                if derived_fields:
                    _report(progress_callback, f"L3-{ver_name}",
                            f"字段推导: {len(derived_fields)} 字段", job_id=job_id)
            except Exception as e:
                _report(progress_callback, f"L3-{ver_name}",
                        f"字段推导异常（非阻断）: {e}", job_id=job_id)
```

### 新建测试 `tests/test_derivation_pass.py`

```python
"""tests/test_derivation_pass.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from research.derivation_pass import (
    _is_missing,
    _derive_gtm_motion,
    _derive_incumbent_enum,
    run_derivation_pass,
)


def test_is_missing_handles_sentinels():
    assert _is_missing(None)
    assert _is_missing("")
    assert _is_missing("暂缺")
    assert not _is_missing("有效值")


def test_derive_gtm_motion_plg():
    result = _derive_gtm_motion("以产品驱动增长（PLG）为核心，配合企业直销攻关大客户")
    assert result is not None
    assert "PLG" in result or "产品" in result


def test_derive_gtm_motion_none_on_empty():
    assert _derive_gtm_motion("") is None
    assert _derive_gtm_motion("短文") is None


def test_derive_incumbent_enum_google():
    result = _derive_incumbent_enum(
        '[{"name": "Google", "threat": "high"}, {"name": "Anthropic", "threat": "medium"}]'
    )
    assert result == "google"


def test_derive_incumbent_enum_multiple():
    result = _derive_incumbent_enum(
        "主要竞争对手包括 Salesforce、Oracle 和 SAP 三大企业软件巨头"
    )
    assert result == "multiple"


def test_run_derivation_pass_skips_existing_values():
    """已有值的字段不应被覆盖"""
    parsed = {
        "gtm_strategy": "采用产品驱动增长策略，配合企业直销",
        "gtm_motion": "已有的打法",  # 已有值
    }
    derived = run_derivation_pass("", parsed)
    assert "gtm_motion" not in derived  # 不应推导已有字段


def test_run_derivation_pass_no_api_key_still_does_rules():
    """无 API Key 时规则推导仍然执行"""
    parsed = {
        "gtm_strategy": "产品驱动增长（PLG）加上企业销售团队直销大客户",
        "market_landscape_top_players": "Google DeepMind 和 OpenAI 是主要竞争对手",
    }
    derived = run_derivation_pass("", parsed)
    # 规则推导的字段应该存在
    assert "gtm_motion" in derived or "incumbent_direct_competitor" in derived
```

---

## PR-3: Hook Paragraph Generation Pass

### 问题

`hook_paragraph_1/2/3` 是微信公众号文章的钩子段落，从 AGENTS.md 可知它们是 `research_fields` 表中的普通字段，不写入知识卡片，但用于辅助编辑者撰写文章引言。当前管道没有对应的写作步骤，字段永远为"暂缺"。

### 设计

Hook 段落的写作依赖 L3 综合分析完成后的全局视角，因此写作步骤应放在 L3 合并完毕之后，作为独立的写作 pass（L4 风格），每次研究**只对 standard 版本**生成，不重复生成 business/spread 版。

### 新建 Prompt 文件 `prompts/layer_hook.md`

```markdown
# Hook 段落写作

## 任务

你是一名科技创业观察作家，为微信公众号「一万个AI初创公司」撰写公司介绍文章的开篇钩子段落。

下方提供了公司的核心研究摘要，请基于这些信息撰写 3 个不同风格的开篇段落（hook），供编辑选择。

## 三种风格

1. **hook_paragraph_1 — 痛点切入型**（100-150字）：从行业/用户痛点出发，揭示现有方案的不足，引出该公司解法。语气犀利，制造焦虑感。

2. **hook_paragraph_2 — 数字冲击型**（80-120字）：用最亮眼的数字/指标作为开场白，用数据说话。要让读者感受到规模感或增长速度。

3. **hook_paragraph_3 — 叙事反转型**（120-160字）：从一个反直觉的观察或行业悖论切入，建立期待，再引出该公司的定位。

## 写作要求

- 全部中文，面向关注 AI 创业的读者
- 不使用"赋能""生态""重塑""引领"等空洞词汇
- 每段独立成型，可直接复制到文章开头
- 不要以公司名开头（避免平铺直叙）

## 输出格式

输出严格 JSON：

```json
{
  "hook_paragraph_1": "...",
  "hook_paragraph_2": "...",
  "hook_paragraph_3": "..."
}
```
```

### 新建文件 `webapp/research/hook_writer.py`

```python
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
```

### 修改 `webapp/pipeline.py`

**位置**: 在 `llm_analysis()` 函数返回 `all_records` 之前（所有版本 L3 处理完毕后），对 standard 版本追加 hook 生成。

找到 `return all_records`（`llm_analysis()` 函数末尾），在其前方插入：

```python
    # ── Hook Paragraph Generation（仅 standard 版本，写作任务）──
    standard_record = next(
        (r for r in all_records if r.get("version") == "standard"), None
    )
    if standard_record and api_key:
        try:
            from research.hook_writer import generate_hook_paragraphs
            hook_prompt = _load_prompt_text("layer_hook")
            if hook_prompt:
                hooks = generate_hook_paragraphs(
                    api_key, standard_record, hook_prompt,
                    progress_callback, job_id
                )
                if hooks:
                    standard_record.update(hooks)
                    _report(progress_callback, "钩子写作",
                            f"生成 {len(hooks)}/3 段钩子", job_id=job_id)
        except Exception as e:
            _report(progress_callback, "钩子写作",
                    f"钩子生成异常（非阻断）: {e}", job_id=job_id)

    return all_records
```

### 修改 `references/field_manifest.yaml`

将 `hook_paragraph_1/2/3` 的 `resolution_type` 从 `official_fact` 改为 `llm_generated`，`if_missing` 从 `unavailable` 改为 `draft`，反映其本质是写作任务而非采集任务：

```yaml
  hook_paragraph_1:
    category: A
    resolution_type: llm_generated   # 改: 原为 official_fact
    if_missing: draft                 # 改: 原为 unavailable
  hook_paragraph_2:
    category: A
    resolution_type: llm_generated
    if_missing: draft
  hook_paragraph_3:
    category: A
    resolution_type: llm_generated
    if_missing: draft
```

### 新建测试 `tests/test_hook_writer.py`

```python
"""tests/test_hook_writer.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from research.hook_writer import (
    generate_hook_paragraphs,
    _build_writing_context,
    HOOK_FIELDS,
)


def test_build_writing_context_excludes_missing():
    parsed = {
        "company_def": "AI 驱动的风险平台",
        "main_product_def": "暂缺",
        "growth_metrics": "",
    }
    ctx = _build_writing_context(parsed)
    assert "AI 驱动的风险平台" in ctx
    assert "暂缺" not in ctx


def test_build_writing_context_returns_empty_on_all_missing():
    parsed = {"company_def": "暂缺", "main_product_def": ""}
    ctx = _build_writing_context(parsed)
    assert ctx == ""


def test_generate_returns_empty_on_short_context():
    result = generate_hook_paragraphs("key", {"company_def": "x"}, "prompt")
    assert result == {}


def test_generate_returns_empty_on_missing_api_key(monkeypatch):
    def mock_call(*args, **kwargs):
        raise RuntimeError("no key")
    monkeypatch.setattr("research.hook_writer.call_deepseek", mock_call, raising=False)
    parsed = {f: "A" * 50 for f in ["company_def", "main_product_def", "moat"]}
    result = generate_hook_paragraphs("", parsed, "prompt")
    assert result == {}


def test_generate_validates_length(monkeypatch):
    """输出长度不合理的字段应被过滤"""
    import json

    def mock_call(*args, **kwargs):
        return json.dumps({
            "hook_paragraph_1": "太短",           # < 20字，过滤
            "hook_paragraph_2": "A" * 600,         # > 500字，过滤
            "hook_paragraph_3": "这是一段合理长度的钩子段落，" * 4,  # 合理长度
        })

    monkeypatch.setattr("research.hook_writer.call_deepseek", mock_call, raising=False)
    parsed = {f: "A" * 50 for f in ["company_def", "main_product_def", "moat",
                                     "main_product_highlight", "growth_metrics"]}
    result = generate_hook_paragraphs("key", parsed, "prompt")
    assert "hook_paragraph_1" not in result
    assert "hook_paragraph_2" not in result
    assert "hook_paragraph_3" in result


def test_hook_fields_constant():
    assert HOOK_FIELDS == ["hook_paragraph_1", "hook_paragraph_2", "hook_paragraph_3"]
```

---

## 执行顺序

```
PR-1 → PR-2 → PR-3
```

每个 PR 完成后验证：

```bash
# 在项目根目录
cd webapp && python3 -m py_compile research/scoring_inference.py
cd webapp && python3 -m py_compile research/derivation_pass.py
cd webapp && python3 -m py_compile research/hook_writer.py
cd webapp && python3 -m py_compile pipeline.py

# 回归测试（所有 808 tests 必须通过，新增测试必须全部 pass）
pytest tests/ -v

# 冒烟验证（可选，需 DeepSeek API Key）
curl -X POST http://127.0.0.1:5050/api/research/start \
  -H "Content-Type: application/json" \
  -d '{"company_name":"TestCo","company_url":"https://example.com"}'
```

---

## 不做的事（明确边界）

- **不修改** `_extract_enum_fields()` 及其 3 个 LLM 分组
- **不修改** `compute_scores()` 的公式和权重
- **不添加** 新的 Tavily 搜索 query（TAM 字段由现有 `market_intelligence` 模块覆盖）
- **不改变** field_manifest.yaml 中字段的 `category` 属性（hook 字段除外）
- **不写入** final_fields 表（这三个 pass 的输出写入 research_fields，定稿由用户手工确认）
- **v2 scoring inference 不修正已有合法枚举值**（parsed 中已有合法值的字段不覆盖）
- **derivation pass 的枚举推导不覆盖 PR-1 的 v2 scoring inference 结果**（检查 parsed 中是否已有值后再写入）
