import json
import os
import sys
import time
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

    def test_collect_via_adapters_cancel_token_stops_while_adapter_is_running(self):
        class SlowAdapter:
            def collect(self, company_identity, field_targets, budget):
                time.sleep(2)
                return []

        fake_identity = SimpleNamespace(
            company_key="cancelco",
            display_name="CancelCo",
            input_name="CancelCo",
            website_url="https://cancel.example",
            website_host="cancel.example",
            aliases=[],
        )
        fake_plan = SimpleNamespace(
            adapters=[{
                "adapter_family": "slow",
                "field_targets": ["company_name"],
                "budget": {},
            }],
            field_to_source_map={},
            total_estimated_queries=1,
            d_class_fields_skipped=[],
        )

        def fake_import(name, fromlist=(), *args, **kwargs):
            if name == "research.adapters.slow_adapter":
                return SimpleNamespace(SlowAdapter=SlowAdapter)
            return __import__(name, globals(), locals(), fromlist, 0)

        started = time.monotonic()
        with patch.object(pipeline, "build_company_identity", return_value=fake_identity), \
             patch.object(pipeline, "build_source_plan", return_value=fake_plan), \
             patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(pipeline.PipelineCancelledError):
                pipeline._collect_via_adapters(
                    "CancelCo",
                    "https://cancel.example",
                    cancel_token=lambda: time.monotonic() - started > 0.2,
                )

        self.assertLess(time.monotonic() - started, 1.5)

    def test_research_options_add_prefetch_and_supplemental_adapters(self):
        plan = SimpleNamespace(
            adapters=[{
                "adapter_family": "tavily_search",
                "field_targets": ["company_name"],
                "budget": {"max_queries": 14},
            }],
            field_to_source_map={},
            total_estimated_queries=14,
        )
        card_fields = [
            "company_name", "funding_info", "product_tech_stack",
            "founder_name", "main_product_name", "ltv",
        ]

        pipeline._apply_research_options_to_source_plan(
            plan,
            card_fields,
            {
                "official_site": True,
                "scrapling_search": True,
                "github": True,
                "youtube": True,
            },
        )

        families = [entry["adapter_family"] for entry in plan.adapters]
        self.assertEqual(families[:2], ["official_site", "scrapling_search"])
        self.assertNotIn("tavily_search", families)
        self.assertIn("github", families)
        self.assertIn("youtube", families)
        self.assertIn("openbb", families)
        self.assertIn("whatweb", families)
        scrapling_entry = next(e for e in plan.adapters if e["adapter_family"] == "scrapling_search")
        self.assertNotIn("ltv", scrapling_entry["field_targets"])

    def test_card_set_field_targets_cover_v1_v2_v3_union(self):
        fields = pipeline._load_card_set_field_targets()

        self.assertEqual(len(fields), 87)
        self.assertIn("timeline_events", fields)
        self.assertIn("competitors_summary", fields)
        self.assertIn("competitors_top3", fields)
        self.assertIn("company_def", fields)
        self.assertIn("product_tech_stack", fields)

    def test_complete_contract_fields_fills_all_fields_json_keys(self):
        record = {
            "company_name": "DemoCo",
            "version": "standard",
            "company_type": "AI工具",
        }

        completed = pipeline._complete_contract_fields(record)
        contract_keys = pipeline._load_field_contract_keys()

        self.assertGreaterEqual(len(contract_keys), 115)
        self.assertTrue(all(key in completed for key in contract_keys))
        self.assertEqual(completed["company_type"], "AI工具")
        self.assertEqual(completed["company_def"], "暂缺")

    def test_execute_adapter_instances_records_empty_results(self):
        class EmptyAdapter:
            def collect(self, company_identity, field_targets, budget):
                return []

        docs, summary = pipeline._execute_adapter_instances(
            [{
                "adapter": EmptyAdapter(),
                "entry": {
                    "adapter_family": "scrapling_search",
                    "field_targets": ["company_name"],
                    "budget": {},
                },
            }],
            {"display_name": "DemoCo"},
        )

        self.assertEqual(docs, [])
        self.assertEqual(summary["scrapling_search"]["status"], "empty")

    def test_execute_adapter_instances_uses_adapter_diagnostics_for_empty_results(self):
        class DiagnosticAdapter:
            last_summary = {}

            def collect(self, company_identity, field_targets, budget):
                self.last_summary = {
                    "status": "empty",
                    "count": 0,
                    "query_count": 4,
                    "serp_ok_count": 2,
                    "parsed_url_count": 8,
                    "fetched_url_count": 0,
                    "failed_url_count": 8,
                    "detail": "SERP成功 2/4，解析URL 8，有效文档 0",
                }
                return []

        docs, summary = pipeline._execute_adapter_instances(
            [{
                "adapter": DiagnosticAdapter(),
                "entry": {
                    "adapter_family": "scrapling_search",
                    "field_targets": ["company_name"],
                    "budget": {},
                },
            }],
            {"display_name": "DemoCo"},
        )

        self.assertEqual(docs, [])
        self.assertEqual(summary["scrapling_search"]["parsed_url_count"], 8)
        self.assertIn("SERP成功", summary["scrapling_search"]["detail"])

    def test_execute_adapter_instances_hard_timeout_returns_without_waiting_for_worker(self):
        class SlowAdapter:
            def collect(self, company_identity, field_targets, budget):
                time.sleep(2)
                return []

        started = time.monotonic()
        with patch.dict(os.environ, {"ADAPTER_HARD_TIMEOUT_SECONDS": "1"}):
            docs, summary = pipeline._execute_adapter_instances(
                [{
                    "adapter": SlowAdapter(),
                    "entry": {
                        "adapter_family": "official_site",
                        "field_targets": ["company_name"],
                        "budget": {},
                    },
                }],
                {"display_name": "DemoCo"},
            )

        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.5)
        self.assertEqual(docs, [])
        self.assertEqual(summary["official_site"]["status"], "failed")
        self.assertIn("超时", summary["official_site"]["detail"])

    def test_execute_adapter_instances_uses_budget_hard_timeout_override(self):
        class SlowAdapter:
            def collect(self, company_identity, field_targets, budget):
                time.sleep(0.15)
                return [SimpleNamespace(content="ok")]

        with patch.dict(os.environ, {"ADAPTER_HARD_TIMEOUT_SECONDS": "0"}):
            docs, summary = pipeline._execute_adapter_instances(
                [{
                    "adapter": SlowAdapter(),
                    "entry": {
                        "adapter_family": "official_site",
                        "field_targets": ["company_name"],
                        "budget": {"hard_timeout_seconds": 1},
                    },
                }],
                {"display_name": "DemoCo"},
            )

        self.assertEqual(len(docs), 1)
        self.assertEqual(summary["official_site"]["status"], "ok")

    def test_special_adapter_class_names_load(self):
        self.assertEqual(
            pipeline._load_adapter_instance("youtube").__class__.__name__,
            "YoutubeTranscriptAdapter",
        )
        self.assertEqual(
            pipeline._load_adapter_instance("producthunt").__class__.__name__,
            "ProductHuntAdapter",
        )
        self.assertEqual(
            pipeline._load_adapter_instance("whatweb").__class__.__name__,
            "WhatWebAdapter",
        )

    def test_github_adapter_imports_agent_from_webapp_cwd(self):
        from research.adapters.github_adapter import _load_github_agent_class

        cls = _load_github_agent_class()

        self.assertEqual(cls.__name__, "GitHubAgent")

    def test_apply_research_options_keeps_tavily_out_of_initial_adapter_plan(self):
        source_plan = type('obj', (object,), {
            'adapters': [
                {
                    "adapter_family": "tavily_search",
                    "field_targets": ["company_name"],
                    "budget": {},
                    "priority": "high",
                },
                {
                    "adapter_family": "official_site",
                    "field_targets": ["company_name"],
                    "budget": {},
                    "priority": "high",
                },
            ],
            'total_estimated_queries': 0,
            'field_to_source_map': {},
        })()

        result = pipeline._apply_research_options_to_source_plan(
            source_plan,
            ["company_name", "product_tech_stack"],
            {
                "official_site": True,
                "scrapling_search": True,
                "tavily_search": True,
                "tavily_extract": True,
                "github": True,
                "youtube": True,
                "producthunt": True,
                "whatweb": True,
            },
        )

        families = [entry["adapter_family"] for entry in result.adapters]
        self.assertNotIn("tavily_search", families)
        self.assertNotIn("tavily_extract", families)
        self.assertLess(families.index("scrapling_search"), families.index("github"))
        self.assertIn("whatweb", families)

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

        l0_valid_json = json.dumps({
            "company_name": "DemoCo",
            "company_def": (
                "An AI tools company founded by Ada Demo, an MIT graduate who previously "
                "founded Demo Labs and won industry awards. The company provides innovative "
                "solutions for the enterprise market with a focus on automation and "
                "productivity. Their flagship product DemoTool serves thousands of customers "
                "worldwide and has been recognized as a leader in the AI-powered developer "
                "tools space by multiple industry analysts. The company operates on a SaaS "
                "business model with annual recurring revenue exceeding benchmarks for its stage."
            ),
            "main_product_name": "DemoTool",
            "founded_date": "2020",
            "company_type": "AI工具",
        }, ensure_ascii=False)

        # New split-L3 path: each version needs A+B+C+founder = 4 calls,
        # plus L0+L1+L2 = 15 total.  A/B return empty-object JSON; C carries
        # the actual record (with missing founder fields); founder retry
        # returns the filled-in record.
        empty_obj = "{}"
        responses = [
            l0_valid_json,                                                 # L0
            "layer1",                                                       # L1
            "layer2",                                                       # L2
            # ── standard 版本 ──
            empty_obj,                                                      # A
            empty_obj,                                                      # B
            str(record()).replace("'", '"'),                                # C
            str(record("MIT", "创办 Demo Labs，获行业奖项")).replace("'", '"'),  # founder
            # ── business 版本 ──
            empty_obj,                                                      # A
            empty_obj,                                                      # B
            str(record()).replace("'", '"'),                                # C
            str(record("MIT", "创办 Demo Labs")).replace("'", '"'),         # founder
            # ── spread 版本 ──
            empty_obj,                                                      # A
            empty_obj,                                                      # B
            str(record()).replace("'", '"'),                                # C
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

        self.assertEqual(call.call_count, 15)
        # C calls use timeout=240 / max_retries=5 (indices 5, 9, 13)
        for index in (5, 9, 13):
            self.assertEqual(call.call_args_list[index].kwargs["timeout"], 240)
            self.assertEqual(call.call_args_list[index].kwargs["max_retries"], 5)
        self.assertEqual(records[0]["founder_edu"], "MIT")
        self.assertEqual(records[0]["founder_achievement"], "创办 Demo Labs，获行业奖项")
        self.assertFalse(any(stage == "补抓" for stage, _ in events))

    def test_l3_main_retries_and_records_error_for_non_object_json(self):
        l0_valid_json = json.dumps({
            "company_name": "DemoCo",
            "company_def": (
                "An AI company providing developer tools for the modern web. Founded with "
                "a mission to simplify software development workflows across teams of all "
                "sizes. The platform offers integrated CI/CD, monitoring, and collaboration "
                "features designed to accelerate deployment velocity while maintaining "
                "enterprise-grade security and reliability standards across cloud and on-premise "
                "environments worldwide. The company serves Fortune 500 enterprises."
            ),
            "main_product_name": "DemoTool",
            "founded_date": "2021",
        }, ensure_ascii=False)

        # Split-L3 path: A/B return valid empty objects, C returns non-object JSON.
        # C is retried once; after second attempt it raises RuntimeError (blocking).
        responses = [
            l0_valid_json,       # L0
            "layer1",             # L1
            "layer2",             # L2
            # standard version — A/B valid, C returns non-object twice
            "{}",                 # A
            "{}",                 # B
            '"not an object"',    # C attempt 1
            '"still not valid"',  # C attempt 2 → RuntimeError
        ]

        with patch.object(pipeline, "call_deepseek", side_effect=responses):
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.llm_analysis(
                    "DemoCo",
                    "https://demo.example",
                    {"website": {"text": "demo"}},
                )
            self.assertIn("L3-C", str(ctx.exception))

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
                pipeline._collect_via_adapters(
                    "DemoCo",
                    "https://demo.example",
                    on_progress,
                    research_options={
                        "official_site": False,
                        "scrapling_search": False,
                        "tavily_search": False,
                        "tavily_extract": False,
                        "github": False,
                        "producthunt": False,
                        "youtube": False,
                        "sec": False,
                        "openbb": False,
                        "companieshouse": False,
                        "whatweb": False,
                    },
                )

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

    def test_l3_value_gap_refetch_skips_when_required_fields_have_values(self):
        record = {
            "company_name": "DemoCo",
            "version": "standard",
            "company_def": "DemoCo 是一款 AI 设计工具。",
            "market_track": "AI 设计工具",
            "market_subtrack": "消费级图像编辑",
            "market_landscape_summary": "AI 设计工具赛道快速增长。",
            "core_business": "提供 AI 图片生成与编辑。",
            "competitors_top3": "[\"A\", \"B\", \"C\"]",
            "competitive_position": "DemoCo 面向专业创作者。",
        }

        report = pipeline._evaluate_l3_value_gaps(record)

        self.assertFalse(report["should_refetch"])
        self.assertEqual(report["missing_required_fields"], [])
        self.assertGreater(report["usable_field_count"], 0)

    def test_l3_value_gap_refetch_fails_when_no_contract_fields_are_usable(self):
        record = {
            "company_name": "DemoCo",
            "version": "standard",
            "summary": "不是契约字段",
        }

        with self.assertRaises(RuntimeError):
            pipeline._evaluate_l3_value_gaps(record)

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

    def test_enum_group_returns_empty_when_llm_omits_json(self):
        with patch.object(pipeline, "_load_prompt_text", return_value="prompt"), \
             patch.object(pipeline, "call_deepseek", return_value="无法根据上下文判断这些枚举字段。"):
            fields = pipeline._run_llm_enum_group("key", "A", "{}")

        self.assertEqual(fields, {})

    def test_enum_group_returns_empty_when_json_parser_raises(self):
        with patch.object(pipeline, "_load_prompt_text", return_value="prompt"), \
             patch.object(pipeline, "call_deepseek", return_value="bad json"), \
             patch.object(pipeline, "_extract_json", side_effect=ValueError("Cannot parse JSON")):
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

    def test_run_pipeline_respects_disabled_image_collection(self):
        records = [
            {
                "company_name": "DemoCo",
                "version": "standard",
                "company_type": "AI工具",
                "company_def": "Demo product",
                "data_confidence": "中",
            }
        ]
        progress = []

        with patch.object(pipeline, "_collect_via_adapters", return_value={
                "company_name": "DemoCo",
                "company_key": "democo",
                "display_name": "DemoCo",
                "website": {"text": "ok"},
                "_source_summary": {},
            }), \
             patch.object(pipeline, "llm_analysis", return_value=[dict(records[0])]), \
             patch.object(pipeline.config, "COLLECTION_ENABLE_GAP_REFETCH", False), \
             patch.object(field_repo, "insert_research_fields_batch", return_value=1), \
             patch("services.entity_sync_service.EntitySyncService.sync_from_llm_result", return_value={}), \
             patch("services.card_value_builder.CardValueBuilder.build_card_values", return_value=[]), \
             patch("services.card_value_builder.CardValueBuilder.write_to_final_card_values", return_value=0), \
             patch("asset_pipeline.collect_image_variants_pipeline") as collect_images:
            pipeline.run_pipeline(
                "DemoCo",
                "https://demo.example",
                progress_callback=lambda stage, detail: progress.append((stage, detail)),
                research_options={"image_collection": False},
            )

        collect_images.assert_not_called()
        self.assertTrue(any(stage == "图片采集跳过" for stage, _detail in progress))

    def test_mark_and_log_fields_passes_run_id_to_entity_sync(self):
        field_rows = [
            {
                "company_name": "DemoCo",
                "company_key": "democo",
                "field_key": "company_type",
                "field_value": "AI工具",
            }
        ]

        with patch("research.field_status._load_manifest", return_value={}), \
             patch("research.evidence_extractor.build_evidence_map", return_value={}), \
             patch("research.field_resolver.resolve_all") as resolve_all, \
             patch("repositories.field_repo.update_field_status_batch"), \
             patch.object(pipeline.config, "ENTITY_TABLES_PRIMARY", True), \
             patch("services.entity_sync_service.EntitySyncService.sync_from_llm_result", return_value={}) as sync:
            resolve_all.return_value = {
                "company_type": SimpleNamespace(
                    value="AI工具",
                    resolution_status="llm_extracted",
                    unavailable_reason="",
                    resolution_method="llm",
                )
            }

            pipeline._mark_and_log_fields(
                "unused.sqlite",
                "DemoCo",
                "standard",
                field_rows,
                run_id="run-123",
            )

        sync.assert_called_once()
        self.assertEqual(sync.call_args.kwargs["run_id"], "run-123")

    def test_bind_field_value_evidence_creates_spans_from_field_values_and_chunks(self):
        """LLM后、分辨率前：字段值在chunks中出现时创建 evidence_spans。"""
        import sqlite3, tempfile

        db_path = os.path.join(tempfile.mkdtemp(), "test_evidence.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS document_chunks ("
            "id INTEGER PRIMARY KEY, document_id INTEGER, chunk_text TEXT, "
            "is_noise INTEGER DEFAULT 0, final_score REAL DEFAULT 0.5)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS evidence_spans ("
            "id INTEGER PRIMARY KEY, document_id INTEGER, company_key TEXT, "
            "field_key TEXT, quote_text TEXT, normalized_fact TEXT, "
            "confidence REAL, created_by_agent TEXT, "
            "start_offset INTEGER DEFAULT 0, end_offset INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO document_chunks(id, document_id, chunk_text, is_noise, final_score) "
            "VALUES (1, 1, 'DemoCo is an AI SaaS platform for enterprise automation.', 0, 0.7)"
        )
        conn.commit()
        conn.close()

        field_rows = [
            {"field_key": "company_type", "field_value": "AI SaaS"},
            {"field_key": "company_def", "field_value": "enterprise automation platform"},
            {"field_key": "founding_year", "field_value": "2020"},
            {"field_key": "unknown_field", "field_value": "暂缺"},
        ]

        count = pipeline._bind_field_value_evidence(
            db_path, "democo", "DemoCo", field_rows, [1]
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        spans = conn.execute("SELECT * FROM evidence_spans").fetchall()
        conn.close()

        self.assertGreater(count, 0, "Should create at least one evidence span")
        self.assertGreaterEqual(len(spans), 1)
        # Verify agent tag — must NOT be posthoc_weak_matcher
        for span in spans:
            self.assertNotEqual(
                span["created_by_agent"], "posthoc_weak_matcher",
                "field_value_matcher spans must not use the filtered agent tag")
            self.assertGreaterEqual(
                span["confidence"], 0.55,
                "Confidence should be >= 0.55 to pass build_evidence_map threshold")

    def test_field_value_evidence_allows_official_fact_confirmed(self):
        import sqlite3, tempfile
        from research.evidence_extractor import build_evidence_map
        from research.field_resolver import resolve_all

        db_path = os.path.join(tempfile.mkdtemp(), "test_confirmed.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
        CREATE TABLE document_chunks (
            id INTEGER PRIMARY KEY, document_id INTEGER, chunk_text TEXT,
            is_noise INTEGER DEFAULT 0, final_score REAL DEFAULT 0.7
        );
        CREATE TABLE evidence_spans (
            id INTEGER PRIMARY KEY, document_id INTEGER, company_key TEXT,
            field_key TEXT, quote_text TEXT, normalized_fact TEXT,
            confidence REAL, created_by_agent TEXT,
            start_offset INTEGER DEFAULT 0, end_offset INTEGER DEFAULT 0
        );
        """)
        conn.execute(
            "INSERT INTO document_chunks(id, document_id, chunk_text, final_score) VALUES (?, ?, ?, ?)",
            (1, 10, "Ideogram is an AI image generation platform for creators.", 0.7),
        )
        conn.commit()
        conn.close()

        field_rows = [{"field_key": "company_type", "field_value": "AI image generation platform"}]
        pipeline._bind_field_value_evidence(db_path, "ideogram.ai", "Ideogram", field_rows, [1])

        evidence_map = build_evidence_map(db_path, "ideogram.ai", ["company_type"])
        resolved = resolve_all(
            {"company_type": "AI image generation platform"},
            {"company_type": {"resolution_type": "official_fact", "category": "A"}},
            evidence_map=evidence_map,
        )

        self.assertEqual(resolved["company_type"].resolution_status, "confirmed")

    def test_bind_field_value_evidence_skips_when_no_chunks(self):
        count = pipeline._bind_field_value_evidence(
            ":memory:", "democo", "DemoCo",
            [{"field_key": "company_type", "field_value": "AI"}], []
        )
        self.assertEqual(count, 0)

    def test_producthunt_adapter_reports_not_configured_when_no_key(self):
        """ProductHunt 适配器缺 Key 时返回空 + not_configured 状态。"""
        from research.adapters.producthunt_adapter import ProductHuntAdapter

        adapter = ProductHuntAdapter()
        with patch.dict(os.environ, {}, clear=True):
            docs = adapter.collect(
                {"display_name": "TestCo", "website_host": "testco.com"},
                ["main_product_name"],
                {"max_documents": 1},
            )
        self.assertEqual(docs, [])
        self.assertEqual(adapter.last_summary.get("status"), "not_configured")

    def test_openbb_adapter_works_without_api_key_local_mode(self):
        """本地 OpenBB Platform 无需 API Key，不再返回 not_configured。"""
        from research.adapters.openbb_adapter import OpenBBAdapter

        adapter = OpenBBAdapter()
        with patch.dict(os.environ, {}, clear=True):
            docs = adapter.collect(
                {"display_name": "TestCo", "website_host": "testco.com"},
                ["company_revenue"],
                {"max_documents": 1},
            )
        # 不因缺少 API Key 而报 not_configured（本地部署无需 Key）
        self.assertNotEqual(adapter.last_summary.get("status"), "not_configured")

    def test_bind_field_value_evidence_matches_json_array_values(self):
        """Complex values like JSON arrays should be searchable in chunks."""
        import sqlite3, tempfile
        db_path = os.path.join(tempfile.mkdtemp(), "test_json.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
        CREATE TABLE document_chunks (id INTEGER PRIMARY KEY, document_id INTEGER, chunk_text TEXT, is_noise INTEGER DEFAULT 0, final_score REAL DEFAULT 0.5);
        CREATE TABLE evidence_spans (id INTEGER PRIMARY KEY, document_id INTEGER, company_key TEXT, field_key TEXT, quote_text TEXT, normalized_fact TEXT, confidence REAL, created_by_agent TEXT, start_offset INTEGER DEFAULT 0, end_offset INTEGER DEFAULT 0);
        """)
        conn.execute("INSERT INTO document_chunks(id, document_id, chunk_text, final_score) VALUES (1,1,'social media and SEO are the main channels for user acquisition',0.6)")
        conn.commit(); conn.close()

        field_rows = [
            {"field_key": "acquisition_channels", "field_value": '[{"name": "social media", "score": "high"}, {"name": "SEO", "score": "high"}]'},
        ]
        count = pipeline._bind_field_value_evidence(db_path, "test", "TestCo", field_rows, [1])
        self.assertGreater(count, 0, "Should match complex JSON values by extracting text")

    def test_bind_field_value_evidence_matches_short_numeric_values(self):
        """Short values like '2022' should match via >=4 char single token rule."""
        import sqlite3, tempfile
        db_path = os.path.join(tempfile.mkdtemp(), "test_num.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
        CREATE TABLE document_chunks (id INTEGER PRIMARY KEY, document_id INTEGER, chunk_text TEXT, is_noise INTEGER DEFAULT 0, final_score REAL DEFAULT 0.5);
        CREATE TABLE evidence_spans (id INTEGER PRIMARY KEY, document_id INTEGER, company_key TEXT, field_key TEXT, quote_text TEXT, normalized_fact TEXT, confidence REAL, created_by_agent TEXT, start_offset INTEGER DEFAULT 0, end_offset INTEGER DEFAULT 0);
        """)
        conn.execute("INSERT INTO document_chunks(id, document_id, chunk_text, final_score) VALUES (1,1,'Founded in 2022 by former Google researchers.',0.6)")
        conn.commit(); conn.close()

        field_rows = [{"field_key": "founding_year", "field_value": "2022"}]
        count = pipeline._bind_field_value_evidence(db_path, "test", "TestCo", field_rows, [1])
        self.assertGreater(count, 0, "Should match short values like '2022'")

    def test_bind_field_value_evidence_creates_multiple_spans_per_field(self):
        """A field value appearing in multiple chunks should get multiple spans (up to 3)."""
        import sqlite3, tempfile
        db_path = os.path.join(tempfile.mkdtemp(), "test_multi.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
        CREATE TABLE document_chunks (id INTEGER PRIMARY KEY, document_id INTEGER, chunk_text TEXT, is_noise INTEGER DEFAULT 0, final_score REAL DEFAULT 0.5);
        CREATE TABLE evidence_spans (id INTEGER PRIMARY KEY, document_id INTEGER, company_key TEXT, field_key TEXT, quote_text TEXT, normalized_fact TEXT, confidence REAL, created_by_agent TEXT, start_offset INTEGER DEFAULT 0, end_offset INTEGER DEFAULT 0);
        """)
        conn.executemany("INSERT INTO document_chunks(id, document_id, chunk_text, final_score) VALUES (?,?,?,?)", [
            (1,1,"Ideogram is an AI image generation platform.",0.7),
            (2,2,"The AI image generation platform Ideogram was founded in 2022.",0.6),
            (3,3,"As an AI image generation platform, Ideogram competes with Midjourney.",0.5),
        ])
        conn.commit(); conn.close()

        field_rows = [{"field_key": "company_type", "field_value": "AI image generation platform"}]
        count = pipeline._bind_field_value_evidence(db_path, "test", "TestCo", field_rows, [1,2,3])
        self.assertGreaterEqual(count, 2, "Should create >=2 spans for value found in multiple chunks")

    def test_posthoc_weak_evidence_does_not_create_confirmable_strong_spans(self):
        """posthoc binding remains weak-only; confirmed evidence is created before status resolution."""
        import sqlite3, tempfile
        db_path = os.path.join(tempfile.mkdtemp(), "test_strong.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
        CREATE TABLE source_documents (
            id INTEGER PRIMARY KEY, run_id TEXT, company_key TEXT, source_type TEXT,
            source_url TEXT, title TEXT, publisher TEXT, published_at TEXT,
            fetched_at TEXT, raw_text TEXT, content_hash TEXT, trust_tier TEXT, intent TEXT
        );
        CREATE TABLE evidence_spans (id INTEGER PRIMARY KEY, document_id INTEGER, company_key TEXT, field_key TEXT, quote_text TEXT, normalized_fact TEXT, confidence REAL, created_by_agent TEXT, start_offset INTEGER DEFAULT 0, end_offset INTEGER DEFAULT 0);
        """)
        conn.commit(); conn.close()

        evidence_pool = [type('e',(),{
            'title':'Test','url':'http://example.com','content':'Ideogram founded in 2022 has 50 employees and raised Series A',
            'source':'search','intent':'test','final_score':0.5
        })()]
        field_rows = [{"field_key":"funding_stage","field_value":"raised Series A"}]

        with patch.object(pipeline.config, 'POSTHOC_EVIDENCE_WEAK_ONLY', True):
            pipeline._bind_posthoc_weak_evidence(db_path, 'testco', 'TestCo', field_rows, evidence_pool, run_id='t1')

        conn = sqlite3.connect(db_path)
        strong_spans = conn.execute("SELECT * FROM evidence_spans WHERE created_by_agent='posthoc_strong_matcher'").fetchall()
        weak_spans = conn.execute("SELECT * FROM evidence_spans WHERE created_by_agent='posthoc_weak_matcher'").fetchall()
        conn.close()
        self.assertEqual(len(strong_spans), 0)
        self.assertGreaterEqual(len(weak_spans), 1)


if __name__ == "__main__":
    unittest.main()
