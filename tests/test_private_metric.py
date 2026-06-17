"""私有指标保护测试 — SPEC Section 16.2

验证：
1. search_plan.py 不为 D 类字段生成搜索 query
2. gap_detector.py 排除 D/E 类字段的补采
3. field_manifest.yaml 标记 D 类字段 refetchable: false
4. D 类字段使用 private_metric resolution_type
"""
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "webapp"))


# D 类私有经营指标（field_manifest.yaml 中 category: D 的字段）
D_CLASS_FIELDS = {
    "arr", "cac", "ltv", "churn_rate", "retention_rate",
    "gross_margin", "burn_rate", "runway_months",
    "revenue_metrics", "growth_metrics",
}

# D 类字段相关的 Tavily 搜索 query 关键词 — 不应出现在 search_plan 的 query 中
D_CLASS_QUERY_KEYWORDS = {
    # 不应搜索的 D 类指标关键词
    "mau", "retention_rate", "ltv", "cac",
    "churn_rate", "gross_margin", "burn_rate", "runway_months",
}

# E 类字段（B2B 不适配）
E_CLASS_FIELDS = {
    "active_users", "registered_users", "paying_users",
}

# 允许出现在 query 中的字段（A/B/C 类，可能与 D 类字段名相似但不是搜索私有指标的）
# 例如 "retention" 作为通用词可能出现在描述性 query 中，但不应以 "retention_rate churn_rate" 组合出现
OK_CONTEXT_KEYWORDS = {
    "retention", "growth", "users", "customers", "revenue", "ARR", "MRR",
}


def _load_manifest() -> dict:
    """加载 field_manifest.yaml"""
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


def _search_plan_query_texts() -> list[str]:
    """从 search_plan.py 收集所有可能的 Tavily query 文本。"""
    from search_plan import TAVILY_QUERY_TEMPLATES
    texts = []
    for intent, templates in TAVILY_QUERY_TEMPLATES.items():
        for tmpl in templates:
            texts.append(tmpl)
    return texts


class PrivateMetricSearchPlanTest(unittest.TestCase):
    """SPEC 16.2 — search_plan.py 不应为 D 类字段生成搜索 query"""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()

    def test_d_class_fields_are_category_d(self):
        """D 类字段在 manifest 中 category 为 D"""
        for fk in D_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            self.assertIsNotNone(
                entry,
                f"D 类字段 '{fk}' 不在 field_manifest.yaml 中"
            )
            self.assertEqual(
                entry.get("category"), "D",
                f"字段 '{fk}' 应为 category: D，实际为 {entry.get('category')}"
            )

    def test_d_class_fields_have_private_metric_resolution_type(self):
        """D 类字段应有 resolution_type: private_metric"""
        for fk in D_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            if entry is None:
                continue
            self.assertEqual(
                entry.get("resolution_type"), "private_metric",
                f"字段 '{fk}' 应为 resolution_type: private_metric，"
                f"实际为 {entry.get('resolution_type')}"
            )

    def test_d_class_fields_not_refetchable(self):
        """D 类字段应标记 refetchable: false 或默认不可补采"""
        for fk in D_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            if entry is None:
                continue
            # refetchable 显式为 false，或未设置 refetchable: true
            refetchable = entry.get("refetchable", None)
            if refetchable is not None:
                self.assertFalse(
                    refetchable,
                    f"D 类字段 '{fk}' refetchable 应为 false，实际为 {refetchable}"
                )

    def test_d_class_allow_proxy_false(self):
        """D 类字段 allow_proxy 应为 false（不允许用 proxy 替代）"""
        for fk in D_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            if entry is None:
                continue
            allow_proxy = entry.get("allow_proxy")
            self.assertFalse(
                allow_proxy,
                f"D 类字段 '{fk}' allow_proxy 应为 false，实际为 {allow_proxy}"
            )

    def test_d_class_if_missing_is_unavailable(self):
        """D 类字段缺失时默认 unavailable"""
        for fk in D_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            if entry is None:
                continue
            self.assertEqual(
                entry.get("if_missing"), "unavailable",
                f"D 类字段 '{fk}' if_missing 应为 'unavailable'，"
                f"实际为 '{entry.get('if_missing')}'"
            )

    def test_unit_economics_intent_not_in_search_plan_if_d_only(self):
        """检查 unit_economics 意图 query 是否包含不应搜索的 D 类指标组合"""
        from search_plan import TAVILY_QUERY_TEMPLATES
        ue_templates = TAVILY_QUERY_TEMPLATES.get("unit_economics", [])
        # 记录当前状态 — 如果 query 直接包含 D 类字段组合，视为未通过
        d_keywords_in_query = []
        for tmpl in ue_templates:
            tmpl_lower = tmpl.lower()
            found = [kw for kw in ["cac", "ltv", "gross_margin", "payback"]
                     if kw in tmpl_lower]
            if found:
                d_keywords_in_query.append((tmpl, found))

        # 当前已知状态：search_plan 仍为 D 类字段生成了 unit_economics query
        # 此测试记录违规情况，作为 SPEC 合规性检查
        if d_keywords_in_query:
            self.fail(
                f"search_plan.py 的 unit_economics 意图 query 模板包含 D 类字段关键词，"
                f"违反 SPEC 16.2:\n" +
                "\n".join(f"  - {tmpl[:80]}... → {kw}" for tmpl, kw in d_keywords_in_query)
            )

    def test_capital_efficiency_intent_not_in_search_plan_if_d_only(self):
        """检查 capital_efficiency 意图 query 是否包含不应搜索的 D 类指标"""
        from search_plan import TAVILY_QUERY_TEMPLATES
        ce_templates = TAVILY_QUERY_TEMPLATES.get("capital_efficiency", [])
        d_keywords_in_query = []
        for tmpl in ce_templates:
            tmpl_lower = tmpl.lower()
            found = [kw for kw in ["burn_rate", "runway", "gross_margin"]
                     if kw in tmpl_lower]
            if found:
                d_keywords_in_query.append((tmpl, found))

        if d_keywords_in_query:
            self.fail(
                f"search_plan.py 的 capital_efficiency 意图 query 模板包含 D 类字段关键词，"
                f"违反 SPEC 16.2:\n" +
                "\n".join(f"  - {tmpl[:80]}... → {kw}" for tmpl, kw in d_keywords_in_query)
            )

    def test_retention_metrics_intent_not_in_search_plan_if_d_only(self):
        """检查 retention_metrics 意图 query 是否包含 D 类指标 (retention_rate, churn_rate)"""
        from search_plan import TAVILY_QUERY_TEMPLATES
        rt_templates = TAVILY_QUERY_TEMPLATES.get("retention_metrics", [])
        d_keywords_in_query = []
        for tmpl in rt_templates:
            tmpl_lower = tmpl.lower()
            found = [kw for kw in ["retention_rate", "churn_rate", "churn metrics",
                                    "cohort retention"]
                     if kw in tmpl_lower]
            if found:
                d_keywords_in_query.append((tmpl, found))

        if d_keywords_in_query:
            self.fail(
                f"search_plan.py 的 retention_metrics 意图 query 模板包含 D 类字段关键词，"
                f"违反 SPEC 16.2:\n" +
                "\n".join(f"  - {tmpl[:80]}... → {kw}" for tmpl, kw in d_keywords_in_query)
            )


