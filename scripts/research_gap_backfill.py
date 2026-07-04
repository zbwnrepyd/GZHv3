#!/usr/bin/env python3
"""Post-research gap backfill.

Backfills only fields that can be supported by existing structured data:
- market fields from market_estimates
- LTV/CAC benchmark fields from local benchmark tables

It intentionally does not fabricate private operating metrics such as MAU,
ARR, retention, revenue, or profit.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Iterable


_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / "webapp"))
sys.path.insert(0, str(_PROJECT_ROOT))

from webapp.research.industry_benchmarks import get_benchmark, get_ltv_cac_benchmark
from webapp.services.render_assembler import RenderAssembler


PLACEHOLDERS = {"", "暂缺", "待研究数据", "None", "none", "null", "NULL", "[]", "{}"}
MIN_MARKET_CONFIDENCE = 0.30

MARKET_VALUE_FIELDS = {"market_size_value", "tam_value", "market_cagr"}
BENCHMARK_FIELDS = {
    "ltv",
    "cac",
    "ltv_cac_ratio",
    "ltv_cac_is_benchmark",
    "ltv_cac_benchmark_source",
}

PRIVATE_DO_NOT_BACKFILL = {
    "arr",
    "mrr",
    "mau",
    "mau_as_of",
    "registered_users",
    "active_users",
    "paying_users",
    "retention_rate",
    "retention_definition",
    "churn_rate",
    "gross_margin",
    "burn_rate",
    "runway_months",
    "company_revenue",
    "company_profit",
    "revenue_metrics",
    "growth_metrics",
}


def _default_research_db_path() -> str:
    return str(_PROJECT_ROOT / "db" / "research_db.sqlite")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def _is_placeholder(value) -> bool:
    if value is None:
        return True
    return str(value).strip() in PLACEHOLDERS


def _company_key_candidates(conn: sqlite3.Connection, company_name: str) -> list[str]:
    candidates = [company_name.lower()]
    for table in ("research_fields", "research_jobs", "companies", "research"):
        cols = _columns(conn, table)
        if not cols or "company_key" not in cols:
            continue
        name_col = "company_name" if "company_name" in cols else "name" if "name" in cols else ""
        if not name_col:
            continue
        try:
            rows = conn.execute(
                f"""
                SELECT company_key FROM {table}
                WHERE {name_col}=? AND company_key IS NOT NULL AND TRIM(company_key)!=''
                """,
                (company_name,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        candidates.extend(str(row["company_key"]).strip() for row in rows if row["company_key"])

    seen = set()
    result = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _visible_field_keys(company_name: str, card_set: str, field_keys: Iterable[str] | None) -> list[str]:
    if field_keys is not None:
        return list(dict.fromkeys(field_keys))
    contract = RenderAssembler().assemble(company_name, card_set)
    keys: list[str] = []
    for card in contract.get("cards", []):
        for item in card.get("items", []):
            key = item.get("field_key")
            if key:
                keys.append(key)
    return list(dict.fromkeys(keys))


def _best_market_estimates(conn: sqlite3.Connection, company_keys: list[str]) -> dict[str, sqlite3.Row]:
    if not company_keys or not _columns(conn, "market_estimates"):
        return {}
    placeholders = ",".join("?" for _ in company_keys)
    rows = conn.execute(
        f"""
        SELECT *
        FROM market_estimates
        WHERE company_key IN ({placeholders})
          AND status != 'unavailable'
          AND confidence >= ?
        ORDER BY confidence DESC, updated_at DESC
        """,
        [*company_keys, MIN_MARKET_CONFIDENCE],
    ).fetchall()
    best: dict[str, sqlite3.Row] = {}
    for row in rows:
        field_key = row["field_key"]
        if field_key in MARKET_VALUE_FIELDS and field_key not in best:
            best[field_key] = row
    return best


def _market_updates(estimates: dict[str, sqlite3.Row], wanted: set[str]) -> list[dict]:
    updates: list[dict] = []

    market_size = estimates.get("market_size_value")
    if market_size:
        updates.extend(_market_size_updates(market_size, wanted))

    tam = estimates.get("tam_value")
    if tam:
        updates.extend(_tam_updates(tam, wanted))

    cagr = estimates.get("market_cagr")
    if cagr and "market_cagr" in wanted:
        updates.append(_field_update(
            "market_cagr",
            _estimate_text(cagr),
            "proxy",
            "market_estimates",
            cagr["source_url"] or "",
            "market_estimates_backfill",
        ))

    return updates


def _market_size_updates(row: sqlite3.Row, wanted: set[str]) -> list[dict]:
    source_url = row["source_url"] or ""
    updates = []
    if "market_size_value" in wanted:
        updates.append(_field_update("market_size_value", _estimate_text(row), "proxy", "market_estimates", source_url, "market_estimates_backfill"))
    if "market_size_currency" in wanted and row["currency"]:
        updates.append(_field_update("market_size_currency", str(row["currency"]), "proxy", "market_estimates", source_url, "market_estimates_backfill"))
    if "market_size_year" in wanted and row["year"]:
        updates.append(_field_update("market_size_year", str(row["year"]), "proxy", "market_estimates", source_url, "market_estimates_backfill"))
    if "market_size_source_note" in wanted:
        note = _source_note(row)
        updates.append(_field_update("market_size_source_note", note, "proxy", "market_estimates", source_url, "market_estimates_backfill"))
    return updates


def _tam_updates(row: sqlite3.Row, wanted: set[str]) -> list[dict]:
    source_url = row["source_url"] or ""
    updates = []
    if "tam_value" in wanted:
        updates.append(_field_update("tam_value", _estimate_text(row), "proxy", "market_estimates", source_url, "market_estimates_backfill"))
    if "tam_currency" in wanted and row["currency"]:
        updates.append(_field_update("tam_currency", str(row["currency"]), "proxy", "market_estimates", source_url, "market_estimates_backfill"))
    if "tam_year" in wanted and row["year"]:
        updates.append(_field_update("tam_year", str(row["year"]), "proxy", "market_estimates", source_url, "market_estimates_backfill"))
    if "tam" in wanted:
        updates.append(_field_update("tam", _source_note(row), "proxy", "market_estimates", source_url, "market_estimates_backfill"))
    return updates


def _benchmark_updates(wanted: set[str], company_type: str) -> list[dict]:
    updates: list[dict] = []
    ltv_cac = get_ltv_cac_benchmark(company_type, "default")
    cac = get_benchmark(company_type if company_type in {"saas", "b2b", "consumer"} else "saas", "cac_range")

    source_parts = []
    if ltv_cac.get("source"):
        source_parts.append(str(ltv_cac["source"]))
    if cac.get("source"):
        source_parts.append(str(cac["source"]))
    source_note = " / ".join(dict.fromkeys(source_parts)) or "industry benchmark"
    source_note = f"{source_note}; industry benchmark, not company disclosed."

    if "ltv_cac_ratio" in wanted and ltv_cac.get("value"):
        updates.append(_field_update("ltv_cac_ratio", str(ltv_cac["value"]), "industry_avg", "industry_benchmark", "", "industry_benchmark"))
    if "ltv_cac_is_benchmark" in wanted:
        updates.append(_field_update("ltv_cac_is_benchmark", "1", "industry_avg", "industry_benchmark", "", "industry_benchmark"))
    if "ltv_cac_benchmark_source" in wanted:
        updates.append(_field_update("ltv_cac_benchmark_source", source_note, "industry_avg", "industry_benchmark", "", "industry_benchmark"))
    if "cac" in wanted and cac.get("value"):
        updates.append(_field_update("cac", str(cac["value"]), "industry_avg", "industry_benchmark", "", "industry_benchmark"))
    if "ltv" in wanted and ltv_cac.get("value"):
        updates.append(_field_update("ltv", str(ltv_cac["value"]), "industry_avg", "industry_benchmark", "", "industry_benchmark"))
    return updates


def _field_update(field_key: str, value: str, status: str, source_type: str, source_url: str, method: str) -> dict:
    return {
        "field_key": field_key,
        "field_value": value,
        "resolution_status": status,
        "source_type": source_type,
        "source_url": source_url,
        "resolution_method": method,
    }


def _estimate_text(row: sqlite3.Row) -> str:
    if row["result_text"]:
        return str(row["result_text"])
    value = row["result_value"]
    if value is None:
        return ""
    return str(value)


def _source_note(row: sqlite3.Row) -> str:
    parts = []
    if row["result_text"]:
        parts.append(str(row["result_text"]))
    if row["region"]:
        parts.append(str(row["region"]))
    if row["segment"]:
        parts.append(str(row["segment"]))
    if row["year"]:
        parts.append(f"{row['year']}")
    if row["disclaimer"]:
        parts.append(str(row["disclaimer"]))
    return " | ".join(parts) or _estimate_text(row)


def _infer_company_type(conn: sqlite3.Connection, company_name: str, company_keys: list[str]) -> str:
    cols = _columns(conn, "research_fields")
    if not cols:
        return "saas"
    clauses = ["company_name=?"]
    params: list[str] = [company_name]
    if "company_key" in cols and company_keys:
        placeholders = ",".join("?" for _ in company_keys)
        clauses.append(f"company_key IN ({placeholders})")
        params.extend(company_keys)
    try:
        row = conn.execute(
            f"""
            SELECT field_value FROM research_fields
            WHERE ({' OR '.join(clauses)})
              AND field_key IN ('company_type', 'company_category')
              AND field_value IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            params,
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    text = str(row["field_value"]).lower() if row else ""
    if "consumer" in text or "toc" in text:
        return "consumer"
    if "b2b" in text or "enterprise" in text:
        return "b2b"
    return "saas"


