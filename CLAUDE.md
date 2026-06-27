# 同步说明
本文件是面向代理工具的同步副本；修改后请同步更新对应的代理说明文件。

# AI自媒体知识卡片生产系统

## 项目概述
三模块流水线系统：Python研究流水线 → 内容定稿（Flask）→ 知识卡片制作（HTML/CSS画布）

## 目录约定

```
prompts/        — LLM Prompt文件（layer0-3 + layer3-group-a/b/c 三组枚举提取 + layer3-group-facts/market/operating L3拆组 + layer_hook 钩子写作）
market_intelligence/ — 市场情报模块（CLI）：采集→提取→估算→解析市场/财务字段
webapp/         — Flask编辑后台 + 研究流水线（app.py入口）
  research/       — 证据层 + 结构化提取 + 深度优化模块：
                     l0_gate（L0质量门控）、competitive_matrix（L1竞品矩阵）、
                     business_canvas（L2商业模式画布/7 Powers壁垒）、
                     market_data_bridge（市场数据桥接）、time_series（时间序列快照）、
                     industry_benchmarks（行业基准SaaS/B2B/Consumer）、
                     scoring_inference（v2评分枚举推断）、derivation_pass（字段推导）、
                     hook_writer（钩子段落生成）、
                     evidence_extractor、field_resolver、field_status、field_validator
    context/      — 噪音与上下文治理：cleaner、chunker、ranker、packer、token_budget
    adapters/     — 11个SourceAdapter（含scrapling_search、Playwright fallback）
  research_agents/ — 多Agent系统：11 Agent + forum/ + resolvers/ + storage/ + orchestrator
  repositories/  — 数据访问：field_repo、entity_repo（10张规范化实体表CRUD）
  routes/        — API路由：field、card_config、render、media、evidence
  services/      — 服务层：contract_validator、render_assembler、field_service 等
  db/            — 迁移脚本：migrate.py（幂等，含迁移047 market_estimates、049 company_snapshots）
image-studio/   — 图片定稿台（三栏），通过 iframe 嵌入定稿台
canvas/         — HTML/CSS卡片制作台、单卡页面、Puppeteer截图脚本
db/             — SQLite建表SQL和数据库文件 + migrations/
contracts/      — RenderContract schema + asset_keys.json + card_sets/ + fields.json（含confidence_level定义）
scripts/        — 覆盖检查 + 导出回归脚本
tests/          — pytest 回归测试（808 passed）
```

## 日常操作

### 启动服务
```bash
# 必须用 .venv Python 3.12（系统 Python 3.9 缺少 Scrapling 等依赖）
cd webapp && .venv/bin/python3 app.py
# Flask 已配置 TEMPLATES_AUTO_RELOAD=True，模板修改后无需重启
# 访问研究台 http://127.0.0.1:5050/
# 定稿台 http://127.0.0.1:5050/editor?company=<公司名>&set=v1|v2|v3
# 卡片制作台 http://127.0.0.1:5050/canvas/?company=<公司名>
# 排版中心 http://127.0.0.1:5050/layout?company=<公司名>&set=v1|v2|v3
```

### 研究一家公司
```bash
curl -X POST http://127.0.0.1:5050/api/research/start \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Anthropic","company_url":"https://www.anthropic.com"}'
# 返回 {"job_id":"abc123","status":"running"}
```

### 查询研究进度
```bash
curl http://127.0.0.1:5050/api/research/status/<job_id>
```

### 市场情报（Market Intelligence）
```bash
# 完整研究
python -m market_intelligence --company "Cursor" --domain cursor.com --category "AI coding assistant"
# 跳过 Crunchbase（无 Key 时）
python -m market_intelligence --company "Cursor" --domain cursor.com --no-crunchbase --verbose
# 指定输出文件
python -m market_intelligence --company "Cursor" --domain cursor.com -o result.json
```

### 验证
```bash
pytest tests/ -v
python3 -m py_compile webapp/*.py
python3 db/migrate.py --help
node canvas/screenshot.js --help

# 生产稳定性检查（Goal 四）
python3 scripts/card_content_coverage_check.py --company Anthropic --set v3
python3 scripts/asset_coverage_check.py --company Anthropic --set v3
python3 scripts/export_regression.py --companies Anthropic --set v3
```

