"""Integration tests for /api/render-data/<company> endpoint — PR5."""

import os
import sys
import pytest

# Match import style of other test modules to avoid dual module instantiation
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))


@pytest.fixture(scope='module')
def app():
    import app as _app_module
    _app_module.app.config['TESTING'] = True
    return _app_module.app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


class TestRenderApi:
    """PR5 integration tests for the render-data API."""

    def test_render_api_returns_valid_v3_contract(self, client):
        """GET /api/render-data/<company>?set=v3 returns a valid RenderContract."""
        resp = client.get('/api/render-data/Anthropic?set=v3')
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.data[:200]}"
        data = resp.get_json()
        assert data is not None, "Response must be valid JSON"
        for key in ('version', 'company', 'card_set', 'cards', 'warnings'):
            assert key in data, f"Missing required key: {key}"
        assert data['card_set'] == 'v3'
        assert len(data['cards']) == 8, f"v3 must have 8 cards, got {len(data['cards'])}"
        card = data['cards'][0]
        for key in ('card_id', 'title', 'items', 'media', 'layout'):
            assert key in card, f"Card missing key: {key}"

    def test_render_api_handles_missing_company_gracefully(self, client):
        """API must return 200 with cards (using defaults) for missing company, not 500."""
        resp = client.get('/api/render-data/NonExistentCompany12345?set=v3')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'cards' in data
        assert len(data['cards']) == 8, "Should return 8 default cards"
        assert data['card_set'] == 'v3'

    def test_render_api_defaults_to_v1_when_no_set(self, client):
        """API defaults to v1 (backward compatible) when ?set is missing."""
        resp = client.get('/api/render-data/Anthropic')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'cards' in data
        assert len(data['cards']) > 0

    def test_render_api_returns_v3_with_explicit_set(self, client):
        """API returns v3 RenderContract when ?set=v3."""
        resp = client.get('/api/render-data/Anthropic?set=v3')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['card_set'] == 'v3'
        assert len(data['cards']) == 8
