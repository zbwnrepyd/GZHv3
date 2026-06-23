from __future__ import annotations

import json

import db as database


CARD_TITLES = {
    1: "首页",
    2: "公司介绍",
    3: "发展沿袭",
    4: "主产品",
    5: "其他产品",
    6: "商业模式",
    7: "竞争格局",
    8: "总结",
}

# v2 卡片标题
CARD_TITLES_V2 = {
    1: "封面",
    2: "公司概览",
    3: "产品与定位",
    4: "创始人与团队",
    5: "核心客户",
    6: "GTM与增长",
    7: "竞争格局",
}

# v3 卡片标题
CARD_TITLES_V3 = {
    1: "封面",
    2: "公司简介",
    3: "主产品",
    4: "创始团队",
    5: "用户群体",
    6: "公司能力分析",
    7: "增长与GTM",
    8: "竞争态势",
}


def _missing(value) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip() == "暂缺"


def _value(record: dict, key: str) -> str:
    value = record.get(key)
    return "暂缺" if _missing(value) else str(value)


def _json_array(value) -> list:
    if _missing(value):
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _format_timeline(value) -> str:
    events = _json_array(value)
    if not events:
        return f"**发展沿袭时间线**：{value if not _missing(value) else '暂缺'}"
    lines = []
    for event in events:
        date = event.get("date") or event.get("time") or event.get("year") or "暂缺"
        title = event.get("event") or event.get("title") or event.get("description") or "暂缺"
        impact = event.get("impact") or event.get("result") or ""
        suffix = f" — *{impact}*" if impact else ""
        lines.append(f"- **{date}** {title}{suffix}")
    return "\n".join(lines)


def _format_other_products(value) -> str:
    products = _json_array(value)
    if not products:
        return "**其他产品**：暂缺" if _missing(value) else str(value)
    return "\n".join(
        f"- **{p.get('name', '暂缺')}**：{p.get('def') or p.get('description') or '暂缺'}"
        f"（{p.get('highlight') or p.get('feature') or '暂缺'}）"
        for p in products
    )


def _format_competitors(value) -> str:
    competitors = _json_array(value)
    if not competitors:
        return f"**竞争格局**：{value if not _missing(value) else '暂缺'}"
    lines = []
    for idx, competitor in enumerate(competitors, start=1):
        name = competitor.get("name") or competitor.get("company") or f"竞品{idx}"
        product = competitor.get("product") or competitor.get("description") or "暂缺"
        data = competitor.get("data") or competitor.get("metric") or competitor.get("evidence") or "暂缺"
        lines.append(f"**TOP{idx}**：{name} — {product}（{data}）")
    return "\n".join(lines)


def build_card_markdown(db_path: str, company_name: str, card_index: int, version: str, card_set_key: str = "v1") -> str:
    """Build one card's editable Markdown from the latest research record. Dispatches by card_set_key."""
    if card_set_key == "v3":
        return _build_card_markdown_v3(db_path, company_name, card_index, version)
    # v1 / v2 共用原逻辑（v2 7张卡复用 v1 的 card_index 映射）
    return _build_card_markdown_v1(db_path, company_name, card_index, version)


def _build_card_markdown_v1(db_path: str, company_name: str, card_index: int, version: str) -> str:
    """原 v1/v2 Markdown 构建逻辑（hardcoded card_index 分支）"""
    record = database.get_research(db_path, company_name, version)
    if not record:
        return ""

    title = CARD_TITLES.get(card_index, f"卡片{card_index}")
    lines = [f"## 卡片{card_index}：{title}", ""]

    if card_index == 1:
        lines += [f"# {company_name}", "", f"**{_value(record, 'company_type')}**"]
    elif card_index == 2:
        lines += [
            f"**位置**：{_value(record, 'location')}",
            "",
            _value(record, "company_def"),
            "",
            f"**创始人**：{_value(record, 'founder_name')}",
            f"**学历背景**：{_value(record, 'founder_edu')}",
            f"**工作背景**：{_value(record, 'founder_bg')}",
            f"**过往成就**：{_value(record, 'founder_achievement')}",
            f"**团队规模**：{_value(record, 'team_size')}",
            f"**团队亮点**：{_value(record, 'team_highlight')}",
            f"**融资**：{_value(record, 'funding_info')}",
            f"**客户群体**：{_value(record, 'customer_segment')}",
            f"**官网**：{_value(record, 'website_url')}",
        ]
    elif card_index == 3:
        lines.append(_format_timeline(record.get("timeline_events")))
    elif card_index == 4:
        lines += [
            f"## {_value(record, 'main_product_name')}",
            "",
            _value(record, "main_product_def"),
            "",
            f"**亮点**：{_value(record, 'main_product_highlight')}",
            f"**成就**：{_value(record, 'main_product_achievement')}",
        ]
        image = record.get("main_product_img_src")
        if not _missing(image):
            lines += ["", f"![产品图片]({image})"]
    elif card_index == 5:
        lines.append(_format_other_products(record.get("other_products")))
    elif card_index == 6:
        lines += [
            f"**盈利**：{_value(record, 'revenue_model')}",
            f"**冷启动**：{_value(record, 'cold_start')}",
            f"**GTM**：{_value(record, 'gtm_strategy')}",
            f"**飞轮**：{_value(record, 'growth_flywheel')}",
        ]
    elif card_index == 7:
        moat_text = _value(record, 'moat')
        # 拆分壁垒和生态位（若 moat 字段中包含"生态位分析"标记则拆分，否则生态位留空）
        moat_part = moat_text
        niche_part = record.get('ecosystem_niche') or ''
        if not niche_part:
            for sep in ['- 生态位分析', '●生态位分析', '生态位分析', '- 生态位', '●生态位', '\n\n生态位']:
                idx = moat_text.find(sep)
                if idx > 0:
                    moat_part = moat_text[:idx].strip()
                    niche_part = moat_text[idx:].strip()
                    break
        lines += [
            f"**壁垒**：{moat_part if moat_part and moat_part != '暂缺' else '暂缺'}",
        ]
        if niche_part and niche_part != '暂缺':
            lines.append(f"**生态位**：{niche_part}")
        lines.append(_format_competitors(record.get("competitors")))
    elif card_index == 8:
        lines += [
            f"**机遇**：{_value(record, 'market_opportunity')}",
        ]

    return "\n".join(lines).rstrip() + "\n"


