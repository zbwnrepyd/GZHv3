"""L0 质量门控 — 最小校验：JSON 有效 + 有内容 + 长度够"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))


def _validate(*args, **kwargs):
    from research.l0_gate import validate_l0_output
    return validate_l0_output(*args, **kwargs)


def _valid_l0():
    """L0 最小可接受输出（至少 3 个 key，>=500 chars，有内容）"""
    return {
        "公司基本信息": "Cursor is an AI code editor built on VS Code. "
                        "Founded in 2022 by Aman Sanger, Arvid Lunnemark, "
                        "Michael Truell, and Sualeh Asif. Headquartered in "
                        "San Francisco, CA. The company has raised over $100M "
                        "in funding from Thrive Capital, Andreessen Horowitz, "
                        "and others.",
        "产品信息": "Cursor is an AI-first code editor that integrates deeply "
                   "with LLMs to provide code completion, chat, and editing "
                   "features. It competes with GitHub Copilot and is used by "
                   "professional developers at companies like OpenAI, Shopify, "
                   "and others. The product offers a freemium model with paid "
                   "Pro and Business plans.",
        "融资信息": "Series B, $100M+, led by Thrive Capital, 2024.",
        "创始人信息": "Aman Sanger (MIT), Michael Truell (MIT), "
                    "Arvid Lunnemark (MIT), Sualeh Asif (MIT).",
    }


class TestL0Gate(unittest.TestCase):

    def test_valid_l0_passes(self):
        """至少有 3 个 key 且有内容 → 通过"""
        l0 = _valid_l0()
        is_valid, errors = _validate(l0)
        self.assertTrue(is_valid, f"Expected valid but got errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_not_dict_fails(self):
        """非 dict → 失败"""
        is_valid, errors = _validate("just a string")
        self.assertFalse(is_valid)

    def test_too_few_keys_fails(self):
        """只有 1-2 个 key → 失败"""
        l0 = {"x": "y", "z": "w"}
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)
        self.assertTrue(any("keys" in e for e in errors))

    def test_too_short_fails(self):
        """内容太短 → 失败"""
        l0 = {"a": "b", "c": "d", "e": "f"}
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)
        self.assertTrue(any("short" in e for e in errors))

    def test_no_meaningful_content_fails(self):
        """所有 value 为空字符串/null/空列表 → 失败"""
        l0 = {"a": "", "b": None, "c": [], "d": {}}
        is_valid, errors = _validate(l0)
        self.assertFalse(is_valid)
        self.assertTrue(any("meaningful" in e.lower() for e in errors))

    def test_empty_dict_fails(self):
        """空 dict → 失败"""
        is_valid, errors = _validate({})
        self.assertFalse(is_valid)

    def test_minimal_valid_passes(self):
        """最少 key (3) + 足够长 → 通过"""
        l0 = {
            "公司基本信息": "X" * 200,
            "产品信息": "Y" * 150,
            "融资信息": "Z" * 150,
        }
        is_valid, errors = _validate(l0)
        self.assertTrue(is_valid, f"Expected valid but got errors: {errors}")

    def test_gate_error_is_runtime_error(self):
        """L0GateError 继承 RuntimeError"""
        from research.l0_gate import L0GateError
        try:
            raise L0GateError("test")
        except RuntimeError:
            pass
        else:
            self.fail("L0GateError should be caught as RuntimeError")

    def test_various_l0_output_formats_pass(self):
        """不同格式的 L0 输出（只要满足最小要求）都应通过"""
        # Format 1: structural keys (need extra length)
        l0_1 = {
            "company_identity": {"company_key": "test", "display_name": "TestCo"},
            "evidence_pool": [{"source": "web", "title": "About", "url": "https://x.com",
                               "content": "X" * 300, "score": 0.8}],
            "source_audit": {"website": 1, "tavily": 3},
        }
        self.assertTrue(_validate(l0_1)[0])

        # Format 2: Chinese dimension keys
        l0_2 = {
            "公司基本信息": "X" * 200,
            "创始人信息": "Y" * 150,
            "产品信息": "Z" * 150,
        }
        self.assertTrue(_validate(l0_2)[0])

        # Format 3: mixed keys (need longer content)
        l0_3 = {
            "company_name": "TestCo",
            "product": "X" * 300,
            "funding": "Series A, $10M from Sequoia. The round was announced in 2023 and values the company at $50M post-money. Additional investors include Y Combinator and Andreessen Horowitz.",
            "team": "Founded by Jane Doe (ex-Google) and John Smith (ex-Meta) in 2022. 15 employees.",
        }
        self.assertTrue(_validate(l0_3)[0])


if __name__ == "__main__":
    unittest.main()
