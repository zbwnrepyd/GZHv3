from __future__ import annotations
import sys, os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from ..schemas.candidate import FieldCandidate


# Source type weight (0.0-0.4)
SOURCE_TYPE_WEIGHTS = {
    "structured": 0.40,
    "filing": 0.35,
    "official_blog": 0.30,
    "trusted_media": 0.25,
    "investor_report": 0.20,
    "web_search": 0.15,
    "estimation": 0.10,
}


class ConfidenceScorer:
    """Score confidence for each field candidate based on evidence strength.

    Three dimensions:
    1. Source type weight (0.0-0.4)
    2. Evidence quantity weight (0.0-0.3)
    3. Recency weight (0.0-0.3)
    """

    def score(self, candidate: FieldCandidate, num_evidence: int = 0, doc_years: list[int] | None = None) -> float:
        source_w = SOURCE_TYPE_WEIGHTS.get(candidate.source_type, 0.10)

        # Evidence quantity
        if num_evidence >= 3:
            ev_w = 0.30
        elif num_evidence >= 2:
            ev_w = 0.20
        elif num_evidence >= 1:
            ev_w = 0.10
        else:
            ev_w = 0.0

        # Recency
        current_year = 2026
        if doc_years:
            newest = max(y for y in doc_years if y is not None)
            age = current_year - newest
        elif candidate.year:
            age = current_year - candidate.year
        else:
            age = 3  # unknown → treat as old

        if age <= 1:
            rec_w = 0.30
        elif age <= 2:
            rec_w = 0.20
        elif age <= 3:
            rec_w = 0.10
        else:
            rec_w = 0.05

        return round(source_w + ev_w + rec_w, 2)

    def map_to_status(self, confidence: float, is_direct_source: bool = False) -> str:
        """Map confidence score to field status.
        Only direct_source=true can achieve confirmed.
        """
        if is_direct_source and confidence >= 0.80:
            return "confirmed"
        if confidence >= 0.50:
            return "derived"
        if confidence >= 0.30:
            return "proxy"
        if confidence >= 0.20:
            return "llm_located"
        return "unavailable"

    def map_to_confidence_level(
        self,
        candidate: "FieldCandidate",
        num_evidence: int = 0,
        is_direct: bool = False,
    ) -> str:
        """Map candidate to user-facing confidence_level tier.

        Four tiers — independent from the internal status field:
          - verified:    Direct structured/filing/official source + high confidence + multi-evidence
          - estimated:   Web search, proxy metrics, estimation-based with moderate confidence
          - benchmark:   Industry average substitution, low/no evidence
          - unavailable: No usable value or extremely low confidence

        Design rules:
          1. estimation source_type NEVER reaches verified
          2. No value → always unavailable
          3. Direct structured/filing with 2+ evidence can achieve verified
          4. Official blog with 3+ evidence can achieve verified
          5. web_search maxes out at estimated
          6. Low confidence + 0 evidence → benchmark if value present, unavailable if no value
        """
        # Rule 1: No value → unavailable
        if candidate.value is None or candidate.value == "":
            return "unavailable"

        # Rule 2: Estimation source NEVER reaches verified
        # estimation sources include: estimation, web_search (general)
        can_be_verified = candidate.source_type not in ("estimation", "web_search")

        # Rule 3: Direct verified sources
        if can_be_verified and is_direct and num_evidence >= 2:
            score = self.score(candidate, num_evidence)
            if score >= 0.70:
                return "verified"

        # Rule 4: Structured/filing specific high-confidence path
        # filing sources need lower threshold (0.60) since they're inherently authoritative
        if candidate.source_type == "filing" and is_direct and num_evidence >= 2:
            score = self.score(candidate, num_evidence)
            if score >= 0.60:
                return "verified"

        if candidate.source_type == "structured" and is_direct:
            score = self.score(candidate, num_evidence)
            if score >= 0.80:
                return "verified"

        # Rule 5: Official blog with strong evidence
        if candidate.source_type == "official_blog" and is_direct and num_evidence >= 3:
            score = self.score(candidate, num_evidence)
            if score >= 0.65:
                return "verified"

        # Rule 6: Benchmark threshold — low confidence, no real evidence
        # estimation source with no evidence → benchmark (not unavailable)
        if num_evidence == 0 and candidate.source_type == "estimation":
            score = self.score(candidate, num_evidence)
            if score < 0.35:
                return "benchmark"

        # Rule 7: Very low confidence + no evidence → unavailable
        score = self.score(candidate, num_evidence)
        if num_evidence == 0 and score < 0.26:
            return "unavailable"

        # Rule 8: Default estimated for anything with value + some confidence
        if score >= 0.26:
            return "estimated"

        # Rule 9: Very low confidence with value → benchmark
        if candidate.value is not None and candidate.value != "":
            return "benchmark"

        return "unavailable"
