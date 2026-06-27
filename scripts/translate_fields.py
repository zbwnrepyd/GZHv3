"""英文字段翻译脚本 — 将 research_fields 中的英文内容批量翻译为中文

用法:
  .venv/bin/python3 scripts/translate_fields.py --company Sardine
  .venv/bin/python3 scripts/translate_fields.py --all --dry-run
  .venv/bin/python3 scripts/translate_fields.py --all
"""

import sqlite3
import sys
import os
import argparse
import re
import time

# 添加 webapp 到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'db', 'research_db.sqlite')

# 不需要翻译的字段 — 这些应该是中文或结构化数据
_SKIP_FIELDS = {
    # 结构化/枚举字段 — 不翻译
    "ai_model_dependency", "workflow_integration_level", "data_flywheel",
    "proprietary_data_asset", "incumbent_direct_competitor",
    "customer_segment_type", "funding_stage", "pricing_model",
    "inference_cost_exposure", "stack_layer",
    "incumbent_overlap", "workflow_lock_in", "data_lock_in",
    "technical_uniqueness", "distribution_lock", "brand_or_community",
    "market_size", "strategic_dependency", "user_visibility",
    "pricing_power", "gross_margin", "customer_budget_level",
    "gtm_motion",
    # URL / 纯数字 / 代码
    "website_url", "mrr", "arr", "mau", "mau_as_of",
    "funding_stage_score", "score_defensibility",
    "score_incumbent_attention", "score_value_capture",
    # 已经是中文的短字段
    "company_name", "display_name",
}


def is_english_text(text: str) -> bool:
    """判断文本是否主要是英文（需要翻译）。"""
    if not text or not text.strip():
        return False
    text = text.strip()
    if len(text) < 20:
        return False

    # 统计中文字符 vs 英文字母
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    ascii_letters = len(re.findall(r'[a-zA-Z]', text))

    # 如果中文字符足够多（>20% 或 >30个），视为已翻译
    total_chars = len(text)
    if chinese_chars > 30 or (total_chars > 0 and chinese_chars / total_chars > 0.2):
        return False

    # 英文信号：常见英文功能词 + 足够的ASCII字母
    english_signals = re.findall(
        r'\b(the|and|for|with|from|that|this|have|has|are|was|not|but|can|all|will|been|its|also|each|more|over|into|than|just|like|now|new|only|other|some|such|through|during|between|under|about|their|would|could|should|which|these|those)\b',
        text.lower()
    )
    return len(english_signals) >= 2 or (
        ascii_letters > 100 and chinese_chars < 10
    )


def translate_batch(texts: list[str]) -> list[str]:
    """批量翻译英文文本为中文。"""
    from deepseek_client import translate_to_chinese
    return translate_to_chinese(texts, batch_size=10)


def translate_text(text: str, field_key: str) -> str | None:
    """翻译单段文本。"""
    try:
        from deepseek_client import translate_to_chinese
        results = translate_to_chinese([text], batch_size=1)
        result = results[0] if results else None
        return result.strip() if result and result != text else None
    except Exception as e:
        print(f"  [translate] error: {e}")
        return None


def get_fields_to_translate(db_path: str, company: str | None = None) -> list[dict]:
    """查询需要翻译的字段。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if company:
        rows = conn.execute(
            "SELECT id, company_name, field_key, field_value, resolution_status "
            "FROM research_fields WHERE company_name=? AND field_value IS NOT NULL "
            "AND field_value != '' AND field_value != '暂缺' "
            "AND field_key NOT IN ({}) "
            "ORDER BY field_key".format(','.join('?' * len(_SKIP_FIELDS))),
            [company] + list(_SKIP_FIELDS),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, company_name, field_key, field_value, resolution_status "
            "FROM research_fields WHERE field_value IS NOT NULL "
            "AND field_value != '' AND field_value != '暂缺' "
            "AND field_key NOT IN ({}) "
            "ORDER BY company_name, field_key".format(','.join('?' * len(_SKIP_FIELDS))),
            list(_SKIP_FIELDS),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def main():
    parser = argparse.ArgumentParser(description="Translate English field values to Chinese")
    parser.add_argument("--company", help="Target a specific company")
    parser.add_argument("--all", action="store_true", help="Process all companies")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be translated without doing it")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of fields to translate")
    args = parser.parse_args()

    if not args.company and not args.all:
        parser.print_help()
        print("\nExample: .venv/bin/python3 scripts/translate_fields.py --company Sardine")
        sys.exit(1)

    db_path = os.path.abspath(DB_PATH)
    print(f"DB: {db_path}")

    fields = get_fields_to_translate(db_path, args.company)
    print(f"Total candidate fields: {len(fields)}")

    # 筛选英文内容，按 (company_name, field_key) 去重
    seen_pairs = set()
    to_translate = []
    for f in fields:
        pair = (f["company_name"], f["field_key"])
        if pair in seen_pairs:
            continue
        if is_english_text(f["field_value"]):
            seen_pairs.add(pair)
            to_translate.append(f)

    print(f"Unique fields with English content: {len(to_translate)}")

    if args.limit and args.limit > 0:
        to_translate = to_translate[:args.limit]
        print(f"Limited to: {len(to_translate)}")

    if args.dry_run:
        print("\n=== DRY RUN (no changes) ===")
        for f in to_translate[:20]:
            preview = f["field_value"][:100].replace("\n", " ")
            print(f"  [{f['company_name']}] {f['field_key']}: {preview}...")
        if len(to_translate) > 20:
            print(f"  ... and {len(to_translate) - 20} more")
        return

    if not to_translate:
        print("Nothing to translate.")
        return

    # 批量翻译: 每批10个，同一字段的所有版本一起更新
    conn = sqlite3.connect(db_path)
    translated = 0
    failed = 0
    batch_size = 10

    for batch_start in range(0, len(to_translate), batch_size):
        batch = to_translate[batch_start:batch_start + batch_size]
        texts = [f["field_value"] for f in batch]
        results = translate_batch(texts)

        for f, chinese in zip(batch, results):
            company = f["company_name"]
            field_key = f["field_key"]
            original = f["field_value"]

            print(f"[{translated+failed+1}/{len(to_translate)}] {company}/{field_key} "
                  f"({len(original)}→{len(chinese)} chars)...", end=" ", flush=True)

            if chinese and len(chinese) > 10 and is_english_text(chinese) == False:
                # 更新所有 version 的同一个 (company_name, field_key)
                conn.execute(
                    "UPDATE research_fields SET field_value=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE company_name=? AND field_key=?",
                    (chinese, company, field_key),
                )
                conn.commit()
                translated += 1
                print(f"✓")
            else:
                failed += 1
                print(f"✗ (skipped)")

        time.sleep(0.5)  # Rate limit between batches

    conn.close()
    print(f"\nDone. Translated: {translated}, Failed/Skipped: {failed}")


if __name__ == "__main__":
    main()
