from __future__ import annotations
import json
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager

from competitive_scoring import compute_scores, normalize_fields
from path_safety import safe_path_segment

# Track whether research schema has been ensured (one-time migration, not per-query)
_schema_ensured: set[str] = set()


def ensure_research_schema_once(db_path: str):
    """幂等确保 research DB schema 包含评分字段（仅首次调用时执行 ALTER TABLE）。"""
    if db_path in _schema_ensured:
        return
    with get_db(db_path) as conn:
        _ensure_research_schema(conn)
        conn.commit()
    _schema_ensured.add(db_path)


@contextmanager
def get_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ── research_db 查询 ──────────────────────────────────────────


def get_companies(db_path: str, final_db_path: str = "",
                  composition_db_path: str = "") -> list[dict]:
    """列出所有已研究公司，附带定稿进度。total 从卡片设置的启用卡片数读取。

    同时从 research 宽表（旧路径）和 research_fields 表（新路径）发现公司。
    """
    with get_db(db_path) as conn:
        _ensure_research_schema(conn)
        # 兼容旧 schema（无 company_key 列）
        has_ckey = any(
            row["name"] == "company_key"
            for row in conn.execute("PRAGMA table_info(research)").fetchall()
        )
        if has_ckey:
            rows = conn.execute(
                "SELECT COALESCE(NULLIF(company_key,''), LOWER(company_name)) as company_key, "
                "MAX(created_at) as created_at "
                "FROM research "
                "GROUP BY COALESCE(NULLIF(company_key,''), LOWER(company_name)) "
                "ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT LOWER(company_name) as company_key, "
                "MAX(created_at) as created_at "
                "FROM research "
                "GROUP BY LOWER(company_name) "
                "ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
        seen_keys: set[str] = set()
        seen_names: set[str] = set()  # 也按 display_name 去重（避免 ckey 不同但同公司）
        companies = []
        for row in rows:
            ckey = row["company_key"]
            seen_keys.add(ckey.lower())
            if has_ckey:
                latest = conn.execute(
                    "SELECT * FROM research "
                    "WHERE COALESCE(NULLIF(company_key,''), LOWER(company_name))=? "
                    "ORDER BY created_at DESC, "
                    "CASE version WHEN 'standard' THEN 0 ELSE 1 END LIMIT 1",
                    (ckey,),
                ).fetchone()
            else:
                latest = conn.execute(
                    "SELECT * FROM research "
                    "WHERE LOWER(company_name)=? "
                    "ORDER BY created_at DESC, "
                    "CASE version WHEN 'standard' THEN 0 ELSE 1 END LIMIT 1",
                    (ckey,),
                ).fetchone()
            display_name = latest["company_name"] if latest else ckey
            seen_names.add(display_name.lower())
            latest_cname = latest["company_name"] if latest else ckey
            filled = 0
            if latest:
                latest_keys = set(latest.keys())
                for field in REQUIRED_RESEARCH_FIELDS:
                    if field not in latest_keys:
                        continue
                    value = latest[field]
                    if value is not None and str(value).strip() not in ("", "暂缺"):
                        filled += 1
            completeness = round(filled / len(REQUIRED_RESEARCH_FIELDS) * 100) if latest else 0
            field_table_completeness = _research_fields_completeness(conn, latest_cname, ckey)
            if field_table_completeness is not None:
                completeness = field_table_completeness
            confirmed = 0
            # total 优先从卡片设置(composition_db)取启用卡片数，否则默认8
            total = _count_enabled_cards(composition_db_path, latest_cname, ckey)
            if final_db_path:
                confirmed, _ = _count_final_fields_progress(final_db_path, latest_cname, ckey)
            confirmed = min(confirmed or 0, total)
            website_url = (latest["website_url"] if latest and "website_url" in latest_keys else "")
            if not website_url or str(website_url).strip() in ("", "暂缺"):
                website_url = _latest_job_company_url(conn, latest_cname)
            scoring = _company_scoring_payload(latest)
            companies.append(
                {
                    "company_name": display_name,
                    "company_key": ckey,
                    "display_name": display_name,
                    "category": latest["company_type"] if latest else "",
                    "company_url": website_url,
                    "website_url": website_url,
                    "created_at": row["created_at"],
                    "researched_at": row["created_at"],
                    "completeness": completeness,
                    "confirmed": confirmed,
                    "total": total,
                    **scoring,
                }
            )

        # ── 从 research_fields 补发现：pipeline 不再写 research 宽表 ──
        rf_companies = _discover_companies_from_research_fields(conn, seen_keys, seen_names)
        for rf in rf_companies:
            ckey = rf["company_key"]
            display_name = rf["display_name"]
            completeness = _research_fields_completeness(conn, display_name, ckey) or 0
            total = _count_enabled_cards(composition_db_path, display_name, ckey)
            confirmed = 0
            if final_db_path:
                confirmed, _ = _count_final_fields_progress(final_db_path, display_name, ckey)
            confirmed = min(confirmed or 0, total)
            website_url = rf.get("website_url") or _latest_job_company_url(conn, display_name)
            # 从 research_fields 读取 company_type
            company_type = _lookup_field_value(conn, display_name, ckey, "company_type")
            scoring = _scoring_from_research_fields(conn, display_name, ckey)
            companies.append({
                "company_name": display_name,
                "company_key": ckey,
                "display_name": display_name,
                "category": company_type or "",
                "company_url": website_url or "",
                "website_url": website_url or "",
                "created_at": rf.get("created_at", ""),
                "researched_at": rf.get("created_at", ""),
                "completeness": completeness,
                "confirmed": confirmed,
                "total": total,
                **scoring,
            })

        # ── 从 research_jobs 补发现：某些 pipeline 路径不写 research_fields ──
        rj_companies = _discover_companies_from_research_jobs(conn, seen_keys, seen_names)
        for rj in rj_companies:
            ckey = rj["company_key"]
            display_name = rj["display_name"]
            completeness = _research_fields_completeness(conn, display_name, ckey)
            if completeness is None:
                completeness = _card_values_completeness(conn, ckey) or 0
            total = _count_enabled_cards(composition_db_path, display_name, ckey)
            confirmed = 0
            if final_db_path:
                confirmed, _ = _count_final_fields_progress(final_db_path, display_name, ckey)
            confirmed = min(confirmed or 0, total)
            website_url = rj.get("website_url") or ""
            # 从 research_fields 读取 company_type，fallback 到 final_card_values
            company_type = _lookup_field_value(conn, display_name, ckey, "company_type")
            scoring = _scoring_from_research_fields(conn, display_name, ckey)
            companies.append({
                "company_name": display_name,
                "company_key": ckey,
                "display_name": display_name,
                "category": company_type or "",
                "company_url": website_url,
                "website_url": website_url,
                "created_at": rj.get("created_at", ""),
                "researched_at": rj.get("created_at", ""),
                "completeness": completeness,
                "confirmed": confirmed,
                "total": total,
                **scoring,
            })

        # 按 created_at 降序重排
        companies.sort(key=lambda c: c.get("created_at") or "", reverse=True)
        return companies[:200]


def _research_fields_completeness(conn: sqlite3.Connection, company_name: str,
                                  company_key: str = "") -> int | None:
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "research_fields" not in tables:
        return None
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(research_fields)").fetchall()
    }
    required_columns = {"company_name", "version", "field_key", "field_value"}
    if not required_columns.issubset(columns):
        return None

    required = list(dict.fromkeys(REQUIRED_RESEARCH_FIELDS))
    placeholders = ",".join(["?"] * len(required))
    clauses = ["LOWER(company_name)=LOWER(?)"]
    params: list[object] = [company_name]
    if company_key and "company_key" in columns:
        clauses.append("company_key=?")
        params.append(company_key)

    rows = conn.execute(
        f"""
        SELECT version, COUNT(DISTINCT field_key) AS filled
        FROM research_fields
        WHERE ({' OR '.join(clauses)})
          AND field_key IN ({placeholders})
          AND field_value IS NOT NULL
          AND TRIM(CAST(field_value AS TEXT)) NOT IN ('', '暂缺')
        GROUP BY version
        """,
        [*params, *required],
    ).fetchall()
    if not rows:
        return None
    filled = max(int(row["filled"] or 0) for row in rows)
    return round(filled / len(required) * 100)


