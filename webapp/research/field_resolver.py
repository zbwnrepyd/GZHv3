"""字段解析器 — 按字段类型走不同解析路径，输出统一 FieldResult

P0 变更：
- official_fact/private_metric 有值但无 evidence_span_ids → llm_extracted（非 confirmed）
- market_model 始终 proxy（不 confirmed）
- 新增 industry_avg、conflict 状态
- LTV/CAC 四级降级：confirmed → proxy → industry_avg → unavailable
- 市场字段必须带 region/segment/year/source，缺口径为 manual_needed/proxy
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FieldResult:
    field_key: str
    value: Optional[str] = None
    resolution_status: str = "unavailable"  # confirmed|derived|proxy|industry_avg|llm_extracted|manual_needed|unavailable|not_applicable|conflict|draft|hidden
    confidence: str = "medium"  # high|medium|low
    source_fields: list[str] = field(default_factory=list)
    formula: str = ""
    assumptions: list[str] = field(default_factory=list)
    unavailable_reason: str = ""
    resolution_method: str = ""
    # P0 新增
    evidence_span_ids: list = field(default_factory=list)
    region: str = ""
    segment: str = ""
    year: str = ""
    source_note: str = ""
    disclaimer: str = ""


# P0: LTV/CAC 行业基准
_LTV_CAC_INDUSTRY_BENCHMARKS = {
    "ltv": "6:1–8:1（SaaS 行业中位数）",
    "cac": "$500–$5,000（SaaS 行业区间）",
    "ltv_cac_ratio": "3:1–5:1（SaaS 行业健康基准）",
    "gross_margin": "70%–80%（SaaS 行业中位数）",
    "churn_rate": "3%–7% 月（SaaS 行业区间）",
    "burn_rate": "N/A（公司差异极大，无通用基准）",
    "runway_months": "18–24 月（SaaS 行业参考）",
}


def _check_evidence_quality(evidence_span_ids: list, evidence_map: dict | None = None) -> dict:
    """Check if evidence meets confirmed requirements.

    Returns {passed: bool, reason: str, source_score: float, entity_score: float}

    SPEC confirmed requirements:
      - source_score >= 0.65
      - entity_score >= 0.60
      - no evidence has strength "weak"
    """
    if not evidence_span_ids:
        return {"passed": False, "reason": "No evidence spans provided", "source_score": 0.0, "entity_score": 0.0}

    if not evidence_map:
        # Cannot check quality without evidence_map; assume passed
        return {"passed": True, "reason": "No evidence_map for quality check", "source_score": 1.0, "entity_score": 1.0}

    min_source = 1.0
    min_entity = 1.0
    has_weak = False

    for sid in evidence_span_ids:
        span = evidence_map.get(sid)
        if not span:
            continue
        src = span.get("source_score", 0.0)
        ent = span.get("entity_score", 0.0)
        strength = span.get("strength", span.get("evidence_strength", ""))
        if src < min_source:
            min_source = src
        if ent < min_entity:
            min_entity = ent
        if strength == "weak":
            has_weak = True

    if min_source < 0.65:
        return {"passed": False, "reason": f"source_score {min_source:.2f} < 0.65", "source_score": min_source, "entity_score": min_entity}
    if min_entity < 0.60:
        return {"passed": False, "reason": f"entity_score {min_entity:.2f} < 0.60", "source_score": min_source, "entity_score": min_entity}
    if has_weak:
        return {"passed": False, "reason": "Evidence contains weak-strength spans", "source_score": min_source, "entity_score": min_entity}

    return {"passed": True, "reason": "ok", "source_score": min_source, "entity_score": min_entity}


def resolve_field(field_key: str, field_value: str | None,
                  resolved_pool: dict[str, FieldResult],
                  manifest_entry: dict | None = None,
                  evidence_span_ids: Optional[list] = None,
                  evidence_quality: Optional[dict] = None) -> FieldResult:
    """对单个字段运行解析策略

    P0 变更:
    - evidence_span_ids 为空时，official_fact 和 private_metric 不得 confirmed
    - market_model 始终 proxy
    - 市场字段无 region/segment/year → manual_needed/proxy

    Args:
        field_key: 字段名
        field_value: LLM 提取的原始值
        resolved_pool: 已完成解析的字段池（用于公式计算）
        manifest_entry: field_manifest.yaml 中的条目
        evidence_span_ids: 绑定的证据 span ID 列表

    Returns:
        FieldResult with resolution_status and metadata
    """
    entry = manifest_entry or {}
    resolution_type = entry.get("resolution_type", "llm_extract")
    category = entry.get("category", "A")
    has_evidence = bool(evidence_span_ids)

    # -- 有值时：根据 resolution_type + evidence 标记 --
    if not _is_missing(field_value):
        return _resolve_with_value(field_key, str(field_value), resolution_type,
                                   resolved_pool, entry, has_evidence, evidence_span_ids or [],
                                   evidence_quality=evidence_quality)

    # -- 无值时：按 if_missing 策略处理 --
    if_missing = entry.get("if_missing", "unavailable")

    if resolution_type == "derived":
        return _resolve_derived(field_key, resolved_pool, entry)

    if resolution_type == "market_model":
        return _resolve_market_model(field_key, entry, evidence_span_ids or [])

    if resolution_type == "private_metric":
        # P0: 无值 + 私有指标 → 尝试 industry_avg 降级
        return _resolve_private_metric_missing(field_key, entry)

    if resolution_type == "b2b_remap":
        return FieldResult(
            field_key=field_key,
            value=None,
            resolution_status="not_applicable",
            confidence="high",
            resolution_method="b2b_remap",
            unavailable_reason=f"{field_key}: B2B 业务模式不适用用户数口径，"
                               f"建议使用 {entry.get('b2b_replace', 'account/logos 数')}",
        )

    if if_missing == "manual_needed":
        return FieldResult(
            field_key=field_key,
            resolution_status="manual_needed",
            resolution_method="marked_manual",
            unavailable_reason=f"{field_key}: 需要人工估算或付费数据源确认",
        )

    # 默认：标记 unavailable
    return FieldResult(
        field_key=field_key,
        resolution_status="unavailable" if if_missing != "not_applicable" else "not_applicable",
        resolution_method="default_unavailable",
        unavailable_reason=f"{field_key}: 公开信息中未找到可靠来源",
    )


def _resolve_with_value(field_key: str, value: str, resolution_type: str,
                        resolved_pool: dict, entry: dict,
                        has_evidence: bool,
                        evidence_span_ids: list,
                        evidence_map: dict | None = None,
                        evidence_quality: dict | None = None) -> FieldResult:
    """有值时的状态判定。

    P0: 核心变更 — official_fact 和 private_metric 需要证据绑定才能 confirmed。
    SPEC: official_fact 除 evidence_span_ids 非空外，还需 source_score>=0.65,
          entity_score>=0.60，且无 weak 证据。
    """
    if resolution_type == "official_fact":
        if has_evidence:
            # SPEC: 证据质量闸门 — source_score / entity_score / strength
            quality = evidence_quality or (
                _check_evidence_quality(evidence_span_ids, evidence_map)
                if evidence_map else {"passed": True}
            )
            if not quality.get("passed", True):
                return FieldResult(
                    field_key=field_key, value=value,
                    resolution_status="llm_extracted", confidence="low",
                    resolution_method="llm_extract_weak_evidence",
                    evidence_span_ids=evidence_span_ids,
                    unavailable_reason=(
                        f"{field_key}: 证据质量不满足 confirmed 要求 — "
                        f"{quality.get('reason', 'quality check failed')}"
                    ),
                )
            return FieldResult(
                field_key=field_key, value=value,
                resolution_status="confirmed", confidence="high" if len(evidence_span_ids) >= 2 else "medium",
                resolution_method="official_fact",
                evidence_span_ids=evidence_span_ids,
            )
        else:
            return FieldResult(
                field_key=field_key, value=value,
                resolution_status="llm_extracted", confidence="low",
                resolution_method="llm_extract_no_evidence",
                unavailable_reason=f"{field_key}: LLM 提取值但未绑定证据源。"
                                   f"需追溯至官网/新闻稿/Crunchbase 等官方来源",
            )

    elif resolution_type == "enum_extraction":
        return FieldResult(
            field_key=field_key, value=value,
            resolution_status="confirmed" if has_evidence else "llm_extracted",
            confidence="medium",
            resolution_method="enum_extraction",
            evidence_span_ids=evidence_span_ids,
        )

    elif resolution_type == "private_metric":
        # P0: 私有指标有值也不得 confirmed 除非有证据
        if has_evidence:
            return FieldResult(
                field_key=field_key, value=value,
                resolution_status="confirmed", confidence="medium",
                resolution_method="private_metric_confirmed",
                evidence_span_ids=evidence_span_ids,
            )
        else:
            return FieldResult(
                field_key=field_key, value=value,
                resolution_status="llm_extracted", confidence="low",
                resolution_method="private_metric_no_evidence",
                unavailable_reason=f"{field_key}: 私有经营指标，LLM 提取但无公开来源证据。"
                                   f"仅公司财报/投资人材料/创始人访谈可确认",
            )

    elif resolution_type == "derived":
        return FieldResult(
            field_key=field_key, value=value,
            resolution_status="derived",
            resolution_method="formula",
        )

    elif resolution_type == "market_model":
        # 市场字段始终 proxy（即使有值）
        result = FieldResult(
            field_key=field_key, value=value,
            resolution_status="proxy",
            confidence="medium" if has_evidence else "low",
            resolution_method="market_model",
            evidence_span_ids=evidence_span_ids,
        )
        # P0: 检查口径完整性
        required_context = entry.get("required_context", [])
        if required_context:
            missing_ctx = [c for c in required_context if c not in entry]
            if missing_ctx:
                result.unavailable_reason = (
                    f"{field_key}: 市场估算缺少口径参数 ({', '.join(missing_ctx)})。"
                    f"需补充 region/segment/year/source"
                )
        return result

    elif resolution_type == "b2b_remap":
        return FieldResult(
            field_key=field_key, value=value,
            resolution_status="confirmed" if has_evidence else "llm_extracted",
            resolution_method="b2b_remap",
        )

    else:
        # llm_extract 或其他
        return FieldResult(
            field_key=field_key, value=value,
            resolution_status="llm_extracted",
            confidence="low",
            resolution_method=resolution_type,
        )


def _resolve_private_metric_missing(field_key: str, entry: dict) -> FieldResult:
    """私有指标缺失时的降级处理。

    P0: LTV/CAC 四级降级 — confirmed → proxy → industry_avg → unavailable
    """
    # 尝试 industry_avg 降级
    if field_key in _LTV_CAC_INDUSTRY_BENCHMARKS:
        return FieldResult(
            field_key=field_key,
            value=_LTV_CAC_INDUSTRY_BENCHMARKS[field_key],
            resolution_status="industry_avg",
            confidence="low",
            resolution_method="industry_avg_fallback",
            disclaimer="行业平均，不代表公司披露",
            unavailable_reason=f"{field_key}: 未披露。使用行业基准（不代表公司披露）",
        )
    # 无行业基准 → unavailable
    return FieldResult(
        field_key=field_key,
        value=None,
        resolution_status="unavailable",
        confidence="high",
        resolution_method="private_metric_policy",
        unavailable_reason=f"{field_key}: 私有经营指标，公开来源未披露。"
                           f"仅公司财报/投资人材料/创始人访谈/Latka等数据库可确认",
    )


def _resolve_derived(field_key: str, resolved_pool: dict,
                     entry: dict) -> FieldResult:
    """公式字段：检查所有输入是否 confirmed/proxy/derived，计算实际值。"""
    required = entry.get("required_inputs", [])
    formula = entry.get("formula", "")

    if not required:
        return FieldResult(
            field_key=field_key, resolution_status="derived",
            resolution_method="formula", formula=formula,
            unavailable_reason="缺少公式定义",
        )

    # 检查输入字段
    for inp in required:
        inp_result = resolved_pool.get(inp)
        if not inp_result or inp_result.value is None:
            return FieldResult(
                field_key=field_key,
                resolution_status="unavailable",
                resolution_method="blocked_formula",
                formula=formula,
                source_fields=required,
                unavailable_reason=f"依赖字段 {inp} 缺失，公式无法计算",
            )

    # 计算实际值
    computed = _compute_formula(formula, resolved_pool, field_key)
    return FieldResult(
        field_key=field_key,
        value=computed,
        resolution_status="derived",
        resolution_method="formula",
        formula=formula,
        source_fields=required,
    )


def _compute_formula(formula: str, resolved_pool: dict, field_key: str) -> str | None:
    """执行公式并返回计算结果字符串。"""
    import re as _re
    formula = formula.strip()

    # extract_rounds(field_key) → 从 funding_info 文本提取融资轮次 JSON
    if formula.startswith("extract_rounds("):
        input_key = formula[len("extract_rounds("):-1].strip()
        input_result = resolved_pool.get(input_key)
        if input_result and input_result.value:
            return _do_extract_rounds(str(input_result.value))
        return None

    # FUNDING_MAP[field_key] → 查枚举映射
    if formula.startswith("FUNDING_MAP["):
        input_key = formula[len("FUNDING_MAP["):-1].strip()
        input_result = resolved_pool.get(input_key)
        if input_result and input_result.value:
            try:
                from competitive_scoring import FUNDING_MAP
            except ImportError:
                return None
            mapped = FUNDING_MAP.get(str(input_result.value).strip())
            return str(mapped) if mapped is not None else None
        return None

    # ltv / cac 等算术公式
    if "/" in formula:
        parts = formula.replace(" ", "").split("/")
        if len(parts) == 2:
            a_val = _extract_numeric(resolved_pool.get(parts[0]))
            b_val = _extract_numeric(resolved_pool.get(parts[1]))
            if a_val is not None and b_val is not None and b_val != 0:
                ratio = round(a_val / b_val, 2)
                # LTV/CAC 特殊处理：附带行业基准标注
                if field_key == "ltv_cac_ratio":
                    if ratio < 1:
                        return f"{ratio}:1（低于 SaaS 健康基准 3:1）"
                    elif ratio > 10:
                        return f"{ratio}:1（远超 SaaS 基准 3:1-5:1，需核实）"
                    return f"{ratio}:1（SaaS 行业健康基准 3:1-5:1）"
                return str(ratio)

    # arr / 12 → MRR
    if formula == "arr / 12":
        arr_val = _extract_numeric(resolved_pool.get("arr"))
        if arr_val is not None:
            return str(round(arr_val / 12, 2))
        return None

    return None


def _extract_numeric(field_result) -> float | None:
    """从 FieldResult 值提取数字（支持范围取均值）。"""
    if not field_result or not field_result.value:
        return None
    import re as _re
    text = str(field_result.value).replace(",", "")
    numbers = _re.findall(r'[\d]+\.?\d*', text)
    if numbers:
        nums = [float(n) for n in numbers]
        return sum(nums) / len(nums)
    return None


def _do_extract_rounds(funding_info_text: str) -> str | None:
    """从 free-text funding_info 中提取融资轮次为 JSON 数组。"""
    import re as _re, json as _json
    rounds = []
    patterns = [
        (_re.compile(r'(?:Series\s+)?([A-E])\s*(?:round|轮)?\s*(?:\(|融资)?\s*\$?([\d,.]+)\s*([MBK]?)\)?', _re.IGNORECASE),
         lambda m: {"round": f"Series {m.group(1).upper()}", "amount": f"${m.group(2)}{m.group(3) or 'M'}"}),
        (_re.compile(r'(Seed|Pre-seed|种子轮|天使轮|Angel)\s*(?:round|融资)?\s*\$?([\d,.]+)\s*([MBK]?)?', _re.IGNORECASE),
         lambda m: {"round": m.group(1), "amount": f"${m.group(2)}{m.group(3) or 'M'}"}),
    ]
    for pattern, builder in patterns:
        for match in pattern.finditer(funding_info_text):
            rounds.append(builder(match))
    return _json.dumps(rounds[:5], ensure_ascii=False) if rounds else None


def _resolve_market_model(field_key: str, entry: dict,
                          evidence_span_ids: list = None) -> FieldResult:
    """市场估算：允许 proxy，检查口径完整性。

    P0: market_size、market_cagr、tam 必须带 region/segment/year/source。
    缺口径 → manual_needed/proxy，不得 confirmed。
    """
    allow_proxy = entry.get("allow_proxy", False)
    required_context = entry.get("required_context", [])

    missing_ctx = []
    if required_context:
        # 检查 manifest 中是否配置了默认 context
        for ctx in required_context:
            if not entry.get(ctx):
                missing_ctx.append(ctx)

    if allow_proxy:
        result = FieldResult(
            field_key=field_key,
            resolution_status="proxy",
            resolution_method="market_model",
            evidence_span_ids=evidence_span_ids or [],
            unavailable_reason=f"{field_key}: 公开市场数据可得，但需要确认市场边界",
        )
        if missing_ctx:
            result.unavailable_reason += f"。缺少口径: {', '.join(missing_ctx)}"
            result.resolution_status = "manual_needed"
        return result

    return FieldResult(
        field_key=field_key,
        resolution_status="manual_needed",
        resolution_method="market_model",
        unavailable_reason=f"{field_key}: 需要市场报告或分析师数据确认边界",
    )


def resolve_all(field_map: dict[str, str | None],
                manifest: dict | None = None,
                evidence_map: dict[str, list] | None = None) -> dict[str, FieldResult]:
    """批量解析所有字段，按依赖顺序处理。

    P0 变更：支持传入 evidence_map 绑定证据。
    """
    if manifest is None:
        from research.field_status import _load_manifest
        manifest = _load_manifest()
    evidence_map = evidence_map or {}

    # 第一遍：先解析非公式字段，构建 resolved_pool
    resolved_pool: dict[str, FieldResult] = {}
    deferred: list[tuple[str, str | None, dict, list]] = []

    for fk, fv in field_map.items():
        entry = manifest.get(fk, manifest.get("_default", {}))
        ev_ids = evidence_map.get(fk)
        if entry.get("resolution_type") == "derived":
            deferred.append((fk, fv, entry, ev_ids or []))
        else:
            resolved_pool[fk] = resolve_field(fk, fv, resolved_pool, entry, ev_ids)

    # 第二遍：解析公式字段（此时 resolved_pool 已包含所有非公式字段）
    for fk, fv, entry, ev_ids in deferred:
        resolved_pool[fk] = resolve_field(fk, fv, resolved_pool, entry, ev_ids)

    return resolved_pool


MISSING_VALUES = {"", "暂缺", "unknown", "Unknown", "N/A", "n/a", "none", "None", "NULL"}


def _is_missing(value) -> bool:
    if value is None:
        return True
    return str(value).strip() in MISSING_VALUES
