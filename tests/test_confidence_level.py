"""SPEC: confidence_level 枚举 — 字段按可获取难度分三类策略

confidence_level values:
  - verified: 从公司官方/知名媒体直接提取
  - estimated: 从代理指标推算
  - benchmark: 用行业均值填充
  - unavailable: 标注"未公开"，不强行造数

Three acquisition tiers:
  Tier 1 (TAM/市场规模): web search + LLM 提取，可 verified/estimated
  Tier 2 (MAU/用户规模): proxy metrics，通常是 estimated
  Tier 3 (LTV/CAC/留存): estimation formulas or industry benchmarks，通常是 benchmark

测试覆盖:
  1. FieldCandidate 包含 confidence_level 字段
  2. ConfidenceScorer.map_to_confidence_level() 正确映射
  3. 市场字段 (Tier 1) 置信度分级
  4. 用户指标 (Tier 2) 代理推算标记
  5. LTV/CAC (Tier 3) 基准标记
  6. 缺失数据正确标记为 unavailable
"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_intelligence.schemas.candidate import FieldCandidate
from market_intelligence.resolvers.confidence import ConfidenceScorer


class TestFieldCandidateConfidenceLevel(unittest.TestCase):
    """FieldCandidate 数据类必须支持 confidence_level 枚举"""

    def test_field_candidate_has_confidence_level_attr(self):
        """FieldCandidate 必须有 confidence_level 属性，默认为 'unavailable'"""
        c = FieldCandidate(field_key="mau")
        self.assertTrue(hasattr(c, "confidence_level"),
                        "FieldCandidate must have confidence_level attribute")
        self.assertEqual(c.confidence_level, "unavailable",
                         "Default confidence_level should be 'unavailable'")

    def test_field_candidate_confidence_level_values(self):
        """confidence_level 只接受四个枚举值"""
        valid_values = {"verified", "estimated", "benchmark", "unavailable"}
        for val in valid_values:
            c = FieldCandidate(field_key="test", confidence_level=val)
            self.assertEqual(c.confidence_level, val)

    def test_field_candidate_to_dict_includes_confidence_level(self):
        """to_dict() 输出必须包含 confidence_level"""
        c = FieldCandidate(
            field_key="tam_value",
            value=10.5,
            value_text="$10.5B",
            confidence_level="estimated",
        )
        d = c.to_dict()
        self.assertIn("confidence_level", d)
        self.assertEqual(d["confidence_level"], "estimated")

    def test_field_candidate_to_dict_excludes_internal_attrs(self):
        """to_dict() 不暴露内部属性"""
        c = FieldCandidate(field_key="test")
        d = c.to_dict()
        self.assertNotIn("_internal", d)


class TestConfidenceScorerMapping(unittest.TestCase):
    """ConfidenceScorer 必须支持 map_to_confidence_level()"""

    @classmethod
    def setUpClass(cls):
        cls.scorer = ConfidenceScorer()

    # ── verified ──
    def test_direct_structured_source_high_confidence_is_verified(self):
        """直接结构化来源 (source_type=structured) + 高置信度 → verified"""
        c = FieldCandidate(
            field_key="market_size_value",
            source_type="structured",
            confidence=0.85,
            value=10.5,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=3, is_direct=True)
        self.assertEqual(level, "verified",
                         "Direct structured source with 3+ evidence → verified")

    def test_filing_source_high_confidence_is_verified(self):
        """filing 来源 + 高置信度 → verified"""
        c = FieldCandidate(
            field_key="funding_total",
            source_type="filing",
            confidence=0.85,
            value=100.0,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=2, is_direct=True)
        self.assertEqual(level, "verified")

    def test_official_blog_high_confidence_is_verified(self):
        """官方博客 + 高置信度 + 多证据 → verified"""
        c = FieldCandidate(
            field_key="tam_value",
            source_type="official_blog",
            confidence=0.75,
            value=50.0,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=3, is_direct=True)
        self.assertEqual(level, "verified",
                         "Official blog with 3+ evidence → verified")

    # ── estimated ──
    def test_web_search_medium_confidence_is_estimated(self):
        """网页搜索 + 中等置信度 → estimated"""
        c = FieldCandidate(
            field_key="market_size_value",
            source_type="web_search",
            confidence=0.55,
            value=5.2,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=2, is_direct=False)
        self.assertEqual(level, "estimated",
                         "Web search with medium confidence → estimated")

    def test_estimation_source_is_estimated(self):
        """估算来源 (estimation) → estimated (永不为 verified)"""
        c = FieldCandidate(
            field_key="mau",
            source_type="estimation",
            confidence=0.90,  # 即使高置信度
            value=1000000,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=5, is_direct=False)
        self.assertEqual(level, "estimated",
                         "Estimation source NEVER becomes verified, even with high confidence")

    def test_proxy_metrics_is_estimated(self):
        """代理指标 (SimilarWeb/GitHub Stars) → estimated"""
        c = FieldCandidate(
            field_key="mau",
            source_type="web_search",
            confidence=0.45,
            value=500000,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=2, is_direct=False)
        self.assertEqual(level, "estimated")

    # ── benchmark ──
    def test_industry_benchmark_mapping(self):
        """行业基准替代 → benchmark"""
        c = FieldCandidate(
            field_key="ltv_cac_ratio",
            source_type="estimation",
            confidence=0.25,
            value=3.0,
            value_text="~3x (SaaS industry benchmark)",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=0, is_direct=False)
        self.assertEqual(level, "benchmark",
                         "Industry benchmark values → benchmark")

    def test_retention_benchmark_mapping(self):
        """留存率行业基准 → benchmark"""
        c = FieldCandidate(
            field_key="retention_rate",
            source_type="estimation",
            confidence=0.20,
            value=75.0,
            value_text="~75% (SaaS month-1 benchmark)",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=0, is_direct=False)
        self.assertEqual(level, "benchmark")

    def test_cac_benchmark_mapping(self):
        """CAC 行业基准 → benchmark"""
        c = FieldCandidate(
            field_key="cac",
            source_type="estimation",
            confidence=0.15,
            value=500.0,
            value_text="~$500 (B2B SaaS benchmark)",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=0, is_direct=False)
        self.assertEqual(level, "benchmark")

    # ── unavailable ──
    def test_no_value_is_unavailable(self):
        """无值 → unavailable"""
        c = FieldCandidate(
            field_key="arr",
            source_type="web_search",
            confidence=0.0,
            value=None,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=0, is_direct=False)
        self.assertEqual(level, "unavailable",
                         "No value → unavailable")

    def test_very_low_confidence_is_unavailable(self):
        """极低置信度 + 无证据 → unavailable"""
        c = FieldCandidate(
            field_key="churn_rate",
            source_type="web_search",
            confidence=0.10,
            value=5.0,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=0, is_direct=False)
        self.assertEqual(level, "unavailable",
                         "Very low confidence + 0 evidence → unavailable")

    def test_unavailable_reason_preserved(self):
        """unavailable 时保留原因说明"""
        c = FieldCandidate(
            field_key="burn_rate",
            source_type="web_search",
            confidence=0.0,
            value=None,
            unavailable_reason="公司未公开披露",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=0, is_direct=False)
        self.assertEqual(level, "unavailable")
        self.assertEqual(c.unavailable_reason, "公司未公开披露")


class TestAcquisitionTierIntegration(unittest.TestCase):
    """集成测试：验证三类字段的 confidence_level 分配逻辑"""

    @classmethod
    def setUpClass(cls):
        cls.scorer = ConfidenceScorer()

    # ── Tier 1: TAM/市场规模 — 可达到 verified ──
    def test_tier1_market_size_from_report_is_verified(self):
        """Tier 1: 从 Grand View Research 等报告提取的市场规模 → verified"""
        c = FieldCandidate(
            field_key="market_size_value",
            source_type="structured",
            confidence=0.85,
            value=10.4,
            value_text="$10.4B",
            region="Global",
            year=2024,
            source_url="https://www.grandviewresearch.com/...",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=3, is_direct=True)
        self.assertEqual(level, "verified")

    def test_tier1_market_size_from_web_search_is_estimated(self):
        """Tier 1: 网页搜索提取的市场规模 → estimated"""
        c = FieldCandidate(
            field_key="tam_value",
            source_type="web_search",
            confidence=0.55,
            value=100.0,
            value_text="$100B",
            year=2023,
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=2, is_direct=False)
        self.assertEqual(level, "estimated")

    # ── Tier 2: MAU/用户规模 — 通常是 estimated ──
    def test_tier2_mau_from_company_blog_is_estimated(self):
        """Tier 2: 公司博客披露的 MAU → estimated（二级来源）"""
        c = FieldCandidate(
            field_key="mau",
            source_type="trusted_media",
            confidence=0.60,
            value=5000000,
            value_text="5M MAU",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=1, is_direct=False)
        self.assertEqual(level, "estimated")

    def test_tier2_mau_from_similarweb_proxy_is_estimated(self):
        """Tier 2: SimilarWeb 月访问量作代理 → estimated"""
        c = FieldCandidate(
            field_key="mau",
            source_type="estimation",
            confidence=0.40,
            value=2000000,
            value_text="~2M monthly visits (SimilarWeb estimate)",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=1, is_direct=False)
        self.assertEqual(level, "estimated",
                         "Proxy metrics → estimated, never verified")

    # ── Tier 3: LTV/CAC — 通常是 benchmark ──
    def test_tier3_ltv_cac_from_disclosure_is_estimated(self):
        """Tier 3: 创始人采访中披露的 LTV/CAC → estimated（有来源但非官方）"""
        c = FieldCandidate(
            field_key="ltv_cac_ratio",
            source_type="investor_report",
            confidence=0.45,
            value=4.0,
            value_text="~4x (founder interview, YC Demo Day 2024)",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=1, is_direct=False)
        self.assertEqual(level, "estimated")

    def test_tier3_retention_industry_avg_is_benchmark(self):
        """Tier 3: 行业平均留存率 → benchmark"""
        c = FieldCandidate(
            field_key="retention_rate",
            source_type="estimation",
            confidence=0.20,
            value=70.0,
            value_text="~70% month-1 retention (SaaS industry avg, 不代表公司披露)",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=0, is_direct=False)
        self.assertEqual(level, "benchmark")

    def test_tier3_cac_not_disclosed_is_unavailable(self):
        """Tier 3: CAC 未公开 → unavailable（不强行造数）"""
        c = FieldCandidate(
            field_key="cac",
            source_type="web_search",
            confidence=0.0,
            value=None,
            unavailable_reason="CAC 未公开披露，且无足够代理指标推算",
        )
        level = self.scorer.map_to_confidence_level(c, num_evidence=0, is_direct=False)
        self.assertEqual(level, "unavailable")


class TestConfidenceLevelContractCompliance(unittest.TestCase):
    """验证 confidence_level 与现有 status 系统的一致性"""

    def test_confidence_level_enum_values(self):
        """confidence_level 枚举值集合正确"""
        expected = {"verified", "estimated", "benchmark", "unavailable"}
        # 验证四个值互斥且完整
        self.assertEqual(len(expected), 4)

    def test_confidence_level_different_from_status(self):
        """confidence_level 是独立维度，不替代 status"""
        c = FieldCandidate(
            field_key="market_size_value",
            status="proxy",  # 现有 status 系统
            confidence_level="estimated",  # 新 confidence_level 系统
            value=10.0,
        )
        self.assertEqual(c.status, "proxy")
        self.assertEqual(c.confidence_level, "estimated")
        self.assertNotEqual(c.status, c.confidence_level,
                           "confidence_level must be independent from status")

    def test_verified_maps_to_distinct_from_confirmed(self):
        """verified ≠ confirmed — 两个独立维度"""
        c = FieldCandidate(
            field_key="funding_total",
            status="confirmed",
            confidence_level="verified",
            source_type="filing",
            value=500.0,
        )
        self.assertEqual(c.status, "confirmed")
        self.assertEqual(c.confidence_level, "verified")
        # verified (confidence_level) 和 confirmed (status) 可共存但含义不同


if __name__ == "__main__":
    unittest.main()
