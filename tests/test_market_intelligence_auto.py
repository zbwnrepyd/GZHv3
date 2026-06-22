import unittest, sys, tempfile, os, sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))


class TestMarketIntelligenceAutoTrigger(unittest.TestCase):
    def test_bridge_detects_empty_data(self):
        from research.market_data_bridge import MarketDataBridge
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        try:
            conn = sqlite3.connect(tmp.name)
            conn.execute("""CREATE TABLE IF NOT EXISTS market_estimates (
                id TEXT PRIMARY KEY, company_key TEXT, field_key TEXT,
                estimate_type TEXT, result_value REAL, result_text TEXT,
                currency TEXT, year INTEGER, confidence REAL, status TEXT,
                source_url TEXT, disclaimer TEXT)""")
            conn.commit(); conn.close()
            bridge = MarketDataBridge(db_path=tmp.name)
            self.assertEqual(len(bridge.fetch_market_context("no_data_co")), 0)
        finally:
            os.unlink(tmp.name)

    def test_bridge_finds_existing_data(self):
        from research.market_data_bridge import MarketDataBridge
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        try:
            conn = sqlite3.connect(tmp.name)
            conn.execute("""CREATE TABLE IF NOT EXISTS market_estimates (
                id TEXT PRIMARY KEY, company_key TEXT, field_key TEXT,
                estimate_type TEXT, result_value REAL, result_text TEXT,
                currency TEXT, year INTEGER, confidence REAL, status TEXT,
                source_url TEXT, disclaimer TEXT)""")
            conn.execute("INSERT INTO market_estimates VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("id1","test_co","tam_value","proxy",10.5,"$10.5B","USD",2024,0.7,"proxy","url",""))
            conn.commit(); conn.close()
            bridge = MarketDataBridge(db_path=tmp.name)
            ctx = bridge.fetch_market_context("test_co")
            self.assertIn("tam_value", ctx)
            self.assertEqual(ctx["tam_value"]["value_text"], "$10.5B")
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
