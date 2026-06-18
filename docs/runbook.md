# Runbook

## Setup

```bash
pip install -r requirements.txt
npm install
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
# 证据层 + 规范化实体表（013-030）
python3 db/migrate.py db/research_db.sqlite --only 013_source_documents.sql
python3 db/migrate.py db/research_db.sqlite --only 014_evidence_spans.sql
python3 db/migrate.py db/research_db.sqlite --only 015_field_candidates.sql
python3 db/migrate.py db/research_db.sqlite --only 016_final_card_values.sql
python3 db/migrate.py db/research_db.sqlite --only 017_card_schema.sql
python3 db/migrate.py db/research_db.sqlite --only 018_company_key_fields.sql
python3 db/migrate.py db/final_db.sqlite --only 019_company_key_final_fields.sql
python3 db/migrate.py db/research_db.sqlite --only 020_companies.sql
python3 db/migrate.py db/research_db.sqlite --only 021_products.sql
python3 db/migrate.py db/research_db.sqlite --only 022_metrics.sql
python3 db/migrate.py db/research_db.sqlite --only 023_sectors.sql
python3 db/migrate.py db/research_db.sqlite --only 024_founders.sql
python3 db/migrate.py db/research_db.sqlite --only 025_funding_rounds.sql
python3 db/migrate.py db/research_db.sqlite --only 026_customers.sql
python3 db/migrate.py db/research_db.sqlite --only 027_competitors.sql
python3 db/migrate.py db/research_db.sqlite --only 028_company_analysis.sql
python3 db/migrate.py db/research_db.sqlite --only 029_research_runs.sql
python3 db/migrate.py db/research_db.sqlite --only 030_entity_table_indexes.sql
# 噪音与上下文治理（031-032）
python3 db/migrate.py db/research_db.sqlite --only 031_document_chunks.sql
python3 db/migrate.py db/research_db.sqlite --only 032_packed_context_logs.sql
# 导出审计（033）
python3 db/migrate.py db/research_db.sqlite --only 033_export_runs.sql
# Evidence Pipeline v2（040-044，Goal 二）
python3 db/migrate.py db/research_db.sqlite --only 040_evidence_source_documents.sql
python3 db/migrate.py db/research_db.sqlite --only 041_evidence_items_v2.sql
python3 db/migrate.py db/research_db.sqlite --only 042_field_candidates_v2.sql
python3 db/migrate.py db/research_db.sqlite --only 043_candidate_evidence_map.sql
python3 db/migrate.py db/research_db.sqlite --only 044_final_field_values.sql
# Context Governance v2（045-046，Goal 三）
python3 db/migrate.py db/research_db.sqlite --only 045_document_chunks_v2.sql
python3 db/migrate.py db/research_db.sqlite --only 046_packed_context_logs_v2.sql
# 历史数据迁移（可选）:
# PYTHONPATH=webapp python3 webapp/db/migrate_entities.py db/research_db.sqlite
```

Put secrets in environment variables or the project root `.env`. The app does not read `~/.env`. Do not commit secrets.

Create the local file from the template:

```bash
cp .env.example .env
```

Required for full research:

```bash
DEEPSEEK_API_KEY=sk-...
# Tavily can use either one key or a comma-separated fallback list.
TAVILY_API_KEY=tvly-...
TAVILY_API_KEYS=tvly-...,tvly-...
```

Tavily collection tuning:

```bash
RESEARCH_DEPTH=deep
TAVILY_QUERY_BUDGET_STANDARD=14
TAVILY_QUERY_BUDGET_DEEP=24
TAVILY_RESULTS_PER_QUERY=5
TAVILY_ADAPTIVE_MODE=1
TAVILY_INITIAL_QUERY_LIMIT=10
TAVILY_INITIAL_SEARCH_DEPTH=basic
TAVILY_INITIAL_INCLUDE_RAW_CONTENT=0
TAVILY_ESCALATE_SEARCH_DEPTH=advanced
TAVILY_ESCALATE_INCLUDE_RAW_CONTENT=0
TAVILY_ESCALATE_RAW_CONTENT_INTENTS=market_size,pricing_details,customers,unit_economics
TAVILY_SEARCH_DEPTH=advanced
TAVILY_INCLUDE_RAW_CONTENT=1
TAVILY_CACHE_TTL_SECONDS=86400
COLLECTION_MIN_UNIQUE_URLS=18
COLLECTION_WEBSITE_SUFFICIENT_CHARS=1500
COLLECTION_GAP_QUERY_LIMIT=5
COLLECTION_ENABLE_GAP_REFETCH=1
EVIDENCE_SPAN_BINDING_ENABLED=1
ORCHESTRATOR_ENABLED=0
```

