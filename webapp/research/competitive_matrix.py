"""L1 竞品矩阵提取器 — 结构化竞品对比，Pydantic 校验"""

from __future__ import annotations
from pydantic import BaseModel, field_validator, ValidationError
from typing import Optional

THREAT_LEVELS = {"high", "medium", "low"}
POSITIONS = {"leader", "strong_contender", "niche_player", "early_stage"}


class CompetitorItem(BaseModel):
    name: str
    url: Optional[str] = None
    overlap_areas: list[str]
    strengths: list[str]
    weaknesses: list[str]
    threat_level: str
    evidence_snippets: list[str]

    @field_validator("threat_level")
    @classmethod
    def check_threat(cls, v: str) -> str:
        if v not in THREAT_LEVELS:
            raise ValueError(f"threat_level must be one of {THREAT_LEVELS}, got '{v}'")
        return v

    @field_validator("evidence_snippets")
    @classmethod
    def check_evidence(cls, v: list[str]) -> list[str]:
        if not v or len(v) == 0:
            raise ValueError("evidence_snippets must not be empty")
        for i, snippet in enumerate(v):
            if len(snippet) > 100:
                raise ValueError(f"evidence_snippets[{i}] too long: {len(snippet)} > 100 chars")
        return v

    @field_validator("overlap_areas")
    @classmethod
    def check_overlap(cls, v: list[str]) -> list[str]:
        if not v or len(v) == 0:
            raise ValueError("overlap_areas must not be empty")
        return v


class CompetitiveMatrix(BaseModel):
    competitors: list[CompetitorItem]
    target_company_position: str
    competitive_landscape_summary: str

    @field_validator("target_company_position")
    @classmethod
    def check_position(cls, v: str) -> str:
        if v not in POSITIONS:
            raise ValueError(f"target_company_position must be one of {POSITIONS}, got '{v}'")
        return v

    @field_validator("competitors")
    @classmethod
    def check_competitors_count(cls, v: list[CompetitorItem]) -> list[CompetitorItem]:
        if len(v) < 2:
            raise ValueError(f"at least 2 competitors required, got {len(v)}")
        if len(v) > 6:
            raise ValueError(f"at most 6 competitors allowed, got {len(v)}")
        return v


class CompetitiveMatrixExtractor:
    """从 LLM 输出中提取并校验竞品矩阵"""

    def validate(self, raw_data: dict) -> tuple[Optional[CompetitiveMatrix], list[str]]:
        try:
            matrix = CompetitiveMatrix(**raw_data)
        except ValidationError as e:
            return None, [str(err) for err in e.errors()]
        return matrix, []

    def to_field_value(self, matrix: CompetitiveMatrix) -> str:
        import json
        return json.dumps(matrix.model_dump(), ensure_ascii=False)
