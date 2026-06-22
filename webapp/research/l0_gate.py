"""L0 质量门控 — 校验 L0 LLM 输出完整性，不通过则阻断下游"""

from __future__ import annotations
import json

L0_REQUIRED_FIELDS = [
    "company_name",
    "company_def",
    "main_product_name",
    "founded_date",
]

L0_MIN_CONTENT_LENGTH = 200


class L0GateError(RuntimeError):
    """L0 输出不完整，放弃本次研究"""
    pass


def validate_l0_output(l0_result: dict) -> tuple[bool, list[str]]:
    """校验 L0 输出是否具备下游所需的最小信息。

    Returns:
        (is_valid, errors): is_valid=False 时应中止流水线
    """
    errors = []

    for field in L0_REQUIRED_FIELDS:
        value = l0_result.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"L0 missing required field: {field}")

    total_text = json.dumps(l0_result, ensure_ascii=False)
    if len(total_text) < L0_MIN_CONTENT_LENGTH:
        errors.append(
            f"L0 output too short: {len(total_text)} chars "
            f"(min: {L0_MIN_CONTENT_LENGTH})"
        )

    return len(errors) == 0, errors
