"""L0 质量门控 — 校验 L0 LLM 输出完整性，不通过则阻断下游

L0 的实际输出结构（来自 prompts/layer0-cleaner.md）：
  - company_identity: {company_key, display_name}
  - evidence_pool: [{source, title, url, content, ...}]
  - source_audit: {source_type: count}
  - source_warnings: [...]
  - raw_sources: {tavily, github, youtube, official_site}

门控检查 company_identity 和 evidence_pool 两个关键结构，而非具体字段值。
具体字段（company_name, founded_date等）由 L3-A 负责提取。
"""

from __future__ import annotations
import json

L0_REQUIRED_KEYS = [
    "company_identity",  # {company_key, display_name} — 身份识别基础
    "evidence_pool",     # [{source, title, url, content, ...}] — 下游分析数据源
]

L0_MIN_CONTENT_LENGTH = 500  # L0 输出通常 2000+ chars

# company_identity 内必填的子字段
L0_IDENTITY_REQUIRED = ["company_key", "display_name"]


class L0GateError(RuntimeError):
    """L0 输出不完整，放弃本次研究"""
    pass


def validate_l0_output(l0_result: dict) -> tuple[bool, list[str]]:
    """校验 L0 输出是否具备下游所需的最小信息。

    Returns:
        (is_valid, errors): is_valid=False 时应中止流水线
    """
    errors = []

    # 检查顶层必需 key
    for key in L0_REQUIRED_KEYS:
        value = l0_result.get(key)
        if value is None:
            errors.append(f"L0 missing required key: {key}")
            continue
        # evidence_pool 必须是非空列表
        if key == "evidence_pool":
            if not isinstance(value, list) or len(value) == 0:
                errors.append(f"L0 evidence_pool is empty or not a list")

    # 检查 company_identity 内部字段
    identity = l0_result.get("company_identity")
    if isinstance(identity, dict):
        for field in L0_IDENTITY_REQUIRED:
            val = identity.get(field)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"L0 company_identity missing: {field}")
    elif identity is not None:
        errors.append("L0 company_identity is not a dict")

    # 整体输出长度
    total_text = json.dumps(l0_result, ensure_ascii=False)
    if len(total_text) < L0_MIN_CONTENT_LENGTH:
        errors.append(
            f"L0 output too short: {len(total_text)} chars "
            f"(min: {L0_MIN_CONTENT_LENGTH})"
        )

    return len(errors) == 0, errors
