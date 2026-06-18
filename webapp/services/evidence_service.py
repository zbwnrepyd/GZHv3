"""Evidence Service — field evidence and candidate lineage (Goal 二)."""

import sqlite3


class EvidenceService:
    def __init__(self, db_conn):
        self.conn = db_conn
        self.conn.row_factory = sqlite3.Row

    def get_field_evidence(self, company_id, field_key):
        cur = self.conn.execute("""
            SELECT ei.*, sd.source_url, sd.source_type, sd.title, sd.published_at
            FROM field_candidates fc
            JOIN candidate_evidence_map cem ON fc.candidate_id = cem.candidate_id
            JOIN evidence_items ei ON cem.evidence_id = ei.evidence_id
            JOIN source_documents sd ON ei.document_id = sd.document_id
            WHERE fc.company_id=? AND fc.field_key=?
            ORDER BY ei.created_at DESC
        """, (company_id, field_key))
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_candidate_lineage(self, candidate_id):
        cur = self.conn.execute(
            "SELECT * FROM field_candidates WHERE candidate_id=?",
            (candidate_id,)
        )
        cand_row = cur.fetchone()
        if not cand_row:
            return None
        candidate = dict(cand_row)
        evidence = []
        ev_cur = self.conn.execute("""
            SELECT ei.*, sd.source_url, sd.source_type, sd.title as document_title,
                   sd.published_at as document_published_at, sd.document_id
            FROM candidate_evidence_map cem
            JOIN evidence_items ei ON cem.evidence_id = ei.evidence_id
            JOIN source_documents sd ON ei.document_id = sd.document_id
            WHERE cem.candidate_id=?
        """, (candidate_id,))
        for row in ev_cur.fetchall():
            ev = dict(row)
            evidence.append(ev)
        field_cur = self.conn.execute(
            "SELECT * FROM final_field_values WHERE selected_candidate_id=?",
            (candidate_id,)
        )
        final_field = None
        ff_row = field_cur.fetchone()
        if ff_row:
            final_field = dict(ff_row)
        return {
            'candidate': candidate,
            'evidence': evidence,
            'final_field': final_field,
        }
