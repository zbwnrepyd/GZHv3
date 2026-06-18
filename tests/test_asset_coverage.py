"""Asset Coverage tests — PR11 (Goal 四)."""

import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))


# Minimal asset registry mirroring contracts/asset_keys.json
SAMPLE_REGISTRY = {
    'logo': {'type': 'image', 'required': True},
    'website_screenshot': {'type': 'image', 'required': False},
    'product_main': {'type': 'image', 'required': False},
    'founder_photo': {'type': 'image', 'required': False},
    'customer_logos': {'type': 'composite_image', 'required': False, 'fallback': 'customer_name_list_text_card'},
    'chart_competitive': {'type': 'chart', 'required': False},
    'chart_ecosystem': {'type': 'chart', 'required': False},
    'flywheel': {'type': 'chart', 'required': False},
    'timeline': {'type': 'chart', 'required': False},
}

REQUIRED_ASSETS = {'logo'}


def _run_asset_check(contract: dict, registry: dict = None) -> list:
    if registry is None:
        registry = SAMPLE_REGISTRY
    failures = []
    for card in contract.get('cards', []):
        card_id = card.get('card_id', '?')
        for m in card.get('media', []):
            asset_key = m.get('asset_key', '?')
            if asset_key not in registry:
                failures.append({
                    'card_id': card_id, 'asset_key': asset_key,
                    'issue': 'unregistered_asset_key',
                })
                continue
            if asset_key in REQUIRED_ASSETS and m.get('status') != 'ready':
                failures.append({
                    'card_id': card_id, 'asset_key': asset_key,
                    'issue': 'required_asset_not_ready',
                })
    return failures


class TestAssetCoverage:
    def test_asset_coverage_detects_unregistered_asset_key(self):
        """An asset_key not in the registry must be flagged."""
        contract = {
            'version': '1.0',
            'company': {'company_id': 'test', 'name': 'Test', 'slug': 'test'},
            'card_set': 'v3',
            'cards': [{
                'card_id': 'c1', 'title': 'Test',
                'items': [],
                'media': [{
                    'asset_key': 'unregistered_image', 'url': None,
                    'status': 'ready', 'source': 'none',
                }],
                'layout': {'template_id': 't1', 'variant': 'wide'},
            }],
            'warnings': [],
        }
        failures = _run_asset_check(contract)
        assert len(failures) > 0
        assert any(f['issue'] == 'unregistered_asset_key' for f in failures)

    def test_asset_coverage_detects_required_logo_missing(self):
        """Required logo asset with non-ready status must be flagged."""
        contract = {
            'version': '1.0',
            'company': {'company_id': 'test', 'name': 'Test', 'slug': 'test'},
            'card_set': 'v3',
            'cards': [{
                'card_id': 'c1', 'title': 'Test',
                'items': [],
                'media': [{
                    'asset_key': 'logo', 'url': None,
                    'status': 'fallback', 'source': 'none',
                }],
                'layout': {'template_id': 't1', 'variant': 'wide'},
            }],
            'warnings': [],
        }
        failures = _run_asset_check(contract)
        assert len(failures) > 0
        assert any(f['issue'] == 'required_asset_not_ready' for f in failures)

    def test_asset_coverage_allows_optional_fallback_media(self):
        """Optional media with fallback status must pass check."""
        contract = {
            'version': '1.0',
            'company': {'company_id': 'test', 'name': 'Test', 'slug': 'test'},
            'card_set': 'v3',
            'cards': [{
                'card_id': 'c1', 'title': 'Test',
                'items': [],
                'media': [
                    {'asset_key': 'logo', 'url': '/img/logo.png', 'status': 'ready', 'source': 'selected_asset'},
                    {'asset_key': 'customer_logos', 'url': None, 'status': 'fallback', 'source': 'none'},
                ],
                'layout': {'template_id': 't1', 'variant': 'wide'},
            }],
            'warnings': [],
        }
        failures = _run_asset_check(contract)
        assert len(failures) == 0, f"Optional fallback should pass, got: {failures}"
