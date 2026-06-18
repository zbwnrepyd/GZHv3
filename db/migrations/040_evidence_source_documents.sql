-- 040_evidence_source_documents: 证据源文档表 (Goal 二 Spec)
-- 对应 Spec §Goal 二 "数据模型" source_documents 定义

CREATE TABLE IF NOT EXISTS source_documents (
    document_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_documents_company
ON source_documents(company_id);
