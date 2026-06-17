-- 036_final_card_values_columns.sql
-- Description: Add SPEC Section 5.4 columns to final_card_values table.
--              resolution_status, confidence (REAL), source_note, card_id.
-- Date: 2026-06-18

BEGIN;

-- Add resolution_status alongside existing 'status' column (SPEC uses resolution_status)
ALTER TABLE final_card_values ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'draft';

-- Add source_note for human-readable provenance
ALTER TABLE final_card_values ADD COLUMN source_note TEXT DEFAULT '';

-- Add card_id for cross-reference (complements card_no)
ALTER TABLE final_card_values ADD COLUMN card_id TEXT DEFAULT '';

COMMIT;