def _apply_research_update(
    conn: sqlite3.Connection,
    company_name: str,
    company_keys: list[str],
    update: dict,
    dry_run: bool,
) -> bool:
    cols = _columns(conn, "research_fields")
    if not cols:
        return False

    field_key = update["field_key"]
    clauses = ["company_name=?"]
    params: list[str] = [company_name]
    if "company_key" in cols and company_keys:
        placeholders = ",".join("?" for _ in company_keys)
        clauses.append(f"company_key IN ({placeholders})")
        params.extend(company_keys)

    rows = conn.execute(
        f"""
        SELECT id, field_value, resolution_status
        FROM research_fields
        WHERE ({' OR '.join(clauses)}) AND field_key=?
        """,
        [*params, field_key],
    ).fetchall()

    should_update = [
        row["id"] for row in rows
        if _is_placeholder(row["field_value"]) or str(row["resolution_status"] or "") in {"unavailable", "manual_needed", "draft"}
    ]

    if should_update:
        if not dry_run:
            set_parts = ["field_value=?"]
            values = [update["field_value"]]
            for col, key in (
                ("resolution_status", "resolution_status"),
                ("confidence", None),
                ("source_type", "source_type"),
                ("source_url", "source_url"),
                ("resolution_method", "resolution_method"),
                ("unavailable_reason", None),
            ):
                if col not in cols:
                    continue
                set_parts.append(f"{col}=?")
                if col == "confidence":
                    values.append("medium")
                elif col == "unavailable_reason":
                    values.append("")
                else:
                    values.append(update[key])
            if "updated_at" in cols:
                set_parts.append("updated_at=CURRENT_TIMESTAMP")
            placeholders = ",".join("?" for _ in should_update)
            conn.execute(
                f"UPDATE research_fields SET {', '.join(set_parts)} WHERE id IN ({placeholders})",
                [*values, *should_update],
            )
        return True

    if rows:
        return False

    if dry_run:
        return True

    insert_cols = ["company_name", "field_key", "field_value"]
    insert_vals = [company_name, field_key, update["field_value"]]
    optional = {
        "version": "standard",
        "company_key": company_keys[0] if company_keys else company_name.lower(),
        "resolution_status": update["resolution_status"],
        "confidence": "medium",
        "source_type": update["source_type"],
        "source_url": update["source_url"],
        "resolution_method": update["resolution_method"],
        "unavailable_reason": "",
    }
    for col, value in optional.items():
        if col in cols:
            insert_cols.append(col)
            insert_vals.append(value)
    placeholders = ",".join("?" for _ in insert_cols)
    conn.execute(
        f"INSERT INTO research_fields ({', '.join(insert_cols)}) VALUES ({placeholders})",
        insert_vals,
    )
    return True


