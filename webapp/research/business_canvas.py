"""L2 商业模式画布提取器 — 结构化商业分析，Pydantic 校验

   壁垒维度基于 Helmer 7 Powers + 技术复杂度：
   network_effects | data_moat | switching_cost | brand |
   scale_economy | tech_complexity | regulatory | counter_positioning
"""

from __future__ import annotations
from pydantic import BaseModel, field_validator, ValidationError
from typing import Optional

REVENUE_PRIMARIES = {
    "subscription", "usage_based", "enterprise_contract",
    "advertising", "marketplace", "freemium", "other"
}

LOOP_TYPES = {
    "viral", "content", "sales", "product_led",
    "partnership", "paid_acquisition"
}

MOAT_DIMENSIONS = {
    "network_effects", "data_moat", "switching_cost", "brand",
    "scale_economy", "tech_complexity", "regulatory", "counter_positioning"
}

STRENGTH_LEVELS = {"strong", "moderate", "weak", "none"}


class RevenueModel(BaseModel):
    primary: str
    secondary: list[str] = []
    pricing_public: bool = False
    evidence_snippets: list[str]

    @field_validator("primary")
    @classmethod
    def check_primary(cls, v: str) -> str:
        if v not in REVENUE_PRIMARIES:
            raise ValueError(f"primary must be one of {REVENUE_PRIMARIES}, got '{v}'")
        return v

    @field_validator("evidence_snippets")
    @classmethod
    def check_evidence(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("revenue_model evidence_snippets must not be empty")
        return v


class UnitEconomics(BaseModel):
    has_ltv_cac_data: bool = False
    ltv_estimate: Optional[str] = None
    cac_estimate: Optional[str] = None
    payback_period_months: Optional[int] = None
    gross_margin_estimate: Optional[str] = None
    disclaimer: str = ""
    evidence_snippets: list[str] = []


class GrowthLoop(BaseModel):
    loop_type: str
    description: str
    strength: str
    evidence_snippets: list[str]

    @field_validator("loop_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in LOOP_TYPES:
            raise ValueError(f"loop_type must be one of {LOOP_TYPES}, got '{v}'")
        return v

    @field_validator("strength")
    @classmethod
    def check_strength(cls, v: str) -> str:
        if v not in STRENGTH_LEVELS:
            raise ValueError(f"strength must be one of {STRENGTH_LEVELS}, got '{v}'")
        return v

    @field_validator("description")
    @classmethod
    def check_length(cls, v: str) -> str:
        if len(v) > 80:
            raise ValueError(f"description too long: {len(v)} > 80 chars")
        return v

    @field_validator("evidence_snippets")
    @classmethod
    def check_evidence(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("growth_loop evidence_snippets must not be empty")
        return v


class MoatDimension(BaseModel):
    dimension: str
    strength: str
    description: str
    evidence_snippets: list[str]

    @field_validator("dimension")
    @classmethod
    def check_dimension(cls, v: str) -> str:
        if v not in MOAT_DIMENSIONS:
            raise ValueError(f"dimension must be one of {MOAT_DIMENSIONS}, got '{v}'")
        return v

    @field_validator("strength")
    @classmethod
    def check_strength(cls, v: str) -> str:
        if v not in STRENGTH_LEVELS:
            raise ValueError(f"strength must be one of {STRENGTH_LEVELS}, got '{v}'")
        return v

    @field_validator("description")
    @classmethod
    def check_length(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError(f"description too long: {len(v)} > 100 chars")
        return v

    @field_validator("evidence_snippets")
    @classmethod
    def check_evidence(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("moat_dimension evidence_snippets must not be empty")
        return v


class BusinessCanvas(BaseModel):
    revenue_model: RevenueModel
    unit_economics: UnitEconomics
    growth_loops: list[GrowthLoop]
    moat_dimensions: list[MoatDimension]
    business_model_summary: str

    @field_validator("business_model_summary")
    @classmethod
    def check_summary_length(cls, v: str) -> str:
        if len(v) > 150:
            raise ValueError(f"business_model_summary too long: {len(v)} > 150 chars")
        return v


class BusinessCanvasExtractor:
    """从 LLM 输出中提取并校验商业模式画布"""

    def validate(self, raw_data: dict) -> tuple[Optional[BusinessCanvas], list[str]]:
        try:
            canvas = BusinessCanvas(**raw_data)
        except ValidationError as e:
            return None, [str(err) for err in e.errors()]
        return canvas, []

    def to_field_value(self, canvas: BusinessCanvas) -> str:
        import json
        return json.dumps(canvas.model_dump(), ensure_ascii=False)
