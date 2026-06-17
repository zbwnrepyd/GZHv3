"""客户字段测试 — SPEC Section 16.7

验证 resolve_field 对客户相关字段的证据绑定行为：
1. customer_names + evidence_span_ids → confirmed（来自官网 customer page）
2. customer_names 无 evidence_span_ids → llm_extracted（不得 confirmed）
3. customer_selection_reasons + evidence_span_ids → confirmed（至少绑定一个事实证据）
4. customer_selection_reasons 无 evidence_span_ids → llm_extracted
5. customer_choice_evidence + evidence_span_ids → confirmed
6. customer_choice_evidence 无 evidence_span_ids → llm_extracted
7. field_manifest 中客户字段均为 category A / resolution_type official_fact
"""
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "webapp"))

from research.field_resolver import resolve_field, FieldResult, _check_evidence_quality


# ── helper: 加载 manifest ──
def _load_manifest() -> dict:
    """加载 field_manifest.yaml 返回 fields 字典。"""
    try:
        import yaml
    except ImportError:
        raise unittest.SkipTest("PyYAML 未安装")
    path = ROOT / "references" / "field_manifest.yaml"
    if not path.exists():
        raise unittest.SkipTest("field_manifest.yaml 不存在")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("fields", {})


# ── 客户字段清单（与 manifest 对齐）──
CUSTOMER_FIELDS = [
    "customer_names",
    "customer_selection_reasons",
    "customer_choice_evidence",
    "ideal_customer_profile",
    "customer_segment",
    "customer_segment_primary",
    "customer_segment_secondary",
]


class CustomerNamesEvidenceTest(unittest.TestCase):
    """SPEC 16.7.1 — customer_names 证据绑定"""

    def setUp(self):
        self.manifest_entry = {
            "resolution_type": "official_fact",
            "category": "A",
            "type": "json_text",
        }

    def test_customer_names_with_evidence_confirmed(self):
        """customer_names 有证据绑定 → confirmed"""
        result = resolve_field(
            field_key="customer_names",
            field_value='["Airbnb", "Stripe", "Notion"]',
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=["ev_cust_001", "ev_cust_002"],
        )
        self.assertEqual(result.field_key, "customer_names")
        self.assertEqual(
            result.resolution_status, "confirmed",
            f"customer_names 有证据时应为 confirmed，实际为 {result.resolution_status}"
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.resolution_method, "official_fact")
        self.assertIn("ev_cust_001", result.evidence_span_ids)
        self.assertIn("ev_cust_002", result.evidence_span_ids)

    def test_customer_names_single_evidence_medium_confidence(self):
        """customer_names 单个证据 → confirmed 但 confidence medium"""
        result = resolve_field(
            field_key="customer_names",
            field_value='["Airbnb"]',
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=["ev_single"],
        )
        self.assertEqual(result.resolution_status, "confirmed")
        self.assertEqual(
            result.confidence, "medium",
            f"单个证据 confidence 应为 medium，实际为 {result.confidence}"
        )

    def test_customer_names_without_evidence_llm_extracted(self):
        """customer_names 无证据绑定 → llm_extracted（不得 confirmed）"""
        result = resolve_field(
            field_key="customer_names",
            field_value='["Airbnb", "Stripe"]',
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=[],  # 空列表 — 无证据
        )
        self.assertEqual(
            result.resolution_status, "llm_extracted",
            f"customer_names 无证据时应为 llm_extracted，实际为 {result.resolution_status}"
        )
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.resolution_method, "llm_extract_no_evidence")
        self.assertIn(
            "未绑定证据源", result.unavailable_reason,
            "无证据时 unavailable_reason 应提示未绑定证据源"
        )

    def test_customer_names_none_evidence_ids_llm_extracted(self):
        """customer_names evidence_span_ids=None → llm_extracted"""
        result = resolve_field(
            field_key="customer_names",
            field_value='["Stripe"]',
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=None,  # None — 等同无证据
        )
        self.assertEqual(result.resolution_status, "llm_extracted")

    def test_customer_names_empty_value_unavailable(self):
        """customer_names 无值时 → unavailable（if_missing: unavailable）"""
        result = resolve_field(
            field_key="customer_names",
            field_value=None,
            resolved_pool={},
            manifest_entry={**self.manifest_entry, "if_missing": "unavailable"},
        )
        self.assertEqual(result.resolution_status, "unavailable")


