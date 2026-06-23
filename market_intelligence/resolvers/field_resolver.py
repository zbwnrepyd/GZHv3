from __future__ import annotations
import sys, os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from ..schemas.candidate import FieldCandidate


# Status priority for resolution (higher = better)
STATUS_PRIORITY = {
    "confirmed": 100,
    "derived": 75,
    "proxy": 50,
    "llm_located": 25,
    "unavailable": 0,
    "not_applicable": -1,
}


class MarketFieldResolver:
    """Resolve final field values from multiple candidate sources.
    Priority: confirmed > derived > proxy > llm_located > unavailable.
    """

    def resolve(self, candidates_by_field: dict[str, list[FieldCandidate]]) -> dict[str, FieldCandidate]:
        """Pick best candidate per field. Returns {field_key: best_candidate}."""
        result = {}
        for field_key, candidates in candidates_by_field.items():
            result[field_key] = self._pick_best(field_key, candidates)
        return result

    def _pick_best(self, field_key: str, candidates: list[FieldCandidate]) -> FieldCandidate:
        if not candidates:
            return FieldCandidate(field_key=field_key, value=None, status="unavailable", confidence=0.0, unavailable_reason="无候选值")

        usable = [c for c in candidates if c.status != "not_applicable"]

        # Prefer usable (non-null) values
        valued = [c for c in usable if c.is_usable()]
        pool = valued if valued else usable
        if not pool:
            return FieldCandidate(field_key=field_key, value=None, status="unavailable", confidence=0.0, unavailable_reason="所有候选值为空")

        # Score: status_priority * 0.5 + confidence * 0.4 + (evidence_count bonus) * 0.1
        def score(c: FieldCandidate) -> float:
            sp = STATUS_PRIORITY.get(c.status, 0) / 100.0
            ev_bonus = min(len(c.evidence_ids) * 0.05, 0.1)
            return sp * 0.5 + c.confidence * 0.4 + ev_bonus

        return max(pool, key=score)
