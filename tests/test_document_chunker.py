"""Document Chunker tests — PR9 (Goal 三)."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from webapp.services.document_chunker import chunk, _estimate_tokens
from webapp.research.context.document_chunker import _infer_chunk_type

LONG_TEXT = "\n\n".join(
    [f"This is paragraph number {i} with some content that describes various "
     f"aspects of the business model, market strategy, and competitive landscape. "
     f"We need enough text to ensure multiple chunks are created." for i in range(100)]
)


class TestDocumentChunker:
    def test_chunker_splits_large_document(self):
        """Long text must be split into multiple chunks."""
        chunks = chunk(LONG_TEXT, company_id='testco', document_id='doc-1',
                       target_chunk_tokens=500)
        assert len(chunks) > 1, f"Expected multiple chunks, got {len(chunks)}"

    def test_chunker_preserves_order(self):
        """chunk_order must be sequential and match paragraph order."""
        chunks = chunk(LONG_TEXT, company_id='testco', document_id='doc-1',
                       target_chunk_tokens=500)
        orders = [c['chunk_order'] for c in chunks]
        assert orders == list(range(len(chunks))), \
            f"chunk_order must be 0..n-1, got {orders}"

    def test_chunker_empty_text(self):
        """Empty text must return empty list."""
        chunks = chunk('', company_id='testco', document_id='doc-1')
        assert chunks == []

    def test_chunker_each_chunk_has_required_fields(self):
        """Each chunk must have all required keys."""
        chunks = chunk(LONG_TEXT, company_id='testco', document_id='doc-1',
                       target_chunk_tokens=500)
        for c in chunks:
            for key in ('chunk_id', 'document_id', 'company_id', 'chunk_text',
                         'token_count', 'chunk_order'):
                assert key in c, f"Missing key '{key}' in chunk {c.get('chunk_id')}"

    def test_chunker_token_estimate_positive(self):
        """Token estimate must be > 0 for non-empty text."""
        assert _estimate_tokens("Hello world") > 0
        assert _estimate_tokens("") == 0

    def test_product_feature_keywords_match(self):
        """Product feature keywords should map to chunk_type='product_feature'."""
        text = (
            "Our platform features include AI agent orchestration, "
            "MCP gateway integration, and one-click deployment. "
            "Core capabilities: multi-agent collaboration, "
            "Chrome extension for browser automation."
        )
        ctype = _infer_chunk_type(text)
        assert ctype == "product_feature", (
            f"Expected 'product_feature' chunk_type, got '{ctype}'"
        )

    def test_unknown_no_longer_noise(self):
        """unknown chunk_type should not be in _NOISE_CHUNK_TYPES."""
        from webapp.research.context.document_chunker import _NOISE_CHUNK_TYPES
        assert "unknown" not in _NOISE_CHUNK_TYPES, (
            "unknown should not be auto-marked as noise"
        )
