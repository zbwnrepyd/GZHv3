from __future__ import annotations
import sys, os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from ..schemas.candidate import FieldCandidate
from ..extractors.market_number import MarketNumberExtractor


def estimate_from_comparables(docs: list, field_key: str = "market_size_value") -> FieldCandidate:
    """Use competitor/industry market data as proxy.
    Extracts market numbers from evidence, returns best-match proxy candidate.
    Status always = "proxy", confidence 0.3-0.6.
    """
    extractor = MarketNumberExtractor()
    all_candidates = []
    for doc in docs:
        content = getattr(doc, 'content', '') or ''
        all_candidates.extend(extractor.extract(content, getattr(doc, 'source_url', ''), getattr(doc, 'source_family', 'web_search')))

    # Filter for the target field
    field_cands = [c for c in all_candidates if c.field_key == field_key and c.value is not None]
    if not field_cands:
        return FieldCandidate(
            field_key=field_key, value=None, status="unavailable", confidence=0.0,
            unavailable_reason="未找到可比公司/赛道市场数据",
        )

    # Pick highest confidence
    best = max(field_cands, key=lambda c: c.confidence)
    best.status = "proxy"
    best.confidence = min(best.confidence, 0.6)
    best.source_type = "comparable"
    return best
