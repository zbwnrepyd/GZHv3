"""L0 质量门控 — 单元测试"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))


def _validate(*args, **kwargs):
    from research.l0_gate import validate_l0_output
    return validate_l0_output(*args, **kwargs)


class TestL0Gate(unittest.TestCase):
    """验证 L0 输出完整性校验"""

    # ── 1. Valid L0 output passes validation ──

    def test_valid_output_passes(self):
        """完整的 L0 输出应通过校验"""
        l0_result = {
            "company_name": "Anthropic",
            "company_def": "An AI safety and research company building Claude, "
                           "a family of large language models. Founded by former "
                           "OpenAI researchers, Anthropic focuses on constitutional "
                           "AI and safe deployment of frontier AI systems for "
                           "enterprise customers.",
            "main_product_name": "Claude",
            "founded_date": "2021",
            "company_type": "AI / LLM",
            "headquarters": "San Francisco, CA",
            "founder_name": "Dario Amodei",
        }
        is_valid, errors = _validate(l0_result)
        self.assertTrue(is_valid, f"Expected valid but got errors: {errors}")
        self.assertEqual(len(errors), 0, f"Expected no errors but got: {errors}")

    # ── 2. Missing company_name fails ──

    def test_missing_company_name_fails(self):
        """缺少 company_name 应校验失败"""
        l0_result = {
            "company_def": "An AI company.",
            "main_product_name": "Claude",
            "founded_date": "2021",
        }
        is_valid, errors = _validate(l0_result)
        self.assertFalse(is_valid)
        self.assertTrue(
            any("company_name" in e for e in errors),
            f"Expected 'company_name' in errors but got: {errors}",
        )

    # ── 3. Missing multiple fields reports all errors ──

    def test_missing_multiple_fields_reports_all(self):
        """缺少多个字段时应报告所有缺失"""
        l0_result = {
            "company_name": "",  # empty string
            # company_def missing entirely
            # main_product_name missing entirely
            "founded_date": "   ",  # whitespace only
        }
        is_valid, errors = _validate(l0_result)
        self.assertFalse(is_valid)
        self.assertTrue(len(errors) >= 3,
                        f"Expected at least 3 errors for 3 missing fields but got: {errors}")

    # ── 4. Too-short output fails ──

    def test_too_short_output_fails(self):
        """所有字段为 1 个字符时因总字符太少而失败"""
        l0_result = {
            "company_name": "A",
            "company_def": "B",
            "main_product_name": "C",
            "founded_date": "D",
        }
        is_valid, errors = _validate(l0_result)
        self.assertFalse(is_valid)
        self.assertTrue(
            any("short" in e for e in errors),
            f"Expected 'short' in errors but got: {errors}",
        )

    # ── 5. Minimal valid output (just above 200 chars) passes ──

    def test_minimal_valid_output_passes(self):
        """刚好超过 200 字符的有效输出应通过"""
        # Build a result where required fields + JSON overhead > 200 chars
        l0_result = {
            "company_name": "TestCo",
            "company_def": "A" * 140,  # enough to push total over 200
            "main_product_name": "TestProduct",
            "founded_date": "2020",
        }
        is_valid, errors = _validate(l0_result)
        self.assertTrue(is_valid, f"Expected valid but got errors: {errors}")

    # ── 6. None value for a required field fails ──

    def test_none_value_fails(self):
        """required 字段值为 None 时应失败"""
        l0_result = {
            "company_name": None,
            "company_def": "An AI company with a long description " * 5,
            "main_product_name": "Claude",
            "founded_date": "2021",
        }
        is_valid, errors = _validate(l0_result)
        self.assertFalse(is_valid)
        self.assertTrue(
            any("company_name" in e for e in errors),
            f"Expected 'company_name' in errors but got: {errors}",
        )

    # ── 7. All required fields present but one whitespace fails ──

    def test_whitespace_only_field_fails(self):
        """required 字段仅为空白字符时应失败"""
        l0_result = {
            "company_name": "Anthropic",
            "company_def": "An AI company " * 20,
            "main_product_name": "   ",
            "founded_date": "2021",
        }
        is_valid, errors = _validate(l0_result)
        self.assertFalse(is_valid)
        self.assertTrue(
            any("main_product_name" in e for e in errors),
            f"Expected 'main_product_name' in errors but got: {errors}",
        )

    # ── 8. L0GateError is a RuntimeError subclass ──

    def test_gate_error_is_runtime_error(self):
        """L0GateError 应是 RuntimeError 的子类"""
        from research.l0_gate import L0GateError
        with self.assertRaises(L0GateError):
            raise L0GateError("test error")
        # Verify it's also a RuntimeError
        try:
            raise L0GateError("test")
        except RuntimeError:
            pass  # expected
        else:
            self.fail("L0GateError should be caught as RuntimeError")


if __name__ == "__main__":
    unittest.main()
