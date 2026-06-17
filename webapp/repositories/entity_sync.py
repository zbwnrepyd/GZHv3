"""EntitySyncService — 将研究字段同步到 10 张规范化实体表。

SPEC Section 数据库层改造：
  研究完成后，research_fields 的值应写入实体表作为权威存储，
  不再仅依赖宽表 research。同步时写 audit log。

Usage:
    syncer = EntitySyncService(db_path)
    result = syncer.sync_from_fields(company_key, field_map, run_id)
    # field_map: {field_key: FieldResult} 来自 field_resolver
"""

from __future__ import annotations
from typing import Optional

from . import entity_repo as repo


class EntitySyncService:
    """将 research_fields 同步到实体表的主写入服务。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.sync_stats: dict[str, int] = {}  # entity_type -> rows written

    # ── 主入口 ──────────────────────────────────────────────────

    def sync_from_fields(
        self,
        company_key: str,
        field_map: dict,       # {field_key: FieldResult}
        run_id: str = "",
    ) -> dict:
        """从字段解析结果同步到所有实体表。

        Args:
            company_key: 公司标识
            field_map: {field_key: FieldResult} 来自 field_resolver.resolve_all()
            run_id: 关联的研究运行 ID

        Returns:
            {entity_type: rows_synced, "errors": [...], "total_rows": int}
        """
        self.sync_stats = {}
        errors: list[str] = []

        # 提取值 dict（仅取 confirmed/derived/proxy/industry_avg 状态的字段）
        values = self._extract_reliable_values(field_map)

        # 按实体表顺序同步
        try:
            self._sync_company(company_key, values, run_id)
        except Exception as e:
            errors.append(f"company: {e}")

        try:
            self._sync_product(company_key, values, run_id)
        except Exception as e:
            errors.append(f"product: {e}")

        try:
            self._sync_metrics(company_key, values, run_id)
        except Exception as e:
            errors.append(f"metrics: {e}")

        try:
            self._sync_sector(company_key, values, run_id)
        except Exception as e:
            errors.append(f"sector: {e}")

        try:
            self._sync_founder(company_key, values, run_id)
        except Exception as e:
            errors.append(f"founder: {e}")

        try:
            self._sync_funding(company_key, values, run_id)
        except Exception as e:
            errors.append(f"funding: {e}")

        try:
            self._sync_customers(company_key, values, run_id)
        except Exception as e:
            errors.append(f"customers: {e}")

        try:
            self._sync_competitors(company_key, values, run_id)
        except Exception as e:
            errors.append(f"competitors: {e}")

        try:
            self._sync_analysis(company_key, values, run_id)
        except Exception as e:
            errors.append(f"analysis: {e}")

        total = sum(self.sync_stats.values())
        return {
            "stats": dict(self.sync_stats),
            "errors": errors,
            "total_rows": total,
            "success": len(errors) == 0,
        }

    # ── 内部：值提取 ────────────────────────────────────────────

    @staticmethod
    def _extract_reliable_values(field_map: dict) -> dict[str, str | None]:
        """从 FieldResult map 中提取可靠值。

        仅取 confirmed/derived/proxy/industry_avg 状态的值；
        llm_extracted/manual_needed 等低信度状态不写入实体表。
        """
        reliable_statuses = {"confirmed", "derived", "proxy", "industry_avg"}
        result: dict[str, str | None] = {}
        for fk, fr in field_map.items():
            status = getattr(fr, "resolution_status", "")
            if status in reliable_statuses:
                val = getattr(fr, "value", None)
                if val is not None:
                    result[fk] = str(val)
        return result

    # ── 内部：各实体表同步 ──────────────────────────────────────

    def _sync_company(self, company_key: str, values: dict, run_id: str):
        """同步 companies 表。"""
        company_data = {
            "company_key": company_key,
            "name": values.get("company_name", company_key),
            "company_definition": values.get("core_business", ""),
            "founded_date": values.get("founded_date", ""),
            "hq_city": values.get("location", ""),
            "main_business": values.get("core_business", ""),
            "core_advantage": values.get("core_competency", ""),
            "industry_positioning": values.get("industry_positioning", ""),
            "data_confidence": "medium",
        }
        ok = repo.upsert_company(self.db_path, company_data)
        if ok:
            self.sync_stats["companies"] = 1
            # Audit: 记录核心字段
            for f in ("company_definition", "founded_date", "main_business", "core_advantage"):
                if values.get(f):
                    repo.audit_entity_write(
                        self.db_path, "companies", company_key, company_key,
                        "upsert", f, None, str(values.get(f)),
                        run_id=run_id, source="EntitySyncService"
                    )

    def _sync_product(self, company_key: str, values: dict, run_id: str):
        """同步 products 表（仅主产品）。"""
        product_name = values.get("main_product_name", "")
        if not product_name:
            return
        product_data = {
            "company_key": company_key,
            "name": product_name,
            "is_primary": True,
            "target_pain_points": values.get("product_pain_points", ""),
            "core_features": values.get("product_core_features", ""),
            "usage_play": values.get("product_usage_playbook", ""),
            "tech_stack": values.get("product_tech_stack", ""),
            "regional_markets": values.get("regional_market_focus", ""),
            "pricing_detail": values.get("pricing_summary", ""),
            "confidence": "medium",
        }
        ok = repo.upsert_product(self.db_path, product_data)
        if ok:
            self.sync_stats["products"] = self.sync_stats.get("products", 0) + 1
            for f in ("target_pain_points", "core_features", "tech_stack"):
                if values.get(f):
                    repo.audit_entity_write(
                        self.db_path, "products", product_name, company_key,
                        "upsert", f, None, str(values.get(f)),
                        run_id=run_id, source="EntitySyncService"
                    )

    def _sync_metrics(self, company_key: str, values: dict, run_id: str):
        """同步 metrics 表（MAU/留存/LTV/CAC 等运营指标）。"""
        metric_map = {
            "mau": ("mau", "count"),
            "retention_rate": ("retention_rate", "percent"),
            "ltv": ("ltv", "usd"),
            "cac": ("cac", "usd"),
            "ltv_cac_ratio": ("ltv_cac_ratio", "ratio"),
            "churn_rate": ("churn_rate", "percent"),
            "gross_margin": ("gross_margin", "percent"),
            "runway_months": ("runway_months", "months"),
        }
        count = 0
        for field_key, (metric_key, unit) in metric_map.items():
            val = values.get(field_key)
            if val is None:
                continue
            metric_data = {
                "company_key": company_key,
                "entity_type": "company",
                "metric_key": metric_key,
                "metric_value": val,
                "unit": unit,
                "status": "confirmed",
                "confidence": "medium",
            }
            if repo.upsert_metric(self.db_path, metric_data):
                count += 1
        if count:
            self.sync_stats["metrics"] = count

    def _sync_sector(self, company_key: str, values: dict, run_id: str):
        """同步 sectors 表。"""
        sector_data = {
            "company_key": company_key,
            "sector_name": values.get("company_type", ""),
            "market_landscape": values.get("market_landscape_summary", ""),
            "market_size_summary": values.get("market_size_value", ""),
            "market_cagr_summary": values.get("market_cagr", ""),
            "tam_summary": values.get("tam", ""),
            "confidence": "medium",
        }
        ok = repo.upsert_sector(self.db_path, sector_data)
        if ok:
            self.sync_stats["sectors"] = 1

    def _sync_founder(self, company_key: str, values: dict, run_id: str):
        """同步 founders 表。"""
        founder_name = values.get("founder_name", "")
        if not founder_name:
            return
        founder_data = {
            "company_key": company_key,
            "name": founder_name,
            "education": values.get("founder_edu", ""),
            "career_background": values.get("founder_bg", ""),
            "founder_achievement": values.get("founder_achievement", ""),
            "confidence": "medium",
        }
        ok = repo.upsert_founder(self.db_path, founder_data)
        if ok:
            self.sync_stats["founders"] = 1

    def _sync_funding(self, company_key: str, values: dict, run_id: str):
        """同步 funding_rounds 表。"""
        funding_info = values.get("funding_info", "")
        funding_rounds_str = values.get("funding_rounds", "")
        if not funding_info and not funding_rounds_str:
            return

        # 结构化 funding_rounds JSON
        import json
        rounds = []
        if funding_rounds_str:
            try:
                rounds = json.loads(funding_rounds_str)
            except (json.JSONDecodeError, TypeError):
                rounds = []

        count = 0
        for rd in (rounds if rounds else [{"summary": funding_info}]):
            round_data = {
                "company_key": company_key,
                "round_name": rd.get("round", rd.get("round_name", "")),
                "announced_date": rd.get("date", rd.get("announced_date", "")),
                "amount_usd": rd.get("amount", rd.get("amount_usd")),
                "lead_investor": rd.get("lead_investor", ""),
                "investors": str(rd.get("investors", "")),
                "confidence": "medium",
            }
            if repo.upsert_funding_round(self.db_path, round_data):
                count += 1
        if count:
            self.sync_stats["funding_rounds"] = count

    def _sync_customers(self, company_key: str, values: dict, run_id: str):
        """同步 customers 表。"""
        customer_names_str = values.get("customer_names", "")
        if not customer_names_str:
            return

        import json
        names = []
        try:
            names = json.loads(customer_names_str)
        except (json.JSONDecodeError, TypeError):
            names = [customer_names_str] if customer_names_str else []

        count = 0
        for name in (names if isinstance(names, list) else [str(names)]):
            customer_data = {
                "company_key": company_key,
                "customer_name": str(name),
                "choice_reason": values.get("customer_selection_reasons", ""),
                "confidence": "medium",
            }
            if repo.upsert_customer(self.db_path, customer_data):
                count += 1
        if count:
            self.sync_stats["customers"] = count

    def _sync_competitors(self, company_key: str, values: dict, run_id: str):
        """同步 competitors 表。"""
        competitors_str = values.get("competitors_top3", "")
        if not competitors_str:
            return

        import json
        comps = []
        try:
            comps = json.loads(competitors_str)
        except (json.JSONDecodeError, TypeError):
            comps = []

        count = 0
        for i, comp in enumerate(comps):
            if isinstance(comp, dict):
                name = comp.get("name", "")
                summary = comp.get("summary", str(comp))
            else:
                name = str(comp)
                summary = ""
            competitor_data = {
                "company_key": company_key,
                "competitor_name": name,
                "company_summary": summary,
                "rank": i + 1,
                "confidence": "medium",
            }
            if repo.upsert_competitor(self.db_path, competitor_data):
                count += 1
        if count:
            self.sync_stats["competitors"] = count

    def _sync_analysis(self, company_key: str, values: dict, run_id: str):
        """同步 company_analysis 表。"""
        analysis_data = {
            "company_key": company_key,
            "ecosystem_niche": values.get("ecosystem_niche", ""),
            "monetization_strategy": values.get("revenue_model", ""),
            "pricing_strategy": values.get("pricing_strategy", ""),
            "competitive_position": values.get("competitive_position", ""),
            "differentiation_opportunity": values.get("differentiated_opportunity", ""),
            "competitive_advantage": values.get("competitive_advantages", ""),
            "gtm_motion": values.get("gtm_strategy", values.get("gtm_motion", "")),
            "cold_start": values.get("cold_start", ""),
            "growth_strategy": values.get("growth_strategy", ""),
            "growth_flywheel": values.get("growth_flywheel", ""),
            "analysis_version": 3,
            "confidence": "medium",
        }
        ok = repo.upsert_analysis(self.db_path, analysis_data)
        if ok:
            self.sync_stats["company_analysis"] = 1
            for f in ("ecosystem_niche", "competitive_position", "differentiation_opportunity",
                       "gtm_motion", "growth_strategy", "growth_flywheel"):
                if values.get(f):
                    repo.audit_entity_write(
                        self.db_path, "company_analysis", company_key, company_key,
                        "upsert", f, None, str(values.get(f)),
                        run_id=run_id, source="EntitySyncService"
                    )
