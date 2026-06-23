"""SPEC §16.6 市场字段测试

验证市场字段（market_size / tam / market_cagr 等 C 类 market_model）的分辨率规则：

规则 1: market_model 类型字段默认 resolution_status="proxy"，不得 "confirmed"
规则 2: 缺少 required_context（region/year/source 等）→ 空值时标 "manual_needed"，有值时仍 "proxy" 但注明缺口径
规则 3: allow_proxy=false 的市场字段始终 "manual_needed"
规则 4: 即使 required_context 全部提供，市场字段仍为 "proxy"，永不为 "confirmed"
规则 5: 市场字段在 manifest 中必须 category='C' 且 allow_proxy=true

设计决策:
- resolve_field（高层 API）处理有值/空值分支
- _resolve_market_model（底层）处理空值时 allow_proxy + required_context 判断
"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.field_resolver import (
    resolve_field,
    FieldResult,
    _resolve_market_model,
)


class TestMarketSizeValueNoEvidence(unittest.TestCase):
    """market_size_value 有值但无证据 → proxy（不得 confirmed）"""

    def test_market_size_value_with_value_no_evidence_is_proxy(self):
        """有 LLM 提取值，但 market_model 类型始终 proxy"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
            "required_context": ["region", "year", "source"],
        }
        result = resolve_field(
            "market_size_value", "$5.2B",
            {}, entry,
            evidence_span_ids=[],  # 无证据
        )
        self.assertEqual(result.resolution_status, "proxy",
                         "market_size_value with value should be proxy, never confirmed")
        self.assertNotEqual(result.resolution_status, "confirmed",
                            "market_model fields must NEVER be confirmed")
        self.assertEqual(result.resolution_method, "market_model")

    def test_market_size_value_even_with_evidence_never_confirmed(self):
        """即使有 evidence_span_ids，market_model 仍为 proxy"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
            "required_context": ["region", "year", "source"],
        }
        result = resolve_field(
            "market_size_value", "$5.2B",
            {}, entry,
            evidence_span_ids=[101, 102],  # 有证据
        )
        self.assertEqual(result.resolution_status, "proxy",
                         "market_model with evidence is still proxy, never confirmed")
        self.assertEqual(len(result.evidence_span_ids), 2)

    def test_market_size_value_no_value_returned_as_manual_needed(self):
        """无值且 required_context 缺失 → manual_needed"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
            "required_context": ["region", "year", "source"],
        }
        result = resolve_field(
            "market_size_value", None,  # 无值
            {}, entry,
            evidence_span_ids=[],
        )
        # 空值时走 _resolve_market_model → missing_ctx → manual_needed
        self.assertEqual(result.resolution_status, "manual_needed",
                         "market_size_value without value + missing context → manual_needed")
        self.assertIn("缺少口径", result.unavailable_reason)


class TestTamValueWithoutRegionYear(unittest.TestCase):
    """tam_value 无 region/year → manual_needed（空值时）"""

    def test_tam_value_missing_required_context_is_manual_needed(self):
        """tam_value 空值且 manifest 中无 region/year/source → manual_needed"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
            "required_context": ["region", "year", "source"],
            # 故意不提供 region, year, source 键
        }
        result = resolve_field(
            "tam_value", None,
            {}, entry,
            evidence_span_ids=[],
        )
        self.assertEqual(result.resolution_status, "manual_needed",
                         "tam_value without region/year/source in entry → manual_needed")

    def test_tam_value_with_region_year_still_manual_needed_without_source(self):
        """部分口径（有 region/year 但缺 source）仍 manual_needed"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
            "required_context": ["region", "year", "source"],
            "region": "Global",
            "year": "2024",
            # source 缺失
        }
        result = resolve_field(
            "tam_value", None,
            {}, entry,
            evidence_span_ids=[],
        )
        # 仍缺 source → manual_needed
        self.assertEqual(result.resolution_status, "manual_needed",
                         "tam_value with missing source still → manual_needed")
        self.assertIn("source", result.unavailable_reason)


