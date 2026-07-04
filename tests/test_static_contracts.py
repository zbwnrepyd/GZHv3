import os
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))


class StaticContractTests(unittest.TestCase):
    def test_canvas_page_uses_html_card_workbench(self):
        with open(os.path.join(ROOT, "canvas", "card-renderer.html"), encoding="utf-8") as f:
            html = f.read()

        self.assertNotIn("fabric.min.js", html)
        self.assertIn('id="card-frame"', html)
        self.assertIn('id="source-editor"', html)
        self.assertIn('id="btn-source-all"', html)
        self.assertIn('id="btn-source-css"', html)
        self.assertIn('id="btn-source-html"', html)
        self.assertIn('id="btn-inspect-source"', html)
        self.assertIn('id="btn-back-research"', html)
        self.assertIn('href="/editor"', html)
        self.assertIn('/editor?company=', html)
        self.assertIn('id="current-company-name"', html)
        self.assertNotIn('id="company-name-input"', html)
        self.assertIn('id="cards-accordion"', html)
        self.assertIn('id="image-folder-accordion"', html)
        self.assertIn('class="left-accordion is-open"', html)
        self.assertIn('class="accordion-trigger"', html)
        self.assertIn('id="image-folder"', html)
        self.assertIn('class="image-folder-tools"', html)
        self.assertIn('id="bg-file-input"', html)
        self.assertIn('id="btn-export-all"', html)
        self.assertLess(html.index('id="image-folder-accordion"'), html.index('id="bg-file-input"'))
        self.assertLess(html.index('id="bg-file-input"'), html.index('id="image-folder"'))
        self.assertLess(html.index('id="image-folder-accordion"'), html.index('id="btn-export-all"'))
        self.assertIn("bindAccordions()", html)
        self.assertIn("data-accordion-target", html)
        self.assertIn("other.classList.remove('is-open')", html)
        self.assertIn("fitFrameToStage(stage, frame)", html)
        self.assertIn("min-width: 0", html)
        self.assertIn("#canvas-stage {\n    position: relative;\n    min-width: 0", html)
        self.assertIn("box-sizing: border-box", html)
        self.assertIn("@media (max-width: 900px)", html)
        self.assertNotIn("min-width: 1220px", html)
        self.assertIn("this.cardLabel(i)", html)
        self.assertIn("js/html-card-renderer.js", html)
        self.assertIn("js/render-data-loader.js", html)
        self.assertIn("js/template-renderer.js", html)
        self.assertIn("RenderDataLoader.load(this.companyName)", html)
        self.assertIn("TemplateRenderer.render(this.currentCardDataWithImage())", html)
        self.assertIn("保存当前启用卡片", html)
        self.assertIn("js/source-editor.js", html)
        self.assertIn("js/export-client.js", html)
        self.assertIn("8: '总结'", html)

        with open(os.path.join(ROOT, "canvas", "js", "source-editor.js"), encoding="utf-8") as f:
            source_editor_js = f.read()
        self.assertIn("signature(defaultSource)", source_editor_js)
        self.assertIn("saved.signature === signature", source_editor_js)
        self.assertIn("viewMode", source_editor_js)
        self.assertIn("splitSource", source_editor_js)
        self.assertIn("showSection", source_editor_js)
        self.assertIn("inspectMode", source_editor_js)
        self.assertIn("installInspectHooks", source_editor_js)
        self.assertIn("locateSourceForElement", source_editor_js)
        self.assertIn("getFullSource", source_editor_js)

    def test_canvas_single_card_page_uses_same_fit_helper(self):
        with open(os.path.join(ROOT, "canvas", "card.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(ROOT, "canvas", "js", "api-loader.js"), encoding="utf-8") as f:
            api_loader_js = f.read()

        self.assertIn("fitCardPage()", html)
        self.assertIn("getBoundingClientRect()", html)
        self.assertIn("translate(-50%, -50%)", html)
        self.assertIn("saved.signature === signature", html)
        self.assertIn("background: #F2F2F2", html)
        self.assertIn("renderCardSource", html)
        self.assertIn("fonts.googleapis.com", html)
        self.assertIn("Bebas+Neue", html)
        self.assertIn("loadResolvedAssetsFromAPI(company)", api_loader_js)
        self.assertIn("cardData._allAssets = assets", api_loader_js)
        self.assertIn("cardData._resolvedCardAssets", api_loader_js)

    def test_layout_center_is_markdown_first_without_layer_panel(self):
        with open(os.path.join(ROOT, "webapp", "templates", "layout.html"), encoding="utf-8") as f:
            layout_html = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "layout", "layout-app.js"), encoding="utf-8") as f:
            layout_js = f.read()

        self.assertIn('id="markdown-editor"', layout_html)
        self.assertIn('id="markdown-toolbar"', layout_html)
        self.assertIn('id="style-panel"', layout_html)
        self.assertIn('id="preview-pane"', layout_html)
        self.assertIn('id="splitter"', layout_html)
        self.assertIn('id="preview-frame-wrap"', layout_html)
        self.assertIn("flex: 0 0 auto", layout_html)
        self.assertIn("grid-template-columns: minmax(360px, 0.58fr) 8px minmax(320px, 0.42fr)", layout_html)
        self.assertIn("grid-template-columns: minmax(320px, 0.58fr) 8px minmax(260px, 0.42fr)", layout_html)
        self.assertIn("grid-template-columns: repeat(8, minmax(64px, 1fr))", layout_html)
        self.assertIn("grid-template-columns: repeat(8, minmax(44px, 1fr))", layout_html)
        self.assertIn("max-height: 72px", layout_html)
        self.assertIn("Markdown 素材", layout_html)
        self.assertIn('aria-label="清除样式"', layout_html)
        self.assertIn("layout-editor-shell", layout_html)
        self.assertNotIn('data-mode="split"', layout_html)
        self.assertNotIn('data-mode="write"', layout_html)
        self.assertNotIn('data-mode="preview"', layout_html)
        self.assertNotIn("write-mode", layout_html)
        self.assertNotIn("preview-mode", layout_html)
        self.assertNotIn('id="layer-list"', layout_html)
        self.assertNotIn('id="property-panel"', layout_html)
        self.assertNotIn("选择图层", layout_html)

        self.assertIn("_markdownByCard", layout_js)
        self.assertIn("_styleByCard", layout_js)
        self.assertIn("_splitRatio: 0.58", layout_js)
        self.assertIn("_renderMarkdownPreview", layout_js)
        self.assertIn("_resolveAssetToken", layout_js)
        self.assertIn("_ensureMediaTokensInMarkdown", layout_js)
        self.assertIn("{{logo}}", layout_js)
        self.assertIn("{{chart_competitive}}", layout_js)
        self.assertIn("_applyStyleToAllCards", layout_js)
        self.assertNotIn("_renderLayerList", layout_js)
        self.assertNotIn("_renderPropertyPanel", layout_js)

    def test_flywheel_chart_workspace_has_stable_layout(self):
        with open(os.path.join(ROOT, "image-studio", "js", "workspace-chart.js"), encoding="utf-8") as f:
            workspace_js = f.read()
        with open(os.path.join(ROOT, "image-studio", "css", "studio.css"), encoding="utf-8") as f:
            studio_css = f.read()

        self.assertIn("flywheel-workspace", workspace_js)
        self.assertIn('id="flywheel-stage-host"', workspace_js)
        self.assertIn("_defaultFlywheelStages()", workspace_js)
        self.assertIn("AI提升产能", workspace_js)
        self.assertNotIn("stageHost.style.cssText", workspace_js)
        self.assertIn(".chart-workspace.flywheel-workspace", studio_css)
        self.assertIn(".flywheel-stage-host", studio_css)
        self.assertIn("grid-template-rows: auto minmax(220px, 1fr) minmax(96px, auto) minmax(150px, 28vh) auto", studio_css)

    def test_v2_card_06_matches_gtm_flywheel_layout(self):
        with open(os.path.join(ROOT, "canvas", "templates", "v2_card_06.html"), encoding="utf-8") as f:
            html = f.read()

        self.assertIn("增长飞轮与GTM策略", html)
        self.assertIn("class=\"flywheel-stage\"", html)
        self.assertIn("white-space: pre-line", html)
        self.assertNotIn("GTM &amp; Growth", html)
        self.assertNotIn("走向市场", html)
        self.assertNotIn("background: var(--bg)", html)

    def test_screenshot_cli_exports_multiple_high_resolution_shots(self):
        with open(os.path.join(ROOT, "canvas", "screenshot.js"), encoding="utf-8") as f:
            script = f.read()

        self.assertIn("--shots", script)
        self.assertIn("--set", script)
        self.assertIn("--scale", script)
        self.assertIn("--shot-delay", script)
        self.assertIn("deviceScaleFactor: args.scale", script)
        self.assertIn("for (let shotIndex = 1; shotIndex <= args.shots; shotIndex += 1)", script)
        self.assertIn("_shot_", script)
        self.assertIn("encodeURIComponent(cardId)", script)
        self.assertIn("safeName(card.card_title || card.card_id)", script)
        self.assertIn("async function resolveFetch()", script)
        self.assertIn("globalThis.fetch", script)
        self.assertIn("?set=${encodeURIComponent(args.set)}", script)
        self.assertIn("buildCardUrl(args.baseUrl, company, cardId, args.set", script)

    def test_editor_api_exposes_research_job_helpers(self):
        with open(os.path.join(ROOT, "webapp", "static", "js", "api.js"), encoding="utf-8") as f:
            api_js = f.read()

        self.assertIn("async startResearch(", api_js)
        self.assertIn("async getResearchStatus(", api_js)
        self.assertIn("async getResearchCard(", api_js)
        self.assertIn("async getFinalStatus(", api_js)

    def test_three_page_spec_static_contract(self):
        with open(os.path.join(ROOT, "webapp", "templates", "index.html"), encoding="utf-8") as f:
            index_html = f.read()
        with open(os.path.join(ROOT, "webapp", "templates", "editor.html"), encoding="utf-8") as f:
            editor_html = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "editor.js"), encoding="utf-8") as f:
            editor_js = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "css", "editor.css"), encoding="utf-8") as f:
            editor_css = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "editor", "card-settings-panel.js"), encoding="utf-8") as f:
            card_settings_js = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "editor", "text-finalize-panel.js"), encoding="utf-8") as f:
            text_finalize_js = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "index.js"), encoding="utf-8") as f:
            index_js = f.read()

        self.assertIn('id="research-desk"', index_html)
        self.assertIn('id="company-table-body"', index_html)
        self.assertIn('id="editor-workbench"', editor_html)
        self.assertIn('data-section="card-settings"', editor_html)
        self.assertIn('data-section="text-finalize"', editor_html)
        self.assertIn('data-section="image"', editor_html)
        self.assertIn('id="btn-go-layout"', editor_html)
        self.assertIn('id="tf-btn-generate-layout-copy"', editor_html)
        self.assertLess(
            editor_html.index('id="tf-btn-generate-layout-copy"'),
            editor_html.index('id="btn-go-layout"'),
        )
        self.assertIn('id="layout-copy-progress-modal"', editor_html)
        self.assertIn('class="editor-goto-layout"', editor_html)
        self.assertNotIn('id="editor-middle-pane"', editor_html)
        self.assertNotIn('id="editor-right-pane"', editor_html)
        self.assertNotIn('id="btn-go-canvas"', editor_html)
        self.assertIn("grid-template-columns: 180px 1fr", editor_css)
        self.assertNotIn("grid-template-columns: 180px 1fr 360px", editor_css)
        self.assertNotIn("editor-middle-pane", editor_js)
        self.assertNotIn("editor-right-pane", editor_js)
        self.assertIn('/static/js/editor/card-settings-panel.js', editor_html)
        self.assertIn('/static/js/editor/text-finalize-panel.js', editor_html)
        self.assertIn("switchSection(section)", editor_js)
        self.assertIn("CardSettingsPanel.init(this.companyName)", editor_js)
        self.assertIn("TextFinalizePanel.init(this.companyName)", editor_js)
        self.assertIn("showCardSettingsMode", editor_js)
        self.assertIn("showTextFinalizeMode", editor_js)
        self.assertIn("showImageMode", editor_js)
        self.assertIn("/api/card-config/", card_settings_js)
        self.assertIn("/api/fields/", text_finalize_js)
        self.assertIn("VERSION_LABELS_TF", text_finalize_js)
        self.assertIn("tf-version-card", text_finalize_js)
        self.assertIn("CARD_COUNT = 8", index_js)
        self.assertIn("${confirmed}/${total}", index_js)
        self.assertNotIn("${confirmed}/7", index_js)
        self.assertNotIn('class="version-radio"', editor_html)
        self.assertNotIn('id="markdown-editor"', editor_html)
        self.assertNotIn('id="field-edit-mini"', editor_html)

    def test_layout_copy_route_uses_deepseek_flash_model(self):
        with open(os.path.join(ROOT, "webapp", "routes", "field_routes.py"), encoding="utf-8") as f:
            routes_py = f.read()

        start = routes_py.index('@bp.route("/fields/<company>/layout-copy"')
        end = routes_py.index("return jsonify({\"status\": \"ok\"", start)
        layout_copy_route = routes_py[start:end]

        self.assertIn("config.DEEPSEEK_FLASH_MODEL", layout_copy_route)
        self.assertNotIn("model=config.DEEPSEEK_MODEL", layout_copy_route)

    def test_failed_research_status_surfaces_error(self):
        with open(os.path.join(ROOT, "webapp", "static", "js", "index.js"), encoding="utf-8") as f:
            index_js = f.read()

        self.assertIn("job.error", index_js)
        self.assertIn("研究失败", index_js)
        self.assertIn("activeJobId", index_js)
        self.assertIn("pollInFlight", index_js)
        self.assertIn("if (btn.disabled || this.activeJobId) return", index_js)
        self.assertIn("this.activeJobId !== jobId || this.pollInFlight", index_js)

    def test_research_desk_surfaces_source_details(self):
        with open(os.path.join(ROOT, "webapp", "templates", "index.html"), encoding="utf-8") as f:
            index_html = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "index.js"), encoding="utf-8") as f:
            index_js = f.read()
        with open(os.path.join(ROOT, "webapp", "app.py"), encoding="utf-8") as f:
            app_py = f.read()
        with open(os.path.join(ROOT, "webapp", "services", "export_service.py"), encoding="utf-8") as f:
            export_service = f.read()

        self.assertIn('id="source-status-grid"', index_html)
        self.assertIn("renderSourceStatus", index_js)
        self.assertIn("job.sources", index_js)
        self.assertIn("collecting: '采集中'", index_js)
        self.assertIn("not_configured: '未配置'", index_js)
        with open(os.path.join(ROOT, "webapp", "static", "css", "editor.css"), encoding="utf-8") as f:
            editor_css = f.read()
        self.assertIn(".source-not_configured", editor_css)
        self.assertIn(".source-not_applicable", editor_css)
        self.assertIn('{**current_sources, **sources}', app_py)
        self.assertNotIn('on_progress("资产采集"', app_py)
        self.assertNotIn("_refetch_founder_fields", app_py)

    def test_research_desk_uses_stable_progress_steps_and_recent_events(self):
        with open(os.path.join(ROOT, "webapp", "templates", "index.html"), encoding="utf-8") as f:
            index_html = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "index.js"), encoding="utf-8") as f:
            index_js = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "css", "editor.css"), encoding="utf-8") as f:
            editor_css = f.read()
        with open(os.path.join(ROOT, "webapp", "app.py"), encoding="utf-8") as f:
            app_py = f.read()

        self.assertIn('id="research-step-track"', index_html)
        self.assertIn('id="research-event-list"', index_html)
        self.assertIn("RESEARCH_PROGRESS_STEPS", index_js)
        self.assertIn("信息采集", index_js)
        self.assertIn("枚举验证", index_js)
        self.assertIn("入库图片", index_js)
        self.assertIn("renderProgressSteps", index_js)
        self.assertIn("renderProgressEvents", index_js)
        self.assertIn("job.stages || []", index_js)
        self.assertIn("Math.max(this.currentProgressPercent", index_js)
        self.assertIn("research-step-track", editor_css)
        self.assertIn("research-event-list", editor_css)
        self.assertIn('stages[-1]["detail"] = message', app_py)

    def test_research_desk_can_restore_and_stop_active_job(self):
        with open(os.path.join(ROOT, "webapp", "templates", "index.html"), encoding="utf-8") as f:
            index_html = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "index.js"), encoding="utf-8") as f:
            index_js = f.read()

        self.assertIn('id="btn-stop-research"', index_html)
        self.assertIn("stopResearch()", index_js)
        self.assertIn("_restoreActiveJob()", index_js)
        self.assertIn("gzh2_active_job", index_js)
        self.assertIn("/api/research/running", index_js)
        self.assertIn("/api/research/stop/", index_js)
        self.assertIn("localStorage.removeItem('gzh2_active_job')", index_js)
        self.assertIn("saved = null", index_js)

    def test_company_library_rows_expand_one_research_detail(self):
        with open(os.path.join(ROOT, "webapp", "static", "js", "index.js"), encoding="utf-8") as f:
            index_js = f.read()

        self.assertIn("expandedCompany", index_js)
        self.assertIn("toggleCompanyDetails", index_js)
        self.assertIn("renderCompanyDetailRow", index_js)
        self.assertIn("API.getAllVersions", index_js)
        self.assertIn('class="company-row ', index_js)
        self.assertIn('data-company="${encodedName}"', index_js)
        self.assertIn('data-refill-company="${this.esc(encodedName)}"', index_js)
        self.assertIn('data-refill-url="${this.esc(encodedUrl)}"', index_js)
        self.assertIn('class="company-detail-row"', index_js)
        self.assertIn("this.expandedCompany = companyName", index_js)
        self.assertIn("refillResearch(encodedName, encodedUrl = '')", index_js)
        self.assertIn("urlInput.value", index_js)
        self.assertNotIn("renderVersionDetail", index_js)
        self.assertNotIn("version-detail-grid", index_js)

    def test_editor_surfaces_hook_copy_view(self):
        with open(os.path.join(ROOT, "contracts", "fields.json"), encoding="utf-8") as f:
            fields_contract = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "editor", "text-finalize-panel.js"), encoding="utf-8") as f:
            text_finalize_js = f.read()
        with open(os.path.join(ROOT, "webapp", "templates", "editor.html"), encoding="utf-8") as f:
            editor_html = f.read()

        self.assertIn('"group_key": "hook"', fields_contract)
        self.assertIn('"hook_paragraph_1"', fields_contract)
        self.assertIn('"hook_paragraph_2"', fields_contract)
        self.assertIn('"hook_paragraph_3"', fields_contract)
        self.assertIn("TextFinalizePanel", text_finalize_js)
        self.assertIn("/api/fields/", text_finalize_js)
        self.assertNotIn('data-card="hook"', editor_html)
        self.assertNotIn('id="hook-render"', editor_html)

    def test_operating_and_card_split_fields_are_in_contract_prompt_and_db(self):
        with open(os.path.join(ROOT, "contracts", "fields.json"), encoding="utf-8") as f:
            fields_contract = f.read()
        with open(os.path.join(ROOT, "prompts", "layer3-field-extraction.md"), encoding="utf-8") as f:
            layer3_prompt = f.read()
        with open(os.path.join(ROOT, "webapp", "db.py"), encoding="utf-8") as f:
            db_py = f.read()
        with open(os.path.join(ROOT, "db", "migrations", "008_operating_metrics_fields.sql"), encoding="utf-8") as f:
            migration = f.read()

        expected_fields = [
            "tam", "sam", "som", "market_cagr", "arr", "mrr",
            "registered_users", "active_users", "paying_users",
            "retention_rate", "churn_rate", "cac", "ltv",
            "ltv_cac_ratio", "gross_margin", "burn_rate",
            "runway_months", "market_size_source_note",
            "ecosystem_positioning", "differentiation_strategy",
            "cost_advantage", "technical_barrier", "switching_cost",
            "ideal_customer_profile", "customer_segment_primary",
            "customer_segment_secondary", "growth_strategy", "gtm_motion",
        ]
        for field in expected_fields:
            self.assertIn(f'"field_key": "{field}"', fields_contract)
            self.assertIn(f'"{field}"', layer3_prompt)
            self.assertIn(f'"{field}"', db_py)
            self.assertIn(f"ADD COLUMN {field} TEXT", migration)

    def test_layout_markdown_defaults_are_project_defaults(self):
        with open(os.path.join(ROOT, "webapp", "static", "js", "layout", "layout-app.js"), encoding="utf-8") as f:
            layout_js = f.read()

        self.assertIn("fontSize: 32", layout_js)
        self.assertIn("lineHeight: 1.6", layout_js)
        self.assertIn("paragraphGap: 22", layout_js)
        self.assertIn("padding: 74", layout_js)
        self.assertIn("imageMaxHeight: 360", layout_js)
        self.assertIn("_defaultMarkdownForCard", layout_js)

    def test_image_studio_caches_svg_data_per_asset_key(self):
        with open(os.path.join(ROOT, "image-studio", "js", "studio-app.js"), encoding="utf-8") as f:
            studio_js = f.read()

        self.assertIn("_svDataByKey", studio_js)
        self.assertIn("this._svDataByKey[slot.asset_key]", studio_js)
        self.assertNotIn("if (!this._svData) {", studio_js)

    def test_image_studio_uses_preview_search_and_candidate_sidebar(self):
        with open(os.path.join(ROOT, "image-studio", "index.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(ROOT, "image-studio", "js", "search-panel.js"), encoding="utf-8") as f:
            search_js = f.read()
        with open(os.path.join(ROOT, "image-studio", "js", "variant-sidebar.js"), encoding="utf-8") as f:
            sidebar_js = f.read()
        with open(os.path.join(ROOT, "image-studio", "css", "studio.css"), encoding="utf-8") as f:
            css = f.read()

        self.assertIn('id="editor-area"', html)
        self.assertIn('id="candidate-panel"', html)
        self.assertIn('id="search-results-area"', search_js)
        self.assertIn('id="preview-stage"', search_js)
        self.assertIn('id="candidate-grid-2col"', sidebar_js)
        self.assertNotIn("<h3>候选</h3>", sidebar_js)
        self.assertIn(".candidate-panel", css)

    def test_image_studio_uses_demand_based_workspaces(self):
        with open(os.path.join(ROOT, "image-studio", "index.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(ROOT, "image-studio", "js", "studio-app.js"), encoding="utf-8") as f:
            app_js = f.read()
        with open(os.path.join(ROOT, "image-studio", "js", "workspace-chart.js"), encoding="utf-8") as f:
            chart_js = f.read()
        with open(os.path.join(ROOT, "image-studio", "js", "param-inspector.js"), encoding="utf-8") as f:
            inspector_js = f.read()
        with open(os.path.join(ROOT, "image-studio", "css", "studio.css"), encoding="utf-8") as f:
            css = f.read()
        with open(os.path.join(ROOT, "webapp", "infographic.py"), encoding="utf-8") as f:
            infographic_py = f.read()

        self.assertIn("workspace-image.js", html)
        self.assertIn("workspace-chart.js", html)
        self.assertIn("param-inspector.js", html)
        self.assertIn("DEMAND_LABELS", app_js)
        self.assertIn("website_screenshot", app_js)
        self.assertIn("competitors_logo_strip", app_js)
        self.assertIn("数据与文字", inspector_js)
        self.assertIn("画布与版式", inspector_js)
        self.assertIn("字体与颜色", inspector_js)
        self.assertIn("图表专属", inspector_js)
        self.assertIn("输出版本", inspector_js)
        self.assertIn(".demand-workspace", css)
        self.assertIn(".param-inspector", css)
        self.assertIn("echarts-code-panel", chart_js)
        self.assertIn("chart-code-editor", chart_js)
        self.assertIn("chart-code-highlight", chart_js)
        self.assertIn("_syncCodeHighlight", chart_js)
        self.assertIn("chart-param-bottom", chart_js)
        self.assertIn('<div id="chart-param-bottom" class="chart-param-bottom"></div>', chart_js)
        self.assertIn("chart-confirm-dock", chart_js)
        self.assertIn("_syncPreviewAspect", chart_js)
        self.assertIn("mode: 'compact'", chart_js)
        self.assertIn("this._syncCodeHighlight(textarea.value)", chart_js)
        self.assertIn("this._applyCodePreview();", chart_js)
        self.assertNotIn("data-chart-code-action=\"apply\"", chart_js)
        self.assertIn("renderChartHtml", chart_js)
        self.assertIn("svg{display:block;max-width:86%;max-height:86%", chart_js)
        self.assertIn("param-inspector-compact", inspector_js)
        self.assertIn("param-compact-tabs", inspector_js)
        self.assertIn(".chart-param-bottom", css)
        self.assertIn("aspect-ratio: var(--chart-aspect, 16 / 9)", css)
        self.assertIn(".chart-confirm-dock", css)
        self.assertIn(".workspace-primary", css)
        self.assertIn(".param-inspector-compact", css)
        self.assertIn(".chart-code-highlight", css)
        self.assertIn(".tok-keyword", css)
        self.assertIn(".chart-right-dock", css)
        self.assertIn(".echarts-code-panel", css)
        self.assertIn(".chart-workspace.echarts-workspace .chart-preview-stage iframe", css)
        self.assertIn("min-height: 0", css)
        self.assertIn("chart-frame", infographic_py)
        self.assertIn("fitChartCanvas", infographic_py)
        self.assertIn("transform='scale('", infographic_py)
        self.assertIn("object-fit:contain", infographic_py)

    def test_canvas_image_folder_supports_all_asset_keys(self):
        with open(os.path.join(ROOT, "canvas", "card-renderer.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(ROOT, "canvas", "card.html"), encoding="utf-8") as f:
            card_html = f.read()
        with open(os.path.join(ROOT, "canvas", "js", "api-loader.js"), encoding="utf-8") as f:
            api_loader = f.read()
        with open(os.path.join(ROOT, "canvas", "js", "render-data-loader.js"), encoding="utf-8") as f:
            render_data_loader = f.read()
        with open(os.path.join(ROOT, "canvas", "js", "html-card-renderer.js"), encoding="utf-8") as f:
            renderer = f.read()
        with open(os.path.join(ROOT, "canvas", "js", "template-renderer.js"), encoding="utf-8") as f:
            template_renderer = f.read()

        self.assertIn("renderAllCompanyAssets", html)
        self.assertIn("render-data-loader.js", card_html)
        self.assertIn("template-renderer.js", card_html)
        self.assertIn("RenderDataLoader.loadCard", card_html)
        self.assertIn("new URLSearchParams(window.location.search).get('set')", render_data_loader)
        self.assertIn("?set=${encodeURIComponent(effectiveSet)}", render_data_loader)
        self.assertIn("const TemplateRenderer", template_renderer)
        self.assertIn("render(cardData)", template_renderer)
        self.assertIn("knowledge-card", template_renderer)
        self.assertIn('data-od-id="card-root"', template_renderer)
        self.assertNotIn("<html><head>", template_renderer)
        self.assertIn("website_screenshot", api_loader)
        self.assertIn("competitors_logo_strip", api_loader)
        self.assertIn("chart_competitive", api_loader)
        self.assertIn("chart_ecosystem", api_loader)
        self.assertIn("allAssets", renderer)

    def test_decoupled_routes_and_safe_flask_start_are_wired(self):
        with open(os.path.join(ROOT, "webapp", "app.py"), encoding="utf-8") as f:
            app_py = f.read()
        with open(os.path.join(ROOT, "webapp", "routes", "__init__.py"), encoding="utf-8") as f:
            routes_init = f.read()
        with open(os.path.join(ROOT, "webapp", "routes", "media_routes.py"), encoding="utf-8") as f:
            media_routes = f.read()
        with open(os.path.join(ROOT, "webapp", "services", "export_service.py"), encoding="utf-8") as f:
            export_service = f.read()
        with open(os.path.join(ROOT, "webapp", "templates", "layout.html"), encoding="utf-8") as f:
            layout_html = f.read()
        with open(os.path.join(ROOT, "webapp", "templates", "template_maker.html"), encoding="utf-8") as f:
            template_maker_html = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "layout", "layout-app.js"), encoding="utf-8") as f:
            layout_js = f.read()
        with open(os.path.join(ROOT, "webapp", "templates", "editor.html"), encoding="utf-8") as f:
            editor_html = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "editor", "card-settings-panel.js"), encoding="utf-8") as f:
            card_settings_js = f.read()
        with open(os.path.join(ROOT, "db", "migrate.py"), encoding="utf-8") as f:
            migrate_py = f.read()

        self.assertIn('host=os.environ.get("FLASK_HOST", "127.0.0.1")', app_py)
        self.assertIn('debug=os.environ.get("FLASK_DEBUG") == "1"', app_py)
        self.assertIn("run_migrations", migrate_py)
        self.assertIn("schema_migrations", migrate_py)
        self.assertIn("_run_migrations(config.DB_PATH_RESEARCH", app_py)
        self.assertIn("_run_migrations(config.DB_PATH_FINAL", app_py)
        self.assertIn('media_bp = Blueprint("media"', routes_init)
        self.assertIn("media_routes", routes_init)
        self.assertIn("/media/<company>/<media_key>/upload", media_routes)
        self.assertIn("UPLOAD_EXTENSIONS", media_routes)
        self.assertIn("普通图片不接受 svg", media_routes)
        self.assertIn("/api/export/", layout_js)
        self.assertIn("layout-status", layout_html)
        self.assertIn("/canvas/js/template-renderer.js", layout_html)
        self.assertIn("_layoutOverrides", layout_js)
        self.assertIn("_effectiveTemplate()", layout_js)
        self.assertIn("body: JSON.stringify({ layout: this._layoutPayload() })", layout_js)
        self.assertIn("_markdownFromCard", layout_js)
        self.assertIn("_insertMarkdown", layout_js)
        self.assertIn("_setMode(mode)", layout_js)
        self.assertIn("this._mode = 'split'", layout_js)
        self.assertIn("_startSplitDrag", layout_js)
        self.assertIn("_renderMarkdownPreview", layout_js)
        self.assertIn("wrap.style.width = `${900 * this._previewScale}px`", layout_js)
        self.assertIn("frame.style.width = '900px'", layout_js)
        self.assertIn("layout-md-body", layout_js)
        self.assertIn("_styleAppliedToAllDirty", layout_js)
        self.assertIn("_saveAllLayouts", layout_js)
        self.assertIn("template-status", template_maker_html)
        self.assertIn("template-checks", template_maker_html)
        self.assertIn("_validateTemplate()", template_maker_html)
        self.assertIn("data-od-id", template_maker_html)
        self.assertIn("URLSearchParams(window.location.search)", editor_html)
        self.assertIn("/api/media/", card_settings_js)
        self.assertIn('data.get("layout")', app_py)
        self.assertIn("save_layout(config.DB_PATH_TEMPLATE", app_py)
        self.assertIn("_build_markdown_card_html", export_service)
        self.assertIn('layout_json.get("mode") == "markdown_first"', export_service)

    def test_layout_markdown_editor_has_inline_format_toolbar(self):
        with open(os.path.join(ROOT, "webapp", "templates", "layout.html"), encoding="utf-8") as f:
            layout_html = f.read()
        with open(os.path.join(ROOT, "webapp", "static", "js", "layout", "layout-app.js"), encoding="utf-8") as f:
            layout_js = f.read()

        self.assertIn("fmt-toolbar", layout_html)
        self.assertIn("fmt-swatch", layout_html)
        self.assertIn("data-action=\"color\"", layout_html)
        self.assertIn("data-action=\"bg\"", layout_html)
        self.assertIn("_wrapSelection", layout_js)
        self.assertIn('this._wrapSelection(`<span style="color:${value}">`', layout_js)
        self.assertIn('this._wrapSelection(`<mark style="background:${value};border-radius:3px;padding:0 2px">`', layout_js)
        self.assertIn("replace(/<\\/?(span|mark)[^>]*>/g, '')", layout_js)

    def test_card_spec_freezes_current_seven_card_asset_contract(self):
        with open(os.path.join(ROOT, "docs", "card-spec.md"), encoding="utf-8") as f:
            spec = f.read()

        self.assertIn("card_spec_version = v2", spec)
        self.assertIn("`card_7`", spec)
        self.assertNotIn("`card_8`", spec)
        self.assertIn("`competitors_logo_strip`", spec)
        self.assertIn("`chart_competitive`", spec)
        self.assertIn("GET /api/assets/resolved", spec)

    def test_office_map_is_manual_collection_only(self):
        with open(os.path.join(ROOT, "webapp", "asset_pipeline.py"), encoding="utf-8") as f:
            pipeline_py = f.read()
        with open(os.path.join(ROOT, "webapp", "app.py"), encoding="utf-8") as f:
            app_py = f.read()

        self.assertIn("Office asset: map first, then supplemental street-view/Tavily candidates", pipeline_py)
        self.assertIn('"公司位置地图"', pipeline_py)
        self.assertIn('if asset_key == "office"', pipeline_py)
        self.assertNotIn("卡片2：公司位置地图", pipeline_py)
        self.assertIn("_render_osm_tile_composite", pipeline_py)
        self.assertIn("_render_static_map_card", pipeline_py)
        self.assertIn('if asset_key != "office"', app_py)
        self.assertNotIn("卡片2公司位置槽位", app_py)


if __name__ == "__main__":
    unittest.main()
