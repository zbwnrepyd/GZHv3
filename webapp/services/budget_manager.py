"""Budget Manager — token budget lookup and validation (Goal 三)."""

# Budget constants (from spec)
L0_STANDARD = 18000
L0_DEEP = 28000
L1_BUDGET = 18000
L2_BUDGET = 18000
L3_BUDGET = 18000

# Feature flags
RAW_TEXT_IN_LLM_ENABLED = False
DOCUMENT_CHUNKING_ENABLED = True
CONTEXT_PACKER_ENABLED = True
LEGACY_CONTEXT_MODE = False  # Must be explicitly set to True to bypass governance

_STAGE_BUDGETS = {
    'L0': L0_STANDARD,
    'L0_deep': L0_DEEP,
    'L1': L1_BUDGET,
    'L2': L2_BUDGET,
    'L3': L3_BUDGET,
}


def get_budget(stage: str) -> int:
    """Return token budget for a pipeline stage.

    Args:
        stage: One of 'L0', 'L0_deep', 'L1', 'L2', 'L3'

    Returns:
        Token budget as int. Defaults to L0_STANDARD for unknown stages.
    """
    return _STAGE_BUDGETS.get(stage, L0_STANDARD)


def validate_within_budget(packed_result: dict) -> bool:
    """Check whether a packer result is within its declared budget.

    Args:
        packed_result: Dict from ContextPacker.pack() with keys:
                       budget_tokens, total_selected_tokens

    Returns:
        True if total_selected_tokens <= budget_tokens.
    """
    budget = packed_result.get('budget_tokens', 0)
    used = packed_result.get('total_selected_tokens', 0)
    return used <= budget


def is_governance_enabled() -> bool:
    """Return True if context governance should be applied."""
    return CONTEXT_PACKER_ENABLED and DOCUMENT_CHUNKING_ENABLED


def is_legacy_mode() -> bool:
    """Return True only if LEGACY_CONTEXT_MODE is explicitly enabled."""
    return LEGACY_CONTEXT_MODE
