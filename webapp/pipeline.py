"""研究流水线：4路并行采集 → 4层LLM分析 → 写库"""
from __future__ import annotations
import copy
import json, os, re, sys, time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Optional
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from company_identity import build_company_identity
from search_plan import build_search_plan
from evidence_pool import (
    normalize_url, EvidenceItem, source_score as evidence_source_score,
    entity_score as evidence_entity_score, final_score as evidence_final_score,
    dedupe_evidence, filter_evidence, metric_snippet,
)
from gap_detector import detect_gaps, build_gap_queries
# ── 上下文治理层 (Goal 三) ──
from services.context_packer import ContextPacker, RawTextNotAllowedError
from services.document_chunker import chunk as chunk_document
from services.context_ranker import rank as rank_chunks
from services.budget_manager import (
    get_budget, is_governance_enabled, is_legacy_mode,
    LEGACY_CONTEXT_MODE, DOCUMENT_CHUNKING_ENABLED, CONTEXT_PACKER_ENABLED,
)

from config import config
from deepseek_client import call_deepseek, load_prompt
from firecrawl_local import scrape_url
from field_rules import run_rule_layer
from field_validator import validate_enum_fields
import db as database

# ── 噪音与上下文治理 ──
from research.context import (
    clean_document_text, chunk_document,
    score_chunks_batch, pack_context,
    TokenBudget, BUDGET_PRESETS, estimate_tokens,
)

# ── P1: 字段驱动采集 ──
from research.field_driven_source_planner import (
    FieldDrivenSourcePlanner, build_source_plan,
)
from research.source_adapter import ADAPTER_REGISTRY

# ── L0 质量门控 ──
from research.l0_gate import validate_l0_output, L0GateError

_REQUIRED_FIELDS = database.REQUIRED_RESEARCH_FIELDS

_SOURCE_LABELS = {
    "scrapling_search": "开放网页搜索",
    "tavily": "Tavily 搜索",
    "tavily_search": "Tavily 搜索",
    "tavily_extract": "Tavily 深抓",
    "github": "GitHub",
    "youtube": "YouTube",
    "youtube_transcript": "YouTube",
    "official_site": "官网抓取",
    "website": "官网抓取",
    "producthunt": "Product Hunt",
    "sec": "SEC",
    "openbb": "OpenBB",
    "companieshouse": "Companies House",
    "whatweb": "WhatWeb",
}

_TAVILY_RESULT_FIELDS = ("title", "url", "content", "score", "raw_content")
_TAVILY_RAW_CONTENT_LIMIT = 2400
_TAVILY_QUERY_CACHE: dict[tuple, tuple[float, dict]] = {}
_ADAPTER_MODULE_BY_FAMILY = {
    "official_site": "official_site_adapter",
    "scrapling_search": "scrapling_search_adapter",
    "tavily_search": "tavily_search_adapter",
    "tavily_extract": "tavily_extract_adapter",
    "github": "github_adapter",
    "producthunt": "producthunt_adapter",
    "youtube": "youtube_transcript_adapter",
    "sec": "sec_adapter",
    "openbb": "openbb_adapter",
    "companieshouse": "companieshouse_adapter",
    "whatweb": "whatweb_adapter",
}
_ADAPTER_CLASS_BY_FAMILY = {
    "official_site": "OfficialSiteAdapter",
    "scrapling_search": "ScraplingSearchAdapter",
    "tavily_search": "TavilySearchAdapter",
    "tavily_extract": "TavilyExtractAdapter",
    "github": "GithubAdapter",
    "producthunt": "ProductHuntAdapter",
    "youtube": "YoutubeTranscriptAdapter",
    "sec": "SecAdapter",
    "openbb": "OpenBBAdapter",
    "companieshouse": "CompaniesHouseAdapter",
    "whatweb": "WhatWebAdapter",
}
_PRIVATE_FIELD_KEYS = {
    "ltv", "cac", "ltv_cac_ratio", "arr", "mrr", "revenue",
    "gross_margin", "burn_rate", "retention_rate", "churn_rate",
}
_FIRST_PHASE_ADAPTERS = (
    "official_site",
    "scrapling_search",
    "github",
    "youtube",
    "producthunt",
    "whatweb",
)
_SUPPLEMENTAL_ADAPTER_FIELDS = {
    "github": [
        "product_tech_stack", "core_competency", "company_achievements",
        "main_product_name", "product_core_features",
    ],
    "youtube": [
        "founder_name", "founder_bg", "founder_achievement",
        "main_product_name", "product_core_features", "funding_info",
    ],
    "producthunt": [
        "main_product_name", "product_core_features", "company_achievements",
        "pricing_summary", "customer_segment",
    ],
    "openbb": [
        "company_revenue", "revenue_metrics", "growth_metrics",
        "gross_margin", "runway_months",
    ],
    "whatweb": [
        "product_tech_stack", "tech_stack", "core_competency",
    ],
}
_GAP_INTENT_PRIORITY = [
    "market_size",
    "unit_economics",
    "revenue_metrics",
    "user_metrics",
    "retention_metrics",
    "pricing_details",
    "customers",
    "competitive_position",
    "founders",
    "funding",
    "product_v3",
    "company_profile_v3",
    "differentiated_opportunity",
]


class PipelineCancelledError(RuntimeError):
    """用户主动取消研究流水线。"""


def _report(progress_callback, stage: str, detail: str = "", job_id: str = None):
    if progress_callback:
        progress_callback(stage, detail)
    if job_id:
        try:
            import db as _db
            from config import config as _cfg
            _db.update_job(_cfg.DB_PATH_RESEARCH, job_id, stage=stage, detail=_detail_text(detail))
        except Exception:
            pass


def _detail_text(detail) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or "")
    return str(detail or "")


def _is_cancelled(cancel_token) -> bool:
    return bool(callable(cancel_token) and cancel_token())


def _adapter_query_count(entry: dict) -> int:
    budget = entry.get("budget") or {}
    return int(budget.get("max_queries", budget.get("max_urls", budget.get("max_documents", 0))) or 0)


def _public_field_targets(card_fields: list[str]) -> list[str]:
    return [field for field in card_fields if field not in _PRIVATE_FIELD_KEYS]


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_field_contract_keys() -> list[str]:
    contract_path = os.path.join(_project_root(), "contracts", "fields.json")
    try:
        with open(contract_path, encoding="utf-8") as f:
            contract = json.load(f)
    except Exception:
        return list(dict.fromkeys(getattr(database, "RESEARCH_SAVE_FIELDS", _REQUIRED_FIELDS)))

    keys = []
    for group in contract.get("groups", []):
        for field in group.get("fields", []):
            key = field.get("field_key")
            if key and key not in keys:
                keys.append(key)
    return keys


def _load_required_field_contract_keys() -> list[str]:
    contract_path = os.path.join(_project_root(), "contracts", "fields.json")
    try:
        with open(contract_path, encoding="utf-8") as f:
            contract = json.load(f)
    except Exception:
        return []

    keys = []
    for group in contract.get("groups", []):
        for field in group.get("fields", []):
            if field.get("deprecated"):
                continue
            key = field.get("field_key")
            if key and field.get("required") is True and key not in keys:
                keys.append(key)
    return keys


def _extract_contract_field_values(record: dict) -> dict[str, object]:
    contract_keys = set(_load_field_contract_keys())
    skip_keys = {"version"}
    return {
        key: value
        for key, value in (record or {}).items()
        if key in contract_keys and key not in skip_keys
    }


def _evaluate_l3_value_gaps(record: dict) -> dict:
    """Evaluate L3 value gaps before evidence/status resolution is available."""
    field_values = _extract_contract_field_values(record)
    usable_fields = {
        key: value for key, value in field_values.items()
        if not _is_missing_value(value)
    }
    identity_fields = {"company_name", "website_url"}
    usable_content_fields = {
        key: value for key, value in usable_fields.items()
        if key not in identity_fields
    }
    if not usable_content_fields:
        version = (record or {}).get("version", "standard")
        raise RuntimeError(f"L3 {version} 版未返回任何可用契约字段")

    required_fields = _load_required_field_contract_keys()
    missing_required = [
        key for key in required_fields
        if _is_missing_value(field_values.get(key))
    ]
    return {
        "should_refetch": bool(missing_required),
        "missing_required_fields": missing_required,
        "field_count": len(field_values),
        "usable_field_count": len(usable_fields),
        "usable_content_field_count": len(usable_content_fields),
    }


def _fields_from_card_config(config_json: str) -> list[str]:
    try:
        config_data = json.loads(config_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return []
    return [
        field for field in config_data.get("fields", [])
        if isinstance(field, str) and field.strip()
    ]


def _load_card_set_field_targets(set_keys: tuple[str, ...] = ("v1", "v2", "v3")) -> list[str]:
    fields = []
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH_COMPOSITION)
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in set_keys)
        rows = conn.execute(
            f"""SELECT config_json FROM default_card_configs
                WHERE set_key IN ({placeholders})
                ORDER BY set_key, card_index""",
            set_keys,
        ).fetchall()
        conn.close()
        for row in rows:
            for field in _fields_from_card_config(row["config_json"]):
                if field not in fields:
                    fields.append(field)
    except Exception:
        fields = []

    if fields:
        return fields

    # Fallback for fresh or damaged composition DBs: parse the checked-in seed SQL.
    sql_path = os.path.join(_project_root(), "db", "init_composition_db.sql")
    try:
        with open(sql_path, encoding="utf-8") as f:
            content = f.read()
        for set_key in set_keys:
            pattern = rf"\('{set_key}',\s*'[^']*',\s*\d+,\s*'[^']*',\s*'(\{{.*?\}})'\)"
            for match in re.finditer(pattern, content):
                for field in _fields_from_card_config(match.group(1)):
                    if field not in fields:
                        fields.append(field)
    except Exception:
        fields = []

    return fields or _load_field_contract_keys()


def _complete_contract_fields(record: dict) -> dict:
    completed = dict(record)
    for field in _load_field_contract_keys():
        val = completed.get(field)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            completed[field] = "暂缺"
    return completed


def _upsert_adapter_plan(source_plan, adapter_family: str, field_targets: list[str],
                         budget: dict, priority: str = "medium",
                         prepend: bool = False) -> None:
    fields = [field for field in field_targets if field]
    for entry in source_plan.adapters:
        if entry.get("adapter_family") != adapter_family:
            continue
        existing_fields = list(entry.get("field_targets") or [])
        for field in fields:
            if field not in existing_fields:
                existing_fields.append(field)
        entry["field_targets"] = existing_fields
        entry["budget"] = {**(entry.get("budget") or {}), **(budget or {})}
        entry["priority"] = priority or entry.get("priority") or "medium"
        return

    adapter_entry = {
        "adapter_family": adapter_family,
        "field_targets": fields,
        "budget": budget or {},
        "priority": priority,
    }
    if prepend:
        source_plan.adapters.insert(0, adapter_entry)
    else:
        source_plan.adapters.append(adapter_entry)


def _apply_research_options_to_source_plan(source_plan, card_fields: list[str],
                                           research_options: dict | None):
    options = research_options or {}
    # Tavily 只作为本机/开放网页第一轮后的补缺口路径，不进入初始 adapter 计划。
    source_plan.adapters = [
        entry for entry in source_plan.adapters
        if entry.get("adapter_family") not in ("tavily_search", "tavily_extract")
    ]
    disabled_adapters = {
        key for key, enabled in options.items()
        if enabled is False and key in _ADAPTER_MODULE_BY_FAMILY
    }
    if disabled_adapters:
        source_plan.adapters = [
            entry for entry in source_plan.adapters
            if entry.get("adapter_family") not in disabled_adapters
        ]
        for field_key, families in list(source_plan.field_to_source_map.items()):
            source_plan.field_to_source_map[field_key] = [
                family for family in families if family not in disabled_adapters
                and family not in ("tavily_search", "tavily_extract")
            ]

    public_fields = _public_field_targets(card_fields)
    if options.get("official_site", True):
        _upsert_adapter_plan(
            source_plan,
        "official_site",
        public_fields,
        {"max_urls": 5, "max_documents": 5, "timeout_seconds": 30, "hard_timeout_seconds": 180},
        priority="high",
        prepend=True,
    )
    if options.get("scrapling_search"):
        _upsert_adapter_plan(
            source_plan,
            "scrapling_search",
            public_fields,
            {"max_queries": 30, "max_documents": 20,
             "timeout_seconds": 10, "enabled": True,
             "hard_timeout_seconds": 300},
            priority="high",
            prepend=True,
        )
    for family, fields in _SUPPLEMENTAL_ADAPTER_FIELDS.items():
        if options.get(family, True):
            _upsert_adapter_plan(
                source_plan,
                family,
                [field for field in fields if field in card_fields] or public_fields[:8],
                {"max_queries": 3, "max_documents": 3, "timeout_seconds": 20},
                priority="medium",
                prepend=False,
            )
    source_plan.adapters.sort(
        key=lambda entry: (
            0 if entry.get("adapter_family") in _FIRST_PHASE_ADAPTERS else 1,
            _FIRST_PHASE_ADAPTERS.index(entry.get("adapter_family"))
            if entry.get("adapter_family") in _FIRST_PHASE_ADAPTERS else 99,
        )
    )
    source_plan.total_estimated_queries = sum(
        _adapter_query_count(entry) for entry in source_plan.adapters
    )
    return source_plan


def _load_adapter_instance(family: str):
    module_name = _ADAPTER_MODULE_BY_FAMILY.get(family, f"{family}_adapter")
    class_name = _ADAPTER_CLASS_BY_FAMILY.get(
        family,
        f"{family.title().replace('_', '')}Adapter",
    )
    mod = __import__(f"research.adapters.{module_name}", fromlist=[class_name])
    adapter_cls = getattr(mod, class_name, None)
    if adapter_cls is None:
        raise RuntimeError(f"adapter class not found: {class_name}")
    return adapter_cls()


