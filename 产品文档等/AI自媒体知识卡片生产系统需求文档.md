# AI 自媒体知识卡片生产系统需求文档

版本：v1.0  
日期：2026-06-17  
适用范围：当前本地 Flask + SQLite 版本，覆盖研究台、定稿台、图片定稿台、排版中心、卡片导出与深度研究报告 v3。

## 1. 背景与目标

本项目是一个面向 AI 初创公司研究与公众号知识卡片生产的本地工具链。系统从公司名和官网 URL 出发，自动完成公开资料采集、LLM 研究分析、字段化入库、人工定稿、图片素材定稿、卡片排版和 PNG 导出。

当前系统已从早期的“研究结果转卡片”演进为两类交付物：

1. 知识卡片：支持 `v1` 经典 8 张、`v2` 新版 7 张，以及用户自定义套卡。
2. 深度研究报告：支持 `v3` 研究增强版 8 页字段体系，并能导出 Markdown / PDF / Notion payload 所需结构。

本需求文档的目标是补齐当前项目的产品级需求描述，明确主流程、功能边界、数据要求、成本约束和验收标准，作为后续开发、测试和产品迭代的统一依据。

## 2. 产品定位

一句话定位：

输入一家 AI 公司，系统自动生成可核查、可定稿、可排版、可导出的公众号知识卡片与深度研究报告。

核心价值：

- 降低单家公司研究和卡片制作的时间成本。
- 用字段化数据替代散乱长文，便于复用、审计和多套卡渲染。
- 用证据池和字段分辨率避免 LLM 猜数，公开事实与不可得指标明确区分。
- 让文字定稿、图片定稿、排版调整分离，减少互相干扰。
- 在 Tavily、DeepSeek、图片 API 成本可控的前提下保持研究质量。

## 3. 用户与使用场景

### 3.1 目标用户

- AI 自媒体作者：需要快速研究 AI 初创公司并产出公众号卡片。
- 内容编辑：需要在自动研究结果上做事实核查、措辞定稿和结构调整。
- 设计/排版执行者：需要选择模板、调整图层、导出 PNG。
- 研究维护者：需要检查字段证据、缺口、来源状态和成本。

### 3.2 典型场景

1. 研究一家公司并制作 v2 公众号卡片。
2. 对同一家公司切换 v1/v2 套卡，复用同一组定稿字段。
3. 生成 v3 深度研究报告，保留字段类型、证据来源和导出结构。
4. 图片自动采集失败后，在图片定稿台手动搜索、上传或 AI 生成补齐素材。
5. 在排版中心对单张卡片的文字、位置、尺寸、颜色做精修后导出 PNG。

## 4. 范围

### 4.1 本期范围

- 本地 Web 应用启动和访问。
- 研究任务创建、进度轮询、取消和状态恢复。
- Tavily / GitHub / YouTube / 官网四路采集。
- DeepSeek L0-L3 研究分析与三版本输出。
- 证据池、字段分辨率、缺口审计。
- v1/v2 卡片编排与 final fields 定稿。
- v3 深度研究字段、卡片配置和导出结构。
- 图片素材候选池、评分、确认。
- SVG/ECharts 图表生成和截图导出。
- HTML/CSS 卡片制作台与排版中心。
- Puppeteer 批量导出 PNG。

### 4.2 非目标

- 不把 n8n 作为研究主流程。
- 不引入 React/Vue 重写前端。
- 不使用 ORM 替代 sqlite3。
- 不把用户目录 `~/.env` 作为配置来源。
- 不把 API Key、token、私钥写入代码、测试、日志或文档。
- 不为了填满字段让 LLM 猜测私有运营指标。
- 不把图片搜索第一张结果直接作为最终图。

## 5. 端到端流程

```text
研究台(/)
  -> 四路采集 + LLM 分析 + 字段入库 + 图片候选池
定稿台(/editor)
  -> 卡片设置 -> 文字定稿 -> 图片定稿
排版中心(/layout) 或卡片制作台(/canvas)
  -> 模板选择 -> 图层调整 -> 单卡预览
导出
  -> PNG / Markdown / JSON / v3 报告结构
```

