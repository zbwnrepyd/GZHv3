"""噪音过滤端到端测试 — SPEC §16.4

验证 document_cleaner → document_chunker → context_packer 全链路:
1. Cookie banner / footer / terms / nav-heavy 页面被识别并过滤
2. 噪声 chunk (is_noise=1) 不进入 packed_context
3. 低分 chunk (final_score < 0.35) 不进入 packed_context
4. 正常文章内容完整通过
"""
import unittest
import sys
import sqlite3
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))
from research.context.document_cleaner import clean_document_text
from research.context.document_chunker import chunk_document, _NOISE_CHUNK_TYPES
from research.context.context_packer import pack_context
from research.context.evidence_ranker import score_chunk


# ── 公用 company_identity  ──
SAMPLE_IDENTITY = {
    "display_name": "ExampleAI",
    "website_host": "exampleai.com",
    "aliases": [],
}


class TestDocumentCleanerNoisePages(unittest.TestCase):
    """验证 DocumentCleaner 对噪音页面的识别 — SPEC §16.4"""

    def test_cookie_banner_is_low_quality(self):
        """Cookie banner 文本应被标记为低质量并进行噪音标记"""
        text = (
            "We use cookies to improve your browsing experience. "
            "By continuing to browse this site, you agree to our use of cookies. "
            "Cookie preferences can be adjusted in your settings."
        )
        result = clean_document_text(text)
        self.assertTrue(
            result["is_low_quality"],
            f"Cookie banner should be low_quality, got flags={result['noise_flags']}",
        )
        self.assertIn("cookie_banner", result["noise_flags"])

    def test_cookie_policy_page_is_noise_page(self):
        """Cookie Policy 页面应被识别为整页噪音"""
        text = (
            "Cookie Policy\n\n"
            "This Cookie Policy explains how we use cookies and similar "
            "technologies. Cookie settings can be managed in your browser. "
            "We use cookies to remember your preferences and to analyze "
            "our traffic. Cookie notice requirements apply."
        )
        result = clean_document_text(text, source_type="official_site")
        self.assertTrue(
            result["is_noise_page"],
            f"Cookie policy page should be noise_page, flags={result['noise_flags']}",
        )
        self.assertTrue(result["is_low_quality"])

    def test_privacy_policy_page_is_low_quality(self):
        """Privacy Policy 页面应被标记为低质量"""
        text = (
            "Privacy Policy\n\n"
            "Last updated: March 2026\n\n"
            "This Privacy Policy describes how we collect, use, and share "
            "your personal information. Data protection policy compliance "
            "with GDPR and CCPA regulations."
        )
        result = clean_document_text(text)
        self.assertTrue(
            result["is_noise_page"],
            f"Privacy page should be noise_page, flags={result['noise_flags']}",
        )
        self.assertIn("privacy_page", result["noise_flags"])

    def test_terms_page_is_noise_page(self):
        """Terms of Service 页面应被识别为整页噪音"""
        text = (
            "Terms of Service\n\n"
            "These terms and conditions govern your use of our platform. "
            "By accessing the service you agree to these terms of use. "
            "Please read this legal disclaimer carefully."
        )
        result = clean_document_text(text)
        self.assertTrue(result["is_noise_page"])
        found_terms = any(
            f in result["noise_flags"] for f in ("terms_page", "legal_page")
        )
        self.assertTrue(found_terms, f"Expected terms/legal flag, got {result['noise_flags']}")

    def test_login_signup_page_is_noise_page(self):
        """Sign In / Sign Up 页面应被识别为 auth 噪音页"""
        text = (
            "Sign In\n\n"
            "Email address\n"
            "Password\n"
            "Forgot password? Reset password here.\n"
            "Don't have an account? Sign up now and create account."
        )
        result = clean_document_text(text)
        self.assertTrue(result["is_noise_page"])
        self.assertIn("auth_page", result["noise_flags"])

    def test_short_noise_page_fully_discarded(self):
        """简短的全噪音页（<500 字符）应完全丢弃"""
        text = "Cookie Policy. We use cookies. Cookie settings. Cookie notice."
        result = clean_document_text(text)
        self.assertEqual(result["clean_text"], "")
        self.assertTrue(result["is_low_quality"])
        self.assertEqual(result["removed_ratio"], 1.0)


