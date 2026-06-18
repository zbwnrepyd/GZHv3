import json
import os
import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'render')


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), 'r') as f:
        return json.load(f)


# Test 1: valid contract passes schema validation
def test_render_contract_schema_valid_contract():
    """Valid contract fixture must pass JSON Schema validation."""
    from jsonschema import Draft202012Validator
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'contracts', 'render_contract.schema.json')
    # Schema file doesn't exist yet - this test will FAIL (RED phase)
    if not os.path.exists(schema_path):
        pytest.fail("Schema file not found at contracts/render_contract.schema.json")
    with open(schema_path, 'r') as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema)
    contract = _load_fixture('valid_render_contract.json')
    errors = list(validator.iter_errors(contract))
    assert len(errors) == 0, f"Expected no validation errors, got: {errors}"


# Test 2: missing cards is rejected
def test_render_contract_schema_missing_cards():
    """Contract without 'cards' key must fail validation."""
    from jsonschema import Draft202012Validator
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'contracts', 'render_contract.schema.json')
    if not os.path.exists(schema_path):
        pytest.fail("Schema file not found")
    with open(schema_path, 'r') as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema)
    contract = _load_fixture('invalid_missing_cards.json')
    errors = list(validator.iter_errors(contract))
    assert len(errors) > 0, "Expected validation errors for missing cards"


# Test 3: invalid item status rejected
def test_render_contract_schema_invalid_item_status():
    """Item with status='unknown' must fail validation."""
    from jsonschema import Draft202012Validator
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'contracts', 'render_contract.schema.json')
    if not os.path.exists(schema_path):
        pytest.fail("Schema file not found")
    with open(schema_path, 'r') as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema)
    contract = _load_fixture('invalid_bad_item_status.json')
    errors = list(validator.iter_errors(contract))
    assert len(errors) > 0, "Expected validation errors for invalid item status"


# Test 4: invalid media status rejected
def test_render_contract_schema_invalid_media_status():
    """Media with status='broken' must fail validation."""
    from jsonschema import Draft202012Validator
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'contracts', 'render_contract.schema.json')
    if not os.path.exists(schema_path):
        pytest.fail("Schema file not found")
    with open(schema_path, 'r') as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema)
    contract = _load_fixture('invalid_bad_media_status.json')
    errors = list(validator.iter_errors(contract))
    assert len(errors) > 0, "Expected validation errors for invalid media status"
