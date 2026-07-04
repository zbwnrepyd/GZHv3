"""AI layout copy generation for finalized card fields."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Callable

from repositories.card_config_repo import get_enabled_cards, get_card_items
from repositories.layout_repo import get_layout, save_layout
from services.card_config_service import create_default_cards_for_company
from services.field_service import get_fields_with_versions


_PLACEHOLDER_VALUES = {"", "暂缺", "待研究数据", "None", "none", "null", "NULL", "[]", "{}"}
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "layout-copy.md"
_HUMANIZER_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "humanizer-zh.md"


def generate_layout_copy_for_company(
    *,
    research_db_path: str,
    final_db_path: str,
    composition_db_path: str,
    template_db_path: str,
    company_name: str,
    card_set_key: str,
    call_llm: Callable[[str, str], str],
) -> dict:
    """Generate and persist three-paragraph markdown for each enabled card."""
    cards = get_enabled_cards(composition_db_path, company_name, card_set_key=card_set_key)
    if not cards:
        create_default_cards_for_company(composition_db_path, company_name, card_set_key=card_set_key)
        cards = get_enabled_cards(composition_db_path, company_name, card_set_key=card_set_key)
    if not cards:
        raise ValueError(f"未找到套卡 {card_set_key} 的卡片编排")

    fields_by_key = _load_fields_by_key(research_db_path, final_db_path, company_name)
    payload_cards = []
    pending = []
    for card in cards:
        items = get_card_items(
            composition_db_path,
            company_name,
            card["card_id"],
            card_set_key=card_set_key,
        )
        facts = []
        media = []
        for item in items:
            if item.get("item_type") == "media":
                item_key = item.get("item_key")
                if item_key:
                    media.append({
                        "asset_key": item_key,
                        "label": item.get("item_label") or item_key,
                        "display_role": item.get("display_role") or "",
                    })
                continue
            if item.get("item_type") != "field":
                continue
            field_key = item.get("item_key")
            field = fields_by_key.get(field_key or "")
            if not field:
                continue
            value = _best_value(field)
            if not _is_usable(value):
                continue
            if field.get("status") != "confirmed":
                pending.append({
                    "card_id": card["card_id"],
                    "field_key": field_key,
                    "label": field.get("label") or field_key,
                })
            facts.append({
                "field_key": field_key,
                "label": field.get("label") or item.get("item_label") or field_key,
                "value": value,
            })
        if facts:
            payload_cards.append({
                "card_id": card["card_id"],
                "card_title": card.get("card_title") or card["card_id"],
                "card_index": card.get("card_index"),
                "template_id": card.get("template_id") or "",
                "facts": facts,
                "media": media,
            })

    if pending:
        raise ValueError(f"仍有 {len(pending)} 个字段未定稿，请先全部保存")
    if not payload_cards:
        raise ValueError("没有可用于生成排版文案的已定稿字段")

    saved = []
    warnings = []
    for card in payload_cards:
        generated_card, warning = _generate_single_card_copy(card, call_llm)
        if warning:
            warnings.append(warning)
        paragraphs = _coerce_three_paragraphs(generated_card, card)
        paragraphs = _preserve_numeric_tokens(paragraphs, card["facts"])
        markdown = _compose_layout_markdown(paragraphs, card)
        existing = get_layout(template_db_path, company_name, card["card_id"])
        layout_json = existing.get("layout_json", {}) if existing else {}
        layout_json.update({
            "mode": "markdown_first",
            "markdown": markdown,
            "generated_copy": {
                "card_set_key": card_set_key,
                "source": "ai_layout_copy",
                "paragraph_count": 3,
            },
        })
        layout_json.setdefault("overrides", {})
        if card.get("template_id") and not layout_json.get("template_id"):
            layout_json["template_id"] = card["template_id"]
        if existing and existing.get("layout_json", {}).get("style"):
            layout_json["style"] = existing["layout_json"]["style"]
        save_layout(
            template_db_path,
            company_name,
            card["card_id"],
            layout_json,
            template_id=layout_json.get("template_id", card.get("template_id") or ""),
        )
        saved.append({
            "card_id": card["card_id"],
            "card_title": card["card_title"],
            "markdown": markdown,
        })

    return {
        "company_name": company_name,
        "card_set_key": card_set_key,
        "cards": saved,
        "warnings": warnings,
    }


def _load_fields_by_key(research_db_path: str, final_db_path: str, company_name: str) -> dict:
    groups = get_fields_with_versions(
        research_db_path,
        final_db_path,
        company_name,
        card_values_db_path=research_db_path,
    )
    result = {}
    for group in groups:
        for field in group.get("fields", []):
            result[field["field_key"]] = {
                "label": field.get("field_label") or field["field_key"],
                "versions": field.get("versions") or {},
                "final_value": field.get("final_value") or "",
                "status": field.get("status") or "draft",
            }
    return result


def _best_value(field: dict) -> str:
    final_value = field.get("final_value")
    if _is_usable(final_value):
        return str(final_value).strip()
    versions = field.get("versions") or {}
    for version in ("standard", "business", "spread"):
        if _is_usable(versions.get(version)):
            return str(versions[version]).strip()
    for value in versions.values():
        if _is_usable(value):
            return str(value).strip()
    return ""


def _is_usable(value) -> bool:
    if value is None:
        return False
    return str(value).strip() not in _PLACEHOLDER_VALUES


def _system_prompt() -> str:
    """第一步：elsewhere 风格串接字段成文。"""
    return _load_layout_copy_prompt()


@lru_cache(maxsize=1)
def _load_layout_copy_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _humaniser_system_prompt() -> str:
    """第二步：Humanizer-zh 去AI味。"""
    return _load_humanizer_zh_prompt()


@lru_cache(maxsize=1)
def _load_humanizer_zh_prompt() -> str:
    return _HUMANIZER_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _humanizer_zh_system_prompt() -> str:
    """公开接口，供测试验证 prompt 内容。"""
    return _humaniser_system_prompt()


def _generate_single_card_copy(card: dict, call_llm: Callable[[str, str], str]) -> tuple[dict, dict | None]:
    """两步 LLM：step1 elsewhere 串接 → step2 humanizer 去AI味。"""
    user_message = json.dumps({"card": card}, ensure_ascii=False, indent=2)

    # Step 1: elsewhere 风格串接字段成3段文字（带重试）
    parsed = _call_step_with_retry(card, user_message, call_llm, step="step1")
    if not parsed:
        return {}, {
            "card_id": card.get("card_id"),
            "card_title": card.get("card_title"),
            "warning": "AI 串接解析失败，已使用事实兜底文案",
        }

    # Step 2: Humanizer-zh 去AI味（带重试）
    humanised = _call_humaniser(parsed, card, call_llm)
    if not humanised:
        # humanizer 失败时使用 step1 输出，不丢失内容
        return _normalize_generated_card(parsed, card), {
            "card_id": card.get("card_id"),
            "card_title": card.get("card_title"),
            "warning": "Humanizer 去AI味失败，使用原始串接文案",
        }

    return _normalize_generated_card(humanised, card), None


def _call_step_with_retry(card: dict, user_message: str, call_llm, *, step: str) -> dict | None:
    """调用一步 LLM，JSON 解析失败时重试一次。"""
    if step == "step1":
        prompts = (_system_prompt(), _system_prompt() + "\n\n上一轮输出不是完整 JSON。请压缩每段文字，只输出一个可被 json.loads 解析的完整 JSON 对象，不要代码块，不要解释。")
    else:
        prompts = (_humaniser_system_prompt(), _humaniser_system_prompt() + "\n\n上一轮输出不是完整 JSON。只输出一个可被 json.loads 解析的完整 JSON 对象，不要代码块，不要解释。")

    for system_prompt in prompts:
        raw = call_llm(system_prompt, user_message)
        try:
            return _parse_llm_json(raw)
        except ValueError:
            continue
    return None


def _call_humaniser(step1_output: dict, source_card: dict, call_llm) -> dict | None:
    """第二步 LLM：用 Humanizer-zh 对 step1 输出的3段文字去AI味。"""
    paragraphs = step1_output.get("paragraphs", [])
    card_id = step1_output.get("card_id") or source_card.get("card_id", "")
    user_msg = json.dumps(
        {"card_id": card_id, "paragraphs": paragraphs},
        ensure_ascii=False,
    )
    result = _call_step_with_retry(source_card, user_msg, call_llm, step="step2")
    if result:
        # 如果 step2 返回的 card_id 丢失，从 step1 补回
        if not result.get("card_id"):
            result["card_id"] = card_id
    return result


def _normalize_generated_card(data: dict, source_card: dict) -> dict:
    if isinstance(data.get("cards"), list):
        for card in data["cards"]:
            if str(card.get("card_id")) == str(source_card.get("card_id")):
                return card
        return data["cards"][0] if data["cards"] else {}
    return data


def _compose_layout_markdown(paragraphs: list[str], source_card: dict) -> str:
    blocks = [p for p in paragraphs if str(p or "").strip()]
    media = source_card.get("media") or []
    media_tokens = []
    seen = set()
    for item in media:
        key = item.get("asset_key") or item.get("item_key")
        if not key or key in seen:
            continue
        seen.add(key)
        media_tokens.append(f"{{{{{key}}}}}")
    if media_tokens:
        insert_at = 1 if blocks else 0
        blocks[insert_at:insert_at] = media_tokens
    return "\n\n".join(blocks)


def _parse_llm_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI 返回不是有效 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("AI 返回不是 JSON 对象")
    if not isinstance(data.get("paragraphs"), list) and not isinstance(data.get("cards"), list):
        raise ValueError("AI 返回缺少 paragraphs 数组")
    return data


def _coerce_three_paragraphs(generated_card: dict, source_card: dict) -> list[str]:
    raw = generated_card.get("paragraphs")
    if isinstance(raw, list):
        paragraphs = [str(p).strip() for p in raw if str(p).strip()]
    else:
        text = str(generated_card.get("paragraph") or "").strip()
        paragraphs = [p.strip() for p in re.split(r"\n{2,}|(?<=。)", text) if p.strip()]
    if len(paragraphs) >= 3:
        return [_humanize_cleanup(p) for p in paragraphs[:3]]
    fallback = _fallback_paragraphs(source_card)
    merged = paragraphs + fallback
    return [_humanize_cleanup(p) for p in merged[:3]]


def _fallback_paragraphs(source_card: dict) -> list[str]:
    facts = source_card.get("facts") or []
    chunks = [f"{f.get('label') or f.get('field_key')}：{f.get('value')}" for f in facts]
    if not chunks:
        return ["", "", ""]
    buckets = [[], [], []]
    for idx, chunk in enumerate(chunks):
        buckets[idx % 3].append(chunk)
    return ["；".join(bucket) + "。" if bucket else "" for bucket in buckets]


def _humanize_cleanup(text: str) -> str:
    """正则兜底清理（破折号→逗号、弯引号→直引号）。主要去AI味由 Humanizer-zh LLM 完成。"""
    replacements = {
        "——": "，",
        "—": "，",
        "–": "，",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    out = str(text or "").strip()
    for old, new in replacements.items():
        out = out.replace(old, new)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _preserve_numeric_tokens(paragraphs: list[str], facts: list[dict]) -> list[str]:
    source = "\n".join(str(f.get("value") or "") for f in facts)
    target = "\n".join(paragraphs)
    tokens = []
    for token in re.findall(r"(?<!\w)(?:\d+(?:\.\d+)?%?|\$\d+(?:\.\d+)?[MBK]?|\d+(?:\.\d+)?[倍年月日])", source):
        if token not in tokens:
            tokens.append(token)
    missing = [token for token in tokens if token not in target]
    if missing:
        suffix = "补充数据：" + "、".join(missing) + "。"
        paragraphs[-1] = (paragraphs[-1].rstrip("。") + "。" + suffix).strip()
    return paragraphs