def _execute_adapter_instances(adapter_instances: list[dict], identity_dict: dict,
                               cancel_token=None, progress_callback=None,
                               job_id: str = "") -> tuple[list, dict]:
    all_docs = []
    source_summary = {}
    if not adapter_instances:
        return all_docs, source_summary

    ex = ThreadPoolExecutor(max_workers=min(4, len(adapter_instances)))
    futures = {}
    # Per-adapter hard timeout (default 120s, from budget or env)
    _ADAPTER_HARD_TIMEOUT = float(os.environ.get("ADAPTER_HARD_TIMEOUT_SECONDS", "120"))
    _started_at: dict = {}
    cancelled = False
    timed_out = False
    try:
        for inst in adapter_instances:
            if _is_cancelled(cancel_token):
                cancelled = True
                raise PipelineCancelledError("用户取消研究")
            entry = inst["entry"]
            family = entry["adapter_family"]
            source_summary.setdefault(family, {
                "status": "collecting",
                "count": 0,
                "detail": "采集中...",
            })
            future = ex.submit(
                inst["adapter"].collect,
                identity_dict,
                entry["field_targets"],
                entry["budget"],
            )
            futures[future] = inst
            _started_at[future] = time.time()

        pending = set(futures)
        while pending:
            if _is_cancelled(cancel_token):
                cancelled = True
                for future in pending:
                    future.cancel()
                raise PipelineCancelledError("用户取消研究")

            # Hard timeout: cancel adapters that exceed the budget
            now = time.time()
            for future in list(pending):
                inst = futures[future]
                budget = inst["entry"].get("budget") or {}
                hard_timeout = float(budget.get("hard_timeout_seconds", _ADAPTER_HARD_TIMEOUT))
                if now - _started_at.get(future, now) > hard_timeout:
                    timed_out = True
                    future.cancel()
                    family = inst["entry"]["adapter_family"]
                    source_summary[family] = {
                        "status": "failed",
                        "count": 0,
                        "detail": f"超时（>{hard_timeout:g}s）",
                    }
                    pending.discard(future)

            if not pending:
                break

            done, pending = wait(
                pending,
                timeout=0.2,
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                inst = futures[future]
                family = inst["entry"]["adapter_family"]
                adapter = inst["adapter"]
                try:
                    docs = future.result(timeout=5)
                    if docs:
                        adapter_summary = getattr(adapter, "last_summary", None)
                        all_docs.extend(docs)
                        source_summary[family] = {
                            "status": "ok",
                            "count": len(docs),
                            "detail": f"{len(docs)} documents",
                            **(adapter_summary if isinstance(adapter_summary, dict) else {}),
                        }
                    else:
                        adapter_summary = getattr(adapter, "last_summary", None)
                        if isinstance(adapter_summary, dict) and adapter_summary:
                            source_summary[family] = adapter_summary
                        else:
                            source_summary[family] = {
                                "status": "empty",
                                "count": 0,
                                "detail": "已运行，未获得有效文档",
                            }
                except Exception as e:
                    source_summary[family] = {
                        "status": "failed",
                        "count": 0,
                        "detail": str(e)[:220],
                    }
    finally:
        if cancelled:
            ex.shutdown(wait=False, cancel_futures=True)
        elif timed_out:
            ex.shutdown(wait=False, cancel_futures=True)
        else:
            ex.shutdown(wait=True)
    return all_docs, source_summary


# ── Step 1: 4路并行采集 ──────────────────────────

def _query_attr(q, name: str, default=None):
    if hasattr(q, name):
        return getattr(q, name)
    if isinstance(q, dict):
        return q.get(name, default)
    return default


def _search_tavily(queries, progress_callback=None, job_id: str = None) -> list:
    """Multi-query Tavily search. Each query is a TavilyQuery or dict with query/intent.
    Backward-compatible: if a string is passed, wraps it as a single query."""
    if isinstance(queries, str):
        # Backward-compatible: old API with company_name string → 2 queries
        queries = [
            {"query": f"{queries} AI startup overview funding founders",
             "intent": "overview"},
            {"query": f"{queries} AI company news competitors product",
             "intent": "competitors"},
        ]
    batches = []
    total = len(queries)
    for q in queries:
        query_str = _query_attr(q, "query", str(q))
        intent = _query_attr(q, "intent", "")
        search_depth = _query_attr(q, "search_depth")
        include_raw_content = _query_attr(q, "include_raw_content")
        try:
            result = _search_tavily_query(
                query_str,
                search_depth=search_depth,
                include_raw_content=include_raw_content,
            )
            result["_query"] = query_str
            result["_intent"] = intent
            batches.append(result)
        except Exception as e:
            batches.append({"error": str(e), "_query": query_str,
                           "_intent": intent, "results": []})
        if progress_callback:
            summary = _summarize_collection_source("tavily", batches)
            summary["status"] = "collecting" if len(batches) < total else summary["status"]
            summary["detail"] = f"{len(batches)}/{total} 组查询，{summary['detail']}"
            _report(progress_callback, "采集", {
                "message": f"Tavily 搜索中：{summary['detail']}",
                "sources": {"tavily": summary},
            }, job_id=job_id)
    return batches


def _tavily_keys() -> list[str]:
    keys = getattr(config, "TAVILY_API_KEYS", None)
    if keys:
        return keys
    return [config.TAVILY_API_KEY] if config.TAVILY_API_KEY else []


def _is_tavily_quota_response(resp) -> bool:
    text = getattr(resp, "text", "") or ""
    return resp.status_code in (429, 432) or "usage limit" in text.lower() or "quota" in text.lower()


def _tavily_error_text(resp) -> str:
    try:
        data = resp.json()
        detail = data.get("detail") if isinstance(data, dict) else None
        if isinstance(detail, dict):
            return str(detail.get("error") or detail)
        if detail:
            return str(detail)
    except Exception:
        pass
    return f"HTTP {resp.status_code}"


def _tavily_proxy() -> dict | None:
    """读取 .env 中的代理配置，用于 requests 显式传参"""
    import os
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
    if proxy_url:
        return {"http": proxy_url, "https": proxy_url}
    return None


def _search_tavily_query(query: str, include_images: bool = False,
                         search_depth: Optional[str] = None,
                         include_raw_content: Optional[bool] = None):
    keys = _tavily_keys()
    if not keys:
        return {"error": "TAVILY_API_KEYS not configured", "results": []}

    depth = search_depth or getattr(config, "TAVILY_SEARCH_DEPTH", "basic")
    include_raw = (
        bool(include_raw_content)
        if include_raw_content is not None
        else bool(getattr(config, "TAVILY_INCLUDE_RAW_CONTENT", False))
    )
    max_results = int(getattr(config, "TAVILY_RESULTS_PER_QUERY", 5))
    cache_ttl = int(getattr(config, "TAVILY_CACHE_TTL_SECONDS", 0) or 0)
    cache_key = (query, bool(include_images), depth, include_raw, max_results)
    if cache_ttl > 0:
        cached = _TAVILY_QUERY_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < cache_ttl:
            return copy.deepcopy(cached[1])

    last_error = ""
    for index, api_key in enumerate(keys):
        try:
            body = {
                "api_key": api_key,
                "query": query,
                "search_depth": depth,
                "include_answer": True,
                "include_raw_content": include_raw,
                "max_results": max_results,
            }
            if include_images:
                body["include_images"] = True
                body["max_results"] = max_results
            resp = requests.post(
                "https://api.tavily.com/search",
                json=body,
                timeout=(30, 120),
                proxies=_tavily_proxy(),
            )
            if resp.status_code >= 400:
                last_error = _tavily_error_text(resp)
                if _is_tavily_quota_response(resp) and index < len(keys) - 1:
                    continue
                return {"error": last_error, "results": []}
            data = resp.json()
            if cache_ttl > 0:
                _TAVILY_QUERY_CACHE[cache_key] = (time.time(), copy.deepcopy(data))
            return data
        except Exception as e:
            last_error = str(e)
            # 超时也尝试下一个 key
            if index < len(keys) - 1:
                continue
    return {"error": last_error or "Tavily request failed", "results": []}


def _merge_tavily_results(raw: dict, supplement: list) -> None:
    """合并 Tavily 补充结果到 raw['tavily'] 列表。"""
    existing = raw.get("tavily", [])
    raw["tavily"] = existing + supplement if isinstance(existing, list) else supplement


def _needs_pre_gap_refetch(raw: dict) -> bool:
    src = raw.get("_source_summary", {}) if isinstance(raw, dict) else {}
    tavily_src = src.get("tavily", {}) or {}
    website_src = src.get("website", {}) or {}
    github_src = src.get("github", {}) or {}
    youtube_src = src.get("youtube", {}) or {}
    website_chars = int(website_src.get("count", 0) or 0)
    website_enough = website_src.get("status") == "ok" and website_chars >= getattr(config, "COLLECTION_WEBSITE_SUFFICIENT_CHARS", 1500)
    secondary_enough = int(github_src.get("count", 0) or 0) > 0 or int(youtube_src.get("count", 0) or 0) > 0
    if website_enough and secondary_enough:
        return False
    unique_urls = int(tavily_src.get("unique_url_count", 0) or 0)
    intents_found = int(tavily_src.get("intent_count", 0) or 0)
    return unique_urls < int(getattr(config, "COLLECTION_MIN_UNIQUE_URLS", 18)) or intents_found < 4


def _prioritize_gap_queries(gaps: dict[str, list[str]], display_name: str,
                            website_host: str, root_domain: str) -> list[dict]:
    ordered_intents = [intent for intent in _GAP_INTENT_PRIORITY if intent in gaps]
    ordered_intents.extend(intent for intent in gaps if intent not in ordered_intents)
    selected_gaps = {intent: gaps[intent] for intent in ordered_intents}
    queries = build_gap_queries(display_name, website_host, root_domain, selected_gaps)
    limit = int(getattr(config, "COLLECTION_GAP_QUERY_LIMIT", 5) or 5)
    result = []
    # First pass: one query per high-priority intent.
    for intent in ordered_intents:
        for query in queries:
            if query.get("intent") == intent:
                result.append(query)
                break
        if len(result) >= limit:
            return result
    # Second pass: fill remaining slots if limit allows.
    for query in queries:
        if len(result) >= limit:
            break
        if query not in result:
            result.append(query)
    return result


def _initial_tavily_queries(plan) -> list:
    if not getattr(config, "TAVILY_ADAPTIVE_MODE", True):
        return list(plan.tavily_queries)
    limit = int(getattr(config, "TAVILY_INITIAL_QUERY_LIMIT", 10) or 10)
    depth = getattr(config, "TAVILY_INITIAL_SEARCH_DEPTH", "basic")
    include_raw = bool(getattr(config, "TAVILY_INITIAL_INCLUDE_RAW_CONTENT", False))
    initial = []
    for q in list(plan.tavily_queries)[:limit]:
        initial.append({
            "query": q.query,
            "intent": q.intent,
            "term": q.term,
            "search_depth": depth,
            "include_raw_content": include_raw,
        })
    return initial


def _evaluate_collection_quality(raw: dict, evidence_items: Optional[list] = None) -> dict:
    src = raw.get("_source_summary", {}) if isinstance(raw, dict) else {}
    tavily_src = src.get("tavily", {}) or {}
    website_src = src.get("website", {}) or {}
    evidence_items = evidence_items or []
    intent_counts: dict[str, int] = {}
    for item in evidence_items:
        for intent in str(_query_attr(item, "intent", "") or "").split(","):
            intent = intent.strip()
            if intent:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
    key_intents = [
        "market_size", "pricing_details", "customers",
        "unit_economics", "competitive_position",
    ]
    missing_key_intents = [
        intent for intent in key_intents
        if intent_counts.get(intent, 0) == 0
    ]
    website_chars = int(website_src.get("count", 0) or 0)
    unique_urls = int(tavily_src.get("unique_url_count", 0) or 0)
    min_urls = max(8, int(getattr(config, "COLLECTION_MIN_UNIQUE_URLS", 18) or 18))
    enough = (
        unique_urls >= min_urls
        and len(missing_key_intents) <= 2
    ) or (
        website_chars >= int(getattr(config, "COLLECTION_WEBSITE_SUFFICIENT_CHARS", 1500) or 1500)
        and len(missing_key_intents) <= 2
    )
    return {
        "enough": bool(enough),
        "unique_url_count": unique_urls,
        "website_chars": website_chars,
        "intent_counts": intent_counts,
        "missing_key_intents": missing_key_intents,
    }


def _build_escalation_queries(plan, quality_report: dict) -> list[dict]:
    if not getattr(config, "TAVILY_ADAPTIVE_MODE", True):
        return []
    missing = quality_report.get("missing_key_intents") or []
    if not missing:
        return []
    raw_intents = set(getattr(config, "TAVILY_ESCALATE_RAW_CONTENT_INTENTS", []) or [])
    depth = getattr(config, "TAVILY_ESCALATE_SEARCH_DEPTH", "advanced")
    default_raw = bool(getattr(config, "TAVILY_ESCALATE_INCLUDE_RAW_CONTENT", False))
    limit = int(getattr(config, "COLLECTION_GAP_QUERY_LIMIT", 5) or 5)
    rows = []
    seen = set()
    for intent in missing:
        for q in plan.tavily_queries:
            if q.intent != intent or q.query in seen:
                continue
            seen.add(q.query)
            rows.append({
                "query": q.query,
                "intent": q.intent,
                "term": q.term,
                "search_depth": depth,
                "include_raw_content": True if intent in raw_intents else default_raw,
            })
            break
        if len(rows) >= limit:
            break
    return rows


def _search_github(queries: list[str]) -> dict:
    """Multi-query GitHub search with dedup by repo id."""
    merged = []
    errors = []
    for q in (queries or [])[:4]:
        if not q.strip():
            continue
        try:
            resp = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": q, "sort": "stars", "per_page": 5},
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=(15, 45),
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    item["_query"] = q
                    merged.append(item)
            else:
                errors.append({"query": q, "error": resp.status_code})
        except Exception as e:
            errors.append({"query": q, "error": str(e)})

    seen = set()
    deduped = []
    for item in merged:
        rid = item.get("id")
        if rid and rid not in seen:
            seen.add(rid)
            deduped.append(item)
    return {"items": deduped, "errors": errors}


def _search_youtube(queries: list[str]) -> dict:
    """Multi-query YouTube search with dedup by video id + transcript fetch."""
    if not config.YOUTUBE_API_KEY:
        return {"items": [], "note": "no API key", "errors": []}

    merged = []
    errors = []
    for q in dict.fromkeys([x for x in (queries or []) if x.strip()]):
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": q,
                    "type": "video",
                    "maxResults": 5,
                    "key": config.YOUTUBE_API_KEY,
                },
                timeout=(15, 45),
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    item["_query"] = q
                    merged.append(item)
            else:
                errors.append({"query": q, "error": resp.status_code})
        except Exception as e:
            errors.append({"query": q, "error": str(e)})

    seen = set()
    deduped = []
    for item in merged:
        vid = (_vid_of(item) or "").strip()
        if vid and vid not in seen:
            seen.add(vid)
            deduped.append(item)

    # 抓取视频字幕/转录文本（youtube-transcript-api，无需 API Key）
    transcripts = _fetch_youtube_transcripts([_vid_of(i) for i in deduped if _vid_of(i)])
    for item in deduped:
        t = transcripts.get(_vid_of(item), "")
        if t:
            item["_transcript"] = t

    return {"items": deduped, "errors": errors}


