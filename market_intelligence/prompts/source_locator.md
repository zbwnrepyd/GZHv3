# 来源定位器 Source Locator

帮助定位包含市场/融资数据的来源 URL。

## 输入

```json
{
  "company_name": "Cursor",
  "category": "AI coding assistant",
  "fields_needed": ["market_size_value", "tam_value", "funding_total", "revenue_estimate"]
}
```

## 输出格式

```json
{
  "queries": [
    {
      "search_query": "AI coding assistant market size 2025",
      "target_field": "market_size_value",
      "source_type_hint": "market_report",
      "priority": "high"
    }
  ],
  "suggested_sources": [
    {
      "url": "https://www.grandviewresearch.com/industry-analysis/ai-coding-tools-market",
      "description": "Grand View Research 的 AI 编码工具行业分析报告",
      "target_fields": ["market_size_value", "market_cagr"],
      "expected_data_type": "market_size_report",
      "reliability": "medium"
    }
  ]
}
```

## 规则

1. 生成 3-5 个精准搜索查询，优先找行业报告和公开财务信息
2. 建议来源可以包括已知的市场研究机构：
   - Grand View Research（grandviewresearch.com）
   - Gartner（gartner.com）
   - IDC（idc.com）
   - Statista（statista.com）
   - Forrester（forrester.com）
3. 对于投资赛道数据，优先 a16z、Sequoia、YC、Bessemer 的市场地图/赛道报告
4. 对于融资数据，优先 Crunchbase、PitchBook 页面
5. 不要编造 URL！suggested_sources 只是建议方向，系统自己执行搜索
6. 如果是找不到具体 URL 的品类，多给几条搜索查询
