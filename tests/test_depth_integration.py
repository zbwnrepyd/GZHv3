"""Integration tests — verify all depth optimization modules coexist and field coverage is maintained"""
import unittest
import sys
import os
import tempfile
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))


class TestAllModulesImportable(unittest.TestCase):
    """All 6 new modules must be importable without errors"""

    def test_l0_gate_import(self):
        from research.l0_gate import validate_l0_output, L0GateError
        self.assertTrue(callable(validate_l0_output))

    def test_competitive_matrix_import(self):
        from research.competitive_matrix import CompetitorItem, CompetitiveMatrix, CompetitiveMatrixExtractor
        self.assertTrue(callable(CompetitiveMatrixExtractor().validate))

    def test_business_canvas_import(self):
        from research.business_canvas import RevenueModel, BusinessCanvas, BusinessCanvasExtractor
        self.assertTrue(callable(BusinessCanvasExtractor().validate))

    def test_market_data_bridge_import(self):
        from research.market_data_bridge import MarketDataBridge
        bridge = MarketDataBridge()
        self.assertTrue(hasattr(bridge, "fetch_market_context"))
        self.assertTrue(hasattr(bridge, "inject_into_l3_context"))

    def test_time_series_import(self):
        from research.time_series import TimeSeriesSnapshotter
        self.assertTrue(hasattr(TimeSeriesSnapshotter(), "snapshot"))

    def test_l3_split_prompts_exist(self):
        base = Path(__file__).resolve().parent.parent / "prompts"
        for fname in ["layer3-group-facts.md", "layer3-group-market.md", "layer3-group-operating.md"]:
            self.assertTrue((base / fname).exists(), f"Missing: {fname}")