def _vid_of(item: dict) -> str:
    vid = item.get("id", {})
    return (vid.get("videoId") or str(vid) or "") if isinstance(vid, dict) else str(vid or "")


def _fetch_youtube_transcripts(video_ids: list[str]) -> dict[str, str]:
    """批量抓取 YouTube 视频字幕，返回 {video_id: transcript_text}。无字幕则静默跳过。"""
    if not video_ids:
        return {}
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        _yt_api = YouTubeTranscriptApi()
    except (ImportError, Exception):
        return {}

    results = {}
    for vid in video_ids:
        if not vid or vid in results:
            continue
        try:
            fetched = _yt_api.fetch(vid, languages=['zh-Hans', 'zh', 'en', 'ja', 'ko'])
            # FetchedTranscript → .snippets → .text
            snippets = getattr(fetched, 'snippets', []) or []
            lines = []
            total = 0
            for seg in snippets:
                text = getattr(seg, 'text', '').strip()
                if not text or (text.startswith("[") and text.endswith("]")):
                    continue
                lines.append(text)
                total += len(text)
                if total > 3000:
                    lines.append("...")
                    break
            if lines:
                results[vid] = " ".join(lines)
        except Exception:
            pass
    return results


def _scrape_website(company_url: str):
    for attempt in range(3):
        result = scrape_url(company_url, timeout=30)
        if not result.get("error"):
            return result
        if attempt < 2:
            time.sleep(3)
    return result


def _crawl_official_site(company_url: str, company_key: str,
                         job_id: str = None) -> dict:
    """P1: 官网深爬 — 抓取 16 个关键路径并写入 source_documents。

    失败不阻塞主流程，返回抓取统计。
    """
    if not company_url:
        return {"pages": [], "count": 0, "error": "no URL"}
    try:
        from research_agents.agents.official_agent import crawl_and_store
        count = crawl_and_store(
            db_path=config.DB_PATH_RESEARCH,
            company_url=company_url,
            company_key=company_key,
            run_id=job_id or "",
            timeout=15,
        )
        return {"pages_crawled": count, "status": "ok" if count > 0 else "empty"}
    except Exception as e:
        return {"pages_crawled": 0, "status": "failed", "error": str(e)[:200]}


# _run_orchestrator_agents removed per SPEC Section 19.1 — not enabled by default.


def _summarize_collection_source(name: str, data) -> dict:
    label = _SOURCE_LABELS.get(name, name)
    summary = {
        "label": label,
        "status": "empty",
        "count": 0,
        "unit": "条",
        "detail": "未获得有效信息",
    }

    if name == "tavily":
        items = data if isinstance(data, list) else []
        count = sum(len(item.get("results", [])) for item in items if isinstance(item, dict))
        errors = [str(item.get("error")) for item in items if isinstance(item, dict) and item.get("error")]
        urls: set[str] = set()
        intents: set[str] = set()
        for item in items:
            if isinstance(item, dict) and not item.get("error"):
                intents.add(item.get("_intent", ""))
                for r in item.get("results", []):
                    u = r.get("url", "")
                    if u:
                        urls.add(normalize_url(u))
        summary.update({"count": count, "unit": "条结果",
                        "unique_url_count": len(urls), "intent_count": len(intents)})
        if count > 0:
            detail = f"{count}条结果，{len(urls)}个唯一URL，{len(intents)}类意图"
            if errors:
                detail += f"，部分查询失败：{errors[0][:40]}"
            summary.update({"status": "ok", "detail": detail})
        elif errors:
            summary.update({"status": "failed", "detail": errors[0]})
        return summary

    if name == "github":
        items = data.get("items", []) if isinstance(data, dict) else []
        errors = data.get("errors", []) if isinstance(data, dict) else []
        count = len(items)
        urls: set[str] = set()
        for item in items:
            u = item.get("html_url", "")
            if u:
                urls.add(normalize_url(u))
        err_msg = errors[0].get("error") if errors else (data.get("error") if isinstance(data, dict) else None)
        summary.update({"count": count, "unit": "个仓库",
                        "unique_url_count": len(urls),
                        "query_count": len(data.get("errors", [])) + (1 if count > 0 else 0) if isinstance(data, dict) else 0})
        if count > 0:
            summary.update({"status": "ok", "detail": f"找到 {count} 个仓库，{len(urls)} 个唯一"})
        elif err_msg:
            summary.update({"status": "failed", "detail": str(err_msg)})
        return summary

    if name == "youtube":
        items = data.get("items", []) if isinstance(data, dict) else []
        note = data.get("note") if isinstance(data, dict) else None
        errors = data.get("errors", []) if isinstance(data, dict) else []
        count = len(items)
        err_msg = errors[0].get("error") if errors else (data.get("error") if isinstance(data, dict) else None)
        summary.update({"count": count, "unit": "个视频",
                        "query_count": len(errors) + (1 if count > 0 else 0)})
        if count > 0:
            summary.update({"status": "ok", "detail": f"找到 {count} 个视频"})
        elif note:
            summary.update({"status": "skipped", "detail": str(note)})
        elif err_msg:
            summary.update({"status": "failed", "detail": str(err_msg)})
        return summary

    if name == "website":
        text = ""
        if isinstance(data, dict):
            text = data.get("text") or data.get("markdown") or data.get("content") or ""
        count = len(str(text).strip())
        error = data.get("error") if isinstance(data, dict) else None
        summary.update({"count": count, "unit": "字符"})
        if count > 0:
            if count < 500:
                summary.update({"status": "warning", "detail": f"仅 {count} 个字符（可能抓取不足）",
                               "warning": "website_low_content"})
            else:
                summary.update({"status": "ok", "detail": f"抓取 {count} 个正文字符"})
        elif error:
            summary.update({"status": "failed", "detail": str(error)})
        return summary

    return summary



# _collect_all removed per SPEC v3 — FieldDrivenSourcePlanner + SourceAdapters is the only path


def _collect_via_adapters(company_name: str, company_url: str,
                          progress_callback=None, job_id: str = None,
                          research_options: dict | None = None,
                          cancel_token=None) -> dict:
    """P1: 字段驱动采集 — 使用 SourceAdapter，SPEC v3 唯一采集路径。"""
    if _is_cancelled(cancel_token):
        raise PipelineCancelledError("用户取消研究")
    identity = build_company_identity(company_name, company_url)

    # 加载 manifest 获取字段清单
    try:
        from research.field_status import _load_manifest
        manifest = _load_manifest()
    except Exception:
        manifest = {}

    # 三套卡共用字段目标；不要依赖已废弃/不存在的 card_schema 表。
    card_fields = _load_card_set_field_targets()

    # 构建采集计划
    identity_dict = {
        "company_key": identity.company_key,
        "canonical_name": identity.display_name,
        "display_name": identity.display_name,
        "aliases": identity.aliases,
        "official_domain": identity.website_host,
        "website_host": identity.website_host,
        "country_hint": "",
    }
    source_plan = build_source_plan(identity_dict, card_fields, manifest)
    source_plan = _apply_research_options_to_source_plan(
        source_plan, card_fields, research_options
    )

    _report(progress_callback, "采集", {
        "message": f"字段驱动采集: {len(source_plan.adapters)} adapters, "
                  f"{source_plan.total_estimated_queries} queries, "
                  f"{len(source_plan.d_class_fields_skipped)} D-class skipped",
    }, job_id=job_id)

    # 构建基础 raw dict
    raw_identity = {
        "company_name": identity.display_name,
        "company_key": identity.company_key,
        "display_name": identity.display_name,
        "input_name": identity.input_name,
        "company_url": identity.website_url,
        "website_host": identity.website_host,
        "aliases": identity.aliases,
    }

    raw = dict(raw_identity)
    source_summary = {}
    all_docs = []

    # 第一阶段：官网 + Scrapling；第二阶段：Tavily/GitHub/YouTube 等补充源。
    adapter_instances = []
    for adapter_entry in source_plan.adapters:
        if _is_cancelled(cancel_token):
            raise PipelineCancelledError("用户取消研究")
        family = adapter_entry["adapter_family"]
        try:
            adapter_instances.append({
                "adapter": _load_adapter_instance(family),
                "entry": adapter_entry,
            })
        except Exception as e:
            print(f"[adapters] Failed to load {family}: {e}")
            source_summary[family] = {
                "status": "failed",
                "count": 0,
                "detail": str(e)[:220],
            }

    first_phase = [
        inst for inst in adapter_instances
        if inst["entry"]["adapter_family"] in _FIRST_PHASE_ADAPTERS
    ]
    second_phase = [
        inst for inst in adapter_instances
        if inst["entry"]["adapter_family"] not in _FIRST_PHASE_ADAPTERS
    ]
    for phase_name, instances in (("基础采集", first_phase), ("补充采集", second_phase)):
        if not instances:
            continue
        _report(progress_callback, "采集", {
            "message": f"{phase_name}: " + ", ".join(
                inst["entry"]["adapter_family"] for inst in instances
            ),
            "sources": source_summary,
        }, job_id=job_id)
        phase_docs, phase_summary = _execute_adapter_instances(
            instances,
            identity_dict,
            cancel_token=cancel_token,
        )
        all_docs.extend(phase_docs)
        source_summary.update(phase_summary)
        _report(progress_callback, "采集", {
            "message": f"{phase_name}完成: {len(phase_docs)} docs",
            "sources": source_summary,
        }, job_id=job_id)

    if _is_cancelled(cancel_token):
        raise PipelineCancelledError("用户取消研究")

    # SPEC v3: 不再回退到传统采集 — FieldDrivenSourcePlanner 是唯一路径
    if not all_docs and not source_summary:
        raise RuntimeError(
            f"字段驱动采集失败: 无适配器加载、无文档产出。"
            f"请检查 research/adapters/ 目录下的适配器实现。")

    raw["_source_summary"] = source_summary
    raw["_adapter_docs"] = all_docs
    raw["_source_plan"] = {
        "adapters": [a["adapter_family"] for a in source_plan.adapters],
        "total_queries": source_plan.total_estimated_queries,
        "d_class_skipped": source_plan.d_class_fields_skipped,
    }

    # 转换 adapter docs 为 evidence_pool 格式（兼容后续流程）
    from evidence_pool import EvidenceItem, normalize_url as norm_url
    evidence_items = []
    for doc in all_docs:
        if hasattr(doc, 'source_url'):
            url = doc.source_url
            title = doc.title
            content = doc.content
            source = doc.source_family
            evidence_items.append(EvidenceItem(
                source=source,
                intent="adapter_collected",
                title=title,
                url=url,
                normalized_url=norm_url(url),
                content=content[:5000] if content else "",
                source_score=doc.source_score,
                entity_score=doc.entity_score,
                final_score=doc.final_score,
            ))
    raw["_evidence_pool"] = evidence_items

    _report(progress_callback, "采集", {
        "message": f"字段驱动采集完成: {len(all_docs)} docs from {len(source_summary)} sources",
        "sources": source_summary,
    }, job_id=job_id)

    return raw


def _persist_evidence(company_name: str, evidence_items: list):
    """持久化证据池到 evidence_items 表（失败不阻塞主流程）"""
    try:
        from config import config
        from research.evidence_persister import persist_evidence_pool
        count = persist_evidence_pool(config.DB_PATH_RESEARCH, company_name, evidence_items)
        if count:
            print(f"[evidence] {company_name}: 持久化 {count} 条证据")
    except Exception as e:
        print(f"[evidence] persist failed: {e}")


def _run_gap_audit(company_name: str, standard_record: dict, raw: dict):
    """运行缺口审计并持久化结果"""
    try:
        from config import config
        from research.gap_auditor import audit_gaps

        # 推断公司类型（从 company_type 文本中提取）
        ct = (standard_record.get("company_type") or "").lower()
        business_type = _classify_business_type(ct)
        data_avail = _classify_data_availability(raw)

        summary = audit_gaps(config.DB_PATH_RESEARCH, company_name, "standard",
                             standard_record, business_type, data_avail)
        print(f"[gap_audit] {company_name}: {summary['total_gap_intents']} 类缺口, "
              f"{summary['total_missing_fields']} 字段缺失")
    except Exception as e:
        print(f"[gap_audit] failed: {e}")


def _classify_business_type(company_type_text: str) -> str:
    """从 company_type 文本推断 business_type"""
    t = company_type_text.lower()
    if any(k in t for k in ["b2b", "enterprise", "saas", "platform", "infrastructure", "api", "middleware"]):
        return "b2b_enterprise" if "enterprise" in t or "platform" in t else "b2b_saas"
    if any(k in t for k in ["b2c", "consumer", "social", "gaming", "ecommerce", "marketplace"]):
        return "b2c" if "b2c" in t else "consumer"
    if any(k in t for k in ["developer", "api", "open source"]):
        return "developer_api"
    if "marketplace" in t:
        return "marketplace"
    return "unknown"


def _classify_data_availability(raw: dict) -> str:
    """根据采集结果评估数据可得性"""
    evidence_count = len(raw.get("_evidence_pool", []))
    has_tavily = bool(raw.get("tavily"))
    has_github = bool(raw.get("github"))
    has_youtube = bool(raw.get("youtube"))
    source_count = sum([has_tavily, has_github, has_youtube])
    if evidence_count >= 40 and source_count >= 3:
        return "high"
    elif evidence_count >= 15 and source_count >= 2:
        return "medium"
    else:
        return "low"


