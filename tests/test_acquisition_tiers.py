"""SPEC: 字段按可获取难度分三类策略

Tier 1 (公开可采集): TAM / 市场规模 — web search + LLM 提取
Tier 2 (代理指标推算): MAU / 用户规模 — proxy metrics
Tier 3 (估算/基准): LTV / CAC / 留存 — estimation formulas or benchmarks
"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.field_status import (
    _load_manifest,
    TIER_CONFIG,
    classify_acquisition_tier,
    get_tier_strategy,
    get_default_confidence_level,
)


class TestAcquisitionTierClassification(unittest.TestCase):
    """验证字段按可获取难度正确分到 Tier 1/2/3"""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()

    # ── Tier 1: 市场规模类 ──
    def test_tier1_market_size_fields(self):
        """市场规模相关字段 → Tier 1"""
        tier1_fields = [
            "market_size_value", "market_size_currency",
            "market_size_year", "market_size_source_note",
            "tam_value", "tam_currency", "tam_year",
            "market_cagr", "tam", "sam", "som",
        ]
        for fk in tier1_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                tier = classify_acquisition_tier(fk, entry)
                self.assertEqual(tier, 1,
                                 f"{fk} should be Tier 1 (公开可采集), got tier={tier}")

    def test_tier1_strategy_includes_web_search(self):
        """Tier 1 策略应包含 web search"""
        cfg = get_tier_strategy(1)
        self.assertIn("web_search", cfg["strategy"])
        self.assertIn("LLM", cfg["strategy"])

    def test_tier1_can_be_verified(self):
        """Tier 1 字段可以达到 verified"""
        cfg = get_tier_strategy(1)
        self.assertTrue(cfg["can_be_verified"])

    def test_tier1_default_confidence_is_estimated(self):
        """Tier 1 默认 confidence_level 为 estimated"""
        cfg = get_tier_strategy(1)
        self.assertEqual(cfg["default_confidence_level"], "estimated")

    # ── Tier 2: 用户规模类 ──
    def test_tier2_user_metric_fields(self):
        """用户/MAU 相关字段 → Tier 2 (仅 D 类私有指标)"""
        # 注意: active_users/registered_users/paying_users 是 E 类 (B2B不适配)
        # 它们不属于 Tier 2 代理指标（基本不可采集）
        tier2_fields = [
            "mau", "mau_as_of",
        ]
        for fk in tier2_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                tier = classify_acquisition_tier(fk, entry)
                self.assertEqual(tier, 2,
                                 f"{fk} should be Tier 2 (代理指标推算), got tier={tier}")

    def test_tier2_strategy_includes_proxy_metrics(self):
        """Tier 2 策略应包含 proxy metrics 描述"""
        cfg = get_tier_strategy(2)
        self.assertIn("proxy", cfg["strategy"].lower())

    def test_tier2_cannot_be_verified(self):
        """Tier 2 proxy 指标永远不能达到 verified"""
        cfg = get_tier_strategy(2)
        self.assertFalse(cfg["can_be_verified"])

    def test_tier2_default_confidence_is_estimated(self):
        """Tier 2 默认 confidence_level 为 estimated"""
        cfg = get_tier_strategy(2)
        self.assertEqual(cfg["default_confidence_level"], "estimated")

    # ── Tier 3: LTV/CAC/留存类 ──
    def test_tier3_financial_metric_fields(self):
        """LTV/CAC/留存 相关 D 类字段 → Tier 3"""
        # 注意: mrr 和 ltv_cac_ratio 是 B 类（公式推导），属于 Tier 1
        tier3_fields = [
            "cac", "ltv", "churn_rate",
            "retention_rate", "gross_margin", "burn_rate",
            "runway_months", "arr",
            "retention_definition",
            "ltv_cac_is_benchmark", "ltv_cac_benchmark_source",
        ]
        for fk in tier3_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                tier = classify_acquisition_tier(fk, entry)
                self.assertEqual(tier, 3,
                                 f"{fk} should be Tier 3 (估算/基准), got tier={tier}")

    def test_tier3_strategy_includes_benchmark(self):
        """Tier 3 策略应包含行业基准描述"""
        cfg = get_tier_strategy(3)
        self.assertIn("benchmark", cfg["strategy"].lower())

    def test_tier3_cannot_be_verified(self):
        """Tier 3 字段永远不能达到 verified"""
        cfg = get_tier_strategy(3)
        self.assertFalse(cfg["can_be_verified"])

    def test_tier3_default_confidence_is_benchmark(self):
        """Tier 3 默认 confidence_level 为 benchmark"""
        cfg = get_tier_strategy(3)
        self.assertEqual(cfg["default_confidence_level"], "benchmark")

    # ── 与现有 category 系统的兼容性 ──
    def test_a_category_fields_are_tier1(self):
        """A 类（直接事实）字段 → Tier 1"""
        a_fields = ["company_name", "location", "founded_date", "founder_name"]
        for fk in a_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                tier = classify_acquisition_tier(fk, entry)
                self.assertEqual(tier, 1,
                                 f"A-category {fk} should be Tier 1")

    def test_b_category_fields_are_tier1(self):
        """B 类（公式计算）字段 → Tier 1（输入已确认时自动 derived）"""
        b_fields = ["mrr", "ltv_cac_ratio"]
        for fk in b_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                tier = classify_acquisition_tier(fk, entry)
                # B category fields default to Tier 1
                self.assertEqual(tier, 1,
                                 f"B-category {fk} should default to Tier 1")

    def test_e_category_fields_are_tier3(self):
        """E 类（B2B 不适配）字段 → Tier 3-like"""
        e_fields = ["active_users", "registered_users", "paying_users"]
        for fk in e_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                tier = classify_acquisition_tier(fk, entry)
                self.assertEqual(tier, 3,
                                 f"E-category {fk} (B2B不适配) should be Tier 3")

    def test_unknown_field_is_tier0(self):
        """完全未知字段 → tier 0"""
        tier = classify_acquisition_tier("nonexistent_field_xyz", {})
        self.assertEqual(tier, 0)

    def test_tier0_default_confidence_is_unavailable(self):
        """未知 tier 默认 confidence_level 为 unavailable"""
        level = get_default_confidence_level("unknown_field", {})
        self.assertEqual(level, "unavailable")

    # ── 集成测试：使用真实 manifest ──
    def test_market_fields_get_estimated_default(self):
        """市场字段使用真实 manifest → confidence_level=estimated"""
        for fk in ["market_size_value", "tam_value", "market_cagr"]:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                level = get_default_confidence_level(fk, entry)
                self.assertEqual(level, "estimated",
                                 f"Market field {fk} default confidence → estimated")

    def test_mau_fields_get_estimated_default(self):
        """MAU 字段使用真实 manifest → confidence_level=estimated"""
        entry = self.manifest.get("mau", {})
        level = get_default_confidence_level("mau", entry)
        self.assertEqual(level, "estimated")

    def test_cac_fields_get_benchmark_default(self):
        """CAC 字段使用真实 manifest → confidence_level=benchmark"""
        for fk in ["cac", "ltv", "retention_rate", "churn_rate"]:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                level = get_default_confidence_level(fk, entry)
                self.assertEqual(level, "benchmark",
                                 f"Financial field {fk} default → benchmark")

    def test_all_manifest_market_fields_tier1(self):
        """所有 C 类市场字段检查 Tier 1"""
        for fk, entry in self.manifest.items():
            if fk == "_default":
                continue
            if entry.get("category") == "C":
                with self.subTest(field=fk):
                    tier = classify_acquisition_tier(fk, entry)
                    self.assertEqual(tier, 1,
                                     f"C-category field {fk} must be Tier 1")

    def test_all_manifest_private_metric_fields_tier2_or_3(self):
        """所有 D 类私有指标字段检查 Tier 2 或 3"""
        tier2_specific = TIER_CONFIG[2]["field_specific"]
        tier3_specific = TIER_CONFIG[3]["field_specific"]

        for fk, entry in self.manifest.items():
            if fk == "_default":
                continue
            if entry.get("category") == "D":
                with self.subTest(field=fk):
                    tier = classify_acquisition_tier(fk, entry)
                    if fk in tier2_specific:
                        self.assertEqual(tier, 2,
                                         f"D-category {fk} is user metric → Tier 2")
                    elif fk in tier3_specific:
                        self.assertEqual(tier, 3,
                                         f"D-category {fk} is financial metric → Tier 3")

    # ── Tier 配置一致性 ──
    def test_tier2_tier3_fields_no_overlap(self):
        """Tier 2 和 Tier 3 字段集合无重叠"""
        t2 = TIER_CONFIG[2]["field_specific"]
        t3 = TIER_CONFIG[3]["field_specific"]
        overlap = t2 & t3
        self.assertEqual(len(overlap), 0,
                         f"Tier 2/3 field overlap found: {overlap}")

    def test_tier_config_has_three_levels(self):
        """TIER_CONFIG 包含 3 个层级"""
        self.assertEqual(len(TIER_CONFIG), 3)

    def test_all_tiers_have_label_and_strategy(self):
        """每个 tier 必须有 label 和 strategy"""
        for tier_id, cfg in TIER_CONFIG.items():
            with self.subTest(tier=tier_id):
                self.assertIn("label", cfg)
                self.assertIn("strategy", cfg)
                self.assertIn("default_confidence_level", cfg)


if __name__ == "__main__":
    unittest.main()
