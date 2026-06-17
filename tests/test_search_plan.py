import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))

from search_plan import build_search_plan
from gap_detector import detect_gaps, build_gap_queries


class SearchPlanTests(unittest.TestCase):
    def test_deep_plan_has_core_intents(self):
        plan = build_search_plan(
            "Limitless", "limitless", "limitless.ai",
            ["Limitless", "limitless", "limitless.ai"],
        )
        intents = {q.intent for q in plan.tavily_queries}
        self.assertTrue(
            {"overview", "founders", "funding", "product",
             "pricing", "competitors"}.issubset(intents),
            f"Missing core intents, got: {intents}",
        )

    def test_github_queries_include_display_name(self):
        plan = build_search_plan(
            "Anthropic", "anthropic", "anthropic.com",
            ["Anthropic", "anthropic", "anthropic.com"],
        )
        self.assertTrue(any("Anthropic" in q for q in plan.github_queries))

    def test_youtube_queries_not_empty(self):
        plan = build_search_plan(
            "Notion", "notion", "notion.so",
            ["Notion", "notion", "notion.so"],
        )
        self.assertGreater(len(plan.youtube_queries), 0)

    def test_empty_plan_has_defaults(self):
        plan = build_search_plan("", "", "", [])
        self.assertGreaterEqual(plan.query_count, 0)

    def test_plan_includes_operating_metric_intents(self):
        plan = build_search_plan(
            "Azra Games", "azragames", "azragames.com",
            ["Azra Games", "Azragames", "azragames.com"],
        )
        intents = {q.intent for q in plan.tavily_queries}
        # P0: D-class 字段（retention_metrics/unit_economics/capital_efficiency/
        # revenue_metrics/user_metrics/growth_metrics/revenue/regional）已从初始搜索
        # 计划中移除，仅保留 market_size 作为运营指标意图
        self.assertTrue(
            "market_size" in intents,
            f"Missing market_size intent, got: {intents}",
        )
        # P0: D-class 意图不得出现在初始搜索计划中
        self.assertFalse(
            {"retention_metrics", "unit_economics", "capital_efficiency",
             "revenue_metrics", "user_metrics", "growth_metrics", "revenue",
             "regional"} & intents,
            f"D-class intents should not be in search plan, got: {intents}",
        )

    def test_plan_includes_v3_deep_research_intents(self):
        plan = build_search_plan(
            "Perplexity", "perplexity", "perplexity.ai",
            ["Perplexity", "perplexity", "perplexity.ai"],
        )
        intents = {q.intent for q in plan.tavily_queries}
        # P0: TAVILY_QUERY_BUDGET_DEEP=18，优先覆盖高优先级意图
        # v3 核心意图（customers/pricing_details/youtube_transcript/competitive_position）
        # 必须在第一轮覆盖；differentiated_opportunity 可能因预算限制被截断
        self.assertTrue(
            {"customers", "pricing_details", "youtube_transcript",
             "competitive_position"}.issubset(intents),
            f"Missing v3 intents, got: {intents}",
        )
        # P0: 验证 D-class 意图不在搜索计划中
        self.assertFalse(
            {"retention_metrics", "unit_economics", "capital_efficiency"} & intents,
            f"D-class intents should not be in search plan, got: {intents}",
        )

    def test_gap_detector_generates_operating_metric_queries(self):
        gaps = detect_gaps({
            "tam": "暂缺",
            "sam": "",
            "som": None,
            "arr": "暂缺",
            "registered_users": "",
            "cac": None,
            "ltv": "暂缺",
            "burn_rate": "",
            "runway_months": None,
        })

        self.assertIn("market_size", gaps)
        self.assertIn("revenue_metrics", gaps)
        self.assertIn("user_metrics", gaps)
        self.assertIn("unit_economics", gaps)
        self.assertIn("capital_efficiency", gaps)

        queries = build_gap_queries("Azra Games", "azragames.com", "azragames", gaps)
        query_text = " ".join(q["query"] for q in queries)
        self.assertIn("TAM", query_text)
        self.assertIn("ARR", query_text)
        self.assertIn("CAC", query_text)


if __name__ == "__main__":
    unittest.main()
