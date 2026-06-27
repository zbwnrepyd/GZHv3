"""Test that RenderAssembler includes display_role in v3 contract items."""
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

from services.role_defaults import default_role_for_field, default_role_for_media


class RenderAssemblerDisplayRoleTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.research_db = os.path.join(self.tmpdir, "research_db.sqlite")
        self.final_db = os.path.join(self.tmpdir, "final_db.sqlite")
        self.assets_db = os.path.join(self.tmpdir, "assets_db.sqlite")
        self.composition_db = os.path.join(self.tmpdir, "composition_db.sqlite")

        # Create minimal tables
        for db_path in [self.research_db, self.final_db, self.assets_db, self.composition_db]:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE IF NOT EXISTS research (company_name TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS research_fields (id INTEGER PRIMARY KEY, company_name TEXT, field_key TEXT, field_value TEXT, version TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS final_fields (company_name TEXT, field_key TEXT, final_value TEXT, status TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS final_card_values (company_key TEXT, field_key TEXT, final_value TEXT, status TEXT, confidence TEXT, resolution_status TEXT, updated_at TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS company_assets (company_name TEXT, asset_key TEXT, local_path TEXT, status TEXT)")
            conn.commit()
            conn.close()

        # Set up composition DB with card configs
        conn = sqlite3.connect(self.composition_db)
        conn.execute("""CREATE TABLE IF NOT EXISTS default_card_configs (
            id INTEGER PRIMARY KEY, set_key TEXT, card_id TEXT, card_index INTEGER,
            card_title TEXT, config_json TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS card_compositions (
            company_name TEXT, card_id TEXT, card_set_key TEXT, card_title TEXT,
            template_id TEXT, card_index INTEGER, enabled INTEGER DEFAULT 1)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS card_items (
            company_name TEXT, card_set_key TEXT, card_id TEXT,
            item_type TEXT, item_key TEXT, item_label TEXT,
            display_role TEXT DEFAULT 'body', enabled INTEGER DEFAULT 1,
            sort_order INTEGER)""")
        # Insert v3 defaults
        conn.execute("""INSERT INTO default_card_configs (set_key,card_id,card_index,card_title,config_json) VALUES
            ('v3','v3_card_01',1,'封面','{"fields":["company_name","company_type"],"media":["logo"],"template_id":"cover_v3"}'),
            ('v3','v3_card_04',4,'创始团队','{"fields":["founder_name","founder_edu"],"media":["founder_photo"],"template_id":"founder_v3"}'),
            ('v3','v3_card_08',8,'竞争态势','{"fields":["competitors_top3","competitive_position"],"media":["chart_competitive"],"template_id":"competition_v3"}')
        """)
        conn.commit()
        conn.close()

        os.environ["COMPOSITION_DB_PATH"] = self.composition_db

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_assembler(self):
        from services.render_assembler import RenderAssembler
        return RenderAssembler(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            assets_db_path=self.assets_db,
            composition_db_path=self.composition_db,
        )

    def test_field_item_has_display_role_from_default(self):
        """company_name -> title, company_type -> subtitle, others -> body."""
        assembler = self._make_assembler()
        contract = assembler.assemble("TestCo", "v3")
        cards = {c["card_id"]: c for c in contract["cards"]}
        card01 = cards["v3_card_01"]
        items = {i["field_key"]: i for i in card01["items"]}

        self.assertIn("company_name", items)
        self.assertEqual(items["company_name"].get("display_role"), "title",
                         "company_name should have display_role='title'")
        self.assertIn("company_type", items)
        self.assertEqual(items["company_type"].get("display_role"), "subtitle",
                         "company_type should have display_role='subtitle'")

    def test_media_item_has_display_role_from_default(self):
        """logo -> logo, chart_competitive -> chart."""
        assembler = self._make_assembler()
        contract = assembler.assemble("TestCo", "v3")
        cards = {c["card_id"]: c for c in contract["cards"]}
        card01 = cards["v3_card_01"]
        media = {m["asset_key"]: m for m in card01["media"]}

        self.assertIn("logo", media)
        self.assertEqual(media["logo"].get("display_role"), "logo",
                         "logo should have display_role='logo'")

        card08 = cards["v3_card_08"]
        media08 = {m["asset_key"]: m for m in card08["media"]}
        self.assertIn("chart_competitive", media08)
        self.assertEqual(media08["chart_competitive"].get("display_role"), "chart",
                         "chart_competitive should have display_role='chart'")

    def test_display_role_from_card_items_preserved(self):
        """When card_items exist with explicit display_role, use that value."""
        # Insert card_items with custom display_role
        conn = sqlite3.connect(self.composition_db)
        conn.execute("""INSERT INTO card_compositions (company_name,card_id,card_set_key,card_title,template_id,card_index,enabled)
            VALUES ('TestCo','v3_card_01','v3','封面','cover_v3',1,1)""")
        conn.execute("""INSERT INTO card_items (company_name,card_set_key,card_id,item_type,item_key,item_label,display_role,enabled,sort_order)
            VALUES ('TestCo','v3','v3_card_01','field','company_name','公司名','custom_title',1,0)""")
        conn.commit()
        conn.close()

        assembler = self._make_assembler()
        contract = assembler.assemble("TestCo", "v3")
        cards = {c["card_id"]: c for c in contract["cards"]}
        items = {i["field_key"]: i for i in cards["v3_card_01"]["items"]}
        self.assertEqual(items["company_name"].get("display_role"), "custom_title",
                         "display_role from card_items should be preserved")

    def test_all_v3_cards_have_display_role_on_all_items(self):
        """Every item in every v3 card should have a display_role."""
        assembler = self._make_assembler()
        contract = assembler.assemble("TestCo", "v3")
        for card in contract["cards"]:
            for item in card["items"]:
                self.assertIn("display_role", item,
                              f"{card['card_id']} item {item.get('field_key','?')} missing display_role")
            for m in card["media"]:
                self.assertIn("display_role", m,
                              f"{card['card_id']} media {m.get('asset_key','?')} missing display_role")


if __name__ == "__main__":
    unittest.main()
