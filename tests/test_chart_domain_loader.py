"""v2.1 数据域隔离加载器测试 — 验证 _load_chart_company_domain 行为"""
from __future__ import annotations
import json
import os
import sqlite3
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))
from app import (
    _canonical_company_key,
    _parse_competitor_names,
    _load_chart_company_domain,
)
from infographic import build_competitive_landscape_svg, build_stack_positioning_svg


def _init_research_db(db_path: str):
    """Create a minimal research + research_jobs schema for testing."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            company_key TEXT,
            display_name TEXT,
            version TEXT DEFAULT 'standard',
            competitors TEXT,
            score_defensibility REAL,
            score_incumbent_attention REAL,
            score_value_capture REAL,
            funding_stage_score REAL,
            stack_layer TEXT,
            ecosystem_niche TEXT,
            ecosystem_positioning TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            company_key TEXT DEFAULT '',
            version TEXT DEFAULT 'standard',
            field_key TEXT NOT NULL,
            field_value TEXT,
            resolution_status TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _seed_rows(db_path: str, rows: list[dict]):
    conn = sqlite3.connect(db_path)
    for r in rows:
        r.setdefault("version", "standard")
        conn.execute(
            """INSERT INTO research
               (company_name, company_key, display_name, version, competitors,
                score_defensibility, score_incumbent_attention,
                score_value_capture, funding_stage_score, stack_layer,
                ecosystem_niche, ecosystem_positioning)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r.get("company_name"), r.get("company_key"), r.get("display_name"),
             r.get("version"), r.get("competitors"),
             r.get("score_defensibility"), r.get("score_incumbent_attention"),
             r.get("score_value_capture"), r.get("funding_stage_score"),
             r.get("stack_layer"), r.get("ecosystem_niche"),
             r.get("ecosystem_positioning")),
        )
    conn.commit()
    conn.close()


def _seed_research_fields(db_path: str, company_name: str, fields: dict, company_key: str = "target.ai"):
    conn = sqlite3.connect(db_path)
    for field_key, value in fields.items():
        conn.execute(
            """INSERT INTO research_fields
               (company_name, company_key, version, field_key, field_value, resolution_status)
               VALUES (?, ?, 'standard', ?, ?, 'confirmed')""",
            (company_name, company_key, field_key, value),
        )
    conn.commit()
    conn.close()


