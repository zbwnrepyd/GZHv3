"""Context Packer tests — PR9 (Goal 三)."""

import os, sys, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from webapp.services.context_packer import (
    ContextPacker, RawTextNotAllowedError,
    L0_STANDARD, L0_DEEP, L1_BUDGET,
)


def _make_chunks(n: int, tokens_each: int = 500, base_score: float = 0.9):
    """Create n test chunks with descending scores."""
    chunks = []
    for i in range(n):
        chunks.append({
            'chunk_id': f'ch-{i:03d}',
            'document_id': 'doc-1',
            'company_id': 'testco',
            'chunk_text': f'Chunk {i} content. ' * (tokens_each // 3),
            'token_count': tokens_each,
            'chunk_order': i,
            'score': base_score - (i * 0.05),
        })
    return chunks


class TestContextPacker:
    def test_packer_respects_budget_l0_standard(self):
        """Packer must not exceed L0_STANDARD budget (18000 tokens)."""
        packer = ContextPacker()
        chunks = _make_chunks(50, tokens_each=500)
        result = packer.pack('testco', 'L0', chunks)
        total = sum(c['token_count'] for c in result['selected_chunks'])
        assert total <= L0_STANDARD, \
            f"Selected tokens {total} exceeds budget {L0_STANDARD}"
        assert len(result['selected_chunks']) <= 36

    def test_packer_respects_budget_l0_deep(self):
        """Packer must not exceed L0_DEEP budget (28000 tokens)."""
        packer = ContextPacker()
        chunks = _make_chunks(70, tokens_each=500)
        result = packer.pack('testco', 'L0_deep', chunks, budget_tokens=L0_DEEP)
        total = sum(c['token_count'] for c in result['selected_chunks'])
        assert total <= L0_DEEP, \
            f"Selected tokens {total} exceeds budget {L0_DEEP}"

    def test_packer_rejects_raw_text_when_disabled(self):
        """Raw text must raise RawTextNotAllowedError when flag is off."""
        packer = ContextPacker(raw_text_enabled=False)
        with pytest.raises(RawTextNotAllowedError):
            packer.pack('testco', 'L0', "This is raw text that should be rejected")

    def test_packer_prefers_high_rank_chunks(self):
        """Higher-scored chunks must be selected before lower-scored ones."""
        packer = ContextPacker()
        chunks = _make_chunks(10, tokens_each=1800)
        chunks[5]['score'] = 999.0
        result = packer.pack('testco', 'L0', chunks, budget_tokens=L0_STANDARD)
        selected_ids = [c['chunk_id'] for c in result['selected_chunks']]
        assert selected_ids[0] == 'ch-005', \
            f"Highest scored chunk should be first, got {selected_ids[0]}"

    def test_packer_logs_selected_and_dropped_chunks(self):
        """Result must contain both selected_chunks and dropped_chunks."""
        packer = ContextPacker()
        chunks = _make_chunks(40, tokens_each=500)
        result = packer.pack('testco', 'L0', chunks)
        assert len(result['selected_chunks']) > 0
        assert len(result['dropped_chunks']) > 0
        for d in result['dropped_chunks']:
            assert 'reason' in d
            assert d['reason'] == 'budget_exceeded'

    def test_packer_includes_packed_text(self):
        """Result must contain packed_text field."""
        packer = ContextPacker()
        chunks = _make_chunks(5, tokens_each=200)
        result = packer.pack('testco', 'L1', chunks, budget_tokens=L1_BUDGET)
        assert 'packed_text' in result
        assert len(result['packed_text']) > 0

    def test_packer_all_fit_no_dropped(self):
        """When all chunks fit in budget, dropped must be empty."""
        packer = ContextPacker()
        chunks = _make_chunks(5, tokens_each=200)
        result = packer.pack('testco', 'L0', chunks)
        assert len(result['selected_chunks']) == 5
        assert len(result['dropped_chunks']) == 0
