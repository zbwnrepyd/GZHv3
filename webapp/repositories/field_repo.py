"""字段仓库 — research_fields + final_fields 数据访问"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from typing import Optional


@contextmanager
def _get_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """返回表中已存在的列名集合。"""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# ═══════════════════════════════════════════
# research_fields — LLM 提取的原始字段
# ═══════════════════════════════════════════

# v3 可能新增的 research_fields 列（兼容旧 schema）
_RF_V3_COLS = {
    "value_type": "",
    "norm_value": "",
    "currency_code": "",
    "unit": "",
    "as_of_date": "",
    "evidence_ids": "",
    "source_urls": "",
    "page_no": None,
    "sort_order": 0,
}


def insert_research_field(db_path: str, company_name: str, version: str,
                          field_key: str, field_label: str = "",
                          field_value: str = "", source_type: str = "",
                          source_url: str = "", confidence: str = "",
                          raw_payload: str = "",
                          company_key: str = "") -> int:
    ckey = (company_key or "").strip() or company_name.lower()
    with _get_db(db_path) as conn:
        existing = _existing_columns(conn, "research_fields")
        base_cols = ["company_name", "version", "field_key", "field_label",
                     "field_value", "source_type", "source_url", "confidence",
                     "raw_payload"]
        base_vals = [company_name, version, field_key, field_label,
                     field_value, source_type, source_url, confidence,
                     raw_payload]
        # P0: 增加 company_key
        if "company_key" in existing:
            base_cols.append("company_key")
            base_vals.append(ckey)
        extra_cols = []
        extra_vals = []
        for col, default in _RF_V3_COLS.items():
            if col in existing:
                extra_cols.append(col)
                extra_vals.append(default)
        all_cols = base_cols + extra_cols + ["updated_at"]
        placeholders = ", ".join("?" for _ in all_cols[:-1]) + ", CURRENT_TIMESTAMP"
        sql = f"INSERT OR REPLACE INTO research_fields ({', '.join(all_cols)}) VALUES ({placeholders})"
        conn.execute(sql, base_vals + extra_vals)
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_research_fields_batch(db_path: str, rows: list[dict]) -> int:
    """批量写入 research_fields，返回写入数。P0: 支持 company_key。"""
    with _get_db(db_path) as conn:
        existing = _existing_columns(conn, "research_fields")
        base_cols = ["company_name", "version", "field_key", "field_label",
                     "field_value", "source_type", "source_url", "confidence",
                     "raw_payload"]
        if "company_key" in existing:
            base_cols.append("company_key")
        extra_cols = [c for c in _RF_V3_COLS if c in existing]
        all_cols = base_cols + extra_cols + ["updated_at"]
        placeholders = ", ".join("?" for _ in all_cols[:-1]) + ", CURRENT_TIMESTAMP"
        sql = f"INSERT OR REPLACE INTO research_fields ({', '.join(all_cols)}) VALUES ({placeholders})"
        count = 0
        for r in rows:
            ckey = r.get("company_key", "").strip() or r.get("company_name", "").lower()
            base_vals = [r.get("company_name"), r.get("version", "standard"),
                         r["field_key"], r.get("field_label", ""),
                         r.get("field_value", ""), r.get("source_type", ""),
                         r.get("source_url", ""), r.get("confidence", ""),
                         r.get("raw_payload", "")]
            if "company_key" in existing:
                base_vals.append(ckey)
            extra_vals = [r.get(c, _RF_V3_COLS[c]) for c in extra_cols]
            conn.execute(sql, base_vals + extra_vals)
            count += 1
        conn.commit()
        return count


def get_research_fields(db_path: str, company_name: str,
                        version: str = "standard") -> list[dict]:
    """获取 research_fields，优先用 company_key 查询，缺失回退 company_name。"""
    with _get_db(db_path) as conn:
        # P0: 优先 company_key，回退 company_name
        existing = _existing_columns(conn, "research_fields")
        has_ckey = "company_key" in existing
        if has_ckey:
            exact_rows = conn.execute(
                """SELECT * FROM research_fields
                   WHERE company_name=? AND version=?
                   ORDER BY field_key""",
                (company_name, version)).fetchall()
            if exact_rows:
                return [dict(r) for r in exact_rows]
            rows = conn.execute(
                """SELECT * FROM research_fields
                   WHERE (company_key=? OR (company_key='' AND company_name=?))
                   AND version=?
                   ORDER BY field_key""",
                (company_name.lower(), company_name, version)).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM research_fields
                   WHERE company_name=? AND version=?
                   ORDER BY field_key""",
                (company_name, version)).fetchall()
        return [dict(r) for r in rows]


