"""CardValueBuilder — 从实体表 + research_fields 构建卡片渲染所需的值映射。

SPEC: 卡片渲染不再通过 card_index 硬编码分支，改为字段驱动的模板渲染。
CardValueBuilder 是字段层（entity tables / research_fields）与模板层之间的桥梁。

Usage:
    builder = CardValueBuilder(db_path)
    values = builder.build_card_values(company_key, card_set_key="v3", page=2)
    # 返回 {field_key: value_str, ...} 可直接注入模板
"""

from __future__ import annotations
from typing import Optional

from . import entity_repo as repo


# ── v3 套卡 8 页字段映射 ──
# 每页需要哪些字段，以及从哪个来源取（entity table → column 或 research_field）

_V3_PAGE_FIELDS: dict[int, list[dict]] = {
    # 第1页：封面
    1: [
        {"field": "company_name", "source": "companies", "column": "name"},
        {"field": "company_type", "source": "sectors", "column": "sector_name"},
    ],
    # 第2页：公司简介
    2: [
        {"field": "market_landscape_summary", "source": "sectors", "column": "market_landscape"},
        {"field": "market_size_value", "source": "sectors", "column": "market_size_summary"},
        {"field": "market_cagr", "source": "sectors", "column": "market_cagr_summary"},
        {"field": "tam", "source": "sectors", "column": "tam_summary"},
        {"field": "location", "source": "companies", "column": "hq_city"},
        {"field": "founded_date", "source": "companies", "column": "founded_date"},
        {"field": "core_business", "source": "companies", "column": "main_business"},
        {"field": "core_competency", "source": "companies", "column": "core_advantage"},
        {"field": "funding_info", "source": "field", "column": "funding_info"},
        {"field": "industry_positioning", "source": "companies", "column": "industry_positioning"},
    ],
    # 第3页：主产品
    3: [
        {"field": "main_product_name", "source": "products", "column": "name"},
        {"field": "product_pain_points", "source": "products", "column": "target_pain_points"},
        {"field": "product_core_features", "source": "products", "column": "core_features"},
        {"field": "product_usage_playbook", "source": "products", "column": "usage_play"},
        {"field": "product_tech_stack", "source": "products", "column": "tech_stack"},
        {"field": "regional_market_focus", "source": "products", "column": "regional_markets"},
        {"field": "mau", "source": "metrics", "column": "metric_value", "filter": "mau"},
        {"field": "retention_rate", "source": "metrics", "column": "metric_value", "filter": "retention_rate"},
        {"field": "pricing_summary", "source": "products", "column": "pricing_detail"},
    ],
    # 第4页：创始团队
    4: [
        {"field": "founder_name", "source": "founders", "column": "name"},
        {"field": "founder_edu", "source": "founders", "column": "education"},
        {"field": "founder_bg", "source": "founders", "column": "career_background"},
        {"field": "founder_achievement", "source": "founders", "column": "founder_achievement"},
    ],
    # 第5页：用户群体
    5: [
        {"field": "ideal_customer_profile", "source": "field", "column": "ideal_customer_profile"},
        {"field": "customer_names", "source": "customers", "column": "customer_name"},
        {"field": "customer_selection_reasons", "source": "customers", "column": "choice_reason"},
    ],
    # 第6页：公司能力分析
    6: [
        {"field": "ecosystem_niche", "source": "company_analysis", "column": "ecosystem_niche"},
        {"field": "revenue_model", "source": "company_analysis", "column": "monetization_strategy"},
        {"field": "pricing_strategy", "source": "company_analysis", "column": "pricing_strategy"},
        {"field": "ltv", "source": "metrics", "column": "metric_value", "filter": "ltv"},
        {"field": "cac", "source": "metrics", "column": "metric_value", "filter": "cac"},
        {"field": "ltv_cac_ratio", "source": "metrics", "column": "metric_value", "filter": "ltv_cac_ratio"},
    ],
    # 第7页：增长与GTM
    7: [
        {"field": "growth_strategy", "source": "company_analysis", "column": "growth_strategy"},
        {"field": "gtm_strategy", "source": "company_analysis", "column": "gtm_motion"},
        {"field": "cold_start", "source": "company_analysis", "column": "cold_start"},
        {"field": "growth_flywheel", "source": "company_analysis", "column": "growth_flywheel"},
        {"field": "acquisition_channels", "source": "field", "column": "acquisition_channels"},
    ],
    # 第8页：竞争态势
    8: [
        {"field": "competitors_top3", "source": "competitors", "column": "company_summary"},
        {"field": "competitive_position", "source": "company_analysis", "column": "competitive_position"},
        {"field": "differentiated_opportunity", "source": "company_analysis", "column": "differentiation_opportunity"},
        {"field": "competitive_advantages", "source": "company_analysis", "column": "competitive_advantage"},
    ],
}


