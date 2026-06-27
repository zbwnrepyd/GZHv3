#!/usr/bin/env python3
"""迁移 051: 同步已有公司的 v3 卡片字段配置至最新默认值。

背景: 修复了 init_composition_db.sql 中 v3_card_02 和 v3_card_07 的字段配置错误。
- v3_card_02: 补加 market_track, market_subtrack
- v3_card_07: gtm_motion → gtm_strategy, 移除 cold_start

本脚本更新已创建 v3 卡片数据的公司，使其 card_items 与修正后的默认配置一致。
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COMPOSITION_DB = PROJECT_ROOT / "db" / "composition_db.sqlite"


def migrate():
    if not COMPOSITION_DB.exists():
        print(f"composition_db 不存在: {COMPOSITION_DB}")
        return

    conn = sqlite3.connect(str(COMPOSITION_DB))
    conn.row_factory = sqlite3.Row

    # 查找所有有 v3 card_items 的公司
    companies = [
        row["company_name"]
        for row in conn.execute(
            "SELECT DISTINCT company_name FROM card_items WHERE card_set_key='v3'"
        ).fetchall()
    ]

    if not companies:
        print("无公司需要迁移。")
        conn.close()
        return

    print(f"找到 {len(companies)} 个有 v3 数据的公司: {companies}")

    for company in companies:
        migrate_card_02(conn, company)
        migrate_card_07(conn, company)

    conn.commit()
    conn.close()
    print("迁移完成。")


def migrate_card_02(conn, company):
    """v3_card_02: 补加 market_track 和 market_subtrack。"""
    existing = {
        row["item_key"]
        for row in conn.execute(
            "SELECT item_key FROM card_items "
            "WHERE company_name=? AND card_set_key='v3' AND card_id='v3_card_02' AND item_type='field'",
            (company,),
        ).fetchall()
    }

    added = []
    for fk in ["market_track", "market_subtrack"]:
        if fk not in existing:
            # 获取当前最大 sort_order
            max_order = conn.execute(
                "SELECT MAX(sort_order) as mo FROM card_items "
                "WHERE company_name=? AND card_set_key='v3' AND card_id='v3_card_02'",
                (company,),
            ).fetchone()["mo"] or 0

            conn.execute(
                "INSERT INTO card_items (company_name, card_set_key, card_id, "
                "item_type, item_key, item_label, display_role, enabled, sort_order) "
                "VALUES (?, 'v3', 'v3_card_02', 'field', ?, ?, 'body', 1, ?)",
                (company, fk, fk, max_order + 1),
            )
            added.append(fk)

    if added:
        print(f"  [{company}] v3_card_02 新增字段: {added}")
    else:
        print(f"  [{company}] v3_card_02 已是最新，跳过")


def migrate_card_07(conn, company):
    """v3_card_07: gtm_motion → gtm_strategy, 移除 cold_start。"""
    items = conn.execute(
        "SELECT id, item_key, sort_order FROM card_items "
        "WHERE company_name=? AND card_set_key='v3' AND card_id='v3_card_07' AND item_type='field'",
        (company,),
    ).fetchall()

    item_keys = {row["item_key"]: row for row in items}

    changes = []

    # 替换 gtm_motion → gtm_strategy
    if "gtm_motion" in item_keys and "gtm_strategy" not in item_keys:
        row = item_keys["gtm_motion"]
        conn.execute(
            "UPDATE card_items SET item_key='gtm_strategy', item_label='gtm_strategy' WHERE id=?",
            (row["id"],),
        )
        changes.append("gtm_motion→gtm_strategy")

    # 移除 cold_start
    if "cold_start" in item_keys:
        conn.execute(
            "DELETE FROM card_items WHERE company_name=? AND card_set_key='v3' AND card_id='v3_card_07' AND item_key='cold_start'",
            (company,),
        )
        changes.append("移除 cold_start")

    if changes:
        print(f"  [{company}] v3_card_07 修改: {changes}")
    else:
        print(f"  [{company}] v3_card_07 已是最新，跳过")


if __name__ == "__main__":
    migrate()