### 初始化数据库
```bash
sqlite3 db/research_db.sqlite < db/init_research_db.sql
sqlite3 db/final_db.sqlite < db/init_final_db.sql
sqlite3 db/assets_db.sqlite < db/init_assets_db.sql
sqlite3 db/composition_db.sqlite < db/init_composition_db.sql
sqlite3 db/template_db.sqlite < db/init_template_db.sql
```

## 技术约束
- 所有LLM调用使用DeepSeek V4 Pro
- 前端不用React/Vue，Vanilla JS + CDN
- CSS 共享设计系统在 `webapp/static/css/gzh2-base.css`（变量、顶栏、按钮、面板布局）；`editor.css` 只定义研究台/定稿台专属样式，不重复定义 :root 变量和 .btn 基类；image-studio 使用独立的 `studio.css`（变量名不同但颜色值对齐）
- `canvas/` 主路径不用 fabric.js；使用 HTML/CSS 源码编辑器 + iframe 预览，右侧展示当前页完整 HTML+CSS 并实时渲染。左侧含模板系统（全局共享，`localStorage` key `aistartups.templates`，默认模板 JSON 在 `canvas/default-templates.json`）
- 卡片制作台左侧公司名是只读项目状态，来自定稿台跳转或 `?company=<公司名>`；不要恢复可输入公司名框
- 卡片制作台返回按钮应回到当前公司的定稿台 `/editor?company=<公司名>`
- 数据库用sqlite3标准库，不用ORM
- SQLite 迁移使用 `db/migrate.py`，通过 `schema_migrations` 幂等记录已执行 SQL；不要在启动路径手工重复 `executescript` 迁移文件
- 规范化实体表（companies/products/metrics/sectors/founders/funding_rounds/customers/competitors/company_analysis/research_runs）通过迁移 020-030 创建，CRUD 统一走 `webapp/repositories/entity_repo.py`；不要直接写 SQL 操作这些表
- 证据层：采集结果先入 `source_documents`（document_store），经 `document_cleaner` 清洗 → `document_chunker` 切块 → `evidence_ranker` 五维打分 → `_extract_evidence_spans_from_chunks` 预抽取 evidence_spans（必须在 LLM 前）→ `context_packer` 按 token 预算打包（L0 <= 18,000）→ 仅 packed_context 进入 LLM；`_bind_posthoc_weak_evidence` 仅做事后弱绑定（confidence <= 0.45，created_by_agent="posthoc_weak_matcher"，不得让字段 confirmed）。chunk_type 含 `product_feature`（features/capabilities/agents/extension/gateway 等关键词），`unknown` 不再默认 `is_noise=1`。evidence_ranker 的 `_FIELD_SEMANTIC_KEYWORDS` 为 `product_core_features` 等 11 个字段注入语义关键词提升 `field_relevance_score`
- 字段状态枚举：confirmed | derived | proxy | industry_avg | llm_extracted | manual_needed | unavailable | not_applicable | conflict | draft | hidden。LTV/CAC 四级降级：confirmed → proxy → industry_avg（标注"不代表公司披露"）→ unavailable
- 字段占位值：`"" | 暂缺 | 待研究数据 | None | null | NULL | [] | {}` 均视为不可用。`"待研究数据"` 不出现在 render-data 的 item.value 中。缺失字段 status=manual_needed/unavailable，display_role fallback 从 `gtm_strategy`/`ecosystem_niche` 提供 ≤200 字参考摘要（不写库，不标 derived/confirmed）
- 写库阶段不在热路径中同步调 LLM（`translate_field_value_if_needed()` 仅记日志）。翻译由采集阶段的 `TRANSLATE_ON_COLLECTION` 负责
- 网页抓取用本地 trafilatura（`webapp/firecrawl_local.py`），不依赖外部 API
- 环境变量只读取系统环境变量和项目根目录 `.env`；不要读取或恢复用户目录 `~/.env`
- Tavily 可用 `TAVILY_API_KEYS` 配置逗号分隔的多 Key，额度限制时自动尝试下一个；不要把真实 Key 写进代码、测试、文档或日志
- Tavily 不作为第一梯队采集源（由 Scrapling + 官网 + GitHub/YouTube 等先跑），只在第一轮采集完成后通过 pre-gap refetch 按阈值自动触发补采。运行时仍走自适应模式：`TAVILY_INITIAL_QUERY_LIMIT=10`（basic）、`TAVILY_CACHE_TTL_SECONDS=86400`；补采触发阈值见下方环境变量
- 成本目标 < $0.20/次研究
- 套卡系统（`card_set_key`）：v1 内置 8 张（经典）、v2 内置 7 张（新版）、v3 内置 8 张（研究增强版）。定稿台顶部切换套卡，卡片设置按套卡独立编排，排版中心和导出同步 `?set=` 参数；`canvas/screenshot.js --set` 支持 v1/v2/v3。v1 卡片7/8 为竞争格局+总结；v2 无独立总结卡；v3 走研究报告字段、Markdown/PDF/Notion bundle 导出。L3 prompt 已将壁垒 `moat` 和生态位 `ecosystem_niche` 拆为独立字段
- 研究主流程不依赖 n8n；不要新增 n8n 工作流作为主路径
- 定稿台主流程：卡片设置 → 文字定稿 → 图片定稿 → 进入排版。旧版内容定稿、钩子文案、数据库字段面板已删除，不再保留兼容入口
- `hook_paragraph_1/2/3` 是 research 表中的字段（可作普通字段使用），不写入知识卡片
- 定稿保存走 `final_fields` 表，按 `(company_name, field_key)` 唯一键；不绑定卡片索引。旧 `final_content` 表仅用于旧版兼容入口
- canvas Markdown 解析必须保留远程/本地 Markdown 图片 URL，并兼容首页、公司介绍、主产品里的无标签正文
- L3 任一版本字段提取失败时，任务应失败且不写入假成功记录
- L3 枚举字段（10个竞争评分维度）改三层解耦：规则层 `field_rules.py`（爬 pricing 页+关键词推断）→ LLM 拆为3组独立调用（prompts/layer3-group-a/b/c）→ Pydantic 验证 `field_validator.py`；关键字段多数投票。不改动 L3 主调用的 45 个非枚举字段提取
- 证据与字段分辨率走 `webapp/research/` + `references/field_manifest.yaml`：公开事实可 confirmed，公式字段 derived，市场规模可 proxy/manual_needed，私有经营指标默认 unavailable，B2B 不适配用户字段标 not_applicable；不要为了填满运营指标让 LLM 猜数。
- 创始人 `founder_edu/founder_achievement` 缺失修复属于 L3 主流程内重试，不要恢复后置补抓流程
- 图片 API Key 可通过环境变量配置，也可在图片定稿台搜索面板 AI 生图时随请求发送；临时 Key 不写入 localStorage 或响应
- 公司名/图片路径片段统一用 `webapp/path_safety.py:safe_path_segment` 消毒；不要在各模块新增不同的路径清理规则
- 公司图片资产通过 `company_assets` 表管理（12 种 `asset_key`：9 个活跃槽位 + `office/products_other/timeline` 三个 v2 起废弃槽位），不用路径约定或 localStorage。采集统一走 `collect_image_variants_pipeline`（含官网首页截图 candidate，不抢 v1/legacy 的 OSM office 默认）。信息图（飞轮/时间线/散点图）走 `infographic.py`：飞轮/时间线用 SVG 模板渲染，散点图用本地 `webapp/static/vendor/echarts.min.js` 内联渲染为 HTML，再由 Playwright 截图（2x scale 高清）；不要恢复 CDN 依赖作为主路径
- 自动图片采集必须走候选池：下载后用 `image_quality.py` 检测、`image_scorer.py` 评分，写入尺寸/分数/失败原因；Tavily 不允许取第一张直接当最终图
- `company_assets` 唯一键仍是 `(company_name, asset_key)`；`company_key` 只用于身份匹配和旧行修复。写资产必须走 `upsert_asset`/`select_variant`，不要直接 INSERT 同槽位。
- v1/legacy 的 `office` 素材默认使用公司位置地图：OSM 瓦片本地拼接 + HTML pin/legend 生成 PNG，并默认选中；Google Street View/Tavily 办公室图只作为后续候选变体，不抢默认选中。v2/v3 主编排不要重新依赖 `office/products_other/timeline`
- 图片定稿台两类槽位两种界面：①采集图片类（logo/website_screenshot/founder_photo/product_main/competitors 等，兼容 office/products_other）→ 三栏布局，中间栏上部预览/搜索切换 + 下部工具栏（搜索/采集/AI生图/上传）；②图表类（flywheel/timeline/chart_competitive/chart_ecosystem）→ 中间栏 iframe 实时预览（ECharts 或 SVG）+ 下部功能区 bar（调参+重置+渲染保存），无搜索框
- 本地 Python SVG 模板上传只允许本机请求并要求 `X-Template-Upload-Intent: local-dev`；不要开放远程上传
- 模板制作（/template-maker）：新建/编辑模板，右上角下拉框选择已有模板进行修改。编辑内置模板时自动创建副本（不修改原内置模板）。保存区分新建（POST）和更新（PATCH）
- chart_competitive/chart_ecosystem 使用本地 ECharts（`webapp/static/vendor/echarts.min.js`）内联渲染为 HTML，通过 `/api/image-studio/.../preview` 实时预览 + Playwright 截图（2x scale，800×600→1600×1200）导出 PNG。v2 改造：0–10 绝对坐标（不做组内归一化）、动态标题给结论。设计规范：light 主题、markArea 象限背景（x=5/y=5 中轴）、目标公司高亮（青色 `#29B8D4` 白边框 2px 固定气泡 22px）、竞品降权（`rgba(27,42,74,0.35)` 14px 气泡）、全员标签展示、ecosystem Y 轴 5 条 category 泳道（分发渠道/垂直应用/中间件层/模型层/基础设施层）+ splitArea 交替背景。前端 workspace-chart.js 只做参数编辑和 iframe 预览，不维护独立的图表逻辑。CSS 不使用 vw/vh（srcdoc iframe 中会坍塌）
- 排版中心（/layout?company=<公司名>&set=v1|v2|v3）：选中卡片→选择模板→点击图层→右侧属性面板调节位置/尺寸/字体/颜色。画布预览由 iframe 渲染，父页面透明 hitbox 接管图层点击，避免浏览器原生文本选区；选中文字图层后双击高亮区域会在 iframe 内打开 Markdown textarea，可编辑原始 Markdown，提交后写入 layout overrides 并跨渲染保持。模板渲染器支持 Markdown（`#`→h1/`##`→h2/`**`→粗体），文字 region 的 `value` override 优先于原字段内容。
- 国内环境访问 Tavily 和 YouTube API 需配 HTTPS_PROXY（在 `.env` 手动配置）。Tavily 使用显式 `proxies=` 传参并支持超时后换 Key；超时配置在 `pipeline.py`
- Pexels（200 req/h，支持中文）和 Unsplash（50 req/h，英文关键词）API Key 通过环境变量配置，用于图片定稿台手动搜索
- 图片自动采集不再使用 Lorem Flickr / Picsum 通用图；搜不到真实图片时标记 `failed`，进入图片定稿台手动补
- 定稿台左侧结构：卡片设置、文字定稿、图片定稿、进入排版。前三个面板点击后占据右侧主区域，互斥切换；「进入排版」是左侧底部固定按钮。旧版内容定稿/钩子文案/数据库字段面板已删除
- 研究台公司库定稿进度优先读取 `final_fields` 的 confirmed/total 字段数；旧 `final_content` 卡片数仅作兼容回退
- 研究台要展示 Tavily/GitHub/YouTube/官网抓取的链路状态与数量；公司库点击一条只展开该公司研究信息，点另一条时其他行折叠
- `EVIDENCE_SPAN_BINDING_ENABLED=1`（默认）控制 posthoc 弱证据绑定；`DOCUMENT_CHUNKING_ENABLED=1`（默认）控制文档清洗+切块+打分；`CONTEXT_PACKER_ENABLED=1`（默认）控制 packed_context 打包；`L0_CONTEXT_BUDGET_TOKENS=18000` 控制 L0 输入 token 上限；`POSTHOC_EVIDENCE_WEAK_ONLY=1`（默认）确保事后绑定不得 confirmed；`ORCHESTRATOR_ENABLED=0`（默认）控制多Agent并行采集；`COLLECTION_ENABLE_GAP_REFETCH=1`（默认）控制 Tavily pre-gap/L3 补采；`COLLECTION_WEBSITE_SUFFICIENT_CHARS=3000`（默认）官网字符数低于此值触发补采；`COLLECTION_MIN_UNIQUE_URLS=10`（默认）Tavily 唯一 URL 低于此值触发补采；`COLLECTION_MIN_INTENTS=2`（默认）Tavily 意图数低于此值触发补采；`TRANSLATE_ON_COLLECTION=1`（默认）控制采集入库前英→中翻译；`TAVILY_SEARCH_DEPTH=basic`（默认）控制 Tavily 首轮搜索深度，补采轮自动使用 advanced
- Evidence API（Goal 二新增）：`/api/evidence/company/<company>`、`/api/evidence/field/<company>/<field_key>`、`/api/evidence/candidate/<candidate_id>`；旧 `/api/evidence/<company_key>/<field_key>` 仍可用
- RenderContract 主出口（Goal 一）：`GET /api/render-data/<company>?set=v3` 返回 `contracts/render_contract.schema.json` 格式的 8 卡结构，由 `webapp/services/render_assembler.py` 组装、`webapp/services/contract_validator.py` 校验
- `LEGACY_CONTEXT_MODE=1` 显式开关绕过 chunk→rank→pack 治理（仅调试用，默认 0）