def _discover_companies_from_research_fields(
    conn: sqlite3.Connection, seen_keys: set[str], seen_names: set[str],
) -> list[dict]:
    """从 research_fields 表发现 research 宽表中不存在的公司。

    返回 list[dict]，每项含 company_key, display_name, created_at, website_url。
    """
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "research_fields" not in tables:
        return []
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(research_fields)").fetchall()
    }
    # 需要 company_key 列来做去重
    has_ckey = "company_key" in columns
    has_created_at = "created_at" in columns

    companies: list[dict] = []
    rows = conn.execute(
        "SELECT DISTINCT company_name, "
        + ("COALESCE(NULLIF(company_key,''), LOWER(company_name)) as company_key, " if has_ckey else "LOWER(company_name) as company_key, ")
        + ("MAX(created_at) as created_at " if has_created_at else "'' as created_at ")
        + "FROM research_fields "
        + "GROUP BY " + ("COALESCE(NULLIF(company_key,''), LOWER(company_name))" if has_ckey else "LOWER(company_name)")
    ).fetchall()

    for row in rows:
        ckey = (row["company_key"] or "").lower()
        display_name = row["company_name"] or ckey
        if ckey in seen_keys or display_name.lower() in seen_names:
            continue
        seen_keys.add(ckey)
        seen_names.add(display_name.lower())
        website_url = _lookup_field_value(conn, display_name, ckey, "website_url") or ""
        companies.append({
            "company_key": ckey,
            "display_name": display_name,
            "created_at": row["created_at"] or "",
            "website_url": website_url,
        })
    return companies


