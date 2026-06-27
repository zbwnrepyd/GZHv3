"""tests/test_scoring_inference.py — scoring_inference 单元测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from research.scoring_inference import (
    infer_v2_scoring_fields,
    _build_context,
    VALID_VALUES,
    V2_SCORING_FIELDS,
)


def test_build_context_returns_empty_for_no_useful_fields():
    parsed = {"company_name": "Acme", "moat": "", "ecosystem_niche": "暂缺"}
    ctx = _build_context(parsed)
    assert ctx == ""


def test_build_context_includes_non_empty_fields():
    parsed = {
        "moat": "强数据护城河",
        "ecosystem_niche": "中间件层",
        "company_name": "Acme",
    }
    ctx = _build_context(parsed)
    assert "moat" in ctx
    assert "强数据护城河" in ctx


def test_valid_values_covers_all_v2_fields():
    for field in V2_SCORING_FIELDS:
        assert field in VALID_VALUES
        assert len(VALID_VALUES[field]) >= 2


def test_infer_returns_empty_on_missing_api_key(monkeypatch):
    """无 API Key 时应非阻断返回空 dict"""
    def mock_call_deepseek(*args, **kwargs):
        raise RuntimeError("no api key")
    monkeypatch.setattr(
        "deepseek_client.call_deepseek",
        mock_call_deepseek,
        raising=False,
    )
    result = infer_v2_scoring_fields("", {"moat": "test moat content here"})
    assert isinstance(result, dict)


def test_infer_returns_empty_on_insufficient_context():
    result = infer_v2_scoring_fields("fake-key", {"moat": "x"})
    assert result == {}


def test_infer_validates_output(monkeypatch):
    """LLM 输出非法值时应被过滤"""
    import json

    def mock_call(*args, **kwargs):
        return json.dumps({
            "incumbent_overlap": "invalid_value",
            "workflow_lock_in": "workflow_embedded",   # 合法
            "data_lock_in": "strong",                  # 合法
        })

    monkeypatch.setattr("deepseek_client.call_deepseek", mock_call, raising=False)

    parsed = {"moat": "A" * 200}  # 足够长的上下文
    result = infer_v2_scoring_fields("key", parsed)
    assert "incumbent_overlap" not in result   # 非法值被过滤
    assert result.get("workflow_lock_in") == "workflow_embedded"
    assert result.get("data_lock_in") == "strong"
