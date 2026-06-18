"""Candidate Lineage test — PR8 (Goal 二)."""
import os, sys, sqlite3
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))


@pytest.fixture
def lineage_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
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
        ('doc-1','testco','https://testco.com/about','official_site','About','2025-06-01','hash1','2025-01-01');
        INSERT INTO evidence_items VALUES
        ('ev-1','doc-1','TestCo has $100M ARR.',NULL,NULL,0.9,'2025-01-01'),
        ('ev-2','doc-1','TestCo founded in 2020.',NULL,NULL,0.85,'2025-01-01');
        INSERT INTO field_candidates VALUES
        ('cand-1','testco','arr','$100M','official_site',0.9,'approved',NULL,'2025-01-01');
        INSERT INTO candidate_evidence_map VALUES ('cand-1','ev-1'),('cand-1','ev-2');
        INSERT INTO final_field_values VALUES
        ('testco','arr','cand-1','confirmed','2025-01-01');
    """)
    conn.commit()
    yield conn
    conn.close()


from webapp.services.candidate_resolver import CandidateResolver
from webapp.services.evidence_service import EvidenceService


class TestCandidateLineage:
    def test_render_assembler_consumes_final_candidate_reference(self, lineage_db):
        """Goal 二 must not break Goal 一: final_field_values.selected_candidate_id →
        field_candidates → candidate_evidence_map → evidence_items → source_documents.
        Verifies the full lineage chain is resolvable.
        """
        # Step 1: Get final_field_values entry
        cur = lineage_db.execute(
            "SELECT * FROM final_field_values WHERE company_id='testco' AND field_key='arr'"
        )
        ff = dict(cur.fetchone())
        assert ff['field_status'] == 'confirmed'
        selected_id = ff['selected_candidate_id']
        assert selected_id == 'cand-1'

        # Step 2: Resolve candidate
        resolver = CandidateResolver(lineage_db)
        best = resolver.resolve_best_candidate('testco', 'arr')
        assert best is not None
        assert best['candidate_id'] == selected_id

        # Step 3: Get full lineage
        svc = EvidenceService(lineage_db)
        lineage = svc.get_candidate_lineage(selected_id)
        assert lineage is not None
        assert len(lineage['evidence']) == 2
        assert lineage['candidate']['candidate_value'] == '$100M'
        assert lineage['final_field']['field_status'] == 'confirmed'

        # Step 4: Verify evidence→document chain
        for ev in lineage['evidence']:
            assert ev['excerpt'] is not None
            assert ev['source_url'] is not None
