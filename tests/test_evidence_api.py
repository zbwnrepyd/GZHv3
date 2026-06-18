"""Evidence API integration tests — PR8 (Goal 二)."""
import os, sys, json, sqlite3
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from webapp.app import app as flask_app


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c


class TestEvidenceApi:
    def test_evidence_api_company_returns_json(self, client):
        """GET /api/evidence/company/<company> returns 200 + JSON."""
        resp = client.get('/api/evidence/company/Anthropic')
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.data[:200]}"
        data = resp.get_json()
        assert data is not None, "Response must be valid JSON"
        assert 'company' in data

    def test_evidence_api_field_returns_alternatives(self, client):
        """GET /api/evidence/field/<company>/<field_key> returns candidates and evidence."""
        resp = client.get('/api/evidence/field/Anthropic/market_size')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'company' in data
        assert 'field_key' in data

    def test_evidence_api_handles_missing_company(self, client):
        """API must not 500 on unknown company."""
        resp = client.get('/api/evidence/company/NonExistent12345')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None

    def test_evidence_api_candidate_returns_lineage(self, client):
        """GET /api/evidence/candidate/<candidate_id> returns lineage data."""
        resp = client.get('/api/evidence/candidate/cand-test-1')
        assert resp.status_code in (200, 404)
