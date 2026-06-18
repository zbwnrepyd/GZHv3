"""Context Logs tests — PR10 (Goal 三)."""

import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from webapp.services.context_packer import ContextPacker, L0_STANDARD, L0_DEEP


def _make_chunks(n: int, tokens_each: int = 500, base_score: float = 0.9):
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


class TestContextLogs:
    def test_context_log_contains_stage_and_model(self):
        """Pack result must include stage for audit trail."""
        packer = ContextPacker()
        chunks = _make_chunks(5, tokens_each=200)
        result = packer.pack('testco', 'L1', chunks, budget_tokens=L0_DEEP)
        assert result['stage'] == 'L1'
        # budget_tokens must be recorded for audit
        assert 'budget_tokens' in result
        assert result['budget_tokens'] > 0

    def test_packer_logs_selected_and_dropped_chunks(self):
        """Pack result must log both selected and dropped chunk IDs."""
        packer = ContextPacker()
        # 40 chunks * 500 tokens = 20000 total, L0 budget = 18000 → some must drop
        chunks = _make_chunks(40, tokens_each=500)
        result = packer.pack('testco', 'L0', chunks)
        assert len(result['selected_chunks']) > 0
        assert len(result['dropped_chunks']) > 0
        # Verify selected/dropped are logged with chunk_ids
        for sel in result['selected_chunks']:
            assert 'chunk_id' in sel
        for drop in result['dropped_chunks']:
            assert 'chunk_id' in drop
            assert 'reason' in drop

    def test_packer_logs_can_be_serialized(self):
        """Pack result must be JSON-serializable for storage in packed_context_logs."""
        packer = ContextPacker()
        chunks = _make_chunks(10, tokens_each=200)
        result = packer.pack('testco', 'L0', chunks)
        # Strip non-serializable chunk dicts for log storage
        log_entry = {
            'stage': result['stage'],
            'budget_tokens': result['budget_tokens'],
            'selected_chunks_json': json.dumps(
                [{'chunk_id': c['chunk_id'], 'score': c.get('score', 0),
                  'token_count': c['token_count']} for c in result['selected_chunks']]
            ),
            'dropped_chunks_json': json.dumps(result['dropped_chunks']),
        }
        assert json.loads(log_entry['selected_chunks_json']) is not None
        # dropped_chunks may be empty (valid JSON '[]')
        dropped = json.loads(log_entry['dropped_chunks_json'])
        assert isinstance(dropped, list)
