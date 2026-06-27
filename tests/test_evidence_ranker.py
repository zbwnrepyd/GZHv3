"""测试证据打分器 — 验证噪音 chunk 不被选入上下文"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))
from research.context.evidence_ranker import (
    score_chunk, score_chunks_batch, is_field_confirmable_source,
)


class TestEvidenceRanker(unittest.TestCase):

    def setUp(self):
        self.company_identity = {
            "display_name": "Anthropic",
            "website_host": "anthropic.com",
            "aliases": ["Anthropic", "Anthropic AI"],
        }

    def _make_chunk(self, text: str, source_type: str = "official_site",
                    source_url: str = "https://anthropic.com",
                    title: str = "Anthropic", chunk_type: str = "about"):
        return {
            "document_id": 1,
            "company_key": "anthropic",
            "source_type": source_type,
            "source_url": source_url,
            "title": title,
            "chunk_text": text,
            "chunk_type": chunk_type,
            "token_estimate": 200,
            "is_noise": 0,
        }

    def test_noise_chunk_scores_low(self):
        """噪声 chunk 应得分很低"""
        chunk = self._make_chunk(
            "Navigation: Home Products Pricing Blog Login Sign up",
            chunk_type="navigation",
        )
        result = score_chunk(chunk, self.company_identity)
        self.assertLess(result["final_score"], 0.35,
                       f"Navigation chunk should score < 0.35, got {result['final_score']}")
        self.assertEqual(result["is_noise"], 1)

    def test_footer_chunk_is_noise(self):
        """Footer chunk 应标记为噪音"""
        chunk = self._make_chunk(
            "© 2025 Anthropic. All rights reserved. Privacy Policy Terms Cookie",
            chunk_type="footer",
        )
        result = score_chunk(chunk, self.company_identity)
        self.assertEqual(result["is_noise"], 1)

    def test_cookie_chunk_is_noise(self):
        """Cookie chunk 应标记为噪音"""
        chunk = self._make_chunk(
            "Cookie Policy We use cookies to improve your experience. Cookie settings.",
            chunk_type="cookie",
        )
        result = score_chunk(chunk, self.company_identity)
        self.assertEqual(result["is_noise"], 1)
        self.assertAlmostEqual(result["noise_score"], 1.0)

    def test_info_dense_chunk_scores_high(self):
        """高信息密度 chunk 应得分高"""
        chunk = self._make_chunk(
            "Anthropic raised $7.3B in funding. Their Series C was $4B at a $60B valuation. "
            "The company launched Claude 4 in May 2025. Revenue grew 300% YoY to $800M ARR.",
            chunk_type="about",
        )
        result = score_chunk(chunk, self.company_identity)
        self.assertGreater(result["final_score"], 0.35,
                          f"Info-dense chunk should score > 0.35, got {result['final_score']}")
        self.assertGreater(result["info_density_score"], 0.3)
        self.assertEqual(result["is_noise"], 0)

    def test_entity_match_boosts_score(self):
        """实体匹配度应提升分数"""
        chunk_with = self._make_chunk(
            "Anthropic is an AI safety company. Anthropic's Claude model is popular.",
        )
        chunk_without = self._make_chunk(
            "The AI industry is growing rapidly. Many companies are entering the market.",
            title="Industry Report",
            source_url="https://example.com/report",
        )
        result_with = score_chunk(chunk_with, self.company_identity)
        result_without = score_chunk(chunk_without, self.company_identity)
        self.assertGreater(result_with["entity_score"], result_without["entity_score"])

    def test_field_relevance_matters(self):
        """字段相关性应影响分数"""
        chunk = self._make_chunk(
            "The company raised a $500M Series E at a $10B valuation. "
            "Key investors include a16z and Sequoia.",
        )
        result = score_chunk(chunk, self.company_identity, field_key="funding_info",
                            keywords=["funding", "raised", "Series", "valuation"])
        self.assertGreater(result["field_relevance_score"], 0.3)

    def test_community_source_not_confirmable(self):
        """社区来源不能用于 confirmed 事实"""
        self.assertFalse(is_field_confirmable_source("community"))
        self.assertFalse(is_field_confirmable_source("social_media"))
        self.assertTrue(is_field_confirmable_source("official_site"))
        self.assertTrue(is_field_confirmable_source("press_release"))

    def test_noise_boilerplate_low_score(self):
        """Boilerplate chunk 应得分低"""
        chunk = self._make_chunk(
            "Subscribe to our newsletter. Follow us on Twitter and LinkedIn. "
            "Related posts: How to build AI agents, The future of LLMs.",
            chunk_type="boilerplate",
        )
        result = score_chunk(chunk, self.company_identity)
        self.assertLess(result["final_score"], 0.35)

    def test_scored_chunks_retain_fields(self):
        """评分不应丢失原始字段"""
        chunk = self._make_chunk("Test content about Anthropic.")
        result = score_chunk(chunk, self.company_identity)
        self.assertEqual(result["document_id"], 1)
        self.assertEqual(result["chunk_text"], "Test content about Anthropic.")
        self.assertIn("source_score", result)
        self.assertIn("entity_score", result)
        self.assertIn("final_score", result)
        self.assertIn("is_noise", result)

    def test_product_core_features_kilo_style_chunk(self):
        """Kilo Features 风格的产品功能 chunk 应获得足够分数进入 LLM 上下文"""
        chunk = self._make_chunk(
            "Kilo provides multiple AI agent modes including single-agent solo, "
            "multi-agent collaboration, and supervisor orchestration. "
            "The platform features a Chrome extension for browser automation, "
            "MCP gateway integration, and one-click cloud deployment. "
            "Workflow builder supports drag-and-drop agent pipelines.",
            source_type="official_site",
            source_url="https://kilo.ai/features",
            title="Kilo Features - AI Agent Platform",
            chunk_type="product_feature",
        )
        result = score_chunk(
            chunk, self.company_identity,
            field_key="product_core_features",
        )
        self.assertGreaterEqual(
            result["field_relevance_score"], 0.4,
            f"field_relevance_score 应 >= 0.4，实际 {result['field_relevance_score']:.3f}"
        )
        self.assertEqual(
            result["is_noise"], 0,
            f"product_feature chunk 不应标记为噪音，实际 is_noise={result['is_noise']}"
        )
        self.assertGreaterEqual(
            result["final_score"], 0.35,
            f"final_score 应 >= 0.35，实际 {result['final_score']:.3f}"
        )


if __name__ == "__main__":
    unittest.main()
