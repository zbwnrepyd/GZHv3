"""上下文预算测试 — SPEC §16.5: L0 context <= 18000 tokens, per-URL <= 3 chunks

验证 TokenBudget 和 context_packer 的 token 预算控制：
- 500 chunks 输入 → L0 context 不超过 18000 tokens
- 同一 URL 最多 3 个 chunk
- 同一 source_family 最多 12 个 chunk
- max_evidence_per_field = 3
- estimate_tokens 基本准确性
"""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))
from research.context.token_budget import (
    TokenBudget,
    estimate_tokens,
    BUDGET_PRESETS,
    get_field_budget,
)
from research.context.context_packer import pack_context


# ── 辅助函数：生成模拟 chunk ──

def _make_chunk(
    chunk_id=1,
    doc_id=1,
    source_url="https://example.com/1",
    source_family="search",
    source_type="press_release",
    token_estimate=200,
    final_score=0.8,
    is_noise=0,
    chunk_text=None,
):
    """构造一个与 document_chunks 表结构兼容的模拟 chunk 字典。"""
    if chunk_text is None:
        chunk_text = f"Mock chunk content number {chunk_id}. " * 10
    return {
        "id": chunk_id,
        "document_id": doc_id,
        "company_key": "testco",
        "source_type": source_type,
        "source_url": source_url,
        "source_family": source_family,
        "title": f"Article {chunk_id}",
        "chunk_text": chunk_text,
        "chunk_type": "about",
        "token_estimate": token_estimate,
        "final_score": final_score,
        "is_noise": is_noise,
        "matched_fields": None,
        "raw_text": "SHOULD NOT LEAK RAW TEXT",
    }


# ══════════════════════════════════════════════════════════════════════
# SPEC §16.5 核心：500 chunks → L0 <= 18000 tokens
# ══════════════════════════════════════════════════════════════════════