class DomainLoaderTests(unittest.TestCase):
    """Fix F: 数据域隔离加载器测试"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        _init_research_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_canonical_key_lower_strip(self):
        self.assertEqual(_canonical_company_key("Limitless"), "limitless")
        self.assertEqual(_canonical_company_key("  Anthropic  "), "anthropic")
        self.assertEqual(_canonical_company_key(None), "")

    def test_parse_competitor_names_from_json_array(self):
        raw = json.dumps([{"name": "OpenAI"}, {"name": "Google"}])
        names = _parse_competitor_names(raw)
        self.assertEqual(names, ["OpenAI", "Google"])

    def test_parse_competitor_names_dedup_case(self):
        raw = json.dumps([{"name": "OpenAI"}, {"name": "openai"}])
        names = _parse_competitor_names(raw)
        self.assertEqual(names, ["OpenAI"])

    def test_parse_competitor_names_empty_or_bad(self):
        self.assertEqual(_parse_competitor_names(None), [])
        self.assertEqual(_parse_competitor_names(""), [])

    def test_parse_competitor_names_text_fallback(self):
        # 纯文本无分隔符 → 单条竞品
        self.assertEqual(_parse_competitor_names("not json"), ["not json"])
        # 中文顿号分隔
        self.assertEqual(_parse_competitor_names("A、B、C"), ["A", "B", "C"])
        # 逗号分隔
        self.assertEqual(_parse_competitor_names("OpenAI,Google,Anthropic"), ["OpenAI", "Google", "Anthropic"])
        # 换行分隔
        self.assertEqual(_parse_competitor_names("A\nB\nC"), ["A", "B", "C"])

    def test_load_domain_only_target_and_competitors(self):
        _seed_rows(self.db_path, [
            {"company_name": "TargetCo", "company_key": "target.ai",
             "competitors": json.dumps([{"name": "RivalA"}, {"name": "RivalB"}]),
             "score_defensibility": 8, "score_incumbent_attention": 6,
             "score_value_capture": 7, "funding_stage_score": 5, "stack_layer": "vertical_app"},
            {"company_name": "RivalA", "company_key": "rivala.io",
             "score_defensibility": 5, "score_incumbent_attention": 4,
             "score_value_capture": 5, "funding_stage_score": 3, "stack_layer": "middleware"},
            {"company_name": "RivalB", "company_key": "rivalb.io",
             "score_defensibility": 6, "score_incumbent_attention": 7,
             "score_value_capture": 6, "funding_stage_score": 4, "stack_layer": "infrastructure"},
            {"company_name": "UnrelatedCo", "company_key": "unrelated.io",
             "score_defensibility": 9, "score_incumbent_attention": 9,
             "score_value_capture": 9, "funding_stage_score": 8, "stack_layer": "model"},
        ])
        domain = _load_chart_company_domain(self.db_path, "TargetCo")
        names = {r["company_name"] for r in domain}
        self.assertIn("TargetCo", names)
        self.assertIn("RivalA", names)
        self.assertIn("RivalB", names)
        self.assertNotIn("UnrelatedCo", names)

    def test_load_domain_target_first(self):
        _seed_rows(self.db_path, [
            {"company_name": "TargetCo", "company_key": "target.ai",
             "competitors": json.dumps([{"name": "RivalB"}, {"name": "RivalA"}]),
             "score_defensibility": 8, "score_incumbent_attention": 6,
             "score_value_capture": 7, "funding_stage_score": 5, "stack_layer": "app"},
            {"company_name": "RivalA", "company_key": "rivala",
             "score_defensibility": 5, "score_incumbent_attention": 4,
             "score_value_capture": 5, "funding_stage_score": 3, "stack_layer": "mw"},
            {"company_name": "RivalB", "company_key": "rivalb",
             "score_defensibility": 6, "score_incumbent_attention": 7,
             "score_value_capture": 6, "funding_stage_score": 4, "stack_layer": "infra"},
        ])
        domain = _load_chart_company_domain(self.db_path, "TargetCo")
        self.assertEqual(domain[0]["company_name"], "TargetCo")
        # competitors 按原始顺序 RivalB → RivalA
        self.assertEqual(domain[1]["company_name"], "RivalB")
        self.assertEqual(domain[2]["company_name"], "RivalA")

    def test_load_domain_caps_to_twelve(self):
        comps = [{"name": f"Comp{i}"} for i in range(20)]
        _seed_rows(self.db_path, [
            {"company_name": "TargetCo", "company_key": "target.ai",
             "competitors": json.dumps(comps),
             "score_defensibility": 8, "score_incumbent_attention": 6,
             "score_value_capture": 7, "funding_stage_score": 5, "stack_layer": "app"},
        ] + [
            {"company_name": f"Comp{i}", "company_key": f"comp{i}.co",
             "score_defensibility": 5, "score_incumbent_attention": 4,
             "score_value_capture": 5, "funding_stage_score": 3, "stack_layer": "mw"}
            for i in range(20)
        ])
        domain = _load_chart_company_domain(self.db_path, "TargetCo", max_companies=12)
        self.assertLessEqual(len(domain), 12)

    def test_load_domain_no_competitors_returns_target_only(self):
        _seed_rows(self.db_path, [
            {"company_name": "SoloCo", "company_key": "solo.ai",
             "competitors": None,
             "score_defensibility": 8, "score_incumbent_attention": 6,
             "score_value_capture": 7, "funding_stage_score": 5, "stack_layer": "app"},
        ])
        domain = _load_chart_company_domain(self.db_path, "SoloCo")
        self.assertEqual(len(domain), 1)
        self.assertEqual(domain[0]["company_name"], "SoloCo")

    def test_load_domain_reclassifies_orchestration_niche_as_middleware(self):
        _seed_rows(self.db_path, [
            {"company_name": "Kilo", "company_key": "kilo.ai",
             "competitors": json.dumps([{"name": "Cursor"}]),
             "score_defensibility": 6, "score_incumbent_attention": 6,
             "score_value_capture": 6, "funding_stage_score": 3,
             "stack_layer": "vertical_app",
             "ecosystem_niche": "开源模型中立编排层，连接 500+ AI 模型与开发者工作流的智能代理中台。"},
            {"company_name": "Cursor", "company_key": "cursor.com",
             "score_defensibility": 6, "score_incumbent_attention": 8,
             "score_value_capture": 5, "funding_stage_score": 9,
             "stack_layer": "vertical_app"},
        ])

        domain = _load_chart_company_domain(self.db_path, "Kilo")

        self.assertEqual(domain[0]["company_name"], "Kilo")
        self.assertEqual(domain[0]["stack_layer"], "middleware")

    def test_load_domain_unknown_target_returns_empty(self):
        domain = _load_chart_company_domain(self.db_path, "GhostCo")
        self.assertEqual(domain, [])

    def test_load_domain_falls_back_to_research_fields(self):
        _seed_research_fields(self.db_path, "FieldOnlyCo", {
            "company_name": "FieldOnlyCo",
            "competitors": json.dumps([
                {"name": "RivalA"},
                {"name": "RivalB"},
            ]),
            "score_defensibility": "8",
            "score_incumbent_attention": "6",
            "score_value_capture": "7",
            "funding_stage_score": "5",
            "stack_layer": "middleware",
        })

        domain = _load_chart_company_domain(self.db_path, "FieldOnlyCo")
        self.assertGreaterEqual(len(domain), 3)
        self.assertEqual(domain[0]["company_name"], "FieldOnlyCo")
        self.assertEqual(domain[0]["score_defensibility"], 8.0)
        self.assertEqual(domain[0]["score_value_capture"], 7.0)
        self.assertEqual(domain[0]["stack_layer"], "middleware")
        estimated = [r for r in domain if r.get("estimated_position")]
        self.assertEqual([r["company_name"] for r in estimated], ["RivalA", "RivalB"])
        for row in estimated:
            self.assertIsNotNone(row.get("score_defensibility"))
            self.assertIsNotNone(row.get("score_incumbent_attention"))
            self.assertIsNotNone(row.get("score_value_capture"))
            self.assertIsNotNone(row.get("stack_layer"))

    def test_research_fields_fallback_renders_both_charts_with_data(self):
        _seed_research_fields(self.db_path, "FieldOnlyCo", {
            "company_name": "FieldOnlyCo",
            "competitors_top3": json.dumps([
                {"name": "RivalA"},
                {"name": "RivalB"},
            ]),
            "score_defensibility": "8",
            "score_incumbent_attention": "6",
            "score_value_capture": "7",
            "funding_stage_score": "5",
            "stack_layer": "middleware",
        })

        domain = _load_chart_company_domain(self.db_path, "FieldOnlyCo")
        competitive = build_competitive_landscape_svg(domain, "FieldOnlyCo", {"theme": "light"})
        ecosystem = build_stack_positioning_svg(domain, "FieldOnlyCo", {"theme": "light"})

        self.assertNotIn("暂无可用图表数据", competitive)
        self.assertNotIn("暂无可用图表数据", ecosystem)
        self.assertIn("FieldOnlyCo", competitive)
        self.assertIn("FieldOnlyCo", ecosystem)

    def test_load_domain_prefers_company_key_dedup(self):
        """大小写变体按 company_key 去重"""
        _seed_rows(self.db_path, [
            {"company_name": "Limitless", "company_key": "limitless.ai",
             "competitors": json.dumps([{"name": "openai"}]),
             "score_defensibility": 8, "score_incumbent_attention": 6,
             "score_value_capture": 7, "funding_stage_score": 5, "stack_layer": "app"},
            {"company_name": "OpenAI", "company_key": "openai.com",
             "score_defensibility": 9, "score_incumbent_attention": 9,
             "score_value_capture": 9, "funding_stage_score": 8, "stack_layer": "model"},
        ])
        domain = _load_chart_company_domain(self.db_path, "Limitless")
        names = [r["company_name"] for r in domain]
        self.assertIn("Limitless", names)
        self.assertIn("OpenAI", names)
        # openai 不应重复出现
        self.assertEqual(len(names), len(set(n.lower() for n in names)))


if __name__ == "__main__":
    unittest.main()
