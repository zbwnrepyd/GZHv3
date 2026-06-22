# 研究深度优化方案 — 设计文档

> 版本 1.0 | 2026-06-22 | 目标：提升分析深度，打通数据孤岛，增加时间序列对比能力

---

## 1. 问题诊断

基于实测 token 数据（`layer1=~326, layer2=~445, layer3=~3582 tokens`）：

| 问题 | 根因 | 影响 |
|------|------|------|
| L1/L2 产出是文字段落 | prompt 未要求结构化输出 | 卡片只能用自然语言，无法做对比表格 |
| L3 体积膨胀 | 45+ 字段、三版本的输出格式在同一 prompt | 每个字段的提取精度被均摊，关键数字字段易出错 |
| market_intelligence 孤岛 | CLI JSON 输出不入库，与 L3 互不感知 | TAM/融资数据被 LLM 重新推断，不一致且浪费 token |
| 无时间序列 | 每次研究覆盖写入，无快照机制 | 无法回答"ARR 在加速还是减速" |

---

## 2. 设计目标

1. **L1/L2 输出结构化** — 竞品矩阵、商业模式画布以 JSON Schema 约束输出
2. **L3 拆组调用** — 45+ 字段按语义拆为 3 组，每组独立 prompt + 独立校验
3. **MarketDataBridge** — market_intelligence → 主管道数据注入，消除重复推断
4. **TimeSeriesSnapshotter** — 每次研究存快照，支持字段级跨时间 diff
5. **L0 质量门控** — L0 输出不完整时阻断下游，不传播错误
6. **Evidence 锚点全覆盖** — L1/L2 输出也绑 evidence_snippet

---

## 3. Token 实测要求

以下数字均为**预估**，每个 L 层的 prompt 改动后需用 tiktoken 实测：

```python
import tiktoken
enc = tiktoken.encoding_for_model("cl100k_base")  # 或项目使用的 encoding
for fname in ["layer1-hv-analysis.md", "layer2-business.md", "layer3-group-market.md",
              "layer3-group-operating.md", "layer3-group-facts.md"]:
    with open(f"prompts/{fname}") as f:
        tokens = len(enc.encode(f.read()))
    print(f"{fname}: {tokens} tokens")
```

**阈值规则**：
- 单个 prompt > 4000 tokens → 需要进一步拆分
- Schema 定义 > 400 tokens → 改用简化的自然语言格式描述
- 实测数字写入 `docs/prompt-token-budget.md`，每次 prompt 变更后更新

---

## 4. 架构设计

### 4.1 改动全景图

```
研究流水线（pipeline.py）

Before:
  Collect → Clean→Chunk→Rank→Pack → L0 → L1 → L2 → L3×3版本 → L3枚举 → Write DB

After:
  Collect → Clean→Chunk→Rank→Pack
    → [L0 Gate] → Block if incomplete
    → L1 Structured (竞品矩阵 JSON, Pydantic 校验)
    → L2 Structured (商业模式画布 JSON, Pydantic 校验)
    → [MarketDataBridge] 注入 TAM/融资/增长数据
    → L3-A 基础事实组 (15 fields)
    → L3-B 市场与运营组 (18 fields)
    → L3-C 商业与竞争组 (12 fields)
    → L3枚举 (不变)
    → [TimeSeriesSnapshotter] 写入 company_snapshots
    → Write DB
```

### 4.2 新增模块

| 模块 | 文件 | 职责 |
|------|------|------|
| L0 质量门控 | `webapp/research/l0_gate.py` | 校验 L0 输出完整性，不通过则阻断 |
| L1 结构化提取器 | `webapp/research/competitive_matrix.py` | LLM 输出竞品矩阵 JSON → Pydantic 校验 |
| L2 结构化提取器 | `webapp/research/business_canvas.py` | LLM 输出商业模式画布 JSON → Pydantic 校验 |
| MarketDataBridge | `webapp/research/market_data_bridge.py` | 读 market_estimates 表 → 注入 L3 context |
| TimeSeriesSnapshotter | `webapp/research/time_series.py` | 写 company_snapshots 表，支持 diff 查询 |
| Evidence 锚点校验 | 扩展 `webapp/research/field_validator.py` | 所有结构化字段强制要求 evidence_snippet |

### 4.3 修改现有模块

| 文件 | 改动 |
|------|------|
| `prompts/layer1-hv-analysis.md` | 输出格式从自然语言改为 JSON Schema，新增 evidence_snippet 要求 |
| `prompts/layer2-business.md` | 输出格式从自然语言改为 JSON Schema，新增 evidence_snippet 要求 |
| `prompts/layer3-field-extraction.md` | 拆为 3 个文件：`layer3-group-facts.md`、`layer3-group-market.md`、`layer3-group-operating.md` |
| `webapp/pipeline.py` | 插入 MarketDataBridge、TimeSeriesSnapshotter 调用点 |
| `webapp/research/field_resolver.py` | 新增 competitive_matrix 和 business_canvas 的 resolution_type |
| `references/field_manifest.yaml` | 新增 L1/L2 结构化字段的 manifest 条目 |
| `db/migrations/` | 新增 049_company_snapshots.sql |

