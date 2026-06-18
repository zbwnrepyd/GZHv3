"""渲染数据 API — /api/render-data/... （v2 支持 card_set_key）
返回卡片渲染所需的完整数据：字段值 + 图片 URL + 模板 + 排版实例
"""
from __future__ import annotations
from flask import Blueprint, request, jsonify
from config import config
from repositories.card_config_repo import get_enabled_cards, get_card_items
from repositories.field_repo import (
    get_final_field_value, get_research_field_value, get_final_card_values, _EMPTY_FINAL,
)
from repositories.template_repo import get_template
from repositories.layout_repo import get_layout
from asset_store import ensure_assets_rows, get_asset
from services.card_config_service import create_default_cards_for_company


def _resolve_field_value(company: str, field_key: str, card_no: int = None) -> str:
    """解析字段值。
    优先级: final_card_values (SPEC v3 主读模型) → final_fields (向后兼容) → research_fields。
    """
    company_key = company.lower()

    # SPEC v3: 优先读 final_card_values (卡片展示读模型)
    if card_no is not None:
        try:
            rows = get_final_card_values(config.DB_PATH_FINAL, company_key, card_no=card_no)
        except Exception:
            rows = []
    else:
        try:
            rows = get_final_card_values(config.DB_PATH_FINAL, company_key)
        except Exception:
            rows = []
    for r in rows:
        if r.get("field_key") == field_key:
            val = r.get("field_value") or r.get("final_value") or ""
            return val

    # 回退：final_fields (向后兼容)
    raw = get_final_field_value(config.DB_PATH_FINAL, company, field_key)
    if raw is _EMPTY_FINAL:
        return ""  # 用户显式清空
    if raw is not None:
        return raw
    return get_research_field_value(config.DB_PATH_RESEARCH, company, field_key) or ""


def _get_set_key() -> str:
    return (request.args.get("set") or "v1").strip()


def _enabled_cards_or_defaults(company: str) -> list[dict]:
    set_key = _get_set_key()
    cards = get_enabled_cards(config.DB_PATH_COMPOSITION, company, card_set_key=set_key)
    if cards:
        return cards
    create_default_cards_for_company(config.DB_PATH_COMPOSITION, company, card_set_key=set_key)
    return get_enabled_cards(config.DB_PATH_COMPOSITION, company, card_set_key=set_key)


def _media_url(company: str, media_key: str) -> str:
    ensure_assets_rows(config.DB_PATH_ASSETS, company)
    asset = get_asset(config.DB_PATH_ASSETS, company, media_key) or {}
    lp = asset.get("local_path") or ""
    if lp:
        return lp
    # fallback: company_assets.local_path 为空时，从 image_variants 找已选中变体
    from asset_store import list_variants
    variants = list_variants(config.DB_PATH_ASSETS, company, media_key) or []
    selected = next((v for v in variants if v.get("is_selected")), None)
    return selected.get("local_path") if selected else ""


def register(bp: Blueprint):
    """将路由注册到 Blueprint"""

    @bp.route("/render-data/<company>")
    def get_render_data(company: str):
        """返回某公司全部启用卡片的渲染数据。

        v3: 走 RenderAssembler → RenderContract 格式 (Goal 一)
        v1/v2: 保持旧格式向后兼容
        """
        try:
            set_key = _get_set_key()

            # v3: RenderContract format via RenderAssembler (Goal 一)
            if set_key == 'v3':
                from services.render_assembler import RenderAssembler
                from services.contract_validator import ContractValidator
                assembler = RenderAssembler()
                contract = assembler.assemble(company, set_key)
                try:
                    ContractValidator.validate(contract)
                except Exception:
                    pass
                return jsonify(contract)

            cards = _enabled_cards_or_defaults(company)
            result_cards = []
            for card in cards:
                card_id = card["card_id"]
                items = get_card_items(config.DB_PATH_COMPOSITION, company, card_id,
                                      card_set_key=set_key)

                # 解析每个 item 的值
                resolved_items = []
                for item in items:
                    resolved = dict(item)
                    if item["item_type"] == "field":
                        resolved["value"] = _resolve_field_value(company, item["item_key"], card.get("card_index"))
                    elif item["item_type"] == "media":
                        resolved["url"] = _media_url(company, item["item_key"])
                        resolved["media_label"] = item.get("item_label", "")
                    resolved_items.append(resolved)

                # 模板
                template_id = card.get("template_id")
                template = get_template(config.DB_PATH_TEMPLATE, template_id) if template_id else None

                # 排版实例
                layout = get_layout(config.DB_PATH_TEMPLATE, company, card_id)

                result_cards.append({
                    "card_id": card_id,
                    "card_index": card["card_index"],
                    "card_title": card["card_title"],
                    "enabled": bool(card["enabled"]),
                    "template_id": template_id,
                    "items": resolved_items,
                    "template": template.get("template_json") if template else None,
                    "layout": layout.get("layout_json") if layout else None,
                })

            return jsonify({
                "company_name": company,
                "cards": result_cards,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/render-data/<company>/<card_id>")
    def get_single_render_data(company: str, card_id: str):
        """返回单张卡片的渲染数据"""
        try:
            from repositories.card_config_repo import get_card
            set_key = _get_set_key()
            card = get_card(config.DB_PATH_COMPOSITION, company, card_id,
                            card_set_key=set_key)
            if not card:
                return jsonify({"error": "卡片不存在"}), 404

            items = get_card_items(config.DB_PATH_COMPOSITION, company, card_id,
                                   card_set_key=set_key)
            resolved_items = []
            for item in items:
                resolved = dict(item)
                if item["item_type"] == "field":
                    resolved["value"] = _resolve_field_value(company, item["item_key"], card.get("card_index"))
                elif item["item_type"] == "media":
                    resolved["url"] = _media_url(company, item["item_key"])
                resolved_items.append(resolved)

            template = get_template(config.DB_PATH_TEMPLATE, card.get("template_id")) if card.get("template_id") else None
            layout = get_layout(config.DB_PATH_TEMPLATE, company, card_id)

            return jsonify({
                "card_id": card_id,
                "card_index": card["card_index"],
                "card_title": card["card_title"],
                "enabled": bool(card["enabled"]),
                "template_id": card.get("template_id"),
                "items": resolved_items,
                "template": template.get("template_json") if template else None,
                "layout": layout.get("layout_json") if layout else None,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
