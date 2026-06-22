# 剩余工作计划

> 2026-06-22 | 深度优化主链已完成（9 commits, 805 tests），以下是收尾和验证

---

## P0 — 端到端验证（1 任务）

### Task 9: 真实公司端到端测试

**为什么**：所有模块的单元测试都过了，但没有在真实数据上验证过整条链路。

**做法**：

1. 启动 Flask：`cd webapp && python3 app.py`
2. 发起研究：
   ```bash
   curl -X POST http://127.0.0.1:5050/api/research/start \
     -H "Content-Type: application/json" \
     -d '{"company_name":"Cursor","company_url":"https://cursor.com"}'
   ```
3. 等研究完成，检查数据库：
   ```bash
   # 验证 L1 竞品矩阵已写入
   sqlite3 db/research_db.sqlite \
     "SELECT field_key, length(field_value) FROM research_fields WHERE company_name='Cursor' AND field_key LIKE '%competitor%'"

   # 验证 L0 门控没误杀
   sqlite3 db/research_db.sqlite \
     "SELECT status, error FROM research_jobs WHERE company_name='Cursor' ORDER BY id DESC LIMIT 1"

   # 验证快照已写入
   sqlite3 db/research_db.sqlite \
     "SELECT COUNT(*) FROM company_snapshots WHERE company_key='cursor_com'"
   ```
4. 如果研究失败：看 error 信息，确认是不是门控误阻断或 L3 拆组问题

**验收**：研究 `status=completed`，`company_snapshots` 有数据，L1/L2 结构化字段非空

---

## P1 — 功能补全（2 任务）

### Task 10: market_intelligence 自动触发

**为什么**：MarketDataBridge 桥已搭好，但桥那头的 `market_estimates` 表是空的——market_intelligence 是独立 CLI，没人手动跑就永远没数据。

**做法**：

在 `pipeline.py` 的 `run_pipeline()` 中，`_collect_via_adapters()` 完成后插入：

```python
# 检查是否需要运行 market_intelligence
from research.market_data_bridge import MarketDataBridge
bridge = MarketDataBridge()
existing_data = bridge.fetch_market_context(company_key)
if not existing_data and domain:
    import subprocess, sys
    subprocess.run([
        sys.executable, "-m", "market_intelligence",
        "--company", display_name,
        "--domain", domain,
        "--no-crunchbase",  # 不需要 API key
        "--timeout", "60",
    ], timeout=90, capture_output=True)
```

**文件**：只改 `webapp/pipeline.py`（~10 行）
**测试**：mock subprocess.run，验证 market_estimates 为空时触发、有数据时跳过
**验收**：研究 Cursor 后 `market_estimates` 表自动有数据

### Task 11: 前端 confidence_level 标注

**为什么**：RenderContract 里已经有 `confidence_level` 字段了，但前端定稿台没显示。用户看不到哪些数据是 verified、哪些是 benchmark。

**做法**：

在 `webapp/static/js/editor.js` 的字段渲染逻辑中，`confidence_level` 对应的视觉标记：

```javascript
const CONFIDENCE_LABELS = {
  verified:   { text: '✓ 已验证',  cls: 'badge-verified' },
  estimated:  { text: '≈ 估算',    cls: 'badge-estimated' },
  benchmark:  { text: 'ⓘ 行业基准', cls: 'badge-benchmark' },
  unavailable:{ text: '— 未公开',  cls: 'badge-unavailable' },
};
```

CSS 在 `webapp/static/css/editor.css` 加 4 个 class（绿/黄/灰/红线）。

**文件**：
- 改：`webapp/static/js/editor.js`
- 改：`webapp/static/css/editor.css`
**测试**：检查 `?company=Cursor` 页面是否有标记出现
**验收**：定稿台字段旁边显示置信度标记

---

## P2 — 技术债清理（2 任务）

### Task 12: 删除 L3 fallback 路径

**为什么**：pipeline.py 中 L3 三组调用有 `try: load new prompts / except FileNotFoundError: use old prompt` 的 fallback 逻辑。端到端验证通过后，旧 L3 路径是死代码。

**做法**：

1. 删除 `llm_analysis()` 中 `try/except FileNotFoundError` 包裹，直接加载新 prompt
2. 删除 fallback 分支中的单 L3 调用代码
3. 更新 `test_pipeline.py` 中 mock `_load_prompt_text` 让旧路径不再可到达的测试

**文件**：只改 `webapp/pipeline.py`（删 ~30 行）和 `tests/test_pipeline.py`（删 fallback 测试）
**验收**：全量 pytest 保持 805+

### Task 13: L0 parsed 传递到下游

**为什么**：code review 发现的——gate 把 L0 解析成了 `l0_parsed` dict，但传给 L1 的仍然是原始字符串 `l0_result`。如果原始字符串有 markdown 代码块或格式问题，L1 会受影响。

**做法**：

```python
# 改前：L1 收到原始字符串
l1_result = call_deepseek(api_key, l1_prompt, l0_result, ...)

# 改后：L1 收到 gate 已校验的干净 JSON
l1_result = call_deepseek(api_key, l1_prompt,
    json.dumps(l0_parsed, ensure_ascii=False, indent=2), ...)
```

**文件**：只改 `webapp/pipeline.py`（~5 行），L1/L2/L3 各一处
**风险**：如果 L1 prompt 里的 few-shot 示例依赖原始 LLM 输出格式（含 markdown 代码块），改后会破坏预期格式。需要先读 L1 prompt 确认。如果依赖原始格式，则不动 L1，只在 L2/L3 改。
**验收**：端到端测试通过

---

## 总览

| # | 优先级 | 预估时间 | 改动范围 |
|---|--------|----------|----------|
| 9 | P0 | 15min 等待 | 无代码，跑研究+检查 |
| 10 | P1 | 30min | pipeline.py +10 行 |
| 11 | P1 | 45min | editor.js + editor.css |
| 12 | P2 | 20min | pipeline.py -30 行 |
| 13 | P2 | 15min | pipeline.py ~5 行 |

**总计约 2 小时**。建议先做 Task 9，验证链路通畅后一次性做 10-13。