class TestMarketCagrProxyAllowed(unittest.TestCase):
    """market_cagr 设 allow_proxy=True → proxy"""

    def test_market_cagr_with_value_is_proxy(self):
        """market_cagr 有值时标 proxy"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
        }
        result = resolve_field(
            "market_cagr", "12.5% CAGR",
            {}, entry,
            evidence_span_ids=[],
        )
        self.assertEqual(result.resolution_status, "proxy",
                         "market_cagr with value should be proxy")

    def test_market_cagr_no_value_no_required_context_is_proxy(self):
        """market_cagr 空值但 allow_proxy=True 且无 required_context → proxy"""
        # 注: market_cagr 在 manifest 中无 required_context，所以不会进 manual_needed
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
        }
        result = resolve_field(
            "market_cagr", None,
            {}, entry,
            evidence_span_ids=[],
        )
        self.assertEqual(result.resolution_status, "proxy",
                         "market_cagr allow_proxy=True without required_context → proxy")


class TestMarketSizeCompleteContext(unittest.TestCase):
    """市场字段即使有完整 context（region/year/source）也永不为 confirmed"""

    def test_market_size_with_complete_context_still_proxy(self):
        """region/year/source 全提供 → 仍 proxy，永不为 confirmed"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
            "required_context": ["region", "year", "source"],
            "region": "Global",
            "year": "2024",
            "source": "Grand View Research",
        }
        result = resolve_field(
            "market_size_value", "$5.2B",
            {}, entry,
            evidence_span_ids=[201],
        )
        self.assertEqual(result.resolution_status, "proxy",
                         "Market field with full context is STILL proxy, never confirmed")
        self.assertNotEqual(result.resolution_status, "confirmed",
                            "market_model must NEVER be confirmed regardless of context")

    def test_market_size_complete_context_no_value_returns_proxy(self):
        """空值但 context 齐全 → proxy（因 allow_proxy=True 且 missing_ctx 为空）"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "if_missing": "manual_needed",
            "required_context": ["region", "year", "source"],
            "region": "Global",
            "year": "2024",
            "source": "Grand View Research",
        }
        result = resolve_field(
            "market_size_value", None,
            {}, entry,
            evidence_span_ids=[],
        )
        # _resolve_market_model: allow_proxy=True, missing_ctx=[] → proxy
        self.assertEqual(result.resolution_status, "proxy",
                         "Market field empty but allow_proxy + complete context → proxy")

    def test_market_field_complete_context_never_confirmed_direct_call(self):
        """直接调用 _resolve_market_model 确认完整 context 仍 proxy"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": True,
            "required_context": ["region", "year", "source"],
            "region": "North America",
            "year": "2023",
            "source": "IDC Report",
        }
        result = _resolve_market_model("market_size_value", entry)
        self.assertEqual(result.resolution_status, "proxy",
                         "Direct call: complete context still proxy")
        self.assertNotEqual(result.resolution_status, "confirmed")


