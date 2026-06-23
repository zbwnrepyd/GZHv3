-- 047_market_estimates: Market Intelligence 估算存储
-- 保存自底向上 TAM 计算、竞品代理估算和融资计算的结果
-- 每行代表一次对某公司某字段的估算尝试

CREATE TABLE IF NOT EXISTS market_estimates (
    id TEXT PRIMARY KEY,
    company_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    estimate_type TEXT NOT NULL CHECK (
        estimate_type IN ('bottom_up','comparable','proxy','direct_report','funding_calc')
    ),
    formula TEXT,
    inputs_json TEXT,
    result_value REAL,
    result_text TEXT,
    currency TEXT DEFAULT 'USD',
    year INTEGER,
    confidence REAL NOT NULL DEFAULT 0.0,
    evidence_ids TEXT,
    status TEXT NOT NULL DEFAULT 'derived' CHECK (
        status IN ('confirmed','derived','proxy','llm_located','unavailable','not_applicable')
    ),
    assumptions TEXT,
    disclaimer TEXT,
    region TEXT,
    segment TEXT,
    source_url TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (company_key) REFERENCES companies(company_key)
);

CREATE INDEX IF NOT EXISTS idx_market_estimates_company_field
ON market_estimates(company_key, field_key);

CREATE INDEX IF NOT EXISTS idx_market_estimates_type
ON market_estimates(estimate_type);

CREATE INDEX IF NOT EXISTS idx_market_estimates_status
ON market_estimates(status);
