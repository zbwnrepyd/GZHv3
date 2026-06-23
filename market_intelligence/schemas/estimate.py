from __future__ import annotations
from dataclasses import dataclass, field
import json as _json
import uuid as _uuid


@dataclass
class MarketEstimate:
    """A computed market estimate (e.g. bottom-up TAM). Persisted to market_estimates table."""
    company_key: str = ""
    estimate_type: str = ""         # bottom_up|comparable|proxy|direct_report|funding_calc
    field_key: str = ""
    formula: str = ""
    inputs: dict = field(default_factory=dict)
    result_value: float | None = None
    result_text: str = ""
    currency: str = "USD"
    year: int | None = None
    confidence: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "derived"
    assumptions: list[str] = field(default_factory=list)
    disclaimer: str = ""
    region: str = ""
    segment: str = ""
    source_url: str = ""

    def to_db_row(self) -> dict:
        return {
            "id": _uuid.uuid4().hex[:16],
            "company_key": self.company_key,
            "field_key": self.field_key,
            "estimate_type": self.estimate_type,
            "formula": self.formula,
            "inputs_json": _json.dumps(self.inputs, ensure_ascii=False) if self.inputs else None,
            "result_value": self.result_value,
            "result_text": self.result_text,
            "currency": self.currency,
            "year": self.year,
            "confidence": self.confidence,
            "evidence_ids": _json.dumps(self.evidence_ids) if self.evidence_ids else None,
            "status": self.status,
            "assumptions": _json.dumps(self.assumptions, ensure_ascii=False) if self.assumptions else None,
            "disclaimer": self.disclaimer,
            "region": self.region,
            "segment": self.segment,
            "source_url": self.source_url,
        }
