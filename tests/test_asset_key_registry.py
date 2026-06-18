import json
import os

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'contracts')


def _load_asset_keys():
    path = os.path.join(CONTRACTS_DIR, 'asset_keys.json')
    if not os.path.exists(path):
        raise FileNotFoundError(f"Asset keys file not found at {path}")
    with open(path, 'r') as f:
        return json.load(f)


V3_REQUIRED_MEDIA_KEYS = [
    'logo',
    'website_screenshot',
    'product_main',
    'founder_photo',
    'customer_logos',
    'chart_competitive',
    'chart_ecosystem',
    'flywheel',
    'timeline',
]


def test_asset_registry_contains_all_v3_media_keys():
    """Every media key referenced by v3 cards must be registered in asset_keys.json."""
    registry = _load_asset_keys()
    for key in V3_REQUIRED_MEDIA_KEYS:
        assert key in registry, f"Missing asset key: {key}"


def test_asset_registry_customer_logos_exists():
    """customer_logos must be registered (was missing in legacy)."""
    registry = _load_asset_keys()
    assert 'customer_logos' in registry, "customer_logos not found in asset keys"
    assert registry['customer_logos']['type'] == 'composite_image', \
        f"Expected composite_image type, got: {registry['customer_logos'].get('type')}"
    assert registry['customer_logos'].get('fallback') == 'customer_name_list_text_card', \
        "customer_logos must have fallback to customer_name_list_text_card"
