"""Tests for MarketDataBridge — 市场数据桥接到 L3 上下文"""

import unittest
import tempfile
import sqlite3
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.market_data_bridge import MarketDataBridge


class TestMarketDataBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp_name = self.tmp.name
        self.tmp.close()

        conn = sqlite3.connect(self.tmp_name)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_estimates (
                id TEXT PRIMARY KEY,
                company_key TEXT NOT NULL,
                field_key TEXT NOT NULL,
                estimate_type TEXT NOT NULL CHECK (
                    estimate_type IN ('bottom_up','comparable','proxy','direct_report','funding_calc')
                ),
                formula TEXT,
                inputs_json TEXT,
                result_value REAL,
                result_text TEXT,
                currency TEXT DEFAULT 'USD',
                year INTEGER,
                confidence REAL NOT NULL DEFAULT 0.0,
                evidence_ids TEXT,
                status TEXT NOT NULL DEFAULT 'derived' CHECK (
                    status IN ('confirmed','derived','proxy','llm_located','unavailable','not_applicable')
                ),
                assumptions TEXT,
                disclaimer TEXT,
                region TEXT,
                segment TEXT,
                source_url TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Insert 3 rows: 2 good, 1 low confidence
        conn.execute("""
            INSERT INTO market_estimates
                (id, company_key, field_key, estimate_type, result_value, result_text,
                 currency, year, confidence, status, source_url)
            VALUES
                ('e1','testco','market_size_value','bottom_up',5200000000.0,'$5.2B',
                 'USD',2025,0.75,'derived','https://example.com/tam'),
                ('e2','testco','total_funding','funding_calc',150000000.0,'$150M',
                 'USD',2025,0.85,'proxy','https://example.com/funding'),
                ('e3','testco','tam','comparable',9900000000.0,'$9.9B',
                 'USD',2024,0.15,'proxy','https://example.com/lowconf')
        """)
        conn.commit()
        conn.close()

        self.bridge = MarketDataBridge(db_path=self.tmp_name)

    def tearDown(self):
        if os.path.exists(self.tmp_name):
            os.unlink(self.tmp_name)

    # ── fetch_market_context tests ──

    def test_fetch_market_context_returns_correct_data(self):
        """已知 company_key 返回置信度足够的数据"""
        result = self.bridge.fetch_market_context("testco")
        self.assertIn("market_size_value", result)
        self.assertIn("total_funding", result)
        self.assertEqual(result["market_size_value"]["value"], 5200000000.0)
        self.assertEqual(result["market_size_value"]["value_text"], "$5.2B")
        self.assertEqual(result["market_size_value"]["confidence"], 0.75)
        self.assertEqual(result["total_funding"]["value"], 150000000.0)
        self.assertEqual(result["total_funding"]["confidence"], 0.85)

    def test_fetch_market_context_returns_empty_for_unknown_company(self):
        """未知 company_key 返回空 dict"""
        result = self.bridge.fetch_market_context("nonexistent")
        self.assertEqual(result, {})

    def test_low_confidence_excluded(self):
        """置信度 < 0.30 的数据被排除"""
        result = self.bridge.fetch_market_context("testco")
        self.assertNotIn("tam", result,
                         "tam has confidence 0.15 and should be excluded")

    # ── inject_into_l3_context tests ──

    def test_inject_appends_market_data_block(self):
        """inject 在有市场数据时追加 block"""
        original = "Some L3 context here"
        augmented = self.bridge.inject_into_l3_context("testco", original)

        self.assertTrue(augmented.startswith(original))
        self.assertIn("market_intelligence 模块", augmented)
        self.assertIn("market_size_value", augmented)
        self.assertIn("total_funding", augmented)
        self.assertIn("$5.2B", augmented)
        self.assertIn("$150M", augmented)
        self.assertNotIn("$9.9B", augmented,
                         "low conf tam should not appear in injected context")

    def test_inject_is_noop_when_no_market_data(self):
        """无市场数据时返回原字符串"""
        original = "Some L3 context here"
        augmented = self.bridge.inject_into_l3_context("nonexistent", original)
        self.assertEqual(augmented, original,
                         "inject should be identity when no data exists")

    # ── _format_context_block tests ──

    def test_format_block_contains_field_keys_and_sources(self):
        """格式化 block 包含 field_key 和 source_url"""
        data = self.bridge.fetch_market_context("testco")
        block = self.bridge._format_context_block(data)

        self.assertIn("market_size_value", block)
        self.assertIn("total_funding", block)
        self.assertIn("https://example.com/tam", block)
        self.assertIn("https://example.com/funding", block)
        self.assertIn("## 已知市场数据", block)

    # ── missing table resilience ──

    def test_missing_table_returns_empty_no_crash(self):
        """表不存在时返回空 dict，不抛异常"""
        # Use a fresh empty db with no market_estimates table
        empty_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        empty_db_name = empty_db.name
        empty_db.close()
        try:
            bridge = MarketDataBridge(db_path=empty_db_name)
            result = bridge.fetch_market_context("anyco")
            self.assertEqual(result, {})
            # inject should also be noop
            ctx = bridge.inject_into_l3_context("anyco", "hello")
            self.assertEqual(ctx, "hello")
        finally:
            os.unlink(empty_db_name)


if __name__ == "__main__":
    unittest.main()