### 5.1 研究台

用户输入：

- `company_name`：必填，公司展示名。
- `company_url`：建议填写，用于官网抓取、域名识别和实体校验。

系统行为：

- 创建研究任务并返回 `job_id`。
- 前端轮询任务状态。
- 展示 Tavily、GitHub、YouTube、官网抓取四条链路的状态、数量和失败原因。
- 公司库中一次只展开一家公司的研究信息。
- 研究完成后允许进入定稿台。

验收标准：

- `POST /api/research/start` 返回 `job_id` 和 `running` 状态。
- `GET /api/research/status/<job_id>` 能在 Flask 重启后从数据库回读任务状态。
- 研究台能展示各采集源的 `ok / skipped / warning / failed` 状态和数量。
- 取消任务后不继续写入假成功记录。

### 5.2 研究采集与成本策略

采集源：

- Tavily：公司公开网页、新闻、市场规模、客户、定价、竞争等。
- GitHub：仓库、README、技术痕迹。
- YouTube：创始人访谈、产品演示、公开视频。
- 官网：本地 trafilatura 抓取，不依赖 Firecrawl API。

Tavily 默认策略：

- 支持 `TAVILY_API_KEYS` 多 Key 轮换，额度限制时自动尝试下一个 Key。
- 默认启用自适应采集：首轮少量 `basic` 查询，不请求 `raw_content`。
- 首轮采集后评估唯一 URL、官网正文长度、关键 intent 覆盖。
- 如果证据不足，只对缺口关键 intent 升级到 `advanced`。
- `raw_content` 只对高价值 intent 请求，默认包括 `market_size`、`pricing_details`、`customers`、`unit_economics`。
- L3 后 gap refetch 按缺口优先级补采，默认只取前 5 组。
- 查询缓存需要区分 query、search_depth、include_raw_content、max_results。

成本要求：

- 单次研究目标成本：低于 0.20 美元。
- Tavily 请求数应随质量动态调整，不固定满额消耗。
- YouTube、图片生成等可选能力缺 Key 时应降级，不阻断主流程。

验收标准：

- 首轮 Tavily 查询数可通过配置控制。
- 证据充足时不会进入 advanced 补采。
- 证据不足时只补关键缺口，不全量重跑。
- 研究状态中能看到 Tavily 查询进度和补采结果。

### 5.3 LLM 分析与字段提取

模型要求：

- 所有 LLM 调用使用 DeepSeek V4 Pro。
- Prompt 文件位于 `prompts/`。

分析流程：

- L0：信息清洗。
- L1：横纵分析。
- L2：商业结构分析。
- L3：字段提取，生成 `standard`、`business`、`spread` 三个版本。

字段规则：

- L3 任一版本失败，任务失败，不写入假成功记录。
- 创始人 `founder_edu`、`founder_achievement` 缺失时，在 L3 主流程内重试，不使用后置补抓。
- 竞争评分枚举字段使用三层解耦：
  - 规则层：`field_rules.py`
  - LLM 三组：`layer3-group-a/b/c`
  - Pydantic 验证：`field_validator.py`
- 关键字段可多数投票。

验收标准：

- 研究成功后至少写入三版本 research 记录。
- `research_fields` 能按公司、版本、字段拆分存储。
- 枚举字段非法值不能进入评分公式。
- 私有运营指标缺公开证据时标记 unavailable 或 manual_needed，而不是编造。

## 6. 定稿需求

### 6.1 定稿台信息架构

定稿台左侧固定结构：

1. 卡片设置
2. 文字定稿
3. 图片定稿
4. 进入排版

交互要求：

- 前三个面板互斥显示，占据右侧主区域。
- “进入排版”是左侧底部固定按钮。
- 顶部可切换 `v1` / `v2` 套卡。
- 旧版内容定稿、钩子文案、数据库字段面板不作为主流程入口。

### 6.2 文字定稿

数据要求：