class TestL0Budget500Chunks(unittest.TestCase):
    """SPEC §16.5 核心场景：500 chunks 输入 → L0 context 不超过 18000 tokens"""

    def test_token_budget_500_chunks_not_exceeded(self):
        """TokenBudget(18000) 接收 500 个唯一 URL chunk → used_tokens <= 18000

        使用唯一 URL 避免 URL 去重成为瓶颈，验证纯 token 预算截断生效。
        """
        budget = TokenBudget(max_tokens=18000)
        for i in range(500):
            budget.add(
                chunk_tokens=200,
                source_url=f"https://example.com/{i}",
                source_family="search",
            )
        self.assertLessEqual(
            budget.used_tokens, 18000,
            "500 chunks must not exceed 18000 token budget",
        )
        self.assertGreater(
            budget.chunks_dropped, 0,
            "Expected chunks to be dropped with 500 chunks at 200 tokens each",
        )
        # 18000 / 200 = 90 chunks 理论最大容纳量
        self.assertLessEqual(budget.chunks_included, 90)

    def test_add_chunk_dict_500_chunks(self):
        """TokenBudget.add_chunk(dict) 方式接收 500 chunks → 预算不超"""
        budget = TokenBudget(max_tokens=18000)
        for i in range(500):
            chunk = _make_chunk(
                chunk_id=i + 1,
                source_url=f"https://example.com/{i}",
                token_estimate=200,
            )
            budget.add_chunk(chunk)
        self.assertLessEqual(budget.used_tokens, 18000)

    def test_500_chunks_with_shared_urls_still_budget_safe(self):
        """即使共享 URL（触发 per-URL 限制），500 chunks 仍然不超预算"""
        budget = TokenBudget(max_tokens=18000)
        # 10 个 URL，每个 50 个 chunk
        for url_idx in range(10):
            url = f"https://example.com/article-{url_idx}"
            for _ in range(50):
                budget.add(chunk_tokens=500, source_url=url)
        # per-URL 限制：10 URLs × 3 = 30 个 chunk 已接受
        # token 预算：30 × 500 = 15000 <= 18000 ✓
        self.assertLessEqual(budget.used_tokens, 18000)
        self.assertEqual(budget.chunks_included, 30)  # 10 URLs × 3

    @patch("research.context.context_packer._load_chunks_from_db")
    @patch("research.context.context_packer._load_evidence_spans")
    @patch("research.context.context_packer._log_packed_context")
    def test_pack_context_500_chunks_budget_enforced(
        self, mock_log, mock_spans, mock_load,
    ):
        """pack_context 面对 500 个模拟 chunk → used_tokens <= 18000

        验证打包器端到端流程：加载 chunk → 按分数排序 → 按预算截断 → 安全过滤输出。
        """
        mock_chunks = [
            _make_chunk(
                chunk_id=i + 1,
                doc_id=(i % 50) + 1,
                source_url=f"https://example.com/article/{i}",
                token_estimate=200,
                final_score=0.8,
            )
            for i in range(500)
        ]
        mock_load.return_value = mock_chunks
        mock_spans.return_value = []
        mock_log.return_value = None

        result = pack_context(
            db_path=":memory:",
            company_key="testco",
            target_type="l0",
            target_key="l0_full",
            run_id="test-500",
        )

        self.assertLessEqual(
            result["used_tokens"], 18000,
            "pack_context with 500 chunks must respect L0 budget of 18000",
        )
        self.assertGreater(
            result["dropped_count"], 0,
            "Expected chunks to be dropped when packing 500 chunks",
        )
        self.assertEqual(result["budget_tokens"], 18000)
        # 验证返回的 chunks 不含 raw_text（安全断言：_CHUNK_OUTPUT_KEYS 白名单过滤）
        for ch in result["chunks"]:
            self.assertNotIn(
                "raw_text", ch,
                "raw_text must never leak into packed context output",
            )

    @patch("research.context.context_packer._load_chunks_from_db")
    @patch("research.context.context_packer._load_evidence_spans")
    @patch("research.context.context_packer._log_packed_context")
    def test_pack_context_500_chunks_all_high_score_no_budget_breach(
        self, mock_log, mock_spans, mock_load,
    ):
        """所有 500 chunk 都是高分（0.95）→ 仍然不超预算"""
        mock_chunks = [
            _make_chunk(
                chunk_id=i + 1,
                source_url=f"https://example.com/{i}",
                token_estimate=180,
                final_score=0.95,
            )
            for i in range(500)
        ]
        mock_load.return_value = mock_chunks
        mock_spans.return_value = []
        mock_log.return_value = None

        result = pack_context(
            db_path=":memory:",
            company_key="testco",
            target_type="l0",
            target_key="l0_full",
        )

        self.assertLessEqual(result["used_tokens"], 18000)
        # 18000 / 180 = 100 chunks max
        self.assertLessEqual(len(result["chunks"]), 100)


# ══════════════════════════════════════════════════════════════════════
# Per-URL 限制：同一 URL 最多 3 个 chunk
# ══════════════════════════════════════════════════════════════════════

