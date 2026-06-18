-- 042_field_candidates_v2: 字段候选值表 (Goal 二 Spec)
-- 对应 Spec §Goal 二 "数据模型" field_candidates 定义

CREATE TABLE IF NOT EXISTS field_candidates (
    candidate_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    candidate_value TEXT NOT NULL,
    source_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL CHECK (status IN ('candidate','approved','rejected')),
    reject_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_field_candidates_company_field
ON field_candidates(company_id, field_key);
