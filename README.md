# AI自媒体知识卡片生产系统

一个本地运行的三段式生产工具：研究一家 AI 公司，人工定稿文字和图片，通过卡片编排和模板排版生成可配置数量的知识卡片。内置四套规格：v1 经典 8 张、v2 新版 7 张、v3 研究增强版 8 张、v4 故事线 7 张（默认），可在定稿台顶部切换。

## 快速开始

```bash
pip install -r requirements.txt
npm install
sqlite3 db/research_db.sqlite < db/init_research_db.sql
sqlite3 db/final_db.sqlite < db/init_final_db.sql
sqlite3 db/assets_db.sqlite < db/init_assets_db.sql
sqlite3 db/composition_db.sqlite < db/init_composition_db.sql
sqlite3 db/template_db.sqlite < db/init_template_db.sql
# 应用全部迁移（含证据层013-019 + 规范化实体表020-030）
python3 db/migrate.py db/research_db.sqlite
python3 db/migrate.py db/final_db.sqlite
cd webapp
python3 app.py
```

打开：

```text
http://127.0.0.1:5050/
```

在研究台输入公司名和官网，点击”开始研究”。研究完成后进入定稿台，按「卡片设置 → 文字定稿 → 图片定稿 → 进入排版」的新流程操作。定稿台顶部可切换 v1/v2/v3/v4 套卡（卡片数量和字段结构不同），文字定稿支持从标准版/商业版/传播版一键采用并编辑；卡片设置可自由增减卡片、分配字段和图片引用。

## 环境变量

服务会读取系统环境变量，也会尝试读取项目根目录 `.env`。优先级是：系统环境变量 > 项目 `.env`。项目不读取 `~/.env`。

```bash
DEEPSEEK_API_KEY=sk-...
# Tavily 单 Key 或多 Key 二选一；多 Key 用英文逗号分隔，遇到额度限制会自动尝试下一个
TAVILY_API_KEY=tvly-...
TAVILY_API_KEYS=tvly-...,tvly-...
TAVILY_ADAPTIVE_MODE=1
TAVILY_INITIAL_QUERY_LIMIT=10
TAVILY_QUERY_BUDGET_STANDARD=14
TAVILY_QUERY_BUDGET_DEEP=24
TAVILY_RESULTS_PER_QUERY=5
TAVILY_CACHE_TTL_SECONDS=86400
COLLECTION_ENABLE_GAP_REFETCH=1
EVIDENCE_SPAN_BINDING_ENABLED=1
ORCHESTRATOR_ENABLED=0
YOUTUBE_API_KEY=...
GOOGLE_MAPS_API_KEY=...  # 可选：Street View Static API，作为 office 地图后的补充候选
IMAGE_API_KEY=sk-...
IMAGE_API_URL=https://api.openai.com/v1/images/generations
FLASK_PORT=5050
SCREENSHOT_PROVIDER=local
```

`YOUTUBE_API_KEY` 和图片生成相关变量可以暂时为空；对应能力会降级或在调用时失败。图片定稿台 AI 生图请求也可以临时发送图片 API URL 和 API Key，API Key 只随当次请求发送，不写入浏览器本地存储，也不在响应中回显。

## 目录

```text
prompts/      L0-L3 研究 Prompt 和文本分段 Prompt
webapp/       Flask 后台、编辑器 API、Python 研究流水线
image-studio/ 图片定稿台：中栏上下分区（预览/搜索切换 + 工具栏），右栏候选缩略图+确定
canvas/       HTML/CSS 卡片制作台、单卡页面和 Puppeteer 截图脚本
db/           SQLite schema 和本地数据库
tests/        unittest 回归测试
```

## 常用命令

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile webapp/*.py
python3 db/migrate.py --help
node canvas/screenshot.js --help
```

命令行启动一次研究：

```bash
curl -X POST http://127.0.0.1:5050/api/research/start \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Anthropic","company_url":"https://www.anthropic.com"}'
```

查询进度：

```bash
curl http://127.0.0.1:5050/api/research/status/<job_id>
```

进入某公司的定稿台：

```text
http://127.0.0.1:5050/editor?company=Anthropic&set=v3
```

进入卡片制作台：

```text
http://127.0.0.1:5050/canvas/?company=Anthropic
```

进入排版中心：

```text
http://127.0.0.1:5050/layout?company=Anthropic&set=v3
```

卡片制作台会从 `/api/render-data/<company>` 读取卡片编排 + 字段值 + 图片路径。左侧只读显示当前项目名，并用互斥手风琴组织”卡片每一页”和”图片素材”；导出按钮始终常驻。中间显示 3:4 HTML 画布，右侧显示当前页完整 HTML+CSS 源码并带语法高亮。顶部”返回定稿台”回到 `/editor?company=<公司名>`。

排版中心同样读取 `/api/render-data/<company>`，用于逐卡选择模板、选择图层、调整位置/尺寸/字体/颜色并保存到 `/api/layout/<company>/<card_id>`。选中文字图层后，画布中的对应区域会高亮；双击高亮区域会打开 Markdown 文本框，可直接编辑原始 Markdown。编辑提交后作为该 region 的 `value` override 保存，模板渲染器会优先使用 override 并按 Markdown 规则渲染。

研究流水线会把证据池写入 `evidence_items`，并给 `research_fields` 标记字段分辨率状态（confirmed/derived/proxy/unavailable/manual_needed/not_applicable/llm_extracted）。`GET /api/company/<company>/all-fields` 会返回这些状态，用于调试哪些经营指标是公开确认、估算、不可得或需人工确认。

图片定稿台按 `asset_key` 管理素材需求。v1/legacy 的 `office` 素材默认生成并选中公司位置地图；Google Street View 和 Tavily 办公室/街景图会补充为后续候选。v2/v3 默认编排主要使用 `website_screenshot`、`product_main`、`founder_photo`、`flywheel`、`chart_competitive`、`chart_ecosystem` 等活跃槽位，`office`、`products_other`、`timeline` 保留 DB 行但不再作为 v2/v3 主渲染槽位。候选变体展示在中间主区域，带来源、尺寸、分数和失败原因，默认按 `final_score` 排序；右侧只放生成、重新评分、当前选定、导入/上传和 SVG 渲染操作。资产写入以 `(company_name, asset_key)` 为唯一键，`company_key` 只作为身份归一化补充，不改变唯一键语义。

批量导出 PNG 需要 Node 依赖：

```bash
npm install
node canvas/screenshot.js --company Anthropic --set v3 --base-url http://127.0.0.1:5050
```

`npm install` 同时安装 `echarts@5.6.0`。生成图表预览和 Playwright PNG 渲染使用 `webapp/static/vendor/echarts.min.js` 的本地副本，避免 iframe `srcdoc` 或 `file://` 渲染路径依赖外部 CDN。

默认每张卡会导出 3 张高倍率候选图（`--shots 3 --scale 3`），默认套卡为 `--set v4`；导出新版 7 张卡传 `--set v2`，导出研究增强版 8 张卡传 `--set v3`，导出故事线 7 张卡传 `--set v4`。需要更少或更高倍率可改 `--shots`、`--scale`。

更多架构和运维细节见 [docs/architecture.md](docs/architecture.md)、[docs/runbook.md](docs/runbook.md) 和 [docs/scoring-system.md](docs/scoring-system.md)。新人推荐先读 [docs/project-guide.md](docs/project-guide.md) 了解项目全貌。
