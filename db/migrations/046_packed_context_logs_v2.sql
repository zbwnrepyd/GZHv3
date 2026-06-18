-- 046_packed_context_logs_v2: 上下文打包日志表 (Goal 三 Spec)
-- 对应 Spec §Goal 三 "数据模型" packed_context_logs 定义

CREATE TABLE IF NOT EXISTS packed_context_logs (
    log_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    model_name TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    selected_chunks_json TEXT NOT NULL,
    dropped_chunks_json TEXT NOT NULL,
    pack_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_packed_context_logs_run_stage
ON packed_context_logs(run_id, stage);