---

## 5. 模块详细设计

### 5.1 L0 质量门控 (`l0_gate.py`)

**触发点**：L0 LLM 调用完成后、L1 调用前。

**校验规则**：

```python
L0_REQUIRED_FIELDS = ["company_name", "company_def", "main_product_name", "founded_date"]
L0_MIN_CONTENT_LENGTH = 200  # 字符

def validate_l0_output(l0_result: dict) -> tuple[bool, list[str]]:
    errors = []
    for field in L0_REQUIRED_FIELDS:
        if not l0_result.get(field):
            errors.append(f"L0 missing required field: {field}")
    # 整体输出不能太短
    total_text = json.dumps(l0_result, ensure_ascii=False)
    if len(total_text) < L0_MIN_CONTENT_LENGTH:
        errors.append(f"L0 output too short: {len(total_text)} chars")
    return len(errors) == 0, errors
```

**失败行为**：`PipelineError("L0 output incomplete, abort downstream")`，任务标记 failed，不继续 L1/L2/L3。

**为什么是这四个字段**：`company_name` 和 `company_def` 是身份基础，`main_product_name` 是所有产品分析的前提，`founded_date` 验证 L0 确实做了时间线提取。四个全缺 = L0 没正常输出。

---

### 5.2 L1 竞品矩阵提取器 (`competitive_matrix.py`)

**输入**：L0 输出 + packed_context（竞品相关 chunk）

**LLM 输出 Schema**：

```json
{
  "competitors": [
    {
      "name": "string",
      "url": "string | null",
      "overlap_areas": ["string (≤3)"],
      "strengths": ["string (≤3)"],
      "weaknesses": ["string (≤3)"],
      "threat_level": "high | medium | low",
      "evidence_snippets": ["string (≤100 chars each, from source)"]
    }
  ],
  "target_company_position": "leader | strong_contender | niche_player | early_stage",
  "competitive_landscape_summary": "string (≤100 chars)"
}
```

**Pydantic 校验规则**：
- `threat_level` 必须在枚举中
- `evidence_snippets` 非空数组（至少 1 条），每条 ≤ 100 字符
- `overlap_areas` 至少 1 个
- `target_company_position` 必须在枚举中
- 竞品数组 ≥ 2 个，≤ 6 个

**evidence_snippet 降级路径**：
- snippet 为空 → `confidence: low` → 进入 `unverified_fields` 列表
- 卡片渲染时显示「待核实」标注（而非隐藏字段）
- `unverified_fields` 写入 `research_fields` 表，`resolution_status = "llm_extracted"`，`confidence_level = "estimated"`

**Token 预估**：L1 prompt 当前 ~326 tokens，加 Schema 后 ~500 tokens（Schema 约 170 tokens，在阈值内）

---

### 5.3 L2 商业模式画布提取器 (`business_canvas.py`)

**输入**：L0 输出 + L1 竞品矩阵 + packed_context（商业模式相关 chunk）

**LLM 输出 Schema**：

```json
{
  "revenue_model": {
    "primary": "subscription | usage_based | enterprise_contract | advertising | marketplace | freemium | other",
    "secondary": ["string (≤2)"],
    "pricing_public": true,
    "evidence_snippets": ["string"]
  },
  "unit_economics": {
    "has_ltv_cac_data": true,
    "ltv_estimate": "string | null",
    "cac_estimate": "string | null",
    "payback_period_months": "integer | null",
    "gross_margin_estimate": "string | null",
    "disclaimer": "string（没数据时说明为什么）",
    "evidence_snippets": ["string"]
  },
  "growth_loops": [
    {
      "loop_type": "viral | content | sales | product_led | partnership | paid_acquisition",
      "description": "string (≤80 chars)",
      "strength": "strong | moderate | weak",
      "evidence_snippets": ["string"]
    }
  ],
  "moat_dimensions": [
    {
      "dimension": "network_effects | data_moat | switching_cost | brand | scale_economy | tech_complexity | regulatory | counter_positioning",
      "strength": "strong | moderate | weak | none",
      "description": "string (≤100 chars)",
      "evidence_snippets": ["string"]
    }
  ],
  "business_model_summary": "string (≤150 chars)"
}
```

