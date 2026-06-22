"""TimeSeriesSnapshotter — 每次研究存快照，支持字段级跨时间对比"""

from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime


class TimeSeriesSnapshotter:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            _project = Path(__file__).resolve().parent.parent.parent
            db_path = str(_project / "db" / "research_db.sqlite")
        self.db_path = db_path

    def snapshot(
        self,
        company_key: str,
        fields: dict,
        snapshot_type: str = "fields_only",
        research_run_id: str | None = None,
    ) -> int:
        """写入本次研究的字段快照。返回写入行数。"""
        import json
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        count = 0
        try:
            for field_key, field_data in fields.items():
                value = field_data.get("value", "")
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)

                conn.execute(
                    """INSERT INTO company_snapshots
                       (company_key, snapshot_at, snapshot_type, field_key,
                        field_value, value_type, norm_value, unit,
                        resolution_status, confidence_level, source_urls,
                        research_run_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        company_key, now, snapshot_type, field_key,
                        str(value) if value else None,
                        field_data.get("value_type"),
                        field_data.get("norm_value"),
                        field_data.get("unit"),
                        field_data.get("resolution_status"),
                        field_data.get("confidence_level"),
                        field_data.get("source_urls"),
                        research_run_id,
                    ),
                )
                count += 1
            conn.commit()
        except sqlite3.OperationalError:
            # Table doesn't exist — no-op
            pass
        finally:
            conn.close()
        return count

    def diff(self, company_key: str, field_key: str) -> dict | None:
        """返回某字段的最新两次快照差异。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT field_value, snapshot_at FROM company_snapshots
                   WHERE company_key = ? AND field_key = ? AND field_value IS NOT NULL
                   ORDER BY snapshot_at DESC LIMIT 2""",
                (company_key, field_key),
            ).fetchall()
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()

        if len(rows) < 2:
            return None

        current, previous = rows[0], rows[1]

        direction = "same"
        try:
            cur_val = float(current["field_value"].replace("$", "").replace("M", "000000").replace("B", "000000000").replace("K", "000").strip())
            prev_val = float(previous["field_value"].replace("$", "").replace("M", "000000").replace("B", "000000000").replace("K", "000").strip())
            if cur_val > prev_val:
                direction = "up"
            elif cur_val < prev_val:
                direction = "down"
        except (ValueError, AttributeError):
            pass

        return {
            "field_key": field_key,
            "previous": {"value": previous["field_value"], "snapshot_at": previous["snapshot_at"]},
            "current": {"value": current["field_value"], "snapshot_at": current["snapshot_at"]},
            "direction": direction,
        }

    def list_comparable_fields(self, company_key: str) -> list[str]:
        """返回有 2+ 次快照的可对比字段列表"""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """SELECT field_key, COUNT(*) as cnt FROM company_snapshots
                   WHERE company_key = ? AND field_value IS NOT NULL
                   GROUP BY field_key HAVING cnt >= 2""",
                (company_key,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
        return [row[0] for row in rows]
