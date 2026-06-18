"""Evidence pipeline migrations (Goal 二).

Run spec-defined evidence schema migrations against research_db.
Tables: source_documents, evidence_items, field_candidates,
        candidate_evidence_map, final_field_values.
"""

import os
import sqlite3
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "db" / "migrations"

_EVIDENCE_MIGRATIONS = [
    "040_evidence_source_documents.sql",
    "041_evidence_items_v2.sql",
    "042_field_candidates_v2.sql",
    "043_candidate_evidence_map.sql",
    "044_final_field_values.sql",
]


def run_evidence_migrations(db_path: str) -> list[str]:
    """Run all evidence pipeline migrations against the given SQLite database.

    Returns list of applied migration filenames.
    """
    applied = []
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        for filename in _EVIDENCE_MIGRATIONS:
            filepath = _MIGRATIONS_DIR / filename
            if not filepath.exists():
                continue
            sql = filepath.read_text()
            conn.executescript(sql)
            applied.append(filename)
        conn.commit()
    finally:
        conn.close()

    return applied


def run_evidence_migrations_on_connection(conn: sqlite3.Connection) -> list[str]:
    """Run evidence migrations on an existing connection (e.g., :memory:)."""
    conn.execute("PRAGMA foreign_keys = ON")
    applied = []
    for filename in _EVIDENCE_MIGRATIONS:
        filepath = _MIGRATIONS_DIR / filename
        if not filepath.exists():
            continue
        sql = filepath.read_text()
        conn.executescript(sql)
        applied.append(filename)
    return applied