`EVIDENCE_SPAN_BINDING_ENABLED=1` (default) controls posthoc weak evidence binding (confidence <= 0.45, cannot confirm fields). `ORCHESTRATOR_ENABLED=0` (default) gates the multi-agent orchestration stage.

Noise/governance tuning:
```bash
L0_CONTEXT_BUDGET_TOKENS=18000       # L0 input token cap (standard mode; deep=28000)
DOCUMENT_CHUNKING_ENABLED=1           # Enable clean→chunk→rank chain
CONTEXT_PACKER_ENABLED=1              # Enable packed_context packing
RAW_TEXT_IN_LLM_ENABLED=0             # Must stay 0 — blocks raw_text in LLM prompt
POSTHOC_EVIDENCE_WEAK_ONLY=1          # Must stay 1 — blocks posthoc evidence from confirming fields
```

With adaptive mode enabled, the first Tavily pass runs only the initial query slice, evaluates source quality, and escalates missing high-priority intents instead of always spending the full deep budget.

Optional:

```bash
YOUTUBE_API_KEY=...
GOOGLE_MAPS_API_KEY=...     # Optional Street View supplements for the office map asset; https://console.cloud.google.com/apis/library/street-view-image.googleapis.com
PEXELS_API_KEY=...          # https://www.pexels.com/api/ — 200 req/h, supports Chinese keywords
UNSPLASH_ACCESS_KEY=...     # https://unsplash.com/developers — 50 req/h, English keywords
IMAGE_API_KEY=sk-...
IMAGE_API_URL=https://api.openai.com/v1/images/generations
FLASK_PORT=5050
DB_PATH_RESEARCH=/absolute/path/to/research_db.sqlite
DB_PATH_FINAL=/absolute/path/to/final_db.sqlite
DB_PATH_ASSETS=/absolute/path/to/assets_db.sqlite
DB_PATH_COMPOSITION=/absolute/path/to/composition_db.sqlite
DB_PATH_TEMPLATE=/absolute/path/to/template_db.sqlite
IMAGES_DIR=/absolute/path/to/images
PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/chromium
SCREENSHOT_PROVIDER=local
SCREENSHOT_API_URL=
SCREENSHOT_API_KEY=
```

`IMAGE_API_KEY` and `IMAGE_API_URL` are defaults for image generation. The card workbench can also send a one-off `image_api_url` and `image_api_key` to `/api/generate-image`; the one-off API key is not persisted or returned.

`SCREENSHOT_PROVIDER=local` uses Playwright. Other screenshot API settings are reserved for later adapters and are not required for the current path.

## Start

```bash
cd webapp
python3 app.py
```

Open:

```text
http://127.0.0.1:5050/
```

If port 5050 is occupied:

```bash
cd webapp
FLASK_PORT=5051 python3 app.py
```

