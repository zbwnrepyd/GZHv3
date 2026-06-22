"""SPEC: 行业基准系统 — LTV/CAC/留存等私有指标的估算和基准值

设计原则:
  1. 基准值必须标注来源和不代表公司披露的声明
  2. 支持按公司类型/阶段的细分基准
  3. 提供公式推算函数（LTV, CAC 等）
  4. 所有基准输出 confidence_level="benchmark"

测试覆盖:
  1. SaaS/B2B/消费级 分类基准
  2. LTV 估算公式
  3. CAC 估算公式
  4. 留存率行业基准
  5. 基准值输出格式（含 disclaimer）
"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))


# Test the module that will be created
class TestIndustryBenchmarks(unittest.TestCase):
    """行业基准数据完整性验证"""

    @classmethod
    def setUpClass(cls):
        # Import with aliases to avoid bound-method issues in class context
        import research.industry_benchmarks as _mod
        cls._mod = _mod
        cls.BENCHMARKS = _mod.BENCHMARKS

    # Convenience wrappers that avoid bound-method issues
    def _get_benchmark(self, category, metric_key):
        return self._mod.get_benchmark(category, metric_key)

    def _get_retention_benchmark(self, company_type="saas"):
        return self._mod.get_retention_benchmark(company_type)

    def _get_ltv_cac_benchmark(self, company_type="saas", stage="default"):
        return self._mod.get_ltv_cac_benchmark(company_type, stage)

    def _estimate_ltv(self, **kwargs):
        return self._mod.estimate_ltv(**kwargs)

    # ── 基准数据结构 ──
    def test_benchmarks_dict_has_required_sections(self):
        """基准数据必须包含 SaaS / B2B / Consumer 三个章节"""
        self.assertIn("saas", self.BENCHMARKS)
        self.assertIn("b2b", self.BENCHMARKS)
        self.assertIn("consumer", self.BENCHMARKS)

    def test_saas_benchmarks_have_key_metrics(self):
        """SaaS 基准包含核心指标"""
        saas = self.BENCHMARKS["saas"]
        required = ["retention_month1", "retention_month12", "churn_monthly",
                     "ltv_cac_ratio", "gross_margin", "cac_range"]
        for key in required:
            self.assertIn(key, saas, f"SaaS benchmarks missing {key}")

    def test_b2b_benchmarks_have_key_metrics(self):
        """B2B 企业服务基准包含核心指标"""
        b2b = self.BENCHMARKS["b2b"]
        required = ["retention_annual", "ltv_cac_ratio", "gross_margin"]
        for key in required:
            self.assertIn(key, b2b, f"B2B benchmarks missing {key}")

    def test_consumer_benchmarks_have_key_metrics(self):
        """消费级产品基准包含核心指标"""
        consumer = self.BENCHMARKS["consumer"]
        required = ["retention_month1", "retention_month12", "ltv_cac_ratio"]
        for key in required:
            self.assertIn(key, consumer, f"Consumer benchmarks missing {key}")

    def test_all_benchmarks_have_source_and_year(self):
        """所有基准条目必须有 source 和 year（跳过嵌套分阶段条目如 ltv_cac_ratio）"""
        for category, metrics in self.BENCHMARKS.items():
            for key, entry in metrics.items():
                if not isinstance(entry, dict):
                    continue
                # ltv_cac_ratio 是嵌套的分阶段字典，内部条目单独检查
                if key == "ltv_cac_ratio":
                    for stage, stage_entry in entry.items():
                        with self.subTest(category=category, metric=key, stage=stage):
                            self.assertIn("source", stage_entry,
                                          f"{category}.{key}.{stage} missing source")
                            self.assertIn("year", stage_entry,
                                          f"{category}.{key}.{stage} missing year")
                else:
                    with self.subTest(category=category, metric=key):
                        self.assertIn("source", entry,
                                      f"{category}.{key} missing source")
                        self.assertIn("year", entry,
                                      f"{category}.{key} missing year")

    # ── get_benchmark 函数 ──
    def test_get_benchmark_returns_value_and_disclaimer(self):
        """get_benchmark 返回 value, source, disclaimer"""
        result = self._get_benchmark("saas", "retention_month1")
        self.assertIn("value", result)
        self.assertIn("source", result)
        self.assertIn("disclaimer", result)
        self.assertIn("不代表公司披露", result["disclaimer"])

    def test_get_benchmark_saas_retention_month1(self):
        """SaaS Month-1 留存基准 ~60-80%"""
        result = self._get_benchmark("saas", "retention_month1")
        self.assertIsNotNone(result["value"])
        # Should be a range or value
        self.assertTrue(isinstance(result["value"], (int, float, str)))

    def test_get_benchmark_unknown_category_returns_none(self):
        """未知品类返回 None"""
        result = self._get_benchmark("nonexistent", "retention_month1")
        self.assertIsNone(result.get("value"))

    def test_get_benchmark_unknown_metric_returns_none(self):
        """未知指标返回 None"""
        result = self._get_benchmark("saas", "nonexistent_metric")
        self.assertIsNone(result.get("value"))

    # ── 留存率基准 ──
    def test_get_retention_benchmark_saas(self):
        """SaaS 留存率基准"""
        result = self._get_retention_benchmark("saas")
        self.assertIsNotNone(result["value"])
        self.assertEqual(result["confidence_level"], "benchmark")

    def test_get_retention_benchmark_consumer(self):
        """消费级留存率基准 (更低)"""
        result = self._get_retention_benchmark("consumer")
        self.assertIsNotNone(result["value"])
        self.assertEqual(result["confidence_level"], "benchmark")

    def test_get_retention_benchmark_unknown_type(self):
        """未知公司类型默认使用 SaaS 基准"""
        result = self._get_retention_benchmark("unknown")
        self.assertIsNotNone(result["value"])
        self.assertEqual(result["confidence_level"], "benchmark")

    # ── LTV/CAC 基准 ──
    def test_get_ltv_cac_benchmark_saas(self):
        """SaaS LTV/CAC 基准 ~3x"""
        result = self._get_ltv_cac_benchmark("saas", "series_a")
        self.assertIsNotNone(result["value"])
        self.assertEqual(result["confidence_level"], "benchmark")
        self.assertIn("source", result)

    def test_get_ltv_cac_benchmark_seed_stage(self):
        """种子轮 LTV/CAC 基准更保守"""
        result_seed = self._get_ltv_cac_benchmark("saas", "seed")
        result_series_c = self._get_ltv_cac_benchmark("saas", "series_c_plus")
        self.assertIsNotNone(result_seed["value"])
        self.assertIsNotNone(result_series_c["value"])

    def test_get_ltv_cac_benchmark_default_stage(self):
        """未知融资阶段使用中位基准"""
        result = self._get_ltv_cac_benchmark("saas", "unknown")
        self.assertIsNotNone(result["value"])

    # ── LTV 估算公式 ──
    def test_estimate_ltv_basic(self):
        """LTV ≈ 月均收入 × 平均生命周期月数"""
        # 月定价 $50, 月流失率 5% → 平均生命周期 20 月 → LTV ≈ $1000
        result = self._estimate_ltv(monthly_price=50, monthly_churn_rate=0.05)
        self.assertAlmostEqual(result["ltv"], 1000.0, delta=10)
        self.assertEqual(result["confidence_level"], "estimated")
        self.assertIn("formula", result)

    def test_estimate_ltv_with_annual_pricing(self):
        """年付 $600 → 月均 $50"""
        result = self._estimate_ltv(annual_price=600, monthly_churn_rate=0.05)
        self.assertAlmostEqual(result["ltv"], 1000.0, delta=10)

    def test_estimate_ltv_no_pricing_returns_none(self):
        """无定价信息 → LTV 无法估算"""
        result = self._estimate_ltv(monthly_churn_rate=0.05)
        self.assertIsNone(result["ltv"])
        self.assertEqual(result["confidence_level"], "unavailable")
        self.assertIn("reason", result)

    def test_estimate_ltv_no_churn_uses_benchmark(self):
        """无流失率 → 使用行业基准流失率"""
        result = self._estimate_ltv(monthly_price=50, company_type="saas")
        self.assertIsNotNone(result["ltv"])
        self.assertEqual(result["confidence_level"], "estimated")
        self.assertIn("assumed_churn_rate", result)

    def test_estimate_ltv_result_has_disclaimer(self):
        """估算结果包含 disclaimer"""
        result = self._estimate_ltv(monthly_price=50, monthly_churn_rate=0.05)
        self.assertIn("disclaimer", result)
        self.assertIn("公式推算", result["disclaimer"])

    # ── CAC 估算 ──
    def test_cac_benchmark_by_type(self):
        """不同品类的 CAC 基准区间"""
        saas_cac = self._get_benchmark("saas", "cac_range")
        b2b_cac = self._get_benchmark("b2b", "cac_range")
        consumer_cac = self._get_benchmark("consumer", "cac_range")

        for name, result in [("saas", saas_cac), ("b2b", b2b_cac), ("consumer", consumer_cac)]:
            with self.subTest(category=name):
                self.assertIsNotNone(result.get("value"), f"{name} CAC benchmark missing")
                self.assertIn("disclaimer", result)

    # ── 基准值不泄露为 confirmed ──
    def test_benchmark_confidence_level_is_never_verified(self):
        """所有基准值 confidence_level 永不为 verified"""
        benchmark_funcs = [
            lambda: self._get_benchmark("saas", "retention_month1"),
            lambda: self._get_retention_benchmark("saas"),
            lambda: self._get_ltv_cac_benchmark("saas", "series_a"),
        ]
        for fn in benchmark_funcs:
            result = fn()
            with self.subTest():
                self.assertNotEqual(result.get("confidence_level"), "verified",
                                    "Benchmark values must NEVER have confidence_level=verified")
                self.assertIn(result.get("confidence_level", ""),
                              ["estimated", "benchmark", "unavailable"])


if __name__ == "__main__":
    unittest.main()
