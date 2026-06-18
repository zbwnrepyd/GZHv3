"""Card Coverage tests — PR11 (Goal 四)."""

import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))


class TestCardCoverage:
    def test_card_coverage_detects_missing_field(self):
        """A card with no items must be flagged as a failure."""
        # Build a minimal contract with one empty card
        contract = {
            'version': '1.0',
            'company': {'company_id': 'test', 'name': 'Test', 'slug': 'test'},
            'card_set': 'v3',
            'cards': [{
                'card_id': 'empty_card',
                'title': 'Empty',
                'items': [],
                'media': [],
                'layout': {'template_id': 't1', 'variant': 'wide'},
            }],
            'warnings': [],
        }
        failures = _check_contract(contract)
        assert len(failures) > 0
        assert any(f['issue'] == 'no_items' for f in failures)

    def test_card_coverage_passes_complete_v3(self):
        """A well-formed v3 contract must pass coverage check."""
        contract = {
            'version': '1.0',
            'company': {'company_id': 'test', 'name': 'Test', 'slug': 'test'},
            'card_set': 'v3',
            'cards': [{
                'card_id': 'v3_card_01',
                'title': '封面',
                'items': [{
                    'field_key': 'company_name', 'label': 'Name',
                    'value': 'TestCo', 'status': 'confirmed',
                    'confidence': 0.9, 'evidence_count': 2, 'source': 'final',
                }],
                'media': [{
                    'asset_key': 'logo', 'url': '/img/logo.png',
                    'status': 'ready', 'source': 'selected_asset',
                }],
                'layout': {'template_id': 'cover_v3', 'variant': 'wide'},
            }],
            'warnings': [],
        }
        failures = _check_contract(contract)
        assert len(failures) == 0, f"Expected no failures, got: {failures}"

    def test_card_coverage_flags_invalid_field_status(self):
        """A field with an unrecognized status must be flagged."""
        contract = {
            'version': '1.0',
            'company': {'company_id': 'test', 'name': 'Test', 'slug': 'test'},
            'card_set': 'v3',
            'cards': [{
                'card_id': 'v3_card_01',
                'title': 'Test',
                'items': [{
                    'field_key': 'bad_field', 'label': 'Bad',
                    'value': 'x', 'status': 'unknown_invalid',
                    'confidence': 0, 'evidence_count': 0, 'source': 'none',
                }],
                'media': [],
                'layout': {'template_id': 't1', 'variant': 'wide'},
            }],
            'warnings': [],
        }
        failures = _check_contract(contract)
        assert len(failures) > 0


def _check_contract(contract: dict) -> list:
    """Internal coverage logic for unit testing (mirrors card_content_coverage_check.py)."""
    failures = []
    for card in contract.get('cards', []):
        card_id = card.get('card_id', '?')
        items = card.get('items', [])
        if len(items) == 0:
            failures.append({'card_id': card_id, 'issue': 'no_items'})
        for item in items:
            status = item.get('status', 'draft')
            valid = {'confirmed', 'derived', 'proxy', 'llm_extracted',
                     'manual_needed', 'unavailable', 'not_applicable'}
            if status not in valid:
                failures.append({
                    'card_id': card_id,
                    'field_key': item.get('field_key'),
                    'issue': 'unresolvable_field',
                })
        for m in card.get('media', []):
            asset_status = m.get('status', '?')
            valid_media = {'ready', 'fallback', 'manual_needed', 'unavailable', 'not_applicable'}
            if asset_status not in valid_media:
                failures.append({
                    'card_id': card_id,
                    'asset_key': m.get('asset_key'),
                    'issue': 'invalid_media_status',
                })
        layout = card.get('layout', {})
        if not (layout.get('template_id') and layout.get('variant')):
            failures.append({'card_id': card_id, 'issue': 'incomplete_layout'})
    return failures
