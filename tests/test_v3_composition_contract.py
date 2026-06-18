import json
import os

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'contracts')


def _load_v3():
    path = os.path.join(CONTRACTS_DIR, 'card_sets', 'v3.json')
    if not os.path.exists(path):
        raise FileNotFoundError(f"v3 card set not found at {path}")
    with open(path, 'r') as f:
        return json.load(f)


def test_v3_composition_has_exactly_8_cards():
    """v3 card set must contain exactly 8 cards."""
    v3 = _load_v3()
    assert 'cards' in v3, "v3.json must have 'cards' key"
    assert len(v3['cards']) == 8, f"Expected 8 cards, got {len(v3['cards'])}"


def test_v3_composition_card_ids_unique():
    """All v3 card_ids must be unique."""
    v3 = _load_v3()
    card_ids = [c['card_id'] for c in v3['cards']]
    assert len(card_ids) == len(set(card_ids)), f"Duplicate card_ids found: {card_ids}"
