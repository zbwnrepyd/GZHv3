# L3-B 市场与运营指标提取

## 输入
- L0 公司概况
- L1 竞品矩阵
- 已知市场数据（如有，来自 MarketDataBridge，标注了来源和置信度——这些数据已经过独立验证，可直接使用其数值）
- 打包后的证据片段

## 任务
提取市场和运营指标。已知市场数据中已有某字段值时，直接使用已知数据，不要重新推断。

## 输出字段

### 市场赛道
1. market_track — 所属赛道
2. market_subtrack — 细分赛道
3. market_size_value — 赛道市场规模数字
4. market_size_currency — 币种
5. market_size_year — 数据年份
6. market_cagr — 市场复合增长率

### TAM
7. tam_value — TAM 数字
8. tam_currency — 币种
9. tam_year — 年份

### 市场格局
10. market_landscape_summary — 赛道格局（2-3句）
11. market_landscape_top_players — Top玩家 JSON 列表
12. regional_market_focus — 地区市场
13. regional_markets — 分地区描述
14. market_opportunity — 赛道机会（2-3句）

### 运营指标（仅当有公开数据时）
15. mau — 月活用户数
16. mau_as_of — 统计时间
17. revenue_metrics — 营收指标
18. growth_metrics — 增长指标

## 输出格式
```json
{
  "market_track": "string | null",
  "market_subtrack": "string | null",
  "market_size_value": "number | null",
  "market_size_currency": "string | null",
  "market_size_year": "number | null",
  "market_cagr": "string | null",
  "tam_value": "number | null",
  "tam_currency": "string | null",
  "tam_year": "number | null",
  "market_landscape_summary": "string | null",
  "market_landscape_top_players": "array | null",
  "regional_market_focus": "array | null",
  "regional_markets": "string | null",
  "market_opportunity": "string | null",
  "mau": "string | null",
  "mau_as_of": "string | null",
  "revenue_metrics": "string | null",
  "growth_metrics": "string | null"
}
```

如果不确定，填 null。私有运营指标（mau/revenue_metrics/growth_metrics）仅在有明确公开数据时填写。
