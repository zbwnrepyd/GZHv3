"""公司图片资产读写层 — company_assets 表 CRUD"""
from __future__ import annotations
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


ASSET_KEYS = [
    "logo", "website_screenshot", "founder_photo",
    "product_main",
    "competitors", "competitors_logo_strip", "flywheel",
    "chart_competitive", "chart_ecosystem",
    # 以下为废弃槽位，保留 DB 行但不再渲染
    "office", "products_other", "timeline",
]

# v1 卡片→主资产映射（套卡1 · 经典8张）
CARD_ASSET_MAP = {
    1: "logo",
    2: "office",
    3: "timeline",
    4: "product_main",
    5: "products_other",
    6: "flywheel",
    7: "competitors",
}

# v2 卡片→主资产映射（套卡2 · 新版7张）
CARD_ASSET_MAP_V2 = {
    1: "logo",
    2: "website_screenshot",
    3: "product_main",       # chart_ecosystem 由 card_3 确认事件单独触发
    4: "founder_photo",
    5: None,                 # page5 无单一主资产
    6: "flywheel",
    7: "competitors",
}

# 每个 asset_key 对应的卡片索引（v1）。
ASSET_TO_CARD = {v: k for k, v in CARD_ASSET_MAP.items() if v}
ASSET_TO_CARD["website_screenshot"] = 2
ASSET_TO_CARD["competitors_logo_strip"] = 7
ASSET_TO_CARD["chart_competitive"] = 7
ASSET_TO_CARD["chart_ecosystem"] = 7

# v2 映射
ASSET_TO_CARD_V2 = {v: k for k, v in CARD_ASSET_MAP_V2.items() if v}
ASSET_TO_CARD_V2["competitors_logo_strip"] = 7
ASSET_TO_CARD_V2["chart_competitive"] = 7
ASSET_TO_CARD_V2["chart_ecosystem"] = 3   # v2 改为 card_3

_COMPETITORS_DISALLOWED_PATH_MARKERS = (
    "/chart_competitive",
    "/chart_ecosystem",
    "/positioning_charts",
    "chart_competitive__",
    "chart_ecosystem__",
    "positioning_charts__",
)


def _is_asset_path_mismatch(asset_key: str, local_path: str | None,
                            source_type: str | None = None) -> bool:
    """Return True when a stored image clearly belongs to another slot."""
    if asset_key != "competitors":
        return False
    path = (local_path or "").lower()
    src = (source_type or "").lower()
    if "derived_from_chart" in src:
        return True
    return any(marker in path for marker in _COMPETITORS_DISALLOWED_PATH_MARKERS)


def _company_where(company_name: str, company_key: str = "") -> tuple[str, list]:
    """构建 company WHERE 子句 — 优先 company_key，回退 case-insensitive company_name。"""
    if company_key:
        return ("(LOWER(company_key)=LOWER(?) OR (company_key IS NULL AND LOWER(company_name)=LOWER(?)))",
                [company_key, company_name])
    return ("LOWER(company_name)=LOWER(?)", [company_name])


def _company_write_cols(company_name: str, company_key: str = "") -> tuple[list[str], list]:
    """返回写入用的列名和值列表，有 company_key 时附带写入。"""
    cols = ["company_name"]
    vals = [company_name]
    if company_key:
        cols.append("company_key")
        vals.append(company_key)
    return cols, vals


def init_assets_db(db_path: str):
    """建表（幂等）"""
    sql_file = Path(__file__).resolve().parent.parent / "db" / "init_assets_db.sql"
    with _get_db(db_path) as conn:
        conn.executescript(sql_file.read_text())
        _ensure_assets_schema(conn)
        conn.commit()


def _ensure_assets_schema(conn: sqlite3.Connection):
    """Migrate existing local DB files to the current image asset schema."""
    _add_missing_columns(conn, "company_assets", {
        "company_key": "TEXT",
        "selected_variant_id": "INTEGER",
        "final_score": "REAL DEFAULT 0",
        "auto_selected": "INTEGER DEFAULT 0",
        "fail_reason": "TEXT",
    })
    _add_missing_columns(conn, "image_variants", {
        "company_key": "TEXT",
        "width": "INTEGER",
        "height": "INTEGER",
        "file_size": "INTEGER",
        "aspect_ratio": "REAL",
        "quality_score": "REAL DEFAULT 0",
        "relevance_score": "REAL DEFAULT 0",
        "source_score": "REAL DEFAULT 0",
        "final_score": "REAL DEFAULT 0",
        "reject_reason": "TEXT",
        "meta_json": "TEXT",
    })


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


