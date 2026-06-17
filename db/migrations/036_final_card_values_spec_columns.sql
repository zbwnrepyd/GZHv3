-- 036_final_card_values_spec_columns: SPEC Section 5.4 列对齐
-- 为 final_card_values 补充读模型所需的 SPEC 约定列名。
-- 原列 (final_value, status, confidence TEXT, source_evidence_ids, editor_note) 保留不动。
-- 新增 SPEC 列：field_value, resolution_status, confidence_score REAL, evidence_span_ids, source_note, card_id

ALTER TABLE final_card_values ADD COLUMN field_value TEXT;
ALTER TABLE final_card_values ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'draft';
ALTER TABLE final_card_values ADD COLUMN confidence_score REAL DEFAULT 0.0;
ALTER TABLE final_card_values ADD COLUMN evidence_span_ids TEXT;
ALTER TABLE final_card_values ADD COLUMN source_note TEXT;
ALTER TABLE final_card_values ADD COLUMN card_id TEXT;

-- 将已有数据同步到新列（后续写入由 CardValueBuilder 同时填双列）
UPDATE final_card_values SET
    field_value = final_value,
    resolution_status = status,
    evidence_span_ids = source_evidence_ids,
    source_note = editor_note;
