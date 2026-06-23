from __future__ import annotations
import sys, os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from ..schemas.candidate import FieldCandidate
from ..schemas.estimate import MarketEstimate
from ..extractors.parameter_extractor import extract_tam_params


def compute_bottom_up_tam(
    company_key: str, docs: list, category: str = "",
) -> FieldCandidate:
    """TAM = addressable_users × penetration_rate × ARPU.

    - Missing params → unavailable with explicit reason
    - All params present → derived (confidence capped at 0.75)
    - Never returns confirmed
    """
    params = extract_tam_params(docs, category)

    total_users = params.get("total_users")
    penetration_rate = params.get("penetration_rate")
    arpu = params.get("arpu")

    missing = []
    if total_users is None:
        missing.append("total_addressable_users")
    if penetration_rate is None:
        missing.append("penetration_rate")
    if arpu is None:
        missing.append("arpu")

    if missing:
        return FieldCandidate(
            field_key="tam_value", value=None, status="unavailable", confidence=0.0,
            formula="TAM = users × penetration × ARPU",
            unavailable_reason=f"无法计算自底向上TAM：缺少参数 {', '.join(missing)}",
            region=params.get("region", ""), segment=params.get("segment", ""),
            year=params.get("year"),
        )

    if penetration_rate < 0 or penetration_rate > 1:
        return FieldCandidate(
            field_key="tam_value", value=None, status="unavailable", confidence=0.0,
            formula=f"TAM = {total_users:,.0f} × {penetration_rate} × ${arpu}",
            unavailable_reason=f"渗透率 {penetration_rate} 超出有效范围 [0, 1]",
        )

    tam = total_users * penetration_rate * arpu
    base_confidence = params.get("confidence", 0.5)
    confidence = min(base_confidence, 0.75)

    formula_str = f"TAM = {total_users:,.0f} users × {penetration_rate:.1%} × ${arpu:,.0f}/year"

    vt = f"${tam/1e9:.1f}B" if tam >= 1e9 else f"${tam/1e6:.1f}M"

    return FieldCandidate(
        field_key="tam_value", value=tam, value_text=vt, currency="USD",
        year=params.get("year"), source_type="estimation", status="derived",
        confidence=round(confidence, 2), formula=formula_str,
        assumptions=[
            f"可寻址用户: {total_users:,.0f} ({params.get('segment', category)})",
            f"付费渗透率: {penetration_rate:.1%}",
            f"ARPU: ${arpu:,.0f}/年",
        ],
        region=params.get("region", ""), segment=params.get("segment", ""),
    )