@contextmanager
def _get_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _migrate_positioning_charts(conn: sqlite3.Connection, company_name: str,
                                  company_key: str = ""):
    """将旧的 positioning_charts 行迁移为 chart_competitive。
    旧 positioning_charts 同时包含竞争格局+生态位图，现拆分为两个独立 slot。
    竞争格局图继承旧数据（变体库也一并迁移），生态位图从空开始。"""
    where, params = _company_where(company_name, company_key)
    old = conn.execute(
        f"SELECT id FROM company_assets WHERE {where} AND asset_key='positioning_charts'",
        params,
    ).fetchone()
    if not old:
        return

    # 如果 chart_competitive 已有数据则不覆盖
    existing = conn.execute(
        f"SELECT id FROM company_assets WHERE {where} AND asset_key='chart_competitive'",
        params,
    ).fetchone()
    if existing:
        # 两边都有了，删掉旧行即可
        conn.execute(f"DELETE FROM company_assets WHERE {where} AND asset_key='positioning_charts'",
                     params)
        return

    # 将 positioning_charts 行重命名为 chart_competitive
    conn.execute(
        f"""UPDATE company_assets SET asset_key='chart_competitive', card_index=7
           WHERE {where} AND asset_key='positioning_charts'""",
        params,
    )
    # 同步迁移 image_variants 表
    conn.execute(
        f"""UPDATE image_variants SET asset_key='chart_competitive'
           WHERE {where} AND asset_key='positioning_charts'""",
        params,
    )


def ensure_assets_rows(db_path: str, company_name: str, company_key: str = ""):
    """确保某公司有全部需求资产行（幂等）"""
    with _get_db(db_path) as conn:
        _migrate_positioning_charts(conn, company_name, company_key)
        for key in ASSET_KEYS:
            card_index = ASSET_TO_CARD.get(key, 0)
            cols, vals = _company_write_cols(company_name, company_key)
            conn.execute(
                f"""INSERT OR IGNORE INTO company_assets ({','.join(cols)}, asset_key, card_index)
                   VALUES ({','.join(['?'] * len(vals))}, ?, ?)""",
                [*vals, key, card_index],
            )
        conn.commit()


def upsert_asset(db_path: str, company_name: str, asset_key: str,
                 local_path: str = None, source_type: str = None,
                 source_url: str = None, prompt: str = None,
                 status: str = None, meta: dict = None,
                 selected_variant_id: int = None,
                 final_score: float = None,
                 auto_selected: bool | int = None,
                 fail_reason: str = None,
                 company_key: str = ""):
    """写入或更新单条资产"""
    normalized_local_path = normalize_browser_image_path(local_path)
    if _is_asset_path_mismatch(asset_key, normalized_local_path, source_type):
        local_path = ""
        normalized_local_path = ""
        status = "failed"
        fail_reason = fail_reason or "asset_key/local_path mismatch"
        selected_variant_id = None
        final_score = 0 if final_score is None else final_score

    with _get_db(db_path) as conn:
        where, where_params = _company_where(company_name, company_key)
        row = conn.execute(
            f"SELECT * FROM company_assets WHERE {where} AND asset_key=?",
            [*where_params, asset_key],
        ).fetchone()
        if not row and company_key:
            row = conn.execute(
                "SELECT * FROM company_assets WHERE LOWER(company_name)=LOWER(?) AND asset_key=?",
                [company_name, asset_key],
            ).fetchone()

        if not row:
            card_index = ASSET_TO_CARD.get(asset_key, 0)
            cols, vals = _company_write_cols(company_name, company_key)
            cols += ["asset_key", "card_index", "local_path", "source_type",
                     "source_url", "prompt", "status", "selected_variant_id",
                     "final_score", "auto_selected", "fail_reason", "meta_json"]
            vals += [asset_key, card_index,
                     normalized_local_path, source_type, source_url, prompt,
                     status or "missing", selected_variant_id, final_score or 0,
                     int(bool(auto_selected)) if auto_selected is not None else 0,
                     fail_reason, json.dumps(meta, ensure_ascii=False) if meta else None]
            conn.execute(
                f"INSERT INTO company_assets ({','.join(cols)}) VALUES ({','.join(['?'] * len(vals))})",
                vals,
            )
        else:
            updates = {}
            if local_path is not None:
                updates["local_path"] = normalized_local_path
            if source_type is not None:
                updates["source_type"] = source_type
            if source_url is not None:
                updates["source_url"] = source_url
            if prompt is not None:
                updates["prompt"] = prompt
            if status is not None:
                updates["status"] = status
            if selected_variant_id is not None:
                updates["selected_variant_id"] = selected_variant_id
            if final_score is not None:
                updates["final_score"] = final_score
            if auto_selected is not None:
                updates["auto_selected"] = int(bool(auto_selected))
            if fail_reason is not None:
                updates["fail_reason"] = fail_reason
            if meta is not None:
                updates["meta_json"] = json.dumps(meta, ensure_ascii=False)
            # 以 company_name+asset_key 命中的旧行可能带旧 company_key，更新为当前规范 key。
            if company_key and (row["company_key"] or "") != company_key:
                updates["company_key"] = company_key
            if updates:
                sets = [f"{k}=?" for k in updates if k != "updated_at"]
                values = [updates[k] for k in updates if k != "updated_at"] + [row["id"]]
                conn.execute(
                    f"UPDATE company_assets SET {', '.join(sets)}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    values,
                )
        conn.commit()