# ── v3 字段驱动 Markdown 构建 ──────────────────────────

# v3 每页字段定义（与 default_card_configs v3 config_json 一致）
_V3_PAGE_FIELDS: dict[int, list[str]] = {
    1: ["company_name", "company_type"],
    2: ["market_track", "market_subtrack",
        "market_landscape_summary", "market_landscape_top_players",
        "market_size_value", "market_size_currency",
        "market_size_year", "market_cagr", "tam_value", "tam_currency",
        "tam_year", "location", "founded_date", "core_business",
        "core_competency", "funding_info", "funding_rounds", "company_achievements",
        "industry_positioning"],
    3: ["main_product_name", "product_pain_points", "product_core_features",
        "product_usage_playbook", "product_tech_stack", "regional_market_focus",
        "mau", "mau_as_of", "retention_definition", "retention_rate",
        "pricing_summary", "pricing_tiers"],
    4: ["founder_name", "founder_edu", "founder_bg", "founder_achievement",
        "team_size", "team_highlight"],
    5: ["ideal_customer_profile", "customer_segment_primary",
        "customer_segment_secondary", "customer_names",
        "customer_selection_reasons", "customer_choice_evidence"],
    6: ["ecosystem_niche", "revenue_model", "pricing_strategy",
        "ltv", "cac", "ltv_cac_ratio", "ltv_cac_is_benchmark",
        "ltv_cac_benchmark_source"],
    7: ["growth_strategy", "gtm_motion", "cold_start", "growth_flywheel",
        "acquisition_channels"],
    8: ["competitors_top3", "competitive_position",
        "differentiated_opportunity", "competitive_advantages"],
}

# v3 字段中文标签（用于 Markdown 渲染）
_V3_FIELD_LABELS: dict[str, str] = {
    "company_name": "公司名称",
    "company_type": "公司分类",
    "market_track": "赛道",
    "market_subtrack": "细分赛道",
    "market_landscape_summary": "赛道市场格局",
    "market_landscape_top_players": "Top 玩家",
    "market_size_value": "赛道市场规模",
    "market_size_currency": "币种",
    "market_size_year": "口径年份",
    "market_cagr": "年复合增长率",
    "tam_value": "TAM",
    "tam_currency": "TAM 币种",
    "tam_year": "TAM 口径年份",
    "location": "地理位置",
    "founded_date": "成立时间",
    "core_business": "主营业务",
    "core_competency": "核心竞争优势",
    "funding_info": "融资情况",
    "funding_rounds": "融资轮次",
    "company_achievements": "公司成就",
    "industry_positioning": "行业定位",
    "main_product_name": "主产品名称",
    "product_pain_points": "针对痛点",
    "product_core_features": "核心功能",
    "product_usage_playbook": "核心用法",
    "product_tech_stack": "技术栈",
    "regional_market_focus": "地区市场",
    "mau": "月活跃用户",
    "mau_as_of": "MAU 统计周期",
    "retention_definition": "留存率口径",
    "retention_rate": "留存率",
    "pricing_summary": "定价摘要",
    "pricing_tiers": "定价梯度",
    "founder_name": "创始人",
    "founder_edu": "学历背景",
    "founder_bg": "工作背景",
    "founder_achievement": "过往成就",
    "team_size": "团队规模",
    "team_highlight": "团队亮点",
    "ideal_customer_profile": "用户画像",
    "customer_segment_primary": "一级细分",
    "customer_segment_secondary": "二级细分",
    "customer_names": "具体客户",
    "customer_selection_reasons": "客户选择理由",
    "customer_choice_evidence": "选择证据",
    "ecosystem_niche": "生态位分析",
    "revenue_model": "变现能力",
    "pricing_strategy": "定价策略",
    "ltv": "LTV",
    "cac": "CAC",
    "ltv_cac_ratio": "LTV/CAC",
    "ltv_cac_is_benchmark": "LTV/CAC 为行业均值",
    "ltv_cac_benchmark_source": "Benchmark 来源",
    "growth_strategy": "增长策略",
    "gtm_motion": "GTM 动作",
    "cold_start": "冷启动",
    "growth_flywheel": "增长飞轮",
    "acquisition_channels": "获客渠道",
    "competitors_top3": "Top3 竞品",
    "competitive_position": "竞争位置",
    "differentiated_opportunity": "错位竞争机会",
    "competitive_advantages": "竞争优势",
}


