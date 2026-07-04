"""Test system card config sync between JSON contracts and DB defaults."""
import json
import re
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CardConfigSyncTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.v3_json_path = ROOT / "contracts" / "card_sets" / "v3.json"
        cls.sql_path = ROOT / "db" / "init_composition_db.sql"
        with open(cls.v3_json_path) as f:
            cls.v3_data = json.load(f)
        cls.v3_cards = {c["card_id"]: c for c in cls.v3_data["cards"]}

        # Parse SQL for v3 card configs
        cls.db_cards = cls._load_sql_cards("v3", "v3_card")

    @classmethod
    def _load_sql_cards(cls, set_key: str, card_prefix: str) -> dict:
        db_cards = {}
        with open(cls.sql_path) as f:
            content = f.read()
        for match in re.finditer(
            rf"\('{set_key}','({card_prefix}_\d+)',\d+,'[^']*','(\{{[^}}]*\}})'\)",
            content
        ):
            card_id = match.group(1)
            config = json.loads(match.group(2))
            db_cards[card_id] = config
        return db_cards

    @classmethod
    def _load_registry(cls) -> dict:
        with open(cls.sql_path) as f:
            content = f.read()
        registry = {}
        for match in re.finditer(
            r"\('([^']+)',\s*'([^']+)',\s*'([^']+)',\s*(\d+),\s*(\d+)\)",
            content
        ):
            set_key, display_name, spec_version, card_count, is_system = match.groups()
            registry[set_key] = {
                "display_name": display_name,
                "spec_version": spec_version,
                "card_count": int(card_count),
                "is_system": int(is_system),
            }
        return registry

    def test_v3_card_02_has_market_track_and_subtrack_in_db(self):
        """v3_card_02 should include market_track and market_subtrack."""
        config = self.db_cards.get("v3_card_02")
        self.assertIsNotNone(config, "v3_card_02 not found in DB")
        fields = config.get("fields", [])
        self.assertIn("market_track", fields,
                      "market_track missing from v3_card_02 in DB")
        self.assertIn("market_subtrack", fields,
                      "market_subtrack missing from v3_card_02 in DB")

    def test_v3_json_and_db_field_sets_identical(self):
        """For every v3 card, the field sets in v3.json and DB must match."""
        all_card_ids = set(list(self.v3_cards.keys()) + list(self.db_cards.keys()))
        for card_id in sorted(all_card_ids):
            v3_fields = set(self.v3_cards.get(card_id, {}).get("fields", []))
            db_fields = set(self.db_cards.get(card_id, {}).get("fields", []))
            only_v3 = v3_fields - db_fields
            only_db = db_fields - v3_fields
            if only_v3:
                self.fail(
                    f"{card_id}: v3.json has fields that DB is missing: {sorted(only_v3)}"
                )
            if only_db:
                self.fail(
                    f"{card_id}: DB has fields that v3.json is missing: {sorted(only_db)}"
                )

    def test_v3_card_07_no_deprecated_fields(self):
        """v3_card_07 must NOT contain gtm_motion."""
        config = self.db_cards.get("v3_card_07")
        self.assertIsNotNone(config, "v3_card_07 not found in DB")
        fields = config.get("fields", [])
        self.assertNotIn("gtm_motion", fields,
                         "gtm_motion is deprecated, should not be in v3_card_07")
        # cold_start 已取消 deprecated，v3_card_07 可以使用

    def test_v3_card_07_has_gtm_strategy(self):
        """v3_card_07 should use gtm_strategy (the replacement for gtm_motion)."""
        config = self.db_cards.get("v3_card_07")
        self.assertIsNotNone(config, "v3_card_07 not found in DB")
        fields = config.get("fields", [])
        self.assertIn("gtm_strategy", fields,
                      "gtm_strategy should be in v3_card_07 (replaces deprecated gtm_motion)")

    def test_v4_storyline_contract_and_db_defaults_match(self):
        """v4 story-line card set should have a v3-style cover plus 6 story cards."""
        v4_json_path = ROOT / "contracts" / "card_sets" / "v4.json"
        with open(v4_json_path) as f:
            v4_data = json.load(f)

        self.assertEqual(v4_data["card_set"], "v4")
        self.assertEqual(len(v4_data["cards"]), 7)

        v3_cover = self.v3_cards["v3_card_01"]
        v4_cover = v4_data["cards"][0]
        self.assertEqual(v4_cover["card_id"], "v4_card_01")
        self.assertEqual(v4_cover["fields"], v3_cover["fields"])
        self.assertEqual(v4_cover["media"], v3_cover["media"])

        v4_market_entry = v4_data["cards"][1]
        self.assertEqual(v4_market_entry["card_id"], "v4_card_02")
        self.assertEqual(v4_market_entry["title"], "赛道切口")
        self.assertEqual(
            v4_market_entry["fields"],
            [
                "market_track",
                "market_subtrack",
                "market_landscape_summary",
                "market_landscape_top_players",
                "market_size_value",
                "market_size_currency",
                "market_size_year",
                "market_cagr",
                "tam_value",
                "tam_currency",
                "tam_year",
                "market_opportunity",
                "company_def",
            ],
        )

        v4_company_case = v4_data["cards"][2]
        self.assertEqual(v4_company_case["card_id"], "v4_card_03")
        self.assertEqual(v4_company_case["title"], "公司基本面")
        self.assertEqual(
            v4_company_case["fields"],
            [
                "main_product_name",
                "founded_date",
                "location",
                "founder_name",
                "founder_bg",
                "founder_achievement",
                "funding_stage",
                "funding_info",
                "company_achievements",
                "team_size",
                "team_highlight",
            ],
        )
        self.assertEqual(v4_company_case["media"], ["founder_photo"])

        v4_product_case = v4_data["cards"][3]
        self.assertEqual(v4_product_case["card_id"], "v4_card_04")
        self.assertNotIn("company_achievements", v4_product_case["fields"])

        field_usage = {}
        media_usage = {}
        for card in v4_data["cards"]:
            for field_key in card.get("fields", []):
                field_usage.setdefault(field_key, []).append(card["card_id"])
            for media_key in card.get("media", []):
                media_usage.setdefault(media_key, []).append(card["card_id"])
        duplicate_fields = {
            key: card_ids for key, card_ids in field_usage.items()
            if len(card_ids) > 1
        }
        duplicate_media = {
            key: card_ids for key, card_ids in media_usage.items()
            if len(card_ids) > 1
        }
        self.assertEqual(duplicate_fields, {})
        self.assertEqual(duplicate_media, {})

        registry = self._load_registry()
        self.assertEqual(registry.get("v4", {}).get("card_count"), 7)
        self.assertEqual(registry.get("v4", {}).get("spec_version"), "v4")

        json_cards = {c["card_id"]: c for c in v4_data["cards"]}
        sql_cards = self._load_sql_cards("v4", "v4_card")
        self.assertEqual(set(json_cards), set(sql_cards))
        for card_id in sorted(json_cards):
            self.assertEqual(
                json_cards[card_id].get("fields", []),
                sql_cards[card_id].get("fields", []),
                f"{card_id} fields differ between v4.json and DB defaults",
            )
            self.assertEqual(
                json_cards[card_id].get("media", []),
                sql_cards[card_id].get("media", []),
                f"{card_id} media differ between v4.json and DB defaults",
            )
        self.assertEqual(
            sql_cards["v4_card_01"].get("template_id"),
            "cover_ai_observation_v4",
        )

    def test_editor_frontend_defaults_to_v4(self):
        """定稿台无 set 参数时应默认打开套卡4。"""
        editor_js = (ROOT / "webapp" / "static" / "js" / "editor.js").read_text()
        editor_html = (ROOT / "webapp" / "templates" / "editor.html").read_text()

        self.assertIn("const DEFAULT_CARD_SET_KEY = 'v4'", editor_js)
        self.assertIn("currentSetKey: DEFAULT_CARD_SET_KEY", editor_js)
        self.assertIn("params.get('set') || DEFAULT_CARD_SET_KEY", editor_js)
        self.assertIn("params.get('set') || 'v4'", editor_html)


    def test_v4_template_ids_exist_in_template_db(self):
        """init_template_db.sql must seed all 7 v4 template_ids for the layout centre."""
        v4_template_ids = [
            "cover_ai_observation_v4",
            "storyline_market_v4",
            "storyline_fundamentals_v4",
            "storyline_product_v4",
            "storyline_moat_v4",
            "storyline_business_model_v4",
            "storyline_growth_v4",
        ]

        template_sql_path = ROOT / "db" / "init_template_db.sql"
        sql_text = template_sql_path.read_text()

        conn = sqlite3.connect(":memory:")
        conn.executescript(sql_text)
        conn.commit()

        rows = conn.execute(
            "SELECT template_id FROM card_templates WHERE is_builtin = 1"
        ).fetchall()
        builtin_ids = {r[0] for r in rows}

        missing = [tid for tid in v4_template_ids if tid not in builtin_ids]
        self.assertEqual(
            missing, [],
            f"v4 template_ids missing from init_template_db.sql: {missing}. "
            f"Found builtin templates: {sorted(builtin_ids)}",
        )

        row = conn.execute(
            "SELECT template_name, canvas_width, canvas_height, template_json "
            "FROM card_templates WHERE template_id='cover_ai_observation_v4'"
        ).fetchone()
        self.assertIsNotNone(row)
        template_json = json.loads(row[3])
        self.assertEqual(row[0], "各赛道AI初创公司观察封面（v4）")
        self.assertEqual((row[1], row[2]), (900, 1200))
        self.assertEqual(template_json["style_defaults"]["skin"], "ai_observation_cover")
        self.assertIn("各赛道AI初创公司观察之", row[3])
        self.assertIn("film_grain", row[3])

        conn.close()


if __name__ == "__main__":
    unittest.main()