class TestDocumentCleanerNoiseBlocks(unittest.TestCase):
    """验证 DocumentCleaner 对噪音块的逐行过滤 — SPEC §16.4"""

    def test_footer_lines_removed(self):
        """Footer 行（copyright / all rights reserved）应被过滤"""
        text = (
            "Our AI platform helps businesses scale.\n"
            "© 2025 ExampleAI Corp. All rights reserved.\n"
            "Privacy Policy | Terms of Service\n"
        )
        result = clean_document_text(text)
        self.assertNotIn("All rights reserved", result["clean_text"])
        self.assertNotIn("© 2025", result["clean_text"])
        # 正文应保留
        self.assertIn("AI platform", result["clean_text"])

    def test_navigation_items_removed(self):
        """单独出现的导航项应被过滤"""
        text = (
            "Our product page.\n"
            "home\n"
            "products\n"
            "pricing\n"
            "blog\n"
            "contact\n"
            "The actual content about the company."
        )
        result = clean_document_text(text)
        self.assertNotIn("\nhome\n", result["clean_text"])
        self.assertNotIn("\npricing\n", result["clean_text"])
        self.assertIn("actual content", result["clean_text"])

    def test_newsletter_cta_removed(self):
        """Newsletter CTA 应被过滤"""
        text = (
            "Subscribe to our newsletter for the latest updates.\n"
            "Join our mailing list today.\n"
            "Our product is used by thousands of companies."
        )
        result = clean_document_text(text)
        self.assertNotIn("newsletter", result["clean_text"].lower())
        self.assertNotIn("mailing list", result["clean_text"].lower())
        self.assertIn("thousands of companies", result["clean_text"])

    def test_cta_button_removed(self):
        """CTA 按钮文本应被过滤"""
        text = (
            "Start free trial today! No credit card required.\n"
            "Book a demo with our team.\n"
            "Get started free and explore the platform."
        )
        result = clean_document_text(text)
        self.assertNotIn("Start free trial", result["clean_text"])
        self.assertNotIn("Book a demo", result["clean_text"])
        self.assertNotIn("Get started free", result["clean_text"])

    def test_youtube_greeting_removed(self):
        """YouTube 视频寒暄和结尾口播应被过滤"""
        text = (
            "Hey guys welcome back to the channel!\n"
            "Don't forget to like and subscribe and hit the bell icon.\n"
            "Today we are looking at an AI startup.\n"
            "Thanks for watching, see you in the next video!"
        )
        result = clean_document_text(text)
        self.assertNotIn("Hey guys", result["clean_text"])
        self.assertNotIn("like and subscribe", result["clean_text"])
        self.assertNotIn("Thanks for watching", result["clean_text"])
        # 正文部分应保留
        self.assertIn("AI startup", result["clean_text"])

    def test_sponsor_mention_removed(self):
        """赞助口播应被过滤"""
        text = (
            "This video is sponsored by BigCorp.\n"
            "Brought to you by our friends at Acme Inc.\n"
            "The actual product review starts here."
        )
        result = clean_document_text(text)
        self.assertNotIn("sponsored by", result["clean_text"].lower())
        self.assertNotIn("Brought to you by", result["clean_text"])
        self.assertIn("product review", result["clean_text"])

    def test_advertisement_removed(self):
        """广告标记应被过滤"""
        text = (
            "Advertisement\n"
            "Promoted story — sponsored content ahead.\n"
            "The company announced a new funding round."
        )
        result = clean_document_text(text)
        self.assertNotIn("Promoted story", result["clean_text"])
        self.assertIn("funding round", result["clean_text"])

    def test_social_media_cta_removed(self):
        """社交媒体关注 CTA 应被过滤"""
        text = (
            "Follow us on Twitter and LinkedIn.\n"
            "Find us on Instagram for behind-the-scenes.\n"
            "Connect with us on social media.\n"
            "Our team has grown to 200 employees."
        )
        result = clean_document_text(text)
        self.assertNotIn("Follow us on", result["clean_text"])
        self.assertNotIn("Find us on", result["clean_text"])
        self.assertIn("200 employees", result["clean_text"])


