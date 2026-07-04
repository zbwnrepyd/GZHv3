# 项目指南

新人入口文档。读完这份文档 + 跑通一次研究 = 理解整个系统。

## 一句话

输入公司名 + 官网 URL → 自动研究 → 人工定稿 → 输出 v1 8 张、v2 7 张、v3 研究增强版 8 张或 v4 故事线 7 张 3:4 知识卡片 PNG。

## 快速理解（5 分钟）

### 这是一条流水线，三个工作台

```
研究台(/) → 定稿台(/editor) → 卡片制作台(/canvas) / 排版中心(/layout) → 导出 PNG
```

1. **研究台** `http://127.0.0.1:5050/` — 输入公司名和官网，点「开始研究」。后台跑 4 路数据采集 + 4 层 LLM 分析 + 自动图片收集
2. **定稿台** `http://127.0.0.1:5050/editor?company=<公司名>&set=v1|v2|v3|v4` — 顶部切换套卡→卡片设置→文字定稿→图片定稿，左栏底部固定「进入排版」
3. **卡片制作台** `http://127.0.0.1:5050/canvas/?company=<公司名>` — HTML/CSS 卡片编辑和预览
4. **排版中心** `http://127.0.0.1:5050/layout?company=<公司名>&set=v1|v2|v3|v4` — 选模板、调图层、改文字位置和样式

### 研究工作流

```
Step 1: 4路并行采集
  Tavily 自适应多意图搜索(初始 basic 查询 + 证据缺口 advanced 升级) + GitHub 仓库 + YouTube 创始人视频 + 官网抓取(trafilatura)
  → 4线程并行，每路独立上报状态；Tavily 按 query 增量上报累计进度并缓存重复查询

Step 2: 4层 LLM 分析
  L0 信息清洗 → L1 横纵分析 → L2 商业结构 → L3 字段提取(3版本)

Step 3: 评分 + 写入
  枚举字段三层管道(规则层→LLM三组→Pydantic验证) → 加权评分 → research 表
  → evidence_items 持久化证据 → research_fields 字段分辨率状态标记

Step 4: 自动图片采集
  Logo/Website/Product/Founder/Competitors 多源候选 → 质量检测 → 评分 → image_variants 候选池
```

### 定稿流程

```
卡片设置 → 文字定稿 → 图片定稿 → 进入排版
(卡片数量/内容可自由编排)   (12种素材槽位，含3个兼容槽位)
```

### 默认卡片（四套卡）

**v1 经典 8 张：**

| 卡片 | 主题 |
|---|---|
| card_1 | 首页：公司名、类型、核心定位 |
| card_2 | 公司介绍：位置、创始人、团队、融资 |
| card_3 | 发展沿袭：时间线 |
| card_4 | 主产品：产品名、定义、亮点、成就 |
| card_5 | 其他产品：产品矩阵 |
| card_6 | 商业模式：盈利、GTM、冷启动、飞轮 |
| card_7 | 竞争格局：壁垒、竞品、生态位 + 2张评分散点图 |
| card_8 | 总结：赛道机会 |

**v2 新版 7 张：**

| 卡片 | 主题 |
|---|---|
| card_1 | 封面：公司名、Logo |
| card_2 | 公司概览：官网截图、定义、地点、融资、主产品、ARR/注册用户 |
| card_3 | 生态位与变现：生态位图、错位竞争、成本优势、TAM/SAM/SOM |
| card_4 | 创始人与团队：创始人照片、背景、团队规模 |
| card_5 | 核心客户：理想客户画像、主/次客户细分、留存/付费指标 |
| card_6 | GTM 与增长：增长策略、GTM、增长飞轮、CAC/LTV |
| card_7 | 竞争格局：竞争格局图、竞品摘要、技术壁垒、迁移成本 |

**v3 研究增强版 8 张：**

| 卡片 | 主题 |
|---|---|
| v3_card_01 | 封面：公司名、类型 |
| v3_card_02 | 公司简介：市场格局、市场规模、地点、融资、公司能力 |
| v3_card_03 | 主产品：痛点、核心功能、使用方法、技术栈、区域市场 |
| v3_card_04 | 创始团队：创始人照片、背景、团队规模 |
| v3_card_05 | 用户群体：客户画像、客户名单、选择理由和证据 |
| v3_card_06 | 公司能力分析：生态位、收入/定价、LTV/CAC |
| v3_card_07 | 增长与 GTM：增长策略、GTM、冷启动、飞轮、渠道 |
| v3_card_08 | 竞争态势：Top 竞品、竞争位置、错位机会、优势 |

**v4 故事线 7 张（默认）：**

| 卡片 | 主题 |
|---|---|
| v4_card_01 | 封面：公司名、类型、Logo |
| v4_card_02 | 赛道切口：市场格局、机会、公司定义 |
| v4_card_03 | 公司基本面：产品、创始人、融资、团队 |
| v4_card_04 | 产品与价值主张：核心业务、亮点、痛点、成就 |
| v4_card_05 | 竞争壁垒与生态位：竞争位置、护城河、生态位、转换成本 |
| v4_card_06 | 商业模式与定价：收入/定价、成本优势、推理成本 |
| v4_card_07 | 增长飞轮与关键指标：GTM、渠道、增长指标、飞轮 |

