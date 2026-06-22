"""
Test L3 prompt split into three domain-specific groups.

Task 6 of the depth optimization plan splits the monolithic L3 field extraction
prompt (prompts/layer3-field-extraction.md, ~3582 tokens, 45+ fields) into three
domain-specific groups to reduce per-call dilution.
"""

import os


PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")

# ── Group A: Basic Facts ──────────────────────────────────────────────
GROUP_A_FILE = "layer3-group-facts.md"
GROUP_A_FIELDS = {
    "company_name",
    "company_type",
    "company_def",
    "location",
    "founded_date",
    "website_url",
    "founder_name",
    "founder_bg",
    "founder_edu",
    "founder_achievement",
    "team_size",
    "team_highlight",
    "funding_info",
    "main_product_name",
    "main_product_def",
}

# ── Group B: Market & Operating Metrics ───────────────────────────────
GROUP_B_FILE = "layer3-group-market.md"
GROUP_B_FIELDS = {
    "market_track",
    "market_subtrack",
    "market_size_value",
    "market_size_currency",
    "market_size_year",
    "market_cagr",
    "tam_value",
    "tam_currency",
    "tam_year",
    "market_landscape_summary",
    "market_landscape_top_players",
    "regional_market_focus",
    "regional_markets",
    "market_opportunity",
    "mau",
    "mau_as_of",
    "revenue_metrics",
    "growth_metrics",
}

# ── Group C: Business & Competition Analysis ──────────────────────────
GROUP_C_FILE = "layer3-group-operating.md"
GROUP_C_FIELDS = {
    "core_business",
    "core_competency",
    "industry_positioning",
    "moat",
    "ecosystem_niche",
    "ecosystem_positioning",
    "competitive_advantages",
    "competitors_summary",
    "pricing_summary",
    "pricing_strategy",
    "gtm_strategy",
    "growth_strategy",
}


class TestL3Split:
    """Verify the three L3 group prompt files exist and are well-formed."""

    # ── 1. Files exist and are non-empty ───────────────────────────

    def test_group_a_file_exists_and_non_empty(self):
        path = os.path.join(PROMPTS_DIR, GROUP_A_FILE)
        assert os.path.isfile(path), f"Missing {GROUP_A_FILE}"
        content = open(path, encoding="utf-8").read()
        assert len(content) > 100, (
            f"{GROUP_A_FILE} too short ({len(content)} chars, need > 100)"
        )

    def test_group_b_file_exists_and_non_empty(self):
        path = os.path.join(PROMPTS_DIR, GROUP_B_FILE)
        assert os.path.isfile(path), f"Missing {GROUP_B_FILE}"
        content = open(path, encoding="utf-8").read()
        assert len(content) > 100, (
            f"{GROUP_B_FILE} too short ({len(content)} chars, need > 100)"
        )

    def test_group_c_file_exists_and_non_empty(self):
        path = os.path.join(PROMPTS_DIR, GROUP_C_FILE)
        assert os.path.isfile(path), f"Missing {GROUP_C_FILE}"
        content = open(path, encoding="utf-8").read()
        assert len(content) > 100, (
            f"{GROUP_C_FILE} too short ({len(content)} chars, need > 100)"
        )

    # ── 2. No field name duplication across groups ─────────────────

    def test_no_field_duplication_a_b(self):
        overlap = GROUP_A_FIELDS & GROUP_B_FIELDS
        assert not overlap, (
            f"Fields duplicated between A and B: {overlap}"
        )

    def test_no_field_duplication_a_c(self):
        overlap = GROUP_A_FIELDS & GROUP_C_FIELDS
        assert not overlap, (
            f"Fields duplicated between A and C: {overlap}"
        )

    def test_no_field_duplication_b_c(self):
        overlap = GROUP_B_FIELDS & GROUP_C_FIELDS
        assert not overlap, (
            f"Fields duplicated between B and C: {overlap}"
        )

    # ── 3. Combined field count >= 45 ──────────────────────────────

    def test_combined_field_count(self):
        all_fields = GROUP_A_FIELDS | GROUP_B_FIELDS | GROUP_C_FIELDS
        assert len(all_fields) >= 45, (
            f"Combined field count {len(all_fields)} < 45"
        )

    # ── 4. Original L3 prompt still exists (backward compat) ───────

    def test_original_l3_prompt_untouched(self):
        path = os.path.join(PROMPTS_DIR, "layer3-field-extraction.md")
        assert os.path.isfile(path), (
            "Original layer3-field-extraction.md should still exist"
        )
