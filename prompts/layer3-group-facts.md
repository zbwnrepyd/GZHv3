# L3-A 基础事实提取

## 输入
- L0 清理后的公司概况
- 打包后的证据片段（packed_context）

## 任务
从证据中提取以下字段。每个字段需要精确描述，有明确数字时给出数字。

## 输出字段

1. company_name — 公司完整官方名称
2. company_type — 公司类型（B2B SaaS / B2C / Marketplace / Developer Tools / ...）
3. company_def — 一句话公司定义（≤50字）
4. location — 总部城市、国家
5. founded_date — 成立年份
6. website_url — 官网 URL
7. founder_name — 创始人姓名
8. founder_bg — 创始人职业背景（2-3句）
9. founder_edu — 学历背景
10. founder_achievement — 关键成就
11. team_size — 团队规模（如有）
12. team_highlight — 团队亮点
13. funding_info — 融资信息（总金额/最新轮次/估值）
14. main_product_name — 主产品名
15. main_product_def — 产品定义（≤50字）

## 输出格式
输出严格 JSON。字段值为 null 表示未找到，不要编造：

```json
{
  "company_name": "string | null",
  "company_type": "string | null",
  "company_def": "string | null",
  "location": "string | null",
  "founded_date": "string | null",
  "website_url": "string | null",
  "founder_name": "string | null",
  "founder_bg": "string | null",
  "founder_edu": "string | null",
  "founder_achievement": "string | null",
  "team_size": "string | null",
  "team_highlight": "string | null",
  "funding_info": "string | null",
  "main_product_name": "string | null",
  "main_product_def": "string | null"
}
```
