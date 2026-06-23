# Layer 3 — 字段提取（{{VERSION}}版）

你是AI初创公司知识卡片内容生成器。基于前序分析结果（Layer 0-2），提取并生成知识卡片所需的全部字段。

## 版本要求：{{VERSION}}

{{VERSION_INSTRUCTIONS}}

## 输出字段

输出一个 JSON 对象。**所有字段必须有值**——找不到信息的字段填 `"暂缺"`。绝不编造。
**私有指标约束**：私有经营指标（`mau`/`retention_rate`/`ltv`/`cac`/`churn_rate`/`gross_margin`/`burn_rate`/`runway_months`）仅在确有公开来源（官方披露、财报、权威媒体引用）时填写具体数值，否则留空（填 `"暂缺"` 或 null）。禁止根据融资额、团队规模或行业惯例倒推编造数值。

```json
{
  "company_type": "公司类型标签（如：AI视频生成平台 / AI代码助手 / LLM基础设施）",

  "location": "总部城市，国家",
  "company_def": "公司一句话定义（50字内）",
  "company_achievement": "公司级别成就（100字内）。聚焦公司整体里程碑而非单一产品：已完成的融资轮次与金额、签约的知名客户名称、获得的媒体引用数据或奖项认可、用户规模里程碑。与 main_product_achievement 区分：前者写公司，后者写产品。找不到填「暂缺」。",
  "founder_name": "创始人姓名",
  "founder_edu": "创始人学历背景",
  "founder_bg": "创始人工作背景（公司、职位）",
  "founder_achievement": "创始人过往成就（获奖、前公司成就等）",
  "team_size": "团队规模（如：约50人 / 暂缺）",
  "team_highlight": "团队亮点（学历/能力/履历的突出点）",
  "funding_info": "融资信息（轮次、金额、投资方、估值、日期）。格式：X轮 $XM，投资方A、B，估值$XM（YYYY-MM）",
  "website_url": "官网URL",

  "main_product_name": "主产品名称",
  "main_product_def": "产品定义（一款什么样的产品，50字内）",
  "main_product_highlight": "最突出亮点功能（从解决痛点角度，一句话）",
  "main_product_achievement": "产品成就（GitHub Star/PH投票/X大V转发/收入/流量等，选最有说服力的一项，含数据来源）",
  "main_product_img_src": "产品图片可能的来源URL（官网截图位置或产品截图描述）",
  "tech_stack": "技术栈描述（100字内）。结合 stack_layer 和 ai_model_dependency 枚举展开为可读文字：核心技术选型是什么（如：基于 GPT-4o API + 自研 RAG 管道）、主要编程语言/框架、自研与调用第三方 API 的比例说明。",

  "office_photo_hints": {
    "newsroom_url": "公司新闻/媒体页URL，如 https://anthropic.com/news（找不到填空字符串）",
    "about_url": "公司About页URL，如 https://anthropic.com/about（找不到填空字符串）",
    "linkedin_url": "公司LinkedIn页URL（如已知，找不到填空字符串）"
  },

  "revenue_model": "核心盈利方式（50-100字）",
  "gtm_strategy": "GTM与增长策略（50-100字）",
  "cold_start": "冷启动策略（50-100字）",
  "customer_segment": "客户群体描述（50-100字）",
  "growth_flywheel": "增长飞轮描述（100字内，[A]→[B]→[C]→强化[A]格式）",

  "revenue_metrics": "财务规模类量化指标（一句话）。包括但不限于：ARR（年度经常性收入）、MRR（月度经常性收入）、GMV、总营收、ACV（年度合同价值）。格式：「ARR $12M（2024Q4，来源：TechCrunch）」。严禁估算，找不到公开数据填「暂缺」。",

  "growth_metrics": "用户/增长规模类量化指标（一句话）。包括但不限于：MAU（月活）、DAU（日活）、注册用户数、付费用户数、企业客户数、NPS 值、交易量。格式：「MAU 500万（2024Q3，官方公告）」。找不到填「暂缺」。",

  "regional_markets": "主要市场地区及比例（100字内）。如「美国占 60%、欧洲 25%、亚太 15%（2024年报）」，或「主要服务北美企业客户，已进入欧洲市场（官网）」。找不到填「暂缺」。",

  "tam": "TAM 总可服务市场规模。格式：「TAM $180B（2025，来源：Grand View Research，口径：全球游戏市场）」；没有公开来源填「暂缺」，严禁估算。",
  "sam": "SAM 可服务市场规模。格式同 TAM，必须说明地域/细分市场/年份/来源；没有公开来源填「暂缺」。",
  "som": "SOM 可获得市场规模。格式同 TAM，必须说明可获得口径；没有公开来源填「暂缺」。",
  "market_cagr": "目标市场复合增长率。格式：「CAGR 18%（2024-2030，来源：...）」；没有公开来源填「暂缺」。",
  "arr": "ARR 年度经常性收入。格式：「ARR $12M（2024Q4，来源：TechCrunch）」；没有公开来源填「暂缺」。",
  "mrr": "MRR 月度经常性收入。格式：「MRR $1M（2024Q4，来源：...）」；没有公开来源填「暂缺」。",
  "registered_users": "注册用户数。格式：「注册用户 4万（2025-09，来源：...）」；没有公开来源填「暂缺」。",
  "active_users": "活跃用户数（DAU/MAU/WAU）。格式：「MAU 50万（2025Q1，来源：...）」；没有公开来源填「暂缺」。",
  "paying_users": "付费用户数或付费客户数。格式：「付费客户 1,200 家（2025Q1，来源：...）」；没有公开来源填「暂缺」。",
  "retention_rate": "留存率（D1/D7/D30/月留存等）。必须说明周期和口径；没有公开来源填「暂缺」。",
  "churn_rate": "流失率（月流失/年流失）。必须说明周期和口径；没有公开来源填「暂缺」。",
  "cac": "CAC 获客成本。必须说明币种、周期和客户口径；没有公开来源填「暂缺」。",
  "ltv": "LTV 生命周期价值。必须说明币种和口径；没有公开来源填「暂缺」。",
  "ltv_cac_ratio": "LTV/CAC 比率。格式：「LTV/CAC 3.2x（2024，来源：...）」；没有公开来源填「暂缺」。",
  "gross_margin": "毛利率。格式：「毛利率 78%（2024，来源：...）」；没有公开来源填「暂缺」。",
  "burn_rate": "Burn rate 月消耗或年度消耗。必须说明周期、币种和来源；没有公开来源填「暂缺」。",
  "runway_months": "Runway 剩余现金可支撑月数。必须说明时间点和来源；没有公开来源填「暂缺」。",
  "market_size_source_note": "市场规模来源说明。记录 TAM/SAM/SOM 的来源、时间、口径差异和可信度；没有公开来源填「暂缺」。",

  "competitors_summary": "Top3 竞争对手的一句话对比摘要（150字内）。从 competitors 数组中取排名前3，按格式输出：「【竞品A】核心产品 X，关键数据 Y；【竞品B】核心产品 X，关键数据 Y；【竞品C】...」。若 competitors 不足3个则据实填写。",

  "ai_model_dependency": "严格枚举：proprietary_model | fine_tuned | multi_model | openai_only | no_ai_core",
  "workflow_integration_level": "严格枚举：system_of_record | workflow_embedded | plugin_addon | standalone_tool",
  "data_flywheel": "严格枚举：yes | partial | no",
  "proprietary_data_asset": "严格枚举：yes_core | yes_supplementary | no",
  "incumbent_direct_competitor": "严格枚举：openai | google | multiple | microsoft | other | none",
  "customer_segment_type": "严格枚举：b2b_enterprise | developer_api | b2b2c | b2b_smb | b2c。注意：这是公式字段，不替代上面的 customer_segment 文案字段。",
  "funding_stage": "严格枚举：series_c_plus | series_b | series_a | seed | pre_seed。根据 funding_info 判断。",
  "pricing_model": "严格枚举：outcome_based | enterprise_contract | subscription | usage_based | freemium | free",
  "inference_cost_exposure": "严格枚举：none | low | medium | high",
  "stack_layer": "严格枚举：infrastructure | foundation_model | middleware | vertical_app | distribution",

  "moat": "竞争壁垒（100-200字）。仅写最强2-3个壁垒，每项用- 起头。不要在这段写生态位分析。",
  "ecosystem_niche": "生态位分析（100-200字）。产业链位置、价值网络、生态位宽度与重叠度、错位竞争策略、生态演化趋势。每项用- 起头。",
  "ecosystem_positioning": "生态位一句话。只写公司处于哪一层、上下游是谁、核心价值截留位置。保留 ecosystem_niche 全文，不用此字段替代母字段。",
  "differentiation_strategy": "错位竞争策略。说明如何避开或重构与传统玩家/巨头/同类创业公司的竞争。保留 ecosystem_niche 全文，不用此字段替代母字段。",
  "cost_advantage": "成本优势。说明 AI、自动化、供应链或组织效率如何降低边际成本。保留 moat 全文，不用此字段替代母字段。",
  "technical_barrier": "技术壁垒。说明自研技术、数据、模型、系统集成或工程复杂度。保留 moat 全文，不用此字段替代母字段。",
  "switching_cost": "迁移成本。说明客户/用户/生态资产为何难以迁移。保留 moat 全文，不用此字段替代母字段。",
  "ideal_customer_profile": "理想客户画像。一句话概括最核心客户是谁、为什么买/用、付费或留存动机。",
  "customer_segment_primary": "主要客户细分。只写第一类客户，包含年龄/行业/角色/预算/痛点等可得信息。",
  "customer_segment_secondary": "次要客户细分。只写第二类客户；如果没有明确第二类，填「暂缺」。",
  "growth_strategy": "增长策略。只写获客、激活、留存或复购的增长动作，保留 gtm_strategy 全文。",
  "gtm_motion": "GTM 打法。只写销售/渠道/社区/PLG/生态合作等进入市场路径，保留 gtm_strategy 全文。",
  "competitors": [
    {
      "name": "竞品公司名",
      "product": "核心产品名",
      "data": "关键运营数据（含来源注明）",
      "url": "竞品官网 URL",
      "rank": 1
    }
  ],

  // ================================================================
  // V3 专用字段（公司简介 Page 2）
  // ================================================================
  "market_track": "赛道分类（如 AI代码助手、AI图像生成、AI视频生成。30字内）。找不到填「暂缺」。",
  "market_subtrack": "细分赛道（如 企业级AI编码平台、消费级图像编辑。50字内）。细分赛道是赛道的子类，不必填赛道名已包含的词汇。找不到填「暂缺」。",
  "market_landscape_summary": "赛道市场格局描述（200字内，含Top玩家名）。找不到填「暂缺」。",
  "market_landscape_top_players": [
    {"name": "玩家名", "description": "一句话描述", "market_position": "市场定位"}
  ],
  "market_size_value": "赛道市场规模数值（亿美元，如 45.2）。必须是数字或 null，不要填文字。找不到填 null。",
  "market_size_currency": "USD/CNY/EUR",
  "market_size_year": 2024,
  "tam_value": "TAM数值（如 180.5）。如果前文 tam 字段为文本格式「暂缺」则此处填 null。",
  "tam_currency": "USD/CNY/EUR。tam_value 为 null 时填 null。",
  "tam_year": "TAM口径年份。tam_value 为 null 时填 null。",
  "founded_date": "成立年月（YYYY-MM 或 YYYY）。找不到填「暂缺」。",
  "core_business": "主营业务一句话（150字内）。区别于 company_def 的公司定性，侧重业务实质描述。找不到填「暂缺」。",
  "core_competency": "核心竞争优势（200字内）。找不到填「暂缺」。",
  "funding_rounds": [
    {"round": "A轮", "date": "YYYY-MM", "amount_usd": "金额（美元，如 12M）", "valuation_usd": "估值（美元，如 80M，未知填 null）", "lead_investor": "领投方", "investors": "跟投方逗号分隔"}
  ],
  "company_achievements": "公司成就里程碑列表（每项一行，最多5项）。与 company_achievement 字段互补：后者是摘要文案，此处是结构化列表。找不到填「暂缺」。",
  "industry_positioning": "行业定位语（50字内）。找不到填「暂缺」。",

  // ================================================================
  // V3 专用字段（主产品 Page 3）
  // ================================================================
  "product_pain_points": [
    {"pain_point": "痛点描述", "severity": "high | medium | low"}
  ],
  "product_core_features": [
    {"feature_name": "功能名称", "description": "功能描述"}
  ],
  "product_usage_playbook": "核心用法/典型工作流描述（200字内）。找不到填「暂缺」。",
  "product_tech_stack": "技术栈详情（200字内）。替代旧的 tech_stack 字段，更详细地描述核心技术选型、架构决策、自研与第三方比例。找不到填「暂缺」。",
  "regional_market_focus": [
    {"region": "地区名（如 北美/欧洲/亚太）", "status": "主力市场 | 拓展中 | 计划进入", "note": "备注"}
  ],
  "mau": "月活跃用户数。格式：「500万」。无公开披露填 null 或不输出此键。",
  "mau_as_of": "MAU统计截止日期（YYYY-MM）。mau 为 null 时填 null。",
  "retention_definition": "留存率口径说明（如「次日留存」「月留存」）。无公开披露填「暂缺」。",
  "pricing_summary": "定价摘要（150字内）。找不到填「暂缺」。",
  "pricing_tiers": [
    {"tier_name": "套餐名（如 Free/Pro/Enterprise）", "price": "价格（如 $0 / $29/月 / 按量计费）", "billing_period": "monthly | annual | usage_based | one_time", "features": "核心功能逗号分隔"}
  ],

  // ================================================================
  // V3 专用字段（用户群体 Page 5）
  // ================================================================
  "customer_names": [
    {"name": "客户名称", "industry": "所属行业", "logo_url": "Logo URL（找不到填空字符串）"}
  ],
  "customer_selection_reasons": "客户选择理由（200字内，绑定具体案例）。找不到填「暂缺」。",
  "customer_choice_evidence": [
    {"customer_name": "客户名称", "evidence_type": "case_study | testimonial | press_release | social_proof", "evidence_summary": "证据摘要（100字内）"}
  ],

  // ================================================================
  // V3 专用字段（公司能力分析 Page 6）
  // ================================================================
  "pricing_strategy": "定价策略分析（200字内）。结合 pricing_model 枚举展开为可读策略说明。找不到填「暂缺」。",
  "ltv_cac_is_benchmark": true,
  "ltv_cac_benchmark_source": "LTV/CAC benchmark 来源。ltv_cac_is_benchmark 为 true 时必填（如「SaaS Capital 2024 benchmark」），false 时填空字符串。",

  // ================================================================
  // V3 专用字段（增长与GTM Page 7）
  // ================================================================
  "acquisition_channels": [
    {"channel": "渠道名（如 内容营销/PLG/社区/付费广告）", "effectiveness": "high | medium | low", "note": "效果说明（100字内）"}
  ],

  // ================================================================
  // V3 专用字段（竞争态势 Page 8）
  // ================================================================
  "competitors_top3": [
    {"name": "竞品公司名", "summary": "一句话描述", "overlap": "与目标公司重叠点", "difference": "与目标公司差异点", "url": "竞品官网URL"}
  ],
  "competitive_position": "被研公司在竞争中的位置（200字内）。找不到填「暂缺」。",
  "differentiated_opportunity": "错位竞争机会（200字内）。说明如何避开或重构与传统玩家/巨头/同类创业公司的竞争，替代旧的 differentiation_strategy 字段。找不到填「暂缺」。",
  "competitive_advantages": "竞争优势摘要（200字内）。找不到填「暂缺」。",

  // 以下字段归属套卡1（v1·经典8张），v2套卡不渲染但仍提取存储
  "timeline_events": [
    {"date": "YYYY-MM", "event": "事件描述", "impact": "战略影响"}
  ],
  "other_products": [
    {"name": "产品名", "def": "一句话定义", "highlight": "亮点功能", "url": "产品独立页面URL，找不到填空字符串"}
  ],
  "hook_paragraph_1": "钩子段落1（约200字，高知识密度，有信息钩子，适合公众号/推文开头）",
  "hook_paragraph_2": "钩子段落2（约200字，不同切入点或延伸讨论）",
  "hook_paragraph_3": "钩子段落3（约200字，从商业/投资人视角切入）",
  "market_opportunity": "赛道客观条件变化带来的契机（100字内）",

  "data_confidence": "整体置信度（高/中/低）"
}
```

