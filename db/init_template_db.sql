-- template_db.sqlite — 模板与排版实例系统
-- 模板只负责表现，绑定的是 display_role 而非具体字段名

-- 卡片模板表
CREATE TABLE IF NOT EXISTS card_templates (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  template_id     TEXT    NOT NULL UNIQUE,   -- 模板唯一标识
  template_name   TEXT    NOT NULL,           -- 模板名称
  canvas_width    INTEGER DEFAULT 900,
  canvas_height   INTEGER DEFAULT 1200,
  background_type TEXT    DEFAULT 'color',    -- color | gradient | image
  background_value TEXT,                      -- CSS 值
  template_json   TEXT    NOT NULL,           -- 完整模板 JSON（regions + decorations）
  is_builtin      INTEGER DEFAULT 0,         -- 1=内置模板不可删
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 排版实例表（某公司某卡片的实际布局微调）
CREATE TABLE IF NOT EXISTS card_layout_instances (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  company_name TEXT    NOT NULL,
  card_id      TEXT    NOT NULL,   -- 关联 card_compositions.card_id
  template_id  TEXT,               -- 使用的模板
  layout_json  TEXT    NOT NULL,   -- JSON: {template_id, overrides: {region_id: {...}}}
  updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(company_name, card_id)
);

CREATE INDEX IF NOT EXISTS idx_layout_instances_company
  ON card_layout_instances(company_name);

-- ============================================================
-- 6 个内置模板
-- ============================================================

-- 1. 首页模板
INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('cover_default', '首页模板', 900, 1200, 'color', '#0B1629', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#0B1629"},
  "regions": [
    {"id": "hero_image", "type": "image", "role": "logo", "x": 325, "y": 380, "w": 250, "h": 250, "style": {"objectFit": "contain"}},
    {"id": "title", "type": "text", "role": "title", "x": 80, "y": 680, "w": 740, "h": 80, "style": {"fontFamily": "Noto Sans SC", "fontSize": 48, "fontWeight": 700, "color": "#FFFFFF", "textAlign": "center"}},
    {"id": "subtitle", "type": "text", "role": "subtitle", "x": 80, "y": 770, "w": 740, "h": 60, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "rgba(255,255,255,0.65)", "textAlign": "center"}}
  ],
  "decorations": [{"id": "grain", "type": "noise", "opacity": 0.04}]
}', 1);

-- 2. 上图下文模板
INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('image_top_text_bottom', '上图下文模板', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 120, "style": {"fontFamily": "Noto Sans SC", "fontSize": 52, "fontWeight": 700, "color": "#111111", "lineHeight": 1.15, "textAlign": "left"}},
    {"id": "hero_image", "type": "image", "role": "hero_image", "x": 80, "y": 240, "w": 740, "h": 400, "style": {"objectFit": "contain", "borderRadius": 8, "borderWidth": 1, "borderColor": "rgba(0,0,0,0.08)"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 700, "w": 740, "h": 420, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#222222", "lineHeight": 1.5}}
  ]
}', 1);

-- 3. 上图表下文模板
INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('chart_top_text_bottom', '上图表下文模板', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 100, "style": {"fontFamily": "Noto Sans SC", "fontSize": 48, "fontWeight": 700, "color": "#111111", "textAlign": "left"}},
    {"id": "chart", "type": "image", "role": "chart", "x": 50, "y": 220, "w": 800, "h": 500, "style": {"objectFit": "contain"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 760, "w": 740, "h": 360, "style": {"fontFamily": "Noto Sans SC", "fontSize": 23, "fontWeight": 400, "color": "#333333", "lineHeight": 1.5}}
  ]
}', 1);

-- 4. 多图表模板
INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('multi_chart', '多图表模板', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 70, "w": 764, "h": 90, "style": {"fontFamily": "Noto Sans SC", "fontSize": 46, "fontWeight": 700, "color": "#111111", "textAlign": "left"}},
    {"id": "chart_1", "type": "image", "role": "chart", "bind": "chart_competitive", "x": 30, "y": 190, "w": 410, "h": 340, "style": {"objectFit": "contain"}},
    {"id": "chart_2", "type": "image", "role": "chart", "bind": "chart_ecosystem", "x": 460, "y": 190, "w": 410, "h": 340, "style": {"objectFit": "contain"}},
    {"id": "logo_strip", "type": "image", "role": "decoration", "bind": "competitors_logo_strip", "x": 80, "y": 560, "w": 740, "h": 80, "style": {"objectFit": "contain"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 680, "w": 740, "h": 440, "style": {"fontFamily": "Noto Sans SC", "fontSize": 22, "fontWeight": 400, "color": "#333333", "lineHeight": 1.5}}
  ]
}', 1);

