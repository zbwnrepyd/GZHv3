import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))


class DeepResearchReportToolTests(unittest.TestCase):
    def test_external_tool_adapters_skip_without_credentials(self):
        from tool_adapters import (
            wappalyzer_lookup, similarweb_traffic,
            semrush_domain_overview, openbb_dataset_stub, crawl4ai_extract_stub,
        )

        for result in (
            wappalyzer_lookup("https://example.com", api_key=""),
            similarweb_traffic("example.com", api_key=""),
            semrush_domain_overview("example.com", api_key=""),
            openbb_dataset_stub("example.com"),
            crawl4ai_extract_stub("https://example.com"),
        ):
            self.assertEqual(result["status"], "skipped")
            self.assertIn("source_family", result)

    def test_metric_formulas_are_explicit_and_benchmark_is_not_company_fact(self):
        from metrics import calculate_cagr, calculate_ltv_cac, ltv_cac_benchmark

        self.assertAlmostEqual(calculate_cagr(100, 200, 4), 18.9207115, places=4)
        self.assertEqual(calculate_ltv_cac(240, 80), 3.0)
        benchmark = ltv_cac_benchmark("b2b_saas_seed", source="Seed benchmark")
        self.assertEqual(benchmark["ltv_cac_ratio"], 3.0)
        self.assertEqual(benchmark["ltv_cac_is_benchmark"], 1)
        self.assertIn("非公司披露值", benchmark["note"])

    def test_robots_helper_returns_auditable_status(self):
        from source_fetchers import robots_allowed

        result = robots_allowed("https://example.com/path", robots_txt="User-agent: *\nDisallow: /private\n")

        self.assertTrue(result["allowed"])
        self.assertEqual(result["robots_status"], "allowed")


if __name__ == "__main__":
    unittest.main()
