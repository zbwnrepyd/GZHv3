"""tests/test_derivation_pass.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from research.derivation_pass import (
    _is_missing,
    _derive_gtm_motion,
    _derive_incumbent_enum,
    _derive_data_flywheel_enum,
    _derive_proprietary_data_asset_enum,
    _derive_workflow_integration_enum,
    run_derivation_pass,
)


def test_is_missing_handles_sentinels():
    assert _is_missing(None)
    assert _is_missing("")
    assert _is_missing("暂缺")
    assert not _is_missing("有效值")


def test_derive_gtm_motion_plg():
    result = _derive_gtm_motion("以产品驱动增长（PLG）为核心，配合企业直销攻关大客户")
    assert result is not None
    assert "PLG" in result or "产品" in result


def test_derive_gtm_motion_none_on_empty():
    assert _derive_gtm_motion("") is None
    assert _derive_gtm_motion("短文") is None


def test_derive_incumbent_enum_google():
    result = _derive_incumbent_enum(
        '[{"name": "Google", "threat": "high"}, {"name": "Anthropic", "threat": "medium"}]'
    )
    assert result == "google"


def test_derive_incumbent_enum_multiple():
    result = _derive_incumbent_enum(
        "主要竞争对手包括 Salesforce、Oracle 和 SAP 三大企业软件巨头"
    )
    assert result == "multiple"


def test_run_derivation_pass_skips_existing_values():
    """已有值的字段不应被覆盖"""
    parsed = {
        "gtm_strategy": "采用产品驱动增长策略，配合企业直销",
        "gtm_motion": "已有的打法",  # 已有值
    }
    derived = run_derivation_pass("", parsed)
    assert "gtm_motion" not in derived  # 不应推导已有字段


def test_run_derivation_pass_no_api_key_still_does_rules():
    """无 API Key 时规则推导仍然执行"""
    parsed = {
        "gtm_strategy": "产品驱动增长（PLG）加上企业销售团队直销大客户",
        "market_landscape_top_players": "Google DeepMind 和 OpenAI 是主要竞争对手",
    }
    derived = run_derivation_pass("", parsed)
    # 规则推导的字段应该存在
    assert "gtm_motion" in derived or "incumbent_direct_competitor" in derived


def test_derive_data_flywheel_yes():
    result = _derive_data_flywheel_enum("核心增长引擎是数据飞轮效应，用户越多推荐越精准")
    assert result == "yes"


def test_derive_data_flywheel_partial():
    result = _derive_data_flywheel_enum("用户行为数据用于产品改进")
    assert result == "partial"


def test_derive_data_flywheel_none_on_irrelevant():
    result = _derive_data_flywheel_enum("主要通过品牌和社区驱动增长")
    assert result == "no"


def test_derive_proprietary_data_asset_core():
    result = _derive_proprietary_data_asset_enum("拥有专有数据和独家数据源构建核心壁垒")
    assert result == "yes_core"


def test_derive_proprietary_data_asset_supplementary():
    result = _derive_proprietary_data_asset_enum("利用数据分析和用户数据辅助决策")
    assert result == "yes_supplementary"


def test_derive_workflow_integration_embedded():
    result = _derive_workflow_integration_enum(
        "中间件层，深度嵌入开发者工作流", "工作流锁定和集成是核心壁垒")
    assert result in ("workflow_embedded", "system_of_record")


def test_derive_workflow_integration_none_on_insufficient():
    result = _derive_workflow_integration_enum("", "")
    assert result is None
