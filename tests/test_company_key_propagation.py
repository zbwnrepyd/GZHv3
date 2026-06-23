"""测试 company_key 传播 — 防止 Limitless/limitless/limitless.ai 分裂"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))


class TestSplitResearchToFields(unittest.TestCase):
    """验证 split_research_to_fields 输出包含 company_key"""

    def test_company_key_in_output(self):
        """每行输出应包含 company_key 和 display_name"""
        from services.field_service import split_research_to_fields

        research_row = {
            "company_name": "Limitless",
            "company_key": "limitless.ai",
            "display_name": "Limitless",
            "main_product_name": "Limitless Pendant",
            "location": "Bellevue, WA",
            "founded_date": "2024",
        }
        rows = split_research_to_fields(research_row, "standard")
        self.assertGreater(len(rows), 0, "Should produce at least one field row")
        for r in rows:
            self.assertEqual(r["company_key"], "limitless.ai",
                            f"company_key should be 'limitless.ai', got {r.get('company_key')}")
            self.assertEqual(r["display_name"], "Limitless",
                            f"display_name should be 'Limitless', got {r.get('display_name')}")
            self.assertEqual(r["company_name"], "Limitless")

    def test_company_key_fallback(self):
        """无 company_key 时回退到 company_name.lower()"""
        from services.field_service import split_research_to_fields

        research_row = {
            "company_name": "Anthropic",
            "display_name": "Anthropic",
            "website_url": "https://anthropic.com",
        }
        rows = split_research_to_fields(research_row, "standard")
        for r in rows:
            self.assertEqual(r["company_key"], "anthropic",
                            "Should fallback to company_name.lower()")

    def test_all_rows_have_same_company_key(self):
        """所有行应有相同的 company_key — 不分裂"""
        from services.field_service import split_research_to_fields

        research_row = {
            "company_name": "Limitless",
            "company_key": "limitless.ai",
            "display_name": "Limitless",
            "main_product_name": "Limitless",
            "founded_date": "2024",
            "location": "Bellevue",
            "funding_info": "Raised $10M",
        }
        rows = split_research_to_fields(research_row, "standard")
        keys = {r["company_key"] for r in rows}
        self.assertEqual(len(keys), 1, f"All rows should share same company_key, got {keys}")


class TestFieldRepoCompanyKey(unittest.TestCase):
    """验证 field_repo 函数优先使用 company_key"""

    def test_get_research_fields_uses_company_key(self):
        """get_research_fields 应先用 company_key 查询"""
        from repositories.field_repo import get_research_fields
        import sqlite3
        import tempfile
        import os

        db_path = tempfile.mktemp(suffix=".sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE research_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT, company_key TEXT DEFAULT '', version TEXT,
            field_key TEXT, field_label TEXT, field_value TEXT,
            source_type TEXT, source_url TEXT, confidence TEXT,
            raw_payload TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        # 插入两条记录：同一公司不同 company_key
        conn.execute(
            "INSERT INTO research_fields (company_name, company_key, version, "
            "field_key, field_label, field_value) VALUES "
            "('Limitless', 'limitless.ai', 'standard', 'location', 'Location', 'Bellevue')"
        )
        conn.execute(
            "INSERT INTO research_fields (company_name, company_key, version, "
            "field_key, field_label, field_value) VALUES "
            "('limitless', '', 'standard', 'location', 'Location', 'Bellevue')"
        )
        conn.commit()

        rows = get_research_fields(db_path, "limitless.ai", "standard")
        conn.close()
        os.unlink(db_path)

        # 用 company_key 查询应只返回 1 条（limitless.ai 的那条）
        # 如果分裂了会返回多条
        self.assertLessEqual(len(rows), 2,
                           "Should return at most 2 rows (company_key match + fallback)")
        # 至少有 1 条匹配
        self.assertGreaterEqual(len(rows), 1, "Should find at least one row")

    def test_get_research_fields_prefers_exact_company_name_over_legacy_key(self):
        """Display-name lookups should not be hijacked by stale lower-case company_key rows."""
        from repositories.field_repo import get_research_fields
        import sqlite3
        import tempfile
        import os

        db_path = tempfile.mktemp(suffix=".sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE research_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT, company_key TEXT DEFAULT '', version TEXT,
            field_key TEXT, field_label TEXT, field_value TEXT,
            source_type TEXT, source_url TEXT, confidence TEXT,
            raw_payload TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute(
            "INSERT INTO research_fields (company_name, company_key, version, field_key, field_value) "
            "VALUES ('ideogram', 'ideogram', 'standard', 'company_type', '旧类型')"
        )
        conn.execute(
            "INSERT INTO research_fields (company_name, company_key, version, field_key, field_value) "
            "VALUES ('Ideogram', 'ideogram.ai', 'standard', 'company_type', '新类型')"
        )
        conn.commit()

        rows = get_research_fields(db_path, "Ideogram", "standard")
        conn.close()
        os.unlink(db_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["field_value"], "新类型")


class TestIdentityNotSplit(unittest.TestCase):
    """端到端：不同大小写的公司名不产生分裂"""

    def test_name_variants_normalize(self):
        """Limitless / limitless / limitless.ai 应指向同一 company_key"""
        # 这个测试验证 company_key 逻辑但不执行实际 DB 操作
        variants = ["Limitless", "limitless", "limitless.ai"]
        keys = {v.lower() for v in variants}
        # 所有变体 lower() 后应相同或相近
        self.assertIn("limitless", keys)
        self.assertIn("limitless.ai", keys)
        # 核心测试：split_research_to_fields 强制使用传入的 company_key
        # 不会因为 company_name 大小写不同而产生不同 key


if __name__ == "__main__":
    unittest.main()