class TestPerUrlLimit(unittest.TestCase):
    """SPEC §16.5: 同一 URL 最多 3 个 chunk"""

    def test_one_url_10_chunks_only_3_accepted(self):
        """1 个 URL 提交 10 个 chunk → 只接受 3 个"""
        budget = TokenBudget(max_tokens=10000)
        url = "https://example.com/single-article"
        for _ in range(10):
            budget.add(chunk_tokens=100, source_url=url)
        self.assertEqual(
            budget.chunks_included, 3,
            "Only 3 chunks per URL should be accepted",
        )
        self.assertEqual(budget.chunks_dropped, 7)

    def test_multiple_urls_each_gets_3(self):
        """5 个 URL 各提交 5 个 chunk → 每个 URL 最多 3 个"""
        budget = TokenBudget(max_tokens=50000)
        for url_idx in range(5):
            url = f"https://example.com/article-{url_idx}"
            for _ in range(5):
                budget.add(chunk_tokens=100, source_url=url)
        # 5 URLs × 3 accepted = 15; 5 URLs × 2 dropped = 10
        self.assertEqual(budget.chunks_included, 15)
        self.assertEqual(budget.chunks_dropped, 10)

    def test_url_limit_via_add_chunk_dict(self):
        """通过 add_chunk(dict) 验证 URL 限制"""
        budget = TokenBudget(max_tokens=10000)
        url = "https://example.com/repeated"
        for i in range(8):
            chunk = _make_chunk(
                chunk_id=i + 1,
                source_url=url,
                token_estimate=100,
            )
            budget.add_chunk(chunk)
        self.assertEqual(
            budget.chunks_included, 3,
            "add_chunk should enforce per-URL limit of 3",
        )

    def test_empty_url_no_dedup_limit(self):
        """空 URL 不触发去重限制"""
        budget = TokenBudget(max_tokens=10000)
        for _ in range(10):
            budget.add(chunk_tokens=100, source_url="")
        self.assertEqual(
            budget.chunks_included, 10,
            "Empty URLs should not be dedup-limited",
        )
        self.assertEqual(budget.chunks_dropped, 0)

    def test_url_tracking_reset_per_budget_instance(self):
        """每个 TokenBudget 实例独立追踪 URL 计数"""
        b1 = TokenBudget(max_tokens=10000)
        b2 = TokenBudget(max_tokens=10000)
        url = "https://example.com/shared"
        # b1 用满 3 个
        b1.add(100, url)
        b1.add(100, url)
        b1.add(100, url)
        b1.add(100, url)  # 被拒绝
        self.assertEqual(b1.chunks_included, 3)
        # b2 独立，不受 b1 影响
        b2.add(100, url)
        self.assertEqual(b2.chunks_included, 1)


# ══════════════════════════════════════════════════════════════════════
# Per-source-family 限制：同一 source_family 最多 12 个 chunk
# ══════════════════════════════════════════════════════════════════════

class TestPerSourceFamilyLimit(unittest.TestCase):
    """同一 source_family 最多 12 个 chunk"""

    def test_one_source_family_20_chunks_only_12_accepted(self):
        """1 个 source_family 提交 20 个 chunk → 只接受 12 个"""
        budget = TokenBudget(max_tokens=50000)
        sf = "tavily_search"
        for i in range(20):
            budget.add(
                chunk_tokens=100,
                source_url=f"https://example.com/{i}",
                source_family=sf,
            )
        self.assertEqual(
            budget.chunks_included, 12,
            "Only 12 chunks per source_family should be accepted",
        )
        self.assertEqual(budget.chunks_dropped, 8)

    def test_different_source_families_each_independent(self):
        """不同 source_family 各 12 个 limit 独立"""
        budget = TokenBudget(max_tokens=50000)
        families = ("tavily_search", "github", "youtube")
        for sf in families:
            for i in range(15):
                budget.add(
                    chunk_tokens=100,
                    source_url=f"https://{sf}.com/{i}",
                    source_family=sf,
                )
        # 3 families × 12 = 36 accepted, 3 × 3 = 9 dropped
        self.assertEqual(budget.chunks_included, 36)
        self.assertEqual(budget.chunks_dropped, 9)

    def test_empty_source_family_no_dedup_limit(self):
        """空 source_family 不触发去重"""
        budget = TokenBudget(max_tokens=10000)
        for i in range(20):
            budget.add(
                chunk_tokens=100,
                source_url=f"https://example.com/{i}",
                source_family="",
            )
        self.assertEqual(
            budget.chunks_included, 20,
            "Empty source_family should not be dedup-limited",
        )

    def test_summary_includes_source_family_counts(self):
        """summary() 应包含 source_family_chunks 计数"""
        budget = TokenBudget(max_tokens=10000)
        budget.add(100, "https://a.com", "sf_a")
        budget.add(100, "https://b.com", "sf_a")
        budget.add(100, "https://c.com", "sf_b")
        s = budget.summary()
        self.assertIn("source_family_chunks", s)
        self.assertEqual(s["source_family_chunks"]["sf_a"], 2)
        self.assertEqual(s["source_family_chunks"]["sf_b"], 1)


# ══════════════════════════════════════════════════════════════════════
# BUDGET_PRESETS 关键值验证
# ══════════════════════════════════════════════════════════════════════

