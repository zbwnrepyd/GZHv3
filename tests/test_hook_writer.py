"""tests/test_hook_writer.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from research.hook_writer import (
    generate_hook_paragraphs,
    _build_writing_context,
    HOOK_FIELDS,
)


def test_build_writing_context_excludes_missing():
    parsed = {
        "company_def": "AI 驱动的风险平台",
        "main_product_def": "暂缺",
        "growth_metrics": "",
    }
    ctx = _build_writing_context(parsed)
    assert "AI 驱动的风险平台" in ctx
    assert "暂缺" not in ctx


def test_build_writing_context_returns_empty_on_all_missing():
    parsed = {"company_def": "暂缺", "main_product_def": ""}
    ctx = _build_writing_context(parsed)
    assert ctx == ""


def test_generate_returns_empty_on_short_context():
    result = generate_hook_paragraphs("key", {"company_def": "x"}, "prompt")
    assert result == {}


def test_generate_returns_empty_on_missing_api_key(monkeypatch):
    def mock_call(*args, **kwargs):
        raise RuntimeError("no key")
    monkeypatch.setattr("deepseek_client.call_deepseek", mock_call, raising=False)
    parsed = {f: "A" * 50 for f in ["company_def", "main_product_def", "moat"]}
    result = generate_hook_paragraphs("", parsed, "prompt")
    assert result == {}


def test_generate_validates_length(monkeypatch):
    """输出长度不合理的字段应被过滤"""
    import json

    def mock_call(*args, **kwargs):
        return json.dumps({
            "hook_paragraph_1": "太短",           # < 20字，过滤
            "hook_paragraph_2": "A" * 600,         # > 500字，过滤
            "hook_paragraph_3": "这是一段合理长度的钩子段落，" * 4,  # 合理长度
        })

    monkeypatch.setattr("deepseek_client.call_deepseek", mock_call, raising=False)
    parsed = {f: "A" * 50 for f in ["company_def", "main_product_def", "moat",
                                     "main_product_highlight", "growth_metrics"]}
    result = generate_hook_paragraphs("key", parsed, "prompt")
    assert "hook_paragraph_1" not in result
    assert "hook_paragraph_2" not in result
    assert "hook_paragraph_3" in result


def test_hook_fields_constant():
    assert HOOK_FIELDS == ["hook_paragraph_1", "hook_paragraph_2", "hook_paragraph_3"]