## 关键架构决策

### 模板渲染而非画布拖拽

卡片不使用 fabric.js 画布拖拽。每张卡是一个 HTML/CSS 模板，在 `900 × 1200` 的 3:4 画布中渲染。模板按 `display_role`（title/body/image/badge）绑定内容区域，不按字段名绑定。`canvas/js/template-renderer.js` 是核心渲染引擎。

### 图片定稿：槽位模式

图片不在卡片制作台处理，而是在专门的图片定稿台（`image-studio/`）中按 `asset_key` 管理。当前 `company_assets` 保留 12 种槽位，其中 `office/products_other/timeline` 是 v2 起不再主渲染的兼容槽位。两类槽位：

- **采集图片类**（logo/website_screenshot/founder_photo/product_main/competitors 等）→ 三栏布局：左槽位列表，中预览+搜索+工具栏，右候选缩略图
- **图表类**（flywheel/timeline/chart_competitive/chart_ecosystem）→ 中间 iframe 实时预览 + 底部参数调节 + 右侧代码/操作面板

### 5 个 SQLite 数据库

| 数据库 | 职责 |
|---|---|
| `research_db` | 研究原始数据（宽表 60+ 字段）+ 评分 + 任务状态 + 证据/字段分辨率审计 |
| `final_db` | 人工定稿字段（按 company+field_key 唯一） |
| `assets_db` | 图片素材槽位 + 候选池 |
| `composition_db` | 卡片编排（每张卡有哪些字段/图片） |
| `template_db` | 模板定义 + 排版实例 |

### 研究数据的三版本

每次研究生成 3 个版本：

- **standard** — 标准版：客观完整，数据优先，适合事实核查
- **business** — 商业版：投资人视角，突出商业潜力和竞争分析
- **spread** — 传播版：高钩子密度，自媒体友好，金句化表达

### 评分体系

10 个枚举字段 → 加权公式 → 3 个 0–10 评分 → 2 张 ECharts 散点图。ECharts 使用 `webapp/static/vendor/echarts.min.js` 本地 runtime，预览和 Playwright 截图不依赖外部 CDN。详见 [docs/scoring-system.md](scoring-system.md)。

## 深入文档

| 文档 | 内容 |
|---|---|
| [README.md](../README.md) | 安装、启动、常用命令 |
| [docs/architecture.md](architecture.md) | 系统架构、数据模型、路由清单 |
| [docs/runbook.md](runbook.md) | 运维手册：冒烟测试、故障排查、API 示例 |
| [docs/card-spec.md](card-spec.md) | 卡片和图片资产规范 |
| [docs/scoring-system.md](scoring-system.md) | 评分体系完整说明 |
| [docs/decoupled-architecture-review.md](decoupled-architecture-review.md) | 解耦架构审查记录 |

## 目录约定

```
prompts/              LLM Prompt 文件（L0-L3 + L3 三组枚举提取）
webapp/               Flask 后台 + 研究流水线
  app.py              主入口（路由 + 资产 API + 渲染）
  pipeline.py          研究流水线
  competitive_scoring.py  评分计算
  field_rules.py       Layer 1 规则层
  field_validator.py   Layer 3 Pydantic 验证
  infographic.py       ECharts/SVG 图表渲染
  asset_pipeline.py    自动图片采集
  path_safety.py        公司名/图片路径片段安全清理
  routes/              Blueprint 路由模块
  services/            业务逻辑层
  repositories/        数据访问层
image-studio/          图片定稿台（独立 HTML + JS/CSS）
canvas/                卡片制作台 + Puppeteer 截图脚本
db/                    SQLite schema + 迁移
  migrate.py            幂等迁移运行器（schema_migrations）
tests/                 29 个 unittest 测试文件
output/                导出输出（卡片 PNG、调试报告）
```

## 第一次上手

```bash
# 1. 安装
pip install -r requirements.txt
npm install

# 2. 初始化数据库
sqlite3 db/research_db.sqlite < db/init_research_db.sql
sqlite3 db/final_db.sqlite < db/init_final_db.sql
sqlite3 db/assets_db.sqlite < db/init_assets_db.sql
sqlite3 db/composition_db.sqlite < db/init_composition_db.sql
sqlite3 db/template_db.sqlite < db/init_template_db.sql
python3 db/migrate.py db/research_db.sqlite --only 001_research_fields.sql
python3 db/migrate.py db/research_db.sqlite --only 009_evidence_items.sql
python3 db/migrate.py db/research_db.sqlite --only 010_field_resolution.sql
python3 db/migrate.py db/research_db.sqlite --only 011_v3_fields.sql
python3 db/migrate.py db/final_db.sqlite --only 002_final_fields.sql
python3 db/migrate.py db/final_db.sqlite --only 012_v3_final_fields.sql

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 和 TAVILY_API_KEY

# 4. 启动
cd webapp && python3 app.py

# 5. 研究一家公司
curl -X POST http://127.0.0.1:5050/api/research/start \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Anthropic","company_url":"https://www.anthropic.com"}'

# 6. 在浏览器打开定稿台
open "http://127.0.0.1:5050/editor?company=Anthropic&set=v3"

# 7. 导出卡片 PNG
node canvas/screenshot.js --company Anthropic --set v3 --base-url http://127.0.0.1:5050
```