-- 5. 纯文字聚焦模板
INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('text_focus', '纯文字聚焦模板', 900, 1200, 'gradient', 'linear-gradient(180deg, #F8FAFC 0%, #FFFFFF 100%)', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "gradient", "value": "linear-gradient(180deg, #F8FAFC 0%, #FFFFFF 100%)"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 80, "y": 100, "w": 740, "h": 120, "style": {"fontFamily": "Noto Sans SC", "fontSize": 56, "fontWeight": 900, "color": "#0B1629", "textAlign": "center", "letterSpacing": "0.02em"}},
    {"id": "subtitle", "type": "text", "role": "subtitle", "x": 120, "y": 240, "w": 660, "h": 40, "style": {"fontFamily": "Noto Sans SC", "fontSize": 20, "fontWeight": 400, "color": "#64748B", "textAlign": "center"}},
    {"id": "divider", "type": "shape", "role": "decoration", "x": 400, "y": 310, "w": 100, "h": 2, "style": {"backgroundColor": "#29B8D4"}},
    {"id": "body", "type": "text", "role": "body", "x": 100, "y": 360, "w": 700, "h": 700, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#334155", "lineHeight": 1.6}}
  ]
}', 1);

-- 6. 蓝色杂志风模板
INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('magazine_blue', '蓝色杂志风模板', 900, 1200, 'color', '#0B1629', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#0B1629"},
  "regions": [
    {"id": "hero_image", "type": "image", "role": "hero_image", "x": 0, "y": 0, "w": 900, "h": 600, "style": {"objectFit": "cover"}},
    {"id": "hero_overlay", "type": "shape", "role": "decoration", "x": 0, "y": 400, "w": 900, "h": 200, "style": {"backgroundColor": "linear-gradient(0deg, #0B1629 0%, transparent 100%)"}},
    {"id": "title", "type": "text", "role": "title", "x": 80, "y": 640, "w": 740, "h": 100, "style": {"fontFamily": "Noto Sans SC", "fontSize": 48, "fontWeight": 700, "color": "#FFFFFF", "textAlign": "left"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 770, "w": 740, "h": 350, "style": {"fontFamily": "Noto Sans SC", "fontSize": 22, "fontWeight": 400, "color": "rgba(255,255,255,0.8)", "lineHeight": 1.55}}
  ]
}', 1);

-- ============================================================
-- v4 套卡模板（复用内置模板布局）
-- ============================================================

-- 7.1 AI 公司观察封面（v4）— 蓝色电影噪点杂志风，无人物/无具体物体
INSERT OR REPLACE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('cover_ai_observation_v4', '各赛道AI初创公司观察封面（v4）', 900, 1200, 'color', '#061A3A', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#061A3A"},
  "style_defaults": {
    "fontSize": 34,
    "lineHeight": 1.12,
    "paragraphGap": 18,
    "padding": 96,
    "bgColor": "#061A3A",
    "textColor": "#F7FBFF",
    "accentColor": "#5AD7FF",
    "imageMaxHeight": 0,
    "skin": "ai_observation_cover"
  },
  "regions": [
    {"id": "top_rule", "type": "shape", "role": "decoration", "x": 96, "y": 92, "w": 708, "h": 2, "style": {"backgroundColor": "#5AD7FF", "opacity": 0.85}},
    {"id": "series_label", "type": "text", "role": "label", "value": "各赛道AI初创公司观察之", "x": 96, "y": 138, "w": 620, "h": 54, "style": {"fontFamily": "Noto Sans SC", "fontSize": 30, "fontWeight": 800, "color": "#5AD7FF", "lineHeight": 1.1, "letterSpacing": "0"}},
    {"id": "title", "type": "text", "role": "title", "x": 96, "y": 224, "w": 708, "h": 310, "style": {"fontFamily": "Noto Sans SC", "fontSize": 88, "fontWeight": 900, "color": "#F7FBFF", "lineHeight": 1.02, "letterSpacing": "0", "textAlign": "left"}},
    {"id": "subtitle", "type": "text", "role": "subtitle", "x": 100, "y": 560, "w": 520, "h": 96, "style": {"fontFamily": "Noto Sans SC", "fontSize": 28, "fontWeight": 700, "color": "rgba(247,251,255,0.72)", "lineHeight": 1.25, "letterSpacing": "0", "textAlign": "left"}},
    {"id": "issue", "type": "text", "role": "caption", "value": "AI COMPANY DOSSIER", "x": 96, "y": 912, "w": 420, "h": 34, "style": {"fontFamily": "IBM Plex Mono", "fontSize": 20, "fontWeight": 700, "color": "rgba(247,251,255,0.62)", "letterSpacing": "0"}},
    {"id": "bottom_rule", "type": "shape", "role": "decoration", "x": 96, "y": 1000, "w": 708, "h": 2, "style": {"backgroundColor": "rgba(247,251,255,0.72)"}},
    {"id": "blue_band", "type": "shape", "role": "decoration", "x": 690, "y": 0, "w": 114, "h": 1200, "style": {"backgroundColor": "rgba(90,215,255,0.12)"}},
    {"id": "dark_band", "type": "shape", "role": "decoration", "x": 804, "y": 0, "w": 30, "h": 1200, "style": {"backgroundColor": "rgba(247,251,255,0.08)"}}
  ],
  "decorations": [{"id": "film_grain", "type": "noise", "opacity": 0.10}]
}', 1);

-- 7. 封面（v4_card_01 复用 cover_default 布局）
INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('cover_v3', '封面（v4）', 900, 1200, 'color', '#0B1629', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#0B1629"},
  "regions": [
    {"id": "hero_image", "type": "image", "role": "logo", "x": 325, "y": 380, "w": 250, "h": 250, "style": {"objectFit": "contain"}},
    {"id": "title", "type": "text", "role": "title", "x": 80, "y": 680, "w": 740, "h": 80, "style": {"fontFamily": "Noto Sans SC", "fontSize": 48, "fontWeight": 700, "color": "#FFFFFF", "textAlign": "center"}},
    {"id": "subtitle", "type": "text", "role": "subtitle", "x": 80, "y": 770, "w": 740, "h": 60, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "rgba(255,255,255,0.65)", "textAlign": "center"}}
  ],
  "decorations": [{"id": "grain", "type": "noise", "opacity": 0.04}]
}', 1);

