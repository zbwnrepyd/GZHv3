"""Test business_canvas.py — L2 商业模式画布提取器单元测试"""

import json
import pytest
from webapp.research.business_canvas import (
    RevenueModel,
    UnitEconomics,
    GrowthLoop,
    MoatDimension,
    BusinessCanvas,
    BusinessCanvasExtractor,
    REVENUE_PRIMARIES,
    LOOP_TYPES,
    MOAT_DIMENSIONS,
    STRENGTH_LEVELS,
)
from pydantic import ValidationError


# ── Valid Fixtures ──

VALID_REVENUE = {
    "primary": "subscription",
    "secondary": ["usage_based"],
    "pricing_public": True,
    "evidence_snippets": ["$20/month per seat, billed annually"],
}

VALID_UNIT_ECONOMICS = {
    "has_ltv_cac_data": False,
    "ltv_estimate": None,
    "cac_estimate": None,
    "payback_period_months": None,
    "gross_margin_estimate": None,
    "disclaimer": "未公开披露单位经济学数据",
    "evidence_snippets": ["公司未公开LTV/CAC数据"],
}

VALID_GROWTH_LOOP = {
    "loop_type": "product_led",
    "description": "用户邀请团队成员协作，形成自然扩张",
    "strength": "moderate",
    "evidence_snippets": ["团队协作是核心使用场景"],
}

VALID_MOAT_1 = {
    "dimension": "switching_cost",
    "strength": "strong",
    "description": "深度集成到客户工作流中，替换成本极高",
    "evidence_snippets": ["客户需要重新培训团队才能迁移"],
}

VALID_MOAT_2 = {
    "dimension": "network_effects",
    "strength": "moderate",
    "description": "用户越多数据越多，模型效果越好",
    "evidence_snippets": ["平台用户量增长带动推荐精度提升"],
}

VALID_MOAT_3 = {
    "dimension": "data_moat",
    "strength": "strong",
    "description": "拥有独特的专有训练数据集",
    "evidence_snippets": ["积累数百万标注样本"],
}

VALID_MOAT_4 = {
    "dimension": "tech_complexity",
    "strength": "moderate",
    "description": "模型架构和推理优化构成技术门槛",
    "evidence_snippets": ["自研推理框架比开源方案快3倍"],
}


def valid_canvas_data():
    return {
        "revenue_model": VALID_REVENUE,
        "unit_economics": VALID_UNIT_ECONOMICS,
        "growth_loops": [VALID_GROWTH_LOOP],
        "moat_dimensions": [VALID_MOAT_1, VALID_MOAT_2, VALID_MOAT_3, VALID_MOAT_4],
        "business_model_summary": "SaaS订阅+用量计费的PLG模式，以切换成本和数据壁垒筑护城河",
    }


# ── Test 1: Valid BusinessCanvas with 4 moat dimensions passes ──

def test_valid_business_canvas_passes():
    data = valid_canvas_data()
    canvas = BusinessCanvas(**data)
    assert canvas.revenue_model.primary == "subscription"
    assert len(canvas.moat_dimensions) == 4
    assert canvas.growth_loops[0].loop_type == "product_led"


# ── Test 2: Invalid revenue_model.primary rejected ──

def test_invalid_revenue_primary_rejected():
    data = valid_canvas_data()
    data["revenue_model"] = {
        "primary": "donations",
        "secondary": [],
        "pricing_public": False,
        "evidence_snippets": ["全靠捐款"],
    }
    with pytest.raises(ValidationError) as exc_info:
        BusinessCanvas(**data)
    errors = str(exc_info.value)
    assert "donations" in errors or "primary" in errors


# ── Test 3: Invalid moat dimension name rejected ──

def test_invalid_moat_dimension_rejected():
    data = valid_canvas_data()
    data["moat_dimensions"] = [
        {
            "dimension": "luck",
            "strength": "strong",
            "description": "纯靠运气",
            "evidence_snippets": ["创始人说的"],
        },
        VALID_MOAT_1,
        VALID_MOAT_2,
        VALID_MOAT_3,
    ]
    with pytest.raises(ValidationError) as exc_info:
        BusinessCanvas(**data)
    errors = str(exc_info.value)
    assert "luck" in errors or "dimension" in errors


# ── Test 4: Invalid growth_loop type rejected ──

def test_invalid_growth_loop_type_rejected():
    data = valid_canvas_data()
    data["growth_loops"] = [
        {
            "loop_type": "magic",
            "description": "魔法增长",
            "strength": "strong",
            "evidence_snippets": ["巫术"],
        },
    ]
    with pytest.raises(ValidationError) as exc_info:
        BusinessCanvas(**data)
    errors = str(exc_info.value)
    assert "magic" in errors or "loop_type" in errors


# ── Test 5: Empty evidence_snippets in growth_loop rejected ──

def test_empty_evidence_in_growth_loop_rejected():
    data = valid_canvas_data()
    data["growth_loops"] = [
        {
            "loop_type": "viral",
            "description": "病毒传播",
            "strength": "strong",
            "evidence_snippets": [],
        },
    ]
    with pytest.raises(ValidationError) as exc_info:
        BusinessCanvas(**data)
    errors = str(exc_info.value)
    assert "evidence" in errors.lower() or "snippets" in errors.lower()


# ── Test 6: Extractor.validate() with valid data returns (canvas, []) ──

def test_extractor_validate_valid_returns_canvas():
    extractor = BusinessCanvasExtractor()
    canvas, errors = extractor.validate(valid_canvas_data())
    assert canvas is not None
    assert errors == []
    assert isinstance(canvas, BusinessCanvas)


# ── Test 7: Valid UnitEconomics with has_ltv_cac_data=False passes ──

def test_unit_economics_no_data_valid():
    ue = UnitEconomics(**VALID_UNIT_ECONOMICS)
    assert ue.has_ltv_cac_data is False
    assert ue.ltv_estimate is None
    assert ue.cac_estimate is None
    assert "未公开" in ue.disclaimer


# ── Test 8: business_model_summary > 150 chars rejected ──

def test_summary_too_long_rejected():
    data = valid_canvas_data()
    data["business_model_summary"] = "X" * 151
    with pytest.raises(ValidationError) as exc_info:
        BusinessCanvas(**data)
    errors = str(exc_info.value)
    assert "150" in errors or "summary" in errors.lower()


# ── Test 9: to_field_value() returns valid JSON string ──

def test_to_field_value_returns_valid_json():
    canvas = BusinessCanvas(**valid_canvas_data())
    extractor = BusinessCanvasExtractor()
    result = extractor.to_field_value(canvas)
    assert isinstance(result, str)
    # 可反序列化
    parsed = json.loads(result)
    assert parsed["revenue_model"]["primary"] == "subscription"
    assert len(parsed["moat_dimensions"]) == 4


# ── Test: description > 100 chars in moat_dimension rejected ──

def test_moat_description_too_long_rejected():
    with pytest.raises(ValidationError) as exc_info:
        MoatDimension(
            dimension="brand",
            strength="strong",
            description="X" * 101,
            evidence_snippets=["来源"],
        )
    errors = str(exc_info.value)
    assert "100" in errors or "description" in errors.lower()


# ── Test: description > 80 chars in growth_loop rejected ──

def test_growth_loop_description_too_long_rejected():
    with pytest.raises(ValidationError) as exc_info:
        GrowthLoop(
            loop_type="content",
            description="Y" * 81,
            strength="moderate",
            evidence_snippets=["来源"],
        )
    errors = str(exc_info.value)
    assert "80" in errors or "description" in errors.lower()
