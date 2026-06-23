"""TDD: 数据库全字段 API 测试（三版本并列）"""
from __future__ import annotations
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import app as app_module
from repositories.field_repo import insert_research_field, upsert_final_field
from services.field_service import load_field_contract


def _init_db(sql_path: str) -> str:
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    with open(sql_path, encoding="utf-8") as f:
        schema = f.read()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


class AllFieldsAPITests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.research_db = _init_db(os.path.join(ROOT, "db", "migrations", "001_research_fields.sql"))
        self.final_db = _init_db(os.path.join(ROOT, "db", "migrations", "002_final_fields.sql"))
        self._orig_research_db = app_module.config.DB_PATH_RESEARCH
        self._orig_final_db = app_module.config.DB_PATH_FINAL
        app_module.config.DB_PATH_RESEARCH = self.research_db
        app_module.config.DB_PATH_FINAL = self.final_db

    def tearDown(self):
        app_module.config.DB_PATH_RESEARCH = self._orig_research_db
        app_module.config.DB_PATH_FINAL = self._orig_final_db
        for p in (self.research_db, self.final_db):
            if os.path.exists(p):
                os.remove(p)

    def _seed_all_versions(self, company="TestCo"):
        """三版本各写入不同字段，验证合并"""
        # standard
        insert_research_field(self.research_db, company, "standard",
                              "company_name", "公司名", "TestCo", "llm_extract", "", "high")
        insert_research_field(self.research_db, company, "standard",
                              "founded_year", "成立年份", "2023", "llm_extract", "", "high")
        # standard only 字段
        insert_research_field(self.research_db, company, "standard",
                              "std_only_field", "标准版专属", "std_val", "llm_extract", "", "low")
        # business
        insert_research_field(self.research_db, company, "business",
                              "company_name", "公司名", "TestCo商业版", "llm_extract", "", "high")
        insert_research_field(self.research_db, company, "business",
                              "founded_year", "成立年份", "2023", "llm_extract", "", "high")
        # business only 字段
        insert_research_field(self.research_db, company, "business",
                              "biz_only_field", "商业版专属", "biz_val", "llm_extract", "", "medium")
        # spread
        insert_research_field(self.research_db, company, "spread",
                              "company_name", "公司名", "TestCo传播版", "llm_extract", "", "high")
        # final
        upsert_final_field(self.final_db, company, "company_name",
                           "定稿公司名", "公司名", "standard", "confirmed")
        upsert_final_field(self.final_db, company, "founded_year",
                           "", "成立年份", "standard", "draft")

    def test_all_fields_returns_200(self):
        self._seed_all_versions("DemoCo")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        self.assertEqual(resp.status_code, 200)

    def test_all_fields_merges_three_versions(self):
        """三个版本的所有唯一 field_key 都应出现"""
        self._seed_all_versions("DemoCo")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        keys = {f["field_key"] for f in data["fields"]}
        self.assertIn("company_name", keys)
        self.assertIn("founded_year", keys)
        self.assertIn("std_only_field", keys)
        self.assertIn("biz_only_field", keys)

    def test_all_fields_expands_to_contract_when_research_is_partial(self):
        """research_fields 只有部分字段时，数据库全字段面板仍展示完整字段清单。"""
        insert_research_field(self.research_db, "DemoCo", "standard",
                              "company_name", "公司名", "DemoCo", "llm_extract", "", "high")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        contract_total = sum(
            len(group.get("fields", []))
            for group in load_field_contract().get("groups", [])
        )
        keys = {f["field_key"] for f in data["fields"]}
        self.assertGreaterEqual(data["total"], contract_total)
        self.assertIn("company_name", keys)
        self.assertIn("company_type", keys)
        self.assertEqual(data["research_counts"]["standard"], 1)

    def test_all_fields_version_values_side_by_side(self):
        """同一字段的三版本值应分别展示"""
        self._seed_all_versions("DemoCo")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        cn = next(f for f in data["fields"] if f["field_key"] == "company_name")
        self.assertEqual(cn["value_standard"], "TestCo")
        self.assertEqual(cn["value_business"], "TestCo商业版")
        self.assertEqual(cn["value_spread"], "TestCo传播版")

    def test_all_fields_version_only_field_has_empty_others(self):
        """仅在 standard 中的字段，business/spread 值应为空字符串"""
        self._seed_all_versions("DemoCo")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        sf = next(f for f in data["fields"] if f["field_key"] == "std_only_field")
        self.assertEqual(sf["value_standard"], "std_val")
        self.assertEqual(sf["value_business"], "")
        self.assertEqual(sf["value_spread"], "")

    def test_all_fields_final_value_override(self):
        self._seed_all_versions("DemoCo")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        cn = next(f for f in data["fields"] if f["field_key"] == "company_name")
        self.assertEqual(cn["final_value"], "定稿公司名")
        self.assertEqual(cn["final_status"], "confirmed")

    def test_all_fields_empty_final_is_empty_string(self):
        self._seed_all_versions("DemoCo")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        fy = next(f for f in data["fields"] if f["field_key"] == "founded_year")
        self.assertEqual(fy["final_value"], "")
        self.assertEqual(fy["final_status"], "draft")

    def test_all_fields_never_finalized_is_none(self):
        self._seed_all_versions("DemoCo")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        sf = next(f for f in data["fields"] if f["field_key"] == "std_only_field")
        self.assertIsNone(sf["final_value"])

    def test_all_fields_counts_match(self):
        self._seed_all_versions("DemoCo")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        self.assertEqual(data["research_counts"]["standard"], 3)
        self.assertEqual(data["research_counts"]["business"], 3)
        self.assertEqual(data["research_counts"]["spread"], 1)
        self.assertEqual(data["final_count"], 2)

    def test_all_fields_empty_company(self):
        resp = self.client.get("/api/company/NoSuchCo/all-fields")
        data = resp.get_json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["fields"], [])

    def test_all_fields_final_only_included(self):
        self._seed_all_versions("DemoCo")
        upsert_final_field(self.final_db, "DemoCo",
                           "card_1_title", "卡片标题", "标准", "confirmed")
        resp = self.client.get("/api/company/DemoCo/all-fields")
        data = resp.get_json()
        self.assertGreaterEqual(data["total"], 5)  # 4 unique keys + 1 final-only
        ct = next(f for f in data["fields"] if f["field_key"] == "card_1_title")
        self.assertEqual(ct["value_standard"], "")
        self.assertEqual(ct["final_value"], "卡片标题")


if __name__ == "__main__":
    unittest.main()