def get_asset(db_path: str, company_name: str, asset_key: str,
              company_key: str = "") -> dict | None:
    with _get_db(db_path) as conn:
        where, params = _company_where(company_name, company_key)
        row = conn.execute(
            f"SELECT * FROM company_assets WHERE {where} AND asset_key=?",
            [*params, asset_key],
        ).fetchone()
        return _row_to_dict(row)


def get_assets(db_path: str, company_name: str, company_key: str = "") -> dict[str, dict]:
    """返回某公司全部资产，keyed by asset_key"""
    with _get_db(db_path) as conn:
        where, params = _company_where(company_name, company_key)
        rows = conn.execute(
            f"SELECT * FROM company_assets WHERE {where} ORDER BY card_index",
            params,
        ).fetchall()
    result = {}
    for row in rows:
        d = _row_to_dict(row)
        result[d["asset_key"]] = d
    return result


def get_all_assets_grouped(db_path: str) -> dict[str, dict[str, dict]]:
    """返回全部公司的资产，{company_name: {asset_key: {...}}}"""
    with _get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM company_assets ORDER BY company_name, card_index"
        ).fetchall()
    result = {}
    for row in rows:
        d = _row_to_dict(row)
        result.setdefault(d["company_name"], {})[d["asset_key"]] = d
    return result


# ═══════════════════════════════════════════════════════════════
# image_variants 变体库 CRUD
# ═══════════════════════════════════════════════════════════════

def list_variants(db_path: str, company_name: str, asset_key: str,
                  company_key: str = "") -> list[dict]:
    """返回某公司某 asset_key 的全部变体，选中优先，然后按 final_score 倒序"""
    with _get_db(db_path) as conn:
        where, params = _company_where(company_name, company_key)
        rows = conn.execute(
            f"""SELECT * FROM image_variants
               WHERE {where} AND asset_key=?
               ORDER BY is_selected DESC, final_score DESC, created_at DESC""",
            [*params, asset_key],
        ).fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        if not d:
            continue
        if _is_asset_path_mismatch(asset_key, d.get("local_path"), d.get("source_type")):
            continue
        result.append(d)
    return result


def insert_variant(db_path: str, company_name: str, asset_key: str,
                   local_path: str, source_type: str,
                   source_url: str = "", source_page: str = "",
                   author: str = "", license: str = "",
                   attribution_req: int = 0, prompt: str = "",
                   width: int = None, height: int = None,
                   file_size: int = None, aspect_ratio: float = None,
                   quality_score: float = 0, relevance_score: float = 0,
                   source_score: float = 0, final_score: float = 0,
                   reject_reason: str = "", meta: dict = None,
                   company_key: str = "") -> int:
    """插入一条变体记录，返回 id"""
    normalized_local_path = normalize_browser_image_path(local_path)
    if _is_asset_path_mismatch(asset_key, normalized_local_path, source_type):
        raise ValueError(f"asset_key/local_path mismatch: {asset_key} -> {normalized_local_path}")
    with _get_db(db_path) as conn:
        cols, vals = _company_write_cols(company_name, company_key)
        cols += ["asset_key", "local_path", "source_type", "source_url",
                 "source_page", "author", "license", "attribution_req",
                 "prompt", "width", "height", "file_size", "aspect_ratio",
                 "quality_score", "relevance_score", "source_score",
                 "final_score", "reject_reason", "meta_json"]
        vals += [asset_key, normalized_local_path, source_type,
                 source_url, source_page, author, license, attribution_req,
                 prompt, width, height, file_size, aspect_ratio,
                 quality_score, relevance_score, source_score, final_score,
                 reject_reason, json.dumps(meta, ensure_ascii=False) if meta else None]
        cur = conn.execute(
            f"INSERT INTO image_variants ({','.join(cols)}) VALUES ({','.join(['?'] * len(vals))})",
            vals,
        )
        conn.commit()
        return cur.lastrowid