class PrivateMetricGapDetectorTest(unittest.TestCase):
    """SPEC 16.2 — gap_detector.py 排除 D/E 类字段的补采"""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()

    def test_is_refetchable_excludes_d_class(self):
        """_is_refetchable 对 D 类字段返回 False"""
        from gap_detector import _is_refetchable
        for fk in D_CLASS_FIELDS:
            self.assertFalse(
                _is_refetchable(fk),
                f"D 类字段 '{fk}' 应不可补采 (_is_refetchable 返回 False)"
            )

    def test_is_refetchable_excludes_e_class(self):
        """_is_refetchable 对 E 类字段返回 False"""
        from gap_detector import _is_refetchable
        for fk in E_CLASS_FIELDS:
            self.assertFalse(
                _is_refetchable(fk),
                f"E 类字段 '{fk}' 应不可补采 (_is_refetchable 返回 False)"
            )

    def test_is_refetchable_allows_a_class(self):
        """_is_refetchable 对 A 类字段返回 True"""
        from gap_detector import _is_refetchable
        a_fields = ["company_name", "founder_name", "funding_info",
                     "main_product_name", "competitors"]
        for fk in a_fields:
            self.assertTrue(
                _is_refetchable(fk),
                f"A 类字段 '{fk}' 应可补采 (_is_refetchable 返回 True)"
            )

    def test_is_refetchable_allows_b_class(self):
        """_is_refetchable 对 B 类字段返回 True"""
        from gap_detector import _is_refetchable
        b_fields = ["mrr", "ltv_cac_ratio", "funding_stage_score"]
        for fk in b_fields:
            self.assertTrue(
                _is_refetchable(fk),
                f"B 类字段 '{fk}' 应可补采 (_is_refetchable 返回 True)"
            )

    def test_is_refetchable_allows_c_class(self):
        """_is_refetchable 对 C 类字段返回 True"""
        from gap_detector import _is_refetchable
        c_fields = ["tam", "sam", "som", "market_cagr"]
        for fk in c_fields:
            self.assertTrue(
                _is_refetchable(fk),
                f"C 类字段 '{fk}' 应可补采 (_is_refetchable 返回 True)"
            )

    def test_build_gap_queries_filters_d_class_fields(self):
        """build_gap_queries 过滤掉 D 类字段，不为它们生成补采 query"""
        from gap_detector import build_gap_queries
        # 模拟全 D 类字段的缺口
        d_only_gaps = {
            "unit_economics": ["cac", "ltv", "gross_margin"],
            "capital_efficiency": ["burn_rate", "runway_months"],
            "retention_metrics": ["retention_rate", "churn_rate"],
        }
        queries = build_gap_queries(
            display_name="TestCo",
            website_host="testco.com",
            root_domain="testco",
            gaps=d_only_gaps,
        )
        self.assertEqual(
            len(queries), 0,
            f"纯 D 类字段缺口不应生成补采 query，实际生成了 {len(queries)} 条"
        )

    def test_build_gap_queries_filters_e_class_fields(self):
        """build_gap_queries 过滤掉 E 类字段"""
        from gap_detector import build_gap_queries
        # 模拟全 E 类字段的缺口
        e_only_gaps = {
            "user_metrics": ["active_users", "registered_users", "paying_users"],
        }
        queries = build_gap_queries(
            display_name="TestCo",
            website_host="testco.com",
            root_domain="testco",
            gaps=e_only_gaps,
        )
        self.assertEqual(
            len(queries), 0,
            f"纯 E 类字段缺口不应生成补采 query，实际生成了 {len(queries)} 条"
        )

    def test_build_gap_queries_keeps_abc_in_mixed_gaps(self):
        """build_gap_queries 在混合缺口中保留 A/B/C 类字段"""
        from gap_detector import build_gap_queries
        # 混合 A + D 类字段的缺口
        mixed_gaps = {
            "founders": ["founder_name", "founder_bg"],  # all A
            "unit_economics": ["cac", "ltv"],              # all D — 应被过滤
            "market_size": ["tam"],                         # C — 应保留
        }
        queries = build_gap_queries(
            display_name="TestCo",
            website_host="testco.com",
            root_domain="testco",
            gaps=mixed_gaps,
        )
        # 应生成 founders 和 market_size 的 query，但不含 unit_economics
        intents = {q["intent"] for q in queries}
        self.assertIn("founders", intents, "A 类缺口应生成补采 query")
        self.assertIn("market_size", intents, "C 类缺口应生成补采 query")
        self.assertNotIn("unit_economics", intents, "D 类缺口不应生成补采 query")

    def test_get_skipped_gap_fields_reports_d_e(self):
        """get_skipped_gap_fields 应报告被跳过的 D/E 类字段"""
        from gap_detector import get_skipped_gap_fields
        gaps = {
            "unit_economics": ["cac", "ltv"],
            "capital_efficiency": ["burn_rate", "runway_months"],
            "user_metrics": ["active_users", "registered_users"],
            "founders": ["founder_name"],
        }
        skipped = get_skipped_gap_fields(gaps)
        self.assertIn("unit_economics", skipped)
        self.assertIn("capital_efficiency", skipped)
        self.assertIn("user_metrics", skipped)
        self.assertNotIn("founders", skipped,
                         "A 类字段不应出现在 skipped 报告中")
        self.assertIn("cac", skipped.get("unit_economics", []))
        self.assertIn("active_users", skipped.get("user_metrics", []))


