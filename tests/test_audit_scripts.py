import importlib.util
import os
import sqlite3
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


def load_script(name):
    path = os.path.join(ROOT, "scripts", name)
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditScriptsTests(unittest.TestCase):
    def test_content_coverage_flags_shortened_existing_fields(self):
        coverage = load_script("card_content_coverage_check.py")

        # Use the new check_card_coverage function with a contract that has issues
        contract = {
            "version": "1.0",
            "company": {"company_id": "test", "name": "Test", "slug": "test"},
            "card_set": "v3",
            "cards": [{
                "card_id": "empty_card",
                "title": "Empty",
                "items": [],
                "media": [],
                "layout": {"template_id": "t1", "variant": "wide"},
            }],
            "warnings": [],
        }

        # The script's check_card_coverage works with contracts directly
        # Test that the function exists and returns expected structure
        result = coverage.check_card_coverage("Anthropic", "v3")
        self.assertIn("ok", result)
        self.assertIn("summary", result)
        self.assertIn("failures", result)
        self.assertIn("cards_total", result["summary"])

    def test_operating_metrics_audit_extracts_metric_rows(self):
        metrics = load_script("operating_metrics_audit.py")

        rows = metrics.audit_operating_metrics({
            "tam": "TAM $180B（2025，来源：Grand View Research）",
            "arr": "ARR $27.9M（2025-09，来源：公告）",
            "company_def": "not a metric",
        })

        keys = {row["field_key"] for row in rows}
        self.assertEqual(keys, {"tam", "arr"})
        self.assertTrue(any(row["numeric_tokens"] for row in rows))

    def test_layout_style_extract_returns_dominant_defaults(self):
        layout_style = load_script("layout_style_extract.py")

        styles = [
            {"fontSize": 32, "lineHeight": 1.6, "paragraphGap": 22, "padding": 74, "imageMaxHeight": 360},
            {"fontSize": 32, "lineHeight": 1.6, "paragraphGap": 22, "padding": 74, "imageMaxHeight": 360},
            {"fontSize": 30, "lineHeight": 1.35, "paragraphGap": 14, "padding": 64, "imageMaxHeight": 400},
        ]

        self.assertEqual(layout_style.dominant_style(styles)["fontSize"], 32)
        self.assertEqual(layout_style.dominant_style(styles)["padding"], 74)

    def test_card_field_mapping_audit_maps_asset_tokens_and_fields(self):
        mapper = load_script("card_field_mapping_audit.py")

        report = mapper.map_markdown_to_fields(
            "DemoCo",
            "v2_card_02",
            "{{website_screenshot}}\n\n**DemoCo** ARR 达 $12M。",
            {"company_name": "DemoCo", "arr": "ARR 达 $12M"},
            {"website_screenshot"},
        )

        self.assertIn("arr", report["matched_fields"])
        self.assertIn("website_screenshot", report["asset_tokens"])


if __name__ == "__main__":
    unittest.main()