- 定稿保存到 `final_fields`。
- 唯一键为 `(company_name, field_key)`。
- 不绑定卡片索引。
- 可从 `standard`、`business`、`spread` 三版本采用字段内容。
- `hook_paragraph_1/2/3` 是普通 research 字段，不写入知识卡片。

验收标准：

- 保存同一字段时更新而不是插入重复行。
- 公司库定稿进度优先读取 `final_fields` 的 confirmed/total。
- 旧 `final_content` 只作为兼容回退。

### 6.3 卡片设置

系统支持：

- `v1` 经典 8 张。
- `v2` 新版 7 张。
- `v3` 研究增强版 8 页报告结构。
- 用户自定义套卡。

要求：

- 每家公司按 `card_set_key` 独立维护卡片编排。
- 卡片内容由字段和素材引用组成，不直接绑定旧 card_index 写死逻辑。
- 删除或新增卡片不得影响其他套卡。

## 7. 卡片与报告规格

### 7.1 v1 经典 8 张

| 卡片 | 主题 |
| --- | --- |
| card_1 | 首页 |
| card_2 | 公司介绍 |
| card_3 | 发展沿袭 |
| card_4 | 主产品 |
| card_5 | 其他产品 |
| card_6 | 商业模式 |
| card_7 | 竞争格局 |
| card_8 | 总结 |

### 7.2 v2 新版 7 张

| 卡片 | 主题 |
| --- | --- |
| card_1 | 封面 |
| card_2 | 公司概览 |
| card_3 | 生态位与变现 |
| card_4 | 创始人与团队 |
| card_5 | 核心客户 |
| card_6 | GTM 与增长 |
| card_7 | 竞争格局 |

### 7.3 v3 深度研究报告 8 页

| 页码 | 主题 | 关键字段 |
| --- | --- | --- |
| 1 | 封面 | `company_name`, `company_type` |
| 2 | 公司简介 | 市场格局、市场规模、TAM、地点、成立时间、融资、行业定位 |
| 3 | 主产品 | 产品名、痛点、核心功能、玩法、技术栈、MAU、留存、定价 |
| 4 | 创始团队 | 创始人、教育、经历、成就、团队规模、团队亮点 |
| 5 | 用户群体 | ICP、客户细分、客户名称、选择理由、证据 |
| 6 | 公司能力分析 | 生态位、变现能力、LTV、CAC、LTV/CAC |
| 7 | 增长与 GTM | 增长策略、GTM、冷启动、飞轮、获客渠道 |
| 8 | 竞争态势 | Top3 竞品、竞争位置、错位机会、竞争优势 |

验收标准：

- v3 字段类型、默认值、索引由迁移文件覆盖。
- v3 `final_fields` 支持 `card_set_key`、`page_no`、`block_key`、`block_type`、`render_json`、`export_targets`。
- v3 Markdown 能渲染所有页面关键字段。
- v3 导出结构支持 Markdown、PDF、Notion 三类目标。

## 8. 图片与图表需求

### 8.1 资产槽位

素材通过 `company_assets` 和 `image_variants` 管理。`company_assets` 唯一键保持 `(company_name, asset_key)`，`company_key` 仅用于身份匹配和旧行修复。

核心资产：

- `logo`
- `website_screenshot`
- `founder_photo`
- `office`
- `product_main`
- `products_other`
- `competitors`
- `competitors_logo_strip`
- `flywheel`
- `timeline`
- `chart_competitive`
- `chart_ecosystem`

要求：

- 写资产必须走 `upsert_asset` / `select_variant`。
- 图片自动采集必须进入候选池，下载后做质量检测、评分和失败原因记录。
- Tavily 图片不允许第一张直接当最终图。
- 搜不到真实图片时标记 failed，进入图片定稿台人工补齐。

### 8.2 图片定稿台

图片类槽位：

- 三栏布局。
- 中间栏支持预览/搜索切换。
- 下部工具栏包含搜索、重新采集、AI 生图、上传、URL 导入。
- 右侧展示候选图、来源、尺寸、分数、失败原因和确定按钮。

图表类槽位：

