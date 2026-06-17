"""字段 API — /api/fields/... """
from __future__ import annotations
from flask import Blueprint, request, jsonify
from config import config
from services.field_service import (
    get_fields_with_versions, finalize_field, batch_finalize,
)


def register(bp: Blueprint):
    """将路由注册到 Blueprint"""

    @bp.route("/fields/<company>")
    def get_company_fields(company: str):
        """返回公司的全部字段（含三版本 + 定稿状态）"""
        try:
            fields = get_fields_with_versions(
                config.DB_PATH_RESEARCH, config.DB_PATH_FINAL, company)
            return jsonify({"company_name": company, "groups": fields})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/fields/<company>/research")
    def get_research_fields_route(company: str):
        """返回 research_fields（三版本对比）"""
        try:
            from repositories.field_repo import get_research_fields
            versions = {}
            for ver in ("standard", "business", "spread"):
                rows = get_research_fields(config.DB_PATH_RESEARCH, company, ver)
                for r in rows:
                    key = r["field_key"]
                    versions.setdefault(key, {})[ver] = r.get("field_value", "")
            return jsonify({"company_name": company, "fields": versions})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/fields/<company>/final")
    def get_final_fields_route(company: str):
        """返回 final_fields + final_card_values（SPEC v3 主读模型）"""
        try:
            from repositories.field_repo import get_final_fields, get_final_card_values
            fields = get_final_fields(config.DB_PATH_FINAL, company)
            # SPEC v3: 同时返回 final_card_values (卡片展示读模型)
            card_values = []
            try:
                card_values = get_final_card_values(config.DB_PATH_FINAL, company.lower())
            except Exception:
                pass
            return jsonify({
                "company_name": company,
                "fields": fields,
                "card_values": card_values,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/fields/<company>/<field_key>", methods=["PATCH"])
    def update_field(company: str, field_key: str):
        """定稿单个字段（写入 final_fields）"""
        try:
            data = request.get_json() or {}
            final_value = data.get("final_value", "")
            status = data.get("status", "confirmed")
            ok = finalize_field(config.DB_PATH_FINAL, company, field_key,
                               final_value, status=status)
            if not ok:
                return jsonify({"error": "保存失败"}), 500
            return jsonify({"status": "ok", "field_key": field_key})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/fields/<company>/confirm", methods=["POST"])
    def confirm_fields(company: str):
        """批量定稿字段"""
        try:
            data = request.get_json() or {}
            field_values = data.get("field_values", {})
            count = batch_finalize(config.DB_PATH_FINAL, company, field_values)
            return jsonify({"status": "ok", "count": count})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
