"""MarketDataBridge — 桥接 market_intelligence 模块的市场数据到主管道

   从 market_estimates 表读取已估算的市场/融资数据，
   在 L3 调用前注入 packed_context，让 L3 引用而非重新推断。
"""

from __future__ import annotations
import sqlite3
from pathlib import Path


MIN_CONFIDENCE_FOR_INJECTION = 0.30


class MarketDataBridge:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            _project = Path(__file__).resolve().parent.parent.parent
            db_path = str(_project / "db" / "research_db.sqlite")
        self.db_path = db_path

    def fetch_market_context(self, company_key: str) -> dict:
        """从 market_estimates 表读取置信度足够的数据"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""
                SELECT field_key, result_value, result_text, currency, year,
                       estimate_type, confidence, status, source_url, disclaimer
                FROM market_estimates
                WHERE company_key = ? AND status != 'unavailable'
                  AND confidence >= ?
                ORDER BY confidence DESC
            """, (company_key, MIN_CONFIDENCE_FOR_INJECTION)).fetchall()
        except sqlite3.OperationalError:
            # Table might not exist yet
            return {}
        finally:
            conn.close()

        result = {}
        for row in rows:
            result[row["field_key"]] = {
                "value": row["result_value"],
                "value_text": row["result_text"],
                "currency": row["currency"],
                "year": row["year"],
                "estimate_type": row["estimate_type"],
                "confidence": row["confidence"],
                "source_url": row["source_url"],
            }
        return result

    def inject_into_l3_context(self, company_key: str, packed_context: str) -> str:
        """将市场数据注入 packed_context"""
        market_data = self.fetch_market_context(company_key)
        if not market_data:
            return packed_context
        block = self._format_context_block(market_data)
        return packed_context + "\n" + block

    def _format_context_block(self, market_data: dict) -> str:
        lines = [
            "",
            "## 已知市场数据（来源: market_intelligence 模块，可直接引用）",
        ]
        for field_key, item in market_data.items():
            source = item.get("source_url") or "估算"
            lines.append(
                f"- {field_key}: {item['value_text']} "
                f"({item.get('currency', 'USD')}, {item.get('year', 'N/A')}年, "
                f"来源: {source})"
            )
        return "\n".join(lines)
