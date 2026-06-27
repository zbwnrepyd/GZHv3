-- 050: 字段治理增强 — 扩展 field_resolution_logs 支持分流、派生、补搜、评分阻塞追踪
-- 新增列: resolution_type (discard|infer|search_once|compute|write)
--          source_fields (派生源的 confirmed 字段列表)
--          search_executed (补搜是否已执行 0|1)
--          lineage (派生链路 JSON: {"from": [...], "method": "...", "prompt_hash": "..."})
--          blocked_by (评分阻塞字段列表 JSON)

ALTER TABLE field_resolution_logs ADD COLUMN resolution_type TEXT DEFAULT '';
ALTER TABLE field_resolution_logs ADD COLUMN source_fields TEXT DEFAULT '';
ALTER TABLE field_resolution_logs ADD COLUMN search_executed INTEGER DEFAULT 0;
ALTER TABLE field_resolution_logs ADD COLUMN lineage TEXT DEFAULT '';
ALTER TABLE field_resolution_logs ADD COLUMN blocked_by TEXT DEFAULT '';

-- 索引: 按 resolution_type 查询（用于定稿台判断字段可信度）
CREATE INDEX IF NOT EXISTS idx_reslog_rtype ON field_resolution_logs(company_name, resolution_type);