class PrivateMetricManifestTest(unittest.TestCase):
    """SPEC 16.2 — field_manifest.yaml 中 D 类字段的 refetchable 和 resolution_type"""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()

    def test_d_class_fields_explicitly_marked_refetchable_false_or_absent(self):
        """D 类字段 refetchable 显式为 false 或未设置（不设为 true）"""
        for fk in D_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            if entry is None:
                continue
            refetchable = entry.get("refetchable")
            # 可以显式 false 或不设置（默认不补采由 gap_detector._is_refetchable 按 category 判断）
            if refetchable is not None:
                self.assertFalse(
                    refetchable,
                    f"D 类字段 '{fk}' 的 refetchable 必须是 false，实际为 {refetchable}"
                )

    def test_d_class_fields_marked_private_metric(self):
        """所有 D 类字段 resolution_type 为 private_metric"""
        for fk in D_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            if entry is None:
                continue
            self.assertEqual(
                entry.get("resolution_type"), "private_metric",
                f"D 类字段 '{fk}' 的 resolution_type 应为 'private_metric'"
            )

    def test_e_class_fields_marked_b2b_remap(self):
        """所有 E 类字段 resolution_type 为 b2b_remap"""
        for fk in E_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            if entry is None:
                continue
            self.assertEqual(
                entry.get("resolution_type"), "b2b_remap",
                f"E 类字段 '{fk}' 的 resolution_type 应为 'b2b_remap'"
            )

    def test_e_class_fields_not_refetchable(self):
        """E 类字段不应标记 refetchable: true"""
        for fk in E_CLASS_FIELDS:
            entry = self.manifest.get(fk)
            if entry is None:
                continue
            refetchable = entry.get("refetchable")
            if refetchable is not None:
                self.assertFalse(
                    refetchable,
                    f"E 类字段 '{fk}' refetchable 应为 false，实际为 {refetchable}"
                )


if __name__ == "__main__":
    unittest.main()