- 中间 iframe 实时预览。
- 底部参数 bar。
- 右侧代码/操作区。
- 无普通图片搜索框。

### 8.3 图表生成

要求：

- 飞轮和时间线使用本地 SVG 模板渲染。
- `chart_competitive` 和 `chart_ecosystem` 使用本地 ECharts。
- ECharts runtime 使用 `webapp/static/vendor/echarts.min.js`，不依赖 CDN。
- 图表导出使用 Playwright 2x scale。
- v2 图表坐标使用 0-10 绝对值，不做组内归一化。

验收标准：

- 图表预览和导出在离线 CDN 环境下可用。
- 导出的 PNG 尺寸和画布比例稳定。
- 目标公司高亮，竞品降权，全员标签展示。

## 9. 排版与导出需求

### 9.1 排版中心

入口：

```text
/layout?company=<公司名>&set=v1|v2
```

要求：

- 左侧选择卡片和模板。
- 中间 iframe 预览。
- 父页面透明 hitbox 接管图层点击。
- 右侧属性面板调整位置、尺寸、字体、颜色。
- 双击文字图层时在 iframe 内打开 Markdown textarea。
- 文字 region 的 `value` override 优先于原字段内容。

验收标准：

- 保存布局后刷新页面仍能恢复 override。
- Markdown 的 `#`、`##`、`**bold**` 能正确渲染。
- 不出现浏览器原生文本选区干扰图层编辑。

### 9.2 卡片制作台

入口：

```text
/canvas/?company=<公司名>
```

要求：

- 左侧公司名只读，不恢复可输入公司名框。
- 返回按钮回到 `/editor?company=<公司名>`。
- 主路径使用 HTML/CSS + iframe，不使用 fabric.js。
- 右侧显示当前页完整 HTML+CSS 并实时渲染。
- 模板系统使用 `localStorage` key `aistartups.templates`。
- Markdown 解析保留远程/本地图片 URL。

### 9.3 导出

PNG 导出：

```bash
node canvas/screenshot.js --company <公司名> --set v2 --base-url http://127.0.0.1:5050
```

要求：

- 支持 `v1` 和 `v2`。
- 单卡页面与工作台使用同一份 render-data。
- 导出时读取已选定的 image-studio 变体。
- 默认导出 3:4 卡片 PNG。

## 10. 数据与配置需求

### 10.1 数据库

当前 SQLite 数据库职责：

| 数据库 | 职责 |
| --- | --- |
| `research_db.sqlite` | 研究记录、任务状态、字段池、证据池、字段分辨率 |
| `final_db.sqlite` | 人工定稿字段和旧版兼容内容 |
| `assets_db.sqlite` | 图片资产槽位和候选池 |
| `composition_db.sqlite` | 卡片编排 |
| `template_db.sqlite` | 模板和布局实例 |

要求：

- 迁移使用 `db/migrate.py` 和 `schema_migrations` 幂等记录。
- 不在启动路径手工重复 `executescript` 迁移文件。
- SQLite 访问使用标准库 `sqlite3`，不引入 ORM。

### 10.2 环境变量

读取顺序：

```text
系统环境变量 > 项目根目录 .env
```

要求：

- 不读取 `~/.env`。
- 不在日志和响应中回显 API Key。
- 国内网络访问 Tavily / YouTube 时可通过项目 `.env` 配置 `HTTPS_PROXY`。

关键变量：

- `DEEPSEEK_API_KEY`
- `TAVILY_API_KEY` / `TAVILY_API_KEYS`
- `YOUTUBE_API_KEY`
- `PEXELS_API_KEY`
- `UNSPLASH_ACCESS_KEY`
- `IMAGE_API_KEY`
- `IMAGE_API_URL`
- `FLASK_PORT`

## 11. 非功能需求

性能：

- 研究采集应并行执行，避免单源阻塞全流程。
- Tavily 长队列应按 query 增量上报进度。
- 页面模板修改后 Flask 自动重载。

可靠性：

- 任一采集源失败不应直接导致整条研究失败，除非 L3 必要字段提取失败。
- L3 任一版本字段提取失败时，任务失败且不写假成功。
- 图片采集失败应记录失败原因并允许人工补齐。