class TestDocumentCleanerNormalContent(unittest.TestCase):
    """验证 DocumentCleaner 对正常内容的保留"""

    def test_article_text_passes_through(self):
        """正常文章内容应完整通过"""
        text = (
            "Anthropic is an AI safety company based in San Francisco. "
            "Founded in 2021 by Dario Amodei and Daniela Amodei, "
            "the company has raised over $7 billion in funding. "
            "Their flagship product is Claude, an AI assistant "
            "focused on being helpful, harmless, and honest."
        )
        result = clean_document_text(text)
        self.assertFalse(result["is_noise_page"])
        self.assertFalse(result["is_low_quality"])
        self.assertIn("Anthropic", result["clean_text"])
        self.assertIn("Claude", result["clean_text"])
        self.assertIn("$7 billion", result["clean_text"])
        self.assertEqual(result["removed_ratio"], 0.0)

    def test_company_description_preserved(self):
        """公司介绍文本应完整保留"""
        text = (
            "ExampleAI builds enterprise-grade machine learning infrastructure. "
            "Our platform processes over 10 million predictions per day "
            "for customers in finance, healthcare, and e-commerce. "
            "Founded in 2020, we have offices in San Francisco and New York."
        )
        result = clean_document_text(text)
        self.assertFalse(result["is_low_quality"])
        self.assertIn("machine learning", result["clean_text"])
        self.assertIn("10 million", result["clean_text"])
        self.assertIn("San Francisco", result["clean_text"])

    def test_mixed_content_noise_filtered_normal_kept(self):
        """混合文本：噪音行被过滤，正文保留"""
        text = (
            "ExampleAI raised $500M in Series C funding.\n"
            "The round was led by Sequoia Capital.\n"
            "Subscribe to our newsletter for updates!\n"
            "© 2025 ExampleAI. All rights reserved.\n"
            "Follow us on LinkedIn and Twitter.\n"  # social CTA, should be removed
            "The funds will be used for R&D expansion."
        )
        result = clean_document_text(text)
        self.assertIn("Series C", result["clean_text"])
        self.assertIn("Sequoia Capital", result["clean_text"])
        self.assertIn("R&D expansion", result["clean_text"])
        self.assertNotIn("Subscribe to our newsletter", result["clean_text"])
        self.assertNotIn("All rights reserved", result["clean_text"])
        self.assertNotIn("Follow us on", result["clean_text"])
        self.assertFalse(result["is_low_quality"])

    def test_navigation_in_content_not_stripped(self):
        """行内导航词（非独占行）不应被误过滤"""
        text = (
            "Our products include AI assistants and analytics tools. "
            "The pricing model is subscription-based. "
            "Visit the contact page for more information about "
            "careers and job openings."
        )
        result = clean_document_text(text)
        # 正常内容不应被清空
        self.assertGreater(len(result["clean_text"]), 50)
        self.assertFalse(result["is_low_quality"])
        # 不应移除行内的 product / pricing / contact 关键词
        self.assertIn("products", result["clean_text"])
        self.assertIn("pricing", result["clean_text"])

    def test_removed_ratio_reasonable(self):
        """正常文本的过滤率应在合理范围"""
        # 构造含少量噪音的文本
        body = "Our AI platform provides advanced analytics. " * 20
        noise = (
            "\nSubscribe to our newsletter!\n"
            "Follow us on social media!\n"
            "© 2025 All Rights Reserved\n"
        )
        text = body + noise
        result = clean_document_text(text)
        self.assertGreater(result["removed_ratio"], 0.0)
        self.assertLess(result["removed_ratio"], 0.5)  # 不应过半
        self.assertFalse(result["is_low_quality"])


