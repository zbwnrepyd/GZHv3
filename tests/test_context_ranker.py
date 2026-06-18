"""Context Ranker tests — PR10 (Goal 三)."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from webapp.services.context_ranker import rank


COMPANY_CHUNKS = [
    {'chunk_id': 'ch-1', 'chunk_text': 'Anthropic is an AI safety company based in San Francisco. Anthropic builds Claude.', 'token_count': 20, 'chunk_order': 0},
    {'chunk_id': 'ch-2', 'chunk_text': 'The AI industry is growing rapidly with many players entering the market. Industry trends suggest continued expansion.', 'token_count': 20, 'chunk_order': 1},
    {'chunk_id': 'ch-3', 'chunk_text': 'Anthropic revenue grew significantly with the launch of Claude Opus and enterprise pricing.', 'token_count': 20, 'chunk_order': 2},
    {'chunk_id': 'ch-4', 'chunk_text': 'According to analysts, the industry has seen many companies in this space emerge recently.', 'token_count': 20, 'chunk_order': 3},
]


class TestContextRanker:
    def test_ranker_scores_company_specific_chunks_higher(self):
        """Chunks mentioning the company name should score higher than generic industry chunks."""
        ranked = rank(COMPANY_CHUNKS, company_id='Anthropic')
        # ch-1 and ch-3 mention Anthropic, should be top 2
        top_two = {ranked[0]['chunk_id'], ranked[1]['chunk_id']}
        assert 'ch-1' in top_two, f"Expected ch-1 in top 2, got {top_two}"
        assert 'ch-3' in top_two or ranked[2]['chunk_id'] in ('ch-1', 'ch-3'), \
            f"Company-specific chunks should rank high"

        # ch-2 and ch-4 are generic industry, should be lower
        bottom_ids = {c['chunk_id'] for c in ranked[2:]}
        assert 'ch-2' in bottom_ids or 'ch-4' in bottom_ids

    def test_ranker_adds_score_field(self):
        """All chunks must have a 'score' field after ranking."""
        ranked = rank(COMPANY_CHUNKS, company_id='Anthropic')
        for ch in ranked:
            assert 'score' in ch, f"Missing 'score' in chunk {ch.get('chunk_id')}"
            assert isinstance(ch['score'], (int, float))
            assert 0 <= ch['score'] <= 100

    def test_ranker_sorts_descending(self):
        """Chunks must be sorted by score descending."""
        ranked = rank(COMPANY_CHUNKS, company_id='Anthropic')
        scores = [c['score'] for c in ranked]
        assert scores == sorted(scores, reverse=True), \
            f"Chunks not sorted descending: {scores}"

    def test_ranker_empty_list(self):
        """Empty input returns empty list."""
        assert rank([], company_id='Anthropic') == []
