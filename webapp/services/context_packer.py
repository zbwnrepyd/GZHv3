"""Context Packer — packs ranked chunks into budget-constrained LLM context (Goal 三)."""

import json

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

_STAGE_BUDGETS = {
    'L0': L0_STANDARD,
    'L0_deep': L0_DEEP,
    'L1': L1_BUDGET,
    'L2': L2_BUDGET,
    'L3': L3_BUDGET,
}


class RawTextNotAllowedError(Exception):
    """Raised when raw text is passed but RAW_TEXT_IN_LLM_ENABLED is False."""
    pass


class ContextPacker:
    """Packs ranked chunks into a budget-constrained context for LLM input."""

    def __init__(self, raw_text_enabled: bool = False):
        self.raw_text_enabled = raw_text_enabled

    def pack(self, company_id: str, stage: str, chunks: list[dict],
             budget_tokens: int = None) -> dict:
        """Pack chunks into budget-constrained context.

        Args:
            company_id: Company identifier
            stage: Pipeline stage (L0, L1, L2, L3)
            chunks: List of chunk dicts with at least: chunk_id, chunk_text,
                    token_count, and optionally score
            budget_tokens: Token budget. Defaults to stage-specific budget.

        Returns:
            PackResult dict with: stage, budget_tokens, selected_chunks,
            dropped_chunks, packed_text
        """
        if budget_tokens is None:
            budget_tokens = _STAGE_BUDGETS.get(stage, L0_STANDARD)

        # Detect if raw (unchunked) text is being passed
        if self._is_raw_text(chunks):
            if not self.raw_text_enabled:
                raise RawTextNotAllowedError(
                    "Raw text detected but RAW_TEXT_IN_LLM_ENABLED is False. "
                    "All input must go through chunk → rank → pack."
                )
            # If raw text is allowed, wrap it as a single chunk
            chunks = [{
                'chunk_id': 'raw',
                'chunk_text': chunks if isinstance(chunks, str) else str(chunks),
                'token_count': budget_tokens + 1,
                'score': 1.0,
            }]

        # Sort by score descending
        sorted_chunks = sorted(chunks, key=lambda c: c.get('score', 0), reverse=True)

        selected = []
        dropped = []
        total_tokens = 0

        for ch in sorted_chunks:
            tokens = ch.get('token_count', _estimate_tokens(ch.get('chunk_text', '')))
            if total_tokens + tokens <= budget_tokens:
                selected.append(ch)
                total_tokens += tokens
            else:
                dropped.append({
                    'chunk_id': ch.get('chunk_id', '?'),
                    'reason': 'budget_exceeded',
                    'token_count': tokens,
                })

        packed_text = '\n\n'.join(
            ch.get('chunk_text', '') for ch in selected
        )

        return {
            'stage': stage,
            'budget_tokens': budget_tokens,
            'selected_chunks': selected,
            'dropped_chunks': dropped,
            'packed_text': packed_text,
            'total_selected_tokens': total_tokens,
        }

    def _is_raw_text(self, chunks) -> bool:
        """Detect if input is raw text rather than structured chunks."""
        if isinstance(chunks, str):
            return True
        if isinstance(chunks, list) and len(chunks) == 1:
            ch = chunks[0]
            if isinstance(ch, dict) and ch.get('chunk_id') == 'raw':
                return True
        return False


def _estimate_tokens(text: str) -> int:
    """Rough token count estimation."""
    if not text:
        return 0
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
    en = len(text) - cjk
    return int(en / 4 + cjk / 1.5)