def _format_json_field(value, field_key: str) -> str:
    """将 JSON 字段格式化为可读 Markdown。"""
    items = _json_array(value)
    if not items:
        return "暂缺"
    if isinstance(items, list) and len(items) > 0:
        if isinstance(items[0], dict):
            lines = []
            for item in items:
                name = item.get("name") or item.get("title") or ""
                detail = item.get("summary") or item.get("description") or item.get("detail") or ""
                if name and detail:
                    lines.append(f"- **{name}**：{detail}")
                elif name:
                    lines.append(f"- {name}")
                else:
                    lines.append(f"- {json.dumps(item, ensure_ascii=False)}")
            return "\n".join(lines)
        else:
            return "\n".join(f"- {item}" for item in items)
    return str(value)


def _build_card_markdown_v3(db_path: str, company_name: str, card_index: int, version: str) -> str:
    """v3 套卡 Markdown 构建：字段驱动，非 card_index 硬编码分支。"""
    record = database.get_research(db_path, company_name, version)
    if not record:
        return ""

    title = CARD_TITLES_V3.get(card_index, f"卡片{card_index}")
    lines = [f"## 卡片{card_index}：{title}", ""]

    field_keys = _V3_PAGE_FIELDS.get(card_index, [])
    if not field_keys:
        return "\n".join(lines).rstrip() + "\n"

    # 首页特殊：大标题 + 分类
    if card_index == 1:
        lines.append(f"# {company_name}")
        lines.append("")
        lines.append(f"**{_value(record, 'company_type')}**")
        return "\n".join(lines).rstrip() + "\n"

    for fk in field_keys:
        label = _V3_FIELD_LABELS.get(fk, fk)
        raw_value = record.get(fk)
        if _missing(raw_value):
            continue

        # JSON 字段：格式化渲染
        if fk in ("market_landscape_top_players", "product_pain_points",
                   "product_core_features", "regional_market_focus",
                   "pricing_tiers", "customer_names", "customer_choice_evidence",
                   "funding_rounds", "acquisition_channels", "competitors_top3"):
            formatted = _format_json_field(raw_value, fk)
            lines.append(f"**{label}**：")
            lines.append(formatted)
        elif fk in ("market_size_value", "market_size_currency", "market_size_year"):
            # 市场规模复合展示：数值 + 币种 + 年份
            val = _value(record, "market_size_value")
            cur = record.get("market_size_currency") or ""
            year = record.get("market_size_year") or ""
            suffix = f" {cur}" if cur else ""
            suffix += f"（{year}）" if year else ""
            if fk == "market_size_value":  # 只在第一个字段输出完整行
                lines.append(f"**赛道市场规模**：{val}{suffix}")
        elif fk == "market_size_currency" or fk == "market_size_year":
            continue  # 已在上方复合展示
        elif fk in ("tam_value",):
            val = _value(record, "tam_value")
            cur = record.get("tam_currency") or ""
            year = record.get("tam_year") or ""
            suffix = f" {cur}" if cur else ""
            suffix += f"（{year}）" if year else ""
            lines.append(f"**TAM**：{val}{suffix}")
        elif fk in ("tam_currency", "tam_year"):
            continue
        elif fk == "ltv_cac_is_benchmark":
            is_bm = record.get("ltv_cac_is_benchmark")
            if is_bm:
                src = record.get("ltv_cac_benchmark_source") or ""
                lines.append(f"**LTV/CAC**：行业均值（来源：{src}）" if src else "**LTV/CAC**：行业均值")
            else:
                ltv = _value(record, "ltv")
                cac = _value(record, "cac")
                ratio = _value(record, "ltv_cac_ratio")
                lines.append(f"**LTV**：{ltv}　**CAC**：{cac}　**LTV/CAC**：{ratio}")
        elif fk == "ltv_cac_benchmark_source":
            continue  # 已在上方展示
        else:
            lines.append(f"**{label}**：{_value(record, fk)}")

    return "\n".join(lines).rstrip() + "\n"