class TestBudgetPresets(unittest.TestCase):
    """验证 BUDGET_PRESETS 关键值符合 SPEC §16.5 要求"""

    def test_l0_budget_values(self):
        """L0 标准预算 = 18000，深度预算 = 28000"""
        self.assertEqual(
            BUDGET_PRESETS["l0_standard"], 18000,
            "L0 standard budget must be 18000 per SPEC",
        )
        self.assertEqual(BUDGET_PRESETS["l0_deep"], 28000)

    def test_max_chunks_per_url_is_3(self):
        self.assertEqual(BUDGET_PRESETS["max_chunks_per_url"], 3)

    def test_max_chunks_per_source_family_is_12(self):
        self.assertEqual(BUDGET_PRESETS["max_chunks_per_source_family"], 12)

    def test_max_evidence_per_field_is_3(self):
        self.assertEqual(BUDGET_PRESETS["max_evidence_per_field"], 3)

    def test_max_chunks_per_field_is_5(self):
        self.assertEqual(BUDGET_PRESETS["max_chunks_per_field"], 5)

    def test_field_budget_mapping(self):
        """字段级预算映射正确"""
        self.assertEqual(get_field_budget("funding_info"), 1600)
        self.assertEqual(get_field_budget("tam"), 2200)
        self.assertEqual(get_field_budget("competitors_top3"), 3000)
        self.assertEqual(get_field_budget("product_core_features"), 800)
        self.assertEqual(get_field_budget("competitive_landscape"), 2500)

    def test_unknown_field_gets_default(self):
        """未映射字段返回 field_default 预算"""
        self.assertEqual(
            get_field_budget("nonexistent_field"),
            BUDGET_PRESETS["field_default"],
        )

    def test_field_budget_via_manifest_override(self):
        """field_manifest 中的 context_budget_tokens 优先于映射表"""
        manifest = {"context_budget_tokens": 500}
        self.assertEqual(
            get_field_budget("funding_info", manifest), 500,
            "Manifest override should take priority over mapping table",
        )


# ══════════════════════════════════════════════════════════════════════
# estimate_tokens 准确性
# ══════════════════════════════════════════════════════════════════════

class TestTokenEstimation(unittest.TestCase):
    """estimate_tokens 基本准确性"""

    def test_empty_and_none(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens(None), 0)

    def test_short_text_returns_at_least_1(self):
        """非空文本至少返回 1 token"""
        tokens = estimate_tokens("Hi")
        self.assertGreaterEqual(tokens, 1)

    def test_chinese_text_tokens_less_than_chars(self):
        """中文约 2.5 字符/token，token 数应小于字符数"""
        text = "这是一段中文文本用于测试"
        tokens = estimate_tokens(text)
        self.assertGreater(tokens, 0)
        self.assertLess(tokens, len(text))

    def test_english_text_tokens_less_than_chars(self):
        """英文 token 数也应小于字符数"""
        text = "This is a sample English text for token estimation"
        tokens = estimate_tokens(text)
        self.assertGreater(tokens, 0)
        self.assertLess(tokens, len(text))

    def test_large_text_ratio_in_range(self):
        """长文本 token 估算比率应在 1.5–4.0 字符/token"""
        text = "content " * 10000
        tokens = estimate_tokens(text)
        ratio = len(text) / tokens
        self.assertGreater(ratio, 1.5)
        self.assertLess(ratio, 4.0)

    def test_very_long_chinese_text(self):
        """超长中文文本 token 估算合理"""
        text = "这是一段很长的中文文本，" * 5000
        tokens = estimate_tokens(text)
        self.assertGreater(tokens, 1000)
        self.assertLess(tokens, len(text))

    def test_token_estimate_monotonic(self):
        """更长的文本应有更多的 token 估算"""
        t1 = estimate_tokens("short")
        t2 = estimate_tokens("a much longer text that should have more tokens")
        self.assertGreater(t2, t1)


# ══════════════════════════════════════════════════════════════════════
# TokenBudget 边界和负向测试
# ══════════════════════════════════════════════════════════════════════

