"""Evidence Service tests — PR7 (Goal 二)."""
import os, sys, sqlite3, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

@pytest.fixture
def evidence_db():
    conn = sqlite3.connect(':memory:')
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS source_documents (
            document_id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
            source_url TEXT NOT NULL, source_type TEXT NOT NULL,
            title TEXT, published_at TEXT, content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS evidence_items (
            evidence_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
            excerpt TEXT NOT NULL, start_offset INTEGER, end_offset INTEGER,
            confidence REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(document_id) REFERENCES source_documents(document_id)
        );
        CREATE TABLE IF NOT EXISTS field_candidates (
            candidate_id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
            field_key TEXT NOT NULL, candidate_value TEXT NOT NULL,
            source_type TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL CHECK (status IN ('candidate','approved','rejected')),
            reject_reason TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS candidate_evidence_map (
            candidate_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
            PRIMARY KEY(candidate_id, evidence_id),
            FOREIGN KEY(candidate_id) REFERENCES field_candidates(candidate_id),
            FOREIGN KEY(evidence_id) REFERENCES evidence_items(evidence_id)
        );
        CREATE TABLE IF NOT EXISTS final_field_values (
            company_id TEXT NOT NULL, field_key TEXT NOT NULL,
            selected_candidate_id TEXT,
            field_status TEXT NOT NULL CHECK (
              field_status IN ('confirmed','derived','proxy','llm_extracted',
              'manual_needed','unavailable','not_applicable')
            ),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(company_id, field_key),
            FOREIGN KEY(selected_candidate_id) REFERENCES field_candidates(candidate_id)
        );
        INSERT INTO source_documents VALUES
        ('doc-1','testco','https://testco.com','official_site','About TestCo','2025-06-01','hash1','2025-01-01');
        INSERT INTO evidence_items(evidence_id, document_id, excerpt, start_offset, end_offset, confidence, created_at) VALUES
        ('ev-1','doc-1','TestCo founded in 2020.',NULL,NULL,0.9,'2025-01-01'),
        ('ev-2','doc-1','TestCo has $100M ARR.',NULL,NULL,0.85,'2025-01-01');
        INSERT INTO field_candidates VALUES
        ('cand-1','testco','founded_year','2020','official_site',0.9,'approved',NULL,'2025-01-01');
        INSERT INTO candidate_evidence_map VALUES ('cand-1','ev-1'),('cand-1','ev-2');
        INSERT INTO final_field_values VALUES
        ('testco','founded_year','cand-1','confirmed','2025-01-01');
    """)
    conn.commit()
    yield conn
    conn.close()

from webapp.services.evidence_service import EvidenceService


class TestEvidenceService:
    def test_evidence_service_returns_lineage(self, evidence_db):
        """get_candidate_lineage returns field → candidate → evidence → document chain."""
        svc = EvidenceService(evidence_db)
        lineage = svc.get_candidate_lineage('cand-1')
        assert lineage is not None, "Lineage should not be None for existing candidate"
        assert 'candidate' in lineage
        assert lineage['candidate']['candidate_id'] == 'cand-1'
        assert 'evidence' in lineage
        assert len(lineage['evidence']) == 2
        # Each evidence item should reference a document
        for ev in lineage['evidence']:
            assert 'document' in ev or 'source_url' in ev or 'document_id' in ev

    def test_evidence_service_handles_missing_candidate(self, evidence_db):
        """get_candidate_lineage must not crash for non-existent candidate."""
        svc = EvidenceService(evidence_db)
        result = svc.get_candidate_lineage('nonexistent')
        assert result is None or result == {} or ('error' not in str(result).lower())