-- 8-13. v4 故事线卡片（复用 image_top_text_bottom 上图下文布局）
INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('storyline_market_v4', '赛道切口（v4）', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 120, "style": {"fontFamily": "Noto Sans SC", "fontSize": 52, "fontWeight": 700, "color": "#111111", "lineHeight": 1.15, "textAlign": "left"}},
    {"id": "hero_image", "type": "image", "role": "hero_image", "x": 80, "y": 240, "w": 740, "h": 400, "style": {"objectFit": "contain", "borderRadius": 8, "borderWidth": 1, "borderColor": "rgba(0,0,0,0.08)"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 700, "w": 740, "h": 420, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#222222", "lineHeight": 1.5}}
  ]
}', 1);

INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('storyline_fundamentals_v4', '公司基本面（v4）', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 120, "style": {"fontFamily": "Noto Sans SC", "fontSize": 52, "fontWeight": 700, "color": "#111111", "lineHeight": 1.15, "textAlign": "left"}},
    {"id": "hero_image", "type": "image", "role": "hero_image", "x": 80, "y": 240, "w": 740, "h": 400, "style": {"objectFit": "contain", "borderRadius": 8, "borderWidth": 1, "borderColor": "rgba(0,0,0,0.08)"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 700, "w": 740, "h": 420, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#222222", "lineHeight": 1.5}}
  ]
}', 1);

INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('storyline_product_v4', '产品与价值主张（v4）', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 120, "style": {"fontFamily": "Noto Sans SC", "fontSize": 52, "fontWeight": 700, "color": "#111111", "lineHeight": 1.15, "textAlign": "left"}},
    {"id": "hero_image", "type": "image", "role": "hero_image", "x": 80, "y": 240, "w": 740, "h": 400, "style": {"objectFit": "contain", "borderRadius": 8, "borderWidth": 1, "borderColor": "rgba(0,0,0,0.08)"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 700, "w": 740, "h": 420, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#222222", "lineHeight": 1.5}}
  ]
}', 1);

INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('storyline_moat_v4', '竞争壁垒与生态位（v4）', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 120, "style": {"fontFamily": "Noto Sans SC", "fontSize": 52, "fontWeight": 700, "color": "#111111", "lineHeight": 1.15, "textAlign": "left"}},
    {"id": "hero_image", "type": "image", "role": "hero_image", "x": 80, "y": 240, "w": 740, "h": 400, "style": {"objectFit": "contain", "borderRadius": 8, "borderWidth": 1, "borderColor": "rgba(0,0,0,0.08)"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 700, "w": 740, "h": 420, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#222222", "lineHeight": 1.5}}
  ]
}', 1);

INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('storyline_business_model_v4', '商业模式与定价（v4）', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 120, "style": {"fontFamily": "Noto Sans SC", "fontSize": 52, "fontWeight": 700, "color": "#111111", "lineHeight": 1.15, "textAlign": "left"}},
    {"id": "hero_image", "type": "image", "role": "hero_image", "x": 80, "y": 240, "w": 740, "h": 400, "style": {"objectFit": "contain", "borderRadius": 8, "borderWidth": 1, "borderColor": "rgba(0,0,0,0.08)"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 700, "w": 740, "h": 420, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#222222", "lineHeight": 1.5}}
  ]
}', 1);

INSERT OR IGNORE INTO card_templates (template_id, template_name, canvas_width, canvas_height, background_type, background_value, template_json, is_builtin) VALUES
('storyline_growth_v4', '增长飞轮与关键指标（v4）', 900, 1200, 'color', '#FFFFFF', '{
  "canvas": {"width": 900, "height": 1200},
  "background": {"type": "color", "value": "#FFFFFF"},
  "regions": [
    {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 120, "style": {"fontFamily": "Noto Sans SC", "fontSize": 52, "fontWeight": 700, "color": "#111111", "lineHeight": 1.15, "textAlign": "left"}},
    {"id": "hero_image", "type": "image", "role": "hero_image", "x": 80, "y": 240, "w": 740, "h": 400, "style": {"objectFit": "contain", "borderRadius": 8, "borderWidth": 1, "borderColor": "rgba(0,0,0,0.08)"}},
    {"id": "body", "type": "text", "role": "body", "x": 80, "y": 700, "w": 740, "h": 420, "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#222222", "lineHeight": 1.5}}
  ]
}', 1);