class CustomerSelectionReasonsEvidenceTest(unittest.TestCase):
    """SPEC 16.7.2 — customer_selection_reasons 必须绑定至少一个事实证据"""

    def setUp(self):
        self.manifest_entry = {
            "resolution_type": "official_fact",
            "category": "A",
        }

    def test_selection_reasons_with_evidence_confirmed(self):
        """customer_selection_reasons 有证据绑定 → confirmed"""
        result = resolve_field(
            field_key="customer_selection_reasons",
            field_value="选择 Anthropic 因为其安全性和可靠性优于竞品",
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=["ev_sel_001"],
        )
        self.assertEqual(result.field_key, "customer_selection_reasons")
        self.assertEqual(
            result.resolution_status, "confirmed",
            f"customer_selection_reasons 有证据时应为 confirmed，实际为 {result.resolution_status}"
        )
        # 至少绑定一个事实证据
        self.assertIsNotNone(result.evidence_span_ids)
        self.assertGreaterEqual(
            len(result.evidence_span_ids), 1,
            "customer_selection_reasons 必须绑定至少一个事实证据"
        )
        self.assertIn("ev_sel_001", result.evidence_span_ids)
        self.assertEqual(result.resolution_method, "official_fact")

    def test_selection_reasons_multiple_evidence_high_confidence(self):
        """customer_selection_reasons 多个证据 → confirmed + high confidence"""
        result = resolve_field(
            field_key="customer_selection_reasons",
            field_value="安全合规 + 模型性能领先",
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=["ev_a", "ev_b", "ev_c"],
        )
        self.assertEqual(result.resolution_status, "confirmed")
        self.assertEqual(result.confidence, "high")
        self.assertEqual(len(result.evidence_span_ids), 3)

    def test_selection_reasons_without_evidence_llm_extracted(self):
        """customer_selection_reasons 无证据 → llm_extracted（不得 confirmed）"""
        result = resolve_field(
            field_key="customer_selection_reasons",
            field_value="客户因其开放性选择该产品",
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=[],
        )
        self.assertEqual(
            result.resolution_status, "llm_extracted",
            f"customer_selection_reasons 无证据时应为 llm_extracted，实际为 {result.resolution_status}"
        )
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.resolution_method, "llm_extract_no_evidence")
        self.assertIn("未绑定证据源", result.unavailable_reason)


class CustomerChoiceEvidenceTest(unittest.TestCase):
    """SPEC 16.7.3 — customer_choice_evidence 证据绑定"""

    def setUp(self):
        self.manifest_entry = {
            "resolution_type": "official_fact",
            "category": "A",
            "type": "json_text",
        }

    def test_choice_evidence_with_evidence_confirmed(self):
        """customer_choice_evidence 有证据绑定 → confirmed"""
        result = resolve_field(
            field_key="customer_choice_evidence",
            field_value='[{"customer":"Airbnb","reason":"更安全"}]',
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=["ev_choice_001", "ev_choice_002"],
        )
        self.assertEqual(result.field_key, "customer_choice_evidence")
        self.assertEqual(
            result.resolution_status, "confirmed",
            f"customer_choice_evidence 有证据时应为 confirmed，实际为 {result.resolution_status}"
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.resolution_method, "official_fact")

    def test_choice_evidence_without_evidence_llm_extracted(self):
        """customer_choice_evidence 无证据 → llm_extracted"""
        result = resolve_field(
            field_key="customer_choice_evidence",
            field_value='[{"customer":"Notion","reason":"更好的集成"}]',
            resolved_pool={},
            manifest_entry=self.manifest_entry,
            evidence_span_ids=[],
        )
        self.assertEqual(
            result.resolution_status, "llm_extracted",
            f"customer_choice_evidence 无证据时应为 llm_extracted，实际为 {result.resolution_status}"
        )
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.resolution_method, "llm_extract_no_evidence")