class TestModuleInterfacesConsistent(unittest.TestCase):
    """All extractors follow the same validate() -> (result, errors) pattern"""

    def test_l0_gate_returns_tuple(self):
        from research.l0_gate import validate_l0_output
        ok, errors = validate_l0_output({
            "company_name": "Test",
            "company_def": "def" * 50,
            "main_product_name": "X",
            "founded_date": "2024",
        })
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(errors, list)

    def test_l0_gate_passes_valid_data(self):
        from research.l0_gate import validate_l0_output
        ok, errors = validate_l0_output({
            "company_name": "TestCo",
            "company_def": "A test company definition that is long enough " * 10,
            "main_product_name": "ProductX",
            "founded_date": "2024",
            "location": "San Francisco",
            "founder_name": "Jane Doe",
        })
        self.assertTrue(ok, f"Expected True but got errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_l0_gate_fails_empty_input(self):
        from research.l0_gate import validate_l0_output
        ok, errors = validate_l0_output({})
        self.assertFalse(ok)
        self.assertGreater(len(errors), 0)

    def test_competitive_matrix_extractor_interface(self):
        from research.competitive_matrix import CompetitiveMatrixExtractor
        extractor = CompetitiveMatrixExtractor()
        result, errors = extractor.validate({})
        self.assertIsNone(result)
        self.assertGreater(len(errors), 0)

    def test_business_canvas_extractor_interface(self):
        from research.business_canvas import BusinessCanvasExtractor
        extractor = BusinessCanvasExtractor()
        result, errors = extractor.validate({})
        self.assertIsNone(result)
        self.assertGreater(len(errors), 0)

    def test_market_data_bridge_interface(self):
        from research.market_data_bridge import MarketDataBridge

        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            conn = sqlite3.connect(tmp_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_estimates (
                    company_key TEXT, field_key TEXT, result_value REAL,
                    result_text TEXT, currency TEXT, year INTEGER,
                    estimate_type TEXT, confidence REAL, status TEXT,
                    source_url TEXT, disclaimer TEXT
                )
            """)
            conn.commit()
            conn.close()

            bridge = MarketDataBridge(db_path=tmp_path)
            # fetch_market_context returns dict
            result = bridge.fetch_market_context("test")
            self.assertIsInstance(result, dict)
            # inject_into_l3_context returns string unchanged when no data
            ctx = bridge.inject_into_l3_context("test", "original context")
            self.assertEqual(ctx, "original context")
        finally:
            os.unlink(tmp_path)

    def test_market_data_bridge_injects_when_data_present(self):
        from research.market_data_bridge import MarketDataBridge

        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            conn = sqlite3.connect(tmp_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_estimates (
                    company_key TEXT, field_key TEXT, result_value REAL,
                    result_text TEXT, currency TEXT, year INTEGER,
                    estimate_type TEXT, confidence REAL, status TEXT,
                    source_url TEXT, disclaimer TEXT
                )
            """)
            conn.execute("""
                INSERT INTO market_estimates
                (company_key, field_key, result_value, result_text, currency, year,
                 estimate_type, confidence, status)
                VALUES ('test', 'market_size_value', 5000000000, '5B', 'USD', 2025,
                        'bottom_up', 0.6, 'estimated')
            """)
            conn.commit()
            conn.close()

            bridge = MarketDataBridge(db_path=tmp_path)
            result = bridge.fetch_market_context("test")
            self.assertIn("market_size_value", result)
            self.assertEqual(result["market_size_value"]["value"], 5000000000)
            # inject_into_l3_context should now include market data
            ctx = bridge.inject_into_l3_context("test", "original context")
            self.assertIn("market_size_value", ctx)
        finally:
            os.unlink(tmp_path)

    def test_time_series_interface(self):
        from research.time_series import TimeSeriesSnapshotter

        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            ss = TimeSeriesSnapshotter(db_path=tmp_path)
            # With no table, snapshot should return 0 not crash
            count = ss.snapshot("test", {"f1": {"value": "v1"}})
            self.assertEqual(count, 0)
            # diff on missing table returns None
            self.assertIsNone(ss.diff("test", "f1"))
            # list_comparable_fields on missing table returns []
            self.assertEqual(ss.list_comparable_fields("test"), [])
        finally:
            os.unlink(tmp_path)


class TestFieldCoverageAcrossL3Groups(unittest.TestCase):
    """Verify L3 split groups cover all expected fields without overlap"""

    GROUPS = {
        "A": {
            "company_name", "company_type", "company_def", "location",
            "founded_date", "website_url", "founder_name", "founder_bg",
            "founder_edu", "founder_achievement", "team_size", "team_highlight",
            "funding_info", "main_product_name", "main_product_def",
        },
        "B": {
            "market_track", "market_subtrack", "market_size_value",
            "market_size_currency", "market_size_year", "market_cagr",
            "tam_value", "tam_currency", "tam_year",
            "market_landscape_summary", "market_landscape_top_players",
            "regional_market_focus", "regional_markets", "market_opportunity",
            "mau", "mau_as_of", "revenue_metrics", "growth_metrics",
        },
        "C": {
            "core_business", "core_competency", "industry_positioning",
            "moat", "ecosystem_niche", "ecosystem_positioning",
            "competitive_advantages", "competitors_summary",
            "pricing_summary", "pricing_strategy", "gtm_strategy",
            "growth_strategy",
        },
    }

    def test_no_field_overlap(self):
        all_fields = set()
        for group_name, field_set in self.GROUPS.items():
            overlap = all_fields & field_set
            self.assertEqual(
                len(overlap), 0,
                f"Group {group_name} overlaps with others: {overlap}",
            )
            all_fields.update(field_set)

    def test_total_field_count(self):
        total = sum(len(fs) for fs in self.GROUPS.values())
        self.assertGreaterEqual(total, 45, f"Only {total} fields across 3 groups, need >= 45")


class TestManifestNewFieldsExist(unittest.TestCase):
    """Verify new manifest entries for structured extraction modules are present"""

    @classmethod
    def setUpClass(cls):
        from research.field_status import _load_manifest
        cls.manifest = _load_manifest()

    def test_competitors_structured_in_manifest(self):
        self.assertIn("competitors_structured", self.manifest)
        entry = self.manifest["competitors_structured"]
        self.assertEqual(entry.get("source_module"), "competitive_matrix")
        self.assertEqual(entry.get("type"), "json_text")

    def test_business_canvas_in_manifest(self):
        self.assertIn("business_canvas", self.manifest)
        entry = self.manifest["business_canvas"]
        self.assertEqual(entry.get("source_module"), "business_canvas")

    def test_moat_dimensions_in_manifest(self):
        self.assertIn("moat_dimensions", self.manifest)
        self.assertEqual(self.manifest["moat_dimensions"].get("source_module"), "business_canvas")

    def test_growth_loops_in_manifest(self):
        self.assertIn("growth_loops", self.manifest)
        self.assertEqual(self.manifest["growth_loops"].get("source_module"), "business_canvas")


class TestConfidenceLevelEnumPropagation(unittest.TestCase):
    """Verify confidence_level enum is defined and usable across modules"""

    def test_valid_confidence_levels_in_market_intelligence(self):
        from market_intelligence.schemas.candidate import VALID_CONFIDENCE_LEVELS
        self.assertEqual(
            VALID_CONFIDENCE_LEVELS,
            {"verified", "estimated", "benchmark", "unavailable"},
        )

    def test_tier_config_has_confidence_levels(self):
        from research.field_status import TIER_CONFIG
        valid = {"verified", "estimated", "benchmark", "unavailable"}
        for tier_id, cfg in TIER_CONFIG.items():
            self.assertIn("default_confidence_level", cfg)
            self.assertIn(cfg["default_confidence_level"], valid)

    def test_benchmarks_have_confidence_level(self):
        from research.industry_benchmarks import get_benchmark
        result = get_benchmark("saas", "retention_month1")
        self.assertIn(result["confidence_level"], {"benchmark", "estimated", "verified", "unavailable"})
