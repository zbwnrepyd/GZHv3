"""No Raw Text In LLM — end-to-end guard (Goal 三)."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

import pytest
from webapp.services.context_packer import (
    ContextPacker, RawTextNotAllowedError, L0_STANDARD,
)
from webapp.services.document_chunker import chunk as chunk_document
from webapp.services.context_ranker import rank as rank_chunks
from webapp.services.budget_manager import is_governance_enabled


SAMPLE_TEXT = "\n\n".join(
    [f"Paragraph {i}: Anthropic is an AI safety company building reliable AI systems. "
     f"The company focuses on frontier model safety and has raised significant funding. "
     f"Claude is their main product used by enterprises worldwide." for i in range(50)]
)


class TestNoRawTextInLlm:
    def test_end_to_end_research_never_sends_raw_text(self):
        """Full governance pipeline: raw text → chunk → rank → pack → only packed text enters LLM.

        If governance is enabled, raw text must never reach the LLM prompt directly.
        """
        # Step 1: Start with raw text
        assert len(SAMPLE_TEXT) > 5000, "Need substantial text for meaningful test"

        # Step 2: Chunk it
        chunks = chunk_document(SAMPLE_TEXT, company_id='Anthropic', document_id='doc-1',
                                target_chunk_tokens=500)
        assert len(chunks) > 1, "Must produce multiple chunks"

        # Step 3: Rank chunks
        ranked = rank_chunks(chunks, company_id='Anthropic')
        assert len(ranked) > 0

        # Step 4: Pack into budget
        packer = ContextPacker(raw_text_enabled=False)
        result = packer.pack('Anthropic', 'L0', ranked, budget_tokens=L0_STANDARD)

        # Step 5: Verify the governance pipeline ran successfully
        # Packed text should be a concatenation of selected chunks (possibly all if they fit)
        assert len(result['packed_text']) > 0, "Packer must produce non-empty output"
        assert len(result['selected_chunks']) > 0, "Must select at least some chunks"
        assert 'budget_tokens' in result
        assert result['total_selected_tokens'] <= result['budget_tokens'], \
            "Selected tokens must not exceed budget"

        # Step 6: Verify raw text is rejected by packer
        with pytest.raises(RawTextNotAllowedError):
            packer.pack('Anthropic', 'L0', SAMPLE_TEXT)

    def test_governance_is_active_by_default(self):
        """Governance must be enabled by default — no silent bypass."""
        assert is_governance_enabled(), \
            "Context governance must be active. Chunking and packing are required."

    def test_chunk_rank_pack_chain_preserves_key_info(self):
        """The chunk→rank→pack chain must preserve key company information."""
        key_terms = ['Anthropic', 'AI safety', 'Claude', 'enterprise']

        chunks = chunk_document(SAMPLE_TEXT, company_id='Anthropic', document_id='doc-1',
                                target_chunk_tokens=500)
        ranked = rank_chunks(chunks, company_id='Anthropic')
        packer = ContextPacker(raw_text_enabled=False)
        result = packer.pack('Anthropic', 'L0', ranked)

        packed = result['packed_text'].lower()
        for term in key_terms:
            assert term.lower() in packed, \
                f"Key term '{term}' lost during chunk→rank→pack pipeline"
