"""实体同步服务 — 将 LLM 提取结果写入 9 张归一化实体表

从研究流水线的 LLM 提取结果（parsed_record + evidence_map）映射到归一化实体表。
每条记录携带审计列：evidence_span_ids, resolution_status, confidence, as_of_date, source_note。

使用 entity_repo 的 UPSERT 函数写入基础行，再通过直接 UPDATE 回填审计列。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from repositories.entity_repo import (
    upsert_company,
    upsert_product,
    upsert_metric,
    upsert_sector,
    upsert_founder,
    upsert_funding_round,
    upsert_customer,
    upsert_competitor,
    upsert_analysis,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 审计列名集合 — 迁移 034 为每个实体表新增的列
# ---------------------------------------------------------------------------
_AUDIT_COLUMNS = [
    "evidence_span_ids",
    "resolution_status",
    "confidence",
    "as_of_date",
    "source_note",
]

# companies 表的 confidence 是 REAL (0.0–1.0)，其余表是 TEXT
# 迁移 034: companies.confidence REAL DEFAULT 0.5; 其他表已有 confidence TEXT
_CONFIDENCE_REAL_TABLES = {"companies"}
_CONFIDENCE_TEXT_DEFAULT = "medium"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collect_evidence_ids(field_keys: list[str], evidence_map: dict[str, list]) -> list[str]:
    """从 evidence_map 中收集指定 field_keys 对应的所有 evidence span ID。

    evidence_map: {field_key: [span_id, ...]}
    """
    ids: list[str] = []
    seen: set[str] = set()
    for key in field_keys:
        spans = evidence_map.get(key, [])
        if isinstance(spans, list):
            for sid in spans:
                if sid and sid not in seen:
                    ids.append(sid)
                    seen.add(sid)
    return ids


def _get_resolution_status(parsed: dict, field_keys: list[str], default: str = "llm_extracted") -> str:
    """从 parsed_record 中提取 resolution_status。

    优先查找 _resolution_status 或 resolution_status 顶层键，
    否则尝试从每个 field_key 的嵌套对象中提取。
    """
    # 顶层覆盖
    for top_key in ("_resolution_status", "resolution_status"):
        val = parsed.get(top_key)
        if val:
            return str(val)

    # 按 field 查找
    for fk in field_keys:
        field_data = parsed.get(fk)
        if isinstance(field_data, dict):
            rs = field_data.get("resolution_status")
            if rs:
                return str(rs)

    return default


def _get_confidence_value(parsed: dict, field_keys: list[str],
                          table_name: str) -> Any:
    """从 parsed_record 提取 confidence。

    companies 表返回 float (0.0–1.0)，默认 0.5。
    其余表返回 TEXT 字符串，默认 'medium'。
    """
    # 顶层覆盖
    for top_key in ("_confidence", "confidence"):
        val = parsed.get(top_key)
        if val is not None and val != "":
            if table_name in _CONFIDENCE_REAL_TABLES:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return 0.5
            else:
                return str(val)

    # 按 field 查找
    for fk in field_keys:
        field_data = parsed.get(fk)
        if isinstance(field_data, dict):
            c = field_data.get("confidence")
            if c is not None and c != "":
                if table_name in _CONFIDENCE_REAL_TABLES:
                    try:
                        return float(c)
                    except (ValueError, TypeError):
                        continue
                else:
                    return str(c)

    # 默认值
    if table_name in _CONFIDENCE_REAL_TABLES:
        return 0.5
    return _CONFIDENCE_TEXT_DEFAULT


def _get_as_of_date(parsed: dict, field_keys: list[str]) -> str:
    """从 parsed_record 提取 as_of_date，否则使用当前时间。"""
    for top_key in ("_as_of_date", "as_of_date", "research_date"):
        val = parsed.get(top_key)
        if val:
            return str(val)
    for fk in field_keys:
        field_data = parsed.get(fk)
        if isinstance(field_data, dict):
            d = field_data.get("as_of_date")
            if d:
                return str(d)
    return _now_iso()


def _get_source_note(parsed: dict, field_keys: list[str]) -> str:
    """从 parsed_record 构建 source_note。"""
    for top_key in ("_source_note", "source_note"):
        val = parsed.get(top_key)
        if val:
            return str(val)
    # 从字段级收集
    sources: list[str] = []
    for fk in field_keys:
        field_data = parsed.get(fk)
        if isinstance(field_data, dict):
            sn = field_data.get("source_note")
            if sn:
                sources.append(str(sn))
    return "; ".join(sources) if sources else ""


def _write_audit_columns(
    cursor: sqlite3.Cursor,
    table_name: str,
    lookup_column: str,
    lookup_value: str,
    evidence_span_ids: list[str],
    resolution_status: str,
    confidence: Any,
    as_of_date: str,
    source_note: str,
) -> bool:
    """在 entity_repo upsert 之后回填审计列。

    使用 try/except 包裹，因为：
    1. entity_repo 当前不写审计列，需要额外 UPDATE
    2. 如果审计列尚不存在（迁移未执行），静默降级
    """
    evidence_json = json.dumps(evidence_span_ids, ensure_ascii=False) if evidence_span_ids else "[]"
    try:
        cursor.execute(
            f"""UPDATE {table_name}
                SET evidence_span_ids = ?,
                    resolution_status = ?,
                    confidence = ?,
                    as_of_date = ?,
                    source_note = ?
                WHERE {lookup_column} = ?""",
            (evidence_json, resolution_status, confidence, as_of_date, source_note,
             lookup_value),
        )
        # 立即提交，释放连接上的写锁，避免阻塞 entity_repo 后续写入
        if cursor.connection is not None:
            cursor.connection.commit()
        return True
    except sqlite3.OperationalError as e:
        err_msg = str(e)
        if "no such column" in err_msg:
            logger.warning(
                "Audit columns not found on %s — migration 034 may not have run: %s",
                table_name, err_msg,
            )
        else:
            logger.warning("Failed to write audit columns for %s: %s", table_name, err_msg)
        return False
    except Exception as e:
        logger.warning("Failed to write audit columns for %s: %s", table_name, e)
        return False


def _parse_location(location_str: str) -> tuple[str, str]:
    """将 location 字符串拆分为 (city, country)。

    "San Francisco, CA, USA" → ("San Francisco", "USA")
    "London, UK" → ("London", "UK")
    "Beijing" → ("Beijing", "")
    """
    if not location_str:
        return "", ""
    parts = [p.strip() for p in location_str.split(",")]
    if len(parts) == 1:
        return parts[0], ""
    if len(parts) == 2:
        return parts[0], parts[1]
    # 3+ parts: 第一部分是 city，最后一部分是 country
    return parts[0], parts[-1]


def _parse_funding_json(value: Any) -> list[dict]:
    """解析 funding_info 或 funding_rounds 为 funding round 列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _parse_competitors(value: Any) -> list[dict]:
    """解析 competitors_top3 为 competitor 列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _parse_customer_names(value: Any) -> list[str]:
    """解析 customer_names 为名称列表。"""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        # 逗号分隔
        return [n.strip() for n in value.split(",") if n.strip()]
    return []


# ---------------------------------------------------------------------------
# EntitySyncService
# ---------------------------------------------------------------------------


class EntitySyncService:
    """将 LLM 提取结果同步到 9 张归一化实体表。

    用法:
        service = EntitySyncService(db_path)
        result = service.sync_from_llm_result(
            company_key="anthropic",
            parsed_record={...},   # L3 提取输出的扁平 dict
            evidence_map={...},    # {field_key: [span_id, ...]}
            run_id="abc123",
        )
        # result: {"companies": 1, "products": 1, ...}
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def sync_from_llm_result(
        self,
        company_key: str,
        parsed_record: dict,
        evidence_map: dict[str, list],
        run_id: str = "",
    ) -> dict[str, int]:
        """将一次 LLM 提取的完整结果写入全部实体表。

        Returns:
            {table_name: rows_written}
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        counts: dict[str, int] = {}

        try:
            counts["companies"] = self._sync_company(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
            counts["products"] = self._sync_products(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
            counts["metrics"] = self._sync_metrics(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
            counts["sectors"] = self._sync_sector(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
            counts["founders"] = self._sync_founders(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
            counts["funding_rounds"] = self._sync_funding_rounds(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
            counts["customers"] = self._sync_customers(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
            counts["competitors"] = self._sync_competitors(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
            counts["company_analysis"] = self._sync_analysis(cursor, company_key, parsed_record, evidence_map)
            conn.commit()
        finally:
            conn.close()

        return counts

    # ------------------------------------------------------------------
    # 1. companies
    # ------------------------------------------------------------------

    def _sync_company(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        field_keys = [
            "company_type", "founded_date", "location", "core_business",
            "core_competency", "industry_positioning", "company_achievements",
            "website_url", "company_name",
        ]
        company_name = parsed.get("company_name", company_key)
        location = parsed.get("location", "")
        city, country = _parse_location(location)

        # 公司成就没有独立列，追加到 company_definition
        achievements = parsed.get("company_achievements", "")
        company_def_parts = []
        if parsed.get("company_def"):
            company_def_parts.append(parsed["company_def"])
        if achievements:
            company_def_parts.append(f"[Achievements] {achievements}")

        data = {
            "company_key": company_key,
            "name": company_name,
            "website_url": parsed.get("website_url", ""),
            "company_category": parsed.get("company_type", ""),
            "company_definition": "\n".join(company_def_parts),
            "founded_date": str(parsed.get("founded_date", "")),
            "hq_country": country,
            "hq_city": city,
            "main_business": parsed.get("core_business", ""),
            "core_advantage": parsed.get("core_competency", ""),
            "industry_positioning": parsed.get("industry_positioning", ""),
            "data_confidence": str(_get_confidence_value(parsed, field_keys, "companies")),
        }

        try:
            ok = upsert_company(self.db_path, data)
        except Exception as e:
            logger.warning("upsert_company failed for %s: %s", company_key, e)
            ok = False

        if not ok:
            logger.warning("upsert_company returned False for %s", company_key)
            return 0

        # 回填审计列
        evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
        resolution_status = _get_resolution_status(parsed, field_keys)
        confidence = _get_confidence_value(parsed, field_keys, "companies")
        as_of_date = _get_as_of_date(parsed, field_keys)
        source_note = _get_source_note(parsed, field_keys)

        _write_audit_columns(
            cursor, "companies", "company_key", company_key,
            evidence_ids, resolution_status, confidence, as_of_date, source_note,
        )
        return 1

    # ------------------------------------------------------------------
    # 2. products
    # ------------------------------------------------------------------

    def _sync_products(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        field_keys = [
            "main_product_name", "product_pain_points", "product_core_features",
            "product_usage_playbook", "product_tech_stack",
            "regional_market_focus", "pricing_summary",
        ]
        product_name = parsed.get("main_product_name", "")
        if not product_name:
            return 0

        data = {
            "company_key": company_key,
            "name": product_name,
            "is_primary": 1,
            "target_pain_points": parsed.get("product_pain_points", ""),
            "core_features": parsed.get("product_core_features", ""),
            "usage_play": parsed.get("product_usage_playbook", ""),
            "tech_stack": parsed.get("product_tech_stack", ""),
            "regional_markets": parsed.get("regional_market_focus", ""),
            "pricing_detail": parsed.get("pricing_summary", ""),
            "confidence": str(_get_confidence_value(parsed, field_keys, "products")),
        }

        try:
            ok = upsert_product(self.db_path, data)
        except Exception as e:
            logger.warning("upsert_product failed for %s: %s", company_key, e)
            ok = False

        if not ok:
            logger.warning("upsert_product returned False for %s", company_key)
            return 0

        evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
        resolution_status = _get_resolution_status(parsed, field_keys)
        confidence = _get_confidence_value(parsed, field_keys, "products")
        as_of_date = _get_as_of_date(parsed, field_keys)
        source_note = _get_source_note(parsed, field_keys)

        _write_audit_columns(
            cursor, "products", "company_key", company_key,
            evidence_ids, resolution_status, confidence, as_of_date, source_note,
        )
        return 1

    # ------------------------------------------------------------------
    # 3. metrics
    # ------------------------------------------------------------------

    _METRIC_FIELD_MAP: dict[str, str] = {
        "market_size_value": "market_size",
        "market_cagr": "cagr",
        "tam_value": "tam",
        "mau": "mau",
        "retention_rate": "retention_rate",
        "cac": "cac",
        "ltv": "ltv",
        "arr": "arr",
    }

    def _sync_metrics(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        count = 0
        for field_key, metric_key in self._METRIC_FIELD_MAP.items():
            value = parsed.get(field_key)
            if value is None or value == "":
                continue

            # 尝试转为数值
            metric_value = None
            metric_text = str(value)
            try:
                metric_value = float(value)
            except (ValueError, TypeError):
                pass

            # 从 parsed 子字段获取更多维度
            unit = parsed.get(f"{field_key}_unit", "")
            period = parsed.get(f"{field_key}_year", "") or parsed.get(f"{field_key}_period", "")
            region = parsed.get(f"{field_key}_region", "")
            segment = parsed.get(f"{field_key}_segment", "")

            field_keys_for_this = [field_key,
                                   f"{field_key}_unit",
                                   f"{field_key}_year",
                                   f"{field_key}_region"]

            data = {
                "company_key": company_key,
                "entity_type": "company",
                "entity_id": None,
                "metric_key": metric_key,
                "metric_value": metric_value,
                "metric_text": metric_text,
                "unit": unit,
                "period": period,
                "region": region,
                "segment": segment,
                "source_id": "",
                "status": parsed.get("resolution_status", "unavailable"),
                "estimate_method": "",
                "confidence": str(_get_confidence_value(parsed, field_keys_for_this, "metrics")),
            }

            try:
                ok = upsert_metric(self.db_path, data)
            except Exception as e:
                logger.warning("upsert_metric failed for %s/%s: %s", company_key, metric_key, e)
                continue

            if not ok:
                continue

            evidence_ids = _collect_evidence_ids(field_keys_for_this, evidence_map)
            resolution_status = _get_resolution_status(parsed, field_keys_for_this)
            confidence = _get_confidence_value(parsed, field_keys_for_this, "metrics")
            as_of_date = _get_as_of_date(parsed, field_keys_for_this)
            source_note = _get_source_note(parsed, field_keys_for_this)

            _write_audit_columns(
                cursor, "metrics", "company_key", company_key,
                evidence_ids, resolution_status, confidence, as_of_date, source_note,
            )
            count += 1

        return count

    # ------------------------------------------------------------------
    # 4. sectors
    # ------------------------------------------------------------------

    def _sync_sector(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        field_keys = [
            "market_size_value", "market_cagr", "tam_value",
            "market_landscape", "sector_name",
        ]

        # 至少有一个值才写入
        market_size = parsed.get("market_size_value", "")
        market_cagr = parsed.get("market_cagr", "")
        tam = parsed.get("tam_value", "")
        if not any([market_size, market_cagr, tam]):
            return 0

        data = {
            "company_key": company_key,
            "sector_name": parsed.get("sector_name", ""),
            "market_landscape": parsed.get("market_landscape", ""),
            "market_size_summary": str(market_size) if market_size else "",
            "market_cagr_summary": str(market_cagr) if market_cagr else "",
            "tam_summary": str(tam) if tam else "",
            "source_note": _get_source_note(parsed, field_keys),
            "confidence": str(_get_confidence_value(parsed, field_keys, "sectors")),
        }

        try:
            ok = upsert_sector(self.db_path, data)
        except Exception as e:
            logger.warning("upsert_sector failed for %s: %s", company_key, e)
            ok = False

        if not ok:
            return 0

        evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
        resolution_status = _get_resolution_status(parsed, field_keys)
        confidence = _get_confidence_value(parsed, field_keys, "sectors")
        as_of_date = _get_as_of_date(parsed, field_keys)
        source_note = _get_source_note(parsed, field_keys)

        _write_audit_columns(
            cursor, "sectors", "company_key", company_key,
            evidence_ids, resolution_status, confidence, as_of_date, source_note,
        )
        return 1

    # ------------------------------------------------------------------
    # 5. founders
    # ------------------------------------------------------------------

    def _sync_founders(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        field_keys = [
            "founder_name", "founder_edu", "founder_bg",
            "founder_achievement",
        ]
        founder_name = parsed.get("founder_name", "")
        if not founder_name:
            return 0

        # founder_name 可能是逗号分隔的多人列表
        names = [n.strip() for n in str(founder_name).split(",") if n.strip()]
        if not names:
            names = [str(founder_name)]

        count = 0
        for name in names:
            data = {
                "company_key": company_key,
                "name": name,
                "role": "",
                "education": parsed.get("founder_edu", ""),
                "career_background": parsed.get("founder_bg", ""),
                "founder_achievement": parsed.get("founder_achievement", ""),
                "credibility_note": "",
                "linkedin_url": "",
                "confidence": str(_get_confidence_value(parsed, field_keys, "founders")),
            }

            try:
                ok = upsert_founder(self.db_path, data)
            except Exception as e:
                logger.warning("upsert_founder failed for %s/%s: %s", company_key, name, e)
                continue

            if not ok:
                continue

            evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
            resolution_status = _get_resolution_status(parsed, field_keys)
            confidence = _get_confidence_value(parsed, field_keys, "founders")
            as_of_date = _get_as_of_date(parsed, field_keys)
            source_note = _get_source_note(parsed, field_keys)

            _write_audit_columns(
                cursor, "founders", "company_key", company_key,
                evidence_ids, resolution_status, confidence, as_of_date, source_note,
            )
            count += 1

        return count

    # ------------------------------------------------------------------
    # 6. funding_rounds
    # ------------------------------------------------------------------

    def _sync_funding_rounds(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        field_keys = ["funding_info", "funding_rounds"]

        # funding_rounds 优先（结构化 JSON），其次 funding_info
        rounds = _parse_funding_json(parsed.get("funding_rounds"))
        if not rounds:
            rounds = _parse_funding_json(parsed.get("funding_info"))

        if not rounds:
            # 尝试将 funding_info 作为纯文本整条写入
            funding_text = parsed.get("funding_info", "")
            if not funding_text:
                return 0
            # 作为单条 unknown round 写入
            rounds = [{"round_name": "Unknown", "amount": funding_text}]

        count = 0
        for rnd in rounds:
            if not isinstance(rnd, dict):
                continue

            amount = rnd.get("amount") or rnd.get("amount_usd")
            try:
                amount_val = float(amount) if amount is not None else None
            except (ValueError, TypeError):
                amount_val = None

            valuation = rnd.get("valuation") or rnd.get("valuation_usd")
            try:
                valuation_val = float(valuation) if valuation is not None else None
            except (ValueError, TypeError):
                valuation_val = None

            investors = rnd.get("investors", "")
            if isinstance(investors, list):
                investors = ", ".join(investors)

            data = {
                "company_key": company_key,
                "round_name": str(rnd.get("round_name") or rnd.get("round") or ""),
                "announced_date": str(rnd.get("announced_date") or rnd.get("date") or ""),
                "amount_usd": amount_val,
                "valuation_usd": valuation_val,
                "lead_investor": str(rnd.get("lead_investor") or ""),
                "investors": str(investors),
                "source_id": "",
                "confidence": str(_get_confidence_value(parsed, field_keys, "funding_rounds")),
            }

            try:
                ok = upsert_funding_round(self.db_path, data)
            except Exception as e:
                logger.warning("upsert_funding_round failed for %s: %s", company_key, e)
                continue

            if not ok:
                continue

            evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
            resolution_status = _get_resolution_status(parsed, field_keys)
            confidence = _get_confidence_value(parsed, field_keys, "funding_rounds")
            as_of_date = _get_as_of_date(parsed, field_keys)
            source_note = _get_source_note(parsed, field_keys)

            _write_audit_columns(
                cursor, "funding_rounds", "company_key", company_key,
                evidence_ids, resolution_status, confidence, as_of_date, source_note,
            )
            count += 1

        return count

    # ------------------------------------------------------------------
    # 7. customers
    # ------------------------------------------------------------------

    def _sync_customers(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        field_keys = [
            "customer_names", "customer_selection_reasons",
            "ideal_customer_profile",
        ]
        customer_names = _parse_customer_names(parsed.get("customer_names"))
        choice_reason = parsed.get("customer_selection_reasons", "")
        persona_name = parsed.get("ideal_customer_profile", "")

        if not customer_names and not persona_name:
            return 0

        count = 0

        if persona_name and not customer_names:
            # 只有 ICP/persona，写入一条 persona 记录
            data = {
                "company_key": company_key,
                "customer_type": "persona",
                "persona_name": persona_name,
                "customer_name": "",
                "industry": "",
                "customer_pain": "",
                "choice_reason": choice_reason,
                "evidence_summary": "",
                "source_id": "",
                "confidence": str(_get_confidence_value(parsed, field_keys, "customers")),
            }

            try:
                ok = upsert_customer(self.db_path, data)
            except Exception as e:
                logger.warning("upsert_customer failed for %s persona: %s", company_key, e)
                ok = False

            if ok:
                evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
                resolution_status = _get_resolution_status(parsed, field_keys)
                confidence = _get_confidence_value(parsed, field_keys, "customers")
                as_of_date = _get_as_of_date(parsed, field_keys)
                source_note = _get_source_note(parsed, field_keys)

                _write_audit_columns(
                    cursor, "customers", "company_key", company_key,
                    evidence_ids, resolution_status, confidence, as_of_date, source_note,
                )
                count += 1

        for cname in customer_names:
            data = {
                "company_key": company_key,
                "customer_type": "named_customer",
                "persona_name": persona_name,
                "customer_name": cname,
                "industry": "",
                "customer_pain": "",
                "choice_reason": choice_reason,
                "evidence_summary": "",
                "source_id": "",
                "confidence": str(_get_confidence_value(parsed, field_keys, "customers")),
            }

            try:
                ok = upsert_customer(self.db_path, data)
            except Exception as e:
                logger.warning("upsert_customer failed for %s/%s: %s", company_key, cname, e)
                continue

            if not ok:
                continue

            evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
            resolution_status = _get_resolution_status(parsed, field_keys)
            confidence = _get_confidence_value(parsed, field_keys, "customers")
            as_of_date = _get_as_of_date(parsed, field_keys)
            source_note = _get_source_note(parsed, field_keys)

            _write_audit_columns(
                cursor, "customers", "company_key", company_key,
                evidence_ids, resolution_status, confidence, as_of_date, source_note,
            )
            count += 1

        return count

    # ------------------------------------------------------------------
    # 8. competitors
    # ------------------------------------------------------------------

    def _sync_competitors(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        field_keys = ["competitors_top3"]
        competitors = _parse_competitors(parsed.get("competitors_top3"))

        if not competitors:
            return 0

        count = 0
        for idx, comp in enumerate(competitors):
            if not isinstance(comp, dict):
                continue

            comp_name = comp.get("name") or comp.get("company") or ""
            if not comp_name:
                continue

            data = {
                "company_key": company_key,
                "competitor_name": str(comp_name),
                "competitor_url": str(comp.get("url", "")),
                "product_summary": str(comp.get("product", "")),
                "company_summary": str(comp.get("data") or comp.get("summary", "")),
                "rank": idx + 1,
                "overlap_area": str(comp.get("overlap", "")),
                "difference_area": str(comp.get("difference", "")),
                "competitor_strength": str(comp.get("strength", "")),
                "competitor_weakness": str(comp.get("weakness", "")),
                "source_id": "",
                "confidence": str(_get_confidence_value(parsed, field_keys, "competitors")),
            }

            try:
                ok = upsert_competitor(self.db_path, data)
            except Exception as e:
                logger.warning("upsert_competitor failed for %s/%s: %s", company_key, comp_name, e)
                continue

            if not ok:
                continue

            evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
            resolution_status = _get_resolution_status(parsed, field_keys)
            confidence = _get_confidence_value(parsed, field_keys, "competitors")
            as_of_date = _get_as_of_date(parsed, field_keys)
            source_note = _get_source_note(parsed, field_keys)

            _write_audit_columns(
                cursor, "competitors", "company_key", company_key,
                evidence_ids, resolution_status, confidence, as_of_date, source_note,
            )
            count += 1

        return count

    # ------------------------------------------------------------------
    # 9. company_analysis
    # ------------------------------------------------------------------

    def _sync_analysis(
        self,
        cursor: sqlite3.Cursor,
        company_key: str,
        parsed: dict,
        evidence_map: dict[str, list],
    ) -> int:
        field_keys = [
            "competitive_position", "differentiated_opportunity",
            "competitive_advantages", "moat", "ecosystem_niche",
            "growth_strategy", "gtm_strategy", "growth_flywheel",
        ]

        # 至少有一个分析字段有值才写入
        has_any = any(parsed.get(fk) for fk in field_keys)
        if not has_any:
            return 0

        data = {
            "company_key": company_key,
            "ecosystem_niche": parsed.get("ecosystem_niche", ""),
            "monetization_strategy": parsed.get("monetization_strategy", ""),
            "pricing_strategy": parsed.get("pricing_strategy", ""),
            "value_capture_score": None,
            "defensibility_score": None,
            "competitive_position": parsed.get("competitive_position", ""),
            "differentiation_opportunity": parsed.get("differentiated_opportunity", ""),
            "competitive_advantage": parsed.get("competitive_advantages", ""),
            "moat": parsed.get("moat", ""),
            "risk_window": "",
            "gtm_motion": parsed.get("gtm_strategy", ""),
            "cold_start": parsed.get("cold_start", ""),
            "growth_strategy": parsed.get("growth_strategy", ""),
            "growth_flywheel": parsed.get("growth_flywheel", ""),
            "analysis_version": 1,
            "confidence": str(_get_confidence_value(parsed, field_keys, "company_analysis")),
        }

        try:
            ok = upsert_analysis(self.db_path, data)
        except Exception as e:
            logger.warning("upsert_analysis failed for %s: %s", company_key, e)
            ok = False

        if not ok:
            return 0

        evidence_ids = _collect_evidence_ids(field_keys, evidence_map)
        resolution_status = _get_resolution_status(parsed, field_keys)
        confidence = _get_confidence_value(parsed, field_keys, "company_analysis")
        as_of_date = _get_as_of_date(parsed, field_keys)
        source_note = _get_source_note(parsed, field_keys)

        _write_audit_columns(
            cursor, "company_analysis", "company_key", company_key,
            evidence_ids, resolution_status, confidence, as_of_date, source_note,
        )
        return 1
