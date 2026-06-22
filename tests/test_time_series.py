"""TimeSeriesSnapshotter tests — snapshot, diff, list_comparable_fields."""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))


MIGRATION_SQL = Path(__file__).resolve().parent.parent / "db" / "migrations" / "049_company_snapshots.sql"


@pytest.fixture
def tmp_db():
    """Create a temp SQLite database with the company_snapshots table."""
    fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    conn = sqlite3.connect(tmp_path)
    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
    conn.close()
    yield tmp_path
    # Cleanup
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)


def make_snapshotter(db_path):
    from webapp.research.time_series import TimeSeriesSnapshotter
    return TimeSeriesSnapshotter(db_path=db_path)


class TestSnapshot:
    def test_snapshot_writes_correct_row_count(self, tmp_db):
        """snapshot writes correct number of rows."""
        t = make_snapshotter(tmp_db)
        fields = {
            "revenue": {"value": "$100M", "value_type": "money", "resolution_status": "confirmed"},
            "employees": {"value": "500", "value_type": "number", "resolution_status": "proxy"},
            "founded_year": {"value": "2020", "value_type": "number", "resolution_status": "confirmed"},
        }
        count = t.snapshot("testco", fields, snapshot_type="fields_only", research_run_id="run-001")
        assert count == 3

    def test_snapshot_handles_missing_table(self):
        """snapshot with missing table returns 0 (no crash)."""
        fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            t = make_snapshotter(tmp_path)
            fields = {"revenue": {"value": "$100M"}}
            count = t.snapshot("testco", fields)
            assert count == 0
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_snapshot_dict_value_serialized_as_json(self, tmp_db):
        """snapshot converts dict values to JSON strings."""
        t = make_snapshotter(tmp_db)
        fields = {
            "address": {"value": {"city": "SF", "state": "CA"}},
        }
        count = t.snapshot("testco", fields)
        assert count == 1
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT field_value FROM company_snapshots WHERE company_key='testco'").fetchone()
        conn.close()
        assert '"city"' in row[0]

    def test_snapshot_list_value_serialized_as_json(self, tmp_db):
        """snapshot converts list values to JSON strings."""
        t = make_snapshotter(tmp_db)
        fields = {
            "competitors": {"value": ["A", "B", "C"]},
        }
        count = t.snapshot("testco", fields)
        assert count == 1
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT field_value FROM company_snapshots WHERE company_key='testco'").fetchone()
        conn.close()
        assert '"A"' in row[0] or "A" in row[0]


