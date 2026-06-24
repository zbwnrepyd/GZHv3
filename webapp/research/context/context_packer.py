"""上下文打包器 — 按字段预算从 document_chunks 中召回、打包上下文

职责：
1. 从 document_chunks 中按 field_key 召回高分 chunk
2. 排除 is_noise=1 的 chunk
3. 每个 source_url 最多 3 个 chunk
4. 按 final_score 降序排列，填充直到预算用完
5. 写 packed_context_logs

核心保证：
- 任何 LLM 调用 used_tokens <= budget_tokens
- raw_text 不直接进入 LLM（只传 chunk_text）
- RAW_TEXT_IN_LLM_ENABLED=0 时，打包结果严禁包含 raw_text 字段
"""
from __future__ import annotations
import json
import os
import sqlite3
from typing import Optional

from .token_budget import (
    TokenBudget,
    estimate_tokens,
    get_field_budget,
    get_field_max_chunks,
    BUDGET_PRESETS,
)

# ── RAW_TEXT 安全开关 ──
_RAW_TEXT_IN_LLM_ENABLED = os.environ.get("RAW_TEXT_IN_LLM_ENABLED", "0") == "1"

# chunk 返回字段白名单：严禁 raw_text 进入 LLM 上下文
_CHUNK_OUTPUT_KEYS = {
    "id", "chunk_text", "chunk_type", "source_type",
    "source_url", "title", "token_estimate", "final_score",
}

# 英→中翻译开关（默认开启）
import os as _os
_TRANSLATE_ENABLED = _os.environ.get("TRANSLATE_CONTEXT_TO_CHINESE", "1") == "1"


def _is_predominantly_english(text: str) -> bool:
    """检测 text 是否以英文为主（需翻译）。CJK 字符占比高则跳过。"""
    if not text:
        return False
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '぀' <= c <= 'ヿ')
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    total = cjk + latin
    if total == 0:
        return True
    return (latin / total) > 0.6  # >60% 拉丁字母 → 判定为英文

# ── 来源类型比例上限（占上下文 token 总数的比例）──
_SOURCE_TYPE_CAP: dict[str, float] = {
    "community": 0.10,
    "social_media": 0.10,
    "youtube_transcript": 0.25,
    "unknown": 0.15,
}