def _apply_final_card_update(conn: sqlite3.Connection, company_keys: list[str], update: dict, dry_run: bool) -> bool:
    cols = _columns(conn, "final_card_values")
    if not cols or not company_keys:
        return False
    placeholders = ",".join("?" for _ in company_keys)
    rows = conn.execute(
        f"""
        SELECT id, final_value, status, resolution_status
        FROM final_card_values
        WHERE company_key IN ({placeholders}) AND field_key=?
        """,
        [*company_keys, update["field_key"]],
    ).fetchall()
    ids = [
        row["id"] for row in rows
        if _is_placeholder(row["final_value"]) or str(row["status"] or "") in {"unavailable", "manual_needed", "draft"}
    ]
    if not ids:
        return False
    if not dry_run:
        set_parts = ["final_value=?", "status=?", "resolution_status=?", "confidence=?"]
        values = [update["field_value"], update["resolution_status"], update["resolution_status"], "medium"]
        if "source_note" in cols:
            set_parts.append("source_note=?")
            values.append(update["source_url"] or update["source_type"])
        if "updated_at" in cols:
            set_parts.append("updated_at=CURRENT_TIMESTAMP")
        id_placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE final_card_values SET {', '.join(set_parts)} WHERE id IN ({id_placeholders})",
            [*values, *ids],
        )
    return True


def backfill_company(
    company: str,
    card_set: str = "v4",
    research_db_path: str | None = None,
    field_keys: Iterable[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Backfill safe gaps for one company."""
    db_path = research_db_path or _default_research_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        company_keys = _company_key_candidates(conn, company)
        wanted = set(_visible_field_keys(company, card_set, field_keys))
        wanted -= PRIVATE_DO_NOT_BACKFILL

        estimates = _best_market_estimates(conn, company_keys)
        updates = _market_updates(estimates, wanted)
        company_type = _infer_company_type(conn, company, company_keys)
        updates.extend(_benchmark_updates(wanted & BENCHMARK_FIELDS, company_type))

        applied = []
        skipped = []
        for update in updates:
            research_changed = _apply_research_update(conn, company, company_keys, update, dry_run)
            final_changed = _apply_final_card_update(conn, company_keys, update, dry_run)
            if research_changed or final_changed:
                applied.append(update)
            else:
                skipped.append(update)
        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "company": company,
        "card_set": card_set,
        "dry_run": dry_run,
        "summary": {
            "updated_fields": len({u["field_key"] for u in applied}),
            "skipped_fields": len({u["field_key"] for u in skipped}),
        },
        "updated": applied,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill safe post-research field gaps")
    parser.add_argument("--company", required=True)
    parser.add_argument("--set", default="v4", help="Card set key")
    parser.add_argument("--research-db", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    result = backfill_company(
        args.company,
        getattr(args, "set"),
        research_db_path=args.research_db,
        dry_run=args.dry_run,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