def _mark_and_log_fields(db_path: str, company_name: str, version: str,
                         field_rows: list[dict], run_id: str = ""):
    """给 research_fields 行打分辨率标签，写 resolution_logs（失败不阻塞）

    P0: 传入 evidence_map，确保 confirmed 只能引用 packed_context 内的 evidence。
    P3: 解析完成后同步到实体表（EntitySyncService）。
    """
    try:
        from research.field_resolver import resolve_all
        from research.field_status import _load_manifest
        from research.evidence_extractor import build_evidence_map
        from repositories.field_repo import update_field_status_batch

        manifest = _load_manifest()
        company_key = ""
        for row in field_rows:
            ck = row.get("company_key", "")
            if ck:
                company_key = ck
                break
        if not company_key:
            company_key = company_name.lower()

        # P0: 先构建 evidence_map（必须在 LLM 后的字段解析前完成）
        field_keys = [r["field_key"] for r in field_rows]
        evidence_map = build_evidence_map(db_path, company_key, field_keys)

        # 用 field_resolver 做完整解析（含 evidence_map）
        field_map = {r["field_key"]: r.get("field_value", "") for r in field_rows}
        resolved = resolve_all(field_map, manifest, evidence_map=evidence_map)

        # 转为 update_field_status_batch 需要的格式
        results = [
            {
                "field_key": fk,
                "field_value": fr.value or field_map.get(fk, ""),
                "resolution_status": fr.resolution_status,
                "unavailable_reason": fr.unavailable_reason,
                "resolution_method": fr.resolution_method,
                "company_key": company_key,
            }
            for fk, fr in resolved.items()
        ]
        update_field_status_batch(db_path, company_name, version, results)
        count = sum(1 for r in results if r.get("resolution_status"))
        confirmed_count = sum(1 for r in results if r.get("resolution_status") == "confirmed")
        if count:
            print(f"[field_status] {company_name}/{version}: {count} resolved "
                  f"({confirmed_count} confirmed, evidence-bound)")

        # P3: 同步到实体表（主写入路径）
        if config.ENTITY_TABLES_PRIMARY:
            try:
                from services.entity_sync_service import EntitySyncService
                syncer = EntitySyncService(db_path)
                # 构建 parsed_record（兼容 sync_from_llm_result 的格式）
                parsed_for_sync = {
                    fk: (fr.value or "") for fk, fr in resolved.items()
                }
                sync_result = syncer.sync_from_llm_result(
                    company_key, parsed_for_sync, evidence_map, run_id=run_id or ""
                )
                if sync_result.get("total_rows", 0) > 0:
                    print(f"[entity_sync] {company_key}: {sync_result['total_rows']} rows "
                          f"written to {list(sync_result.get('stats', {}).keys())}")
                if sync_result.get("errors"):
                    for err in sync_result["errors"]:
                        print(f"[entity_sync] WARNING: {err}")
            except Exception as e:
                print(f"[entity_sync] failed (non-fatal): {e}")
    except Exception as e:
        print(f"[field_status] failed: {e}")


def _bind_posthoc_weak_evidence(db_path: str, company_key: str, company_name: str,
                               field_rows: list[dict], evidence_pool: list,
                               run_id: str = ""):
    """事后弱绑定 — LLM 后反向匹配证据（仅弱引用，不得让字段 confirmed）。

    噪音与上下文治理:
    - created_by_agent = "posthoc_weak_matcher"
    - confidence <= 0.45
    - 此类证据不得让字段变成 confirmed
    - 只允许 llm_extracted / manual_needed 状态

    与旧版 _bind_evidence_spans 的区别:
    - 不再作为 confirmed 依据
    - 明确标注为 posthoc（事后）
    """
    try:
        from research.document_store import insert_document
        from research.evidence_extractor import extract_field_evidence

        if not config.POSTHOC_EVIDENCE_WEAK_ONLY:
            return

        doc_map = {}
        source_score_map = {"website": "official", "official_blog": "official",
                            "github": "developer", "youtube": "media",
                            "media_article": "trusted_media", "press_release": "official",
                            "case_study": "official", "pricing_page": "official",
                            "whatweb": "database",
                            "search": "search"}

        for e in (evidence_pool or [])[:40]:  # 减半到 40 条
            title = getattr(e, "title", "") or ""
            url = getattr(e, "url", "")
            content = getattr(e, "content", "") or ""
            source = getattr(e, "source", "search")
            intent = getattr(e, "intent", "")

            final_score = getattr(e, "final_score", 0)
            if not content.strip() or final_score < 0.35:
                continue

            trust_tier = source_score_map.get(source, "search")

            doc_id = insert_document(
                db_path, company_key=company_key,
                source_type=source,
                source_url=url,
                title=title,
                raw_text=content,
                trust_tier=trust_tier,
                intent=intent,
                run_id=run_id,
            )
            if doc_id > 0:
                doc_map[url or title] = doc_id

        if not doc_map:
            return

        # 构建词集索引
        doc_tokens = {}
        for e in (evidence_pool or [])[:40]:
            url = getattr(e, "url", "")
            title = getattr(e, "title", "")
            content = getattr(e, "content", "") or ""
            doc_id = doc_map.get(url) or doc_map.get(title)
            if not doc_id or not content.strip():
                continue
            tokens = set(content.lower().split())
            doc_tokens[doc_id] = tokens

        bound_count = 0
        for row in field_rows:
            field_key = row.get("field_key", "")
            field_value = str(row.get("field_value", "")).strip()
            if not field_value or len(field_value) < 3:
                continue
            if field_value in ("暂缺", "N/A", "TBD", ""):
                continue

            value_words = set(field_value.lower().split())
            if len(value_words) < 2:
                continue

            best_doc_id = 0
            best_overlap = 0
            for doc_id, tokens in doc_tokens.items():
                overlap = len(value_words & tokens)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_doc_id = doc_id

            # 至少需要 3 个词匹配
            if best_doc_id and best_overlap >= 3:
                span_id = extract_field_evidence(
                    db_path,
                    document_id=best_doc_id,
                    company_key=company_key,
                    field_key=field_key,
                    quote_text=field_value[:500],
                    normalized_fact=field_value[:200],
                    confidence=min(0.2 + best_overlap * 0.03, 0.45),  # P0: 上限 0.45
                    created_by_agent="posthoc_weak_matcher",           # P0: 明确标注
                )
                if span_id > 0:
                    bound_count += 1

        if bound_count:
            print(f"[posthoc_evidence] {company_name}: {len(doc_map)} docs, "
                  f"{bound_count} weak-bindings created (NOT confirmed)")
    except Exception as e:
        print(f"[posthoc_evidence] bind failed: {e}")


def _bind_field_value_evidence(db_path: str, company_key: str, company_name: str,
                               field_rows: list[dict], chunk_ids: list[int],
                               run_id: str = "") -> int:
    """LLM后、分辨率前：用字段值反向匹配chunks，创建强证据绑定。

    与 _bind_posthoc_weak_evidence 的关键区别：
    - created_by_agent="field_value_matcher"（不被 build_evidence_map 过滤）
    - confidence=0.55+（高于 0.35 阈值，可进入 confirmed 判定）
    - 在 _mark_and_log_fields **之前**运行，让分辨率能看到证据

    匹配策略：
    1. 搜索文本 >= 4 字符且作为子串出现在 chunk 中 → 匹配
    2. 搜索文本 token 与 chunk token 重叠 >= 2 且 >= 50% → 匹配
    3. 任一 token >= 4 字符作为子串出现在 chunk 中 → 匹配
    每个字段最多创建 3 条 evidence_span（不同 chunk）。
    复杂值（JSON 数组、超长文本、Markdown/HTML、纯数字）先归一化为可搜索文本。
    """
    if not chunk_ids or not field_rows:
        return 0

    try:
        import sqlite3
        from research.evidence_extractor import extract_field_evidence

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'"
        ).fetchone()
        if not exists:
            conn.close()
            return 0

        placeholders = ", ".join("?" for _ in chunk_ids)
        chunks = conn.execute(
            f"""SELECT * FROM document_chunks
                WHERE id IN ({placeholders})
                AND final_score >= 0.15
                ORDER BY final_score DESC LIMIT 300""",
            chunk_ids,
        ).fetchall()

        if not chunks:
            conn.close()
            return 0

        span_ids = []
        for row in field_rows:
            field_key = row.get("field_key", "")
            field_value = str(row.get("field_value", "")).strip()
            if not field_value or len(field_value) < 2:
                continue
            if field_value in ("暂缺", "N/A", "TBD", ""):
                continue

            # Change 1: 从复杂值中提取可搜索文本
            searchable_value = _extract_searchable_text(field_value, field_key)

            value_lower = searchable_value.lower()
            value_tokens = set(value_lower.split())

            if not value_tokens:
                continue

            span_count_for_field = 0
            for chunk_row in chunks:
                chunk = dict(chunk_row)
                chunk_text = chunk.get("chunk_text", "")
                if not chunk_text.strip():
                    continue
                chunk_lower = chunk_text.lower()

                # 匹配规则
                matched = False
                # 规则1: 搜索文本 >= 4 字符且作为子串出现在 chunk 中
                if len(value_lower) >= 4 and value_lower in chunk_lower:
                    matched = True
                # 规则2: token 重叠 >= 2 且 >= 50%
                elif value_tokens:
                    chunk_tokens = set(chunk_lower.split())
                    overlap = len(value_tokens & chunk_tokens)
                    if overlap >= max(2, len(value_tokens) * 0.5):
                        matched = True
                # 规则3 (Change 3): 任一 value token >= 4 字符作为子串出现在 chunk 中
                if not matched and value_tokens:
                    for token in value_tokens:
                        if len(token) >= 4 and token in chunk_lower:
                            matched = True
                            break

                if matched:
                    chunk_score = chunk.get("final_score", 0.35)
                    confidence = min(0.55 + chunk_score * 0.3, 0.85)
                    span_id = extract_field_evidence(
                        db_path,
                        document_id=chunk["document_id"],
                        company_key=company_key,
                        field_key=field_key,
                        quote_text=chunk_text[:500],
                        normalized_fact=field_value[:200],
                        confidence=confidence,
                        created_by_agent="field_value_matcher",
                    )
                    if span_id > 0:
                        span_ids.append(span_id)
                        span_count_for_field += 1
                    # Change 2: 每个字段最多 3 条 evidence_span
                    if span_count_for_field >= 3:
                        break

        conn.close()

        if span_ids:
            print(f"[field_evidence] {company_name}: {len(span_ids)} field-value "
                  f"evidence bindings created for {len(field_rows)} fields")
        return len(span_ids)
    except Exception as e:
        print(f"[field_evidence] bind failed: {e}")
        return 0


def _extract_searchable_text(field_value: str, field_key: str) -> str:
    """从复杂字段值中提取可用于匹配的纯文本。

    - JSON 数组: 提取所有字符串值拼接
    - Markdown/HTML: 去除标签和格式标记
    - 超长文本 (>200): 截取前 200 字符
    - 纯数字值: 附加 field_key 中的词作为搜索词
    """
    import json
    import re

    value = field_value.strip()

    # JSON 数组处理: 提取所有字符串值
    if value.startswith("[") and value.endswith("]"):
        try:
            data = json.loads(value)
            if isinstance(data, list):
                strings = []
                for item in data:
                    if isinstance(item, str):
                        strings.append(item)
                    elif isinstance(item, dict):
                        for v in item.values():
                            if isinstance(v, str):
                                strings.append(v)
                if strings:
                    value = " ".join(strings)
        except (json.JSONDecodeError, TypeError):
            pass

    # 去除 Markdown 和 HTML 标记
    value = re.sub(r'<[^>]+>', ' ', value)                      # HTML tags
    value = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', value)      # Markdown links
    value = re.sub(r'[*_~`#>|]', ' ', value)                     # Markdown formatting
    value = re.sub(r'\s+', ' ', value).strip()

    # 超长文本截取
    if len(value) > 200:
        value = value[:200]

    # 纯数字值附加 field_key 词汇作为搜索词
    if re.match(r'^[\d\s.,\-–]+$', value):
        field_words = re.findall(r'[a-zA-Z_]+', field_key)
        if field_words:
            value = value + " " + " ".join(field_words)

    return value


def _run_forum_moderation(db_path: str, company_name: str, version: str,
                          field_rows: list[dict]):
    """ForumModerator 字段质量检查 — 在字段定稿前进行冲突/弱证据/误标检查。

    P2: 集成到主流程。失败不阻塞。
    将结果打印到日志，严重问题写入 resolution_logs。
    """
    try:
        from research_agents.forum.moderator import ForumModerator
        from research.field_status import _load_manifest
        from research.evidence_extractor import build_evidence_map

        manifest = _load_manifest()
        moderator = ForumModerator(manifest=manifest)

        # 构建字段审计输入
        fields_meta = {}
        for row in field_rows:
            fk = row.get("field_key", "")
            fv = str(row.get("field_value", "")).strip()
            status = row.get("resolution_status", "draft")
            fields_meta[fk] = {
                "status": status,
                "evidence_ids": [],  # 后续从 evidence_spans 获取
                "candidate_count": 1,
                "has_context": bool(fv and len(fv) > 10),
            }

        # 尝试获取 evidence 绑定
        company_key = ""
        # 从 field_rows 中提取可能存在的 company_key
        for row in field_rows:
            ck = row.get("company_key", "")
            if ck:
                company_key = ck
                break
        if not company_key:
            company_key = company_name.lower()

        try:
            field_keys = list(fields_meta.keys())
            evidence_map = build_evidence_map(db_path, company_key, field_keys)
            for fk, span_ids in evidence_map.items():
                if fk in fields_meta:
                    fields_meta[fk]["evidence_ids"] = span_ids
        except Exception:
            pass

        # 运行 ForumModerator
        report = moderator.audit_batch(fields_meta)

        # 打印结果
        if report.findings:
            errors = [f for f in report.findings if f.severity == "error"]
            warnings = [f for f in report.findings if f.severity == "warning"]
            if errors:
                print(f"[forum] {company_name}/{version}: {len(errors)} errors, "
                      f"{len(warnings)} warnings — PASSED={report.passed}")
                for f in errors[:5]:
                    print(f"  [forum:error] {f.field_key}: {f.detail}")
            elif warnings:
                print(f"[forum] {company_name}/{version}: {len(warnings)} warnings — no errors")
            else:
                print(f"[forum] {company_name}/{version}: {len(report.findings)} findings — "
                      f"no blocking issues")

            # 记录弱证据字段和冲突
            if report.weak_evidence_fields:
                print(f"  weak_evidence: {', '.join(report.weak_evidence_fields[:5])}")
            if report.conflict_fields:
                print(f"  conflicts: {', '.join(report.conflict_fields[:5])}")
            if report.refetch_tasks:
                print(f"  refetch_tasks: {len(report.refetch_tasks)} generated")
        else:
            print(f"[forum] {company_name}/{version}: all checks passed")
    except Exception as e:
        print(f"[forum] moderation failed: {e}")


