-- 034_entity_audit_columns.sql
-- Description: Add audit-trace columns (evidence_span_ids, resolution_status, confidence,
--              as_of_date, source_note) to all 9 normalized entity tables.
--              These columns enable field-resolution tracking and evidence-to-entity
--              provenance without requiring JOINs back to source_documents for every read.
-- Date: 2026-06-17
--
-- Column semantics:
--   evidence_span_ids   JSON array of evidence_span.id values that support this row.
--   resolution_status   Field-resolution enum (confirmed|derived|proxy|industry_avg|
--                        llm_extracted|manual_needed|unavailable|not_applicable|conflict|
--                        draft|hidden) — matches the field-resolution layer.
--   confidence          0.0–1.0 numeric confidence.  Added only to companies (which has
--                        data_confidence TEXT but no confidence column).  The other 8
--                        tables already carry confidence TEXT DEFAULT 'medium' and are
--                        left as-is.
--   as_of_date          ISO-8601 date the fact was current as of (e.g. '2025-Q2').
--   source_note         Free-text provenance note (e.g. "Crunchbase, accessed 2025-06").
--
-- NOTE: SQLite does not support IF NOT EXISTS for ADD COLUMN.  The migrate.py runner
--       (db/migrate.py) catches "duplicate column name" errors and treats them as
--       idempotent, so each ALTER below is safe to re-run on an already-migrated DB.

BEGIN;

-- =========================================================================
-- 1. companies
-- =========================================================================
ALTER TABLE companies ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE companies ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
ALTER TABLE companies ADD COLUMN confidence REAL DEFAULT 0.5;
ALTER TABLE companies ADD COLUMN as_of_date TEXT DEFAULT '';
ALTER TABLE companies ADD COLUMN source_note TEXT DEFAULT '';

-- =========================================================================
-- 2. products
-- =========================================================================
ALTER TABLE products ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE products ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
-- confidence TEXT column already exists — skipped
ALTER TABLE products ADD COLUMN as_of_date TEXT DEFAULT '';
ALTER TABLE products ADD COLUMN source_note TEXT DEFAULT '';

-- =========================================================================
-- 3. metrics
-- =========================================================================
ALTER TABLE metrics ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE metrics ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
-- confidence TEXT column already exists — skipped
ALTER TABLE metrics ADD COLUMN as_of_date TEXT DEFAULT '';
ALTER TABLE metrics ADD COLUMN source_note TEXT DEFAULT '';

-- =========================================================================
-- 4. sectors
-- =========================================================================
ALTER TABLE sectors ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE sectors ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
-- confidence TEXT column already exists — skipped
ALTER TABLE sectors ADD COLUMN as_of_date TEXT DEFAULT '';
-- source_note TEXT already exists without DEFAULT.  The ALTER TABLE ADD COLUMN
-- will be skipped as duplicate by the migration runner.

-- =========================================================================
-- 5. founders
-- =========================================================================
ALTER TABLE founders ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE founders ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
-- confidence TEXT column already exists — skipped
ALTER TABLE founders ADD COLUMN as_of_date TEXT DEFAULT '';
ALTER TABLE founders ADD COLUMN source_note TEXT DEFAULT '';

-- =========================================================================
-- 6. funding_rounds
-- =========================================================================
ALTER TABLE funding_rounds ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE funding_rounds ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
-- confidence TEXT column already exists — skipped
ALTER TABLE funding_rounds ADD COLUMN as_of_date TEXT DEFAULT '';
ALTER TABLE funding_rounds ADD COLUMN source_note TEXT DEFAULT '';

-- =========================================================================
-- 7. customers
-- =========================================================================
ALTER TABLE customers ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE customers ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
-- confidence TEXT column already exists — skipped
ALTER TABLE customers ADD COLUMN as_of_date TEXT DEFAULT '';
ALTER TABLE customers ADD COLUMN source_note TEXT DEFAULT '';

-- =========================================================================
-- 8. competitors
-- =========================================================================
ALTER TABLE competitors ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE competitors ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
-- confidence TEXT column already exists — skipped
ALTER TABLE competitors ADD COLUMN as_of_date TEXT DEFAULT '';
ALTER TABLE competitors ADD COLUMN source_note TEXT DEFAULT '';

-- =========================================================================
-- 9. company_analysis
-- =========================================================================
ALTER TABLE company_analysis ADD COLUMN evidence_span_ids TEXT DEFAULT '[]';
ALTER TABLE company_analysis ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'llm_extracted';
-- confidence TEXT column already exists — skipped
ALTER TABLE company_analysis ADD COLUMN as_of_date TEXT DEFAULT '';
ALTER TABLE company_analysis ADD COLUMN source_note TEXT DEFAULT '';

COMMIT;
