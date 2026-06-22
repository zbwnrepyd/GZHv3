"""L0 质量门控 — 单元测试（匹配 L0 实际输出结构）"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))


def _validate(*args, **kwargs):
    from research.l0_gate import validate_l0_output
    return validate_l0_output(*args, **kwargs)


def _valid_l0():
    """构建一个完整的 L0 输出样本，匹配 layer0-cleaner 的实际输出结构"""
    return {
        "company_identity": {
            "company_key": "anthropic_com",
            "display_name": "Anthropic",
            "canonical_name": "Anthropic PBC",
            "website_host": "anthropic.com",
        },
        "evidence_pool": [
            {"source": "website", "title": "About Anthropic",
             "url": "https://www.anthropic.com/company", "content": "Anthropic is an AI safety company...",
             "score": 0.85},
            {"source": "tavily", "title": "Anthropic raises $4B",
             "url": "https://techcrunch.com/...", "content": "Anthropic has raised...",
             "score": 0.75},
        ],
        "source_audit": {"website": 2, "tavily": 5, "github": 1},
        "source_warnings": [],
        "raw_sources": {},
    }


class TestL0Gate(unittest.TestCase):
    """验证 L0 输出完整性校验"""

    def test_valid_l0_passes(self):
        """完整的 L0 输出应通过校验"""
        l0 = _valid_l0()
        is_valid, errors = _validate(l0)
        self.assertTrue(is_valid, f"Expected valid but got errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_missing_company_identity_fails(self):
        """缺少 company_identity 应校验失败"""
        l0 = _valid_l0()
        del l0["company_identity"]
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)
        self.assertTrue(any("company_identity" in e for e in errors))

    def test_missing_evidence_pool_fails(self):
        """缺少 evidence_pool 应校验失败"""
        l0 = _valid_l0()
        del l0["evidence_pool"]
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)

    def test_empty_evidence_pool_fails(self):
        """evidence_pool 为空列表应失败"""
        l0 = _valid_l0()
        l0["evidence_pool"] = []
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)
        self.assertTrue(any("empty" in e.lower() for e in errors))

    def test_evidence_pool_not_list_fails(self):
        """evidence_pool 不是列表应失败"""
        l0 = _valid_l0()
        l0["evidence_pool"] = "not a list"
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)

    def test_missing_company_key_in_identity_fails(self):
        """company_identity 缺少 company_key 应失败"""
        l0 = _valid_l0()
        l0["company_identity"] = {"display_name": "Test"}
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)
        self.assertTrue(any("company_key" in e for e in errors))

    def test_missing_display_name_in_identity_fails(self):
        """company_identity 缺少 display_name 应失败"""
        l0 = _valid_l0()
        l0["company_identity"] = {"company_key": "test"}
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)
        self.assertTrue(any("display_name" in e for e in errors))

    def test_company_identity_not_dict_fails(self):
        """company_identity 不是 dict 应失败"""
        l0 = _valid_l0()
        l0["company_identity"] = "just a string"
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)

    def test_too_short_output_fails(self):
        """总输出太短应失败"""
        l0 = {
            "company_identity": {"company_key": "a", "display_name": "b"},
            "evidence_pool": [{"x": "y"}],
        }
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)
        self.assertTrue(any("short" in e for e in errors))

    def test_minimal_valid_passes(self):
        """刚好超过 500 chars 的有效输出应通过"""
        l0 = {
            "company_identity": {"company_key": "test_co", "display_name": "TestCo"},
            "evidence_pool": [
                {"source": "web", "title": "X" * 60, "url": "https://x.com",
                 "content": "Y" * 300, "score": 0.5}
            ],
        }
        is_valid, errors = _validate(l0)
        self.assertTrue(is_valid, f"Expected valid but got errors: {errors}")

    def test_gate_error_is_runtime_error(self):
        """L0GateError 应是 RuntimeError 的子类"""
        from research.l0_gate import L0GateError
        try:
            raise L0GateError("test")
        except RuntimeError:
            pass
        else:
            self.fail("L0GateError should be caught as RuntimeError")


if __name__ == "__main__":
    unittest.main()
