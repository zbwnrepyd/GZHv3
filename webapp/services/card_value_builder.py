"""CardValueBuilder -- 从实体表构建 final_card_values 的读模型。

SPEC Section 5.2: 研究事实优先写入实体表。final_card_values 只作为卡片展示读模型。

Usage:
    builder = CardValueBuilder(db_path)
    card_values = builder.build_card_values(company_key, card_schema_version="v3")
    count = builder.write_to_final_card_values(company_key, run_id, card_values)
"""

from __future__ import annotations
import json
import sqlite3
from typing import Optional

from repositories import entity_repo as repo


# ── v3 套卡 8 页：每页字段 → 实体表映射 ──────────────────────────

_V3_CARD_FIELDS: dict[int, list[dict]] = {
    1: [
        {"field_key": "company_name",    "source": "companies",     "column": "name"},
        {"field_key": "company_type",    "source": "companies",     "column": "company_category"},
    ],
    2: [
        {"field_key": "market_landscape",     "source": "sectors",           "column": "market_landscape"},
        {"field_key": "market_size",          "source": "metrics",           "column": "metric_value",  "filter": "market_size"},
        {"field_key": "market_cagr",          "source": "metrics",           "column": "metric_value",  "filter": "market_cagr"},
        {"field_key": "tam",                  "source": "metrics",           "column": "metric_value",  "filter": "tam"},
        {"field_key": "location",             "source": "companies",         "column": "hq_city"},
        {"field_key": "founded_date",         "source": "companies",         "column": "founded_date"},
        {"field_key": "core_business",        "source": "companies",         "column": "main_business"},
        {"field_key": "core_competency",      "source": "companies",         "column": "core_advantage"},
        {"field_key": "funding_info",         "source": "funding_rounds",    "column": "summary",       "aggregate": "funding"},
        {"field_key": "company_achievements", "source": "companies",         "column": "company_definition"},
        {"field_key": "industry_positioning", "source": "companies",         "column": "industry_positioning"},
    ],
    3: [
        {"field_key": "main_product_name",       "source": "products",    "column": "name"},
        {"field_key": "product_pain_points",     "source": "products",    "column": "target_pain_points"},
        {"field_key": "product_core_features",   "source": "products",    "column": "core_features"},
        {"field_key": "product_usage_playbook",  "source": "products",    "column": "usage_play"},
        {"field_key": "product_tech_stack",      "source": "products",    "column": "tech_stack"},
        {"field_key": "regional_market_focus",   "source": "products",    "column": "regional_markets"},
        {"field_key": "mau",                     "source": "metrics",     "column": "metric_value",  "filter": "mau"},
        {"field_key": "retention_rate",          "source": "metrics",     "column": "metric_value",  "filter": "retention_rate"},
        {"field_key": "pricing_summary",         "source": "products",    "column": "pricing_detail"},
        {"field_key": "pricing_tiers",           "source": "products",    "column": "pricing_detail"},
    ],
    4: [
        {"field_key": "founder_name",        "source": "founders",  "column": "name"},
        {"field_key": "founder_edu",         "source": "founders",  "column": "education"},
        {"field_key": "founder_bg",          "source": "founders",  "column": "career_background"},
        {"field_key": "founder_achievement", "source": "founders",  "column": "founder_achievement"},
        {"field_key": "founder_role",        "source": "founders",  "column": "role"},
    ],
    5: [
        {"field_key": "ideal_customer_profile",     "source": "customers",  "column": "persona_name",     "aggregate": "list"},
        {"field_key": "customer_names",              "source": "customers",  "column": "customer_name",    "aggregate": "list"},
        {"field_key": "customer_selection_reasons",  "source": "customers",  "column": "choice_reason",    "aggregate": "list"},
        {"field_key": "customer_pains",              "source": "customers",  "column": "customer_pain",    "aggregate": "list"},
    ],
    6: [
        {"field_key": "ecosystem_niche",              "source": "company_analysis",  "column": "ecosystem_niche"},
        {"field_key": "revenue_model",                "source": "company_analysis",  "column": "monetization_strategy"},
        {"field_key": "pricing_strategy",             "source": "company_analysis",  "column": "pricing_strategy"},
        {"field_key": "ltv",                          "source": "metrics",           "column": "metric_value",  "filter": "ltv"},
        {"field_key": "cac",                          "source": "metrics",           "column": "metric_value",  "filter": "cac"},
        {"field_key": "ltv_cac_ratio",                "source": "metrics",           "column": "metric_value",  "filter": "ltv_cac_ratio"},
        {"field_key": "competitive_advantages",       "source": "company_analysis",  "column": "competitive_advantage"},
        {"field_key": "moat",                         "source": "company_analysis",  "column": "moat"},
    ],
    7: [
        {"field_key": "growth_strategy",      "source": "company_analysis",  "column": "growth_strategy"},
        {"field_key": "gtm_strategy",         "source": "company_analysis",  "column": "gtm_motion"},
        {"field_key": "cold_start",           "source": "company_analysis",  "column": "cold_start"},
        {"field_key": "growth_flywheel",      "source": "company_analysis",  "column": "growth_flywheel"},
        {"field_key": "acquisition_channels", "source": "company_analysis",  "column": "acquisition_channels"},
    ],
    8: [
        {"field_key": "competitors_top3",              "source": "competitors",       "column": "company_summary",  "aggregate": "top3"},
        {"field_key": "competitive_position",           "source": "company_analysis",  "column": "competitive_position"},
        {"field_key": "differentiated_opportunity",    "source": "company_analysis",  "column": "differentiation_opportunity"},
        {"field_key": "competitive_advantages_8",      "source": "company_analysis",  "column": "competitive_advantage"},
    ],
}


