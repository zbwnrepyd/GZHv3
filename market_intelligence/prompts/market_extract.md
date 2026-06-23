# 市场数字提取器 Market Number Extractor

从非结构化文本中提取市场规模、TAM、CAGR、营收、ARR、融资等数字。

## 输入

一段来自网页或报告的文字，可能包含市场规模、TAM、CAGR、营收/ARR、融资信息。

## 输出格式

```json
{
  "found": true,
  "extractions": [
    {
      "field": "market_size_value|tam_value|funding_total|revenue_estimate|arr_range",
      "value": 10.4,
      "unit": "B",
      "currency": "USD",
      "year": 2025,
      "scope": "AI coding assistant market, global",
      "snippet": "原文中包含该数字的完整句子",
      "is_range": false,
      "range_low": null,
      "range_high": null,
      "confidence": 0.85
    }
  ]
}
```

如果文字中没有可提取的市场数据，返回：
```json
{"found": false, "reason": "未找到可提取的市场数据"}
```

## 规则

1. 单位转换：B = 十亿、M = 百万、K = 千。例如 "$10.4 billion" → value=10.4, unit="B"
2. 优先采用最近年份的数据
3. 区分 TAM（总可寻址市场）和当前市场规模
4. 区间值标记 is_range=true，提供 range_low 和 range_high
5. 不要编造数字。如果原文没有明确数字，不要猜测
6. 不确定时 confidence 设低（<0.5）
7. 同时处理中英文文本
8. revenue_estimate 和 arr_range 只在文字明确提到营收或 ARR 数字时提取
