import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

from services.field_service import get_fields_with_versions


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


if __name__ == "__main__":
    unittest.main()
