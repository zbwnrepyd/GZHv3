-- 049_company_snapshots: 字段快照存储
-- 每次研究后保存字段值的快照，支持跨时间对比和变化方向检测

CREATE TABLE IF NOT EXISTS company_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_key TEXT NOT NULL,
    snapshot_at TEXT NOT NULL DEFAULT (datetime('now')),
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('full', 'fields_only', 'metrics_only')),
    field_key TEXT NOT NULL,
    field_value TEXT,
    value_type TEXT,
    norm_value REAL,
    unit TEXT,
    resolution_status TEXT,
    confidence_level TEXT,
    source_urls TEXT,
    research_run_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (company_key) REFERENCES companies(company_key)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_company_field
ON company_snapshots(company_key, field_key, snapshot_at);

CREATE INDEX IF NOT EXISTS idx_snapshots_type
ON company_snapshots(snapshot_type);