def _discover_companies_from_research_jobs(
    conn: sqlite3.Connection, seen_keys: set[str], seen_names: set[str],
) -> list[dict]:
    """从 research_jobs 表发现 research_fields 中不存在的公司（已完成的研究）。"""
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "research_jobs" not in tables:
        return []

    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(research_jobs)").fetchall()
    }
    has_ckey = "company_key" in columns
    has_display_name = "display_name" in columns

    # 取每个公司最新一次完成的研究
    if has_ckey:
        group_by = "COALESCE(NULLIF(company_key,''), LOWER(company_name))"
    else:
        group_by = "LOWER(company_name)"

    rows = conn.execute(
        f"SELECT company_name, company_url, "
        + ("COALESCE(NULLIF(company_key,''), LOWER(company_name)) as company_key, " if has_ckey else "LOWER(company_name) as company_key, ")
        + ("MAX(display_name) as display_name, " if has_display_name else "company_name as display_name, ")
        + "MAX(created_at) as created_at "
        + "FROM research_jobs "
        + "WHERE status='done' "
        + f"GROUP BY {group_by} "
        + "ORDER BY created_at DESC"
    ).fetchall()

    companies: list[dict] = []
    for row in rows:
        ckey = (row["company_key"] or "").lower()
        display_name = (row["display_name"] if has_display_name and row["display_name"] else row["company_name"])
        if ckey in seen_keys or display_name.lower() in seen_names:
            continue
        seen_keys.add(ckey)
        seen_names.add(display_name.lower())
        companies.append({
            "company_key": ckey,
            "display_name": display_name,
            "created_at": row["created_at"] or "",
            "website_url": row["company_url"] or "",
        })
    return companies