## Smoke Tests

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile webapp/*.py
python3 db/migrate.py --help
node canvas/screenshot.js --help
```

Chart runtime:

```bash
test -s webapp/static/vendor/echarts.min.js
node -e "console.log(require('./package.json').dependencies.echarts)"
```

Expected dependency line is `^5.6.0`. The vendor file is copied from `node_modules/echarts/dist/echarts.min.js` and is used for inline chart rendering.

Prompt loading:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "webapp")
from deepseek_client import load_prompt
for name in ["layer0-cleaner", "layer1-hv-analysis", "layer2-business", "layer3-field-extraction",
             "layer3-group-a-technical", "layer3-group-b-competitive", "layer3-group-c-business",
             "split-text"]:
    print(name, len(load_prompt(name)))
print("ecosystem_niche field split from moat — see prompts/layer3-field-extraction.md")
PY
```

Field-resolution audit:

```bash
python3 scripts/operating_metrics_audit.py Anthropic
python3 scripts/card_field_mapping_audit.py Anthropic
python3 scripts/card_content_coverage_check.py --company Anthropic
```

`operating_metrics_audit.py` lists TAM/SAM/SOM, ARR/MRR, users, retention/churn, CAC/LTV, gross margin, burn, and runway values with source hints when available. Missing private metrics should stay `unavailable` unless a reliable source explicitly discloses them.

Check duplicate final fields:

```bash
sqlite3 db/final_db.sqlite \
"SELECT company_name, card_index, field_name, COUNT(*) FROM final_content GROUP BY company_name, card_index, field_name HAVING COUNT(*) > 1;"
```

Expected output is empty.

## Start Research By API

```bash
curl -X POST http://127.0.0.1:5050/api/research/start \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Anthropic","company_url":"https://www.anthropic.com"}'
```

Response:

```json
{"job_id":"abc123","status":"running"}
```

Poll:

```bash
curl http://127.0.0.1:5050/api/research/status/<job_id>
```

Read result:

```bash
curl http://127.0.0.1:5050/api/research/Anthropic
```

Open finalization desk (with card set parameter):

```text
http://127.0.0.1:5050/editor?company=Anthropic&set=v3
```

Open layout center:

```text
http://127.0.0.1:5050/layout?company=Anthropic&set=v3
```

Open image studio directly (standalone):

```text
http://127.0.0.1:5050/image-studio/?company=Anthropic
```

The image studio is also embedded in the editor via the left-side "图片定稿" accordion section; in embed mode it hides its top bar and slot overview panel. Standalone layout: left slot overview, middle preview/search toggle + toolbar (search, recollect, AI gen, upload, URL import), right 2-column candidate thumbnails + "确定图片" confirm button. Candidate thumbnails show source, dimensions, `final_score`, previewed/selected state, and `reject_reason`.

The finalization desk uses the flow: 卡片设置 (card settings) → 文字定稿 (text finalization) → 图片定稿 (image finalization) → 进入排版 (layout). The first three sections are mutually exclusive panels that occupy the right work area; “进入排版” is a fixed button at the bottom of the left rail. The old per-card content editing, hook copy, and database field panels have been removed. Text finalization supports adopting content from standard/business/spread versions into editable final fields. v1 card 7 is the competition landscape and card 8 is the summary; v2 has no separate summary card; v3 is an 8-page research-enhanced report set. The spread hook paragraphs (`hook_paragraph_1/2/3`) are research fields and are not written into knowledge cards.

The research desk company table shows finalization progress from `final_fields` as `confirmed/total` field counts. If a company only has legacy `final_content`, the app falls back to legacy card-count progress. The card workbench `返回定稿台` button should return to `/editor?company=<company>` for the currently loaded company.

Export for canvas:

```bash
# Structured JSON for the card renderer
curl "http://127.0.0.1:5050/api/final/export/Anthropic?format=json&set=v3" | python3 -m json.tool

# Open canvas directly with company data
open "http://127.0.0.1:5050/canvas/?company=Anthropic"

# Open one card directly
open "http://127.0.0.1:5050/canvas/card/Anthropic/1"
```

## Layout Center

The layout center lives at `/layout?company=<company>` and is opened from the finalization desk's “进入排版” link. It loads the same `/api/render-data/<company>` contract used by export, then shows card list, template selector, layer list, iframe preview, and right-side property controls.

Common flow:

1. Select a card in the left card list.
2. Choose a template and click “应用” if the card should use a different template.
3. Click a layer. The iframe preview highlights the matching region, and the right panel shows geometry/style controls.
4. For text layers, double-click the highlighted region in the preview. A Markdown textarea opens in-place; edit raw Markdown there.
5. Blur the textarea or press Cmd/Ctrl+Enter to commit. Press Escape to cancel.
6. Click “保存排版” to persist overrides to `/api/layout/<company>/<card_id>`.

The preview iframe is intentionally protected by parent-page hitboxes. Do not remove the hitbox layer or re-enable direct pointer events on the iframe for normal browsing; otherwise browser double-click selection can select the whole card instead of opening the Markdown editor. During Markdown editing, the controller temporarily lets pointer events reach the iframe so the textarea can be focused and edited.

Text edits are saved as region `value` overrides. `canvas/js/template-renderer.js` renders that value through the Markdown parser before falling back to role-matched card fields.

## Card Workbench And PNG Export

The card workbench is an HTML/CSS renderer, not the legacy fabric.js canvas. The left pane shows the current project name as read-only state from `?company=<company>`; use the finalization desk link or URL parameter to switch projects. “卡片每一页” and “图片夹” are mutually exclusive accordions, and each open panel scrolls internally when content is long. The image folder should show Markdown images from finalized cards plus selected `company_assets`, and it also contains the background-watermark upload/clear controls. The middle pane previews a scaled `900 x 1200` card. The right pane shows the current card's full `<style>...</style>` plus `<article class="knowledge-card">...</article>` source with syntax highlighting. Editing the source live-renders into the middle iframe. Use “保存当前页源码” to persist that card's source in browser `localStorage`.

Image generation is accessed through the image studio search panel (AI prompt bar) or the editor's embedded image-studio iframe. The API key is sent only with the generation request and is not persisted.

Batch export:

```bash
# 不带水印
node canvas/screenshot.js \
  --company Anthropic \
  --set v3 \
  --base-url http://127.0.0.1:5050 \
  --out output/cards/Anthropic \
  --shots 3 \
  --scale 3

# 带背景水印图片
node canvas/screenshot.js \
  --company Anthropic \
  --set v3 \
  --base-url http://127.0.0.1:5050 \
  --out output/cards/Anthropic \
  --bg-image /path/to/watermark.png \
  --shots 3 \
  --scale 3

# 带参数覆盖（从 param-editor 导出的 JSON）
node canvas/screenshot.js \
  --company Anthropic \
  --set v3 \
  --base-url http://127.0.0.1:5050 \
  --params-file /path/to/card-params.json \
  --shots 3 \
  --scale 3
```

`--set` 控制导出的套卡，默认 `v1`；导出新版 7 张卡时传 `--set v2`，导出研究增强版 8 张卡时传 `--set v3`。单卡页面会把 `?set=` 透传到 `/api/render-data/<company>/<card_id>`，因此动态 ID（如 `v2_card_01`、`v3_card_01`）可以直接截图导出。`--shots` 控制每张卡导出几张候选图；`--scale` 控制 Puppeteer 的 `deviceScaleFactor`，数值越高图片越清晰、文件越大。默认是 `--shots 3 --scale 3`。

v3 report bundle export:

```bash
curl "http://127.0.0.1:5050/api/final/export/Anthropic?set=v3&format=bundle" | python3 -m json.tool
curl "http://127.0.0.1:5050/api/final/export/Anthropic?set=v3&format=pdf" | python3 -m json.tool
curl "http://127.0.0.1:5050/api/final/export/Anthropic?set=v3&format=notion" | python3 -m json.tool
```
`--params` 和 `--params-file` 接受卡片参数 JSON（字号/颜色/间距覆盖），参数通过 base64 编码注入到卡片页面 URL。

### 生产稳定性检查（Goal 四）

```bash
# Card 内容覆盖率（需 Flask 运行中）
python3 scripts/card_content_coverage_check.py --company Anthropic --set v3

# Asset 覆盖率
python3 scripts/asset_coverage_check.py --company Anthropic --set v3

# 多公司导出回归（需 Flask + Puppeteer）
python3 scripts/export_regression.py --companies Anthropic OpenAI --set v3
```

Asset collection and infographic generation:

```bash
# Trigger auto-collection (active slots plus legacy office/products_other compatibility slots)
curl -X POST http://127.0.0.1:5050/api/assets/collect/Anthropic

# View all assets
curl http://127.0.0.1:5050/api/assets/Anthropic | python3 -m json.tool

# Regenerate and select the office company location map
curl -X POST http://127.0.0.1:5050/api/image-studio/Anthropic/office/generate-map

# Re-score candidates and auto-select the highest scored usable image
curl -X POST http://127.0.0.1:5050/api/image-studio/Anthropic/product_main/rescore

# Flywheel and timeline infographics are auto-generated on card confirm (card 3/6).
# Manual generation via API:
curl -X POST http://127.0.0.1:5050/api/image-studio/Anthropic/flywheel/render-svg \
  -H "Content-Type: application/json" \
  -d '{"template_id":"flywheel_circular","params":{"radius":200,"accent_color":"#29B8D4","label_size":16}}'

# Generate competitive landscape scatter plot
curl -X POST http://127.0.0.1:5050/api/media/Anthropic/chart_competitive/generate \
  -H "Content-Type: application/json" \
  -d '{}'

# Generate AI stack positioning scatter plot
curl -X POST http://127.0.0.1:5050/api/media/Anthropic/chart_ecosystem/generate \
  -H "Content-Type: application/json" \
  -d '{}'

# Upload a local Python SVG template (localhost only)
curl -X POST http://127.0.0.1:5050/api/svg-templates/upload \
  -H "X-Template-Upload-Intent: local-dev" \
  -F "file=@/absolute/path/to/template.py"

# Preview a template without selecting it
curl -X POST http://127.0.0.1:5050/api/svg-templates/preview \
  -H "Content-Type: application/json" \
  -d '{"template_id":"flywheel_circular","params":{"radius":200}}'

# Generate a card image and register it in company_assets
curl -X POST http://127.0.0.1:5050/api/generate-image \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Anthropic","field_name":"card_1_image","prompt":"...","asset_key":"logo"}'
```

Delete a company and all its data (irreversible):

```bash
curl -X DELETE http://127.0.0.1:5050/api/research/Anthropic
```

Response lists deleted row counts per table plus images directory status.

Check job persistence across restarts:

```bash
sqlite3 db/research_db.sqlite "SELECT job_id, status, stage FROM research_jobs ORDER BY created_at DESC LIMIT 5;"
```

## Troubleshooting

- Empty or non-JSON request to `/api/research/start` should return 400 with `缺少 company_name 或 company_url`.
- If Tavily returns a plan usage limit or quota error, put multiple keys in project `.env` as `TAVILY_API_KEYS=key1,key2,key3` and restart Flask. The pipeline tries the next key for Tavily 429/432 quota responses.
- If Tavily shows `等待 / 0条 / 等待采集` for a long time, confirm the Flask process is restarted on code containing incremental Tavily progress. Deep plans default to 24 planned queries, adaptive mode initially runs 10, and the expected status during collection is `采集中` with `N/total 组查询`.
- If a research job fails at L3, no partial all-missing record should be written.
- If spread hook copy is missing, inspect `hook_paragraph_1/2/3` through `GET /api/research/<company>/<version>` or `GET /api/company/<company>/all-fields`. These fields are no longer edited through a dedicated left-side panel and are not written into knowledge cards.
- If generated images do not display, confirm `/images/<filename>` returns 200 and `IMAGES_DIR` points to the saved image directory. Asset APIs normalize absolute local image paths to `/images/...`; stale DB rows with raw absolute paths can be fixed by reselecting or reimporting the variant.
- If the image folder is empty, check that assets have been auto-collected (triggered after research completes) or manually recollected via the image studio toolbar "全部重新采集" / "当页重新采集" buttons. "当页重新采集" passes `?asset_key=` to collect only the current slot. Asset images from `company_assets` with `status=ready` are displayed first.
- If a slot has variants but no good final image, open image-studio and sort by score. Rejected candidates keep a visible `reject_reason`; click “重新评分” after changing scoring rules or manually importing better candidates.
- If the background watermark is missing, open “图片夹”, upload a local image again, and confirm browser `localStorage` is available for `aistartups_bg_image`.
- If image generation fails from image studio, check the AI generation request's runtime API URL/API Key first, then the environment `IMAGE_API_URL` and `IMAGE_API_KEY`.
- If flywheel or timeline infographic generation fails, confirm card 6 or card 3 has been finalized with Markdown content in `final_db`. The infographic pipeline needs the card's markdown to extract structured JSON for SVG rendering.
- If the card workbench opens without a project name, go back through `/editor?company=<company>` or add `?company=<company>` to the canvas URL; the left project label is intentionally not editable.
- If the card preview differs from the source editor, reload `/canvas/?company=<company>` and confirm the current card source was saved in the same browser profile.
- If double-clicking text in `/layout` turns the whole card blue, hard-refresh the page so `/static/js/layout/layout-app.js?v=layout-md-edit` is loaded. The expected behavior is: select a text layer, double-click the cyan highlighted region, and see a Markdown textarea such as `title Markdown`. If the blue selection persists, confirm the `#region-hitboxes` overlay exists above the iframe and `.canvas-stage iframe` still has `pointer-events: none` outside active editing.
- If the template list is empty on first visit, clear `aistartups.templates` from browser localStorage and refresh. Default templates auto-load from `/canvas/default-templates.json`.
- To share templates across machines, use "导入模板" / export the `aistartups.templates` localStorage key as JSON.
- If Tavily / GitHub / YouTube requests time out during research, confirm the proxy is running on the port configured in `.env` (`HTTPS_PROXY`). Timeout values are set in `pipeline.py` (connect/read: Tavily 30s/120s, GitHub 15s/45s, YouTube 15s/45s). Tavily now uses explicit `proxies=` parameter (not just env-var auto-detection).
- If PNG export says Puppeteer is missing, run `npm install` from the project root.
- If imports fail in a new environment, reinstall with `pip install -r requirements.txt`.
- If chart preview or PNG export is blank, confirm `npm install` has run and `webapp/static/vendor/echarts.min.js` exists. Chart preview and Playwright rendering use this local runtime inlined via `_echarts_inline_js()`; CDN access should not be required. If chart renders in Playwright but not in the browser iframe, check: (1) Flask server restarted after `.py` changes, (2) browser hard refresh (Cmd+Shift+R), (3) browser console for JS errors (common: missing comma in graphic array, double-brace in splitArea — validate with `node --check`). Chart CSS uses `position:absolute;inset:0` for iframe compatibility — vw/vh units cause srcdoc iframe collapse.
- If a migration table is missing after schema initialization, run `python3 db/migrate.py <db-path> --only <migration.sql>`. The runner records applied files in `schema_migrations` and skips unchanged migrations on later runs.
- If field-resolution metadata is missing from `GET /api/company/<company>/all-fields`, run migrations `009_evidence_items.sql` and `010_field_resolution.sql`, then rerun research for that company. Old research rows remain readable but may show "暂无分辨率数据".
- `urllib3` may warn about LibreSSL on the system Python. The warning is noisy but was not a blocker in local verification.
- If Playwright fails with "找不到 Chromium 可执行文件", run `playwright install chromium` or set `PLAYWRIGHT_CHROMIUM_PATH` to the chromium binary path. In Docker, install `chromium` via apt and add `--no-sandbox` etc. The pipeline auto-detects macOS/Linux Playwright caches and system chromium.
- If the office map asset fails, confirm outbound access to Nominatim/OpenStreetMap tile hosts and Playwright Chromium. In domestic networks, set `HTTPS_PROXY` in project `.env`; `config.py` does not set proxy automatically.
- If Google Street View images are missing from the office slot, verify the Google Cloud project has the Street View Static API enabled at https://console.cloud.google.com/apis/library/street-view-image.googleapis.com. The API key is configured as `GOOGLE_MAPS_API_KEY` in `.env`. Street View is only a supplemental candidate after the default map.
- If images show in image studio but not in the layout center, check with `GET /api/render-data/<company>?set=v3` that media items have non-empty `url`. If `url` is empty but the variant is selected in image studio, the `company_assets.local_path` may be out of sync with `image_variants.is_selected`. Run `select_variant()` for the affected asset to re-sync, or use the all-fields debug endpoint to inspect raw data.
- Debug: `GET /api/company/<company>/all-fields` returns all research_fields (standard/business/spread) merged with final_fields. Useful for inspecting raw field values, checking which fields are missing per version, and verifying finalization state.
- If image collection fails with `UNIQUE constraint failed: company_assets.company_name, company_assets.asset_key`, check whether old rows have stale `company_key` values. Current `upsert_asset()` repairs same-name/same-slot rows by `id`; restarting Flask and re-running collection should update the row instead of inserting a duplicate.
