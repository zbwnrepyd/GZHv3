from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class MarketEvidence:
    """Wrapper around SourceDocument with market-specific metadata."""
    extracted_numbers: list[dict] = field(default_factory=list)
    # [{"value": 10.4, "unit": "B", "currency": "USD", "year": 2025, "field_key": "market_size_value"}]
    relevant_fields: list[str] = field(default_factory=list)
    snippet: str = ""
    source_url: str = ""
    title: str = ""
    source_family: str = ""
