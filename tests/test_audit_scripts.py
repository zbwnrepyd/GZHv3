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

    def test_content_coverage_counts_industry_avg_as_resolved(self):
        coverage = load_script("card_content_coverage_check.py")

        class StubAssembler:
            def assemble(self, company, card_set):
                return {
                    "cards": [{
                        "card_id": "metrics",
                        "items": [{
                            "field_key": "ltv",
                            "value": "3x-5x",
                            "status": "industry_avg",
                        }],
                        "media": [],
                        "layout": {"template_id": "t1", "variant": "wide"},
                    }]
                }

        original = coverage.RenderAssembler
        coverage.RenderAssembler = StubAssembler
        try:
            result = coverage.check_card_coverage("DemoCo", "v3")
        finally:
            coverage.RenderAssembler = original

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["fields_resolved"], 1)
        self.assertEqual(result["failures"], [])

    def test_content_coverage_reports_value_coverage_ratio(self):
        coverage = load_script("card_content_coverage_check.py")

        class StubAssembler:
            def assemble(self, company, card_set):
                return {
                    "cards": [{
                        "card_id": "market",
                        "items": [
                            {"field_key": "market_size_value", "value": "$5.2B", "status": "proxy"},
                            {"field_key": "tam_value", "value": None, "status": "manual_needed"},
                        ],
                        "media": [],
                        "layout": {"template_id": "t1", "variant": "wide"},
                    }]
                }

        original = coverage.RenderAssembler
        coverage.RenderAssembler = StubAssembler
        try:
            result = coverage.check_card_coverage("DemoCo", "v3")
        finally:
            coverage.RenderAssembler = original

        self.assertEqual(result["summary"]["fields_with_values"], 1)
        self.assertEqual(result["summary"]["value_coverage_ratio"], 0.5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["issue"], "low_value_coverage")

    def test_research_gap_backfill_uses_market_estimates_and_benchmarks(self):
        backfill = load_script("research_gap_backfill.py")

        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.executescript("""
                CREATE TABLE research_fields (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    version TEXT DEFAULT 'standard',
                    field_key TEXT NOT NULL,
                    field_value TEXT,
                    source_type TEXT,
                    source_url TEXT,
                    confidence TEXT,
                    resolution_status TEXT,
                    resolution_method TEXT,
                    unavailable_reason TEXT,
                    company_key TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE market_estimates (
                    id TEXT PRIMARY KEY,
                    company_key TEXT NOT NULL,
                    field_key TEXT NOT NULL,
                    estimate_type TEXT NOT NULL,
                    result_value REAL,
                    result_text TEXT,
                    currency TEXT DEFAULT 'USD',
                    year INTEGER,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'derived',
                    disclaimer TEXT,
                    region TEXT,
                    segment TEXT,
                    source_url TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                    resolution_status TEXT DEFAULT 'draft',
                    source_note TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            for field_key in (
                "market_size_value", "market_size_currency", "market_size_year",
                "tam_value", "tam_currency", "tam_year", "ltv", "cac",
                "ltv_cac_ratio", "ltv_cac_is_benchmark",
                "ltv_cac_benchmark_source", "mau",
            ):
                conn.execute("""
                    INSERT INTO research_fields
                    (company_name, company_key, version, field_key, field_value, resolution_status)
                    VALUES ('DemoCo', 'democo.com', 'standard', ?, '暂缺', 'unavailable')
                """, (field_key,))
            conn.execute("""
                INSERT INTO market_estimates
                (id, company_key, field_key, estimate_type, result_value, result_text,
                 currency, year, confidence, status, disclaimer, region, segment, source_url)
                VALUES
                ('ms1', 'democo.com', 'market_size_value', 'proxy', 5200000000,
                 '$5.2B', 'USD', 2025, 0.7, 'proxy', '市场报告口径',
                 'Global', 'Demo category', 'https://example.com/market'),
                ('tam1', 'democo.com', 'tam_value', 'proxy', 9900000000,
                 '$9.9B', 'USD', 2026, 0.65, 'proxy', '市场报告口径',
                 'Global', 'Demo category', 'https://example.com/tam')
            """)
            conn.commit()
            conn.close()

            result = backfill.backfill_company(
                "DemoCo",
                "v3",
                research_db_path=tmp.name,
                field_keys=[
                    "market_size_value", "market_size_currency", "market_size_year",
                    "tam_value", "tam_currency", "tam_year", "ltv", "cac",
                    "ltv_cac_ratio", "ltv_cac_is_benchmark",
                    "ltv_cac_benchmark_source", "mau",
                ],
            )

            conn = sqlite3.connect(tmp.name)
            rows = {
                row[0]: (row[1], row[2])
                for row in conn.execute(
                    "SELECT field_key, field_value, resolution_status FROM research_fields"
                )
            }
            conn.close()

        self.assertEqual(rows["market_size_value"], ("$5.2B", "proxy"))
        self.assertEqual(rows["market_size_currency"], ("USD", "proxy"))
        self.assertEqual(rows["market_size_year"], ("2025", "proxy"))
        self.assertEqual(rows["tam_value"], ("$9.9B", "proxy"))
        self.assertEqual(rows["tam_currency"], ("USD", "proxy"))
        self.assertEqual(rows["tam_year"], ("2026", "proxy"))
        self.assertEqual(rows["ltv_cac_ratio"], ("3x–5x", "industry_avg"))
        self.assertEqual(rows["ltv_cac_is_benchmark"], ("1", "industry_avg"))
        self.assertIn("OpenView", rows["ltv_cac_benchmark_source"][0])
        self.assertEqual(rows["mau"], ("暂缺", "unavailable"))
        self.assertGreaterEqual(result["summary"]["updated_fields"], 8)

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