class TestDiff:
    def test_diff_returns_dict_with_two_snapshots(self, tmp_db):
        """diff returns expected diff dict when 2 snapshots exist for a field."""
        t = make_snapshotter(tmp_db)
        # Write first snapshot
        t.snapshot("testco", {"revenue": {"value": "$50M"}}, research_run_id="run-001")
        # Write second snapshot
        t.snapshot("testco", {"revenue": {"value": "$100M"}}, research_run_id="run-002")
        result = t.diff("testco", "revenue")
        assert result is not None
        assert result["field_key"] == "revenue"
        assert result["previous"]["value"] == "$50M"
        assert result["current"]["value"] == "$100M"
        assert "snapshot_at" in result["previous"]
        assert "snapshot_at" in result["current"]

    def test_diff_returns_none_with_only_one_snapshot(self, tmp_db):
        """diff returns None when only 1 snapshot exists (need 2+)."""
        t = make_snapshotter(tmp_db)
        t.snapshot("testco", {"revenue": {"value": "$50M"}}, research_run_id="run-001")
        result = t.diff("testco", "revenue")
        assert result is None

    def test_diff_returns_none_for_unknown_field(self, tmp_db):
        """diff returns None for unknown field."""
        t = make_snapshotter(tmp_db)
        result = t.diff("testco", "nonexistent_field")
        assert result is None

    def test_diff_detects_up_direction(self, tmp_db):
        """diff correctly detects 'up' direction when value increases."""
        t = make_snapshotter(tmp_db)
        t.snapshot("testco", {"employees": {"value": "500"}}, research_run_id="run-001")
        t.snapshot("testco", {"employees": {"value": "1000"}}, research_run_id="run-002")
        result = t.diff("testco", "employees")
        assert result is not None
        assert result["direction"] == "up"

    def test_diff_detects_down_direction(self, tmp_db):
        """diff correctly detects 'down' direction when value decreases."""
        t = make_snapshotter(tmp_db)
        t.snapshot("testco", {"revenue": {"value": "$100M"}}, research_run_id="run-001")
        t.snapshot("testco", {"revenue": {"value": "$50M"}}, research_run_id="run-002")
        result = t.diff("testco", "revenue")
        assert result is not None
        assert result["direction"] == "down"

    def test_diff_detects_same_direction(self, tmp_db):
        """diff detects 'same' direction when value unchanged."""
        t = make_snapshotter(tmp_db)
        t.snapshot("testco", {"revenue": {"value": "100"}}, research_run_id="run-001")
        t.snapshot("testco", {"revenue": {"value": "100"}}, research_run_id="run-002")
        result = t.diff("testco", "revenue")
        assert result is not None
        assert result["direction"] == "same"

    def test_diff_handles_non_numeric_values(self, tmp_db):
        """diff falls back to 'same' when values can't be parsed as numbers."""
        t = make_snapshotter(tmp_db)
        t.snapshot("testco", {"status": {"value": "private"}}, research_run_id="run-001")
        t.snapshot("testco", {"status": {"value": "public"}}, research_run_id="run-002")
        result = t.diff("testco", "status")
        assert result is not None
        assert result["direction"] == "same"

    def test_diff_with_money_suffixes(self, tmp_db):
        """diff parses $, M, B, K suffixes correctly."""
        t = make_snapshotter(tmp_db)
        t.snapshot("testco", {"funding": {"value": "$5B"}}, research_run_id="run-001")
        t.snapshot("testco", {"funding": {"value": "$10B"}}, research_run_id="run-002")
        result = t.diff("testco", "funding")
        assert result is not None
        assert result["direction"] == "up"
        assert result["previous"]["value"] == "$5B"
        assert result["current"]["value"] == "$10B"

    def test_diff_missing_table_returns_none(self):
        """diff returns None when table doesn't exist."""
        fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            t = make_snapshotter(tmp_path)
            result = t.diff("testco", "revenue")
            assert result is None
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestListComparableFields:
    def test_returns_fields_with_two_plus_snapshots(self, tmp_db):
        """list_comparable_fields returns fields with 2+ snapshots."""
        t = make_snapshotter(tmp_db)
        t.snapshot("testco", {"revenue": {"value": "$100M"}, "employees": {"value": "500"}}, research_run_id="run-001")
        t.snapshot("testco", {"revenue": {"value": "$150M"}}, research_run_id="run-002")
        # revenue has 2, employees has 1
        fields = t.list_comparable_fields("testco")
        assert "revenue" in fields
        assert "employees" not in fields

    def test_returns_empty_for_new_company(self, tmp_db):
        """list_comparable_fields returns empty list for company with no snapshots."""
        t = make_snapshotter(tmp_db)
        fields = t.list_comparable_fields("unknown_co")
        assert fields == []

    def test_ignores_null_values(self, tmp_db):
        """list_comparable_fields ignores rows with NULL field_value."""
        t = make_snapshotter(tmp_db)
        # Write one with value, one with empty string (stored as NULL via falsy check)
        t.snapshot("testco", {"name": {"value": "TestCo"}}, research_run_id="run-001")
        t.snapshot("testco", {"name": {"value": ""}}, research_run_id="run-002")
        # Only 1 non-null snapshot — not enough for comparison
        fields = t.list_comparable_fields("testco")
        assert "name" not in fields

    def test_missing_table_returns_empty_list(self):
        """list_comparable_fields returns empty list when table doesn't exist."""
        fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            t = make_snapshotter(tmp_path)
            fields = t.list_comparable_fields("testco")
            assert fields == []
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_multiple_snapshots_all_counted(self, tmp_db):
        """list_comparable_fields counts all snapshots correctly."""
        t = make_snapshotter(tmp_db)
        for i in range(5):
            t.snapshot("testco", {"revenue": {"value": f"${100 + i * 10}M"}}, research_run_id=f"run-{i:03d}")
        fields = t.list_comparable_fields("testco")
        assert "revenue" in fields
