"""L0 质量门控 — 校验 L0 LLM 输出完整性，不通过则阻断下游

L0 prompt 包含两种输出格式（结构化和维度化），LLM 可能遵循任一种。
门控只做最小校验：输出是合法 JSON、非空、有足够内容。
不检查具体 key —— L3-A 负责字段级提取和质量判断。
"""

from __future__ import annotations
import json

L0_MIN_CONTENT_LENGTH = 500  # L0 输出通常 2000+ chars
L0_MIN_TOP_KEYS = 3          # 至少有 3 个顶层 key（无论叫什么）


class L0GateError(RuntimeError):
    """L0 输出不完整，放弃本次研究"""
    pass


def validate_l0_output(l0_result: dict) -> tuple[bool, list[str]]:
    """校验 L0 输出是否具备下游所需的最小信息。

    不做字段名检查（L0 输出格式因 prompt 版本而异），
    只验证：1) 非空 dict  2) 有足够 key  3) 整体长度够

    Returns:
        (is_valid, errors): is_valid=False 时应中止流水线
    """
    errors = []

    if not isinstance(l0_result, dict):
        errors.append("L0 output is not a dict")
        return False, errors

    if len(l0_result) < L0_MIN_TOP_KEYS:
        errors.append(
            f"L0 output has only {len(l0_result)} top-level keys "
            f"(min: {L0_MIN_TOP_KEYS})"
        )

    total_text = json.dumps(l0_result, ensure_ascii=False)
    if len(total_text) < L0_MIN_CONTENT_LENGTH:
        errors.append(
            f"L0 output too short: {len(total_text)} chars "
            f"(min: {L0_MIN_CONTENT_LENGTH})"
        )

    # 至少有一个 key 的值是非空（不是 "" null [] {}）
    has_content = False
    for key, val in l0_result.items():
        if val and val not in ("", "暂缺", [], {}):
            has_content = True
            break
    if not has_content:
        errors.append("L0 output has no meaningful content (all values empty)")

    return len(errors) == 0, errors