## 技术约束（补充）

### 开放网页搜索（Scrapling）
- Scrapling 搜索使用 curl-cffi（`scrapling.fetchers.Fetcher`）直接抓取 SERP，不再先 `requests.get` 后 fallback；`webapp/research/scrapling/page_fetcher.py` 中 `fetch_html` 的 auto 模式只使用基础 Fetcher，不串行尝试 DynamicFetcher/StealthyFetcher（headless 太慢）
- **Scrapling 0.4.x 代理**：废弃了环境变量自动检测，必须在 `_fetch_serp_with_scrapling()` 中显式传 `proxy=` 参数（`webapp/research/scrapling/serp_fetcher.py`）。代理仍从 `HTTPS_PROXY`/`HTTP_PROXY` 环境变量读取
- 官网页面抓取回退超时使用 `timeout_seconds`（默认 15s），不再用 `max(timeout_seconds, 60)`（60s 回退会在多 URL 并发时撑爆 300s hard_timeout）
- 默认搜索引擎 Bing + DuckDuckGo（Google 在国内不可达）；可通过 `SCRAPLING_SEARCH_PROVIDERS` 覆盖
- **红线**：`youtube_transcript_adapter.py` 的 `_webapp_dir` 必须是 3 层 `dirname`（`webapp/`），不是 2 层（`webapp/research/`）。2 层会导致本地 `research/scrapling/` 遮蔽 site-packages `scrapling`，Scrapling 全部超时失败
- Scrapling 适配器 hard_timeout 设为 300s；单次抓取最大 URL 数 `SCRAPLING_MAX_URLS_PER_COMPANY` 默认 50
- 补充适配器（github/youtube/producthunt/openbb/companieshouse/sec）同样 hard_timeout=300s、timeout_seconds=30
- Scrapling 需要 Python ≥ 3.10；用 `.venv/bin/python3`（3.12）启动 Flask，不要用系统 python3（3.9）。官网抓取 403 时除 Scrapling 级联外还增加直接 Playwright fallback（`_collect_with_playwright`）
- 新增 ADAPTER_HARD_TIMEOUT_SECONDS 环境变量（默认 120），可在 .env 覆盖为 300

