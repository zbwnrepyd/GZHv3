"""Tests for webapp/research/competitive_matrix.py — L1 structured competitor extraction."""

import unittest


class TestCompetitorItem(unittest.TestCase):
    """CompetitorItem Pydantic validation tests."""

    def setUp(self):
        from webapp.research.competitive_matrix import CompetitorItem
        self.CompetitorItem = CompetitorItem

    def test_valid_competitor_item_passes(self):
        """Valid CompetitorItem should pass validation."""
        item = self.CompetitorItem(
            name="OpenAI",
            url="https://openai.com",
            overlap_areas=["LLM APIs", "AI assistants"],
            strengths=["Brand recognition", "GPT models"],
            weaknesses=["Closed source", "Enterprise focus"],
            threat_level="high",
            evidence_snippets=["OpenAI dominates the enterprise LLM API market"]
        )
        self.assertEqual(item.name, "OpenAI")
        self.assertEqual(item.threat_level, "high")

    def test_invalid_threat_level_rejected(self):
        """Invalid threat_level should raise ValidationError."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.CompetitorItem(
                name="OpenAI",
                url="https://openai.com",
                overlap_areas=["LLM APIs"],
                strengths=["Brand"],
                weaknesses=["Closed"],
                threat_level="extreme",  # invalid
                evidence_snippets=["OpenAI is a major player"]
            )

    def test_empty_evidence_snippets_rejected(self):
        """Empty evidence_snippets should raise ValidationError."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.CompetitorItem(
                name="OpenAI",
                url="https://openai.com",
                overlap_areas=["LLM APIs"],
                strengths=["Brand"],
                weaknesses=["Closed"],
                threat_level="high",
                evidence_snippets=[]  # empty
            )

    def test_evidence_snippet_too_long_rejected(self):
        """evidence_snippet > 100 chars should raise ValidationError."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.CompetitorItem(
                name="OpenAI",
                url="https://openai.com",
                overlap_areas=["LLM APIs"],
                strengths=["Brand"],
                weaknesses=["Closed"],
                threat_level="high",
                evidence_snippets=["x" * 101]  # too long
            )


class TestCompetitiveMatrix(unittest.TestCase):
    """CompetitiveMatrix Pydantic validation tests."""

    def setUp(self):
        from webapp.research.competitive_matrix import CompetitorItem, CompetitiveMatrix
        self.CompetitorItem = CompetitorItem
        self.CompetitiveMatrix = CompetitiveMatrix

    def _make_competitor(self, name, threat_level="medium"):
        return self.CompetitorItem(
            name=name,
            url=f"https://{name.lower()}.com",
            overlap_areas=["AI"],
            strengths=["Innovation"],
            weaknesses=["Scale"],
            threat_level=threat_level,
            evidence_snippets=[f"{name} is growing fast"]
        )

    def test_valid_matrix_with_two_competitors_passes(self):
        """Valid CompetitiveMatrix with 2 competitors should pass."""
        matrix = self.CompetitiveMatrix(
            competitors=[
                self._make_competitor("OpenAI", "high"),
                self._make_competitor("Google", "medium"),
            ],
            target_company_position="strong_contender",
            competitive_landscape_summary="Anthropic competes on safety and research."
        )
        self.assertEqual(len(matrix.competitors), 2)

    def test_only_one_competitor_rejected(self):
        """Only 1 competitor should raise ValidationError (need >= 2)."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.CompetitiveMatrix(
                competitors=[
                    self._make_competitor("OpenAI"),
                ],
                target_company_position="strong_contender",
                competitive_landscape_summary="Limited competition."
            )

    def test_invalid_target_position_rejected(self):
        """Invalid target_company_position should raise ValidationError."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.CompetitiveMatrix(
                competitors=[
                    self._make_competitor("OpenAI"),
                    self._make_competitor("Google"),
                ],
                target_company_position="dominator",  # invalid
                competitive_landscape_summary="Anthropic competes on safety."
            )


class TestCompetitiveMatrixExtractor(unittest.TestCase):
    """CompetitiveMatrixExtractor validate / to_field_value tests."""

    def setUp(self):
        from webapp.research.competitive_matrix import CompetitiveMatrixExtractor
        self.extractor = CompetitiveMatrixExtractor()

    def test_validate_valid_data_returns_matrix_and_empty_errors(self):
        """validate() with valid data returns (matrix, [])."""
        valid_data = {
            "competitors": [
                {
                    "name": "OpenAI",
                    "url": "https://openai.com",
                    "overlap_areas": ["LLM APIs"],
                    "strengths": ["GPT models"],
                    "weaknesses": ["Closed source"],
                    "threat_level": "high",
                    "evidence_snippets": ["OpenAI dominates enterprise LLM market"]
                },
                {
                    "name": "Google",
                    "url": "https://deepmind.google.com",
                    "overlap_areas": ["AI research"],
                    "strengths": ["Compute resources"],
                    "weaknesses": ["Slow to ship"],
                    "threat_level": "medium",
                    "evidence_snippets": ["Google has massive compute advantage"]
                },
            ],
            "target_company_position": "strong_contender",
            "competitive_landscape_summary": "Anthropic leads on AI safety."
        }
        matrix, errors = self.extractor.validate(valid_data)
        self.assertIsNotNone(matrix)
        self.assertEqual(errors, [])
        self.assertEqual(len(matrix.competitors), 2)

    def test_validate_missing_key_returns_none_and_errors(self):
        """validate() with missing key returns (None, errors)."""
        invalid_data = {
            "competitors": [
                {
                    "name": "OpenAI",
                    # missing required fields
                    "threat_level": "high",
                }
            ],
            "target_company_position": "strong_contender",
        }
        matrix, errors = self.extractor.validate(invalid_data)
        self.assertIsNone(matrix)
        self.assertTrue(len(errors) > 0)

    def test_to_field_value_returns_json_string(self):
        """to_field_value should return a JSON string."""
        from webapp.research.competitive_matrix import CompetitiveMatrix
        valid_data = {
            "competitors": [
                {
                    "name": "OpenAI",
                    "url": "https://openai.com",
                    "overlap_areas": ["LLM APIs"],
                    "strengths": ["GPT"],
                    "weaknesses": ["Closed"],
                    "threat_level": "high",
                    "evidence_snippets": ["Dominates enterprise"]
                },
                {
                    "name": "Google",
                    "url": None,
                    "overlap_areas": ["AI"],
                    "strengths": ["Compute"],
                    "weaknesses": ["Slow"],
                    "threat_level": "medium",
                    "evidence_snippets": ["Massive compute advantage"]
                }
            ],
            "target_company_position": "strong_contender",
            "competitive_landscape_summary": "Summary here."
        }
        matrix, errors = self.extractor.validate(valid_data)
        self.assertIsNotNone(matrix)
        self.assertEqual(errors, [])
        result = self.extractor.to_field_value(matrix)
        self.assertIsInstance(result, str)
        import json
        parsed = json.loads(result)
        self.assertEqual(len(parsed["competitors"]), 2)


if __name__ == "__main__":
    unittest.main()
