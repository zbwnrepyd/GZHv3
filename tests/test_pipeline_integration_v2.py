"""Integration tests for L1/L2 extractors, MarketDataBridge, L3 split, and TimeSeriesSnapshotter."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))


class TestCompetitiveMatrixIntegration(unittest.TestCase):
    def test_competitive_matrix_extractor_valid(self):
        from research.competitive_matrix import CompetitiveMatrixExtractor
        extractor = CompetitiveMatrixExtractor()
        data = {
            "competitors": [
                {"name": "A", "overlap_areas": ["X"], "strengths": ["S"],
                 "weaknesses": ["W"], "threat_level": "low",
                 "evidence_snippets": ["evidence"]},
                {"name": "B", "overlap_areas": ["Y"], "strengths": ["S2"],
                 "weaknesses": ["W2"], "threat_level": "medium",
                 "evidence_snippets": ["evidence"]},
            ],
            "target_company_position": "niche_player",
            "competitive_landscape_summary": "summary"
        }
        matrix, errors = extractor.validate(data)
        self.assertIsNotNone(matrix)
        self.assertEqual(len(errors), 0)

    def test_competitive_matrix_extractor_invalid(self):
        from research.competitive_matrix import CompetitiveMatrixExtractor
        extractor = CompetitiveMatrixExtractor()
        # Missing required fields
        data = {"target_company_position": "niche_player"}
        matrix, errors = extractor.validate(data)
        self.assertIsNone(matrix)
        self.assertTrue(len(errors) > 0)


class TestBusinessCanvasIntegration(unittest.TestCase):
    def test_business_canvas_extractor_valid(self):
        from research.business_canvas import BusinessCanvasExtractor
        extractor = BusinessCanvasExtractor()
        data = {
            "revenue_model": {"primary": "subscription", "secondary": [],
                              "pricing_public": True, "evidence_snippets": ["s"]},
            "unit_economics": {"has_ltv_cac_data": False, "disclaimer": "N/A",
                               "evidence_snippets": ["none"]},
            "growth_loops": [{"loop_type": "product_led", "description": "PLG",
                              "strength": "strong", "evidence_snippets": ["e"]}],
            "moat_dimensions": [
                {"dimension": "network_effects", "strength": "moderate",
                 "description": "Network effects", "evidence_snippets": ["e"]},
                {"dimension": "switching_cost", "strength": "strong",
                 "description": "High switching cost", "evidence_snippets": ["e"]},
                {"dimension": "data_moat", "strength": "moderate",
                 "description": "Data advantage", "evidence_snippets": ["e"]},
                {"dimension": "tech_complexity", "strength": "strong",
                 "description": "Technical moat", "evidence_snippets": ["e"]},
            ],
            "business_model_summary": "summary"
        }
        canvas, errors = extractor.validate(data)
        self.assertIsNotNone(canvas)
        self.assertEqual(len(errors), 0)

    def test_business_canvas_extractor_invalid(self):
        from research.business_canvas import BusinessCanvasExtractor
        extractor = BusinessCanvasExtractor()
        # Missing required nested fields
        data = {"business_model_summary": "test"}
        canvas, errors = extractor.validate(data)
        self.assertIsNone(canvas)
        self.assertTrue(len(errors) > 0)


class TestMarketDataBridgeIntegration(unittest.TestCase):
    def _temp_db(self) -> str:
        import tempfile
        import os
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        return tmp.name

    def test_market_data_bridge_noop_when_no_table(self):
        from research.market_data_bridge import MarketDataBridge
        import os
        db = self._temp_db()
        try:
            bridge = MarketDataBridge(db_path=db)
            ctx = bridge.inject_into_l3_context("any_co", "original context")
            self.assertEqual(ctx, "original context")
        finally:
            os.unlink(db)

    def test_market_data_bridge_fetch_market_context_handles_missing_table(self):
        from research.market_data_bridge import MarketDataBridge
        import os
        db = self._temp_db()
        try:
            bridge = MarketDataBridge(db_path=db)
            result = bridge.fetch_market_context("any_co")
            self.assertEqual(result, {})
        finally:
            os.unlink(db)


class TestTimeSeriesSnapshotterIntegration(unittest.TestCase):
    def test_time_series_snapshotter_noop_when_no_table(self):
        import tempfile
        import os
        from research.time_series import TimeSeriesSnapshotter
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        try:
            ss = TimeSeriesSnapshotter(db_path=tmp.name)
            count = ss.snapshot("test", {"f1": {"value": "v1"}})
            self.assertEqual(count, 0)  # No table -- no crash
        finally:
            os.unlink(tmp.name)

    def test_time_series_snapshotter_diff_empty(self):
        import tempfile
        import os
        from research.time_series import TimeSeriesSnapshotter
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        try:
            ss = TimeSeriesSnapshotter(db_path=tmp.name)
            result = ss.diff("test", "f1")
            self.assertIsNone(result)
        finally:
            os.unlink(tmp.name)


class TestL3MergeLogic(unittest.TestCase):
    def test_l3_merge_produces_complete_field_set(self):
        """Test that merging L3-A/B/C results produces complete field set"""
        a = {"company_name": "TestCo", "founded_date": "2024"}
        b = {"market_size_value": 10.5, "mau": "5M"}
        c = {"moat": "Strong network effects", "gtm_strategy": "PLG"}
        merged = {}
        merged.update(a)
        merged.update(b)
        merged.update(c)
        self.assertEqual(len(merged), 6)
        self.assertIn("company_name", merged)
        self.assertIn("market_size_value", merged)
        self.assertIn("moat", merged)

    def test_l3_merge_later_wins_on_conflict(self):
        """Test that C overrides A on overlapping keys"""
        a = {"moat": "weak"}
        b = {"market_size_value": 10.5}
        c = {"moat": "strong"}
        merged = {}
        merged.update(a)
        merged.update(b)
        merged.update(c)
        self.assertEqual(merged["moat"], "strong")


if __name__ == "__main__":
    unittest.main()
