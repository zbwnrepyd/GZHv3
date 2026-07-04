import os
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

from services.field_service import (
    get_fields_with_versions,
    split_research_to_fields,
    translate_field_rows_if_needed,
    translate_field_value_if_needed,
)


class FieldServiceTests(unittest.TestCase):
    def _tmp_db(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_fields_with_versions_reads_final_card_values_from_research_db(self):
        research_db = self._tmp_db()
        final_db = self._tmp_db()
        with sqlite3.connect(research_db) as conn:
            conn.executescript(
                """
                CREATE TABLE research_fields (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    company_key TEXT DEFAULT '',
                    version TEXT DEFAULT 'standard',
                    field_key TEXT NOT NULL,
                    field_label TEXT,
                    field_value TEXT
                );
                CREATE TABLE final_card_values (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    company_key TEXT NOT NULL,
                    card_no INTEGER NOT NULL,
                    field_key TEXT NOT NULL,
                    final_value TEXT,
                    status TEXT DEFAULT 'draft',
                    confidence TEXT DEFAULT 'medium',
                    resolution_status TEXT DEFAULT 'draft'
                );
                INSERT INTO research_fields
                    (company_name, company_key, version, field_key, field_label, field_value)
                VALUES ('TestCo', '', 'standard', 'ltv', 'LTV', '暂缺');
                INSERT INTO final_card_values
                    (run_id, company_key, card_no, field_key, final_value, status, confidence, resolution_status)
                VALUES ('run-1', 'testco', 6, 'ltv', '行业基准 LTV', 'unavailable', 'medium', 'industry_avg');
                """
            )
        with sqlite3.connect(final_db) as conn:
            conn.executescript(
                """
                CREATE TABLE final_fields (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    field_key TEXT NOT NULL,
                    field_label TEXT,
                    final_value TEXT,
                    source_version TEXT DEFAULT 'standard',
                    status TEXT DEFAULT 'draft',
                    UNIQUE(company_name, field_key)
                );
                """
            )

        groups = get_fields_with_versions(
            research_db,
            final_db,
            "TestCo",
            card_values_db_path=research_db,
        )
        fields = {
            field["field_key"]: field
            for group in groups
            for field in group["fields"]
        }

        self.assertEqual(fields["ltv"]["final_value"], "行业基准 LTV")
        self.assertEqual(fields["ltv"]["status"], "industry_avg")
        self.assertEqual(fields["ltv"]["card_no"], 6)

    def test_translate_field_value_translates_english_business_text(self):
        value = "DemoCo helps teams automate research workflows with AI agents."

        with patch("deepseek_client.translate_to_chinese", return_value=["DemoCo 帮助团队用 AI Agent 自动化研究流程。"]) as translate:
            result = translate_field_value_if_needed("core_business", value)

        self.assertEqual(result, "DemoCo 帮助团队用 AI Agent 自动化研究流程。")
        translate.assert_called_once_with([value])

    def test_split_research_to_fields_serializes_json_values_as_json(self):
        rows = split_research_to_fields({
            "company_name": "DemoCo",
            "company_key": "democo",
            "display_name": "DemoCo",
            "product_pain_points": ["人工研究耗时", "信息分散"],
        })

        row = next(r for r in rows if r["field_key"] == "product_pain_points")

        self.assertEqual(row["field_value"], '["人工研究耗时", "信息分散"]')
        self.assertEqual(json.loads(row["field_value"]), ["人工研究耗时", "信息分散"])

    def test_translate_field_rows_batches_english_business_text(self):
        rows = [
            {"field_key": "core_business", "field_value": "DemoCo helps teams automate research workflows."},
            {"field_key": "growth_strategy", "field_value": "It grows through community templates and product-led adoption."},
            {"field_key": "main_product_name", "field_value": "DemoAgent"},
        ]

        with patch("deepseek_client.translate_to_chinese", return_value=[
            "DemoCo 帮助团队自动化研究流程。",
            "它通过社区模板和产品驱动采用增长。",
        ]) as translate:
            result = translate_field_rows_if_needed(rows)

        self.assertIs(result, rows)
        self.assertEqual(rows[0]["field_value"], "DemoCo 帮助团队自动化研究流程。")
        self.assertEqual(rows[1]["field_value"], "它通过社区模板和产品驱动采用增长。")
        self.assertEqual(rows[2]["field_value"], "DemoAgent")
        translate.assert_called_once_with([
            "DemoCo helps teams automate research workflows.",
            "It grows through community templates and product-led adoption.",
        ])

    def test_fields_with_versions_prefers_manual_final_fields(self):
        research_db = self._tmp_db()
        final_db = self._tmp_db()
        with sqlite3.connect(research_db) as conn:
            conn.executescript(
                """
                CREATE TABLE research_fields (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    company_key TEXT DEFAULT '',
                    version TEXT DEFAULT 'standard',
                    field_key TEXT NOT NULL,
                    field_label TEXT,
                    field_value TEXT
                );
                CREATE TABLE final_card_values (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    company_key TEXT NOT NULL,
                    card_no INTEGER NOT NULL,
                    field_key TEXT NOT NULL,
                    final_value TEXT,
                    status TEXT DEFAULT 'draft',
                    confidence TEXT DEFAULT 'medium',
                    resolution_status TEXT DEFAULT 'draft'
                );
                INSERT INTO research_fields
                    (company_name, company_key, version, field_key, field_label, field_value)
                VALUES ('TestCo', '', 'standard', 'company_type', '公司类型', '旧研究值');
                INSERT INTO final_card_values
                    (run_id, company_key, card_no, field_key, final_value, status, confidence, resolution_status)
                VALUES ('run-1', 'testco', 1, 'company_type', '旧读模型值', 'llm_extracted', 'medium', 'llm_extracted');
                """
            )
        with sqlite3.connect(final_db) as conn:
            conn.executescript(
                """
                CREATE TABLE final_fields (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    field_key TEXT NOT NULL,
                    field_label TEXT,
                    final_value TEXT,
                    source_version TEXT DEFAULT 'standard',
                    status TEXT DEFAULT 'draft',
                    UNIQUE(company_name, field_key)
                );
                INSERT INTO final_fields
                    (company_name, field_key, field_label, final_value, status)
                VALUES ('TestCo', 'company_type', '公司类型', '用户保存值', 'confirmed');
                """
            )

        groups = get_fields_with_versions(
            research_db,
            final_db,
            "TestCo",
            card_values_db_path=research_db,
        )
        fields = {
            field["field_key"]: field
            for group in groups
            for field in group["fields"]
        }

        self.assertEqual(fields["company_type"]["final_value"], "用户保存值")
        self.assertEqual(fields["company_type"]["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
