"""字段服务 — 字段拆分、版本比较、定稿"""
from __future__ import annotations
import json
from typing import Optional

from repositories.field_repo import (
    insert_research_fields_batch, get_research_fields,
    upsert_final_field, get_final_fields, get_final_field_value,
    get_final_card_values,
    confirm_all_fields, set_field_status,
)

_VALUE_TYPE_BY_CONTRACT_TYPE = {
    "text": "text",
    "long_text": "text",
    "url": "url",
    "json_text": "json",
    "number": "number",
    "enum": "enum",
}

_V3_PAGE_FIELDS = {
    1: ["company_name", "company_type"],
    2: ["market_track", "market_subtrack",
        "market_landscape_summary", "market_landscape_top_players",
        "market_size_value", "market_size_currency", "market_size_year",
        "market_cagr", "tam_value", "tam_currency", "tam_year",
        "location", "founded_date", "core_business", "core_competency",
        "funding_info", "funding_rounds", "company_achievements",
        "industry_positioning"],
    3: ["main_product_name", "product_pain_points", "product_core_features",
        "product_usage_playbook", "product_tech_stack",
        "regional_market_focus", "mau", "mau_as_of",
        "retention_definition", "retention_rate", "pricing_summary",
        "pricing_tiers"],
    4: ["founder_name", "founder_edu", "founder_bg",
        "founder_achievement", "team_size", "team_highlight"],
    5: ["ideal_customer_profile", "customer_segment_primary",
        "customer_segment_secondary", "customer_names",
        "customer_selection_reasons", "customer_choice_evidence"],
    6: ["ecosystem_niche", "revenue_model", "pricing_strategy",
        "ltv", "cac", "ltv_cac_ratio", "ltv_cac_is_benchmark",
        "ltv_cac_benchmark_source"],
    7: ["growth_strategy", "gtm_strategy", "cold_start",
        "growth_flywheel", "acquisition_channels"],
    8: ["competitors_top3", "competitive_position",
        "differentiated_opportunity", "competitive_advantages"],
}

_FIELD_PAGE_META = {
    field_key: {"page_no": page_no, "sort_order": sort_order}
    for page_no, fields in _V3_PAGE_FIELDS.items()
    for sort_order, field_key in enumerate(fields)
}

_PLACEHOLDER_VALUES = {"", "暂缺", "待研究数据", "None", "none", "null", "NULL", "[]", "{}"}

# Status → confidence_level mapping (mirrors render_assembler._STATUS_TO_CONFIDENCE_LEVEL)
_STATUS_TO_CONFIDENCE_LEVEL = {
    "confirmed": "verified",
    "derived": "estimated",
    "proxy": "estimated",
    "industry_avg": "benchmark",
    "llm_extracted": "estimated",
    "llm_located": "estimated",
    "manual_needed": "unavailable",
    "unavailable": "unavailable",
    "not_applicable": "unavailable",
    "conflict": "estimated",
    "draft": "unavailable",
    "hidden": "unavailable",
}


def _map_status_to_confidence_level(status: str) -> str:
    """Map internal resolution status to user-facing confidence_level."""
    if not status:
        return "unavailable"
    return _STATUS_TO_CONFIDENCE_LEVEL.get(status, "unavailable")


def _is_usable_value(value) -> bool:
    if value is None:
        return False
    return str(value).strip() not in _PLACEHOLDER_VALUES


def load_field_contract() -> dict:
    """加载 fields.json 契约"""
    from pathlib import Path
    contract_path = Path(__file__).resolve().parent.parent.parent / "contracts" / "fields.json"
    with open(contract_path) as f:
        return json.load(f)


# 字段值可以保留英文的 field_key（专有名词、URL、代码、枚举值等）
_ENGLISH_OK_FIELDS = frozenset({
    'company_name', 'website_url', 'company_key', 'main_product_name',
    'founder_name', 'founder_edu', 'main_product_img_src',
    'company_type', 'pricing_model', 'stack_layer',
    'funding_stage', 'customer_segment_type',
    'ecosystem_niche', 'market_track', 'market_subtrack',
    'ai_model_dependency', 'workflow_integration_level',
    'data_flywheel', 'proprietary_data_asset',
    'incumbent_direct_competitor', 'inference_cost_exposure',
    'gtm_motion', 'pricing_strategy',
    'competitors_top3', 'market_landscape_top_players',
})


def _is_predominantly_english(text: str) -> bool:
    """检测文本是否以英文为主（拉丁字母占比 > 60%，且包含完整英文句子）。"""
    import re
    if not text or len(text) < 20:
        return False
    cjk = len(re.findall(r'[一-鿿㐀-䶿]', text))
    latin = len(re.findall(r'[a-zA-Z]', text))
    total = cjk + latin
    if total == 0:
        return False
    # 拉丁字母 > 60% 且至少有 3 个英文单词
    if latin / total <= 0.60:
        return False
    words = re.findall(r'[a-zA-Z]{3,}', text)
    return len(words) >= 3