def _get_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_chunks_from_db(
    db_path: str,
    company_key: str,
    field_key: str = "",
    limit: int = 200,
) -> list[dict]:
    """从 document_chunks 表加载已评分 chunk。"""
    try:
        conn = _get_db(db_path)
        # 检查表是否存在
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'"
        ).fetchone()
        if not exists:
            conn.close()
            return []

        if field_key:
            # 按 field_relevance 召回
            rows = conn.execute(
                """SELECT * FROM document_chunks
                   WHERE company_key=? AND is_noise=0
                   AND (matched_fields LIKE ? OR matched_fields IS NULL)
                   ORDER BY final_score DESC
                   LIMIT ?""",
                (company_key, f"%{field_key}%", limit),
            ).fetchall()
        else:
            # 无字段限制
            rows = conn.execute(
                """SELECT * FROM document_chunks
                   WHERE company_key=? AND is_noise=0
                   ORDER BY final_score DESC
                   LIMIT ?""",
                (company_key, limit),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _load_evidence_spans(
    db_path: str,
    company_key: str,
    field_key: str = "",
) -> list[dict]:
    """加载已有 evidence_spans。"""
    try:
        conn = _get_db(db_path)
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='evidence_spans'"
        ).fetchone()
        if not exists:
            conn.close()
            return []

        if field_key:
            rows = conn.execute(
                """SELECT es.*, sd.source_url, sd.title as doc_title
                   FROM evidence_spans es
                   JOIN source_documents sd ON es.document_id = sd.id
                   WHERE es.company_key=? AND es.field_key=?
                   ORDER BY es.confidence DESC
                   LIMIT 20""",
                (company_key, field_key),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT es.*, sd.source_url, sd.title as doc_title
                   FROM evidence_spans es
                   JOIN source_documents sd ON es.document_id = sd.id
                   WHERE es.company_key=?
                   ORDER BY es.confidence DESC
                   LIMIT 100""",
                (company_key,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _log_packed_context(
    db_path: str,
    company_key: str,
    target_type: str,
    target_key: str,
    budget_tokens: int,
    used_tokens: int,
    chunk_ids: list[int],
    evidence_span_ids: list[int],
    dropped_count: int,
    run_id: str = "",
):
    """写 packed_context_logs 记录。"""
    try:
        conn = _get_db(db_path)
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='packed_context_logs'"
        ).fetchone()
        if not exists:
            conn.close()
            return
        conn.execute(
            """INSERT INTO packed_context_logs
               (run_id, company_key, target_type, target_key,
                budget_tokens, used_tokens, chunk_ids, evidence_span_ids,
                dropped_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id or "", company_key, target_type, target_key,
             budget_tokens, used_tokens,
             json.dumps(chunk_ids), json.dumps(evidence_span_ids),
             dropped_count),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def pack_context(
    db_path: str,
    company_key: str,
    target_type: str = "l0",
    target_key: str = "",
    budget_tokens: int | None = None,
    max_chunks: int | None = None,
    source_policy: dict | None = None,
    manifest_entry: dict | None = None,
    run_id: str = "",
) -> dict:
    """按预算打包上下文。

    Args:
        db_path: 数据库路径
        company_key: 公司标识
        target_type: l0 | field | analysis | card
        target_key: 目标 key（l0 时为 "l0_full"，field 时为 field_key）
        budget_tokens: token 预算上限（None 则按 target_type 自动选择）
        max_chunks: 最大 chunk 数（None 则按类型自动选择）
        source_policy: 可选，来源策略配置
        manifest_entry: 可选，field_manifest 条目
        run_id: 可选，关联的研究 run

    Returns:
        {
            "company_key": str,
            "target_type": str,
            "target_key": str,
            "budget_tokens": int,
            "used_tokens": int,
            "chunks": [dict],                # 打包的 chunk 列表
            "evidence_spans": [dict],         # 关联的 evidence_spans
            "evidence_span_ids": [int],       # evidence_span ID 列表
            "dropped_count": int,
            "source_breakdown": dict,         # 来源类型分布
        }
    """
    # ── 确定预算 ──
    if budget_tokens is None:
        if target_type == "l0":
            budget_tokens = BUDGET_PRESETS["l0_standard"]
        elif target_type == "field" and target_key:
            budget_tokens = get_field_budget(target_key, manifest_entry)
        elif target_type == "analysis":
            budget_tokens = BUDGET_PRESETS["field_analysis"]
        elif target_type == "card":
            budget_tokens = BUDGET_PRESETS["card_default"]
        else:
            budget_tokens = BUDGET_PRESETS["field_default"]

    if max_chunks is None:
        if target_type == "field" and target_key:
            max_chunks = get_field_max_chunks(target_key, manifest_entry)
        elif target_type == "l0":
            max_chunks = 60  # L0 可以多一些，但也会被 token 预算截断
        else:
            max_chunks = BUDGET_PRESETS["max_chunks_per_field"]

    # ── 加载数据 ──
    # 1. 加载 chunks
    field_key = target_key if target_type == "field" else ""
    all_chunks = _load_chunks_from_db(db_path, company_key, field_key, limit=300)

    # 2. 加载 evidence_spans
    all_spans = _load_evidence_spans(db_path, company_key, field_key)

    # ── 打包 ──
    budget = TokenBudget(budget_tokens)
    selected_chunks = []
    selected_span_ids = []
    source_type_counts: dict[str, int] = {}
    source_type_token_counts: dict[str, int] = {}

    # 预过滤：排除 is_noise=1 和 final_score < 0.35
    qualified = [
        c for c in all_chunks
        if not c.get("is_noise")
        and c.get("final_score", 0) >= 0.35
    ]

    # 按 final_score 降序排列
    qualified.sort(key=lambda c: c.get("final_score", 0), reverse=True)

    # 逐 chunk 尝试添加
    for chunk in qualified:
        if len(selected_chunks) >= max_chunks:
            break

        st = chunk.get("source_type", "unknown")

        # 来源类型比例检查
        if st in _SOURCE_TYPE_CAP:
            current_ratio = source_type_token_counts.get(st, 0) / max(budget.used_tokens, 1)
            if current_ratio >= _SOURCE_TYPE_CAP[st] and budget.used_tokens > 0:
                continue

        if not budget.can_add(chunk.get("token_estimate", 0)):
            continue

        if budget.add_chunk(chunk):
            selected_chunks.append(chunk)
            source_type_counts[st] = source_type_counts.get(st, 0) + 1
            source_type_token_counts[st] = (
                source_type_token_counts.get(st, 0) + chunk.get("token_estimate", 0)
            )

    # 关联 evidence_spans（只取与选中 chunk 的 document_id 匹配的）
    selected_doc_ids = {c["document_id"] for c in selected_chunks}
    for span in all_spans:
        if span.get("document_id") in selected_doc_ids:
            selected_span_ids.append(span["id"])

    # 限制 evidence_span 数量
    if len(selected_span_ids) > BUDGET_PRESETS["max_evidence_per_field"]:
        selected_span_ids = selected_span_ids[:BUDGET_PRESETS["max_evidence_per_field"]]

    dropped = len(qualified) - len(selected_chunks)

    # ── 写日志 ──
    chunk_ids = [c["id"] for c in selected_chunks]
    _log_packed_context(
        db_path, company_key, target_type, target_key,
        budget_tokens, budget.used_tokens,
        chunk_ids, selected_span_ids, dropped,
        run_id=run_id,
    )

    # ── 构建返回 ──
    packed_chunks = []
    for c in selected_chunks:
        # SPEC: 白名单过滤，严禁 raw_text 泄漏到 LLM 上下文
        chunk_out = {k: v for k, v in c.items() if k in _CHUNK_OUTPUT_KEYS}
        packed_chunks.append(chunk_out)

    # 安全断言：当 RAW_TEXT_IN_LLM_ENABLED=0 时，验证无 raw_text 泄漏
    if not _RAW_TEXT_IN_LLM_ENABLED:
        for ch in packed_chunks:
            if "raw_text" in ch:
                raise RuntimeError(
                    "RAW_TEXT_IN_LLM_ENABLED=0 but raw_text found in packed chunk. "
                    "This is a safety violation — raw_text must never enter LLM context."
                )

    # ── 英→中翻译（仅翻译已入选预算的 chunk，最小化 token 成本）──
    if _TRANSLATE_ENABLED:
        try:
            translate_indices = []
            texts_to_translate = []
            for idx, ch in enumerate(packed_chunks):
                text = ch.get("chunk_text", "")
                if _is_predominantly_english(text):
                    translate_indices.append(idx)
                    texts_to_translate.append(text)

            if texts_to_translate:
                from deepseek_client import translate_to_chinese
                translated = translate_to_chinese(texts_to_translate)
                for list_idx, packed_idx in enumerate(translate_indices):
                    if list_idx < len(translated):
                        packed_chunks[packed_idx]["chunk_text"] = translated[list_idx]
        except Exception as e:
            print(f"[context_packer] translation failed (non-fatal): {e}")

    return {
        "company_key": company_key,
        "target_type": target_type,
        "target_key": target_key,
        "budget_tokens": budget_tokens,
        "used_tokens": budget.used_tokens,
        "chunks": packed_chunks,
        "evidence_spans": [
            {k: v for k, v in s.items()
             if k in ("id", "field_key", "quote_text", "confidence",
                       "doc_title", "source_url")}
            for s in all_spans
            if s["id"] in selected_span_ids
        ],
        "evidence_span_ids": selected_span_ids,
        "dropped_count": dropped,
        "source_breakdown": {
            "counts": source_type_counts,
            "token_counts": source_type_token_counts,
        },
    }