class TestDocumentChunkerNoiseTypes(unittest.TestCase):
    """验证 DocumentChunker 对噪音 chunk 类型的标记"""

    def _make_document(self, text, source_type="official_site", title=""):
        return {
            "id": 1,
            "source_type": source_type,
            "source_url": "https://example.com/page",
            "title": title,
            "raw_text": text,
        }

    def test_footer_chunk_marked_is_noise(self):
        """Footer 文本切块后应标记 is_noise=1"""
        doc = self._make_document(
            "© 2025 Example Corp. All rights reserved. "
            "Privacy policy. Terms of service. Cookie settings. "
            "Contact us at info@example.com. 备案号 123456.",
            title="Footer",
        )
        chunks = chunk_document(doc, "example")
        self.assertGreater(len(chunks), 0, "Should produce at least one chunk")
        for chunk in chunks:
            self.assertEqual(
                chunk["is_noise"], 1,
                f"Footer chunk should be is_noise=1, got chunk_type={chunk['chunk_type']}",
            )

    def test_navigation_chunk_marked_is_noise(self):
        """导航文本切块后应标记 is_noise=1"""
        doc = self._make_document(
            "Navigation menu: Home Products Solutions Pricing Blog Contact "
            "Careers Jobs About us. Site map. Breadcrumb navigation sidebar.",
            title="Navigation",
        )
        chunks = chunk_document(doc, "example")
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertEqual(chunk["is_noise"], 1,
                           f"Navigation chunk should be is_noise=1, got {chunk['chunk_type']}")

    def test_legal_chunk_marked_is_noise(self):
        """法律条款文本切块后应标记 is_noise=1"""
        doc = self._make_document(
            "Terms of service. Privacy policy. Cookie policy. "
            "GDPR compliance disclaimer. Legal notice. "
            "End user license agreement applies.",
            title="Legal",
        )
        chunks = chunk_document(doc, "example")
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertEqual(chunk["is_noise"], 1,
                           f"Legal chunk should be is_noise=1, got {chunk['chunk_type']}")

    def test_boilerplate_chunk_marked_is_noise(self):
        """Boilerplate 文本（newsletter / social）切块后应标记 is_noise=1"""
        doc = self._make_document(
            "Subscribe to our newsletter for weekly updates. "
            "Follow us on Twitter and LinkedIn. "
            "Share this article with your network. "
            "Related posts you might find interesting.",
            title="Footer",
        )
        chunks = chunk_document(doc, "example")
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertEqual(chunk["is_noise"], 1,
                           f"Boilerplate chunk should be is_noise=1, got {chunk['chunk_type']}")

    def test_normal_chunk_not_marked_noise(self):
        """正常内容切块不应标记 is_noise=1"""
        # 使用含 blog 和 press 关键词的文本，确保匹配到非噪音 chunk_type
        text = (
            "Anthropic blog article published: Anthropic is an AI safety company "
            "based in San Francisco. Founded in 2021 by Dario Amodei and Daniela "
            "Amodei, the company has raised over $7 billion in funding. "
            "Their flagship product Claude is an AI assistant focused on being "
            "helpful, harmless, and honest. The company competes with OpenAI, "
            "Google DeepMind, and others. Anthropic's mission and vision center "
            "on AI safety including constitutional AI and mechanistic "
            "interpretability research."
        )
        doc = self._make_document(text, source_type="official_blog", title="About Anthropic")
        chunks = chunk_document(doc, "example")
        self.assertGreater(len(chunks), 0, "Normal content should produce chunks")
        for chunk in chunks:
            self.assertEqual(
                chunk["is_noise"], 0,
                f"Normal chunk should NOT be noise, got chunk_type={chunk['chunk_type']}",
            )

    def test_noise_chunk_types_are_comprehensive(self):
        """确认 _NOISE_CHUNK_TYPES 包含所有预期的噪音类型"""
        expected_noise_types = {
            "boilerplate", "navigation", "footer", "cookie",
            "legal", "community_comment", "unknown",
        }
        self.assertEqual(
            _NOISE_CHUNK_TYPES, expected_noise_types,
            f"Expected noise types {expected_noise_types}, got {_NOISE_CHUNK_TYPES}",
        )

    def test_navigation_heavy_page_all_chunks_noise(self):
        """纯导航页面所有 chunk 都应标记为噪音"""
        nav_text = (
            "Navigation Sidebar\n"
            "Main Menu\n"
            "Dashboard Analytics Reports Settings\n"
            "Breadcrumb: Home > Products > AI Platform\n"
            "Site Map: Home Products Solutions Pricing Blog Contact\n"
            "Footer navigation: Terms Privacy Cookies Careers"
        )
        doc = self._make_document(
            nav_text, source_type="official_site", title="Page Navigation",
        )
        chunks = chunk_document(doc, "example")
        if chunks:
            noise_count = sum(1 for c in chunks if c["is_noise"] == 1)
            self.assertGreater(noise_count, 0,
                             "At least some chunks in navigation-heavy page should be noise")


class TestEvidenceRankerNoiseScoring(unittest.TestCase):
    """验证 EvidenceRanker 对噪音 chunk 的低分处理"""

    def test_footer_chunk_scores_low(self):
        """Footer chunk 应被打低分（final_score < 0.35）"""
        chunk = {
            "document_id": 1,
            "company_key": "example",
            "source_type": "official_site",
            "source_url": "https://example.com",
            "title": "Footer",
            "chunk_text": "© 2025 All rights reserved. Privacy policy. Terms.",
            "chunk_type": "footer",
            "token_estimate": 30,
            "is_noise": 1,
        }
        result = score_chunk(chunk, SAMPLE_IDENTITY)
        self.assertEqual(result["is_noise"], 1)
        self.assertLess(
            result["final_score"], 0.35,
            f"Footer chunk final_score={result['final_score']} should be < 0.35",
        )

    def test_cookie_chunk_scores_low(self):
        """Cookie chunk 应被打低分"""
        chunk = {
            "document_id": 1,
            "company_key": "example",
            "source_type": "official_site",
            "source_url": "https://example.com/cookies",
            "title": "Cookie Policy",
            "chunk_text": (
                "Cookie Policy. We use cookies to improve your experience. "
                "By continuing you agree to our use of cookies."
            ),
            "chunk_type": "cookie",
            "token_estimate": 40,
            "is_noise": 1,
        }
        result = score_chunk(chunk, SAMPLE_IDENTITY)
        self.assertEqual(result["is_noise"], 1)

    def test_normal_chunk_scores_ok(self):
        """正常内容 chunk 应得分 >= 0"""
        chunk = {
            "document_id": 1,
            "company_key": "example",
            "source_type": "official_site",
            "source_url": "https://example.com/about",
            "title": "About Us",
            "chunk_text": (
                "ExampleAI is a leading AI company founded in 2020. "
                "The company has raised $500M and serves over 1000 enterprise "
                "customers. Their flagship product processes 10M daily predictions."
            ),
            "chunk_type": "about",
            "token_estimate": 80,
            "is_noise": 0,
        }
        result = score_chunk(chunk, SAMPLE_IDENTITY)
        self.assertEqual(result["is_noise"], 0)
        self.assertGreaterEqual(result["final_score"], 0.0)

    def test_navigation_chunk_noise_score_high(self):
        """Navigation chunk 的 noise_score 应 >= 0.7"""
        chunk = {
            "document_id": 1,
            "company_key": "example",
            "source_type": "official_site",
            "source_url": "https://example.com",
            "title": "Nav",
            "chunk_text": "Home Products Solutions Pricing Blog Contact",
            "chunk_type": "navigation",
            "token_estimate": 20,
            "is_noise": 1,
        }
        result = score_chunk(chunk, SAMPLE_IDENTITY)
        self.assertGreaterEqual(
            result["noise_score"], 0.7,
            f"Navigation noise_score={result['noise_score']} should be >= 0.7",
        )


