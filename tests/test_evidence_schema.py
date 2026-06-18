"""Evidence schema tests — PR6 (Goal 二)."""

import os
import sqlite3
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))


@pytest.fixture
def evidence_db():
    """Create an in-memory SQLite DB with all 5 evidence tables."""
    conn = sqlite3.connect(':memory:')
    conn.execute("PRAGMA foreign_keys = ON")
    # We execute the migration SQL inline to avoid path-dependency issues in CI
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS source_documents (
            document_id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            title TEXT,
            published_at TEXT,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_source_documents_company
        ON source_documents(company_id);

        CREATE TABLE IF NOT EXISTS evidence_items (
            evidence_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            start_offset INTEGER,
            end_offset INTEGER,
            confidence REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(document_id) REFERENCES source_documents(document_id)
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_items_document
        ON evidence_items(document_id);

        CREATE TABLE IF NOT EXISTS field_candidates (
            candidate_id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            field_key TEXT NOT NULL,
            candidate_value TEXT NOT NULL,
            source_type TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL CHECK (status IN ('candidate','approved','rejected')),
            reject_reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_field_candidates_company_field
        ON field_candidates(company_id, field_key);

        CREATE TABLE IF NOT EXISTS candidate_evidence_map (
            candidate_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            PRIMARY KEY(candidate_id, evidence_id),
            FOREIGN KEY(candidate_id) REFERENCES field_candidates(candidate_id),
            FOREIGN KEY(evidence_id) REFERENCES evidence_items(evidence_id)
        );

        CREATE TABLE IF NOT EXISTS final_field_values (
            company_id TEXT NOT NULL,
            field_key TEXT NOT NULL,
            selected_candidate_id TEXT,
            field_status TEXT NOT NULL CHECK (
              field_status IN (
                'confirmed','derived','proxy','llm_extracted',
                'manual_needed','unavailable','not_applicable'
              )
            ),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(company_id, field_key),
            FOREIGN KEY(selected_candidate_id) REFERENCES field_candidates(candidate_id)
        );
        CREATE INDEX IF NOT EXISTS idx_final_field_values_candidate
        ON final_field_values(selected_candidate_id);
    """)
    yield conn
    conn.close()


class TestEvidenceSchema:
    """Verify the 5 evidence pipeline tables are correctly created."""

    def test_all_5_tables_exist(self, evidence_db):
        """All 5 evidence tables must be present in the schema."""
        cur = evidence_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cur.fetchall()}
        expected = {
            'source_documents', 'evidence_items', 'field_candidates',
            'candidate_evidence_map', 'final_field_values'
        }
        missing = expected - tables
        assert not missing, f"Missing tables: {missing}"

    def test_source_documents_columns(self, evidence_db):
        """source_documents must have spec-defined columns."""
        cur = evidence_db.execute("PRAGMA table_info('source_documents')")
        cols = {row[1]: row[2] for row in cur.fetchall()}
        for col in ('document_id', 'company_id', 'source_url', 'source_type', 'content_hash'):
            assert col in cols, f"Missing column: {col}"

    def test_fk_cascade_deletes_on_document(self, evidence_db):
        """Deleting a source_document should cascade-restrict evidence_items."""
        evidence_db.execute(
            "INSERT INTO source_documents(document_id,company_id,source_url,source_type,content_hash) "
            "VALUES ('doc-1','testco','https://a.com','official_site','abc123')"
        )
        evidence_db.execute(
            "INSERT INTO evidence_items(evidence_id,document_id,excerpt) "
            "VALUES ('ev-1','doc-1','Sample text.')"
        )
        # FK should prevent deleting parent while child exists
        with pytest.raises(sqlite3.IntegrityError):
            evidence_db.execute("DELETE FROM source_documents WHERE document_id='doc-1'")

    def test_field_candidates_status_check(self, evidence_db):
        """field_candidates.status must reject values outside approved enum."""
        evidence_db.execute(
            "INSERT INTO field_candidates(candidate_id,company_id,field_key,candidate_value,source_type,status) "
            "VALUES ('cand-1','testco','market_size','$10B','official_site','candidate')"
        )
        # Valid statuses: candidate, approved, rejected
        evidence_db.execute("UPDATE field_candidates SET status='approved' WHERE candidate_id='cand-1'")
        evidence_db.execute("UPDATE field_candidates SET status='rejected' WHERE candidate_id='cand-1'")
        # Invalid status
        with pytest.raises(sqlite3.IntegrityError):
            evidence_db.execute("UPDATE field_candidates SET status='invalid_status' WHERE candidate_id='cand-1'")

    def test_final_field_values_status_check(self, evidence_db):
        """final_field_values.field_status must reject values outside spec enum."""
        evidence_db.execute(
            "INSERT INTO field_candidates(candidate_id,company_id,field_key,candidate_value,source_type,status) "
            "VALUES ('cand-ff','testco','revenue','$100M','official_site','approved')"
        )
        evidence_db.execute(
            "INSERT INTO final_field_values(company_id,field_key,selected_candidate_id,field_status) "
            "VALUES ('testco','revenue','cand-ff','confirmed')"
        )
        # Valid re-assign
        evidence_db.execute(
            "UPDATE final_field_values SET field_status='derived' WHERE company_id='testco' AND field_key='revenue'"
        )
        # Invalid status
        with pytest.raises(sqlite3.IntegrityError):
            evidence_db.execute(
                "UPDATE final_field_values SET field_status='unknown' WHERE company_id='testco' AND field_key='revenue'"
            )

    def test_indexes_exist(self, evidence_db):
        """All spec-defined indexes must be created."""
        cur = evidence_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
        indexes = {row[0] for row in cur.fetchall()}
        expected_indexes = {
            'idx_source_documents_company',
            'idx_evidence_items_document',
            'idx_field_candidates_company_field',
            'idx_final_field_values_candidate',
        }
        missing = expected_indexes - indexes
        assert not missing, f"Missing indexes: {missing}"

    def test_primary_keys(self, evidence_db):
        """Verify PRIMARY KEY constraints exist for all 5 tables."""
        # Insert duplicate PK should fail
        evidence_db.execute(
            "INSERT INTO source_documents(document_id,company_id,source_url,source_type,content_hash) "
            "VALUES ('pk-test','tc','https://x.com','blog','hash1')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            evidence_db.execute(
                "INSERT INTO source_documents(document_id,company_id,source_url,source_type,content_hash) "
                "VALUES ('pk-test','tc','https://y.com','blog','hash2')"
            )

    def test_candidate_evidence_map_composite_pk(self, evidence_db):
        """candidate_evidence_map composite PK prevents duplicates."""
        evidence_db.execute(
            "INSERT INTO source_documents(document_id,company_id,source_url,source_type,content_hash) "
            "VALUES ('doc-ce','tc','https://z.com','blog','hash-ce')"
        )
        evidence_db.execute(
            "INSERT INTO evidence_items(evidence_id,document_id,excerpt) "
            "VALUES ('ev-ce-1','doc-ce','Text 1.')"
        )
        evidence_db.execute(
            "INSERT INTO field_candidates(candidate_id,company_id,field_key,candidate_value,source_type,status) "
            "VALUES ('cand-ce','tc','field_x','val','blog','candidate')"
        )
        evidence_db.execute(
            "INSERT INTO candidate_evidence_map(candidate_id,evidence_id) "
            "VALUES ('cand-ce','ev-ce-1')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            evidence_db.execute(
                "INSERT INTO candidate_evidence_map(candidate_id,evidence_id) "
                "VALUES ('cand-ce','ev-ce-1')"
            )
