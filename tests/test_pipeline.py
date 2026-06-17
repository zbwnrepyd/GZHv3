import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import pipeline
import repositories.field_repo as field_repo


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"{self.status_code} Error")

    def json(self):
        return self._payload


class PipelineFailureTests(unittest.TestCase):
    def test_extract_json_accepts_uppercase_fence_and_prose(self):
        text = """这里是结果：

```JSON
{"company_type": "AI工具", "data_confidence": "中"}
```

以上。"""

        parsed = pipeline._extract_json(text)

        self.assertEqual(parsed["company_type"], "AI工具")
        self.assertEqual(parsed["data_confidence"], "中")

    def test_extract_json_accepts_prose_wrapped_object(self):
        text = '结果如下：{"company_type": "AI搜索", "data_confidence": "高"} 请查收。'

        parsed = pipeline._extract_json(text)

        self.assertEqual(parsed["company_type"], "AI搜索")
        self.assertEqual(parsed["data_confidence"], "高")

    def test_l3_error_fails_before_writing_database(self):
        bad_records = [{"company_name": "BadCo", "version": "standard", "_error": "bad json"}]
        with patch.object(pipeline, "_collect_via_adapters", return_value={}), \
             patch.object(pipeline, "llm_analysis", return_value=bad_records), \
             patch("services.entity_sync_service.EntitySyncService.sync_from_llm_result", return_value={}):
            with self.assertRaises(RuntimeError):
                pipeline.run_pipeline("BadCo", "https://bad.example")

    def test_run_pipeline_cancel_token_stops_after_collection_before_llm(self):
        with patch.object(pipeline, "_collect_via_adapters", return_value={"_source_summary": {}}), \
             patch.object(pipeline, "llm_analysis") as llm_analysis, \
             patch("services.entity_sync_service.EntitySyncService.sync_from_llm_result", return_value={}):
            with self.assertRaises(pipeline.PipelineCancelledError):
                pipeline.run_pipeline(
                    "CancelCo",
                    "https://cancel.example",
                    cancel_token=lambda: True,
                )

        llm_analysis.assert_not_called()

    def test_l3_identity_mismatch_fails_before_writing_database(self):
        mismatched_records = [
            {
                "company_name": "Sardine",
                "version": "standard",
                "website_url": "https://www.perplexity.ai",
                "company_type": "AI原生搜索引擎",
                "data_confidence": "中",
            }
        ]
        with patch.object(pipeline, "_collect_via_adapters", return_value={"website": {"text": "ok"}}), \
             patch.object(pipeline, "llm_analysis", return_value=mismatched_records), \
             patch.object(field_repo, "insert_research_fields_batch"), \
             patch.object(pipeline, "_search_tavily") as search_tavily, \
             patch("services.entity_sync_service.EntitySyncService.sync_from_llm_result", return_value={}), \
             patch("asset_pipeline.collect_image_variants_pipeline", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "公司身份校验失败"):
                pipeline.run_pipeline("Sardine", "https://www.sardine.ai")

        search_tavily.assert_not_called()

    def test_l3_retries_missing_founder_fields_inside_main_flow(self):
        def record(founder_edu="暂缺", founder_achievement="暂缺"):
            return {
                "company_type": "AI工具",
                "founder_name": "Ada Demo",
                "founder_edu": founder_edu,
                "founder_bg": "前研究员",
                "founder_achievement": founder_achievement,
                "data_confidence": "中",
            }

        responses = [
            "创始人 Ada Demo 毕业于 MIT，曾创办 Demo Labs 并获行业奖项。",  # L0
            "layer1",                                                       # L1
            "layer2",                                                       # L2
            # ── standard 版本 ──
            str(record()).replace("'", '"'),                                # L3
            str(record("MIT", "创办 Demo Labs，获行业奖项")).replace("'", '"'),  # founder
            # ── business 版本 ──
            str(record()).replace("'", '"'),                                # L3
            str(record("MIT", "创办 Demo Labs")).replace("'", '"'),         # founder
            # ── spread 版本 ──
            str(record()).replace("'", '"'),                                # L3
            str(record("MIT", "创办 Demo Labs")).replace("'", '"'),         # founder
        ]
        events = []

        with patch.object(pipeline, "call_deepseek", side_effect=responses) as call, \
             patch.object(pipeline, "_extract_enum_fields", return_value={}):
            records = pipeline.llm_analysis(
                "DemoCo",
                "https://demo.example",
                {"website": {"text": "demo"}},
                lambda stage, detail: events.append((stage, detail)),
            )

        self.assertEqual(call.call_count, 9)
        self.assertEqual(records[0]["founder_edu"], "MIT")
        self.assertEqual(records[0]["founder_achievement"], "创办 Demo Labs，获行业奖项")
        self.assertFalse(any(stage == "补抓" for stage, _ in events))

    def test_collection_source_summary_counts_success_and_failures(self):
        tavily = pipeline._summarize_collection_source(
            "tavily",
            [
                {"results": [{"title": "A"}, {"title": "B"}]},
                {"error": "quota", "results": []},
            ],
        )
        github = pipeline._summarize_collection_source(
            "github", {"items": [{"name": "repo"}]}
        )
        youtube = pipeline._summarize_collection_source(
            "youtube", {"items": [], "note": "no API key"}
        )
        website = pipeline._summarize_collection_source(
            "website", {"text": "hello world"}
        )

        self.assertEqual(tavily["status"], "ok")
        self.assertEqual(tavily["count"], 2)
        self.assertIn("quota", tavily["detail"])
        self.assertEqual(github["count"], 1)
        self.assertEqual(youtube["status"], "skipped")
        self.assertEqual(website["count"], 11)

    def test_collect_via_adapters_reports_structured_source_details(self):
        # SPEC v3: _collect_via_adapters is the only collection path.
        # When no adapters load, it raises RuntimeError (no fallback).
        events = []

        def on_progress(stage, detail):
            events.append((stage, detail))

        with patch.object(pipeline, "build_source_plan") as mock_plan, \
             patch.object(pipeline.config, "USE_FIELD_DRIVEN_COLLECTION", True):
            mock_plan.return_value = type('obj', (object,), {
                'adapters': [],
                'total_estimated_queries': 0,
                'd_class_fields_skipped': [],
                'field_to_source_map': {},
            })()

            with self.assertRaises(RuntimeError):
                pipeline._collect_via_adapters("DemoCo", "https://demo.example", on_progress)

    def test_tavily_search_tries_next_key_after_quota_limit(self):
        calls = []

        def fake_post(url, json, timeout, proxies=None):
            calls.append(json["api_key"])
            if json["api_key"] == "quota-key":
                return FakeResponse(
                    432,
                    {"detail": {"error": "usage limit"}},
                    "usage limit",
                )
            return FakeResponse(200, {"results": [{"title": "ok"}]})

        with patch.object(pipeline.config, "TAVILY_API_KEYS", ["quota-key", "working-key"]), \
             patch.object(pipeline.requests, "post", side_effect=fake_post):
            results = pipeline._search_tavily("DemoCo")

        self.assertEqual(results[0]["results"], [{"title": "ok"}])
        self.assertEqual(results[1]["results"], [{"title": "ok"}])
        self.assertEqual(
            calls,
            ["quota-key", "working-key", "quota-key", "working-key"],
        )

    def test_tavily_search_reports_partial_collection_progress(self):
        events = []
        queries = [
            {"query": "DemoCo ARR", "intent": "revenue_metrics"},
            {"query": "DemoCo users", "intent": "user_metrics"},
            {"query": "DemoCo TAM", "intent": "market_size"},
        ]

        def fake_query(query, **kwargs):
            return {"results": [{"title": query, "url": f"https://example.com/{len(events)}"}]}

        with patch.object(pipeline, "_search_tavily_query", side_effect=fake_query):
            batches = pipeline._search_tavily(
                queries,
                progress_callback=lambda stage, detail: events.append((stage, detail)),
            )

        self.assertEqual(len(batches), 3)
        progress_events = [
            detail for stage, detail in events
            if stage == "采集" and isinstance(detail, dict) and "sources" in detail
        ]
        self.assertGreaterEqual(len(progress_events), 3)
        self.assertEqual(progress_events[0]["sources"]["tavily"]["status"], "collecting")
        self.assertEqual(progress_events[-1]["sources"]["tavily"]["count"], 3)
        self.assertIn("3/3", progress_events[-1]["sources"]["tavily"]["detail"])

    def test_tavily_query_uses_cache_for_repeated_query(self):
        calls = []

        def fake_post(url, json, timeout, proxies=None):
            calls.append(json["query"])
            return FakeResponse(200, {"results": [{"title": "cached", "url": "https://example.com"}]})

        with patch.object(pipeline.config, "TAVILY_API_KEYS", ["working-key"]), \
             patch.object(pipeline.config, "TAVILY_CACHE_TTL_SECONDS", 3600), \
             patch.object(pipeline.requests, "post", side_effect=fake_post):
            pipeline._TAVILY_QUERY_CACHE.clear()
            first = pipeline._search_tavily_query("DemoCo market size")
            second = pipeline._search_tavily_query("DemoCo market size")

        self.assertEqual(first, second)
        self.assertEqual(calls, ["DemoCo market size"])

    def test_pre_gap_refetch_skips_when_website_content_is_sufficient(self):
        raw = {
            "_source_summary": {
                "tavily": {"unique_url_count": 0, "intent_count": 0},
                "website": {"count": 1800, "status": "ok"},
                "github": {"count": 1, "status": "ok"},
            },
            "display_name": "DemoCo",
            "website_host": "demo.example",
            "aliases": ["DemoCo"],
        }

        self.assertFalse(pipeline._needs_pre_gap_refetch(raw))

    def test_gap_queries_are_limited_to_top_priority_intents(self):
        # P0: COLLECTION_GAP_QUERY_LIMIT=4，补采最多 4 条 query
        # D/E class fields filtered by build_gap_queries
        gaps = {
            "founders": ["founder_edu"],
            "market_size": ["tam", "market_cagr"],
            "pricing_details": ["pricing_summary"],
            "product": ["main_product_name"],
            "customers": ["customer_names"],
            "competitive_position": ["competitive_position"],
            "differentiated_opportunity": ["differentiated_opportunity"],
        }

        selected = pipeline._prioritize_gap_queries(gaps, "DemoCo", "demo.example", "demo")
        intents = {q["intent"] for q in selected}

        self.assertEqual(len(selected), pipeline.config.COLLECTION_GAP_QUERY_LIMIT)
        # 验证补采数量不超过限制
        self.assertLessEqual(len(selected), 4)

    def test_tavily_query_defaults_to_advanced_raw_content(self):
        bodies = []

        def fake_post(url, json, timeout, proxies=None):
            bodies.append(json)
            return FakeResponse(200, {"results": [{"title": "ok"}]})

        with patch.object(pipeline.config, "TAVILY_API_KEYS", ["working-key"]), \
             patch.object(pipeline.requests, "post", side_effect=fake_post):
            pipeline._TAVILY_QUERY_CACHE.clear()
            pipeline._search_tavily_query("DemoCo raw content test")

        self.assertEqual(bodies[0]["search_depth"], "advanced")
        self.assertTrue(bodies[0]["include_raw_content"])

    def test_adaptive_initial_tavily_queries_use_basic_without_raw_content(self):
        plan = SimpleNamespace(
            tavily_queries=[
                SimpleNamespace(query=f"DemoCo query {i}", intent="overview", term="DemoCo")
                for i in range(12)
            ]
        )

        with patch.object(pipeline.config, "TAVILY_ADAPTIVE_MODE", True), \
             patch.object(pipeline.config, "TAVILY_INITIAL_QUERY_LIMIT", 10), \
             patch.object(pipeline.config, "TAVILY_INITIAL_SEARCH_DEPTH", "basic"), \
             patch.object(pipeline.config, "TAVILY_INITIAL_INCLUDE_RAW_CONTENT", False):
            selected = pipeline._initial_tavily_queries(plan)

        self.assertEqual(len(selected), 10)
        self.assertEqual(selected[0]["query"], "DemoCo query 0")
        self.assertEqual(selected[-1]["query"], "DemoCo query 9")
        self.assertTrue(all(q["search_depth"] == "basic" for q in selected))
        self.assertTrue(all(q["include_raw_content"] is False for q in selected))

    def test_adaptive_escalation_uses_advanced_and_raw_content_for_priority_intents(self):
        plan = SimpleNamespace(
            tavily_queries=[
                SimpleNamespace(query="DemoCo TAM", intent="market_size", term="DemoCo"),
                SimpleNamespace(query="DemoCo pricing", intent="pricing_details", term="DemoCo"),
                SimpleNamespace(query="DemoCo competitors", intent="competitive_position", term="DemoCo"),
            ]
        )
        quality = {
            "missing_key_intents": [
                "market_size",
                "pricing_details",
                "competitive_position",
            ]
        }

        with patch.object(pipeline.config, "TAVILY_ADAPTIVE_MODE", True), \
             patch.object(pipeline.config, "TAVILY_ESCALATE_SEARCH_DEPTH", "advanced"), \
             patch.object(pipeline.config, "TAVILY_ESCALATE_INCLUDE_RAW_CONTENT", False), \
             patch.object(pipeline.config, "TAVILY_ESCALATE_RAW_CONTENT_INTENTS", ["market_size", "pricing_details"]), \
             patch.object(pipeline.config, "COLLECTION_GAP_QUERY_LIMIT", 5):
            selected = pipeline._build_escalation_queries(plan, quality)

        by_intent = {q["intent"]: q for q in selected}
        self.assertEqual(len(selected), 3)
        self.assertTrue(all(q["search_depth"] == "advanced" for q in selected))
        self.assertTrue(by_intent["market_size"]["include_raw_content"])
        self.assertTrue(by_intent["pricing_details"]["include_raw_content"])
        self.assertFalse(by_intent["competitive_position"]["include_raw_content"])

    def test_prepare_raw_data_for_llm_trims_tavily_raw_content(self):
        raw = {
            "company_name": "DemoCo",
            "company_key": "democo",
            "display_name": "DemoCo",
            "website_host": "demo.example",
            "company_url": "https://demo.example",
            "aliases": ["DemoCo"],
            "_source_summary": {"tavily": {"unique_url_count": 5}},
            "_source_warnings": [],
            "_evidence_pool": [],
            "tavily": [
                {
                    "answer": "answer",
                    "results": [
                        {
                            "title": "Useful result",
                            "url": "https://example.com/useful",
                            "content": "short summary",
                            "score": 0.91,
                            "raw_content": "x" * 20000,
                            "extra": "drop me",
                        }
                    ],
                }
            ],
            "website": {"text": "homepage"},
            "github": {},
            "youtube": {},
        }

        prepared = pipeline._prepare_raw_data_for_llm(raw)

        # P0: 噪音与上下文治理 — 使用 packed_context / evidence_summary，不再传 raw_sources
        self.assertIn("company_identity", prepared)
        self.assertIn("source_audit", prepared)
        # raw_sources 不再进入 L0
        self.assertNotIn("raw_sources", prepared)
        # evidence_pool 不再直接进入 L0（改用 evidence_summary 或 packed_context）
        self.assertNotIn("evidence_pool", prepared)
        # 回退模式应包含 evidence_summary
        self.assertIn("evidence_summary", prepared)

        # 验证原始数据未被修改
        self.assertEqual(raw["tavily"][0]["results"][0]["raw_content"], "x" * 20000)

    def test_enum_group_ignores_non_object_llm_json(self):
        with patch.object(pipeline, "_load_prompt_text", return_value="prompt"), \
             patch.object(pipeline, "call_deepseek", return_value='"not an object"'):
            fields = pipeline._run_llm_enum_group("key", "A", "{}")

        self.assertEqual(fields, {})

    def test_run_pipeline_writes_field_rows_under_requested_company_name(self):
        inserted_batches = []
        records = [
            {
                "company_name": "limitless",
                "version": "standard",
                "company_type": "AI wearable",
                "company_def": "AI meeting memory platform",
                "data_confidence": "高",
            }
        ]

        with patch.object(pipeline, "_collect_via_adapters", return_value={
                "company_name": "Limitless",
                "company_key": "limitless_ai",
                "display_name": "Limitless",
                "website": {"text": "ok"},
                "_source_summary": {},
            }), \
             patch.object(pipeline, "llm_analysis", return_value=[dict(records[0])]), \
             patch.object(pipeline.config, "COLLECTION_ENABLE_GAP_REFETCH", False), \
             patch.object(field_repo, "insert_research_fields_batch", side_effect=lambda _db, rows: inserted_batches.append(rows) or len(rows)), \
             patch("services.entity_sync_service.EntitySyncService.sync_from_llm_result", return_value={}), \
             patch("services.card_value_builder.CardValueBuilder.build_card_values", return_value=[]), \
             patch("services.card_value_builder.CardValueBuilder.write_to_final_card_values", return_value=0), \
             patch("asset_pipeline.collect_image_variants_pipeline", return_value={}):
            ids = pipeline.run_pipeline("Limitless", "https://www.limitless.ai")

        self.assertIsInstance(ids, list)
        self.assertTrue(inserted_batches)
        self.assertTrue(all(row["company_name"] == "Limitless" for row in inserted_batches[0]))
        self.assertTrue(any(row["field_key"] == "company_type" for row in inserted_batches[0]))


if __name__ == "__main__":
    unittest.main()
