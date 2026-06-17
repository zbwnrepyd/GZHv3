"""覆盖度闸门 — 评估字段覆盖度，决定是否触发缺口补采

SPEC Section 14: CoverageGate 在 L3 字段提取完成后评估整体覆盖质量，
低于阈值时触发 should_refetch 信号，由调用方决定是否启动定向补采。

SPEC Section 3: 统一状态分数 + confirmed 硬性要求（evidence_span_ids、
source_score、entity_score、evidence_strength）。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── SPEC Section 3: 统一状态分数 ──
STATUS_SCORES: dict[str, float] = {
    "confirmed": 1.0,
    "derived": 1.0,
    "unavailable": 1.0,
    "not_applicable": 1.0,
    "proxy": 0.8,
    "industry_avg": 0.8,
    "manual_needed": 0.6,
    "llm_extracted": 0.5,
    "conflict": 0.5,       # 冲突视为低信度
    "draft": 0.0,          # 草稿不计分
    "hidden": 0.0,         # 隐藏不计分
}

# ── SPEC Section 3: confirmed 硬性要求 ──
# 仅当满足全部条件时字段才被视为"真 confirmed"
CONFIRMED_REQUIREMENTS = {
    "min_source_score": 0.65,
    "min_entity_score": 0.60,
    "require_evidence_span_ids": True,   # evidence_span_ids 必须非空
    "forbid_weak_evidence": True,        # evidence_strength 不得为 "weak"
}

# ── 私有指标字段（manifest category D）─ 权重降权
_PRIVATE_METRIC_CATEGORY = "D"

# ── manifest 缓存 ──
_manifest_cache: dict = {}
_manifest_loaded = False


def _load_manifest() -> dict:
    """加载 field_manifest.yaml（与 field_status.py 一致的加载模式）。"""
    global _manifest_cache, _manifest_loaded
    if _manifest_loaded:
        return _manifest_cache
    try:
        import yaml
        path = Path(__file__).resolve().parent.parent.parent / "references" / "field_manifest.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            _manifest_cache = raw.get("fields", {}) if isinstance(raw, dict) else {}
    except Exception:
        _manifest_cache = {}
    _manifest_loaded = True
    return _manifest_cache


@dataclass
class CoverageReport:
    """覆盖度评估报告。

    Attributes:
        coverage_score: 覆盖度综合得分 (0.0–1.0)，按字段权重加权
        confirmed_ratio: 真 confirmed 字段占比
        missing_required_fields: 缺失的必填字段列表
        weak_fields: 弱证据字段列表（已声明 confirmed 但未通过硬性检查）
        private_metric_fields: 私有指标字段状态映射 field_key -> resolution_status
        should_refetch: 是否需要触发缺口补采
        total_tokens_used: 本轮消耗的 token 数
        runtime_seconds: 本轮耗时（秒）
        details: 额外调试信息
    """
    coverage_score: float = 0.0
    confirmed_ratio: float = 0.0
    missing_required_fields: list[str] = field(default_factory=list)
    weak_fields: list[str] = field(default_factory=list)
    private_metric_fields: dict[str, str] = field(default_factory=dict)
    should_refetch: bool = False
    total_tokens_used: int = 0
    runtime_seconds: float = 0.0
    details: dict = field(default_factory=dict)


class CoverageGate:
    """覆盖度闸门。

    在 L3 字段提取完成后评估整体覆盖质量，决定是否触发 should_refetch。

    Usage:
        gate = CoverageGate(manifest, card_schema_fields)
        report = gate.evaluate(field_map, evidence_map, runtime_seconds, tokens_used)
        if report.should_refetch:
            # 触发定向补采
            ...
    """

    def __init__(self, manifest: dict, card_schema_fields: list[str]):
        """
        Args:
            manifest: field_manifest.yaml 的 fields 子 dict（{field_key: {category, resolution_type, ...}}）
            card_schema_fields: 卡片 schema 中引用的字段 key 列表（用于识别必填字段）
        """
        self.manifest = manifest
        self.card_schema_fields = set(card_schema_fields)

    # ── 内部辅助 ──────────────────────────────────────────────

    @staticmethod
    def _status_score(status: str | None) -> float:
        """返回状态对应的分数，未知状态返回 0.0。"""
        if not status:
            return 0.0
        return STATUS_SCORES.get(status, 0.0)

    @staticmethod
    def _is_missing(value: str | None) -> bool:
        """判断字段值是否为空/缺失。"""
        if value is None:
            return True
        stripped = str(value).strip()
        return stripped == "" or stripped in ("暂缺", "unknown", "Unknown",
                                               "N/A", "n/a", "none", "None", "NULL")

    def _field_category(self, field_key: str) -> str:
        """返回字段的 A/B/C/D/E 类别，未在 manifest 中定义的默认 A。"""
        entry = self.manifest.get(field_key, self.manifest.get("_default", {}))
        return entry.get("category", "A")

    def _field_weight(self, field_key: str) -> float:
        """按 SPEC 规则计算字段权重。

        - D 类（私有指标）: 0.5
        - A 类 且 出现在卡片 schema 中（必填字段）: 2.0
        - 其余: 1.0
        """
        category = self._field_category(field_key)
        if category == _PRIVATE_METRIC_CATEGORY:
            return 0.5
        if category == "A" and field_key in self.card_schema_fields:
            return 2.0
        return 1.0

    def _check_confirmed_hard_rules(
        self,
        field_result,          # FieldResult
        evidence_map: dict,
    ) -> bool:
        """检查字段是否通过 confirmed 硬性要求（SPEC Section 3）。

        一个字段要被视为"真 confirmed"，必须同时满足：
        1. resolution_status == "confirmed"
        2. evidence_span_ids 非空
        3. 所有绑定证据的 source_score >= 0.65（如有该元数据）
        4. 所有绑定证据的 entity_score >= 0.60（如有该元数据）
        5. 所有绑定证据的 evidence_strength != "weak"

        Returns:
            True 如果字段通过全部硬性检查
        """
        # 基础：状态必须是 confirmed
        if getattr(field_result, "resolution_status", "") != "confirmed":
            return False

        # 硬性要求 1: evidence_span_ids 必须非空
        span_ids = getattr(field_result, "evidence_span_ids", None) or []
        if CONFIRMED_REQUIREMENTS.get("require_evidence_span_ids", True) and not span_ids:
            return False

        # 如果没有 evidence_map，跳过来源级别检查（尽可能宽松）
        if not evidence_map:
            return True

        # 硬性要求 2–4: 逐条检查每个绑定的 evidence span
        for sid in span_ids:
            ev = evidence_map.get(sid, {})
            if not isinstance(ev, dict):
                continue

            # source_score
            src_score = ev.get("source_score")
            if src_score is not None:
                try:
                    if float(src_score) < CONFIRMED_REQUIREMENTS["min_source_score"]:
                        return False
                except (TypeError, ValueError):
                    pass

            # entity_score
            ent_score = ev.get("entity_score")
            if ent_score is not None:
                try:
                    if float(ent_score) < CONFIRMED_REQUIREMENTS["min_entity_score"]:
                        return False
                except (TypeError, ValueError):
                    pass

            # evidence_strength
            if CONFIRMED_REQUIREMENTS.get("forbid_weak_evidence", True):
                strength = ev.get("evidence_strength", "")
                if isinstance(strength, str) and strength.lower() == "weak":
                    return False

        return True

    # ── 主入口 ─────────────────────────────────────────────────

    def evaluate(
        self,
        field_map: dict[str, object],       # field_key -> FieldResult
        evidence_map: dict,                 # evidence_span_id -> metadata dict
        runtime_seconds: float = 0.0,
        tokens_used: int = 0,
    ) -> CoverageReport:
        """评估字段覆盖度，返回 CoverageReport。

        Args:
            field_map: {field_key: FieldResult} 映射，来自 L3 提取 + 字段解析
            evidence_map: {evidence_span_id: {source_score, entity_score, evidence_strength, ...}}
            runtime_seconds: 本轮研究耗时
            tokens_used: 本轮消耗 token 数

        Returns:
            CoverageReport 含覆盖度得分、真 confirmed 占比、缺失/弱字段、补采标记
        """
        report = CoverageReport(
            runtime_seconds=runtime_seconds,
            total_tokens_used=tokens_used,
        )

        if not field_map:
            report.should_refetch = True
            report.details["reason"] = "no_field_map"
            return report

        # 只评估卡片 schema 中引用的字段（不在卡片上的字段不影响覆盖度）
        eval_fields = [fk for fk in field_map if fk in self.card_schema_fields]

        # 如果没有卡片 schema 字段，回退到评估所有字段
        if not eval_fields:
            eval_fields = list(field_map.keys())

        total_weight = 0.0
        weighted_score = 0.0
        hard_confirmed_count = 0
        eval_count = 0

        for fk in eval_fields:
            fr = field_map[fk]

            # 提取状态和值
            status = getattr(fr, "resolution_status", None)
            value = getattr(fr, "value", None)

            # 状态分数（缺失值直接 0 分，不看 status）
            if self._is_missing(value):
                status = None  # 强制走 0.0 分

            score = self._status_score(status)
            weight = self._field_weight(fk)

            weighted_score += weight * score
            total_weight += weight
            eval_count += 1

            # 真 confirmed 检查
            if self._check_confirmed_hard_rules(fr, evidence_map):
                hard_confirmed_count += 1
            elif getattr(fr, "resolution_status", "") == "confirmed":
                # 声明 confirmed 但未通过硬性检查 → 弱字段
                report.weak_fields.append(fk)

            # 缺失的必填字段（A 类且值缺失）
            category = self._field_category(fk)
            if category == "A" and self._is_missing(value):
                report.missing_required_fields.append(fk)

            # 私有指标字段收集
            if category == _PRIVATE_METRIC_CATEGORY:
                report.private_metric_fields[fk] = status or "unavailable"

        # ── 计算最终指标 ──
        if total_weight > 0:
            report.coverage_score = weighted_score / total_weight
        else:
            report.coverage_score = 1.0  # 无字段可评估视为满分

        if eval_count > 0:
            report.confirmed_ratio = hard_confirmed_count / eval_count
        else:
            report.confirmed_ratio = 1.0

        # ── should_refetch 触发条件（SPEC Section 14）──
        # 1. coverage_score < 0.95
        # 2. 任何必填 A 类字段缺失
        # 3. confirmed_ratio < 0.65
        report.should_refetch = (
            report.coverage_score < 0.95
            or len(report.missing_required_fields) > 0
            or report.confirmed_ratio < 0.65
        )

        # ── 调试信息 ──
        report.details.update({
            "eval_field_count": eval_count,
            "total_weight": total_weight,
            "weighted_score": weighted_score,
            "hard_confirmed_count": hard_confirmed_count,
            "triggers": _build_triggers(report),
        })

        return report


def _build_triggers(report: CoverageReport) -> list[str]:
    """构建触发原因列表（供调试）。"""
    triggers: list[str] = []
    if report.coverage_score < 0.95:
        triggers.append(f"coverage_score={report.coverage_score:.3f} < 0.95")
    if report.missing_required_fields:
        triggers.append(f"missing_required={report.missing_required_fields}")
    if report.confirmed_ratio < 0.65:
        triggers.append(f"confirmed_ratio={report.confirmed_ratio:.3f} < 0.65")
    return triggers
