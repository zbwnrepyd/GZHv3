-- 033_export_runs: 导出运行审计表 (Goal 四 Spec)
-- 对应 Spec §Goal 四 "数据模型" export_runs 定义

CREATE TABLE IF NOT EXISTS export_runs (
    export_run_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    card_set TEXT NOT NULL,
    requested_cards_json TEXT NOT NULL,
    format TEXT NOT NULL,
    scale REAL NOT NULL DEFAULT 2.0,
    status TEXT NOT NULL,
    output_dir TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_export_runs_company
ON export_runs(company_id, created_at);