### Tavily 两阶段搜索
- 首轮使用 `basic` 深度（`TAVILY_SEARCH_DEPTH=basic` 或 `TAVILY_INITIAL_SEARCH_DEPTH`）
- 补采轮（pre-gap refetch + L3 gap refetch）自动使用 `advanced` 深度，带 `search_depth: "advanced"` 参数
- Tavily 4 种模式：`ultra-fast` | `fast` | `basic` | `advanced`；`deep` 是 `advanced` 别名

### 采集时翻译
- `TRANSLATE_ON_COLLECTION=1`（默认）：`_persist_source_documents_from_raw()` 入库前逐条中英文检测，非中文批量翻译
- 复用 `deepseek_client.translate_to_chinese()` 和 `_is_predominantly_english()`（CJK vs 拉丁字母占比 >60%→英文）
- 翻译后文本进入 source_documents → 下游清洗/切块/LLM 全部拿到中文，context_packer 的翻译变为空操作

### Market Intelligence 模块
- 独立 CLI 模块：`python -m market_intelligence --company "Cursor" --domain cursor.com`
- 数据流：Collect（Crunchbase/Tavily）→ Extract（LLM+Regex）→ Estimate（Bottom-up TAM）→ Resolve → JSON 输出
- 不变量：LLM 不产生 `confirmed` 状态；找不到数据标 `unavailable`（是有效结论）；采集器不抛异常
- 新表 `market_estimates`（迁移 047）
- API Key：`CRUNCHBASE_API_KEY`（.env）
- 主管道自动触发：`run_pipeline()` 中 MarketDataBridge 检测到 `market_estimates` 无数据时自动 `subprocess.run("python -m market_intelligence ...")`