class TestMarketModelNoProxyFallback(unittest.TestCase):
    """market_model 无 allow_proxy → manual_needed"""

    def test_market_model_allow_proxy_false_is_manual_needed(self):
        """allow_proxy=false → manual_needed（无论有无值）"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "allow_proxy": False,
            "if_missing": "manual_needed",
        }
        # 空值走 _resolve_market_model
        result = resolve_field(
            "some_market_field", None,
            {}, entry,
            evidence_span_ids=[],
        )
        self.assertEqual(result.resolution_status, "manual_needed",
                         "market_model with allow_proxy=False → manual_needed")

    def test_market_model_no_allow_proxy_key_is_manual_needed(self):
        """未设 allow_proxy 键（默认 False）→ manual_needed"""
        entry = {
            "category": "C",
            "resolution_type": "market_model",
            "if_missing": "manual_needed",
            # allow_proxy 未设置，entry.get("allow_proxy", False) → False
        }
        result = resolve_field(
            "another_market_field", None,
            {}, entry,
            evidence_span_ids=[],
        )
        self.assertEqual(result.resolution_status, "manual_needed",
                         "market_model without allow_proxy key defaults → manual_needed")


class TestMarketFieldManifestConformance(unittest.TestCase):
    """验证 manifest 中市场字段配置符合规范"""

    @classmethod
    def setUpClass(cls):
        from research.field_status import _load_manifest
        cls.manifest = _load_manifest()

    def test_market_fields_in_manifest(self):
        """核心市场字段必须存在于 manifest 中"""
        market_fields = [
            "market_size_value", "market_size_currency",
            "market_size_year", "market_size_source_note",
            "tam_value", "tam_currency", "tam_year",
            "market_cagr",
        ]
        for fk in market_fields:
            with self.subTest(field=fk):
                self.assertIn(fk, self.manifest,
                              f"{fk} must exist in field_manifest.yaml")

    def test_market_fields_have_category_c(self):
        """所有市场字段 category 必须为 'C'"""
        market_fields = [
            "market_size_value", "market_size_currency",
            "market_size_year", "market_size_source_note",
            "tam_value", "tam_currency", "tam_year",
            "market_cagr",
        ]
        for fk in market_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                self.assertEqual(entry.get("category"), "C",
                                 f"{fk} must have category='C'")

    def test_market_fields_have_resolution_type_market_model(self):
        """所有市场字段 resolution_type 必须为 'market_model'"""
        market_fields = [
            "market_size_value", "market_size_currency",
            "market_size_year", "market_size_source_note",
            "tam_value", "tam_currency", "tam_year",
            "market_cagr",
        ]
        for fk in market_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                self.assertEqual(entry.get("resolution_type"), "market_model",
                                 f"{fk} must have resolution_type='market_model'")

    def test_market_fields_allow_proxy_true(self):
        """所有市场字段 allow_proxy 必须为 True"""
        market_fields = [
            "market_size_value", "market_size_currency",
            "market_size_year", "market_size_source_note",
            "tam_value", "tam_currency", "tam_year",
            "market_cagr",
        ]
        for fk in market_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                self.assertTrue(entry.get("allow_proxy"),
                                f"{fk} must have allow_proxy=true")

    def test_market_size_value_allows_proxy(self):
        """market_size_value allow_proxy 为 true，空值时返回 proxy 而非 manual_needed"""
        entry = self.manifest.get("market_size_value", {})
        self.assertTrue(entry.get("allow_proxy"))
        self.assertEqual(entry.get("if_missing"), "manual_needed")

    def test_tam_value_has_required_context(self):
        """tam_value 必须声明 required_context"""
        entry = self.manifest.get("tam_value", {})
        required = entry.get("required_context", [])
        self.assertIn("region", required)
        self.assertIn("year", required)
        self.assertIn("source", required)

    def test_tam_has_required_context(self):
        """tam 必须声明 required_context（含 segment）"""
        entry = self.manifest.get("tam", {})
        required = entry.get("required_context", [])
        self.assertIn("region", required)
        self.assertIn("segment", required)
        self.assertIn("year", required)
        self.assertIn("source", required)

    def test_market_fields_if_missing_is_manual_needed(self):
        """所有市场字段 if_missing 应为 'manual_needed'"""
        market_fields = [
            "market_size_value", "market_size_currency",
            "market_size_year", "market_size_source_note",
            "tam_value", "tam_currency", "tam_year",
            "market_cagr",
        ]
        for fk in market_fields:
            entry = self.manifest.get(fk, {})
            with self.subTest(field=fk):
                self.assertEqual(entry.get("if_missing"), "manual_needed",
                                 f"{fk} must have if_missing='manual_needed'")


class TestMarketFieldIntegration(unittest.TestCase):
    """集成测试：验证 resolve_field 对真实 manifest 条目的行为"""

    @classmethod
    def setUpClass(cls):
        from research.field_status import _load_manifest
        cls.manifest = _load_manifest()

    def test_market_size_value_with_manifest_entry_no_value(self):
        """使用真实 manifest 条目：空值 + allow_proxy → proxy"""
        entry = self.manifest.get("market_size_value", {})
        result = resolve_field(
            "market_size_value", None,
            {}, entry,
            evidence_span_ids=[],
        )
        # allow_proxy=true 且 removed required_context → proxy（允许用行业估算兜底）
        self.assertEqual(result.resolution_status, "proxy",
                         "Real manifest: empty market_size_value with allow_proxy → proxy")
        self.assertNotEqual(result.resolution_status, "confirmed")

    def test_market_size_value_with_manifest_entry_has_value(self):
        """使用真实 manifest 条目：有值 → proxy"""
        entry = self.manifest.get("market_size_value", {})
        result = resolve_field(
            "market_size_value", "$10B",
            {}, entry,
            evidence_span_ids=[],
        )
        # 有值时走 _resolve_with_value → market_model → proxy
        self.assertEqual(result.resolution_status, "proxy",
                         "Real manifest: market_size_value with value → proxy")
        self.assertNotEqual(result.resolution_status, "confirmed")

    def test_tam_with_manifest_entry_no_value(self):
        """使用真实 tam manifest：空值 → manual_needed（缺 4 个 context）"""
        entry = self.manifest.get("tam", {})
        result = resolve_field(
            "tam", None,
            {}, entry,
            evidence_span_ids=[],
        )
        # tam 有 required_context: [region, segment, year, source]
        # 全部缺失 → manual_needed
        self.assertEqual(result.resolution_status, "manual_needed",
                         "Real manifest: empty tam → manual_needed")
        self.assertIn("缺少口径", result.unavailable_reason)

    def test_tam_with_manifest_entry_has_value(self):
        """使用真实 tam manifest：有值 → proxy"""
        entry = self.manifest.get("tam", {})
        result = resolve_field(
            "tam", "$50B",
            {}, entry,
            evidence_span_ids=[301, 302],
        )
        self.assertEqual(result.resolution_status, "proxy",
                         "Real manifest: tam with value → proxy")

    def test_market_cagr_with_manifest_entry(self):
        """market_cagr 真实 manifest：无 required_context，空值 → proxy"""
        entry = self.manifest.get("market_cagr", {})
        result = resolve_field(
            "market_cagr", None,
            {}, entry,
            evidence_span_ids=[],
        )
        # market_cagr 无 required_context → allow_proxy → proxy
        self.assertEqual(result.resolution_status, "proxy",
                         "Real manifest: market_cagr empty → proxy (no required_context)")

    def test_all_market_fields_never_confirmed(self):
        """所有真实市场字段在任何条件下都不得 confirmed"""
        market_fields = [
            "market_size_value", "market_size_currency",
            "market_size_year", "market_size_source_note",
            "tam_value", "tam_currency", "tam_year",
            "market_cagr", "tam",
        ]
        test_values = {
            "market_size_value": "$10B",
            "market_size_currency": "USD",
            "market_size_year": "2024",
            "market_size_source_note": "GVR Report",
            "tam_value": "$100B",
            "tam_currency": "USD",
            "tam_year": "2024",
            "market_cagr": "15%",
            "tam": "$100B",
        }
        for fk in market_fields:
            entry = self.manifest.get(fk, {})
            val = test_values.get(fk, "test_value")
            with self.subTest(field=fk):
                # Test with value
                result = resolve_field(fk, val, {}, entry, evidence_span_ids=[999])
                self.assertNotEqual(
                    result.resolution_status, "confirmed",
                    f"{fk} must NEVER be confirmed (got {result.resolution_status})"
                )


if __name__ == "__main__":
    unittest.main()