**Pydantic 校验规则**：
- `revenue_model.primary` 必须在枚举中
- `moat_dimensions[].dimension` 必须在 8 种壁垒类型中（对应 Helmer 7 Powers + 技术复杂度）
- `growth_loops[].loop_type` 必须在枚举中
- 所有 `evidence_snippets` 非空

**Token 预估**：L2 prompt 当前 ~445 tokens，加 Schema 后 ~800 tokens（Schema 约 350 tokens，在阈值内）

---

### 5.4 MarketDataBridge (`market_data_bridge.py`)

**问题**：market_intelligence 模块输出的 TAM/融资数据仅在 CLI JSON 中出现，未持久化到 research_fields。L3 每次重新从 web search 结果推断，浪费 token 且可能产生不一致的数值。

**做法**：

```python
class MarketDataBridge:
    """桥接 market_intelligence 模块的市场数据到主管道"""

    def fetch_market_context(self, company_key: str) -> dict:
        """从 market_estimates 表读取已估算的市场数据"""
        conn = sqlite3.connect(research_db_path)
        rows = conn.execute("""
            SELECT field_key, result_value, result_text, currency, year,
                   estimate_type, confidence, status, source_url, disclaimer
            FROM market_estimates
            WHERE company_key = ? AND status != 'unavailable'
            ORDER BY confidence DESC
        """, (company_key,)).fetchall()
        return self._format_as_context(rows)

    def inject_into_l3_context(self, company_key: str, packed_context: str) -> str:
        """将市场数据注入 L3 的 packed_context，作为已知事实"""
        market_data = self.fetch_market_context(company_key)
        if not market_data:
            return packed_context  # 无市场数据时不注入，不报错

        context_block = "\n\n## 已知市场数据（来自 market_intelligence 模块）\n"
        for item in market_data:
            context_block += f"- {item['field_key']}: {item['value_text']} "
            context_block += f"(来源: {item['source_url'] or '估算'}, "
            context_block += f"置信度: {item['confidence']})\n"

        # 注入到 packed_context 末尾，不替换原有内容
        return packed_context + "\n" + context_block
```

**调用点**：`pipeline.py` 中 L2 完成后、L3 各组调用前。

**为什么不是 CLI → DB 自动写入**：market_intelligence 是独立 CLI 工具，和主管道异步运行。桥接层只读取 `market_estimates` 表中已有的数据。如果表为空（第一次研究），桥接层是 no-op，不影响主管道。

**触发 market_intelligence 的时机**：在主管道的 `_collect_via_adapters` 之后，如果检测到 `market_estimates` 中该公司无记录，自动触发一次 `market_intelligence --no-crunchbase`（仅 Tavily 搜索，不需要 API Key）。

---

### 5.5 TimeSeriesSnapshotter (`time_series.py` + 新表)

**新表**（迁移 049）：

```sql
CREATE TABLE IF NOT EXISTS company_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_key TEXT NOT NULL,
    snapshot_at TEXT NOT NULL DEFAULT (datetime('now')),
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('full', 'fields_only', 'metrics_only')),
    field_key TEXT NOT NULL,
    field_value TEXT,
    value_type TEXT,
    norm_value REAL,
    unit TEXT,
    resolution_status TEXT,
    confidence_level TEXT,
    source_urls TEXT,
    research_run_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (company_key) REFERENCES companies(company_key)
);

CREATE INDEX idx_snapshots_company_field
ON company_snapshots(company_key, field_key, snapshot_at);
```

**Snapshotter 逻辑**：

```python
class TimeSeriesSnapshotter:
    def snapshot(self, company_key: str, fields: dict,
                 snapshot_type: str = "full",
                 research_run_id: str = None) -> int:
        """为本次研究的字段值写入快照。返回写入行数。"""

    def diff(self, company_key: str, field_key: str) -> dict | None:
        """返回某字段的最新两次快照的差异。
        Returns: {
            "field_key": "arr",
            "previous": {"value": "$10M", "snapshot_at": "2026-01-15"},
            "current": {"value": "$25M", "snapshot_at": "2026-06-22"},
            "change_pct": "+150%",
            "direction": "up"
        }
        """

    def list_comparable_fields(self, company_key: str) -> list[str]:
        """返回有 2+ 次快照的可对比字段列表"""
```

**调用点**：`pipeline.py` 中 `_write_to_db` 之后。

**为什么是行级存储（每字段一行）而不是 JSON blob**：
- 支持字段级 diff 查询（不需要解析 JSON）
- 支持按字段类型筛选（只看 metrics_only）
- 随时间推移不会膨胀（每次研究新增的行数 = 字段数）

---

### 5.6 L3 拆组

当前 L3 prompt 体积 3582 tokens，45+ 字段在同一 prompt。**字段越多，每个字段的平均注意力越低**。

**拆为三组**：

