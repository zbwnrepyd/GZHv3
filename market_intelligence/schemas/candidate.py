from __future__ import annotations
from dataclasses import dataclass, field


# Valid confidence_level values
VALID_CONFIDENCE_LEVELS = {"verified", "estimated", "benchmark", "unavailable"}


@dataclass
class FieldCandidate:
    """A candidate value for a market/financial field, produced by extractors or estimators.

    confidence_level 是新增的置信度分级维度（独立于 status）：
      - verified:    从公司官方/知名媒体/权威报告直接提取
      - estimated:   从代理指标推算（SimilarWeb/GitHub Stars/PH votes 等）
      - benchmark:   用行业均值填充（标注"不代表公司披露"）
      - unavailable: 未公开，不强行造数
    """
    field_key: str = ""
    value: float | str | None = None
    value_text: str = ""                # Human-readable form (e.g. "$10.4B")
    currency: str = "USD"
    year: int | None = None
    source_type: str = ""               # structured|filing|web_search|investor_report|estimation
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "derived"             # confirmed|derived|proxy|llm_located|unavailable|not_applicable
    confidence: float = 0.0
    confidence_level: str = "unavailable"  # verified|estimated|benchmark|unavailable
    formula: str = ""
    assumptions: list[str] = field(default_factory=list)
    region: str = ""
    segment: str = ""
    source_url: str = ""
    unavailable_reason: str = ""

    def __post_init__(self):
        if self.confidence_level not in VALID_CONFIDENCE_LEVELS:
            raise ValueError(
                f"confidence_level must be one of {VALID_CONFIDENCE_LEVELS}, "
                f"got '{self.confidence_level}'"
            )

    def is_usable(self) -> bool:
        return self.value is not None and self.value != ""

    def to_dict(self) -> dict:
        return {
            "field_key": self.field_key,
            "value": self.value,
            "value_text": self.value_text,
            "currency": self.currency,
            "year": self.year,
            "source_type": self.source_type,
            "status": self.status,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "formula": self.formula,
            "assumptions": self.assumptions,
            "region": self.region,
            "segment": self.segment,
            "source_url": self.source_url,
            "unavailable_reason": self.unavailable_reason,
            "evidence_count": len(self.evidence_ids),
        }