def _build_evidence_pool(raw: dict) -> list:
    """将采集原始结果转为打分、去重后的 EvidenceItem 列表。"""
    items = []
    identity_display = raw.get("display_name", raw.get("company_name", ""))
    identity_host = raw.get("website_host", "")
    identity_root = identity_host.split(".")[0] if identity_host else ""

    # SourceAdapter 文档是当前主采集路径，先保留为 evidence。
    # 后面的旧 raw 兼容分支只补充 Tavily/GitHub/YouTube/website 遗留结果。
    for doc in raw.get("_adapter_docs") or []:
        url = getattr(doc, "source_url", "") or ""
        title = getattr(doc, "title", "") or ""
        content = getattr(doc, "content", "") or getattr(doc, "raw_text", "") or ""
        source = getattr(doc, "source_family", "search") or "search"
        intent = getattr(doc, "intent", "") or "adapter_collected"
        if not content.strip():
            continue
        fs = evidence_final_score(
            url, source, title, content[:2000],
            identity_display, identity_host, identity_root)
        items.append(EvidenceItem(
            source=source,
            intent=intent,
            title=title,
            url=url,
            normalized_url=normalize_url(url),
            content=content,
            raw_content=getattr(doc, "raw_text", "") or content,
            metric_snippet=metric_snippet(content),
            source_score=getattr(doc, "source_score", evidence_source_score(url, source)),
            entity_score=getattr(doc, "entity_score", 0.5),
            final_score=max(fs, getattr(doc, "final_score", 0) or 0),
            query=intent,
        ))

    # Tavily
    for batch in (raw.get("tavily") or []):
        if not isinstance(batch, dict) or batch.get("error"):
            continue
        for r in batch.get("results", []):
            url = r.get("url", "")
            nurl = normalize_url(url)
            title = r.get("title", "")
            content = r.get("content", "")
            fs = evidence_final_score(
                url, "tavily", title, content,
                identity_display, identity_host, identity_root)
            items.append(EvidenceItem(
                source="tavily", intent=batch.get("_intent", ""),
                title=title, url=url, normalized_url=nurl,
                content=content, raw_content=r.get("raw_content", ""),
                metric_snippet=metric_snippet(
                    f"{title} {content} {r.get('raw_content', '')}"),
                source_score=evidence_source_score(url, "tavily"),
                entity_score=evidence_entity_score(
                    title, url, content, identity_display,
                    identity_host, identity_root),
                final_score=fs, query=batch.get("_query", "")))

    # GitHub
    for r in (raw.get("github", {}) or {}).get("items", []):
        url = r.get("html_url", "")
        nurl = normalize_url(url)
        title = r.get("full_name", "")
        desc = r.get("description", "") or ""
        fs = evidence_final_score(
            url, "github", title, desc,
            identity_display, identity_host, identity_root)
        items.append(EvidenceItem(
            source="github", intent="product",
            title=title, url=url, normalized_url=nurl,
            content=desc, source_score=evidence_source_score(url, "github"),
            final_score=fs))

    # YouTube（标题 + 描述 + 转录文本）
    for r in (raw.get("youtube", {}) or {}).get("items", []):
        snippet = r.get("snippet", {})
        vid = (_vid_of(r) or "").strip()
        url = f"https://www.youtube.com/watch?v={vid}" if vid else ""
        title = snippet.get("title", "")
        desc = snippet.get("description", "") or ""
        transcript = r.get("_transcript", "") or ""
        # 优先用转录文本，其次用描述
        content = transcript if transcript else desc
        # 保留描述作为补充上下文
        if transcript and desc:
            content = f"[Transcript]\n{transcript}\n\n[Description]\n{desc[:500]}"
        fs = evidence_final_score(
            url, "youtube", title, content[:2000],
            identity_display, identity_host, identity_root)
        items.append(EvidenceItem(
            source="youtube", intent="interview",
            title=title, url=url, normalized_url=url,
            content=content, source_score=evidence_source_score(url, "youtube"),
            final_score=fs))

    # Website
    ws = raw.get("website", {}) or {}
    text = ws.get("text") or ws.get("markdown") or ""
    url = raw.get("company_url", "")
    items.append(EvidenceItem(
        source="website", intent="overview",
        title=f"{identity_display} 官网", url=url,
        normalized_url=normalize_url(url),
        content=str(text)[:5000], source_score=1.0, final_score=1.0))

    return filter_evidence(dedupe_evidence(items), min_score=0.35)


# ── Step 2: AI 分析 ──────────────────────────────

# ── 上下文治理钩子 (Goal 三) ──

def _validate_context_governance(raw_data: dict, stage: str = "L0") -> None:
    """Ensure LLM input never receives raw text directly.

    Raises RawTextNotAllowedError if governance is enabled and raw text is detected.
    No-op if LEGACY_CONTEXT_MODE is explicitly set.
    """
    if is_legacy_mode():
        return
    if not is_governance_enabled():
        return

    packed = raw_data.get("_packed_context", {})
    has_packed = packed and packed.get("chunks")

    # Check for raw text leakage
    raw_sources = raw_data.get("raw_sources", {})
    raw_website = raw_sources.get("website", "")
    raw_tavily = raw_sources.get("tavily_fulltext", "")

    # If raw content exists without packed context being the primary source, that's a violation
    long_raw = (isinstance(raw_website, str) and len(raw_website) > 5000) or \
               (isinstance(raw_tavily, str) and len(raw_tavily) > 5000)

    if long_raw and not has_packed:
        raise RawTextNotAllowedError(
            f"Raw text detected in {stage} input but RAW_TEXT_IN_LLM_ENABLED is False. "
            "All input must go through chunk → rank → pack."
        )