安全：

- 本地 Python SVG 模板上传只允许本机请求，并要求 `X-Template-Upload-Intent: local-dev`。
- 图片 API 临时 Key 不写入 localStorage。
- 公司名和图片路径片段统一使用 `safe_path_segment`。

可维护性：

- 前端保持 Vanilla JS + CDN/本地 vendor。
- CSS 共享变量在 `webapp/static/css/gzh2-base.css`。
- `editor.css` 不重复定义 `:root` 和 `.btn` 基类。
- 共享业务逻辑优先放入 `services/`、`repositories/`、`webapp/research/`。

## 12. 验收清单

### 12.1 研究链路

- [ ] 可创建研究任务并轮询状态。
- [ ] Tavily/GitHub/YouTube/官网状态可见。
- [ ] Tavily 支持多 Key、缓存、自适应升级和 gap refetch 前 5 组。
- [ ] 研究成功写入三版本记录和字段池。
- [ ] L3 失败不写假成功。
- [ ] 字段分辨率能区分 confirmed/derived/proxy/unavailable/manual_needed/not_applicable。

### 12.2 定稿链路

- [ ] 卡片设置、文字定稿、图片定稿互斥展示。
- [ ] final_fields 按 `(company_name, field_key)` 保存。
- [ ] 公司库优先显示 final_fields 进度。
- [ ] v1/v2 套卡可切换且互不覆盖。
- [ ] v3 字段可用于研究报告导出。

### 12.3 图片链路

- [ ] 自动采集进入候选池。
- [ ] 候选图有质量分、来源分、最终分和失败原因。
- [ ] 选图写回 company_assets。
- [ ] 图表类槽位用 iframe 预览和参数区，不混入普通搜索 UI。
- [ ] ECharts 图表不依赖外部 CDN。

### 12.4 排版导出

- [ ] 排版中心可选卡、选模板、选图层、保存 override。
- [ ] 双击文字图层可编辑 Markdown。
- [ ] 卡片制作台返回当前公司定稿台。
- [ ] PNG 批量导出读取当前套卡和选定资产。

### 12.5 回归验证

推荐命令：

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile webapp/*.py webapp/services/*.py
python3 db/migrate.py --help
node canvas/screenshot.js --help
```

## 13. 迭代优先级

P0：

- 保证研究主链路成功率和失败可见性。
- 控制 Tavily 成本，完成自适应采集和缺口补采。
- 保证 final_fields、company_assets、image_variants 的唯一键和写入路径稳定。
- 保证 v1/v2 卡片导出不回退。

P1：

- 完善 v3 深度研究报告的前端入口和导出体验。
- 优化字段证据展示和人工确认体验。
- 强化图片定稿台对失败原因、版权信息、来源可信度的展示。
- 增加单次研究成本估算面板。

P2：

- 增加更多用户自定义套卡模板。
- 增加批量研究队列和批量导出。
- 增加报告版本对比和字段变更历史。

## 14. 风险与约束

- Tavily、YouTube、图片生成 API 成本与额度不稳定，需要动态降级。
- 部分公司公开信息不足，运营指标不能强行填满。
- 图片版权和可用性需要候选池与人工确认兜底。
- 多套卡共用字段时，字段含义变更可能影响旧套卡，需要通过字段名和 manifest 控制。
- 本地 Playwright 截图依赖浏览器环境，CI 中部分测试需显式启用。

## 15. 成功标准

一次标准研究应满足：

- 用户能从公司名和官网启动研究，并看到清晰进度。
- 研究完成后，字段、证据、图片候选、定稿入口均可追溯。
- v2 卡片可以完成文字定稿、图片定稿、排版并导出 PNG。
- v3 报告字段可以按页面结构导出 Markdown/PDF/Notion 所需数据。
- 单次研究 Tavily 消耗随证据质量动态调整，默认目标成本低于 0.20 美元。
- 自动化测试覆盖主流程关键约束，修改后可通过回归命令验证。
