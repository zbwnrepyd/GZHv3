from __future__ import annotations
import sys, os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from ..schemas.candidate import FieldCandidate
from ..extractors.funding_extractor import FundingExtractor


def compute_funding(company_key: str, docs: list, crunchbase_total: float | None = None) -> dict[str, FieldCandidate]:
    """Compute funding fields from documents + Crunchbase data.
    Returns dict with keys: funding_total, funding_rounds, last_funding_date.
    """
    extractor = FundingExtractor()
    return extractor.extract_all(docs, crunchbase_total)
