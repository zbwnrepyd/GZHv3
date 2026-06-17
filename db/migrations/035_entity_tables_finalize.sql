-- 035_entity_tables_finalize.sql
-- Description: Add audit column indexes and missing timestamp columns for SPEC v3 entity tables.
--              Audit columns (evidence_span_ids, resolution_status, confidence, as_of_date,
--              source_note) were added by migration 034. This migration adds indexes on
--              resolution_status and any missing created_at/updated_at columns.
-- Date: 2026-06-17
--
-- Entity tables covered: companies, products, metrics, founders, funding_rounds,
-- customers, competitors, company_analysis

BEGIN;

-- ============================================================================
-- 1. Missing timestamp columns (SQLite ALTER only supports constant defaults)
-- ============================================================================

-- products: already has created_at, add updated_at if missing
ALTER TABLE products ADD COLUMN updated_at TEXT DEFAULT '';

-- metrics: already has created_at
ALTER TABLE metrics ADD COLUMN updated_at TEXT DEFAULT '';

-- founders: add timestamp columns
ALTER TABLE founders ADD COLUMN created_at TEXT DEFAULT '';
ALTER TABLE founders ADD COLUMN updated_at TEXT DEFAULT '';

-- funding_rounds: add timestamp columns
ALTER TABLE funding_rounds ADD COLUMN created_at TEXT DEFAULT '';
ALTER TABLE funding_rounds ADD COLUMN updated_at TEXT DEFAULT '';

-- customers: add timestamp columns
ALTER TABLE customers ADD COLUMN created_at TEXT DEFAULT '';
ALTER TABLE customers ADD COLUMN updated_at TEXT DEFAULT '';

-- competitors: add timestamp columns
ALTER TABLE competitors ADD COLUMN created_at TEXT DEFAULT '';
ALTER TABLE competitors ADD COLUMN updated_at TEXT DEFAULT '';

-- company_analysis: already has created_at
ALTER TABLE company_analysis ADD COLUMN updated_at TEXT DEFAULT '';

-- ============================================================================
-- 2. Indexes on resolution_status (added by 034)
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_companies_resolution      ON companies(resolution_status);
CREATE INDEX IF NOT EXISTS idx_products_resolution        ON products(resolution_status);
CREATE INDEX IF NOT EXISTS idx_metrics_resolution         ON metrics(resolution_status);
CREATE INDEX IF NOT EXISTS idx_founders_resolution        ON founders(resolution_status);
CREATE INDEX IF NOT EXISTS idx_funding_rounds_resolution  ON funding_rounds(resolution_status);
CREATE INDEX IF NOT EXISTS idx_customers_resolution       ON customers(resolution_status);
CREATE INDEX IF NOT EXISTS idx_competitors_resolution     ON competitors(resolution_status);
CREATE INDEX IF NOT EXISTS idx_company_analysis_resolution ON company_analysis(resolution_status);

-- ============================================================================
-- 3. Composite index on (company_key, resolution_status)
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_companies_key_resolution
    ON companies(company_key, resolution_status);

COMMIT;