def _trim_text(value, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def _prepare_raw_data_for_llm(raw_data: dict) -> dict:
    """构建 L0 LLM 的结构化输入。

    噪音与上下文治理: 不再传递 raw_sources.website 全文、Tavily raw_content 全量、
    evidence_pool 前 80 条。只传 company_identity、source_audit、source_warnings、
    packed_context（chunks + evidence_spans）。

    禁止:
    - raw_sources.website 全文进入 L0
    - Tavily raw_content 全量进入 L0
    - evidence_pool 前 80 条直接进入 L0

    Goal 三治理: 如果 CONTEXT_PACKER_ENABLED=1 且非 LEGACY_CONTEXT_MODE，
    强制要求数据经 chunk → rank → pack 处理后进入 LLM。
    """
    # ── Goal 三：上下文治理验证 ──
    _validate_context_governance(raw_data, stage="L0")

    company_identity = {
        "company_key": raw_data.get("company_key", raw_data.get("company_name", "")),
        "display_name": raw_data.get("display_name", raw_data.get("company_name", "")),
        "website_host": raw_data.get("website_host", ""),
        "website_url": raw_data.get("company_url", ""),
        "aliases": raw_data.get("aliases", []),
    }

    source_audit = raw_data.get("_source_summary", {})
    source_warnings = raw_data.get("_source_warnings", [])

    # ── 使用 packed_context 替代 evidence_pool + raw_sources ──
    packed = raw_data.get("_packed_context", {})
    context_budget_info = {
        "target_type": "l0",
        "budget_tokens": config.L0_CONTEXT_BUDGET_TOKENS,
        "used_tokens": packed.get("used_tokens", 0) if packed else 0,
    }

    # 如果 packed_context 可用，只用它
    if packed and packed.get("chunks"):
        result = {
            "company_identity": company_identity,
            "source_audit": source_audit,
            "source_warnings": source_warnings,
            "context_budget": context_budget_info,
            "packed_context": packed["chunks"],
            "evidence_spans": packed.get("evidence_spans", []),
            "dropped_context_count": packed.get("dropped_count", 0),
        }
        return result

    # ── 回退模式：无 packed_context 时使用轻量 evidence_pool 摘要 ──
    # 注意：此模式下不传 raw_text，仅传标题 + URL + 来源类型
    evidence_summary = []
    for e in (raw_data.get("_evidence_pool") or [])[:40]:
        evidence_summary.append({
            "source": getattr(e, "source", ""),
            "intent": getattr(e, "intent", ""),
            "title": getattr(e, "title", ""),
            "url": getattr(e, "url", ""),
            "final_score": getattr(e, "final_score", 0),
        })

    return {
        "company_identity": company_identity,
        "source_audit": source_audit,
        "source_warnings": source_warnings,
        "context_budget": context_budget_info,
        "evidence_summary": evidence_summary,
    }

def _load_prompt_text(name: str) -> str:
    return load_prompt(name)


# ══ 三层枚举提取（规则层 → LLM 三组 → 验证）══════════════════

ENUM_GROUP_PROMPTS = {
    "A": ("layer3-group-a-technical", ["ai_model_dependency", "data_flywheel", "proprietary_data_asset"]),
    "B": ("layer3-group-b-competitive", ["incumbent_direct_competitor", "workflow_integration_level", "inference_cost_exposure"]),
    "C": ("layer3-group-c-business", ["pricing_model", "customer_segment_type", "stack_layer"]),
}

KEY_ENUM_FIELDS = ["ai_model_dependency", "incumbent_direct_competitor", "pricing_model"]


def _run_llm_enum_group(api_key: str, group_name: str, context: str,
                        rule_hits: dict | None = None,
                        temperature: float = 0.1) -> dict:
    """调用单组 LLM 提取枚举字段。返回 {field: value} dict。"""
    prompt_file, field_names = ENUM_GROUP_PROMPTS[group_name]
    prompt = _load_prompt_text(prompt_file)

    # 组 C 需要注入规则层提示
    if group_name == "C" and rule_hits:
        hint_lines = [f"- {k} = \"{v}\"（规则层已确定，跳过）" for k, v in rule_hits.items()]
        prompt = prompt.replace("{rule_fields_hint}", "\n".join(hint_lines))
    elif group_name == "C":
        prompt = prompt.replace("{rule_fields_hint}", "（无）")

    result = call_deepseek(
        api_key, prompt, context,
        temperature=temperature, max_tokens=200, timeout=60,
    )
    try:
        parsed = _extract_json(result)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    # 只保留本组字段
    return {k: v for k, v in parsed.items() if k in field_names and v}


def _extract_enum_fields(api_key: str, l0_result: str, l1_result: str, l2_result: str,
                         company_url: str, company_type: str = "",
                         progress_callback=None, job_id: str = None) -> dict:
    """三层枚举提取：规则层 → LLM 组A+B→组C → 验证 → 合并。
    返回 {field: value} dict，覆盖原 L3 的枚举字段。"""
    context = json.dumps(
        {"layer0": l0_result, "layer1": l1_result, "layer2": l2_result},
        ensure_ascii=False, indent=2,
    )

    # 层1：规则层
    _report(progress_callback, "枚举-规则", "规则层提取...", job_id=job_id)
    rule_hits = run_rule_layer(company_url, company_type)
    _report(progress_callback, "枚举-规则",
            f"命中 {len(rule_hits)} 字段: {list(rule_hits.keys())}", job_id=job_id)

    # 层2：LLM 组 A + B 并行
    _report(progress_callback, "枚举-LLM", "组A+B并行提取...", job_id=job_id)
    group_a = {}
    group_b = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(_run_llm_enum_group, api_key, "A", context)
        fb = ex.submit(_run_llm_enum_group, api_key, "B", context)
        group_a = fa.result() or {}
        group_b = fb.result() or {}

    # 层2：LLM 组 C（传规则层结果，跳过已有字段）
    _report(progress_callback, "枚举-LLM", "组C提取...", job_id=job_id)
    group_c = _run_llm_enum_group(api_key, "C", context, rule_hits) or {}

    # 合并三组
    merged = {}
    merged.update(group_a)
    merged.update(group_b)
    merged.update(group_c)
    # 规则层覆盖（优先级最高）
    merged.update(rule_hits)

    _report(progress_callback, "枚举-LLM",
            f"合并 {len(merged)} 字段: {list(merged.keys())}", job_id=job_id)

    # 关键字段多数投票（2 round，不一致时加第3 round）
    for field in KEY_ENUM_FIELDS:
        if field in merged:
            v1 = merged[field]
            _report(progress_callback, "枚举-投票", f"{field} round 2...", job_id=job_id)
            r2 = _run_llm_enum_group(api_key, _group_for_field(field), context,
                                     rule_hits if _group_for_field(field) == "C" else None,
                                     temperature=0.2)
            v2 = r2.get(field) if r2 else None
            if v2 and v2 != v1:
                _report(progress_callback, "枚举-投票",
                        f"{field} 不一致({v1} vs {v2}), round 3...", job_id=job_id)
                r3 = _run_llm_enum_group(api_key, _group_for_field(field), context,
                                         rule_hits if _group_for_field(field) == "C" else None,
                                         temperature=0.25)
                v3 = r3.get(field) if r3 else None
                # 取众数
                votes = [v1, v2]
                if v3: votes.append(v3)
                merged[field] = max(set(votes), key=votes.count)
                _report(progress_callback, "枚举-投票",
                        f"{field} → {merged[field]} (投票: {votes})", job_id=job_id)
            else:
                _report(progress_callback, "枚举-投票",
                        f"{field} 一致 ({v1})", job_id=job_id)

    # 层3：Pydantic 验证
    _report(progress_callback, "枚举-验证", "Pydantic 验证...", job_id=job_id)
    try:
        validated = validate_enum_fields(merged)
        _report(progress_callback, "枚举-验证",
                f"通过 {len(validated)}/{len(merged)} 字段", job_id=job_id)
        return validated
    except ValueError as e:
        _report(progress_callback, "枚举-验证",
                f"验证失败: {e}，退回未验证结果", job_id=job_id)
        return merged


def _group_for_field(field: str) -> str:
    for g, (_, fields) in ENUM_GROUP_PROMPTS.items():
        if field in fields:
            return g
    return "A"


def llm_analysis(company_name: str, company_url: str, raw_data: dict,
                 progress_callback=None, job_id: str = None,
                 cancel_token=None) -> list[dict]:
    """4层 Prompt 分析，返回 3 版本记录列表"""
    api_key = config.DEEPSEEK_API_KEY

    def _check_cancel():
        if callable(cancel_token) and cancel_token():
            raise PipelineCancelledError("用户取消研究")

    # Layer 0
    _report(progress_callback, "L0清洗", "信息清洗中...", job_id=job_id)
    l0_prompt = _load_prompt_text("layer0-cleaner")
    l0_result = call_deepseek(
        api_key, l0_prompt,
        json.dumps(_prepare_raw_data_for_llm(raw_data), ensure_ascii=False, indent=2),
        temperature=0.1, max_tokens=4096, timeout=120,
    )
    _check_cancel()

    # ── L0 质量门控：校验输出完整性，不通过则阻断 L1/L2/L3 ──
    try:
        l0_parsed = _extract_json(l0_result)
    except ValueError as e:
        raise L0GateError(
            f"L0 输出无法解析为 JSON，中止 {company_name} 研究: {e}"
        )
    if not isinstance(l0_parsed, dict):
        raise L0GateError(
            f"L0 输出不是 JSON 对象 (got {type(l0_parsed).__name__})，中止 {company_name} 研究"
        )
    l0_valid, l0_errors = validate_l0_output(l0_parsed)
    if not l0_valid:
        raise L0GateError(
            f"L0 输出不完整，中止 {company_name} 研究: {'; '.join(l0_errors)}"
        )
    l0_clean = json.dumps(l0_parsed, ensure_ascii=False, indent=2)

    # Layer 1
    _report(progress_callback, "L1横纵分析", "横纵分析中...", job_id=job_id)
    l1_prompt = _load_prompt_text("layer1-hv-analysis")
    l1_result = call_deepseek(
        api_key, l1_prompt, l0_clean,
        temperature=0.3, max_tokens=4096, timeout=120,
    )
    _check_cancel()

    # ── L1 竞品矩阵提取 ──
    competitive_matrix = None
    try:
        l1_parsed = _extract_json(l1_result)
        from research.competitive_matrix import CompetitiveMatrixExtractor
        cm_extractor = CompetitiveMatrixExtractor()
        l1_matrix, l1_errors = cm_extractor.validate(l1_parsed)
        if l1_matrix:
            competitive_matrix = l1_matrix
        elif l1_errors:
            print(f"[L1 matrix] validation warnings: {'; '.join(l1_errors[:3])}")
    except Exception as e:
        print(f"[L1 matrix] extract failed (non-blocking): {e}")

    # Layer 2
    _report(progress_callback, "L2商业结构", "商业结构分析中...", job_id=job_id)
    l2_prompt = _load_prompt_text("layer2-business")
    l2_context = json.dumps({"layer0": l0_parsed, "layer1": l1_result}, ensure_ascii=False, indent=2)
    l2_result = call_deepseek(
        api_key, l2_prompt, l2_context,
        temperature=0.2, max_tokens=4096, timeout=120,
    )
    _check_cancel()

    # ── L2 商业模式画布提取 ──
    business_canvas = None
    try:
        l2_parsed = _extract_json(l2_result)
        from research.business_canvas import BusinessCanvasExtractor
        bc_extractor = BusinessCanvasExtractor()
        l2_canvas, l2_errors = bc_extractor.validate(l2_parsed)
        if l2_canvas:
            business_canvas = l2_canvas
        elif l2_errors:
            print(f"[L2 canvas] validation warnings: {'; '.join(l2_errors[:3])}")
    except Exception as e:
        print(f"[L2 canvas] extract failed (non-blocking): {e}")

    # Layer 3 — 3 版本
    all_context = json.dumps(
        {"layer0": l0_parsed, "layer1": l1_result, "layer2": l2_result},
        ensure_ascii=False, indent=2,
    )

    # ── MarketDataBridge: 注入已知市场数据 ──
    try:
        from research.market_data_bridge import MarketDataBridge
        bridge = MarketDataBridge()
        all_context = bridge.inject_into_l3_context(
            raw_data.get("company_key", company_name.lower()), all_context)
    except Exception as e:
        print(f"[MarketDataBridge] inject failed (non-blocking): {e}")

    versions = [
        ("standard", "标准版：客观完整，数据优先，适合事实核查。用词严谨，多引用具体数据。要求：语气客观中立，强调数据可靠性和来源可验证性。"),
        ("business", "商业版：强调价值判断，投资人/同行视角。突出商业潜力和竞争分析。要求：语气专业但有判断力，关注估值空间、市场空间、竞争壁垒。"),
        ("spread", "传播版：高钩子密度，语言有张力，自媒体友好。要求：开头要有强钩子，用数据制造冲击感。金句化表达关键洞察。适合大众传播。"),
    ]

    # ── 加载分组 L3 Prompt ──
    l3a_prompt_base = _load_prompt_text("layer3-group-facts")
    l3b_prompt_base = _load_prompt_text("layer3-group-market")
    l3c_prompt_base = _load_prompt_text("layer3-group-operating")

    all_records = []
    for ver_name, ver_inst in versions:
        _report(progress_callback, f"L3-{ver_name}", f"提取 {ver_name} 版...", job_id=job_id)

        # ── L3 分组并行（A+B 并行 → C 串行）──
        import concurrent.futures

        ver_prefix = f"\n\n## 版本要求（{ver_name}）\n{ver_inst}"
        l3a_prompt = l3a_prompt_base + ver_prefix
        l3b_prompt = l3b_prompt_base + ver_prefix
        l3c_prompt = l3c_prompt_base + ver_prefix

        # A context: L0 only
        a_context = json.dumps({"layer0": l0_parsed}, ensure_ascii=False, indent=2)

        # B context: L0 + L1 matrix
        b_context = all_context
        if competitive_matrix:
            b_context += "\n\n## L1 竞品矩阵\n" + json.dumps(
                competitive_matrix.model_dump(), ensure_ascii=False, indent=2)

        # Run A + B in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as l3exec:
            future_a = l3exec.submit(
                call_deepseek, api_key, l3a_prompt, a_context,
                temperature=0.15, max_tokens=4096, timeout=120)
            future_b = l3exec.submit(
                call_deepseek, api_key, l3b_prompt, b_context,
                temperature=0.15, max_tokens=4096, timeout=120)
            l3a_result = future_a.result()
            l3b_result = future_b.result()

        _check_cancel()

        # Parse A and B — failures are blocking
        try:
            l3a_parsed = _extract_json(l3a_result) if l3a_result else {}
        except ValueError as e:
            raise RuntimeError(
                f"L3-A ({ver_name}) 输出无法解析为 JSON: {e}") from e
        try:
            l3b_parsed = _extract_json(l3b_result) if l3b_result else {}
        except ValueError as e:
            raise RuntimeError(
                f"L3-B ({ver_name}) 输出无法解析为 JSON: {e}") from e

        if not isinstance(l3a_parsed, dict) or not isinstance(l3b_parsed, dict):
            raise RuntimeError(
                f"L3-A 或 L3-B ({ver_name}) 输出不是 JSON 对象 "
                f"(A={type(l3a_parsed).__name__}, B={type(l3b_parsed).__name__})")

        # C context: everything
        c_context = all_context
        if competitive_matrix:
            c_context += "\n\n## L1 竞品矩阵\n" + json.dumps(
                competitive_matrix.model_dump(), ensure_ascii=False, indent=2)
        if business_canvas:
            c_context += "\n\n## L2 商业模式画布\n" + json.dumps(
                business_canvas.model_dump(), ensure_ascii=False, indent=2)
        c_context += "\n\n## L3-A 基础事实\n" + (l3a_result or "")
        c_context += "\n\n## L3-B 市场数据\n" + (l3b_result or "")

        # Run C with retry
        parsed = None
        for attempt in range(2):
            try:
                l3c_result = call_deepseek(
                    api_key, l3c_prompt, c_context,
                    temperature=0.15, max_tokens=16384, timeout=240, max_retries=5,
                )
                l3c_parsed = _extract_json(l3c_result)
                if not isinstance(l3c_parsed, dict):
                    raise ValueError(
                        f"L3-C output must be a JSON object, got {type(l3c_parsed).__name__}")
                # Merge A + B + C
                merged = {}
                merged.update(l3a_parsed)
                merged.update(l3b_parsed)
                merged.update(l3c_parsed)
                parsed = merged
                break
            except ValueError as e:
                if attempt == 0:
                    _report(progress_callback, f"L3-{ver_name}",
                            f"JSON修复失败，重试...", job_id=job_id)
                    retry_msg = f"上一次输出 JSON 无法解析：{e}\n请确保输出合法 JSON（检查逗号、引号、转义）。"
                    l3c_prompt = l3c_prompt + "\n\n" + retry_msg
                else:
                    raise RuntimeError(
                        f"L3-C ({ver_name}) 提取失败: {e}") from e

        if parsed is not None:
            # ── 三层枚举提取覆盖 ──
            try:
                enum_fields = _extract_enum_fields(
                    api_key, l0_result, l1_result, l2_result,
                    company_url, parsed.get("company_type", ""),
                    progress_callback, job_id,
                )
                parsed.update(enum_fields)
            except Exception as e:
                _report(progress_callback, f"L3-{ver_name}",
                        f"枚举提取异常: {e}", job_id=job_id)

            missing_founder_fields = _missing_founder_fields(parsed)
            if missing_founder_fields and _has_founder_detail_signal(l0_result):
                _report(
                    progress_callback,
                    f"L3-{ver_name}",
                    f"创始人字段缺失，重试 {', '.join(missing_founder_fields)}...",
                    job_id=job_id,
                )
                retry_prompt = _founder_retry_prompt(l3c_prompt, missing_founder_fields)
                retry_context = c_context
                try:
                    retry_result = call_deepseek(
                        api_key, retry_prompt, retry_context,
                        temperature=0.1, max_tokens=16384, timeout=240, max_retries=5,
                    )
                    retry_parsed = _extract_json(retry_result)
                    parsed = _merge_founder_retry(parsed, retry_parsed, missing_founder_fields)
                except ValueError:
                    pass
            parsed["company_name"] = company_name
            parsed["version"] = ver_name
            all_records.append(parsed)

    return all_records


def _extract_json(text: str) -> dict:
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text, flags=re.IGNORECASE)
    if match:
        text = match.group(1)
    clean = text.strip()

    # 尝试直接解析
    try:
        if clean.startswith('{'):
            return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # LLM 偶尔会在 JSON 前后加解释文字；截取第一个完整对象再解析。
    json_obj = _find_json_object(clean)
    if json_obj:
        try:
            return json.loads(json_obj)
        except json.JSONDecodeError:
            text = json_obj

    # 用 json_repair 自动修复常见语法错误
    try:
        from json_repair import repair_json
        return json.loads(repair_json(text))
    except ImportError:
        pass

    raise ValueError(f"Cannot parse JSON from: {text[:200]}...")


def _is_missing_value(value) -> bool:
    return str(value or "").strip() in ("", "暂缺", "unknown", "Unknown", "N/A", "n/a")


def _missing_founder_fields(record: dict) -> list[str]:
    fields = ["founder_edu", "founder_achievement"]
    return [field for field in fields if _is_missing_value(record.get(field))]


def _has_founder_detail_signal(text: str) -> bool:
    lowered = str(text or "").lower()
    keywords = [
        "founder", "founded", "university", "college", "school", "degree",
        "phd", "mit", "stanford", "harvard", "berkeley", "alumni",
        "创始", "大学", "学院", "学位", "博士", "硕士", "本科",
        "毕业", "获奖", "奖项", "创业", "前公司", "曾任",
    ]
    return any(keyword in lowered for keyword in keywords)


def _founder_retry_prompt(prompt: str, missing_fields: list[str]) -> str:
    fields = ", ".join(missing_fields)
    return prompt + f"""

上一轮输出遗漏了以下创始人字段：{fields}。
请重新输出完整 JSON，保持原有字段结构不变，并优先从 Layer 0 的创始人信息中提取：
- founder_edu：只写学校、专业、学位等教育信息，不要混入工作履历。
- founder_achievement：只写获奖、创业经历、前公司重要成果等，不要与教育信息混淆。
如果 Layer 0 已有相关线索，不允许填“暂缺”。
"""


def _merge_founder_retry(original: dict, retry: dict, missing_fields: list[str]) -> dict:
    merged = dict(original)
    for field in missing_fields:
        value = retry.get(field)
        if not _is_missing_value(value):
            merged[field] = value
    for key, value in retry.items():
        if key not in merged or _is_missing_value(merged.get(key)):
            merged[key] = value
    return merged


def _find_json_object(text: str) -> str | None:
    start = text.find('{')
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _validate_records(records: list[dict]) -> list[dict]:
    """填充暂缺字段"""
    for rec in records:
        rec.update(_complete_contract_fields(rec))
        for f in _REQUIRED_FIELDS:
            val = rec.get(f)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                rec[f] = "暂缺"
    return records


def _normalized_host(url: str) -> str:
    value = str(url or "").strip()
    if not value or value in {"暂缺", "unknown", "N/A"}:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.netloc or parsed.path).split("/")[0].split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _hosts_match(expected: str, actual: str) -> bool:
    return (
        expected == actual
        or actual.endswith(f".{expected}")
        or expected.endswith(f".{actual}")
    )


def _validate_record_identity(records: list[dict], company_url: str):
    expected_host = _normalized_host(company_url)
    if not expected_host:
        return

    mismatches = []
    for rec in records:
        actual_host = _normalized_host(rec.get("website_url", ""))
        if actual_host and not _hosts_match(expected_host, actual_host):
            mismatches.append(
                f"{rec.get('version', '?')}: website_url={rec.get('website_url')}"
            )

    if mismatches:
        raise RuntimeError(
            "公司身份校验失败: L3 输出官网域名与请求 URL 不一致；"
            f"expected={expected_host}; " + "; ".join(mismatches)
        )


# ── 文档治理：source_documents → clean → chunk → rank → evidence_spans ──

def _persist_source_documents_from_raw(raw: dict, run_id: str = "") -> list[int]:
    """将 evidence_pool 条目写入 source_documents（如果尚未存在）。

    噪音与上下文治理: source_documents 是仓库，不是 prompt。
    返回 doc_id 列表。
    """
    try:
        from research.document_store import insert_document

        doc_ids = []
        evidence_pool = raw.get("_evidence_pool", [])
        company_key = raw.get("company_key", raw.get("company_name", ""))

        source_score_map = {"website": "official", "official_blog": "official",
                            "github": "developer", "youtube": "media",
                            "media_article": "trusted_media", "press_release": "official",
                            "case_study": "official", "pricing_page": "official",
                            "whatweb": "database",
                            "search": "search"}

        for e in (evidence_pool or [])[:80]:
            title = getattr(e, "title", "") or ""
            url = getattr(e, "url", "")
            content = getattr(e, "content", "") or ""
            source = getattr(e, "source", "search")
            intent = getattr(e, "intent", "")
            final_score = getattr(e, "final_score", 0)

            if not content.strip() or final_score < 0.3:
                continue

            trust_tier = source_score_map.get(source, "search")

            doc_id = insert_document(
                config.DB_PATH_RESEARCH, company_key=company_key,
                source_type=source,
                source_url=url,
                title=title,
                raw_text=content,
                trust_tier=trust_tier,
                intent=intent,
                run_id=run_id,
            )
            if doc_id > 0:
                doc_ids.append(doc_id)

        if doc_ids:
            print(f"[document_store] {raw.get('company_name', company_key)}: "
                  f"{len(doc_ids)} source_documents stored")
        return doc_ids
    except Exception as e:
        print(f"[document_store] persist failed: {e}")
        return []