class TestTokenBudgetEdgeCases(unittest.TestCase):
    """TokenBudget 边界条件和负向测试"""

    def test_single_chunk_exceeds_total_budget(self):
        """单个 chunk token 超过总预算 → 直接拒绝"""
        budget = TokenBudget(max_tokens=1000)
        self.assertFalse(
            budget.add(1500),
            "Chunk exceeding total budget should be rejected",
        )

    def test_zero_token_budget(self):
        """零预算不接受任何 chunk"""
        budget = TokenBudget(max_tokens=0)
        self.assertFalse(budget.add(1))
        self.assertTrue(budget.is_full)

    def test_exactly_at_budget_no_overflow(self):
        """恰好达到预算时 is_full=True，不再接受"""
        budget = TokenBudget(max_tokens=1000)
        self.assertTrue(budget.add(500))
        self.assertTrue(budget.add(500))
        self.assertTrue(budget.is_full)
        self.assertFalse(budget.add(1))

    def test_remaining_property(self):
        budget = TokenBudget(max_tokens=1000)
        budget.add(300)
        self.assertEqual(budget.remaining, 700)

    def test_sub_budget_tracking(self):
        """子预算追踪：check_sub_budget + use_sub_budget"""
        budget = TokenBudget(max_tokens=5000)
        budget.set_sub_budget("identity", 600)
        self.assertTrue(budget.check_sub_budget("identity", 300))
        budget.use_sub_budget("identity", 300)
        self.assertFalse(
            budget.check_sub_budget("identity", 400),
            "Should exceed sub-budget limit",
        )
        # 子预算耗尽但总预算还有空间 → add 仍可接受
        self.assertTrue(budget.add(100))

    def test_summary_all_keys_present(self):
        """summary() 返回所有必需字段"""
        budget = TokenBudget(max_tokens=1000)
        budget.add(200, "https://a.com", "sf_a")
        s = budget.summary()
        for key in ("budget", "used", "remaining", "chunks_included",
                     "chunks_dropped", "sub_budgets", "source_family_chunks"):
            self.assertIn(key, s, f"summary() must contain '{key}'")


# ══════════════════════════════════════════════════════════════════════
# pack_context 集成测试（mock DB）
# ══════════════════════════════════════════════════════════════════════