## 字段来源映射
- 公司类型/地点/定义 → Layer 0
- 创始人/团队/融资 → Layer 0
- 公司成就 → Layer 0（融资信息、媒体引用）+ Layer 1（里程碑事件）
- 产品信息/成就 → Layer 0 + Layer 1
- 技术栈 → Layer 0（技术描述）+ stack_layer/ai_model_dependency 枚举
- office_photo_hints → Layer 0（公司官网/新闻/LinkedIn URL）
- 商业模式/GTM/冷启动 → Layer 2
- 营收指标/增长指标 → Layer 1（新闻报道）+ Layer 0（官网公开数据）
- TAM/SAM/SOM、CAGR、ARR/MRR、用户、留存、CAC/LTV、毛利、Burn/Runway → Layer 1（新闻/市场报告）+ Tavily 补采证据池 + 官网公开数据。必须保留来源、时间、口径；不允许根据融资额、团队规模或市场常识倒推。
- 分地区市场 → Layer 1（市场报告引用）+ Layer 0（官网地区信息）
- 竞争/生态位评分枚举字段 → Layer 0 + Layer 1 + Layer 2。信息不足时选择最接近枚举，不输出自由文本。
- 竞争壁垒/赛道/机遇 → Layer 2
- 竞品信息 → Layer 1 horizontal + Layer 2
- 竞对Top3摘要 → Layer 1 horizontal + competitors 数组合成
- 发展沿袭/时间线 → Layer 1 longitudinal
- 钩子段落 → 综合所有层，{{VERSION}}版风格

## {{VERSION}}版特殊要求
{{VERSION_SPECIFIC}}

## 必填字段提醒
以下字段常被遗漏，请确保从 Layer 0 创始人信息中逐项提取，不得以"暂缺"替代有数据可查的情况：
- `founder_edu`：创始人学历背景（学校、专业、学位），区别于 `founder_bg`（工作经历）
- `founder_achievement`：创始人过往成就（获奖、创业经历、前公司重要成果），与教育和工作经历分属不同维度

输出纯 JSON，不要 Markdown 代码块包裹。
