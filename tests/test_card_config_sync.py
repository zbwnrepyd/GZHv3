"""Test v3 card config sync between v3.json and DB."""
import json
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
        cls.db_cards = {}
        with open(cls.sql_path) as f:
            content = f.read()
        import re
        for match in re.finditer(
            r"\('v3','(v3_card_\d+)',\d+,'[^']*','(\{[^}]*\})'\)",
            content
        ):
            card_id = match.group(1)
            config = json.loads(match.group(2))
            cls.db_cards[card_id] = config

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


if __name__ == "__main__":
    unittest.main()