def get_research_field_value(db_path: str, company_name: str,
                             field_key: str, version: str = "standard") -> Optional[str]:
    with _get_db(db_path) as conn:
        existing = _existing_columns(conn, "research_fields")
        has_ckey = "company_key" in existing
        if has_ckey:
            row = conn.execute(
                """SELECT field_value FROM research_fields
                   WHERE (company_key=? OR (company_key='' AND company_name=?))
                   AND version=? AND field_key=?""",
                (company_name.lower(), company_name, version, field_key)).fetchone()
        else:
            row = conn.execute(
                """SELECT field_value FROM research_fields
                   WHERE company_name=? AND version=? AND field_key=?""",
                (company_name, version, field_key)).fetchone()
        return row["field_value"] if row else None


# ═══════════════════════════════════════════
# final_fields — 人工定稿字段
# ═══════════════════════════════════════════

# v3 可能新增的 final_fields 列（兼容旧 schema）
_FF_V3_COLS = {
    "card_set_key": "v1",
    "page_no": None,
    "block_key": "",
    "block_type": "field",
    "render_json": "",
    "export_targets": '["markdown","pdf","notion"]',
}


def upsert_final_field(db_path: str, company_name: str, field_key: str,
                       final_value: str, field_label: str = "",
                       source_version: str = "standard",
                       status: str = "draft",
                       card_set_key: str = "v1",
                       page_no: int = None,
                       block_key: str = "",
                       block_type: str = "field",
                       render_json: str = "",
                       export_targets: str = '["markdown","pdf","notion"]',
                       company_key: str = "") -> int:
    ckey = (company_key or "").strip() or company_name.lower()
    with _get_db(db_path) as conn:
        existing = _existing_columns(conn, "final_fields")
        base_cols = ["company_name", "field_key", "field_label", "final_value",
                     "source_version", "status"]
        base_vals = [company_name, field_key, field_label or "", final_value,
                     source_version, status]
        if "company_key" in existing:
            base_cols.append("company_key")
            base_vals.append(ckey)
        extra_cols = [c for c in _FF_V3_COLS if c in existing]
        param_map = {
            "card_set_key": card_set_key, "page_no": page_no,
            "block_key": block_key, "block_type": block_type,
            "render_json": render_json, "export_targets": export_targets,
        }
        extra_vals = [param_map[c] for c in extra_cols]
        all_cols = base_cols + extra_cols + ["updated_at"]
        placeholders = ", ".join("?" for _ in all_cols[:-1]) + ", CURRENT_TIMESTAMP"

        # ON CONFLICT DO UPDATE
        set_parts = [
            "final_value=excluded.final_value",
            "field_label=excluded.field_label",
            "source_version=excluded.source_version",
            "status=excluded.status",
        ]
        if "company_key" in existing:
            set_parts.append("company_key=excluded.company_key")
        for c in extra_cols:
            set_parts.append(f"{c}=excluded.{c}")
        set_parts.append("updated_at=CURRENT_TIMESTAMP")
        set_clause = ", ".join(set_parts)

        sql = (f"INSERT INTO final_fields ({', '.join(all_cols)}) "
               f"VALUES ({placeholders}) "
               f"ON CONFLICT(company_name, field_key) DO UPDATE SET {set_clause}")
        cur = conn.execute(sql, base_vals + extra_vals)
        conn.commit()
        return cur.lastrowid