| 组 | 文件 | 字段数 | 预估 tokens | 并行策略 |
|----|------|--------|-------------|----------|
| L3-A 基础事实 | `layer3-group-facts.md` | ~15 | ~1200 | 与 B 并行 |
| L3-B 市场与运营 | `layer3-group-market.md` | ~18 | ~1500 | 与 A 并行 |
| L3-C 商业与竞争 | `layer3-group-operating.md` | ~12 | ~1300 | 串行（依赖 A 的身份字段 + B 的市场数据） |

**分组原则**：
- A 组（基础事实）：公司名、创始人、产品、融资、团队 — 可独立提取，不需要市场上下文
- B 组（市场与运营）：TAM/SAM、市场规模、用户指标、增长指标 — 需要 MarketDataBridge 注入，但不需要 A 的结果
- C 组（商业与竞争）：壁垒、生态位、定价、GTM — 依赖 A 的身份确认 + B 的市场大小做判断

**Token 预算**：
- 每组 ≤ 2000 tokens（指令 + Schema + few-shot 示例）
- 输入 context 共享 L0 输出 + packed_context
- B 组额外注入 MarketDataBridge 上下文（≤ 500 tokens）

---

## 6. 数据模型变更

### 6.1 新表：company_snapshots（迁移 049）

见 §5.5。

### 6.2 新字段：manifest 扩展

`references/field_manifest.yaml` 新增条目：

```yaml
# L1 竞品矩阵产出字段
competitors_structured:
  category: A
  resolution_type: structured_extraction
  if_missing: unavailable
  type: json_text
  source_module: competitive_matrix

# L2 商业模式画布产出字段
business_canvas:
  category: A
  resolution_type: structured_extraction
  if_missing: unavailable
  type: json_text
  source_module: business_canvas

unit_economics:
  category: D
  resolution_type: private_metric
  if_missing: unavailable
  source_module: business_canvas

growth_loops:
  category: A
  resolution_type: structured_extraction
  if_missing: unavailable
  type: json_text
  source_module: business_canvas

moat_dimensions:
  category: A
  resolution_type: structured_extraction
  if_missing: unavailable
  type: json_text
  source_module: business_canvas
```

### 6.3 RenderContract 变化

`contracts/render_contract.schema.json` 中 items 的 status enum 无变化。新字段（competitors_structured、business_canvas）通过已有的 card_compositions 表分配到卡片，走现有渲染流程。

---

## 7. unreviewed_fields 降级路径

所有结构化输出的 evidence_snippet 为空时，统一的降级路径：

```
evidence_snippets 为空
  → field_validator 标记 confidence: low
  → research_fields 写入 resolution_status: "llm_extracted"
  → confidence_level: "estimated"（而非 "verified"）
  → 不进入 final_fields 的 auto-confirm 路径
  → 卡片渲染时显示「⚡ 待核实」标注
  → 用户可在定稿台手动确认或修改
```

**不隐藏字段**。理由：LLM 提取的结果即使无 evidence，对用户仍有参考价值。隐藏 = 用户不知道系统"看到了但不确定"，标注 = 用户知道需要自己判断。

---

## 8. 开发依赖的无第三方库原则

所有新增模块使用已有依赖：
- Pydantic（已在 field_validator.py 使用）
- sqlite3 标准库
- 不引入新的 LLM 调用框架（沿用 `deepseek_client.py`）

---

## 9. 风险与回退

| 风险 | 缓解 |
|------|------|
| L3 拆组后字段遗漏 | 三组字段覆盖率检查脚本（`scripts/l3_coverage_check.py`） |
| Schema 体积膨胀 | 实测 token，超 400 tokens 就改用简化格式 |
| MarketDataBridge 注入噪声 | 仅注入 confidence ≥ 0.30 的数据，低置信度数据不注入 |
| 历史快照表膨胀 | 超过 100 条/公司时只保留最新 50 条，旧快照归档 |
| L0 Gate 误阻断 | 仅检查 4 个最基础字段，不扩大校验范围 |

---

## 10. 验收标准

1. L1 输出可通过 `jq` 解析为合法 JSON，含 ≥ 2 个竞品
2. L2 输出含 8 种壁垒维度中的 ≥ 4 种
3. 存在 `company_snapshots` 表中至少一次快照的研究公司，`diff()` 返回非空结果
4. MarketDataBridge 在 market_estimates 有数据时，L3-B 输出引用了 market_intelligence 的数字（而非重新推断）
5. L0 输出缺少 `company_name` 时，任务标记 `failed`，不在后续表写入数据
6. 所有新 prompt 文件 token 实测值 ≤ 2000（不含输入 context）
7. 全量 pytest ≥ 现有通过数 (636+) + 新增测试 ≥ 50 个