def _card_values_completeness(conn: sqlite3.Connection, company_key: str) -> int | None:
    """从 final_card_values 表计算字段完整度（research_fields 不存在时的 fallback）。"""
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "final_card_values" not in tables:
        return None
    required = list(dict.fromkeys(REQUIRED_RESEARCH_FIELDS))
    placeholders = ",".join(["?"] * len(required))
    row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT field_key) AS filled
        FROM final_card_values
        WHERE company_key=?
          AND field_key IN ({placeholders})
          AND final_value IS NOT NULL
          AND TRIM(CAST(final_value AS TEXT)) NOT IN ('', '暂缺')
        """,
        [company_key, *required],
    ).fetchone()
    if not row or not row["filled"]:
        return None
    return round(int(row["filled"] or 0) / len(required) * 100)


def _lookup_field_value(conn: sqlite3.Connection, company_name: str,
                        company_key: str, field_key: str) -> str | None:
    """从 research_fields 查找单个字段的最新非空值。"""
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "research_fields" not in tables:
        return None
    columns = {r["name"] for r in conn.execute(
        "PRAGMA table_info(research_fields)").fetchall()}
    has_ckey = "company_key" in columns
    clauses = ["LOWER(company_name)=LOWER(?)"]
    params: list[object] = [company_name]
    if has_ckey and company_key:
        clauses.append("company_key=?")
        params.append(company_key)
    row = conn.execute(
        f"SELECT field_value FROM research_fields "
        f"WHERE ({' OR '.join(clauses)}) AND field_key=? "
        f"AND field_value IS NOT NULL "
        f"AND TRIM(CAST(field_value AS TEXT)) NOT IN ('', '暂缺') "
        f"ORDER BY id DESC LIMIT 1",
        [*params, field_key],
    ).fetchone()
    return str(row["field_value"]) if row else None


def _scoring_from_research_fields(conn: sqlite3.Connection,
                                   company_name: str, company_key: str) -> dict:
    """从 research_fields 读取评分相关字段，构建 scoring payload."""
    scoring_fields = [
        "ai_model_dependency", "workflow_integration_level", "data_flywheel",
        "proprietary_data_asset", "incumbent_direct_competitor",
        "customer_segment_type", "funding_stage", "pricing_model",
        "inference_cost_exposure", "stack_layer",
    ]
    payload: dict[str, object] = {}
    for fk in scoring_fields:
        v = _lookup_field_value(conn, company_name, company_key, fk)
        payload[fk] = v or ""
    # 数值评分字段默认 None
    for fk in ("funding_stage_score", "score_defensibility",
               "score_incumbent_attention", "score_value_capture"):
        v = _lookup_field_value(conn, company_name, company_key, fk)
        try:
            payload[fk] = float(v) if v else None
        except (ValueError, TypeError):
            payload[fk] = None
    return payload


def _company_scoring_payload(row: sqlite3.Row | None) -> dict:
    if not row:
        return {
            "ai_model_dependency": "",
            "workflow_integration_level": "",
            "data_flywheel": "",
            "proprietary_data_asset": "",
            "incumbent_direct_competitor": "",
            "customer_segment_type": "",
            "funding_stage": "",
            "funding_stage_score": None,
            "pricing_model": "",
            "inference_cost_exposure": "",
            "stack_layer": "",
            "score_defensibility": None,
            "score_incumbent_attention": None,
            "score_value_capture": None,
        }

    data = dict(row)
    normalized = normalize_fields(data)
    scores = compute_scores(normalized)
    payload = {}
    for field in [
        "ai_model_dependency",
        "workflow_integration_level",
        "data_flywheel",
        "proprietary_data_asset",
        "incumbent_direct_competitor",
        "customer_segment_type",
        "funding_stage",
        "pricing_model",
        "inference_cost_exposure",
        "stack_layer",
    ]:
        payload[field] = data.get(field) or normalized[field]
    for field in [
        "funding_stage_score",
        "score_defensibility",
        "score_incumbent_attention",
        "score_value_capture",
    ]:
        payload[field] = data.get(field) if data.get(field) is not None else scores[field]
    return payload


def _latest_job_company_url(conn: sqlite3.Connection, company_name: str) -> str:
    try:
        row = conn.execute(
            "SELECT company_url FROM research_jobs WHERE company_name=? ORDER BY created_at DESC LIMIT 1",
            (company_name,),
        ).fetchone()
        return row["company_url"] if row else ""
    except sqlite3.Error:
        return ""


def _count_confirmed_cards(final_db_path: str, company_name: str) -> int:
    try:
        with get_db(final_db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT card_index) as cnt FROM final_content WHERE company_name=? AND field_name='markdown_full'",
                (company_name,),
            ).fetchone()
            return row["cnt"] if row else 0
    except Exception:
        return 0


def _count_enabled_cards(composition_db_path: str, company_name: str,
                         company_key: str = "") -> int:
    """返回卡片设置中启用的卡片数。无数据则默认 8。
    优先按 company_key 查询，回退到 company_name（兼容旧数据）。"""
    if not composition_db_path:
        return 8
    try:
        with get_db(composition_db_path) as conn:
            # 优先 company_key（如果列存在且有值匹配）
            if company_key:
                has_ckey = any(
                    r["name"] == "company_key"
                    for r in conn.execute("PRAGMA table_info(card_compositions)").fetchall()
                )
                if has_ckey:
                    row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM card_compositions "
                        "WHERE (company_key=? OR (company_key IS NULL AND company_name=?)) "
                        "AND enabled=1",
                        (company_key, company_name),
                    ).fetchone()
                    if row and row["cnt"] > 0:
                        return row["cnt"]
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM card_compositions "
                "WHERE company_name=? AND enabled=1",
                (company_name,),
            ).fetchone()
            if row and row["cnt"] > 0:
                return row["cnt"]
    except Exception:
        pass
    return 8


def _count_final_fields_progress(final_db_path: str, company_name: str,
                                  company_key: str = "") -> tuple[int, int]:
    try:
        with get_db(final_db_path) as conn:
            # 优先 company_key（如果 final_fields 表有此列且有值）
            if company_key:
                has_ckey = any(
                    r["name"] == "company_key"
                    for r in conn.execute("PRAGMA table_info(final_fields)").fetchall()
                )
                if has_ckey:
                    row = conn.execute(
                        """SELECT
                             COUNT(CASE WHEN status='confirmed' THEN 1 END) as confirmed,
                             COUNT(*) as total
                           FROM final_fields
                           WHERE (company_key=? OR (company_key IS NULL AND company_name=?))""",
                        (company_key, company_name),
                    ).fetchone()
                    if row and row["total"] > 0:
                        return row["confirmed"] or 0, 0
            row = conn.execute(
                """SELECT
                     COUNT(CASE WHEN status='confirmed' THEN 1 END) as confirmed,
                     COUNT(*) as total
                   FROM final_fields
                   WHERE company_name=?""",
                (company_name,),
            ).fetchone()
            total = row["total"] if row else 0
            if total:
                return row["confirmed"] or 0, 0
    except Exception:
        pass
    return _count_confirmed_cards(final_db_path, company_name), 0


def get_research(db_path: str, company_name: str, version: str) -> dict | None:
    """读取指定版本的全部字段。先按 company_key 查（支持传 key），再按 company_name 回退。"""
    with get_db(db_path) as conn:
        has_ckey = any(
            r["name"] == "company_key"
            for r in conn.execute("PRAGMA table_info(research)").fetchall()
        )
        if has_ckey:
            # 先按 company_key 精确匹配
            row = conn.execute(
                "SELECT * FROM research "
                "WHERE company_key=? AND version=? "
                "ORDER BY created_at DESC LIMIT 1",
                (company_name, version),
            ).fetchone()
            if row:
                return dict(row)
            # 再按 COALESCE 回退（兼容 company_key 为空的历史数据）
            row = conn.execute(
                "SELECT * FROM research "
                "WHERE COALESCE(NULLIF(company_key,''), LOWER(company_name))=LOWER(?) "
                "AND version=? "
                "ORDER BY created_at DESC LIMIT 1",
                (company_name, version),
            ).fetchone()
            return dict(row) if row else None
        # 旧 schema：精确 company_name 匹配
        row = conn.execute(
            "SELECT * FROM research WHERE company_name=? AND version=? "
            "ORDER BY created_at DESC LIMIT 1",
            (company_name, version),
        ).fetchone()
        return dict(row) if row else None


def get_research_by_key(db_path: str, company_key: str, version: str) -> dict | None:
    """读取指定版本的全部字段（按 company_key）"""
    with get_db(db_path) as conn:
        has_ckey = any(
            r["name"] == "company_key"
            for r in conn.execute("PRAGMA table_info(research)").fetchall()
        )
        if has_ckey:
            row = conn.execute(
                "SELECT * FROM research "
                "WHERE COALESCE(NULLIF(company_key,''), LOWER(company_name))=? "
                "AND version=? "
                "ORDER BY created_at DESC LIMIT 1",
                (company_key, version),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM research "
                "WHERE LOWER(company_name)=? AND version=? "
                "ORDER BY created_at DESC LIMIT 1",
                (company_key, version),
            ).fetchone()
        return dict(row) if row else None


def get_all_versions(db_path: str, company_name: str) -> dict[str, dict]:
    """读取某公司的所有版本"""
    versions = {}
    for v in ("standard", "business", "spread"):
        data = get_research(db_path, company_name, v)
        if data:
            versions[v] = data
    return versions


# ── research_db 写入 ──────────────────────────────────────────

REQUIRED_RESEARCH_FIELDS = [
    "company_type", "location", "company_def", "company_achievement",
    "founder_name", "founder_edu", "founder_bg", "founder_achievement",
    "team_size", "team_highlight",
    "funding_info", "website_url", "timeline_events", "main_product_name",
    "main_product_def", "main_product_highlight", "main_product_achievement",
    "main_product_img_src", "other_products", "revenue_model", "gtm_strategy",
    "cold_start", "customer_segment", "growth_flywheel",
    "revenue_metrics", "growth_metrics", "regional_markets",
    "tam", "sam", "som", "market_cagr",
    "arr", "mrr", "registered_users", "active_users", "paying_users",
    "retention_rate", "churn_rate", "cac", "ltv", "ltv_cac_ratio",
    "gross_margin", "burn_rate", "runway_months",
    "market_size_source_note",
    "moat", "competitors", "competitors_summary",
    "ecosystem_positioning", "differentiation_strategy",
    "cost_advantage", "technical_barrier", "switching_cost",
    "ideal_customer_profile", "customer_segment_primary",
    "customer_segment_secondary", "growth_strategy", "gtm_motion",
    "market_opportunity", "hook_paragraph_1", "hook_paragraph_2", "hook_paragraph_3",
    "data_confidence", "tech_stack",
    # v3 新增字段 — 公司简介页
    "market_track", "market_subtrack",
    "market_landscape_summary", "market_landscape_top_players",
    "market_size_value", "market_size_currency", "market_size_year",
    "tam_value", "tam_currency", "tam_year",
    "founded_date", "core_business", "core_competency",
    "funding_rounds", "company_achievements", "industry_positioning",
    # v3 新增字段 — 主产品页
    "product_pain_points", "product_core_features",
    "product_usage_playbook", "product_tech_stack",
    "regional_market_focus", "mau", "mau_as_of",
    "retention_definition", "pricing_summary", "pricing_tiers",
    "ecosystem_niche",
    # v3 新增字段 — 用户群体页
    "customer_names", "customer_selection_reasons", "customer_choice_evidence",
    # v3 新增字段 — 能力分析页
    "pricing_strategy", "ltv_cac_is_benchmark", "ltv_cac_benchmark_source",
    # v3 新增字段 — GTM 页
    "acquisition_channels",
    # v3 新增字段 — 竞争态势页
    "competitors_top3", "competitive_position",
    "differentiated_opportunity", "competitive_advantages",
]

COMPETITIVE_RESEARCH_FIELDS = [
    "ai_model_dependency",
    "workflow_integration_level",
    "data_flywheel",
    "proprietary_data_asset",
    "incumbent_direct_competitor",
    "customer_segment_type",
    "funding_stage",
    "funding_stage_score",
    "pricing_model",
    "inference_cost_exposure",
    "stack_layer",
    "score_defensibility",
    "score_incumbent_attention",
    "score_value_capture",
]

RESEARCH_SAVE_FIELDS = REQUIRED_RESEARCH_FIELDS + COMPETITIVE_RESEARCH_FIELDS


def _ensure_research_schema(conn: sqlite3.Connection):
    """Migrate existing local research DB files to the current scoring schema."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(research)").fetchall()}
    columns = {
        "ai_model_dependency": "TEXT",
        "workflow_integration_level": "TEXT",
        "data_flywheel": "TEXT",
        "proprietary_data_asset": "TEXT",
        "incumbent_direct_competitor": "TEXT",
        "customer_segment_type": "TEXT",
        "funding_stage": "TEXT",
        "funding_stage_score": "REAL",
        "pricing_model": "TEXT",
        "inference_cost_exposure": "TEXT",
        "stack_layer": "TEXT",
        "score_defensibility": "REAL",
        "score_incumbent_attention": "REAL",
        "score_value_capture": "REAL",
        # v2 新增字段
        "company_achievement": "TEXT",
        "tech_stack": "TEXT",
        "revenue_metrics": "TEXT",
        "growth_metrics": "TEXT",
        "regional_markets": "TEXT",
        "competitors_summary": "TEXT",
        "tam": "TEXT",
        "sam": "TEXT",
        "som": "TEXT",
        "market_cagr": "TEXT",
        "arr": "TEXT",
        "mrr": "TEXT",
        "registered_users": "TEXT",
        "active_users": "TEXT",
        "paying_users": "TEXT",
        "retention_rate": "TEXT",
        "churn_rate": "TEXT",
        "cac": "TEXT",
        "ltv": "TEXT",
        "ltv_cac_ratio": "TEXT",
        "gross_margin": "TEXT",
        "burn_rate": "TEXT",
        "runway_months": "TEXT",
        "market_size_source_note": "TEXT",
        "ecosystem_positioning": "TEXT",
        "differentiation_strategy": "TEXT",
        "cost_advantage": "TEXT",
        "technical_barrier": "TEXT",
        "switching_cost": "TEXT",
        "ideal_customer_profile": "TEXT",
        "customer_segment_primary": "TEXT",
        "customer_segment_secondary": "TEXT",
        "growth_strategy": "TEXT",
        "gtm_motion": "TEXT",
        # identity fields (P1)
        "company_key": "TEXT",
        "display_name": "TEXT",
        "input_name": "TEXT",
        "website_host": "TEXT",
        # v3 新增字段 — 公司简介页
        "market_track": "TEXT",
        "market_subtrack": "TEXT",
        "market_landscape_summary": "TEXT",
        "market_landscape_top_players": "TEXT",
        "market_size_value": "REAL",
        "market_size_currency": "TEXT",
        "market_size_year": "INTEGER",
        "tam_value": "REAL",
        "tam_currency": "TEXT",
        "tam_year": "INTEGER",
        "founded_date": "TEXT",
        "core_business": "TEXT",
        "core_competency": "TEXT",
        "funding_rounds": "TEXT",
        "company_achievements": "TEXT",
        "industry_positioning": "TEXT",
        # v3 新增字段 — 主产品页
        "product_pain_points": "TEXT",
        "product_core_features": "TEXT",
        "product_usage_playbook": "TEXT",
        "product_tech_stack": "TEXT",
        "regional_market_focus": "TEXT",
        "mau": "INTEGER",
        "mau_as_of": "TEXT",
        "retention_definition": "TEXT",
        "pricing_summary": "TEXT",
        "pricing_tiers": "TEXT",
        "ecosystem_niche": "TEXT",
        # v3 新增字段 — 用户群体页
        "customer_names": "TEXT",
        "customer_selection_reasons": "TEXT",
        "customer_choice_evidence": "TEXT",
        # v3 新增字段 — 能力分析页
        "pricing_strategy": "TEXT",
        "ltv_cac_is_benchmark": "INTEGER",
        "ltv_cac_benchmark_source": "TEXT",
        # v3 新增字段 — GTM 页
        "acquisition_channels": "TEXT",
        # v3 新增字段 — 竞争态势页
        "competitors_top3": "TEXT",
        "competitive_position": "TEXT",
        "differentiated_opportunity": "TEXT",
        "competitive_advantages": "TEXT",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE research ADD COLUMN {name} {definition}")


def save_research_records(db_path: str, records: list[dict]) -> list[int]:
    """保存多条研究记录到 research_db，返回插入的 ID 列表"""
    ids = []
    with get_db(db_path) as conn:
        _ensure_research_schema(conn)
        for rec in records:
            rec = dict(rec)
            for f in REQUIRED_RESEARCH_FIELDS:
                val = rec.get(f)
                if f == "ltv_cac_is_benchmark" and (
                    val is None or (isinstance(val, str) and val.strip() == "")
                ):
                    rec[f] = 0
                elif val is None or (isinstance(val, str) and val.strip() == ""):
                    rec[f] = "暂缺"
                elif isinstance(val, (list, dict)):
                    rec[f] = json.dumps(val, ensure_ascii=False)

            normalized = normalize_fields(rec)
            rec.update(normalized)
            rec.update(compute_scores(rec))

            values = [rec.get("company_name", "未知"), rec.get("version", "unknown")]
            values += [rec.get(f, "暂缺") for f in RESEARCH_SAVE_FIELDS]
            # identity columns (P1 — available when _collect_all runs with company_identity)
            id_cols = []
            for col in ["company_key", "display_name", "input_name", "website_host"]:
                if col in rec:
                    id_cols.append(col)
                    values.append(rec[col])
            placeholders = ",".join(["?"] * (len(RESEARCH_SAVE_FIELDS) + 2 + len(id_cols)))
            all_cols = ["company_name", "version"] + RESEARCH_SAVE_FIELDS + id_cols
            cur = conn.execute(
                f"INSERT INTO research ({','.join(all_cols)}) VALUES ({placeholders})",
                values,
            )
            ids.append(cur.lastrowid)
        conn.commit()
    return ids


# ── research_jobs 追踪 ──────────────────────────────────────────


def create_job(db_path: str, job_id: str, company_name: str, company_url: str,
               company_key: str = "", display_name: str = "", website_host: str = ""):
    with get_db(db_path) as conn:
        # 兼容旧 schema（无 company_key 列）
        has_ckey = any(
            row["name"] == "company_key"
            for row in conn.execute("PRAGMA table_info(research_jobs)").fetchall()
        )
        if has_ckey:
            conn.execute(
                """INSERT INTO research_jobs (job_id, company_name, company_url, company_key, display_name, website_host, status, stage, detail)
                   VALUES (?, ?, ?, ?, ?, ?, 'running', '启动', '准备开始...')""",
                (job_id, company_name, company_url, company_key or None,
                 display_name or None, website_host or None),
            )
        else:
            conn.execute(
                """INSERT INTO research_jobs (job_id, company_name, company_url, status, stage, detail)
                   VALUES (?, ?, ?, 'running', '启动', '准备开始...')""",
                (job_id, company_name, company_url),
            )
        conn.commit()


def update_job(db_path: str, job_id: str, **kwargs):
    if not kwargs:
        return
    sets = [f"{k}=?" for k in kwargs]
    values = list(kwargs.values()) + [job_id]
    with get_db(db_path) as conn:
        conn.execute(
            f"UPDATE research_jobs SET {','.join(sets)}, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
            values,
        )
        conn.commit()


def get_job(db_path: str, job_id: str) -> dict | None:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM research_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        return dict(row) if row else None


def get_latest_running_job(db_path: str) -> dict | None:
    """返回最近一条 running/cancelling 状态的 job，用于页面刷新恢复。"""
    with get_db(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM research_jobs
               WHERE status IN ('running', 'cancelling')
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None


# ── final_db 读写 ─────────────────────────────────────────────


def _ensure_final_unique_index(conn: sqlite3.Connection):
    """清理历史重复字段，并重建定稿字段唯一索引（含 card_set_key）。"""
    # 尝试删除旧版索引（如果存在），再创建新版索引
    try:
        conn.execute("DROP INDEX IF EXISTS idx_final_unique_field")
    except Exception:
        pass
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_final_unique_field
           ON final_content(company_name, card_set_key, card_index, field_name)"""
    )


def save_final_card(
    db_path: str,
    company_name: str,
    card_index: int,
    fields: dict[str, str],
    img_paths: dict[str, str] = None,
    card_set_key: str = "v1",
):
    """保存单张卡片字段到 final_db（UPSERT）。card_set_key 指定套卡。"""
    img_paths = img_paths or {}
    with get_db(db_path) as conn:
        _ensure_final_unique_index(conn)
        for field_name, field_value in fields.items():
            img_local_path = img_paths.get(field_name)
            conn.execute(
                """INSERT INTO final_content
                   (company_name, card_set_key, card_index, field_name,
                    field_value, img_local_path)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(company_name, card_set_key, card_index, field_name)
                   DO UPDATE SET
                     field_value=excluded.field_value,
                     img_local_path=COALESCE(excluded.img_local_path,
                                             final_content.img_local_path),
                     confirmed_at=CURRENT_TIMESTAMP""",
                (company_name, card_set_key, card_index,
                 field_name, field_value, img_local_path),
            )
        conn.commit()


def save_final_markdown(db_path: str, company_name: str, card_index: int,
                        markdown_content: str, card_set_key: str = "v1"):
    """保存单张卡片的整块 Markdown。"""
    save_final_card(db_path, company_name, card_index,
                    {"markdown_full": markdown_content},
                    card_set_key=card_set_key)


def get_final_card_markdown(db_path: str, company_name: str, card_index: int,
                            card_set_key: str = "v1") -> str | None:
    """读取单张卡片已定稿的 markdown_full。"""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT field_value FROM final_content"
            " WHERE company_name=? AND card_set_key=? AND card_index=? AND field_name='markdown_full'",
            (company_name, card_set_key, card_index),
        ).fetchone()
        return row["field_value"] if row else None


def get_finalized_field(final_db_path: str, research_db_path: str,
                        company_name: str, field_key: str,
                        card_set_key: str = "v1") -> str | None:
    """读取定稿字段值：final_fields → research DB → final_content（兼容旧数据）。"""
    # 1. 优先从 final_fields 读（表可能尚未创建，如旧 DB 未迁移）
    try:
        from repositories.field_repo import get_final_field_value
        value = get_final_field_value(final_db_path, company_name, field_key)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass

    # 2. 回退到 research DB 原始数据
    research = get_research(research_db_path, company_name, "standard")
    if research:
        raw = research.get(field_key)
        if raw is not None and str(raw).strip() not in ("", "暂缺"):
            val = str(raw).strip()
            # 如果是 JSON 字符串（如 timeline_events），解析为 markdown 友好格式
            if val.startswith("[") and val.endswith("]"):
                try:
                    import json as _json
                    items = _json.loads(val)
                    lines = []
                    for item in items:
                        if isinstance(item, dict):
                            # 兼容两种字段名：{year,title,desc} 或 {date,event,impact}
                            time = item.get("year") or item.get("date") or ""
                            title = item.get("title") or item.get("event") or ""
                            desc = item.get("desc") or item.get("impact") or ""
                            parts = [f"**{time}**" if time else ""]
                            if title: parts.append(title)
                            if desc: parts.append(f"— {desc}")
                            lines.append(" ".join(p for p in parts if p))
                        else:
                            lines.append(f"- {item}")
                    return "\n".join(lines)
                except Exception:
                    pass
            return val

    # 3. 回退到旧 final_content 表（兼容迁移前的数据）
    field_to_card = {
        "timeline_events": 3,      # v1 套卡仍需
        "growth_flywheel": 6,      # 两套卡共用
    }
    card_index = field_to_card.get(field_key)
    if card_index:
        markdown = get_final_card_markdown(final_db_path, company_name, card_index,
                                           card_set_key=card_set_key)
        if markdown:
            return markdown
    return None


def get_final_status(db_path: str, company_name: str,
                     card_set_key: str = "v1") -> dict:
    cards = get_final_cards(db_path, company_name, card_set_key=card_set_key)
    confirmed = sorted({c["card_index"] for c in cards if c["field_name"] == "markdown_full"} or
                       {c["card_index"] for c in cards})
    total = 7 if card_set_key == "v2" else 8  # v1=8, v2=7, v3=8
    return {
        "company_name": company_name,
        "card_set_key": card_set_key,
        "confirmed": confirmed,
        "total": total,
    }


def get_final_cards(db_path: str, company_name: str,
                    card_set_key: str = "v1") -> list[dict]:
    """读取某公司某套卡所有已确认卡片，按 card_index 排序"""
    with get_db(db_path) as conn:
        _ensure_final_unique_index(conn)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM final_content WHERE company_name=? AND card_set_key=? ORDER BY card_index, id",
            (company_name, card_set_key),
        ).fetchall()
        return [dict(row) for row in rows]


def export_json(db_path: str, company_name: str, card_set_key: str = "v1") -> dict | None:
    """导出结构化 JSON，供 canvas 直接消费"""
    cards = get_final_cards(db_path, company_name, card_set_key=card_set_key)
    if not cards:
        return None

    result: dict[str, dict] = {}
    for c in cards:
        ci = str(c["card_index"])
        if ci not in result:
            result[ci] = {"fields": {}, "img_paths": {}}
        if c["field_name"] == "markdown_full":
            result[ci]["markdown_content"] = c["field_value"] or ""
        else:
            result[ci]["fields"][c["field_name"]] = c["field_value"] or ""
        if c["img_local_path"]:
            result[ci]["img_paths"][c["field_name"]] = c["img_local_path"]

    return {
        "company_name": company_name,
        "cards": result,
        "confirmed_count": len(result),
    }


def _safe_image_dir_name(company_name: str) -> str:
    return safe_path_segment(company_name)


def delete_company(research_db_path: str, final_db_path: str, assets_db_path: str,
                  images_dir: str, company_name: str) -> dict:
    """真删除某公司全部数据：3个DB的5张表 + images目录。返回删除计数。"""
    counts = {}

    # research_db: research + research_jobs
    with get_db(research_db_path) as conn:
        cur = conn.execute("DELETE FROM research WHERE company_name=?", (company_name,))
        counts["research"] = cur.rowcount
        cur = conn.execute("DELETE FROM research_jobs WHERE company_name=?", (company_name,))
        counts["research_jobs"] = cur.rowcount
        conn.commit()

    # final_db: final_content
    with get_db(final_db_path) as conn:
        cur = conn.execute("DELETE FROM final_content WHERE company_name=?", (company_name,))
        counts["final_content"] = cur.rowcount
        conn.commit()

    # assets_db: image_variants + company_assets
    with get_db(assets_db_path) as conn:
        cur = conn.execute("DELETE FROM image_variants WHERE company_name=?", (company_name,))
        counts["image_variants"] = cur.rowcount
        cur = conn.execute("DELETE FROM company_assets WHERE company_name=?", (company_name,))
        counts["company_assets"] = cur.rowcount
        conn.commit()

    # images 目录
    base_dir = os.path.abspath(images_dir)
    img_dir = os.path.abspath(os.path.join(base_dir, _safe_image_dir_name(company_name)))
    if os.path.commonpath([base_dir, img_dir]) != base_dir:
        counts["images_dir"] = "路径越界，已跳过"
        return counts
    if os.path.exists(img_dir):
        shutil.rmtree(img_dir)
        counts["images_dir"] = "已删除"
    else:
        counts["images_dir"] = "不存在"

    return counts


def export_markdown(db_path: str, company_name: str, card_set_key: str = "v1") -> str:
    """从 final_db 导出完整 Markdown"""
    cards = get_final_cards(db_path, company_name, card_set_key=card_set_key)
    if not cards:
        return ""

    # 按卡片分组
    card_groups: dict[int, list[dict]] = {}
    for c in cards:
        card_groups.setdefault(c["card_index"], []).append(c)

    lines: list[str] = []
    _CARD_TITLES_MAP = {
        "v1": ["", "首页", "公司介绍", "发展沿袭",
               "产品线（主产品）", "其他产品", "商业模式", "竞争格局", "总结"],
        "v2": ["", "封面", "公司概览", "产品与定位",
               "创始人与团队", "核心客户", "GTM与增长", "竞争格局"],
        "v3": ["", "封面", "公司简介", "主产品",
               "创始团队", "用户群体", "公司能力分析", "增长与GTM", "竞争态势"],
    }
    card_titles = _CARD_TITLES_MAP.get(card_set_key, _CARD_TITLES_MAP["v1"])

    for idx in range(1, 9):
        fields = card_groups.get(idx, [])
        if not fields:
            continue
        lines.append(f"## 卡片{idx}：{card_titles[idx]}")
        lines.append("")
        for f in fields:
            if f["field_name"] == "markdown_full":
                lines.append(f["field_value"] or "")
                continue
            label = f["field_name"]
            value = f["field_value"] or ""
            if f["img_local_path"]:
                lines.append(f"- **{label}**：{value}")
                lines.append(f"  ![图片]({f['img_local_path']})")
            else:
                lines.append(f"- **{label}**：{value}")
        lines.append("")

    return "\n".join(lines)
