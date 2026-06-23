-- 048_add_market_track_fields: 新增赛道/细分赛道字段
-- 两个字段均为文本类型，存储在 research 表 company_profile 列区域

ALTER TABLE research ADD COLUMN market_track TEXT;
ALTER TABLE research ADD COLUMN market_subtrack TEXT;
