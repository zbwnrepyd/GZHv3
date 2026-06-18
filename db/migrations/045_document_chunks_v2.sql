-- 045_document_chunks_v2: 文档切块表 (Goal 三 Spec)
-- 对应 Spec §Goal 三 "数据模型" document_chunks 定义

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    section_title TEXT,
    chunk_text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    chunk_order INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(document_id) REFERENCES source_documents(document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document
ON document_chunks(document_id);