def _build_document_chunks_for_run(company_key: str, doc_ids: list[int],
                                   display_name: str = "",
                                   website_host: str = "",
                                   aliases=None) -> list[int]:
    """文档清洗 + 切块 + 打分，写入 document_chunks 表。

    返回 chunk_id 列表。
    """
    if not config.DOCUMENT_CHUNKING_ENABLED:
        return []

    try:
        import sqlite3
        from research.document_store import get_document_text

        db_path = config.DB_PATH_RESEARCH
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # 检查表是否存在
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'"
        ).fetchone()
        if not exists:
            conn.close()
            return []

        chunk_ids = []
        company_identity = {
            "display_name": display_name or company_key,
            "website_host": website_host or "",
            "aliases": aliases or [],
        }

        # 从 source_documents 获取文档标题/来源信息
        placeholders = ", ".join("?" for _ in doc_ids)
        docs = conn.execute(
            f"""SELECT id, source_type, source_url, title, raw_text, trust_tier
                FROM source_documents WHERE id IN ({placeholders})""",
            doc_ids,
        ).fetchall()

        for doc in docs:
            doc_dict = dict(doc)
            raw_text = doc_dict.get("raw_text", "")

            # 1. 清洗
            clean_result = clean_document_text(
                raw_text,
                source_type=doc_dict.get("source_type", ""),
                source_url=doc_dict.get("source_url", ""),
            )
            if clean_result["is_low_quality"]:
                continue

            # 2. 切块
            doc_dict["raw_text"] = clean_result["clean_text"]
            chunks = chunk_document(doc_dict, company_key)

            # 3. 打分
            scored = score_chunks_batch(chunks, company_identity)

            # 4. 写入 document_chunks
            for c in scored:
                cur = conn.execute(
                    """INSERT INTO document_chunks
                       (document_id, company_key, source_type, source_url,
                        title, chunk_text, chunk_type, token_estimate,
                        source_score, entity_score, field_relevance_score,
                        freshness_score, info_density_score, noise_score,
                        final_score, is_noise)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (c["document_id"], company_key, c.get("source_type", ""),
                     c.get("source_url", ""), c.get("title", ""),
                     c["chunk_text"], c.get("chunk_type", "unknown"),
                     c.get("token_estimate", 0),
                     c.get("source_score", 0), c.get("entity_score", 0),
                     c.get("field_relevance_score", 0), c.get("freshness_score", 0),
                     c.get("info_density_score", 0), c.get("noise_score", 0),
                     c.get("final_score", 0), c.get("is_noise", 0)),
                )
                chunk_ids.append(cur.lastrowid)

        conn.commit()
        conn.close()

        if chunk_ids:
            noise_count = sum(1 for c in scored if c.get("is_noise"))
            print(f"[document_chunks] {company_key}: {len(chunk_ids)} chunks "
                  f"from {len(docs)} docs ({noise_count} noise)")
        return chunk_ids
    except Exception as e:
        print(f"[document_chunks] build failed: {e}")
        return []


def _extract_evidence_spans_from_chunks(
    company_key: str, chunk_ids: list[int], field_rows: list[dict] | None = None
) -> list[int]:
    """从高分 chunk 预抽取 evidence_spans（必须在 LLM 前完成）。

    对每个 field_key，从相关 chunk 中提取引用片段并创建 evidence_span。
    返回 evidence_span ID 列表。
    """
    if not config.DOCUMENT_CHUNKING_ENABLED or not chunk_ids:
        return []

    try:
        import sqlite3
        from research.evidence_extractor import extract_field_evidence

        db_path = config.DB_PATH_RESEARCH
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'"
        ).fetchone()
        if not exists:
            conn.close()
            return []

        # 只取非噪音 + 高分的 chunk
        placeholders = ", ".join("?" for _ in chunk_ids)
        rows = conn.execute(
            f"""SELECT * FROM document_chunks
                WHERE id IN ({placeholders})
                AND is_noise=0 AND final_score >= 0.35
                ORDER BY final_score DESC LIMIT 200""",
            chunk_ids,
        ).fetchall()

        span_ids = []

        if field_rows:
            # 如果有 field_rows，每字段创建 evidence_spans
            field_keys = [r.get("field_key", "") for r in field_rows]
            field_key_set = set(field_keys)

            for row in rows:
                chunk = dict(row)
                chunk_text = chunk.get("chunk_text", "")
                if not chunk_text.strip():
                    continue

                # 为每个可能相关的 field_key 创建 evidence_span
                for fk in list(field_key_set)[:5]:  # 限制每 chunk 的字段数
                    # 简单关键词检查
                    fk_tokens = set(fk.replace("_", " ").lower().split())
                    if any(t in chunk_text.lower() for t in fk_tokens if len(t) >= 3):
                        span_id = extract_field_evidence(
                            db_path,
                            document_id=chunk["document_id"],
                            company_key=company_key,
                            field_key=fk,
                            quote_text=chunk_text[:500],
                            normalized_fact=chunk_text[:200],
                            confidence=0.6,  # 预抽取有中等置信度
                            created_by_agent="chunk_pre_extractor",
                        )
                        if span_id > 0:
                            span_ids.append(span_id)

        conn.close()

        if span_ids:
            print(f"[evidence_spans] {company_key}: {len(span_ids)} pre-extracted "
                  f"from {len(rows)} chunks")
        return span_ids
    except Exception as e:
        print(f"[evidence_spans] pre-extract failed: {e}")
        return []


def _build_packed_context_for_l0(
    raw: dict, company_key: str, run_id: str = ""
) -> dict:
    """为 L0 构建 packed_context。"""
    if not config.CONTEXT_PACKER_ENABLED:
        return {}
    try:
        packed = pack_context(
            config.DB_PATH_RESEARCH,
            company_key=company_key,
            target_type="l0",
            target_key="l0_full",
            budget_tokens=config.L0_CONTEXT_BUDGET_TOKENS,
            run_id=run_id,
        )
        if packed.get("chunks"):
            print(f"[context_packer] L0: {packed['used_tokens']}/{packed['budget_tokens']} "
                  f"tokens, {len(packed['chunks'])} chunks, "
                  f"{packed['dropped_count']} dropped")
        return packed
    except Exception as e:
        print(f"[context_packer] L0 pack failed: {e}")
        return {}


# ── 主入口 ─────────────────────────────────────

def run_pipeline(company_name: str, company_url: str,
                 progress_callback=None, job_id: str = None,
                 cancel_token=None,
                 research_options: dict | None = None) -> list[int]:
    """执行完整研究流水线，返回插入的记录 ID 列表"""
    t0 = time.time()

    def _check_cancel():
        if callable(cancel_token) and cancel_token():
            raise PipelineCancelledError("用户取消研究")

    # Step 1: 采集
    research_options = research_options or {}
    raw = _collect_via_adapters(
        company_name, company_url, progress_callback, job_id=job_id,
        research_options=research_options,
        cancel_token=cancel_token,
    )
    _check_cancel()
    raw["_evidence_pool"] = _build_evidence_pool(raw)
    _check_cancel()
    _persist_evidence(company_name, raw["_evidence_pool"])

    t1 = time.time()
    _report(
        progress_callback,
        "采集完成",
        {
            "message": f"采集完成（{t1 - t0:.1f}s），{len(raw['_evidence_pool'])} 条有效证据",
            "sources": raw.get("_source_summary", {}),
        },
        job_id=job_id,
    )
    _check_cancel()

    # P2: 采集审计 + 缺口预补采（LLM 分析之前，确保证据充分）
    tavily_enabled = research_options.get("tavily_search", True)
    if (
        tavily_enabled
        and research_options.get("gap_refetch", config.COLLECTION_ENABLE_GAP_REFETCH)
        and "_source_summary" in raw
    ):
        src = raw.get("_source_summary", {})
        tavily_src = src.get("tavily", {})
        unique_urls = tavily_src.get("unique_url_count", 0)
        intents_found = tavily_src.get("intent_count", 0)
        if _needs_pre_gap_refetch(raw):
            identity_display = raw.get("display_name", company_name)
            identity_host = raw.get("website_host", "")
            identity_root = identity_host.split(".")[0] if identity_host else ""
            # 预补采：用 search_plan 的宽泛覆盖生成额外 query
            from search_plan import build_search_plan as _plan
            pre_plan = _plan(identity_display, identity_root, identity_host,
                           raw.get("aliases", []))
            # 取前 6 组核心意图 query 做补充
            extra = [{"query": q.query, "intent": q.intent}
                    for q in pre_plan.tavily_queries[:6]]
            if extra:
                _report(progress_callback, "补采", {
                    "message": f"采集不足({unique_urls}URL/{intents_found}意图)，预补采 {len(extra)} 组",
                }, job_id=job_id)
                supplement = _search_tavily(extra, progress_callback, job_id)
                _merge_tavily_results(raw, supplement)
                raw["_evidence_pool"] = _build_evidence_pool(raw)
                _persist_evidence(company_name, raw["_evidence_pool"])
                raw["_pre_gap_refetch"] = {"extra_queries": len(extra), "reason": "low_initial_recall"}
                _report(progress_callback, "补采", {
                    "message": f"预补采完成，证据池更新为 {len(raw['_evidence_pool'])} 条",
                }, job_id=job_id)
        else:
            raw["_pre_gap_refetch"] = {"extra_queries": 0, "reason": "website_or_secondary_sources_sufficient"}

    # ── 噪音与上下文治理: source_documents → clean → chunk → rank → evidence_spans → pack ──
    company_key = raw.get("company_key", company_name.lower())
    chunk_ids: list[int] = []
    if research_options.get("document_chunking", config.DOCUMENT_CHUNKING_ENABLED):
        _check_cancel()
        _report(progress_callback, "文档治理", "清洗 + 切块 + 打分...", job_id=job_id)
        doc_ids = _persist_source_documents_from_raw(raw, run_id=job_id or "")
        _check_cancel()
        chunk_ids = _build_document_chunks_for_run(
            company_key, doc_ids,
            display_name=raw.get("display_name", ""),
            website_host=raw.get("website_host", ""),
            aliases=raw.get("aliases", []))
        if chunk_ids:
            # 预抽取 evidence_spans（必须在 LLM 前完成）
            span_ids = _extract_evidence_spans_from_chunks(
                company_key, chunk_ids)
            # 构建 L0 packed_context
            if research_options.get("context_packer", config.CONTEXT_PACKER_ENABLED):
                packed = _build_packed_context_for_l0(raw, company_key, run_id=job_id or "")
            else:
                packed = {}
            raw["_packed_context"] = packed
            quality_noise = sum(1 for c in packed.get("chunks", [])
                              if c.get("is_noise"))
            _report(progress_callback, "文档治理", {
                "message": (f"文档治理完成: {len(doc_ids)} docs → "
                           f"{len(chunk_ids)} chunks → "
                           f"{len(packed.get('chunks', []))} packed "
                           f"({packed.get('used_tokens', 0)}/{packed.get('budget_tokens', 0)} tokens, "
                           f"{packed.get('dropped_count', 0)} dropped)"),
            }, job_id=job_id)
        else:
            _report(progress_callback, "文档治理",
                    "跳过（无有效文档或表未迁移）", job_id=job_id)
            raw["_packed_context"] = {}

    # ── Auto-trigger market_intelligence if no data exists ──
    try:
        from research.market_data_bridge import MarketDataBridge
        bridge = MarketDataBridge()
        existing = bridge.fetch_market_context(company_key)
        if not existing and raw.get("website_host"):
            _report(progress_callback, "市场情报", "自动运行市场情报采集...", job_id=job_id)
            result = subprocess.run(
                [sys.executable, "-m", "market_intelligence",
                 "--company", raw.get("display_name", company_name),
                 "--domain", raw.get("website_host", ""),
                 "--no-crunchbase",
                 "--timeout", "90"],
                capture_output=True, text=True, timeout=120,
                cwd=str(Path(__file__).resolve().parent.parent)
            )
            if result.returncode != 0:
                print(f"[MarketIntelligence] auto-trigger failed: {result.stderr[:200]}", flush=True)
    except Exception:
        pass  # Non-blocking — pipeline continues without market data

    # Step 2: AI 分析
    _check_cancel()
    _report(progress_callback, "分析", "开始 4 层 LLM 分析...", job_id=job_id)
    records = llm_analysis(
        company_name, company_url, raw, progress_callback,
        job_id=job_id, cancel_token=cancel_token,
    )
    errors = [r for r in records if r.get("_error")]
    if errors:
        details = ", ".join(f"{r.get('version', '?')}: {r.get('_error')}" for r in errors)
        raise RuntimeError(f"L3 字段提取失败: {details}")
    _check_cancel()
    _validate_record_identity(records, company_url)
    records = _validate_records(records)

    t2 = time.time()
    _report(progress_callback, "分析完成", f"({t2 - t1:.1f}s)", job_id=job_id)

    # P0: L3 值缺口驱动的补采（最多一次，最多4条query）。
    # 此时字段还未写库/解析/绑定证据，不能使用证据状态型 CoverageGate。
    if tavily_enabled and research_options.get("gap_refetch", config.COLLECTION_ENABLE_GAP_REFETCH):
        try:
            standard = next((r for r in records if r.get("version") == "standard"), None)
            if not standard:
                raise RuntimeError("L3 standard 版结果缺失，无法评估补采缺口")

            l3_gap_report = _evaluate_l3_value_gaps(standard)
            print(f"[l3_gap] {company_name}: usable={l3_gap_report['usable_field_count']}/"
                  f"{l3_gap_report['field_count']}, "
                  f"should_refetch={l3_gap_report['should_refetch']}")

            if l3_gap_report["should_refetch"]:
                _report(progress_callback, "补采", {
                    "message": f"L3关键字段缺失触发补采: "
                              f"missing={l3_gap_report['missing_required_fields']}",
                }, job_id=job_id)

                # 生成定向补采 query（最多4条）
                identity_display = raw.get("display_name", company_name)
                identity_host = raw.get("website_host", "")
                identity_root = identity_host.split(".")[0] if identity_host else ""

                gap_fields = l3_gap_report["missing_required_fields"][:8]
                if gap_fields:
                    gap_queries = []
                    for fk in gap_fields[:4]:  # 最多4条
                        q = f'"{identity_display}" {fk.replace("_", " ")}'
                        gap_queries.append({"query": q, "intent": "gap_refetch"})

                    if gap_queries:
                        supplement = _search_tavily(gap_queries, progress_callback, job_id)
                        _merge_tavily_results(raw, supplement)
                        raw["_evidence_pool"] = _build_evidence_pool(raw)
                        _persist_evidence(company_name, raw["_evidence_pool"])

                        # 重建文档治理
                        if research_options.get("document_chunking", config.DOCUMENT_CHUNKING_ENABLED):
                            doc_ids = _persist_source_documents_from_raw(raw, run_id=job_id or "")
                            chunk_ids = _build_document_chunks_for_run(
                                company_key, doc_ids,
                                display_name=raw.get("display_name", ""),
                                website_host=raw.get("website_host", ""),
                                aliases=raw.get("aliases", []))
                            if research_options.get("context_packer", config.CONTEXT_PACKER_ENABLED):
                                raw["_packed_context"] = _build_packed_context_for_l0(
                                    raw, company_key, run_id=job_id or "")
                            else:
                                raw["_packed_context"] = {}

                        # 重新 L0-L3
                        _report(progress_callback, "分析", "补采后重新 4 层 LLM 分析...", job_id=job_id)
                        records = llm_analysis(
                            company_name, company_url, raw, progress_callback,
                            job_id=job_id, cancel_token=cancel_token,
                        )
                        errors = [r for r in records if r.get("_error")]
                        if errors:
                            details = ", ".join(f"{r.get('version', '?')}: {r.get('_error')}" for r in errors)
                            raise RuntimeError(f"补采后 L3 字段提取失败: {details}")
                        _check_cancel()
                        _validate_record_identity(records, company_url)
                        records = _validate_records(records)
                        raw["_gap_refetch_applied"] = True
                        _report(progress_callback, "分析完成", f"补采后重分析完成", job_id=job_id)
            else:
                print(f"[l3_gap] {company_name}: required L3 values present, no refetch needed")
                raw["_gap_refetch_applied"] = False
        except Exception as e:
            raise RuntimeError(f"L3 补采缺口评估失败: {e}") from e

    # Step 3: 写库
    _check_cancel()
    _report(progress_callback, "写库", "写入数据库...", job_id=job_id)
    # SPEC v3: 实体表主写入，宽表仅兼容保留。不再写入 research 宽表。
    # 旧代码: ids = database.save_research_records(config.DB_PATH_RESEARCH, records)
    ids = []

    # Step 3.5: 写入字段级表（解耦架构 — 字段不天然属于任何卡片）
    from services.field_service import split_research_to_fields
    from repositories.field_repo import insert_research_fields_batch
    all_extracted_fields = {}
    for record in records:
        _check_cancel()
        version = record.get('version', 'standard')
        field_record = {
            **record,
            "company_name": company_name,
            "company_key": raw.get("company_key", ""),
            "display_name": raw.get("display_name", company_name),
        }
        field_rows = split_research_to_fields(field_record, version)
        if field_rows:
            # Collect fields for post-write snapshot
            for fr in field_rows:
                fk = fr.get("field_key", "")
                fv = fr.get("field_value", "")
                if fk:
                    all_extracted_fields[fk] = fv
            insert_research_fields_batch(config.DB_PATH_RESEARCH, field_rows)
            # LLM后、分辨率前：用字段值匹配chunks创建强证据绑定
            if chunk_ids:
                _bind_field_value_evidence(
                    config.DB_PATH_RESEARCH,
                    raw.get("company_key", ""),
                    company_name,
                    field_rows,
                    chunk_ids,
                    run_id=job_id or "",
                )
            # 字段分辨率状态标记
            _mark_and_log_fields(config.DB_PATH_RESEARCH, company_name,
                                 version, field_rows, run_id=job_id or "")
            # P0: 事后弱绑定（source_documents → evidence_spans, 不得 confirmed）
            if research_options.get("evidence_span_binding", config.EVIDENCE_SPAN_BINDING_ENABLED):
                _bind_posthoc_weak_evidence(
                    config.DB_PATH_RESEARCH,
                    raw.get("company_key", ""),
                    company_name,
                    field_rows,
                    raw.get("_evidence_pool", []),
                    run_id=job_id or "",
                )
            # P2: ForumModerator 字段质量检查
            _run_forum_moderation(
                config.DB_PATH_RESEARCH, company_name, version, field_rows)

    # ── L1/L2 结构化字段写入（非阻断）──
    from repositories.field_repo import upsert_final_field
    try:
        if competitive_matrix:
            import json as _json
            cm_json = _json.dumps(competitive_matrix.model_dump(),
                                  ensure_ascii=False)
            all_extracted_fields["competitors_structured"] = cm_json
            all_extracted_fields["competitive_position"] = \
                competitive_matrix.target_company_position
            # Persist to research_fields for render contract consumption
            _field_rows = [{
                "company_name": company_name, "company_key": company_key,
                "version": "standard", "field_key": "competitors_structured",
                "field_value": cm_json, "value_type": "json_text",
                "resolution_status": "llm_extracted",
            }, {
                "company_name": company_name, "company_key": company_key,
                "version": "standard", "field_key": "competitive_position",
                "field_value": competitive_matrix.target_company_position,
                "value_type": "text", "resolution_status": "llm_extracted",
            }]
            insert_research_fields_batch(config.DB_PATH_RESEARCH, _field_rows)
    except Exception:
        pass

    try:
        if business_canvas:
            import json as _json
            bc_json = _json.dumps(business_canvas.model_dump(),
                                  ensure_ascii=False)
            all_extracted_fields["business_canvas"] = bc_json
            # Extract individual fields
            moat_json = _json.dumps(
                [m.model_dump() for m in business_canvas.moat_dimensions],
                ensure_ascii=False)
            loops_json = _json.dumps(
                [g.model_dump() for g in business_canvas.growth_loops],
                ensure_ascii=False)
            all_extracted_fields["moat_dimensions"] = moat_json
            all_extracted_fields["growth_loops"] = loops_json
            all_extracted_fields["unit_economics"] = _json.dumps(
                business_canvas.unit_economics.model_dump(), ensure_ascii=False)
            _field_rows = [{
                "company_name": company_name, "company_key": company_key,
                "version": "standard", "field_key": "business_canvas",
                "field_value": bc_json, "value_type": "json_text",
                "resolution_status": "llm_extracted",
            }, {
                "company_name": company_name, "company_key": company_key,
                "version": "standard", "field_key": "moat_dimensions",
                "field_value": moat_json, "value_type": "json_text",
                "resolution_status": "llm_extracted",
            }, {
                "company_name": company_name, "company_key": company_key,
                "version": "standard", "field_key": "growth_loops",
                "field_value": loops_json, "value_type": "json_text",
                "resolution_status": "llm_extracted",
            }, {
                "company_name": company_name, "company_key": company_key,
                "version": "standard", "field_key": "unit_economics",
                "field_value": _json.dumps(
                    business_canvas.unit_economics.model_dump(),
                    ensure_ascii=False),
                "value_type": "json_text", "resolution_status": "llm_extracted",
            }]
            insert_research_fields_batch(config.DB_PATH_RESEARCH, _field_rows)
    except Exception:
        pass

    # ── TimeSeriesSnapshotter: 字段快照（非阻断）──
    from research.time_series import TimeSeriesSnapshotter
    try:
        snapshotter = TimeSeriesSnapshotter()
        fields_for_snapshot = {}
        for fk, fv in all_extracted_fields.items():
            fields_for_snapshot[fk] = {
                "value": fv,
                "resolution_status": "llm_extracted",
            }
        snapshotter.snapshot(
            company_key, fields_for_snapshot,
            snapshot_type="fields_only",
            research_run_id=job_id,
        )
    except Exception:
        pass  # Snapshot failure must not block the pipeline

    t3 = time.time()

    # P0: CoverageGate 评估
    if config.FIELD_MANIFEST_REQUIRED:
        try:
            from research.coverage_gate import CoverageGate
            from research.field_status import _load_manifest
            from research.field_resolver import resolve_all

            manifest = _load_manifest()
            gate = CoverageGate(manifest, card_schema_fields=[])

            # 收集所有版本的已解析字段
            all_field_map = {}
            all_evidence = {}
            for record in records:
                version = record.get('version', 'standard')
                field_rows = split_research_to_fields(
                    {**record, "company_name": company_name,
                     "company_key": raw.get("company_key", ""),
                     "display_name": raw.get("display_name", company_name)},
                    version,
                )
                for fr in field_rows:
                    fk = fr.get("field_key", "")
                    fv = fr.get("field_value", "")
                    if fk not in all_field_map or all_field_map[fk] == "暂缺":
                        all_field_map[fk] = fv

            resolved_field_map = resolve_all(all_field_map, manifest, evidence_map={})

            runtime_sec = time.time() - t0
            tokens_used = len(raw.get("_packed_context", {}).get("chunks", []))

            coverage_report = gate.evaluate(
                resolved_field_map, evidence_map={},
                runtime_seconds=runtime_sec,
                tokens_used=tokens_used,
            )

            print(f"[coverage] {company_name}: score={coverage_report.coverage_score:.2f}, "
                  f"confirmed_ratio={coverage_report.confirmed_ratio:.2f}, "
                  f"should_refetch={coverage_report.should_refetch}")
            if coverage_report.missing_required_fields:
                print(f"  missing_required: {coverage_report.missing_required_fields}")
            if coverage_report.weak_fields:
                print(f"  weak_fields: {coverage_report.weak_fields}")
            if coverage_report.private_metric_fields:
                pm_summary = {k: v for k, v in coverage_report.private_metric_fields.items()}
                print(f"  private_metrics: {pm_summary}")

            raw["_coverage_report"] = {
                "coverage_score": coverage_report.coverage_score,
                "confirmed_ratio": coverage_report.confirmed_ratio,
                "should_refetch": coverage_report.should_refetch,
                "missing_required": coverage_report.missing_required_fields,
            }
        except Exception as e:
            print(f"[coverage] evaluation failed (non-fatal): {e}")

    # P3: CardValueBuilder — 从实体表生成 final_card_values
    if config.ENTITY_TABLES_PRIMARY:
        try:
            from services.card_value_builder import CardValueBuilder

            builder = CardValueBuilder(config.DB_PATH_RESEARCH)
            card_values = builder.build_card_values(
                raw.get("company_key", company_name.lower()),
                card_schema_version="v3",
            )
            if card_values:
                count = builder.write_to_final_card_values(
                    raw.get("company_key", company_name.lower()),
                    job_id or "",
                    card_values,
                )
                print(f"[card_values] {company_name}: {count} final_card_values written")
        except Exception as e:
            print(f"[card_values] build failed (non-fatal): {e}")

    # Step 4: 图片采集
    _check_cancel()
    if research_options.get("image_collection", True):
        def _clean(v, default=""):
            """过滤 L3 占位符，避免「暂缺」进入图片搜索查询"""
            if v is None:
                return default
            s = str(v).strip()
            return default if s in ("暂缺", "") else v

        standard_record = records[0] if records else {}
        company_data = {
            "company_name": company_name,
            "company_key": raw.get("company_key", ""),
            "display_name": raw.get("display_name", company_name),
            "company_url": company_url,
            "website_url": company_url,
            "location": _clean(standard_record.get("location")),
            "other_products": _clean(standard_record.get("other_products"), default=[]),
            "competitors": _clean(standard_record.get("competitors"), default=[]),
            "main_product_name": _clean(standard_record.get("main_product_name")),
            "main_product_img_src": _clean(standard_record.get("main_product_img_src")),
            "office_photo_hints": _clean(standard_record.get("office_photo_hints"), default={}),
        }
        try:
            from asset_pipeline import collect_image_variants_pipeline
            image_results = collect_image_variants_pipeline(
                config.DB_PATH_ASSETS, config.IMAGES_DIR, company_name, company_data,
                progress_callback=progress_callback, job_id=job_id,
            )
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[图片采集异常] {company_name}: {tb}", flush=True)
            _report(progress_callback, "图片采集",
                    {"message": f"图片采集异常：{e}", "card": 0, "total": 4},
                    job_id=job_id)
            image_results = {}

        total_images = sum(image_results.values())
        _report(progress_callback, "图片采集完成",
                {"message": f"共 {total_images} 张候选图"},
                job_id=job_id)
    else:
        _report(progress_callback, "图片采集跳过",
                {"message": "已按研究选项跳过图片采集"},
                job_id=job_id)

    t4 = time.time()
    _report(progress_callback, "完成", f"总耗时 {t4 - t0:.1f}s, IDs: {ids}", job_id=job_id)

    # 持久化采集审计数据到 research_jobs（研究结束后仍可追溯）
    if job_id:
        try:
            src_summary = raw.get("_source_summary", {})
            source_audit = {
                "company_key": raw.get("company_key", ""),
                "display_name": raw.get("display_name", ""),
                "search_terms": raw.get("aliases", []),
                "total_query_count": len(raw.get("tavily", [])),
                "unique_url_count": sum(
                    s.get("unique_url_count", 0) for s in src_summary.values()
                    if isinstance(s, dict)
                ),
                "sources": {
                    name: {
                        "status": s.get("status", "unknown"),
                        "query_count": s.get("query_count", s.get("count", 0)),
                        "raw_count": s.get("count", 0),
                        "unique_count": s.get("unique_url_count", s.get("count", 0)),
                        "detail": s.get("detail", ""),
                    }
                    for name, s in src_summary.items() if isinstance(s, dict)
                },
                "warnings": raw.get("_source_warnings", []),
                "pre_gap_refetch": raw.get("_pre_gap_refetch", {}),
                "gap_refetch": raw.get("_gap_info", {}),
            }
            database.update_job(config.DB_PATH_RESEARCH, job_id,
                              detail=json.dumps(source_audit, ensure_ascii=False))
        except Exception:
            pass

    return ids
