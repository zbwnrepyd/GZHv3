"""Test that init_company_set uses correct display_role defaults."""
import json
import os
import sqlite3
import sys
import unittest
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBAPP = ROOT / "webapp"
if str(WEBAPP) not in sys.path:
    sys.path.insert(0, str(WEBAPP))


class CardConfigInitTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "composition_db.sqlite")
        conn = sqlite3.connect(self.db_path)
        # Create all required tables (matching init_composition_db.sql schema)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS card_set_registry (
                set_key TEXT PRIMARY KEY, display_name TEXT, spec_version TEXT, card_count INTEGER);
            CREATE TABLE IF NOT EXISTS card_compositions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT NOT NULL,
                card_set_key TEXT NOT NULL, card_id TEXT NOT NULL, card_index INTEGER,
                card_title TEXT, template_id TEXT, enabled INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS card_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT NOT NULL,
                card_set_key TEXT NOT NULL, card_id TEXT NOT NULL, item_type TEXT,
                item_key TEXT, item_label TEXT, display_role TEXT DEFAULT 'body',
                enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0,
                config_json TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS default_card_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, set_key TEXT NOT NULL,
                card_id TEXT NOT NULL, card_index INTEGER NOT NULL,
                card_title TEXT NOT NULL, config_json TEXT NOT NULL);
            INSERT OR REPLACE INTO card_set_registry VALUES ('v3','套卡3','v3',8);
            INSERT OR REPLACE INTO default_card_configs (set_key,card_id,card_index,card_title,config_json) VALUES
            ('v3','v3_card_01',1,'封面','{"fields":["company_name","company_type"],"media":["logo"],"template_id":"cover_v3"}'),
            ('v3','v3_card_04',4,'创始团队','{"fields":["founder_name","founder_edu"],"media":["founder_photo"],"template_id":"founder_v3"}'),
            ('v3','v3_card_07',7,'增长与GTM','{"fields":["growth_strategy","growth_flywheel"],"media":["flywheel"],"template_id":"gtm_growth_v3"}');
        """)
        conn.commit()
        conn.close()
        os.environ["COMPOSITION_DB_PATH"] = self.db_path

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_company_set_uses_correct_field_roles(self):
        """company_name->title, company_type->subtitle, others->body."""
        from repositories.card_config_repo import init_company_set
        init_company_set(self.db_path, "TestCo", "v3", "v3")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT item_key, display_role FROM card_items WHERE company_name='TestCo' AND item_type='field'"
        ).fetchall()
        conn.close()

        role_map = {r["item_key"]: r["display_role"] for r in rows}
        self.assertEqual(role_map.get("company_name"), "title",
                         f"company_name should be title, got {role_map.get('company_name')}")
        self.assertEqual(role_map.get("company_type"), "subtitle",
                         f"company_type should be subtitle, got {role_map.get('company_type')}")
        self.assertEqual(role_map.get("founder_name"), "body",
                         f"founder_name should be body, got {role_map.get('founder_name')}")

    def test_init_company_set_uses_correct_media_roles(self):
        """logo->logo, flywheel->chart, others->hero_image."""
        from repositories.card_config_repo import init_company_set
        init_company_set(self.db_path, "TestCo", "v3", "v3")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT item_key, display_role FROM card_items WHERE company_name='TestCo' AND item_type='media'"
        ).fetchall()
        conn.close()

        role_map = {r["item_key"]: r["display_role"] for r in rows}
        self.assertEqual(role_map.get("logo"), "logo",
                         f"logo should be logo, got {role_map.get('logo')}")
        self.assertEqual(role_map.get("flywheel"), "chart",
                         f"flywheel should be chart, got {role_map.get('flywheel')}")
        self.assertEqual(role_map.get("founder_photo"), "hero_image",
                         f"founder_photo should be hero_image, got {role_map.get('founder_photo')}")


if __name__ == "__main__":
    unittest.main()