class CustomerFieldManifestCategoryTest(unittest.TestCase):
    """SPEC 16.7.4 — field_manifest 中客户字段均为 category A / official_fact"""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()

    def test_all_customer_fields_are_category_a(self):
        """所有客户字段 category 均为 A"""
        for field_key in CUSTOMER_FIELDS:
            entry = self.manifest.get(field_key)
            self.assertIsNotNone(
                entry,
                f"{field_key} 应在 field_manifest.yaml 中有定义"
            )
            self.assertEqual(
                entry.get("category"), "A",
                f"{field_key} 应为 category A，实际为 {entry.get('category')}"
            )

    def test_all_customer_fields_are_official_fact(self):
        """所有客户字段 resolution_type 均为 official_fact"""
        for field_key in CUSTOMER_FIELDS:
            entry = self.manifest.get(field_key, {})
            self.assertEqual(
                entry.get("resolution_type"), "official_fact",
                f"{field_key} 应为 official_fact，实际为 {entry.get('resolution_type')}"
            )

    def test_all_customer_fields_missing_is_unavailable(self):
        """所有客户字段 if_missing 均为 unavailable"""
        for field_key in CUSTOMER_FIELDS:
            entry = self.manifest.get(field_key, {})
            self.assertEqual(
                entry.get("if_missing"), "unavailable",
                f"{field_key} 的 if_missing 应为 unavailable，实际为 {entry.get('if_missing')}"
            )

    def test_customer_names_has_json_text_type(self):
        """customer_names 应有 type: json_text"""
        entry = self.manifest.get("customer_names", {})
        self.assertEqual(
            entry.get("type"), "json_text",
            f"customer_names 的 type 应为 json_text，实际为 {entry.get('type')}"
        )

    def test_customer_choice_evidence_has_json_text_type(self):
        """customer_choice_evidence 应有 type: json_text"""
        entry = self.manifest.get("customer_choice_evidence", {})
        self.assertEqual(
            entry.get("type"), "json_text",
            f"customer_choice_evidence 的 type 应为 json_text，实际为 {entry.get('type')}"
        )

    def test_customer_fields_present_in_manifest(self):
        """确认 manifest 中至少包含 3 个核心客户字段"""
        core_fields = [
            "customer_names",
            "customer_selection_reasons",
            "customer_choice_evidence",
        ]
        for fk in core_fields:
            self.assertIn(fk, self.manifest, f"{fk} 必须在 field_manifest.yaml 中定义")


class EvidenceQualityCheckTest(unittest.TestCase):
    """用于客户字段的证据质量闸门测试（source_score / entity_score / strength）"""

    def test_evidence_quality_passed_with_good_scores(self):
        """高质量证据 span → passed"""
        evidence_map = {
            "ev_good": {
                "source_score": 0.80,
                "entity_score": 0.75,
                "strength": "strong",
            }
        }
        result = _check_evidence_quality(["ev_good"], evidence_map)
        self.assertTrue(result["passed"], f"应该 passed，但 reason={result.get('reason')}")
        self.assertEqual(result["source_score"], 0.80)
        self.assertEqual(result["entity_score"], 0.75)

    def test_evidence_quality_fails_on_low_source_score(self):
        """source_score < 0.65 → 不通过"""
        evidence_map = {
            "ev_low_src": {
                "source_score": 0.50,
                "entity_score": 0.80,
                "strength": "strong",
            }
        }
        result = _check_evidence_quality(["ev_low_src"], evidence_map)
        self.assertFalse(result["passed"])
        self.assertIn("source_score", result["reason"])

    def test_evidence_quality_fails_on_low_entity_score(self):
        """entity_score < 0.60 → 不通过"""
        evidence_map = {
            "ev_low_ent": {
                "source_score": 0.90,
                "entity_score": 0.40,
                "strength": "strong",
            }
        }
        result = _check_evidence_quality(["ev_low_ent"], evidence_map)
        self.assertFalse(result["passed"])
        self.assertIn("entity_score", result["reason"])

    def test_evidence_quality_fails_on_weak_strength(self):
        """strength=weak → 不通过（即使分数高）"""
        evidence_map = {
            "ev_weak": {
                "source_score": 0.90,
                "entity_score": 0.85,
                "strength": "weak",
            }
        }
        result = _check_evidence_quality(["ev_weak"], evidence_map)
        self.assertFalse(result["passed"])
        self.assertIn("weak", result["reason"])

    def test_evidence_quality_fails_with_empty_ids(self):
        """空 evidence_span_ids → 不通过"""
        result = _check_evidence_quality([], None)
        self.assertFalse(result["passed"])
        self.assertIn("No evidence spans", result["reason"])

    def test_customer_field_with_weak_evidence_becomes_llm_extracted(self):
        """客户字段绑定的证据质量不足 → llm_extracted（不得 confirmed）"""
        evidence_map = {
            "ev_weak_cust": {
                "source_score": 0.50,
                "entity_score": 0.50,
                "strength": "weak",
            }
        }
        quality = _check_evidence_quality(["ev_weak_cust"], evidence_map)
        result = resolve_field(
            field_key="customer_names",
            field_value='["WeakCorp"]',
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=["ev_weak_cust"],
            evidence_quality=quality,
        )
        self.assertEqual(
            result.resolution_status, "llm_extracted",
            f"证据质量不足时应为 llm_extracted，实际为 {result.resolution_status}"
        )
        self.assertEqual(result.resolution_method, "llm_extract_weak_evidence")
        self.assertIn(
            "证据质量不满足 confirmed 要求", result.unavailable_reason,
        )


if __name__ == "__main__":
    unittest.main()
