# TAM 参数提取器 Parameter Extractor

从证据文本中提取自底向上 TAM 估算所需的三个参数：可寻址用户数、付费渗透率、ARPU。

## 输入

关于某市场品类的文字和数据，可能来自市场报告、公司财报、投资者材料、新闻报道。

## 输出格式

```json
{
  "found": true,
  "parameters": {
    "total_addressable_users": {
      "value": 10000000,
      "unit": "individuals",
      "source_description": "基于 Stack Overflow 2025 调查和 GitHub 活跃用户统计",
      "confidence": 0.75
    },
    "penetration_rate": {
      "value": 0.05,
      "unit": "ratio",
      "source_description": "参考同类 AI 编码工具在企业中的渗透率",
      "confidence": 0.50
    },
    "arpu": {
      "value": 240,
      "currency": "USD",
      "period": "annual",
      "source_description": "基于公开定价页：Pro 版 $20/月",
      "confidence": 0.70
    }
  },
  "region": "全球",
  "segment": "AI coding assistant",
  "year": 2025,
  "explanation": "TAM = 1000万专业开发者 × 5% 付费渗透率 × $240/年 = $1.2亿"
}
```

如果关键参数无法估算：
```json
{"found": false, "reason": "缺少 total_addressable_users 数据，无法估算"}
```

## 规则

1. total_addressable_users：全球范围内该品类所有潜在买家/用户数量
   - unit 可选：individuals（个人）、organizations（企业）、developers（开发者）
2. penetration_rate：当前或未来3年的付费渗透率，0.0-1.0，保守估计
3. arpu：每用户/每账号年收入
   - period 可选：annual 或 monthly
   - 基于公开定价信息，优先采用付费版定价的中间档
4. 优先采用引用来源明确的数据，不编造
5. 如果是从竞争品类推的，标注 confidence 较低
6. 如果参数完全无法判断，confidence=0 并说明原因
7. 所有数据标注是否来自明确出处（source_description）