class TestPackContextWithMockDB(unittest.TestCase):
    """pack_context 集成测试：mock 数据库验证打包行为"""

    @patch("research.context.context_packer._load_chunks_from_db")
    @patch("research.context.context_packer._load_evidence_spans")
    @patch("research.context.context_packer._log_packed_context")
    def test_l0_pack_returns_correct_structure(
        self, mock_log, mock_spans, mock_load,
    ):
        """pack_context L0 返回结构完整"""
        mock_load.return_value = [
            _make_chunk(chunk_id=1, token_estimate=300, final_score=0.9),
        ]
        mock_spans.return_value = []
        mock_log.return_value = None

        result = pack_context(
            db_path=":memory:",
            company_key="testco",
            target_type="l0",
            target_key="l0_full",
            run_id="test-struct",
        )

        for key in (
            "company_key", "target_type", "target_key",
            "budget_tokens", "used_tokens", "chunks",
            "evidence_spans", "dropped_count", "source_breakdown",
        ):
            self.assertIn(key, result, f"Result must contain '{key}'")
        self.assertEqual(result["company_key"], "testco")
        self.assertEqual(result["target_type"], "l0")

    @patch("research.context.context_packer._load_chunks_from_db")
    @patch("research.context.context_packer._load_evidence_spans")
    @patch("research.context.context_packer._log_packed_context")
    def test_low_score_chunks_filtered_out(
        self, mock_log, mock_spans, mock_load,
    ):
        """final_score < 0.35 的 chunk 应被过滤"""
        mock_load.return_value = [
            _make_chunk(chunk_id=1, final_score=0.9, token_estimate=300),
            _make_chunk(chunk_id=2, final_score=0.1, token_estimate=300,
                        source_url="https://example.com/2"),
        ]
        mock_spans.return_value = []
        mock_log.return_value = None

        result = pack_context(
            db_path=":memory:",
            company_key="testco",
            target_type="l0",
            target_key="l0_full",
        )

        chunk_ids = [c["id"] for c in result["chunks"]]
        self.assertIn(1, chunk_ids)
        self.assertNotIn(2, chunk_ids, "Low-score chunk (0.1) should be excluded")

    @patch("research.context.context_packer._load_chunks_from_db")
    @patch("research.context.context_packer._load_evidence_spans")
    @patch("research.context.context_packer._log_packed_context")
    def test_noise_chunks_filtered_out(
        self, mock_log, mock_spans, mock_load,
    ):
        """is_noise=1 的 chunk 应被过滤"""
        mock_load.return_value = [
            _make_chunk(chunk_id=1, final_score=0.9, is_noise=0),
            _make_chunk(chunk_id=2, final_score=0.9, is_noise=1,
                        source_url="https://example.com/2"),
        ]
        mock_spans.return_value = []
        mock_log.return_value = None

        result = pack_context(
            db_path=":memory:",
            company_key="testco",
            target_type="l0",
            target_key="l0_full",
        )

        chunk_ids = [c["id"] for c in result["chunks"]]
        self.assertIn(1, chunk_ids)
        self.assertNotIn(2, chunk_ids, "Noise chunk should be excluded")

    @patch("research.context.context_packer._load_chunks_from_db")
    @patch("research.context.context_packer._load_evidence_spans")
    @patch("research.context.context_packer._log_packed_context")
    def test_raw_text_not_in_output_chunks(
        self, mock_log, mock_spans, mock_load,
    ):
        """pack_context 输出 chunks 白名单过滤，raw_text 不得出现"""
        mock_load.return_value = [
            _make_chunk(chunk_id=1, token_estimate=100, final_score=0.8),
        ]
        mock_spans.return_value = []
        mock_log.return_value = None

        result = pack_context(
            db_path=":memory:",
            company_key="testco",
            target_type="l0",
            target_key="l0_full",
        )

        for ch in result["chunks"]:
            self.assertNotIn(
                "raw_text", ch,
                "raw_text must not leak into packed context output",
            )
            # 同时验证白名单字段存在
            for expected_key in ("chunk_text", "source_url", "title", "final_score"):
                self.assertIn(expected_key, ch)

    @patch("research.context.context_packer._load_chunks_from_db")
    @patch("research.context.context_packer._load_evidence_spans")
    @patch("research.context.context_packer._log_packed_context")
    def test_field_target_type_uses_field_budget(
        self, mock_log, mock_spans, mock_load,
    ):
        """target_type='field' 时使用字段级预算"""
        mock_load.return_value = [
            _make_chunk(chunk_id=i + 1, token_estimate=300, final_score=0.9,
                        source_url=f"https://example.com/{i}")
            for i in range(10)
        ]
        mock_spans.return_value = []
        mock_log.return_value = None

        result = pack_context(
            db_path=":memory:",
            company_key="testco",
            target_type="field",
            target_key="funding_info",  # budget = 1600
        )

        self.assertEqual(result["budget_tokens"], 1600)
        self.assertLessEqual(result["used_tokens"], 1600)

    @patch("research.context.context_packer._load_chunks_from_db")
    @patch("research.context.context_packer._load_evidence_spans")
    @patch("research.context.context_packer._log_packed_context")
    def test_evidence_spans_capped_at_max(
        self, mock_log, mock_spans, mock_load,
    ):
        """evidence_spans 数量受 max_evidence_per_field=3 限制"""
        mock_chunks = [
            _make_chunk(chunk_id=1, doc_id=1, token_estimate=100, final_score=0.9),
        ]
        mock_spans.return_value = [
            {"id": i, "document_id": 1, "field_key": "funding_info",
             "quote_text": f"Evidence {i}", "confidence": 0.9,
             "doc_title": "Test", "source_url": "https://example.com"}
            for i in range(1, 11)  # 10 evidence spans, only 3 should be kept
        ]
        mock_load.return_value = mock_chunks
        mock_log.return_value = None

        result = pack_context(
            db_path=":memory:",
            company_key="testco",
            target_type="l0",
            target_key="l0_full",
        )

        self.assertLessEqual(
            len(result["evidence_spans"]), 3,
            "evidence_spans should be capped at max_evidence_per_field=3",
        )


if __name__ == "__main__":
    unittest.main()
