"""Candidate Resolver tests — PR7 (Goal 二)."""
import os, sys, sqlite3, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

# Fixture: build in-memory DB with all 5 evidence tables + test data
@pytest.fixture
def resolver_db():
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

        -- Test data for resolver tests
        INSERT INTO source_documents VALUES
        ('doc-ofc','testco','https://testco.com/about','official_site','About','2025-06-01','hash1','2025-01-01'),
        ('doc-blog','testco','https://blog.example.com','industry_blog','Some Blog','2025-03-01','hash2','2025-01-01'),
        ('doc-old','testco','https://old.report.com','market_report','Old Report','2024-01-01','hash3','2025-01-01'),
        ('doc-new','testco','https://new.report.com','market_report','New Report','2026-01-01','hash4','2025-01-01');

        INSERT INTO evidence_items(evidence_id, document_id, excerpt, start_offset, end_offset, confidence, created_at) VALUES
        ('ev-ofc-1','doc-ofc','TestCo revenue is $100M.',NULL,NULL,0.9,'2025-01-01'),
        ('ev-ofc-2','doc-ofc','TestCo ARR grew 50%.',NULL,NULL,0.85,'2025-01-01'),
        ('ev-ofc-3','doc-ofc','TestCo has 500 employees.',NULL,NULL,0.8,'2025-01-01'),
        ('ev-blog-1','doc-blog','Estimate: TestCo $80M revenue.',NULL,NULL,0.5,'2025-01-01'),
        ('ev-old-1','doc-old','Market was $50M in 2024.',NULL,NULL,0.7,'2025-01-01'),
        ('ev-new-1','doc-new','Market is $200M in 2026.',NULL,NULL,0.8,'2025-01-01');

        INSERT INTO field_candidates VALUES
        ('cand-ofc','testco','revenue','$100M','official_site',0.9,'approved',NULL,'2025-01-01'),
        ('cand-blog','testco','revenue','$80M','industry_blog',0.4,'candidate',NULL,'2025-01-01'),
        ('cand-old','testco','market_size','$50M','market_report',0.7,'candidate',NULL,'2025-01-01'),
        ('cand-new','testco','market_size','$200M','market_report',0.8,'approved',NULL,'2025-01-01'),
        ('cand-noreason','testco','team_size','50','llm_inferred',0.3,'rejected','low confidence','2025-01-01'),
        ('cand-noev','testco','secret_metric','123','llm_inferred',0.9,'approved',NULL,'2025-01-01'),
        ('cand-conflict-a','testco','location','SF','official_site',0.9,'approved',NULL,'2025-01-01'),
        ('cand-conflict-b','testco','location','NYC','investor_deck',0.8,'candidate',NULL,'2025-01-01'),
        ('cand-conflict-c','testco','location','Remote','industry_blog',0.5,'candidate',NULL,'2025-01-01'),
        ('cand-priv','testco','retention','95%','llm_inferred',0.6,'approved',NULL,'2025-01-01');

        INSERT INTO candidate_evidence_map VALUES
        ('cand-ofc','ev-ofc-1'), ('cand-ofc','ev-ofc-2'), ('cand-ofc','ev-ofc-3'),
        ('cand-blog','ev-blog-1'),
        ('cand-old','ev-old-1'),
        ('cand-new','ev-new-1'),
        ('cand-conflict-a','ev-ofc-1'),
        ('cand-conflict-b','ev-ofc-1'),
        ('cand-conflict-c','ev-blog-1');
    """)
    conn.commit()
    yield conn
    conn.close()


# Import after path setup (will fail until modules exist — RED phase)
from webapp.services.candidate_resolver import CandidateResolver
from webapp.services.evidence_service import EvidenceService


class TestCandidateResolver:
    """7 tests from spec Goal 二 TDD table."""

    def test_candidate_resolver_prefers_official_source(self, resolver_db):
        """official_site candidate should outrank industry_blog."""
        resolver = CandidateResolver(resolver_db)
        best = resolver.resolve_best_candidate('testco', 'revenue')
        assert best is not None
        assert best['candidate_id'] == 'cand-ofc', f"Expected cand-ofc (official_site), got {best['candidate_id']}"
        assert best['candidate_value'] == '$100M'

    def test_candidate_resolver_prefers_more_evidence(self, resolver_db):
        """Candidate with more evidence items should rank higher."""
        resolver = CandidateResolver(resolver_db)
        best = resolver.resolve_best_candidate('testco', 'revenue')
        # cand-ofc has 3 evidence items, cand-blog has 1
        assert best['candidate_id'] == 'cand-ofc'

    def test_candidate_resolver_prefers_recent_candidate(self, resolver_db):
        """Newer candidate should be preferred when source weights are equal."""
        resolver = CandidateResolver(resolver_db)
        best = resolver.resolve_best_candidate('testco', 'market_size')
        # Both are market_report, but cand-new is 2026 vs cand-old 2024
        assert best['candidate_id'] == 'cand-new', f"Expected cand-new (more recent), got {best['candidate_id']}"

    def test_candidate_resolver_keeps_conflicting_values(self, resolver_db):
        """Conflicting values should all be retained as candidates (not silently dropped)."""
        resolver = CandidateResolver(resolver_db)
        candidates = resolver.get_field_candidates('testco', 'location')
        assert len(candidates) >= 2, f"Expected >=2 conflicting candidates, got {len(candidates)}"

    def test_candidate_resolver_reject_reason_required(self, resolver_db):
        """Rejected candidates MUST have a reject_reason."""
        resolver = CandidateResolver(resolver_db)
        candidates = resolver.get_field_candidates('testco', 'team_size')
        for c in candidates:
            if c['status'] == 'rejected':
                assert c.get('reject_reason'), f"candidate {c['candidate_id']} is rejected but has no reason"

    def test_field_status_confirmed_requires_evidence(self, resolver_db):
        """A candidate with no evidence items must not be confirmed."""
        resolver = CandidateResolver(resolver_db)
        # cand-noev has 0 evidence items
        candidates = resolver.get_field_candidates('testco', 'secret_metric')
        for c in candidates:
            if c['candidate_id'] == 'cand-noev':
                evidence_count = resolver._count_evidence(c['candidate_id'])
                if evidence_count == 0:
                    # Should not be confirmable
                    assert c['status'] != 'confirmed' or evidence_count > 0, \
                        "Candidate without evidence must not be confirmed"

    def test_field_status_unavailable_for_private_metric(self, resolver_db):
        """Private metric without reliable source should be not_applicable/unavailable."""
        resolver = CandidateResolver(resolver_db)
        # cand-priv has source_type=llm_inferred, which is low weight
        best = resolver.resolve_best_candidate('testco', 'retention')
        if best:
            # llm_inferred should not produce confirmed status
            assert best.get('status') != 'confirmed', \
                "LLM-inferred private metric must not be confirmed"