def _translatable_field_value(field_key: str, value: str) -> str | None:
    if field_key in _ENGLISH_OK_FIELDS:
        return None
    if not value or not isinstance(value, str):
        return None
    if value.strip() in ('', '暂缺'):
        return None
    stripped = value.strip()
    if stripped.startswith('[') or stripped.startswith('{'):
        return None
    if not _is_predominantly_english(stripped):
        return None
    return stripped


def translate_field_value_if_needed(field_key: str, value: str) -> str:
    """如果字段值以英文为主，翻译为中文后返回。

    翻译应在采集阶段通过 TRANSLATE_ON_COLLECTION 完成，
    这里作为字段生成后的兜底，防止英文值穿透到前端。
    保留英文的字段（专有名词等）见 _ENGLISH_OK_FIELDS。
    """
    stripped = _translatable_field_value(field_key, value)
    if not stripped:
        return value

    import logging
    _log = logging.getLogger("field_service")
    try:
        from deepseek_client import translate_to_chinese
        translated = translate_to_chinese([stripped])
    except Exception as exc:
        _log.warning(
            "field %s English value fallback translation failed: %s",
            field_key, exc,
        )
        return value

    if translated and translated[0] and translated[0] != stripped:
        return translated[0]

    _log.warning(
        "field %s has English value (%d chars) and translation returned original value.",
        field_key, len(stripped),
    )
    return value


def translate_field_rows_if_needed(field_rows: list[dict]) -> list[dict]:
    """Batch-translate English field values in-place before DB writes."""
    to_translate: list[tuple[int, str]] = []
    for idx, row in enumerate(field_rows or []):
        text = _translatable_field_value(
            row.get("field_key", ""),
            row.get("field_value", ""),
        )
        if text:
            to_translate.append((idx, text))

    if not to_translate:
        return field_rows

    import logging
    _log = logging.getLogger("field_service")
    texts = [text for _, text in to_translate]
    try:
        from deepseek_client import translate_to_chinese
        translated = translate_to_chinese(texts)
    except Exception as exc:
        _log.warning("batch field translation failed: %s", exc)
        return field_rows

    for (idx, original), result in zip(to_translate, translated):
        if result and result != original:
            field_rows[idx]["field_value"] = result
        else:
            _log.warning(
                "field %s has English value (%d chars) and translation returned original value.",
                field_rows[idx].get("field_key", ""),
                len(original),
            )
    return field_rows


def split_research_to_fields(research_row: dict, version: str = "standard") -> list[dict]:
    """将 research 宽表一行拆分为 research_fields 列表（按 fields.json 契约）

    P0: 输出必须包含 company_key 和 display_name，防止 Limitless/limitless/limitless.ai 分裂。
    """
    contract = load_field_contract()
    result = []
    company_name = research_row.get("company_name", "")
    company_key = research_row.get("company_key", "") or company_name.lower()
    display_name = research_row.get("display_name", company_name)
    for group in contract.get("groups", []):
        for field_def in group.get("fields", []):
            key = field_def["field_key"]
            value = research_row.get(key)
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                field_value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, str):
                field_value = value
            else:
                field_value = str(value)
            result.append({
                "company_name": company_name,
                "company_key": company_key,
                "display_name": display_name,
                "version": version,
                "field_key": key,
                "field_label": field_def.get("field_label", key),
                "field_value": field_value,
                "source_type": "llm_extract",
                "confidence": "medium",
                "value_type": _VALUE_TYPE_BY_CONTRACT_TYPE.get(field_def.get("type"), "text"),
                **_FIELD_PAGE_META.get(key, {}),
            })
    return result


def get_field_versions(db_path_research: str, company_name: str) -> dict[str, dict[str, str]]:
    """返回 {field_key: {standard: "...", business: "...", spread: "..."}}

    包含所有版本（即使值为空），让前端决定显示策略。
    json_text 字段的 [] / {} 是合法 LLM 返回，不应在后端过滤。
    """
    versions = {}
    for ver in ("standard", "business", "spread"):
        fields = get_research_fields(db_path_research, company_name, ver)
        for f in fields:
            value = f.get("field_value", "")
            if value is not None and str(value).strip() not in ("",):
                versions.setdefault(f["field_key"], {})[ver] = value
    return versions


