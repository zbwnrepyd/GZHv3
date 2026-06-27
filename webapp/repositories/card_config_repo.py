"""卡片编排仓库 — card_compositions + card_items 数据访问（v2 支持套卡）"""
from __future__ import annotations
import json
import os
import sys
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Allow importing from services/ sibling
_WEBAPP = Path(__file__).resolve().parent.parent
if str(_WEBAPP) not in sys.path:
    sys.path.insert(0, str(_WEBAPP))

from services.role_defaults import default_role_for_field, default_role_for_media


@contextmanager
def _get_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ═══════════════════════════════════════════
# card_compositions
# ═══════════════════════════════════════════

def create_card(db_path: str, company_name: str, card_id: str,
                card_index: int, card_title: str, template_id: str = "",
                enabled: bool = True, card_set_key: str = "v1") -> int:
    with _get_db(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO card_compositions
               (company_name, card_set_key, card_id, card_index,
                card_title, template_id, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (company_name, card_set_key, card_id, card_index,
             card_title, template_id, 1 if enabled else 0))
        conn.commit()
        return cur.lastrowid


def get_cards(db_path: str, company_name: str,
              card_set_key: str = "v1") -> list[dict]:
    with _get_db(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM card_compositions
               WHERE company_name=? AND card_set_key=?
               ORDER BY card_index""",
            (company_name, card_set_key)).fetchall()
        return [dict(r) for r in rows]


def get_card(db_path: str, company_name: str, card_id: str,
             card_set_key: str = "v1") -> dict | None:
    with _get_db(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM card_compositions
               WHERE company_name=? AND card_set_key=? AND card_id=?""",
            (company_name, card_set_key, card_id)).fetchone()
        return dict(row) if row else None


def get_card_by_set(db_path: str, company_name: str,
                    card_set_key: str, card_id: str) -> dict | None:
    """别名，按 set_key + card_id 查找。"""
    return get_card(db_path, company_name, card_id, card_set_key=card_set_key)


def get_enabled_cards(db_path: str, company_name: str,
                      card_set_key: str = "v1") -> list[dict]:
    with _get_db(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM card_compositions
               WHERE company_name=? AND card_set_key=? AND enabled=1
               ORDER BY card_index""",
            (company_name, card_set_key)).fetchall()
        return [dict(r) for r in rows]


def update_card(db_path: str, company_name: str, card_id: str,
                card_set_key: str = "v1", **kwargs) -> bool:
    allowed = {"card_index", "card_title", "template_id", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return False
    sets = ", ".join(f"{k}=?" for k in updates)
    with _get_db(db_path) as conn:
        cur = conn.execute(
            f"""UPDATE card_compositions SET {sets},
                updated_at=CURRENT_TIMESTAMP
                WHERE company_name=? AND card_set_key=? AND card_id=?""",
            [*updates.values(), company_name, card_set_key, card_id])
        conn.commit()
        return cur.rowcount > 0


def delete_card(db_path: str, company_name: str, card_id: str,
                card_set_key: str = "v1") -> bool:
    with _get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM card_items WHERE company_name=? AND card_set_key=? AND card_id=?",
            (company_name, card_set_key, card_id))
        cur = conn.execute(
            "DELETE FROM card_compositions WHERE company_name=? AND card_set_key=? AND card_id=?",
            (company_name, card_set_key, card_id))
        conn.commit()
        return cur.rowcount > 0


def delete_company_set(db_path: str, company_name: str,
                       card_set_key: str) -> int:
    """删除某公司在某套卡的全部编排数据，返回删除的卡片数。"""
    with _get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM card_items WHERE company_name=? AND card_set_key=?",
            (company_name, card_set_key))
        cur = conn.execute(
            "DELETE FROM card_compositions WHERE company_name=? AND card_set_key=?",
            (company_name, card_set_key))
        conn.commit()
        return cur.rowcount


def reorder_cards(db_path: str, company_name: str,
                  card_ids: list[str], card_set_key: str = "v1") -> bool:
    with _get_db(db_path) as conn:
        for idx, card_id in enumerate(card_ids, 1):
            conn.execute(
                """UPDATE card_compositions SET card_index=?,
                   updated_at=CURRENT_TIMESTAMP
                   WHERE company_name=? AND card_set_key=? AND card_id=?""",
                (idx, company_name, card_set_key, card_id))
        conn.commit()
        return True


# ═══════════════════════════════════════════
# card_items
# ═══════════════════════════════════════════

def add_card_item(db_path: str, company_name: str, card_id: str,
                  item_type: str, item_key: str, item_label: str = "",
                  sort_order: int = 0, display_role: str = "body",
                  card_set_key: str = "v1") -> int:
    with _get_db(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO card_items
               (company_name, card_set_key, card_id, item_type, item_key,
                item_label, sort_order, display_role)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_name, card_set_key, card_id, item_type, item_key,
             item_label or "", sort_order, display_role))
        conn.commit()
        return cur.lastrowid


def get_card_items(db_path: str, company_name: str,
                   card_id: str, card_set_key: str = "v1") -> list[dict]:
    with _get_db(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM card_items
               WHERE company_name=? AND card_set_key=? AND card_id=? AND enabled=1
               ORDER BY sort_order""",
            (company_name, card_set_key, card_id)).fetchall()
        return [dict(r) for r in rows]


def update_card_item(db_path: str, company_name: str, card_id: str,
                     item_id: int, card_set_key: str = "v1", **kwargs) -> bool:
    allowed = {"sort_order", "display_role", "item_label", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return False
    sets = ", ".join(f"{k}=?" for k in updates)
    with _get_db(db_path) as conn:
        cur = conn.execute(
            f"""UPDATE card_items SET {sets}
                WHERE id=? AND company_name=? AND card_set_key=? AND card_id=?""",
            [*updates.values(), item_id, company_name, card_set_key, card_id])
        conn.commit()
        return cur.rowcount > 0


def remove_card_item(db_path: str, company_name: str, card_id: str,
                     item_id: int, card_set_key: str = "v1") -> bool:
    with _get_db(db_path) as conn:
        cur = conn.execute(
            """DELETE FROM card_items
               WHERE id=? AND company_name=? AND card_set_key=? AND card_id=?""",
            (item_id, company_name, card_set_key, card_id))
        conn.commit()
        return cur.rowcount > 0


def clear_card_items(db_path: str, company_name: str, card_id: str,
                     card_set_key: str = "v1") -> int:
    with _get_db(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM card_items WHERE company_name=? AND card_set_key=? AND card_id=?",
            (company_name, card_set_key, card_id))
        conn.commit()
        return cur.rowcount


def batch_set_card_items(db_path: str, company_name: str, card_id: str,
                         items: list[dict], card_set_key: str = "v1") -> int:
    """批量替换卡片的所有 items（先删后插）"""
    clear_card_items(db_path, company_name, card_id, card_set_key=card_set_key)
    count = 0
    for item in items:
        add_card_item(db_path, company_name, card_id,
                      item_type=item["item_type"],
                      item_key=item["item_key"],
                      item_label=item.get("item_label", ""),
                      sort_order=item.get("sort_order", count),
                      display_role=item.get("display_role", "body"),
                      card_set_key=card_set_key)
        count += 1
    return count


# ═══════════════════════════════════════════
# default_card_configs
# ═══════════════════════════════════════════

def get_default_card_configs(db_path: str, set_key: str = "v1") -> list[dict]:
    with _get_db(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM default_card_configs
               WHERE set_key=? ORDER BY card_index""",
            (set_key,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["config"] = json.loads(d.get("config_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["config"] = {}
            result.append(d)
        return result


def init_company_set(composition_db: str, company_name: str,
                     set_key: str, spec_version: str) -> int:
    """
    从 default_card_configs 读取指定 spec_version 的默认配置，
    批量写入 card_compositions + card_items（幂等，已有则跳过）。
    返回实际创建的卡片数。
    """
    configs = get_default_card_configs(composition_db, set_key=spec_version)
    created = 0
    for cfg in configs:
        card_id = cfg["card_id"]
        card_idx = cfg["card_index"]
        card_title = cfg["card_title"]
        template_id = cfg["config"].get("template_id", "")
        # 幂等检查
        existing = get_card_by_set(composition_db, company_name,
                                   set_key, card_id)
        if existing:
            continue
        row_id = create_card(
            composition_db, company_name, card_id, card_idx,
            card_title, template_id, enabled=True,
            card_set_key=set_key,
        )
        # 写入 card_items
        fields = cfg["config"].get("fields", [])
        media = cfg["config"].get("media", [])
        for i, fk in enumerate(fields):
            add_card_item(composition_db, company_name, card_id,
                          "field", fk, sort_order=i,
                          display_role=default_role_for_field(fk), card_set_key=set_key)
        for i, mk in enumerate(media):
            add_card_item(composition_db, company_name, card_id,
                          "media", mk, sort_order=i,
                          display_role=default_role_for_media(mk), card_set_key=set_key)
        created += 1
    return created
