-- 041_evidence_items_v2: 证据条目表 (Goal 二 Spec)
-- 对应 Spec §Goal 二 "数据模型" evidence_items 定义

CREATE TABLE IF NOT EXISTS evidence_items (
    evidence_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    start_offset INTEGER,
    end_offset INTEGER,
    confidence REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(document_id) REFERENCES source_documents(document_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_items_document
ON evidence_items(document_id);
