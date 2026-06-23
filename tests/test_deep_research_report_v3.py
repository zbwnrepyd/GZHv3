import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import db
import markdown_builder
from repositories.field_repo import get_research_fields, insert_research_fields_batch
from services.field_service import split_research_to_fields


def _temp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    return path


def _exec_sql(conn: sqlite3.Connection, rel_path: str) -> None:
    with open(os.path.join(ROOT, rel_path), encoding="utf-8") as f:
        conn.executescript(f.read())


class DeepResearchReportV3Tests(unittest.TestCase):
    def tearDown(self):
        for attr in ("research_db", "final_db", "composition_db"):
            path = getattr(self, attr, None)
            if path and os.path.exists(path):
                os.remove(path)

    def _init_research_with_v3_migrations(self):
        self.research_db = _temp_db()
        with sqlite3.connect(self.research_db) as conn:
            _exec_sql(conn, "db/init_research_db.sql")
            _exec_sql(conn, "db/migrations/001_research_fields.sql")
            _exec_sql(conn, "db/migrations/009_evidence_items.sql")
            _exec_sql(conn, "db/migrations/010_field_resolution.sql")
            _exec_sql(conn, "db/migrations/011_v3_fields.sql")
        return self.research_db

    def _init_final_with_v3_migrations(self):
        self.final_db = _temp_db()
        with sqlite3.connect(self.final_db) as conn:
            _exec_sql(conn, "db/init_final_db.sql")
            _exec_sql(conn, "db/migrations/002_final_fields.sql")
            _exec_sql(conn, "db/migrations/012_v3_final_fields.sql")
        return self.final_db

    def test_v3_research_schema_matches_report_field_types_defaults_and_indexes(self):
        self._init_research_with_v3_migrations()
        with sqlite3.connect(self.research_db) as conn:
            conn.row_factory = sqlite3.Row
            research_cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(research)")}
            research_fields_cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(research_fields)")}
            evidence_cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(evidence_items)")}
            indexes = {r["name"] for r in conn.execute("PRAGMA index_list(research)")}
            rf_indexes = {r["name"] for r in conn.execute("PRAGMA index_list(research_fields)")}

        expected_research_types = {
            "company_type": "TEXT",
            "market_landscape_summary": "TEXT",
            "market_landscape_top_players": "TEXT",
            "market_size_value": "REAL",
            "market_size_currency": "TEXT",
            "market_size_year": "INTEGER",
            "market_cagr": "REAL",
            "tam_value": "REAL",
            "tam_currency": "TEXT",
            "tam_year": "INTEGER",
            "location": "TEXT",
            "founded_date": "TEXT",
            "core_business": "TEXT",
            "core_competency": "TEXT",
            "funding_rounds": "TEXT",
            "company_achievements": "TEXT",
            "industry_positioning": "TEXT",
            "main_product_name": "TEXT",
            "product_pain_points": "TEXT",
            "product_core_features": "TEXT",
            "product_usage_playbook": "TEXT",
            "product_tech_stack": "TEXT",
            "regional_market_focus": "TEXT",
            "mau": "INTEGER",
            "mau_as_of": "TEXT",
            "retention_definition": "TEXT",
            "retention_rate": "REAL",
            "pricing_summary": "TEXT",
            "pricing_tiers": "TEXT",
            "founder_name": "TEXT",
            "founder_edu": "TEXT",
            "founder_bg": "TEXT",
            "founder_achievement": "TEXT",
            "team_size": "TEXT",
            "team_highlight": "TEXT",
            "ideal_customer_profile": "TEXT",
            "customer_segment_primary": "TEXT",
            "customer_segment_secondary": "TEXT",
            "customer_names": "TEXT",
            "customer_selection_reasons": "TEXT",
            "customer_choice_evidence": "TEXT",
            "ecosystem_niche": "TEXT",
            "revenue_model": "TEXT",
            "pricing_strategy": "TEXT",
            "ltv": "REAL",
            "cac": "REAL",
            "ltv_cac_ratio": "REAL",
            "ltv_cac_is_benchmark": "INTEGER",
            "ltv_cac_benchmark_source": "TEXT",
            "growth_strategy": "TEXT",
            "gtm_motion": "TEXT",
            "cold_start": "TEXT",
            "growth_flywheel": "TEXT",
            "acquisition_channels": "TEXT",
            "competitors_top3": "TEXT",
            "competitive_position": "TEXT",
            "differentiated_opportunity": "TEXT",
            "competitive_advantages": "TEXT",
        }
        for field, expected_type in expected_research_types.items():
            self.assertIn(field, research_cols)
            self.assertEqual(research_cols[field]["type"].upper(), expected_type, field)
        self.assertEqual(research_cols["ltv_cac_is_benchmark"]["dflt_value"], "0")

        for field in (
            "value_type", "norm_value", "currency_code", "unit", "as_of_date",
            "evidence_ids", "source_urls", "page_no", "sort_order",
        ):
            self.assertIn(field, research_fields_cols)
        self.assertEqual(research_fields_cols["sort_order"]["dflt_value"], "0")
        for field in ("domain", "published_at", "lang", "content_hash", "robots_status", "source_family"):
            self.assertIn(field, evidence_cols)

        for index_name in (
            "idx_research_company_type", "idx_research_market_landscape_summary",
            "idx_research_market_size_value", "idx_research_market_size_year",
            "idx_research_market_cagr", "idx_research_tam_value",
            "idx_research_tam_year", "idx_research_location",
            "idx_research_founded_date", "idx_research_industry_positioning",
            "idx_research_main_product_name", "idx_research_product_tech_stack",
            "idx_research_regional_market_focus", "idx_research_mau",
            "idx_research_mau_as_of", "idx_research_retention_rate",
            "idx_research_ideal_customer_profile",
            "idx_research_customer_segment_primary",
            "idx_research_customer_segment_secondary", "idx_research_ltv",
            "idx_research_cac", "idx_research_ltv_cac_ratio",
            "idx_research_ltv_cac_is_benchmark",
        ):
            self.assertIn(index_name, indexes)
        self.assertIn("idx_research_fields_company_page", rf_indexes)

    def test_v3_final_fields_schema_defaults(self):
        self._init_final_with_v3_migrations()
        with sqlite3.connect(self.final_db) as conn:
            conn.row_factory = sqlite3.Row
            cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(final_fields)")}

        self.assertEqual(cols["card_set_key"]["type"].upper(), "TEXT")
        self.assertEqual(cols["card_set_key"]["dflt_value"], "'v1'")
        self.assertEqual(cols["page_no"]["type"].upper(), "INTEGER")
        self.assertEqual(cols["block_key"]["type"].upper(), "TEXT")
        self.assertEqual(cols["block_type"]["type"].upper(), "TEXT")
        self.assertEqual(cols["block_type"]["dflt_value"], "'field'")
        self.assertEqual(cols["render_json"]["type"].upper(), "TEXT")
        self.assertEqual(cols["export_targets"]["type"].upper(), "TEXT")
        self.assertEqual(cols["export_targets"]["dflt_value"], '\'["markdown","pdf","notion"]\'')

    def test_v3_default_card_configs_cover_report_pages(self):
        self.composition_db = _temp_db()
        with sqlite3.connect(self.composition_db) as conn:
            conn.row_factory = sqlite3.Row
            _exec_sql(conn, "db/init_composition_db.sql")
            cards = conn.execute(
                "SELECT card_index, card_title, config_json FROM default_card_configs "
                "WHERE set_key='v3' ORDER BY card_index"
            ).fetchall()
            registry = conn.execute(
                "SELECT display_name, card_count FROM card_set_registry WHERE set_key='v3'"
            ).fetchone()

        self.assertEqual(registry["display_name"], "套卡3 · 研究增强版")
        self.assertEqual(registry["card_count"], 8)
        self.assertEqual([c["card_title"] for c in cards], [
            "封面", "公司简介", "主产品", "创始团队",
            "用户群体", "公司能力分析", "增长与GTM", "竞争态势",
        ])
        page_fields = {c["card_index"]: json.loads(c["config_json"])["fields"] for c in cards}
        self.assertIn("market_landscape_top_players", page_fields[2])
        self.assertIn("funding_rounds", page_fields[2])
        self.assertIn("customer_choice_evidence", page_fields[5])

    def test_v3_markdown_renders_all_report_page_fields(self):
        self.research_db = _temp_db()
        with sqlite3.connect(self.research_db) as conn:
            _exec_sql(conn, "db/init_research_db.sql")
        db.save_research_records(self.research_db, [{
            "company_name": "DemoCo",
            "version": "standard",
            "company_type": "AI 搜索",
            "market_landscape_summary": "原生搜索与传统搜索增强并存。",
            "market_landscape_top_players": [{"name": "Google AI Overview"}, {"name": "You.com"}],
            "market_size_value": 12.5,
            "market_size_currency": "USD",
            "market_size_year": 2026,
            "funding_rounds": [{"round": "Series C", "amount": "500M USD"}],
            "customer_names": ["Acme"],
            "customer_choice_evidence": [{"type": "case_study", "url": "https://example.com/case"}],
        }])

        card2 = markdown_builder.build_card_markdown(
            self.research_db, "DemoCo", 2, "standard", card_set_key="v3"
        )
        card5 = markdown_builder.build_card_markdown(
            self.research_db, "DemoCo", 5, "standard", card_set_key="v3"
        )

        self.assertIn("Top 玩家", card2)
        self.assertIn("Google AI Overview", card2)
        self.assertIn("融资轮次", card2)
        self.assertIn("Series C", card2)
        self.assertIn("选择证据", card5)
        self.assertIn("case_study", card5)

    def test_split_research_to_fields_persists_v3_type_and_page_metadata(self):
        self._init_research_with_v3_migrations()
        rows = split_research_to_fields({
            "company_name": "DemoCo",
            "market_size_value": 12.5,
            "market_landscape_top_players": '[{"name":"Google"}]',
            "ltv_cac_is_benchmark": 1,
            "competitors_top3": '[{"name":"You.com"}]',
        })

        insert_research_fields_batch(self.research_db, rows)
        by_key = {
            row["field_key"]: row
            for row in get_research_fields(self.research_db, "DemoCo")
        }

        self.assertEqual(by_key["market_size_value"]["value_type"], "number")
        self.assertEqual(by_key["market_size_value"]["page_no"], 2)
        self.assertEqual(by_key["market_size_value"]["sort_order"], 4)
        self.assertEqual(by_key["market_landscape_top_players"]["value_type"], "json")
        self.assertEqual(by_key["ltv_cac_is_benchmark"]["page_no"], 6)
        self.assertEqual(by_key["competitors_top3"]["page_no"], 8)


if __name__ == "__main__":
    unittest.main()
