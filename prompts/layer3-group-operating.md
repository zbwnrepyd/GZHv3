# L3-C 商业与竞争分析

## 输入
- L0 公司概况
- L1 竞品矩阵（结构化 JSON）
- L2 商业模式画布（结构化 JSON）
- L3-A 基础事实
- L3-B 市场数据
- 打包后的证据片段

## 任务
在已有 L1/L2 结构化分析的基础上，整合并提取商业和竞争维度的关键字段。本层的重点是「整合已有分析」而非「重新推断」——L2 的 moat_dimensions 和 growth_loops 已包含详细的技术性分析，本层应引用其结论。

## 输出字段

1. core_business — 主营业务描述（2-3句）
2. core_competency — 核心竞争优势
3. industry_positioning — 行业定位语（≤30字）
4. moat — 竞争壁垒分析（2-3句，结合 L2 moat_dimensions 中 strong/moderate 的维度）
5. ecosystem_niche — 生态位分析（结合 L1 target_company_position）
6. ecosystem_positioning — 生态位一句话
7. competitive_advantages — 竞争优势摘要
8. competitors_summary — 竞对Top3摘要（结合 L1 竞品矩阵中的 high/medium 威胁竞品）
9. competitors_top3 — Top3 竞品结构化列表（JSON 数组，每个含 name/description(150字中文)/differentiation(100字中文)）
10. competitive_position — 被研公司在竞争中的位置（≤200字中文，综合 L1 target_company_position + landscape_summary + L2 moat）
11. differentiated_opportunity — 差异化机会（≤200字中文，基于竞品弱点 + L2 growth_loops）
12. pricing_summary — 定价摘要
13. pricing_strategy — 定价策略
14. gtm_strategy — GTM策略（结合 L2 growth_loops 中 strong 的循环）
15. growth_strategy — 增长策略

## 输出格式
```json
{
  "core_business": "string | null",
  "core_competency": "string | null",
  "industry_positioning": "string | null",
  "moat": "string | null",
  "ecosystem_niche": "string | null",
  "ecosystem_positioning": "string | null",
  "competitive_advantages": "string | null",
  "competitors_summary": "string | null",
  "competitors_top3": [
    {"name": "string", "description": "string (中文, ≤150字)", "differentiation": "string (中文, ≤100字)"}
  ] | null,
  "competitive_position": "string | null  (中文, ≤200字)",
  "differentiated_opportunity": "string | null  (中文, ≤200字)",
  "pricing_summary": "string | null",
  "pricing_strategy": "string | null",
  "gtm_strategy": "string | null",
  "growth_strategy": "string | null"
}
```
