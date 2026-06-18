"""Candidate Resolver — scores and ranks field_candidates (Goal 二)."""

import sqlite3

SOURCE_WEIGHTS = {
    'official_site': 40,
    'official_blog': 38,
    'pricing_page': 36,
    'founder_interview': 35,
    'investor_deck': 32,
    'press_release': 30,
    'crunchbase': 25,
    'linkedin': 22,
    'financial_database': 28,
    'market_report': 26,
    'mainstream_media': 20,
    'industry_blog': 15,
    'github': 14,
    'youtube': 12,
    'community': 8,
    'forum': 6,
    'search': 4,
    'llm_inferred': 2,
    'database': 10,
    'manual': 1,
}

PRIVATE_METRIC_FIELDS = {
    'ltv', 'cac', 'ltv_cac_ratio', 'retention_rate', 'churn_rate',
    'arr', 'mrr', 'gross_margin', 'burn_rate', 'runway_months',
    'paying_users', 'active_users', 'registered_users', 'mau',
    'retention', 'company_revenue', 'company_profit',
}


class CandidateResolver:
    def __init__(self, db_conn):
        self.conn = db_conn
        self.conn.row_factory = sqlite3.Row

    def get_field_candidates(self, company_id, field_key):
        cur = self.conn.execute(
            "SELECT * FROM field_candidates WHERE company_id=? AND field_key=? ORDER BY created_at DESC",
            (company_id, field_key)
        )
        return [dict(row) for row in cur.fetchall()]

    def _count_evidence(self, candidate_id):
        cur = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM candidate_evidence_map WHERE candidate_id=?",
            (candidate_id,)
        )
        row = cur.fetchone()
        return row['cnt'] if row else 0

    def _get_evidence_ids(self, candidate_id):
        cur = self.conn.execute(
            "SELECT evidence_id FROM candidate_evidence_map WHERE candidate_id=?",
            (candidate_id,)
        )
        return [row['evidence_id'] for row in cur.fetchall()]

    def _get_document_date(self, candidate_id):
        cur = self.conn.execute("""
            SELECT MAX(sd.published_at) as latest_date
            FROM candidate_evidence_map cem
            JOIN evidence_items ei ON cem.evidence_id = ei.evidence_id
            JOIN source_documents sd ON ei.document_id = sd.document_id
            WHERE cem.candidate_id=?
        """, (candidate_id,))
        row = cur.fetchone()
        return row['latest_date'] if row else None

    def _score_candidate(self, candidate_row):
        source_type = candidate_row['source_type'] or 'search'
        source_weight = SOURCE_WEIGHTS.get(source_type, 1)
        evidence_count = self._count_evidence(candidate_row['candidate_id'])
        evidence_weight = min(evidence_count * 10, 40)
        date_str = self._get_document_date(candidate_row['candidate_id'])
        recency_weight = 0
        if date_str:
            try:
                year = int(date_str[:4])
                recency_weight = max(0, (year - 2020) * 5)
            except (ValueError, TypeError):
                pass
        confidence_weight = (candidate_row['confidence'] or 0.0) * 20
        total = source_weight + evidence_weight + recency_weight + confidence_weight
        return total

    def resolve_best_candidate(self, company_id, field_key):
        candidates = self.get_field_candidates(company_id, field_key)
        if not candidates:
            return None
        best = None
        best_score = -1
        for c in candidates:
            score = self._score_candidate(c)
            if score > best_score:
                best_score = score
                best = dict(c)
                best['score'] = score
        if best:
            evidence_count = self._count_evidence(best['candidate_id'])
            if best.get('status') == 'approved' and evidence_count == 0:
                best['status'] = 'candidate'
            if best.get('source_type') == 'llm_inferred':
                field_lower = field_key.lower()
                for pm in PRIVATE_METRIC_FIELDS:
                    if pm in field_lower:
                        best['status'] = 'candidate'
                        break
        return best