def get_fields_with_versions(db_path_research: str, db_path_final: str,
                             company_name: str,
                             card_values_db_path: Optional[str] = None) -> list[dict]:
    """返回完整的字段列表（含三版本 + 定稿状态）。

    定稿值优先级: final_fields（人工保存）→ final_card_values（研究读模型）→ research_fields。
    """
    contract = load_field_contract()
    versioned = get_field_versions(db_path_research, company_name)
    research_rows = []
    for ver in ("standard", "business", "spread"):
        research_rows.extend(get_research_fields(db_path_research, company_name, ver))
    final_fields = {f["field_key"]: f for f in get_final_fields(db_path_final, company_name)}

    # SPEC v3: 加载 final_card_values 按 field_key 索引（取首张卡的值）
    card_value_map: dict[str, dict] = {}
    try:
        card_values_db = card_values_db_path or db_path_final
        candidate_keys = [company_name.lower()]
        for row in research_rows:
            ckey = str(row.get("company_key") or "").strip()
            if ckey and ckey not in candidate_keys:
                candidate_keys.insert(0, ckey)
        for company_key in candidate_keys:
            for cv in get_final_card_values(card_values_db, company_key):
                fk = cv.get("field_key", "")
                value = cv.get("field_value") or cv.get("final_value")
                if fk and fk not in card_value_map and _is_usable_value(value):
                    card_value_map[fk] = cv
    except Exception:
        pass

    result = []
    for group in contract.get("groups", []):
        group_fields = []
        for field_def in group.get("fields", []):
            key = field_def["field_key"]
            vers = versioned.get(key, {})
            final = final_fields.get(key, {})
            cv = card_value_map.get(key, {})

            # 人工定稿值必须优先，否则保存后会被 final_card_values 旧读模型覆盖。
            cv_value = cv.get("field_value") or cv.get("final_value")
            if _is_usable_value(final.get("final_value")):
                final_value = final.get("final_value")
            elif _is_usable_value(cv_value):
                final_value = cv_value
            else:
                final_value = vers.get("standard", "")

            # 人工定稿状态优先，回退 final_card_values resolution_status。
            cv_status = cv.get("resolution_status") or cv.get("status")
            final_status = final.get("status") or cv_status or "draft"

            # ── 轻量展示 fallback：cold_start/growth_flywheel/acquisition_channels ──
            # 字段本身为空时，从 gtm_strategy 或 ecosystem_niche 提供参考摘要（不写库）
            # 每个字段使用不同的来源优先顺序，避免三个字段共用同一段摘要
            fallback_ref: dict[str, str] = {}
            _FALLBACK_SOURCE_PREFERENCE = {
                "cold_start":           [("gtm_strategy", "standard"), ("ecosystem_niche", "standard")],
                "growth_flywheel":      [("ecosystem_niche", "standard"), ("gtm_strategy", "business")],
                "acquisition_channels": [("gtm_strategy", "business"), ("ecosystem_niche", "business")],
            }
            if key in _FALLBACK_SOURCE_PREFERENCE and not _is_usable_value(final_value):
                has_usable_version = any(
                    _is_usable_value(v) for v in vers.values()
                )
                if not has_usable_version:
                    for src_key, src_ver in _FALLBACK_SOURCE_PREFERENCE[key]:
                        src_vers = versioned.get(src_key, {})
                        src_val = src_vers.get(src_ver, "")
                        if not _is_usable_value(src_val):
                            # 回退到该来源的任意版本
                            for vk, vv in src_vers.items():
                                if _is_usable_value(vv):
                                    src_val = vv
                                    break
                        if _is_usable_value(src_val):
                            snippet = str(src_val)[:200]
                            last_period = max(snippet.rfind("。"), snippet.rfind(". "))
                            if last_period > 80:
                                snippet = snippet[:last_period + 1]
                            fallback_ref = {
                                "source_field": src_key,
                                "source_version": src_ver,
                                "snippet": snippet,
                            }
                            break
            # ── end fallback ──

            group_fields.append({
                "field_key": key,
                "field_label": field_def["field_label"],
                "type": field_def["type"],
                "group_key": group["group_key"],
                "versions": vers,
                "final_value": final_value,
                "status": final_status,
                "card_no": cv.get("card_no"),  # 该值所属卡片页码
                "confidence": cv.get("confidence_score") or cv.get("confidence"),
                "confidence_level": _map_status_to_confidence_level(final_status),
                **({"fallback_reference": fallback_ref} if fallback_ref else {}),
            })
        if group_fields:
            result.append({
                "group_key": group["group_key"],
                "group_label": group["group_label"],
                "fields": group_fields,
            })

    return result


def finalize_field(db_path_final: str, company_name: str, field_key: str,
                   final_value: str, status: str = "confirmed") -> bool:
    """定稿单个字段（写入 final_fields）"""
    contract = load_field_contract()
    label = field_key
    for group in contract.get("groups", []):
        for f in group.get("fields", []):
            if f["field_key"] == field_key:
                label = f["field_label"]
                break
    upsert_final_field(db_path_final, company_name, field_key, final_value,
                       field_label=label, status=status)
    return True


def batch_finalize(db_path_final: str, company_name: str,
                   field_values: dict[str, str]) -> int:
    """批量定稿字段"""
    count = 0
    for key, value in field_values.items():
        finalize_field(db_path_final, company_name, key, value)
        count += 1
    return count