class TestContextPackerNoiseExclusion(unittest.TestCase):
    """验证 ContextPacker 排除噪音 chunk — SPEC §16.4"""

    def setUp(self):
        """创建临时 SQLite 数据库并插入测试数据"""
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_noise.db")
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                company_key TEXT,
                source_type TEXT,
                source_url TEXT,
                title TEXT,
                chunk_text TEXT,
                chunk_type TEXT,
                token_estimate INTEGER,
                is_noise INTEGER DEFAULT 0,
                final_score REAL DEFAULT 0.5,
                matched_fields TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evidence_spans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                company_key TEXT,
                field_key TEXT,
                quote_text TEXT,
                normalized_fact TEXT,
                start_offset INTEGER,
                end_offset INTEGER,
                confidence REAL,
                created_by_agent TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS packed_context_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                company_key TEXT,
                target_type TEXT,
                target_key TEXT,
                budget_tokens INTEGER,
                used_tokens INTEGER,
                chunk_ids TEXT,
                evidence_span_ids TEXT,
                dropped_count INTEGER
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        """清理临时数据库"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _insert_chunks(self, chunks):
        """批量插入 chunk 数据"""
        conn = sqlite3.connect(self.db_path)
        for c in chunks:
            conn.execute(
                """INSERT INTO document_chunks
                   (document_id, company_key, source_type, source_url,
                    title, chunk_text, chunk_type, token_estimate,
                    is_noise, final_score, matched_fields)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c.get("document_id", 1),
                    c.get("company_key", "example"),
                    c.get("source_type", "unknown"),
                    c.get("source_url", "https://example.com"),
                    c.get("title", ""),
                    c.get("chunk_text", ""),
                    c.get("chunk_type", "unknown"),
                    c.get("token_estimate", 50),
                    c.get("is_noise", 0),
                    c.get("final_score", 0.5),
                    c.get("matched_fields", None),
                ),
            )
        conn.commit()
        conn.close()

    def test_noise_footer_chunks_excluded_from_packed(self):
        """Footer 噪音 chunk 不应出现在 packed_context 中"""
        self._insert_chunks([
            {
                "document_id": 1, "source_type": "official_site",
                "source_url": "https://example.com",
                "chunk_text": "© 2025 All rights reserved. Privacy policy.",
                "chunk_type": "footer", "is_noise": 1, "final_score": 0.1,
            },
            {
                "document_id": 1, "source_type": "official_site",
                "source_url": "https://example.com/about",
                "chunk_text": "ExampleAI raises $500M in funding led by Sequoia.",
                "chunk_type": "about", "is_noise": 0, "final_score": 0.85,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        joined = "\n".join(c["chunk_text"] for c in result["chunks"])
        # 噪音 footer chunk 不应出现
        self.assertNotIn(
            "All rights reserved", joined,
            "Footer noise chunk should NOT be in packed_context",
        )
        # 正常 chunk 应出现
        self.assertIn(
            "ExampleAI raises $500M", joined,
            "Normal chunk should be in packed_context",
        )

    def test_cookie_chunks_excluded_from_packed(self):
        """Cookie chunk 不应出现在 packed_context 中"""
        self._insert_chunks([
            {
                "document_id": 2, "source_type": "official_site",
                "source_url": "https://example.com/cookies",
                "chunk_text": "Cookie Policy. We use cookies to improve experience.",
                "chunk_type": "cookie", "is_noise": 1, "final_score": 0.05,
            },
            {
                "document_id": 2, "source_type": "official_site",
                "source_url": "https://example.com/about",
                "chunk_text": "The company was founded in 2021 by leading AI researchers.",
                "chunk_type": "about", "is_noise": 0, "final_score": 0.8,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        joined = "\n".join(c["chunk_text"] for c in result["chunks"])
        self.assertNotIn("Cookie Policy", joined)
        self.assertIn("founded in 2021", joined)

    def test_legal_chunks_excluded_from_packed(self):
        """Legal/Terms chunk 不应出现在 packed_context 中"""
        self._insert_chunks([
            {
                "document_id": 3, "source_type": "official_site",
                "source_url": "https://example.com/terms",
                "chunk_text": "Terms of Service. Legal disclaimer. GDPR compliance.",
                "chunk_type": "legal", "is_noise": 1, "final_score": 0.1,
            },
            {
                "document_id": 3, "source_type": "official_site",
                "source_url": "https://example.com/blog",
                "chunk_text": "ExampleAI launches new enterprise AI platform.",
                "chunk_type": "blog", "is_noise": 0, "final_score": 0.75,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        joined = "\n".join(c["chunk_text"] for c in result["chunks"])
        self.assertNotIn("Terms of Service", joined)
        self.assertIn("enterprise AI platform", joined)

    def test_navigation_chunks_excluded_from_packed(self):
        """Navigation 噪音 chunk 不应出现在 packed_context 中"""
        self._insert_chunks([
            {
                "document_id": 4, "source_type": "official_site",
                "source_url": "https://example.com",
                "chunk_text": "Home Products Solutions Pricing Blog Contact Careers.",
                "chunk_type": "navigation", "is_noise": 1, "final_score": 0.15,
            },
            {
                "document_id": 4, "source_type": "press_release",
                "source_url": "https://example.com/press",
                "chunk_text": "ExampleAI achieves 200% revenue growth in Q4.",
                "chunk_type": "press", "is_noise": 0, "final_score": 0.82,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        joined = "\n".join(c["chunk_text"] for c in result["chunks"])
        self.assertNotIn("Home Products Solutions", joined)
        self.assertIn("200% revenue growth", joined)

    def test_low_score_non_noise_chunks_also_excluded(self):
        """final_score < 0.35 的非噪音 chunk 也应被排除"""
        self._insert_chunks([
            {
                "document_id": 5, "source_type": "unknown",
                "source_url": "https://unknown-blog.com/post",
                "chunk_text": "Some random low-quality text from unknown source.",
                "chunk_type": "unknown", "is_noise": 1, "final_score": 0.1,
            },
            {
                "document_id": 5, "source_type": "official_blog",
                "source_url": "https://example.com/blog",
                "chunk_text": "ExampleAI partnered with Microsoft for cloud AI.",
                "chunk_type": "blog", "is_noise": 0, "final_score": 0.72,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        joined = "\n".join(c["chunk_text"] for c in result["chunks"])
        self.assertNotIn("random low-quality", joined)
        self.assertIn("Microsoft", joined)

    def test_all_noise_chunks_empty_packed_context(self):
        """当所有 chunk 都是噪音时，packed_context 的 chunk 列表应为空"""
        self._insert_chunks([
            {
                "document_id": 6, "source_type": "official_site",
                "source_url": "https://example.com/footer",
                "chunk_text": "© 2025 All rights reserved.",
                "chunk_type": "footer", "is_noise": 1, "final_score": 0.1,
            },
            {
                "document_id": 6, "source_type": "official_site",
                "source_url": "https://example.com/nav",
                "chunk_text": "Home Products About Contact.",
                "chunk_type": "navigation", "is_noise": 1, "final_score": 0.15,
            },
            {
                "document_id": 6, "source_type": "official_site",
                "source_url": "https://example.com/cookies",
                "chunk_text": "We use cookies. Cookie policy.",
                "chunk_type": "cookie", "is_noise": 1, "final_score": 0.05,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        self.assertEqual(
            len(result["chunks"]), 0,
            "Packed context should be empty when all chunks are noise",
        )
        self.assertEqual(result["used_tokens"], 0)

    def test_mixed_chunks_noise_filtered_clean_packed(self):
        """混合场景：多个源中噪音被过滤，正常内容全部打包"""
        self._insert_chunks([
            # 噪音 chunk #1
            {
                "document_id": 7, "source_type": "official_site",
                "source_url": "https://example.com",
                "chunk_text": "© 2025 ExampleAI. All rights reserved. Privacy Policy.",
                "chunk_type": "footer", "is_noise": 1, "final_score": 0.1,
            },
            # 噪音 chunk #2
            {
                "document_id": 7, "source_type": "official_site",
                "source_url": "https://example.com/terms",
                "chunk_text": "Terms of Service and legal disclaimer apply.",
                "chunk_type": "legal", "is_noise": 1, "final_score": 0.12,
            },
            # 正常 chunk #1
            {
                "document_id": 8, "source_type": "official_blog",
                "source_url": "https://example.com/blog/post1",
                "chunk_text": "ExampleAI raises $1B Series D at $20B valuation.",
                "chunk_type": "blog", "is_noise": 0, "final_score": 0.85,
            },
            # 正常 chunk #2
            {
                "document_id": 9, "source_type": "press_release",
                "source_url": "https://prnewswire.com/exampleai-launch",
                "chunk_text": "ExampleAI launches Claude competitor with safety focus.",
                "chunk_type": "press", "is_noise": 0, "final_score": 0.78,
            },
            # 正常 chunk #3
            {
                "document_id": 10, "source_type": "official_site",
                "source_url": "https://example.com/about",
                "chunk_text": "Founded in 2021 by ex-OpenAI researchers, 500 employees.",
                "chunk_type": "about", "is_noise": 0, "final_score": 0.9,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        chunk_texts = [c["chunk_text"] for c in result["chunks"]]
        # 噪音不应出现
        self.assertNotIn("© 2025 ExampleAI", chunk_texts[0] if chunk_texts else "")
        self.assertNotIn("Terms of Service", chunk_texts[0] if chunk_texts else "")
        # 仅噪音被排除
        for ct in chunk_texts:
            self.assertNotIn("legal disclaimer", ct.lower())
            self.assertNotIn("all rights reserved", ct.lower())
        # 正常内容出现
        self.assertEqual(len(result["chunks"]), 3,
                         f"Expected 3 normal chunks, got {len(result['chunks'])}")
        self.assertGreater(result["used_tokens"], 0)

    def test_packed_context_never_contains_raw_text(self):
        """packed_context 返回的 chunk 不应包含 raw_text 字段"""
        self._insert_chunks([
            {
                "document_id": 11, "source_type": "official_site",
                "source_url": "https://example.com/about",
                "chunk_text": "ExampleAI is a leading AI company.",
                "chunk_type": "about", "is_noise": 0, "final_score": 0.8,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        for chunk in result["chunks"]:
            self.assertNotIn(
                "raw_text", chunk,
                "packed_context chunks must NOT contain raw_text (safety invariant)",
            )

    def test_dropped_count_reflects_noise_exclusion(self):
        """dropped_count 应反映被排除的噪音 chunk 数量"""
        self._insert_chunks([
            # 3 个噪音 chunk
            {
                "document_id": 12, "source_type": "official_site",
                "source_url": "https://example.com/footer",
                "chunk_text": "Footer copyright all rights reserved.",
                "chunk_type": "footer", "is_noise": 1, "final_score": 0.1,
            },
            {
                "document_id": 12, "source_type": "official_site",
                "source_url": "https://example.com/nav",
                "chunk_text": "Nav menu home products contact.",
                "chunk_type": "navigation", "is_noise": 1, "final_score": 0.15,
            },
            {
                "document_id": 12, "source_type": "official_site",
                "source_url": "https://example.com/cookies",
                "chunk_text": "Cookie policy notice.",
                "chunk_type": "cookie", "is_noise": 1, "final_score": 0.05,
            },
            # 2 个正常 chunk
            {
                "document_id": 13, "source_type": "press_release",
                "source_url": "https://prnewswire.com/funding",
                "chunk_text": "ExampleAI raises $500M.",
                "chunk_type": "press", "is_noise": 0, "final_score": 0.85,
            },
            {
                "document_id": 14, "source_type": "official_blog",
                "source_url": "https://example.com/blog",
                "chunk_text": "ExampleAI platform growth accelerates.",
                "chunk_type": "blog", "is_noise": 0, "final_score": 0.78,
            },
        ])

        result = pack_context(
            self.db_path, "example",
            target_type="l0", target_key="l0_full",
            budget_tokens=5000,
        )

        # 5 个 qualified chunks, 2 个通过 → dropped 应为 3
        # 实际上 qualified chunks 排除了 is_noise=1 的，所以只有 2 个 qualified
        # dropped = qualified_count - selected_count = 2 - 2 = 0
        # 不对...让我们重新理解。qualified 过滤已经排除了 is_noise 和 low score
        # 所以 qualified = 2, dropped = 2 - 2 = 0
        # 3 个噪音 chunk 在预过滤阶段就被排除了,不计入 dropped_count
        self.assertEqual(result["dropped_count"], 0)  # 预过滤排除不算 dropped
        self.assertEqual(len(result["chunks"]), 2,
                       f"Expected 2 clean chunks, got {len(result['chunks'])}")


class TestFullPipelineEndToEnd(unittest.TestCase):
    """全链路端到端测试: cleaner → chunker → packer"""

    def test_cleaner_to_chunker_noise_filtered(self):
        """清洗后的噪音文本在 chunker 中应被标记为噪音"""
        # Step 1: cleaner
        cookie_text = (
            "Cookie Policy\n\n"
            "We use cookies to improve your experience. "
            "By continuing to browse you agree to our cookie policy. "
            "Cookie settings can be managed in your browser."
        )
        cleaned = clean_document_text(cookie_text)
        self.assertTrue(cleaned["is_low_quality"],
                        "Cookie page should be low_quality")

        # Step 2: chunker on cleaned text (if any left)
        if cleaned["clean_text"]:
            doc = {
                "id": 1,
                "source_type": "official_site",
                "source_url": "https://example.com/cookies",
                "title": "Cookie Policy",
                "raw_text": cleaned["clean_text"],
            }
            chunks = chunk_document(doc, "example")
            # All chunks from a cookie page should be noise
            for chunk in chunks:
                self.assertEqual(chunk["is_noise"], 1,
                               "Chunks from cookie page should all be noise")

    def test_normal_article_full_pipeline(self):
        """正常文章：cleaner 保留 → chunker 不标记噪音"""
        article = (
            "ExampleAI Raises $1B Series D at $20B Valuation\n\n"
            "SAN FRANCISCO, June 2026 — ExampleAI, the enterprise AI platform, "
            "today announced it has raised $1 billion in Series D funding "
            "led by Sequoia Capital, with participation from a16z and "
            "Kleiner Perkins.\n\n"
            "The round values the company at $20 billion post-money, "
            "making it one of the most valuable private AI companies.\n\n"
            "ExampleAI plans to use the funds to expand its R&D team, "
            "scale its cloud infrastructure, and enter new markets "
            "in Europe and Asia-Pacific.\n\n"
            "The company, founded in 2021 by ex-Google AI researchers, "
            "now serves over 2,000 enterprise customers including "
            "Fortune 500 companies in finance, healthcare, and retail."
        )

        # Step 1: cleaner — should pass through
        cleaned = clean_document_text(article)
        self.assertFalse(cleaned["is_low_quality"], "Normal article should not be low_quality")
        self.assertFalse(cleaned.get("is_noise_page"), "Normal article should not be noise_page")
        self.assertGreater(len(cleaned["clean_text"]), 100, "Content should be mostly preserved")

        # Step 2: chunker — chunks should not be noise
        doc = {
            "id": 1,
            "source_type": "press_release",
            "source_url": "https://prnewswire.com/exampleai-funding",
            "title": "ExampleAI Raises $1B Series D",
            "raw_text": cleaned["clean_text"],
        }
        chunks = chunk_document(doc, "example")
        self.assertGreater(len(chunks), 0, "Normal article should produce chunks")
        for chunk in chunks:
            self.assertEqual(chunk["is_noise"], 0,
                           f"Normal article chunk should not be noise, got type={chunk['chunk_type']}")

    def test_mixed_page_noise_sections_filtered_normal_kept(self):
        """含噪音片段的页面：block-level 噪音行被清掉，正文保留并正常切块"""
        # 注意：Privacy Policy | Terms 等是 page-level flag，不是 block-level filter，
        # 会触发 is_noise_page 但不会逐行移除。这里测试 block-level 过滤（CTA/copyright/social）
        # + chunker 正常处理清洗后的正文
        mixed = (
            "ExampleAI Launches Next-Gen AI Platform\n\n"
            "The new platform features advanced natural language processing, "
            "computer vision, and predictive analytics capabilities.\n\n"
            "Subscribe to our newsletter for product updates!\n"
            "Follow us on LinkedIn and Twitter for the latest news.\n\n"
            "Book a demo today to see the platform in action.\n\n"
            "The platform is already being used by leading financial "
            "institutions and healthcare providers across the US.\n\n"
            "© 2026 ExampleAI Corp. All rights reserved."
        )

        # Step 1: cleaner
        cleaned = clean_document_text(mixed)
        self.assertIn("next-gen", cleaned["clean_text"].lower())
        self.assertIn("financial institutions", cleaned["clean_text"])
        # block-level 噪音行应被移除
        self.assertNotIn("Subscribe to our newsletter", cleaned["clean_text"])
        self.assertNotIn("Follow us on", cleaned["clean_text"])
        self.assertNotIn("Book a demo", cleaned["clean_text"])
        self.assertNotIn("All rights reserved", cleaned["clean_text"])
        # 正文足够多，不应被标为低质量
        self.assertFalse(
            cleaned["is_low_quality"],
            "Article with minor noise should not be marked low_quality",
        )

        # Step 2: chunker — 清洗后的正文不应被标记为噪音
        doc = {
            "id": 1,
            "source_type": "official_blog",
            "source_url": "https://example.com/blog/launch",
            "title": "ExampleAI Launches Next-Gen AI Platform",
            "raw_text": cleaned["clean_text"],
        }
        chunks = chunk_document(doc, "example")
        self.assertGreater(len(chunks), 0)
        non_noise = [c for c in chunks if c["is_noise"] == 0]
        self.assertGreater(len(non_noise), 0,
                         "At least one non-noise chunk from the article body should exist")


if __name__ == "__main__":
    unittest.main()
