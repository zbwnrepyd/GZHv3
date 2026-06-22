# Prompt Token 预算实测

> 最后更新: 2026-06-22 | 方法: 词数估算 (word-count heuristic), tiktoken 不可用

## L3 拆分效果

| 文件 | tokens (估) | chars | 预算 | 状态 |
|------|-------------|-------|------|------|
| `layer3-field-extraction.md` (旧) | ~3582 | 11237 | 4000 | ❌ 超预算 |
| `layer3-group-facts.md` (A) | ~337 | 1163 | 2000 | ✅ |
| `layer3-group-market.md` (B) | ~440 | 1502 | 2000 | ✅ |
| `layer3-group-operating.md` (C) | ~365 | 1229 | 2000 | ✅ |
| **三组合计** | **~1142** | 3894 | — | **-68%** |

## L1/L2 Schema 添加后

| 文件 | tokens (估) | chars | 变化 | 状态 |
|------|-------------|-------|------|------|
| `layer1-hv-analysis.md` | ~559 | 1753 | +233 (Schema ~170 tokens) | ✅ |
| `layer2-business.md` | ~767 | 2317 | +322 (Schema ~350 tokens) | ✅ |

## 阈值规则

- 单 prompt > 4000 tokens → 需要拆分
- Schema 定义 > 400 tokens → 改用简化自然语言格式
- 实测需 tiktoken (`pip install tiktoken`)，词数估算仅供参考

## 实测命令

```bash
python3 -c "
import tiktoken
enc = tiktoken.encoding_for_model('cl100k_base')
for f in ['layer3-group-facts.md','layer3-group-market.md','layer3-group-operating.md']:
    with open(f'prompts/{f}') as fp:
        print(f'{f}: {len(enc.encode(fp.read()))} tokens')
"
```
