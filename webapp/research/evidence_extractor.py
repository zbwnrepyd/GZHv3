"""证据抽取器 — 从 source_documents 中抽取字段级 evidence_spans。

P1: 解决字段可追溯问题。
从完整文档中定位与特定 field_key 相关的引用片段，
生成 evidence_spans 行并关联回 source_documents。
"""
from __future__ import annotations
import sqlite3
from typing import Optional


def _get_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def extract_field_evidence(db_path: str, document_id: int,
                           company_key: str, field_key: str,
                           quote_text: str, normalized_fact: str = "",
                           confidence: float = 0.5,
                           created_by_agent: str = "llm",
                           start_offset: int = 0,
                           end_offset: int = 0) -> int:
    """从文档中抽取一条证据片段。返回 span id，失败返回 -1。"""
    try:
        conn = _get_db(db_path)
        cur = conn.execute(
            """INSERT INTO evidence_spans
               (document_id, company_key, field_key, quote_text,
                normalized_fact, start_offset, end_offset, confidence,
                created_by_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (document_id, company_key, field_key,
             (quote_text or "").strip(),
             (normalized_fact or "").strip(),
             start_offset, end_offset,
             confidence, created_by_agent),
        )
        conn.commit()
        span_id = cur.lastrowid
        conn.close()
        return span_id
    except Exception:
        return -1


def get_evidence_for_field(db_path: str, field_key: str,
                           company_key: str = "") -> list[dict]:
    """获取某字段的所有证据片段。"""
    try:
        conn = _get_db(db_path)
        if company_key:
            rows = conn.execute(
                """SELECT es.*, sd.title as doc_title, sd.source_url,
                   sd.trust_tier
                   FROM evidence_spans es
                   LEFT JOIN source_documents sd ON es.document_id = sd.id
                   WHERE es.field_key=? AND es.company_key=?
                   ORDER BY es.confidence DESC""",
                (field_key, company_key),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT es.*, sd.title as doc_title, sd.source_url,
                   sd.trust_tier
                   FROM evidence_spans es
                   LEFT JOIN source_documents sd ON es.document_id = sd.id
                   WHERE es.field_key=?
                   ORDER BY es.confidence DESC""",
                (field_key,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def count_evidence_for_field(db_path: str, field_key: str,
                             company_key: str) -> int:
    """返回某字段绑定的证据数量。"""
    try:
        conn = _get_db(db_path)
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM evidence_spans
               WHERE field_key=? AND company_key=?""",
            (field_key, company_key),
        ).fetchone()
        conn.close()
        return row["cnt"] if row else 0
    except Exception:
        return 0


def build_evidence_map(db_path: str, company_key: str,
                       field_keys: list[str]) -> dict[str, list[int]]:
    """批量构建 {field_key: [span_id, ...]} 映射。

    用于 FieldResolver 的证据绑定检查。
    P0: 排除 posthoc_weak_matcher 创建的弱证据（不得进入 confirmed 判定）。
    """
    evidence_map: dict[str, list[int]] = {}
    if not company_key or not field_keys:
        return evidence_map
    try:
        conn = _get_db(db_path)
        placeholders = ", ".join("?" for _ in field_keys)
        rows = conn.execute(
            f"""SELECT field_key, id, created_by_agent, confidence FROM evidence_spans
                WHERE company_key=? AND field_key IN ({placeholders})
                AND (created_by_agent NOT IN ('posthoc_weak_matcher') OR created_by_agent IS NULL)
                AND confidence >= 0.35
                ORDER BY confidence DESC""",
            [company_key] + field_keys,
        ).fetchall()
        for r in rows:
            fk = r["field_key"]
            evidence_map.setdefault(fk, []).append(r["id"])
        conn.close()
    except Exception:
        pass
    return evidence_map
