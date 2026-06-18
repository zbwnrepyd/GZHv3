"""Pipeline Context Integration tests — PR10 (Goal 三)."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

import pytest
from webapp.services.budget_manager import (
    LEGACY_CONTEXT_MODE, DOCUMENT_CHUNKING_ENABLED, CONTEXT_PACKER_ENABLED,
    is_governance_enabled, is_legacy_mode, get_budget,
    L0_STANDARD, L0_DEEP, L1_BUDGET, L2_BUDGET, L3_BUDGET,
)


class TestPipelineContextIntegration:
    def test_pipeline_uses_context_packer_when_enabled(self):
        """When CONTEXT_PACKER_ENABLED and DOCUMENT_CHUNKING_ENABLED are True,
        governance must be active."""
        # These are module-level constants — verify they're set correctly
        assert DOCUMENT_CHUNKING_ENABLED is True
        assert CONTEXT_PACKER_ENABLED is True
        assert is_governance_enabled() is True

    def test_pipeline_bypasses_packer_only_in_explicit_legacy_mode(self):
        """Governance must NOT be bypassed by default.
        Only LEGACY_CONTEXT_MODE=True should bypass.
        """
        # Default: legacy mode is OFF
        assert is_legacy_mode() is False

        # Governance should be enabled by default
        assert is_governance_enabled() is True

    def test_budget_constants_match_spec(self):
        """Budget values must match Goal 三 spec."""
        assert L0_STANDARD == 18000
        assert L0_DEEP == 28000
        assert L1_BUDGET == 18000
        assert L2_BUDGET == 18000
        assert L3_BUDGET == 18000

    def test_get_budget_returns_correct_stage_values(self):
        """get_budget() must return correct values for each stage."""
        assert get_budget('L0') == 18000
        assert get_budget('L0_deep') == 28000
        assert get_budget('L1') == 18000
        assert get_budget('L2') == 18000
        assert get_budget('L3') == 18000
        assert get_budget('unknown') == L0_STANDARD  # fallback