def select_variant(db_path: str, company_name: str, asset_key: str,
                   variant_id: int, auto_selected: bool = False,
                   company_key: str = "") -> bool:
    """将指定变体设为选中，其他取消选中；同时写回 company_assets"""
    with _get_db(db_path) as conn:
        where, params = _company_where(company_name, company_key)
        row = conn.execute(
            f"""SELECT local_path, source_type, source_url, prompt, final_score
               FROM image_variants
               WHERE id=? AND {where} AND asset_key=?""",
            [variant_id, *params, asset_key],
        ).fetchone()
        if not row:
            return False
        if _is_asset_path_mismatch(asset_key, row["local_path"], row["source_type"]):
            return False

        # 取消该 asset_key 下所有变体的选中
        conn.execute(
            f"""UPDATE image_variants SET is_selected=0
               WHERE {where} AND asset_key=?""",
            [*params, asset_key],
        )
        # 选中目标变体
        conn.execute(
            f"""UPDATE image_variants SET is_selected=1
               WHERE id=? AND {where} AND asset_key=?""",
            [variant_id, *params, asset_key],
        )

        conn.commit()

    # 写回 company_assets
    upsert_asset(db_path, company_name, asset_key,
                 local_path=normalize_browser_image_path(row["local_path"]),
                 source_type=row["source_type"],
                 source_url=row["source_url"],
                 prompt=row["prompt"],
                 status="ready",
                 selected_variant_id=variant_id,
                 final_score=row["final_score"] or 0,
                 auto_selected=auto_selected,
                 fail_reason="",
                 company_key=company_key)
    return True


def update_variant_scores(db_path: str, variant_id: int, *,
                          width: int = None, height: int = None,
                          file_size: int = None, aspect_ratio: float = None,
                          quality_score: float = None,
                          relevance_score: float = None,
                          source_score: float = None,
                          final_score: float = None,
                          reject_reason: str = None,
                          meta: dict = None) -> bool:
    updates = {}
    for key, value in {
        "width": width,
        "height": height,
        "file_size": file_size,
        "aspect_ratio": aspect_ratio,
        "quality_score": quality_score,
        "relevance_score": relevance_score,
        "source_score": source_score,
        "final_score": final_score,
        "reject_reason": reject_reason,
    }.items():
        if value is not None:
            updates[key] = value
    if meta is not None:
        updates["meta_json"] = json.dumps(meta, ensure_ascii=False)
    if not updates:
        return False
    sets = ", ".join(f"{k}=?" for k in updates)
    with _get_db(db_path) as conn:
        cur = conn.execute(
            f"UPDATE image_variants SET {sets} WHERE id=?",
            [*updates.values(), variant_id],
        )
        conn.commit()
        return cur.rowcount > 0


def delete_variant(db_path: str, company_name: str, asset_key: str,
                   variant_id: int, company_key: str = "") -> bool:
    """删除变体记录（不删本地文件）"""
    with _get_db(db_path) as conn:
        where, params = _company_where(company_name, company_key)
        cur = conn.execute(
            f"""DELETE FROM image_variants
               WHERE id=? AND {where} AND asset_key=?""",
            [variant_id, *params, asset_key],
        )
        conn.commit()
        return cur.rowcount > 0


def _row_to_dict(row) -> dict | None:
    if not row:
        return None
    d = dict(row)
    d["local_path"] = normalize_browser_image_path(d.get("local_path"))
    if _is_asset_path_mismatch(
        str(d.get("asset_key") or ""),
        d.get("local_path"),
        d.get("source_type"),
    ):
        d["local_path"] = ""
        d["status"] = "failed" if d.get("status") == "ready" else d.get("status", "missing")
        d["selected_variant_id"] = None
        d["fail_reason"] = d.get("fail_reason") or "asset_key/local_path mismatch"
    if d.get("meta_json"):
        try:
            d["meta"] = json.loads(d["meta_json"])
        except (json.JSONDecodeError, TypeError):
            d["meta"] = {}
    else:
        d["meta"] = {}
    return d


def normalize_browser_image_path(path: str | None) -> str | None:
    """Normalize image paths stored before browser-safe URLs were introduced."""
    if not path:
        return path
    if path.startswith(("/images/", "http://", "https://", "data:")):
        return path
    marker = "/images/"
    idx = path.find(marker)
    if idx >= 0:
        return path[idx:]
    return path
