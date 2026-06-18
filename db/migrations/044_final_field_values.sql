-- 044_final_field_values: 最终字段值表 (Goal 二 Spec)
-- 对应 Spec §Goal 二 "数据模型" final_field_values 定义

CREATE TABLE IF NOT EXISTS final_field_values (
    company_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    selected_candidate_id TEXT,
    field_status TEXT NOT NULL CHECK (
      field_status IN (
        'confirmed','derived','proxy','llm_extracted',
        'manual_needed','unavailable','not_applicable'
      )
    ),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(company_id, field_key),
    FOREIGN KEY(selected_candidate_id) REFERENCES field_candidates(candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_final_field_values_candidate
ON final_field_values(selected_candidate_id);