### 深度优化（2026-06-22 实施）
- **confidence_level** 四级标注（独立于 status）：verified（官方/权威来源）| estimated（代理推算）| benchmark（行业基准）| unavailable（未公开）
- **字段三级采集难度**：Tier 1 公开可采集（web_search+LLM）、Tier 2 代理指标推算（SimilarWeb/GitHub/PH 多源代理）、Tier 3 估算/行业基准（公式推算+基准兜底）。`classify_acquisition_tier()` 在 `field_status.py`
- **L0 质量门控**（`l0_gate.py`）：校验 L0 输出完整性（≥3 key、>500 chars、有内容），不通过阻断下游
- **L1 竞品矩阵**（`competitive_matrix.py`）：Pydantic 校验的结构化 JSON（threat_level、overlap_areas、evidence_snippets），非阻塞（失败回退文本）
- **L2 商业模式画布**（`business_canvas.py`）：Pydantic 校验的 JSON，含 Helmer 7 Powers 8 种壁垒维度 + 6 种增长循环
- **L3 拆组**：原 3582-token 单 prompt 拆为 A（基础事实 15）+ B（市场运营 18）+ C（商业竞争 12），A+B 并行→C 串行（依赖 A+B）
- **MarketDataBridge**（`market_data_bridge.py`）：从 `market_estimates` 表读 TAM/融资数据注入 L3 context，避免重复推断
- **TimeSeriesSnapshotter**（`time_series.py`）：新表 `company_snapshots`（迁移 049），每次研究存字段快照，支持 `diff()` 跨时间对比
- **行业基准**（`industry_benchmarks.py`）：SaaS/B2B/Consumer 三套基准（留存率/LTV/CAC/毛利率），含 `estimate_ltv()` 公式，所有基准输出 `confidence_level="benchmark"` + 免责声明
- **前端置信度标记**：定稿台字段旁显示 `✓ 已验证` / `≈ 估算` / `ⓘ 行业基准` / `— 未公开` 标签
- **token 预算**：L3 拆分后 ~1142 tokens（-68%），详见 `docs/prompt-token-budget.md`

