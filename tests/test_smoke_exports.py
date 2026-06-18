"""Smoke Export tests — PR12 (Goal 四).

Uses local fixture data only. No external network calls.
"""

import os, sys, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import pytest


class TestSmokeExports:
    def test_smoke_anthropic_v3_export(self):
        """Smoke test: RenderAssembler produces a valid contract for Anthropic v3."""
        from webapp.services.render_assembler import RenderAssembler
        assembler = RenderAssembler()
        contract = assembler.assemble('Anthropic', 'v3')

        # Must have exactly 8 cards
        assert len(contract['cards']) == 8

        # Every card must have required structure
        for card in contract['cards']:
            assert card['card_id'].startswith('v3_card_')
            assert len(card['title']) > 0
            assert isinstance(card['items'], list)
            assert isinstance(card['media'], list)
            assert 'template_id' in card['layout']
            assert 'variant' in card['layout']

        # First card (封面) must have company_name field and logo media
        cover = contract['cards'][0]
        assert cover['card_id'] == 'v3_card_01'
        has_name = any(i['field_key'] == 'company_name' for i in cover['items'])
        has_logo = any(m['asset_key'] == 'logo' for m in cover['media'])
        assert has_name, "Cover card must have company_name field"
        assert has_logo, "Cover card must have logo media"

    def test_smoke_export_contract_is_schema_valid(self):
        """Smoke test: Generated contract passes JSON Schema validation."""
        from webapp.services.render_assembler import RenderAssembler
        from webapp.services.contract_validator import ContractValidator
        assembler = RenderAssembler()
        contract = assembler.assemble('Anthropic', 'v3')
        # Must not raise
        result = ContractValidator.validate(contract)
        assert result is True

    def test_smoke_export_coverage_check_passes(self):
        """Smoke test: coverage check script's core logic passes on valid data."""
        from webapp.services.render_assembler import RenderAssembler
        assembler = RenderAssembler()
        contract = assembler.assemble('Anthropic', 'v3')

        # Run coverage logic inline
        failures = []
        for card in contract['cards']:
            card_id = card['card_id']
            if len(card['items']) == 0:
                failures.append({'card_id': card_id, 'issue': 'no_items'})
            for item in card['items']:
                valid_statuses = {'confirmed', 'derived', 'proxy', 'llm_extracted',
                                  'manual_needed', 'unavailable', 'not_applicable'}
                if item.get('status') not in valid_statuses:
                    failures.append({'card_id': card_id, 'field_key': item['field_key'],
                                     'issue': 'invalid_status'})
            layout = card.get('layout', {})
            if not layout.get('template_id') or not layout.get('variant'):
                failures.append({'card_id': card_id, 'issue': 'incomplete_layout'})

        assert len(failures) == 0, f"Smoke test failures: {failures}"
