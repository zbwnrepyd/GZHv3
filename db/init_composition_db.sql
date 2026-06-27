-- composition_db.sqlite — 卡片编排系统
-- v2: 加 card_set_key + card_set_registry

-- 卡片表
CREATE TABLE IF NOT EXISTS card_compositions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  company_name TEXT    NOT NULL,
  card_set_key TEXT    NOT NULL DEFAULT 'v1',
  card_id      TEXT    NOT NULL,
  card_index   INTEGER NOT NULL,
  card_title   TEXT    NOT NULL,
  enabled      INTEGER DEFAULT 1,
  template_id  TEXT,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(company_name, card_set_key, card_id)
);

CREATE INDEX IF NOT EXISTS idx_card_compositions_company
  ON card_compositions(company_name, card_set_key);

-- 卡片内容项表
CREATE TABLE IF NOT EXISTS card_items (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  company_name TEXT    NOT NULL,
  card_set_key TEXT    NOT NULL DEFAULT 'v1',
  card_id      TEXT    NOT NULL,
  item_type    TEXT    NOT NULL,
  item_key     TEXT    NOT NULL,
  item_label   TEXT,
  sort_order   INTEGER DEFAULT 0,
  display_role TEXT    DEFAULT 'body',
  enabled      INTEGER DEFAULT 1,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_card_items_card
  ON card_items(company_name, card_set_key, card_id);

-- 套卡注册表
CREATE TABLE IF NOT EXISTS card_set_registry (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    set_key        TEXT    NOT NULL UNIQUE,
    display_name   TEXT    NOT NULL,
    spec_version   TEXT    NOT NULL,
    card_count     INTEGER NOT NULL,
    is_system      INTEGER NOT NULL DEFAULT 0,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO card_set_registry
    (set_key, display_name, spec_version, card_count, is_system)
VALUES
    ('v1', '套卡1 · 经典8张', 'v1', 8, 1),
    ('v2', '套卡2 · 新版7张', 'v2', 7, 1),
    ('v3', '套卡3 · 研究增强版', 'v3', 8, 1);

-- 默认卡片配置（v2: 加 set_key，UNIQUE 约束改为 (set_key, card_id)）
CREATE TABLE IF NOT EXISTS default_card_configs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  set_key      TEXT    NOT NULL DEFAULT 'v1',
  card_id      TEXT    NOT NULL,
  card_index   INTEGER NOT NULL,
  card_title   TEXT    NOT NULL,
  config_json  TEXT    NOT NULL,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(set_key, card_id)
);

-- v1 套卡的 8 张默认配置（set_key='v1'）
INSERT OR IGNORE INTO default_card_configs (set_key, card_id, card_index, card_title, config_json) VALUES
('v1','card_01',1,'首页','{"fields":["company_name","company_type"],"media":["logo"],"template_id":"cover_default"}'),
('v1','card_02',2,'公司介绍','{"fields":["location","company_def","founder_name","founder_edu","founder_bg","founder_achievement","team_size","team_highlight","funding_info","website_url"],"media":["office","website_screenshot"],"template_id":"image_top_text_bottom"}'),
('v1','card_03',3,'发展沿袭','{"fields":["timeline_events"],"media":["timeline"],"template_id":"chart_top_text_bottom"}'),
('v1','card_04',4,'主产品','{"fields":["main_product_name","main_product_def","main_product_highlight","main_product_achievement"],"media":["product_main"],"template_id":"image_top_text_bottom"}'),
('v1','card_05',5,'其他产品','{"fields":["other_products"],"media":["products_other"],"template_id":"image_top_text_bottom"}'),
('v1','card_06',6,'商业模式','{"fields":["revenue_model","gtm_strategy","cold_start","customer_segment","growth_flywheel"],"media":["flywheel"],"template_id":"chart_top_text_bottom"}'),
('v1','card_07',7,'竞争格局','{"fields":["moat","ecosystem_niche","competitors"],"media":["competitors_logo_strip","chart_competitive","chart_ecosystem"],"template_id":"multi_chart"}'),
('v1','card_08',8,'总结','{"fields":["market_opportunity","data_confidence"],"media":[],"template_id":"text_focus"}');

-- v2 套卡的 7 张默认配置（set_key='v2'）
-- 用 OR REPLACE 让已有本地库在应用启动时拿到最新默认编排；不影响已实例化到具体公司的 card_items。
INSERT OR REPLACE INTO default_card_configs (set_key, card_id, card_index, card_title, config_json) VALUES
('v2','v2_card_01',1,'封面','{"fields":["company_name","company_type"],"media":["logo"],"template_id":"cover_default"}'),
('v2','v2_card_02',2,'公司概览','{"fields":["company_def","location","funding_info","main_product_name","main_product_highlight","main_product_achievement","arr","registered_users","website_url"],"media":["website_screenshot"],"template_id":"overview_v2"}'),
('v2','v2_card_03',3,'产品与定位','{"fields":["ecosystem_positioning","differentiation_strategy","cost_advantage","tam","sam","som","market_cagr"],"media":["chart_ecosystem"],"template_id":"product_v2"}'),
('v2','v2_card_04',4,'创始人与团队','{"fields":["founder_name","founder_edu","founder_bg","founder_achievement","team_size","team_highlight"],"media":["founder_photo"],"template_id":"founder_v2"}'),
('v2','v2_card_05',5,'核心客户','{"fields":["ideal_customer_profile","customer_segment_primary","customer_segment_secondary","retention_rate","paying_users"],"media":["product_main"],"template_id":"finance_v2"}'),
('v2','v2_card_06',6,'GTM与增长','{"fields":["growth_strategy","gtm_motion","growth_flywheel","cac","ltv","ltv_cac_ratio"],"media":["flywheel"],"template_id":"gtm_v2"}'),
('v2','v2_card_07',7,'竞争格局','{"fields":["competitors_summary","technical_barrier","switching_cost","score_defensibility","score_incumbent_attention"],"media":["chart_competitive"],"template_id":"competitive_v2"}');

-- v3 套卡的 8 张默认配置（set_key='v3'）
INSERT OR REPLACE INTO default_card_configs (set_key, card_id, card_index, card_title, config_json) VALUES
('v3','v3_card_01',1,'封面','{"fields":["company_name","company_type"],"media":["logo"],"template_id":"cover_v3"}'),
('v3','v3_card_02',2,'公司简介','{"fields":["market_track","market_subtrack","market_landscape_summary","market_landscape_top_players","market_size_value","market_size_currency","market_size_year","market_cagr","tam_value","tam_currency","tam_year","location","founded_date","core_business","core_competency","funding_info","funding_rounds","company_achievements","industry_positioning"],"media":["website_screenshot"],"template_id":"company_intro_v3"}'),
('v3','v3_card_03',3,'主产品','{"fields":["main_product_name","product_pain_points","product_core_features","product_usage_playbook","product_tech_stack","regional_market_focus","mau","mau_as_of","retention_definition","retention_rate","pricing_summary","pricing_tiers"],"media":["product_main"],"template_id":"product_v3"}'),
('v3','v3_card_04',4,'创始团队','{"fields":["founder_name","founder_edu","founder_bg","founder_achievement","team_size","team_highlight"],"media":["founder_photo"],"template_id":"founder_v3"}'),
('v3','v3_card_05',5,'用户群体','{"fields":["ideal_customer_profile","customer_segment_primary","customer_segment_secondary","customer_names","customer_selection_reasons","customer_choice_evidence"],"media":["customer_logos"],"template_id":"users_v3"}'),
('v3','v3_card_06',6,'公司能力分析','{"fields":["ecosystem_niche","revenue_model","pricing_strategy","ltv","cac","ltv_cac_ratio","ltv_cac_is_benchmark","ltv_cac_benchmark_source"],"media":["chart_ecosystem"],"template_id":"capability_v3"}'),
('v3','v3_card_07',7,'增长与GTM','{"fields":["growth_strategy","cold_start","gtm_strategy","growth_flywheel","acquisition_channels"],"media":["flywheel"],"template_id":"gtm_growth_v3"}'),
('v3','v3_card_08',8,'竞争态势','{"fields":["competitors_top3","competitive_position","differentiated_opportunity","competitive_advantages"],"media":["chart_competitive"],"template_id":"competition_v3"}');