def get_final_fields(db_path: str, company_name: str) -> list[dict]:
    """获取 final_fields，优先用 company_key 查询，缺失回退 company_name。"""
    with _get_db(db_path) as conn:
        existing = _existing_columns(conn, "final_fields")
        has_ckey = "company_key" in existing
        if has_ckey:
            rows = conn.execute(
                """SELECT * FROM final_fields
                   WHERE (company_key=? OR (company_key='' AND company_name=?))
                   AND status != 'hidden'
                   ORDER BY field_key""",
                (company_name.lower(), company_name)).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM final_fields
                   WHERE company_name=? AND status != 'hidden'
                   ORDER BY field_key""",
                (company_name,)).fetchall()
        return [dict(r) for r in rows]


# Sentinel: 区分「从未定稿」(None) 和「用户显式清空」("")
_EMPTY_FINAL = object()


def get_final_field_value(db_path: str, company_name: str,
                          field_key: str) -> Optional[str]:
    """返回 final_value，若从未定稿返回 None，若用户显式清空返回 _EMPTY_FINAL sentinel。

    P0: 优先 company_key，回退 company_name。
    """
    ckey = company_name.lower()
    with _get_db(db_path) as conn:
        existing = _existing_columns(conn, "final_fields")
        has_ckey = "company_key" in existing
        if has_ckey:
            row = conn.execute(
                """SELECT final_value FROM final_fields
                   WHERE (company_key=? OR (company_key='' AND company_name=?))
                   AND field_key=? AND status != 'hidden'""",
                (ckey, company_name, field_key)).fetchone()
        else:
            row = conn.execute(
                """SELECT final_value FROM final_fields
                   WHERE company_name=? AND field_key=? AND status != 'hidden'""",
                (company_name, field_key)).fetchone()
        if row is None:
            return None
        val = row["final_value"]
        return val if val else _EMPTY_FINAL


def set_field_status(db_path: str, company_name: str, field_key: str,
                     status: str, company_key: str = "") -> bool:
    """P0: 优先 company_key，回退 company_name。"""
    ckey = (company_key or "").strip() or company_name.lower()
    with _get_db(db_path) as conn:
        existing = _existing_columns(conn, "final_fields")
        has_ckey = "company_key" in existing
        if has_ckey:
            cur = conn.execute(
                """UPDATE final_fields SET status=?, updated_at=CURRENT_TIMESTAMP
                   WHERE (company_key=? OR (company_key='' AND company_name=?))
                   AND field_key=?""",
                (status, ckey, company_name, field_key))
        else:
            cur = conn.execute(
                """UPDATE final_fields SET status=?, updated_at=CURRENT_TIMESTAMP
                   WHERE company_name=? AND field_key=?""",
                (status, company_name, field_key))
        conn.commit()
        return cur.rowcount > 0


def confirm_all_fields(db_path: str, company_name: str,
                       company_key: str = "") -> int:
    """P0: 优先 company_key，回退 company_name。"""
    ckey = (company_key or "").strip() or company_name.lower()
    with _get_db(db_path) as conn:
        existing = _existing_columns(conn, "final_fields")
        has_ckey = "company_key" in existing
        if has_ckey:
            cur = conn.execute(
                """UPDATE final_fields SET status='confirmed',
                   updated_at=CURRENT_TIMESTAMP
                   WHERE (company_key=? OR (company_key='' AND company_name=?))
                   AND status='draft'""",
                (ckey, company_name))
        else:
            cur = conn.execute(
                """UPDATE final_fields SET status='confirmed',
                   updated_at=CURRENT_TIMESTAMP
                   WHERE company_name=? AND status='draft'""",
                (company_name,))
        conn.commit()
        return cur.rowcount


# ═══════════════════════════════════════════
# final_card_values — 卡片展示读模型 (SPEC v3 Section 5.2)
# ═══════════════════════════════════════════

def get_final_card_values(db_path: str, company_key: str, card_no: int = None) -> list[dict]:
    """SPEC v3: Read final_card_values as the card display model.

    返回按 card_no, field_key 排序的记录列表。
    card_no 可选：传入时只返回该卡片页的记录；不传或为 None 时返回全部卡片。
    """
    with _get_db(db_path) as conn:
        if card_no is not None:
            rows = conn.execute(
                """SELECT * FROM final_card_values
                   WHERE company_key=? AND card_no=?
                   ORDER BY card_no, field_key""",
                (company_key, card_no),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM final_card_values
                   WHERE company_key=?
                   ORDER BY card_no, field_key""",
                (company_key,),
            ).fetchall()
        return [dict(r) for r in rows]


def update_field_status_batch(db_path: str, company_name: str, version: str,
                              results: list[dict]) -> int:
    """批量更新 research_fields 的分辨率状态列 + 写 resolution_logs

    P0: 优先 company_key，回退 company_name。
    results: [{"field_key": str, "resolution_status": str, "unavailable_reason": str|None,
               "resolution_method": str, "field_value": str, "company_key": str}, ...]
    返回更新条数
    """
    count = 0
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(research_fields)").fetchall()}
        has_ckey = "company_key" in existing

        for r in results:
            fk = r.get("field_key", "")
            status = r.get("resolution_status", "")
            reason = r.get("unavailable_reason", "")
            method = r.get("resolution_method", "")
            ckey = r.get("company_key", "").strip() or company_name.lower()
            if not fk or not status:
                continue

            # 更新 research_fields — 优先 company_key
            if has_ckey:
                conn.execute(
                    """UPDATE research_fields
                       SET resolution_status=?, unavailable_reason=?,
                           resolution_method=?, updated_at=CURRENT_TIMESTAMP
                       WHERE (company_key=? OR (company_key='' AND company_name=?))
                       AND version=? AND field_key=?""",
                    (status, reason, method, ckey, company_name, version, fk),
                )
            else:
                conn.execute(
                    """UPDATE research_fields
                       SET resolution_status=?, unavailable_reason=?,
                           resolution_method=?, updated_at=CURRENT_TIMESTAMP
                       WHERE company_name=? AND version=? AND field_key=?""",
                    (status, reason, method, company_name, version, fk),
                )
            # 写 resolution_log
            conn.execute(
                """INSERT INTO field_resolution_logs
                   (company_name, version, field_key, resolution_status,
                    resolution_method, evidence_count, detail_json)
                   VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (company_name, version, fk, status, method,
                 f'{{"reason":"{reason}"}}' if reason else None),
            )
            count += 1
        conn.commit()
        conn.close()
    except Exception:
        pass
    return count
