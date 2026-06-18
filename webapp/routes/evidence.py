"""Evidence API routes (Goal 二)."""
from __future__ import annotations
import sqlite3
from flask import Blueprint, jsonify, current_app
from services.evidence_service import EvidenceService
from services.candidate_resolver import CandidateResolver


evidence_lineage_bp = Blueprint('evidence_lineage', __name__)


def _get_db_conn():
    """Get research_db connection from app config."""
    db_path = current_app.config.get('DB_PATH_RESEARCH')
    if not db_path:
        from config import config
        db_path = config.DB_PATH_RESEARCH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@evidence_lineage_bp.route('/api/evidence/company/<company>')
def evidence_company(company: str):
    """Return all evidence for a company."""
    try:
        conn = _get_db_conn()
        svc = EvidenceService(conn)
        resolver = CandidateResolver(conn)
        # Collect fields with candidates
        cur = conn.execute(
            "SELECT DISTINCT field_key FROM field_candidates WHERE company_id=?",
            (company,)
        )
        fields_data = {}
        for row in cur.fetchall():
            fk = row['field_key']
            best = resolver.resolve_best_candidate(company, fk)
            candidates = resolver.get_field_candidates(company, fk)
            evidence = svc.get_field_evidence(company, fk)
            fields_data[fk] = {
                'best_candidate': best,
                'candidates': candidates,
                'evidence': evidence,
            }
        conn.close()
        return jsonify({'company': company, 'fields': fields_data})
    except Exception as e:
        return jsonify({'company': company, 'fields': {}, 'error': str(e)}), 200


@evidence_lineage_bp.route('/api/evidence/field/<company>/<field_key>')
def evidence_field(company: str, field_key: str):
    """Return candidates, best candidate, and evidence for a field."""
    try:
        conn = _get_db_conn()
        svc = EvidenceService(conn)
        resolver = CandidateResolver(conn)
        best = resolver.resolve_best_candidate(company, field_key)
        candidates = resolver.get_field_candidates(company, field_key)
        evidence = svc.get_field_evidence(company, field_key)
        conn.close()
        return jsonify({
            'company': company,
            'field_key': field_key,
            'final_candidate': best,
            'alternatives': [c for c in candidates if c['candidate_id'] != (best or {}).get('candidate_id')],
            'evidence': evidence,
        })
    except Exception as e:
        return jsonify({
            'company': company, 'field_key': field_key,
            'final_candidate': None, 'alternatives': [], 'evidence': [],
            'error': str(e),
        }), 200


@evidence_lineage_bp.route('/api/evidence/candidate/<candidate_id>')
def evidence_candidate(candidate_id: str):
    """Return full lineage for a candidate."""
    try:
        conn = _get_db_conn()
        svc = EvidenceService(conn)
        lineage = svc.get_candidate_lineage(candidate_id)
        conn.close()
        if lineage is None:
            return jsonify({'candidate_id': candidate_id, 'error': 'Not found'}), 404
        return jsonify(lineage)
    except Exception as e:
        return jsonify({'candidate_id': candidate_id, 'error': str(e)}), 404