## 参考
- 新人入口：`docs/project-guide.md`
- 全量规格书：`SPEC.md`（1298 行，覆盖全部 21 章节）
- 架构说明：`docs/architecture.md`
- 重构 Spec：`docs/refactor/master_refactor_spec.md`（Goal 一~四 12 PR 全量重构方案）
- 评分体系：`docs/scoring-system.md`
- 卡片规范：`docs/card-spec.md`
- 运行手册：`docs/runbook.md`
- Token 预算：`docs/prompt-token-budget.md`
- 深度优化设计：`docs/superpowers/specs/2026-06-22-depth-optimization-design.md`
- 深度优化计划：`docs/superpowers/plans/2026-06-22-depth-optimization-plan.md`
- 字段→采集方法映射：`references/field_acquisition_map.json`（N:N，117字段×15采集方法）
- v3 卡片字段配置：`contracts/card_sets/v3.json` + `db/init_composition_db.sql`（default_card_configs）保持一致。v3_card_07 含 5 字段：`growth_strategy`、`cold_start`（2026-06-27 取消 deprecated）、`gtm_strategy`、`growth_flywheel`、`acquisition_channels`
- display_role 默认值：`webapp/services/role_defaults.py`（共享模块，card_config_service + render_assembler + card_config_repo 共用）
- 公司列表发现：`get_companies()` 从三个来源发现公司——`research` 宽表 + `research_fields` 表 + `research_jobs` 表（兜底已完成但字段未写入 research_fields 的研究）