class CardValueBuilder:
    """从实体表 + research_fields 构建卡片渲染值映射。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        # 缓存：避免重复查询同一实体
        self._cache: dict[str, dict | list[dict] | None] = {}

    def _cached(self, cache_key: str, loader):
        """带缓存的加载。"""
        if cache_key not in self._cache:
            self._cache[cache_key] = loader()
        return self._cache[cache_key]

    def _load_company(self, company_key: str) -> dict | None:
        return repo.get_company(self.db_path, company_key)

    def _load_primary_product(self, company_key: str) -> dict | None:
        return repo.get_primary_product(self.db_path, company_key)

    def _load_metrics(self, company_key: str) -> list[dict]:
        return repo.get_metrics(self.db_path, company_key)

    def _load_sector(self, company_key: str) -> dict | None:
        return repo.get_sector(self.db_path, company_key)

    def _load_founders(self, company_key: str) -> list[dict]:
        return repo.get_founders(self.db_path, company_key)

    def _load_customers(self, company_key: str) -> list[dict]:
        return repo.get_customers(self.db_path, company_key)

    def _load_competitors(self, company_key: str) -> list[dict]:
        return repo.get_competitors(self.db_path, company_key)

    def _load_analysis(self, company_key: str) -> dict | None:
        return repo.get_analysis(self.db_path, company_key)

    # ── 主入口 ──────────────────────────────────────────────────

    def build_card_values(
        self,
        company_key: str,
        card_set_key: str = "v3",
        page: int = 0,
        field_map: dict | None = None,
    ) -> dict[str, str]:
        """构建单页卡片渲染所需的值映射。

        Args:
            company_key: 公司标识
            card_set_key: 套卡版本（v1/v2/v3）
            page: 页码（1-8 for v3），0 表示返回所有页字段
            field_map: 可选，research_fields 的 {field_key: value} 兜底映射

        Returns:
            {field_key: value_str} 扁平键值对
        """
        page_fields = _V3_PAGE_FIELDS if card_set_key == "v3" else {}
        result: dict[str, str] = {}

        if page > 0 and page in page_fields:
            # 单页查询
            for mapping in page_fields[page]:
                val = self._resolve_value(mapping, company_key, field_map or {})
                if val:
                    result[mapping["field"]] = val
        else:
            # 全量：遍历所有页
            for pg, mappings in page_fields.items():
                for mapping in mappings:
                    fk = mapping["field"]
                    if fk not in result:
                        val = self._resolve_value(mapping, company_key, field_map or {})
                        if val:
                            result[fk] = val

        # 兜底：field_map 中的值（未被 entity table 覆盖的）
        if field_map:
            for fk, fv in field_map.items():
                if fk not in result and fv and str(fv).strip():
                    result[fk] = str(fv)

        return result

    # ── 内部：值解析 ────────────────────────────────────────────

    def _resolve_value(
        self,
        mapping: dict,
        company_key: str,
        field_map: dict,
    ) -> str | None:
        """按 mapping 定义从对应数据源解析字段值。

        mapping: {"field": str, "source": str, "column": str, "filter": Optional[str]}
        """
        source = mapping.get("source", "field")
        column = mapping.get("column", "")
        filter_key = mapping.get("filter", "")
        field_key = mapping["field"]

        if source == "field":
            # 从 research_fields / field_map 直接取
            return field_map.get(field_key, field_map.get(column, None))

        # 从实体表取
        entity_data = self._load_entity(source, company_key)

        if source == "metrics":
            # metrics 是列表，需要按 filter (metric_key) 匹配
            if isinstance(entity_data, list) and filter_key:
                for m in entity_data:
                    if m.get("metric_key") == filter_key:
                        val = m.get(column)
                        return str(val) if val is not None else None
            return None

        if isinstance(entity_data, dict):
            val = entity_data.get(column)
            return str(val) if val else None

        if isinstance(entity_data, list) and entity_data:
            # 多行实体（founders/customers/competitors）：取第一个匹配的值
            first = entity_data[0]
            if isinstance(first, dict):
                val = first.get(column)
                return str(val) if val else None

        return None

    def _load_entity(self, source: str, company_key: str):
        """加载指定实体表的数据（带缓存）。"""
        loaders = {
            "companies": lambda: self._load_company(company_key),
            "products": lambda: self._load_primary_product(company_key),
            "metrics": lambda: self._load_metrics(company_key),
            "sectors": lambda: self._load_sector(company_key),
            "founders": lambda: self._load_founders(company_key),
            "customers": lambda: self._load_customers(company_key),
            "competitors": lambda: self._load_competitors(company_key),
            "company_analysis": lambda: self._load_analysis(company_key),
        }
        loader = loaders.get(source)
        if not loader:
            return None
        return self._cached(f"entity:{source}:{company_key}", loader)

    def clear_cache(self):
        """清除内部缓存。"""
        self._cache.clear()