class CardValueBuilder:
    """从实体表构建卡片展示用的 final_card_values 读模型。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._cache: dict[str, dict | list[dict] | None] = {}

    # ── 缓存加载器 ──────────────────────────────────────────────────

    def _cached(self, cache_key: str, loader):
        if cache_key not in self._cache:
            self._cache[cache_key] = loader()
        return self._cache[cache_key]

    def _load_company(self, company_key: str) -> dict | None:
        return repo.get_company(self.db_path, company_key)

    def _load_primary_product(self, company_key: str) -> dict | None:
        return repo.get_primary_product(self.db_path, company_key)

    def _load_all_metrics(self, company_key: str) -> list[dict]:
        return repo.get_metrics(self.db_path, company_key)

    def _load_sector(self, company_key: str) -> dict | None:
        return repo.get_sector(self.db_path, company_key)

    def _load_founders(self, company_key: str) -> list[dict]:
        return repo.get_founders(self.db_path, company_key)

    def _load_funding_rounds(self, company_key: str) -> list[dict]:
        return repo.get_funding_rounds(self.db_path, company_key)

    def _load_customers(self, company_key: str) -> list[dict]:
        return repo.get_customers(self.db_path, company_key)

    def _load_competitors(self, company_key: str) -> list[dict]:
        return repo.get_competitors(self.db_path, company_key)

    def _load_analysis(self, company_key: str) -> dict | None:
        return repo.get_analysis(self.db_path, company_key)

    def _load_entity(self, source: str, company_key: str):
        loaders = {
            "companies":        lambda: self._load_company(company_key),
            "products":         lambda: self._load_primary_product(company_key),
            "metrics":          lambda: self._load_all_metrics(company_key),
            "sectors":          lambda: self._load_sector(company_key),
            "founders":         lambda: self._load_founders(company_key),
            "funding_rounds":   lambda: self._load_funding_rounds(company_key),
            "customers":        lambda: self._load_customers(company_key),
            "competitors":      lambda: self._load_competitors(company_key),
            "company_analysis": lambda: self._load_analysis(company_key),
        }
        loader = loaders.get(source)
        if not loader:
            return None
        return self._cached(f"entity:{source}:{company_key}", loader)

    # ── 证据 ID 查询 ─────────────────────────────────────────────────

    def _load_evidence_map(self, company_key: str) -> dict[str, list[int]]:
        """加载所有字段的证据 span ID 映射。"""
        cache_key = f"evidence_map:{company_key}"
        if cache_key in self._cache:
            return self._cache[cache_key] or {}

        evidence_map: dict[str, list[int]] = {}
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT field_key, id FROM evidence_spans
                   WHERE company_key = ?
                   AND (created_by_agent != 'posthoc_weak_matcher'
                        OR created_by_agent IS NULL)
                   AND confidence >= 0.35
                   ORDER BY confidence DESC""",
                (company_key,),
            ).fetchall()
            for r in rows:
                fk = r["field_key"]
                evidence_map.setdefault(fk, []).append(r["id"])
            conn.close()
        except Exception:
            pass

        self._cache[cache_key] = evidence_map
        return evidence_map

    def _get_evidence_ids(self, field_key: str, company_key: str) -> list[int]:
        evidence_map = self._load_evidence_map(company_key)
        return evidence_map.get(field_key, [])

    # ── 主入口 ──────────────────────────────────────────────────────

    def build_card_values(
        self,
        company_key: str,
        card_schema_version: str = "v3",
    ) -> list[dict]:
        """构建所有卡片的值列表。

        Args:
            company_key: 公司标识
            card_schema_version: 套卡版本（目前仅支持 v3）

        Returns:
            list of {card_no, field_key, final_value, source_evidence_ids, status, confidence}
        """
        card_fields = _V3_CARD_FIELDS if card_schema_version == "v3" else {}
        result: list[dict] = []

        for card_no in sorted(card_fields.keys()):
            mappings = card_fields[card_no]
            for mapping in mappings:
                field_key = mapping["field_key"]
                record = self._build_field_record(
                    mapping, company_key, card_no, field_key,
                )
                result.append(record)

        self.clear_cache()
        return result

    def _build_field_record(
        self,
        mapping: dict,
        company_key: str,
        card_no: int,
        field_key: str,
    ) -> dict:
        """为单个字段构建一条 final_card_values 记录。"""
        source = mapping.get("source", "")
        column = mapping.get("column", "")
        filter_key = mapping.get("filter", "")
        aggregate = mapping.get("aggregate", "")

        # 查询实体数据
        entity_data = self._load_entity(source, company_key)

        # 解析值、状态、置信度
        raw_value = None
        entity_confidence = None
        entity_status = None
        entity_row = None

        if source == "metrics" and isinstance(entity_data, list):
            raw_value, entity_row = self._resolve_metric(entity_data, filter_key)
        elif source in ("founders", "customers", "competitors", "funding_rounds") and isinstance(entity_data, list):
            raw_value, entity_row = self._resolve_list_entity(
                entity_data, column, aggregate,
            )
        elif isinstance(entity_data, dict):
            raw_value = entity_data.get(column)
            entity_row = entity_data

        # 格式化 final_value
        final_value = self._format_value(raw_value)

        # 收集证据 ID
        evidence_ids = self._collect_evidence_ids(field_key, company_key, entity_row, column)

        # 推断状态
        status = self._infer_status(raw_value, source, entity_row, entity_status)

        # 获取置信度
        confidence = self._get_confidence(entity_row, source)

        return {
            "card_no":              card_no,
            "field_key":            field_key,
            "final_value":          final_value,
            "source_evidence_ids":  json.dumps(evidence_ids, ensure_ascii=False) if evidence_ids else "",
            "status":               status,
            "confidence":           confidence,
        }

    # ── 值解析 ──────────────────────────────────────────────────────

    def _resolve_metric(
        self,
        metrics: list[dict],
        filter_key: str,
    ) -> tuple:
        """从 metrics 列表中按 metric_key 匹配。返回 (value, row_or_None)。"""
        for m in metrics:
            if m.get("metric_key") == filter_key:
                val = m.get("metric_value")
                if val is not None:
                    return val, m
                # 有些 metric 只有 metric_text
                text = m.get("metric_text")
                if text:
                    return text, m
        return None, None

    def _resolve_list_entity(
        self,
        rows: list[dict],
        column: str,
        aggregate: str = "",
    ) -> tuple:
        """从多行实体中提取值。支持聚合模式。

        aggregate="list": 返回列表（customer names 等）
        aggregate="funding": 格式化融资轮次为文本
        aggregate="top3": 取前 3 个竞品 summary
        默认：取第一行的值
        """
        if not rows:
            return None, None

        if aggregate == "list":
            values = [r.get(column, "") for r in rows if r.get(column)]
            return values if values else None, rows[0] if rows else None

        if aggregate == "funding":
            text = self._format_funding_rounds(rows)
            return text if text else None, rows[0] if rows else None

        if aggregate == "top3":
            summaries = []
            for r in rows[:3]:
                name = r.get("competitor_name", "")
                summary = r.get(column, "")
                if summary:
                    summaries.append(f"{name}: {summary}")
                elif name:
                    summaries.append(name)
            return summaries if summaries else None, rows[0] if rows else None

        # 默认：第一行第一列
        first = rows[0]
        return first.get(column), first

    # ── 格式化 ──────────────────────────────────────────────────────

    def _format_value(self, raw_value) -> str:
        """将原始值格式化为最终展示用的字符串。"""
        if raw_value is None:
            return "暂缺"

        if isinstance(raw_value, (int, float)):
            # 大数字加千分位
            if abs(raw_value) >= 1000 and raw_value == int(raw_value):
                return f"{int(raw_value):,}"
            if isinstance(raw_value, float):
                # 保留合理精度
                if abs(raw_value) < 1:
                    return f"{raw_value:.4f}"
                if abs(raw_value) < 100:
                    return f"{raw_value:.2f}"
                return f"{raw_value:,.1f}"
            return str(raw_value)

        if isinstance(raw_value, list):
            # 列表转为 JSON 字符串或中文顿号分隔
            if not raw_value:
                return "暂缺"
            # 如果每个元素都是简单字符串，用顿号连接
            if all(isinstance(x, str) for x in raw_value):
                return "、".join(str(x) for x in raw_value if x)
            return json.dumps(raw_value, ensure_ascii=False)

        s = str(raw_value).strip()
        return s if s else "暂缺"

    def _format_funding_rounds(self, rounds: list[dict]) -> str:
        """格式融资轮次为可读文本。"""
        if not rounds:
            return ""
        lines = []
        for r in rounds:
            round_name = r.get("round_name", "")
            amount = r.get("amount_usd")
            date_str = r.get("announced_date", "")
            lead = r.get("lead_investor", "")

            parts = []
            if date_str:
                parts.append(str(date_str)[:10] if len(str(date_str)) > 10 else str(date_str))
            if round_name:
                parts.append(str(round_name))
            if amount is not None:
                try:
                    amt = float(amount)
                    if amt >= 1_000_000_000:
                        parts.append(f"${amt/1_000_000_000:.1f}B")
                    elif amt >= 1_000_000:
                        parts.append(f"${amt/1_000_000:.0f}M")
                    else:
                        parts.append(f"${amt:,.0f}")
                except (ValueError, TypeError):
                    parts.append(str(amount))
            if lead:
                parts.append(f"领投: {lead}")

            if parts:
                lines.append(" | ".join(parts))

        return "\n".join(lines) if lines else ""

    # ── 证据收集 ────────────────────────────────────────────────────

    def _collect_evidence_ids(
        self,
        field_key: str,
        company_key: str,
        entity_row: dict | None,
        column: str,
    ) -> list[int]:
        """收集字段相关的证据 span ID。

        优先级:
        1. evidence_spans 表中匹配 field_key 的 span IDs
        2. entity row 中 source_id 引用的文档（如果有）
        """
        ids = self._get_evidence_ids(field_key, company_key)

        # 尝试从 entity row 的 source_id 补充
        if not ids and entity_row:
            source_id = entity_row.get("source_id", "")
            if source_id:
                try:
                    sid = int(source_id)
                    ids.append(sid)
                except (ValueError, TypeError):
                    pass

        return ids

    # ── 状态推断 ────────────────────────────────────────────────────

    def _infer_status(
        self,
        raw_value,
        source: str,
        entity_row: dict | None,
        metric_status: str | None = None,
    ) -> str:
        """根据实体数据和指标状态推断 resolution_status。

        返回: confirmed | proxy | industry_avg | unavailable
        """
        # 空值 → unavailable
        if raw_value is None:
            return "unavailable"
        if isinstance(raw_value, str) and raw_value.strip() == "":
            return "unavailable"
        if isinstance(raw_value, list) and not raw_value:
            return "unavailable"

        # metrics 表有自己的 status 字段
        if source == "metrics" and entity_row:
            ms = metric_status or entity_row.get("status", "")
            if ms == "confirmed":
                return "confirmed"
            if ms == "proxy":
                return "proxy"
            if ms == "industry_avg":
                return "industry_avg"
            if ms == "unavailable":
                return "unavailable"
            # 有值但状态不明确 → 根据 estimate_method 判断
            est_method = entity_row.get("estimate_method", "")
            if est_method == "industry_avg":
                return "industry_avg"
            if est_method == "proxy":
                return "proxy"
            # 有 metric_value 但非 confirmed → proxy
            return "proxy"

        # 其他实体表：有值就认为 confirmed（entity 表只存可靠值）
        confidence = self._get_confidence(entity_row, source)
        if confidence == "high" or confidence == "medium":
            return "confirmed"
        if confidence == "low":
            return "proxy"

        return "confirmed"

    # ── 置信度 ──────────────────────────────────────────────────────

    def _get_confidence(self, entity_row: dict | None, source: str) -> str:
        """从实体行获取置信度。"""
        if not entity_row:
            return "low"

        conf = entity_row.get("confidence", "") or entity_row.get("data_confidence", "")
        if conf in ("high", "medium", "low"):
            return conf
        return "medium"

    # ── 写入 final_card_values ───────────────────────────────────

    def write_to_final_card_values(
        self,
        company_key: str,
        run_id: str,
        card_values: list[dict],
    ) -> int:
        """将卡片值写入 final_card_values 表。返回实际写入行数。

        Args:
            company_key: 公司标识
            run_id: 关联的研究运行 ID
            card_values: build_card_values() 返回值

        Returns:
            写入的行数
        """
        if not card_values:
            return 0

        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """CREATE TABLE IF NOT EXISTS final_card_values (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    company_key TEXT NOT NULL,
                    card_no INTEGER NOT NULL,
                    field_key TEXT NOT NULL,
                    final_value TEXT,
                    source_evidence_ids TEXT,
                    status TEXT DEFAULT 'draft',
                    confidence TEXT DEFAULT 'medium',
                    editor_note TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (company_key, card_no, field_key)
                )""",
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_final_card_values_company
                   ON final_card_values(company_key)""",
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_final_card_values_card
                   ON final_card_values(company_key, card_no)""",
            )

            count = 0
            for cv in card_values:
                conn.execute(
                    """INSERT OR REPLACE INTO final_card_values
                       (run_id, company_key, card_no, field_key, final_value,
                        source_evidence_ids, status, confidence, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (
                        run_id,
                        company_key,
                        cv["card_no"],
                        cv["field_key"],
                        cv["final_value"],
                        cv.get("source_evidence_ids", ""),
                        cv.get("status", "draft"),
                        cv.get("confidence", "medium"),
                    ),
                )
                count += 1

            conn.commit()
            conn.close()
            return count
        except Exception:
            return 0

    def clear_cache(self):
        """清除内部缓存。"""
        self._cache.clear()
