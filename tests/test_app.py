import os
import io
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import app as app_module
import db
import asset_store
import asset_pipeline
import infographic_templates
import path_safety


def init_sqlite(schema_name: str) -> str:
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    schema_path = os.path.join(ROOT, "db", schema_name)
    with open(schema_path, encoding="utf-8") as f:
        schema = f.read()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


class ResearchStartTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_start_research_empty_body_returns_400(self):
        response = self.client.post("/api/research/start")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "缺少 company_name 或 company_url")

    def test_start_research_stores_research_options(self):
        class FakeThread:
            def __init__(self, target=None, args=(), daemon=False):
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                return None

        with app_module._jobs_lock:
            app_module._jobs.clear()
        payload = {
            "company_name": "DemoCo",
            "company_url": "https://demo.example",
            "research_options": {
                "scrapling_search": True,
                "tavily_search": False,
                "github": True,
            },
        }

        try:
            with patch.object(app_module.threading, "Thread", FakeThread):
                response = self.client.post("/api/research/start", json=payload)
            data = response.get_json()
            with app_module._jobs_lock:
                job = app_module._jobs[data["job_id"]]
        finally:
            with app_module._jobs_lock:
                app_module._jobs.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(job["research_options"]["scrapling_search"], True)
        self.assertEqual(job["research_options"]["tavily_search"], False)
        self.assertEqual(data["research_options"]["github"], True)

    def test_count_research_fields_uses_name_or_company_key(self):
        fd, db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(db_path) and os.remove(db_path))
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE research_fields (company_name TEXT, company_key TEXT)")
            conn.executemany(
                "INSERT INTO research_fields (company_name, company_key) VALUES (?, ?)",
                [
                    ("DemoCo", "demo.co"),
                    ("Demo Company", "demo.co"),
                    ("OtherCo", "other.co"),
                ],
            )

        with patch.object(app_module.config, "DB_PATH_RESEARCH", db_path):
            count = app_module._count_research_fields_for_company("DemoCo", "demo.co")

        self.assertEqual(count, 2)

    def test_stop_research_marks_running_job_as_cancelling(self):
        with app_module._jobs_lock:
            app_module._jobs.clear()
            app_module._jobs["job-stop"] = {
                "job_id": "job-stop",
                "company_name": "DemoCo",
                "status": "running",
                "stage": "分析",
                "detail": "",
            }
        db_path = init_sqlite("init_research_db.sql")
        old_research = app_module.config.DB_PATH_RESEARCH
        app_module.config.DB_PATH_RESEARCH = db_path
        db.create_job(db_path, "job-stop", "DemoCo", "https://demo.example")
        try:
            response = self.client.post("/api/research/stop/job-stop")
        finally:
            app_module.config.DB_PATH_RESEARCH = old_research
            os.remove(db_path)
            with app_module._jobs_lock:
                app_module._jobs.clear()

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(payload["stage"], "已停止")
        self.assertEqual(payload["sources"], {})
        self.assertEqual(payload["stages"], [])

    def test_stop_research_is_idempotent_for_cancelled_memory_job(self):
        with app_module._jobs_lock:
            app_module._jobs.clear()
            app_module._jobs["job-stop"] = {
                "job_id": "job-stop",
                "company_name": "DemoCo",
                "status": "cancelled",
                "stage": "已停止",
                "detail": "用户已停止研究",
                "cancelled": True,
                "sources": {"tavily_search": {"count": 2}},
                "stages": [{"stage": "采集", "detail": "旧信息"}],
            }
        try:
            response = self.client.post("/api/research/stop/job-stop")
        finally:
            with app_module._jobs_lock:
                app_module._jobs.clear()

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(payload["sources"], {})
        self.assertEqual(payload["stages"], [])

    def test_running_research_cancels_orphaned_db_job_when_memory_is_empty(self):
        db_path = init_sqlite("init_research_db.sql")
        old_research = app_module.config.DB_PATH_RESEARCH
        app_module.config.DB_PATH_RESEARCH = db_path
        with app_module._jobs_lock:
            app_module._jobs.clear()
        db.create_job(db_path, "job-running", "DemoCo", "https://demo.example")
        db.create_job(db_path, "job-running-2", "OtherCo", "https://other.example")
        try:
            response = self.client.get("/api/research/running")
            job = db.get_job(db_path, "job-running")
            job2 = db.get_job(db_path, "job-running-2")
        finally:
            app_module.config.DB_PATH_RESEARCH = old_research
            os.remove(db_path)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "none")
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job2["status"], "cancelled")
        self.assertEqual(job["stage"], "已停止")

    def test_stop_research_cancels_db_running_job_when_memory_is_empty(self):
        db_path = init_sqlite("init_research_db.sql")
        old_research = app_module.config.DB_PATH_RESEARCH
        app_module.config.DB_PATH_RESEARCH = db_path
        with app_module._jobs_lock:
            app_module._jobs.clear()
        db.create_job(db_path, "job-db-stop", "DemoCo", "https://demo.example")
        try:
            response = self.client.post("/api/research/stop/job-db-stop")
            job = db.get_job(db_path, "job-db-stop")
        finally:
            app_module.config.DB_PATH_RESEARCH = old_research
            os.remove(db_path)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "cancelled")
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["stage"], "已停止")

    def test_stop_research_clears_written_research_fields_for_company(self):
        db_path = init_sqlite("init_research_db.sql")
        migration_paths = [
            "001_research_fields.sql",
            "013_source_documents.sql",
            "016_final_card_values.sql",
        ]
        with sqlite3.connect(db_path) as conn:
            for migration in migration_paths:
                with open(os.path.join(ROOT, "db", "migrations", migration), encoding="utf-8") as f:
                    conn.executescript(f.read())
            conn.execute(
                "INSERT INTO research_fields(company_name, version, field_key, field_value) VALUES (?, ?, ?, ?)",
                ("DemoCo", "standard", "company_type", "AI工具"),
            )
            conn.execute(
                "INSERT INTO research_fields(company_name, version, field_key, field_value) VALUES (?, ?, ?, ?)",
                ("OtherCo", "standard", "company_type", "AI工具"),
            )
            conn.execute(
                "INSERT INTO final_card_values(run_id, company_key, card_no, field_key, final_value) VALUES (?, ?, ?, ?, ?)",
                ("job-db-stop", "democo", 1, "company_type", "AI工具"),
            )
            conn.commit()

        old_research = app_module.config.DB_PATH_RESEARCH
        app_module.config.DB_PATH_RESEARCH = db_path
        with app_module._jobs_lock:
            app_module._jobs.clear()
        db.create_job(db_path, "job-db-stop", "DemoCo", "https://demo.example",
                      company_key="democo")
        try:
            response = self.client.post("/api/research/stop/job-db-stop")
            payload = response.get_json()
            with sqlite3.connect(db_path) as conn:
                demo_count = conn.execute(
                    "SELECT COUNT(*) FROM research_fields WHERE company_name='DemoCo'"
                ).fetchone()[0]
                other_count = conn.execute(
                    "SELECT COUNT(*) FROM research_fields WHERE company_name='OtherCo'"
                ).fetchone()[0]
                card_count = conn.execute(
                    "SELECT COUNT(*) FROM final_card_values WHERE run_id='job-db-stop'"
                ).fetchone()[0]
        finally:
            app_module.config.DB_PATH_RESEARCH = old_research
            os.remove(db_path)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(demo_count, 0)
        self.assertEqual(other_count, 1)
        self.assertEqual(card_count, 0)


class PageRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_root_renders_research_desk_not_editor(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="research-desk"', html)
        self.assertIn("公司库", html)
        self.assertNotIn('id="company-select"', html)

    def test_editor_without_trailing_slash_renders_directly(self):
        response = self.client.get("/editor?company=DemoCo")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="editor-workbench"', response.get_data(as_text=True))

    def test_canvas_single_card_route_renders_html_card_page(self):
        response = self.client.get("/canvas/card/DemoCo/1")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="card-page"', html)
        self.assertIn("knowledge-card", html)

    def test_canvas_single_card_route_accepts_card_8(self):
        response = self.client.get("/canvas/card/DemoCo/8")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="card-page"', response.get_data(as_text=True))

    def test_canvas_single_card_route_accepts_dynamic_card_id(self):
        response = self.client.get("/canvas/card/DemoCo/card_09")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="card-page"', response.get_data(as_text=True))


class ResearchCardMarkdownTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.db_path = init_sqlite("init_research_db.sql")
        self.old_research = app_module.config.DB_PATH_RESEARCH
        app_module.config.DB_PATH_RESEARCH = self.db_path
        db.save_research_records(
            self.db_path,
            [
                {
                    "company_name": "DemoCo",
                    "version": "standard",
                    "company_type": "AI 工具",
                    "timeline_events": [
                        {"date": "2024-01", "event": "上线 Beta", "impact": "获得首批用户"}
                    ],
                    "market_opportunity": "AI 工作流进入重构期。",
                }
            ],
        )

    def tearDown(self):
        app_module.config.DB_PATH_RESEARCH = self.old_research
        os.remove(self.db_path)

    def test_research_card_endpoint_returns_card_markdown(self):
        response = self.client.get("/api/research/DemoCo/card/3?version=standard")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("## 卡片3：发展沿袭", payload["markdown"])
        self.assertIn("2024-01", payload["markdown"])

    def test_research_card_endpoint_returns_card_7_summary_markdown(self):
        response = self.client.get("/api/research/DemoCo/card/7?version=standard")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("## 卡片7：竞争格局", payload["markdown"])
        self.assertIn("**壁垒**：", payload["markdown"])


class CompanyListTests(unittest.TestCase):
    def setUp(self):
        self.db_path = init_sqlite("init_research_db.sql")
        db.save_research_records(
            self.db_path,
            [
                {
                    "company_name": "DemoCo",
                    "version": "standard",
                    "company_type": "AI 工具",
                    "website_url": "https://demo.example",
                }
            ],
        )

    def tearDown(self):
        os.remove(self.db_path)

    def test_company_list_includes_latest_website_url_for_refill(self):
        companies = db.get_companies(self.db_path)

        self.assertEqual(companies[0]["company_name"], "DemoCo")
        self.assertEqual(companies[0]["website_url"], "https://demo.example")
        self.assertEqual(companies[0]["company_url"], "https://demo.example")

    def test_company_list_completeness_prefers_research_fields(self):
        valid_fields = db.REQUIRED_RESEARCH_FIELDS[:10]
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_fields (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    company_key TEXT DEFAULT '',
                    version TEXT DEFAULT 'standard',
                    field_key TEXT NOT NULL,
                    field_value TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.executemany(
                """
                INSERT INTO research_fields
                    (company_name, company_key, version, field_key, field_value)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("DemoCo", "", "standard", field_key, f"value-{field_key}")
                    for field_key in valid_fields
                ],
            )

        companies = db.get_companies(self.db_path)

        self.assertEqual(
            companies[0]["completeness"],
            round(len(valid_fields) / len(db.REQUIRED_RESEARCH_FIELDS) * 100),
        )


class ImageRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.assets_db_path = init_sqlite("init_assets_db.sql")
        self.old_assets = app_module.config.DB_PATH_ASSETS
        app_module.config.DB_PATH_ASSETS = self.assets_db_path

    def tearDown(self):
        app_module.config.DB_PATH_ASSETS = self.old_assets
        os.remove(self.assets_db_path)

    def test_generate_image_returns_browser_url(self):
        image_path = os.path.join(ROOT, "images", "DemoCo_logo.png")
        with patch.object(app_module, "generate_image", return_value=image_path):
            response = self.client.post(
                "/api/generate-image",
                json={
                    "company_name": "DemoCo",
                    "field_name": "logo",
                    "prompt": "clean product image",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["img_path"], "/images/DemoCo_logo.png")

    def test_generate_image_accepts_runtime_api_config_without_echoing_key(self):
        image_path = os.path.join(ROOT, "images", "DemoCo_card.png")
        with patch.object(app_module, "generate_image", return_value=image_path) as generate:
            response = self.client.post(
                "/api/generate-image",
                json={
                    "company_name": "DemoCo",
                    "field_name": "card_1_image",
                    "prompt": "clean card image",
                    "image_api_url": "https://image.example.test/generate",
                    "image_api_key": "secret-test-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["img_path"], "/images/DemoCo_card.png")
        self.assertNotIn("secret-test-key", str(payload))
        self.assertEqual(generate.call_args.kwargs["api_url"], "https://image.example.test/generate")
        self.assertEqual(generate.call_args.kwargs["api_key"], "secret-test-key")

    def test_generate_image_with_asset_key_records_selected_variant(self):
        image_path = os.path.join(ROOT, "images", "DemoCo_office.png")
        with patch.object(app_module, "generate_image", return_value=image_path):
            response = self.client.post(
                "/api/generate-image",
                json={
                    "company_name": "DemoCo",
                    "field_name": "office",
                    "asset_key": "office",
                    "prompt": "clean office image",
                },
            )

        self.assertEqual(response.status_code, 200)
        variants = asset_store.list_variants(self.assets_db_path, "DemoCo", "office")
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["local_path"], "/images/DemoCo_office.png")
        self.assertEqual(variants[0]["source_type"], "api_generate")
        self.assertEqual(variants[0]["is_selected"], 1)

    def test_variants_endpoint_returns_scored_variants(self):
        asset_store.insert_variant(
            self.assets_db_path,
            "DemoCo",
            "product_main",
            local_path="/images/DemoCo/variants/og.png",
            source_type="official_og_image",
            width=1200,
            height=630,
            file_size=180000,
            final_score=86.5,
        )

        response = self.client.get("/api/image-studio/DemoCo/product_main/variants")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["asset_key"], "product_main")
        self.assertEqual(payload["variants"][0]["width"], 1200)
        self.assertAlmostEqual(payload["variants"][0]["final_score"], 86.5)

    def test_image_studio_overview_uses_demand_order(self):
        response = self.client.get("/api/image-studio/DemoCo")

        self.assertEqual(response.status_code, 200)
        keys = [slot["asset_key"] for slot in response.get_json()["slots"]]
        self.assertEqual(keys, [
            "logo", "website_screenshot", "founder_photo",
            "product_main",
            "competitors", "competitors_logo_strip",
            "chart_competitive", "chart_ecosystem", "flywheel",
        ])

    def test_resolved_assets_flattens_card_assets_and_prefers_selected_variant(self):
        asset_store.ensure_assets_rows(self.assets_db_path, "DemoCo")
        selected_logo_id = asset_store.insert_variant(
            self.assets_db_path, "DemoCo", "logo",
            local_path="/images/DemoCo/variants/logo__selected.png",
            source_type="upload",
            width=512, height=512, aspect_ratio=1.0,
            final_score=0.4,
        )
        asset_store.insert_variant(
            self.assets_db_path, "DemoCo", "logo",
            local_path="/images/DemoCo/variants/logo__higher.png",
            source_type="clearbit",
            width=512, height=512, aspect_ratio=1.0,
            final_score=0.9,
        )
        asset_store.select_variant(self.assets_db_path, "DemoCo", "logo", selected_logo_id)
        asset_store.insert_variant(
            self.assets_db_path, "DemoCo", "product_main",
            local_path="/images/DemoCo/variants/product__low.png",
            source_type="playwright",
            width=1200, height=900, aspect_ratio=1.333,
            final_score=0.2,
        )
        asset_store.insert_variant(
            self.assets_db_path, "DemoCo", "product_main",
            local_path="/images/DemoCo/variants/product__best.png",
            source_type="playwright",
            width=1600, height=900, aspect_ratio=1.777,
            final_score=0.8,
        )

        response = self.client.get("/api/assets/resolved?company=DemoCo&spec=v2")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["company_name"], "DemoCo")
        self.assertEqual(payload["card_spec_version"], "v2")
        self.assertEqual(payload["card_assets"]["card_1"]["logo"]["url"], "/images/DemoCo/variants/logo__selected.png")
        self.assertEqual(payload["card_assets"]["card_1"]["logo"]["status"], "selected")
        self.assertEqual(payload["card_assets"]["card_1"]["logo"]["variant_id"], selected_logo_id)
        self.assertEqual(payload["card_assets"]["card_3"]["product_main"]["url"], "/images/DemoCo/variants/product__best.png")
        self.assertEqual(payload["card_assets"]["card_3"]["product_main"]["status"], "fallback")
        self.assertEqual(payload["card_assets"]["card_3"]["product_main"]["variant_type"], "ratio_16_9")
        self.assertEqual(payload["card_assets"]["card_3"]["chart_ecosystem"]["status"], "placeholder")
        self.assertEqual(payload["card_assets"]["card_3"]["chart_ecosystem"]["kind"], "chart")
        self.assertNotIn("card_8", payload["card_assets"])

    def test_chart_data_endpoint_returns_editable_competitive_payload(self):
        response = self.client.post("/api/image-studio/DemoCo/chart_competitive/chart-data")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["asset_key"], "chart_competitive")
        self.assertEqual(data["chart_type"], "competitive_landscape")
        self.assertIn("companies", data)
        self.assertIn("params", data)
        self.assertIn("title", data["params"])

    def test_chart_preview_returns_html_even_without_scored_companies(self):
        with patch.object(app_module, "_load_all_scored_companies", return_value=[]):
            response = self.client.post(
                "/api/image-studio/DemoCo/chart_competitive/preview",
                json={"params": {"title": "竞争格局图"}},
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("暂无可用图表数据", html)
        self.assertIn("echarts.init", html)

    def test_render_html_endpoint_records_hand_edited_echarts_variant(self):
        def fake_html_to_png(html, dest, width=800, height=600, scale=2):
            Image.new("RGB", (width, height), (20, 30, 40)).save(dest)

        html = "<!doctype html><html><body><script>const echarts = window.echarts || {};</script></body></html>"
        with patch.object(app_module, "_html_to_png", side_effect=fake_html_to_png):
            response = self.client.post(
                "/api/image-studio/DemoCo/chart_competitive/render-html",
                json={"html": html, "params": {"width": 900, "height": 500}},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        variants = asset_store.list_variants(self.assets_db_path, "DemoCo", "chart_competitive")
        self.assertEqual(payload["variant_id"], variants[0]["id"])
        self.assertEqual(variants[0]["source_type"], "echarts_html")
        self.assertEqual(variants[0]["width"], 900)
        self.assertEqual(variants[0]["height"], 500)
        self.assertTrue(variants[0]["is_selected"])

    def test_rescore_endpoint_updates_scores_and_selects_best_variant(self):
        low_id = asset_store.insert_variant(
            self.assets_db_path,
            "DemoCo",
            "product_main",
            local_path="/images/DemoCo/variants/tavily.png",
            source_type="web_tavily",
            width=400,
            height=260,
            file_size=30000,
            source_url="https://cdn.example/random.png",
        )
        high_id = asset_store.insert_variant(
            self.assets_db_path,
            "DemoCo",
            "product_main",
            local_path="/images/DemoCo/variants/official.png",
            source_type="official_og_image",
            width=1200,
            height=630,
            file_size=180000,
            source_url="https://demo.example/product-og.png",
            source_page="https://demo.example/product",
            prompt="DemoCo product dashboard screenshot",
        )

        response = self.client.post("/api/image-studio/DemoCo/product_main/rescore")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["selected_variant_id"], high_id)
        self.assertGreater(payload["variants"][0]["final_score"], payload["variants"][1]["final_score"])
        asset = asset_store.get_asset(self.assets_db_path, "DemoCo", "product_main")
        self.assertEqual(asset["selected_variant_id"], high_id)
        self.assertNotEqual(asset["selected_variant_id"], low_id)


class SvgTemplateUploadTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_local_python_template_upload_registers_template(self):
        content = b"""META = {
    "id": "unit_test_template",
    "name": "Unit Test Template",
    "asset_key": "timeline",
    "builtin": False,
    "params": [],
}

def build(data, params):
    return '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
"""
        old_registry = dict(infographic_templates._registry)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                with patch.object(infographic_templates, "_USER_DIR", Path(tmp)):
                    response = self.client.post(
                        "/api/svg-templates/upload",
                        data={"file": (io.BytesIO(content), "unit_template.py")},
                        content_type="multipart/form-data",
                        headers={"X-Template-Upload-Intent": "local-dev"},
                    )
                    preview = self.client.post(
                        "/api/svg-templates/preview",
                        json={"template_id": "unit_test_template", "data": {}, "params": {}},
                    )
                    saved = Path(tmp) / "unit_template.py"
                    saved_exists = saved.exists()
            finally:
                infographic_templates._registry.clear()
                infographic_templates._registry.update(old_registry)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["meta"]["id"], "unit_test_template")
        self.assertTrue(saved_exists)
        self.assertEqual(preview.status_code, 200)
        self.assertIn("<svg", preview.get_data(as_text=True))

    def test_python_template_upload_requires_intent_header(self):
        content = b"""META = {
    "id": "unit_test_template",
    "name": "Unit Test Template",
    "asset_key": "timeline",
    "params": [],
}

def build(data, params):
    return '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
"""
        response = self.client.post(
            "/api/svg-templates/upload",
            data={"file": (io.BytesIO(content), "unit_template.py")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("上传意图", response.get_json()["error"])

    def test_python_template_delete_removes_uploaded_filename(self):
        content = b"""META = {
    "id": "unit_test_template",
    "name": "Unit Test Template",
    "asset_key": "timeline",
    "params": [],
}

def build(data, params):
    return '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
"""
        old_registry = dict(infographic_templates._registry)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                with patch.object(infographic_templates, "_USER_DIR", Path(tmp)):
                    upload = self.client.post(
                        "/api/svg-templates/upload",
                        data={"file": (io.BytesIO(content), "unit_template.py")},
                        content_type="multipart/form-data",
                        headers={"X-Template-Upload-Intent": "local-dev"},
                    )
                    response = self.client.delete("/api/svg-templates/unit_test_template")
                    saved = Path(tmp) / "unit_template.py"
                    saved_exists = saved.exists()
            finally:
                infographic_templates._registry.clear()
                infographic_templates._registry.update(old_registry)

        self.assertEqual(upload.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(saved_exists)

    def test_remote_python_template_upload_is_rejected(self):
        response = self.client.post(
            "/api/svg-templates/upload",
            data={"file": (io.BytesIO(b"META = {}\n\ndef build(data, params):\n    return ''\n"), "unsafe.py")},
            content_type="multipart/form-data",
            environ_base={"REMOTE_ADDR": "10.0.0.20"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("仅允许本机", response.get_json()["error"])


class AssetPathSafetyTests(unittest.TestCase):
    def test_company_path_sanitizer_is_shared_across_modules(self):
        unsafe = "../坏 Company 01/%logo"

        self.assertEqual(path_safety.safe_path_segment(unsafe), "坏_Company_01_logo")
        self.assertEqual(asset_pipeline._safe_path_segment(unsafe), path_safety.safe_path_segment(unsafe))
        self.assertEqual(db._safe_image_dir_name(unsafe), path_safety.safe_path_segment(unsafe))

    def test_variant_path_sanitizes_company_and_suffix_inside_images_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = asset_pipeline._variant_path(tmp, "../Bad Co", "../timeline", "../../shot")

            root = os.path.abspath(tmp)
            self.assertEqual(os.path.commonpath([root, os.path.abspath(dest)]), root)
            self.assertNotIn("..", os.path.relpath(dest, root))
            self.assertIn("Bad_Co", dest)

    def test_collection_pipeline_selects_first_ready_variant(self):
        assets_db_path = init_sqlite("init_assets_db.sql")
        self.addCleanup(lambda: os.path.exists(assets_db_path) and os.remove(assets_db_path))

        def collect_office(db_path, images_root, company_name, location, query_config, company_url="", company_key=""):
            asset_store.insert_variant(
                db_path,
                company_name,
                "office",
                local_path="/images/DemoCo/variants/office.png",
                source_type="web_tavily",
            )
            return 1

        with tempfile.TemporaryDirectory() as images_root:
            with patch.object(asset_pipeline, "_collect_office_variants", side_effect=collect_office), \
                 patch.object(asset_pipeline, "_collect_product_main_variants", return_value=0), \
                 patch.object(asset_pipeline, "_collect_products_other_variants", return_value=0), \
                 patch.object(asset_pipeline, "_collect_competitors_variants", return_value=0):
                asset_pipeline.collect_image_variants_pipeline(
                    assets_db_path,
                    images_root,
                    "DemoCo",
                    {"location": "San Francisco"},
                    asset_key="office",
                )

        demo_asset = asset_store.get_asset(assets_db_path, "DemoCo", "office")
        variants = asset_store.list_variants(assets_db_path, "DemoCo", "office")
        self.assertEqual(demo_asset["local_path"], "/images/DemoCo/variants/office.png")
        self.assertEqual(variants[0]["is_selected"], 1)

    def test_collection_pipeline_skips_office_map_by_default(self):
        assets_db_path = init_sqlite("init_assets_db.sql")
        self.addCleanup(lambda: os.path.exists(assets_db_path) and os.remove(assets_db_path))

        with tempfile.TemporaryDirectory() as images_root:
            with patch.object(asset_pipeline, "_collect_office_variants", return_value=1) as collect_office, \
                 patch.object(asset_pipeline, "_collect_website_screenshot_variants", return_value=0), \
                 patch.object(asset_pipeline, "_collect_product_main_variants", return_value=0), \
                 patch.object(asset_pipeline, "_collect_products_other_variants", return_value=0), \
                 patch.object(asset_pipeline, "_collect_competitors_variants", return_value=0), \
                 patch.object(asset_pipeline, "_collect_competitor_logo_strip_variants", return_value=0):
                results = asset_pipeline.collect_image_variants_pipeline(
                    assets_db_path,
                    images_root,
                    "DemoCo",
                    {"location": "San Francisco"},
                )

        collect_office.assert_not_called()
        self.assertNotIn("office", results)

    def test_collection_progress_labels_use_asset_demand_not_card_number(self):
        assets_db_path = init_sqlite("init_assets_db.sql")
        self.addCleanup(lambda: os.path.exists(assets_db_path) and os.remove(assets_db_path))
        progress = []

        with tempfile.TemporaryDirectory() as images_root:
            with patch.object(asset_pipeline, "_collect_office_variants", return_value=0):
                asset_pipeline.collect_image_variants_pipeline(
                    assets_db_path,
                    images_root,
                    "DemoCo",
                    {"location": "San Francisco"},
                    progress_callback=lambda _stage, detail: progress.append(detail["message"]),
                    asset_key="office",
                )

        self.assertEqual(progress[0], "公司位置地图")
        self.assertEqual(progress[1], "公司位置地图完成：0 张候选图")
        self.assertFalse(any("卡片" in message for message in progress))

    def test_office_collection_selects_map_and_keeps_supplements(self):
        assets_db_path = init_sqlite("init_assets_db.sql")
        self.addCleanup(lambda: os.path.exists(assets_db_path) and os.remove(assets_db_path))
        asset_store.ensure_assets_rows(assets_db_path, "DemoCo")

        with tempfile.TemporaryDirectory() as images_root:
            with patch.object(asset_pipeline, "_render_osm_map", return_value=True) as render_map, \
                 patch.object(asset_pipeline, "_geocode_location", return_value=(37.77, -122.42)), \
                 patch.object(asset_pipeline.config, "GOOGLE_MAPS_API_KEY", "maps-key"), \
                 patch.object(asset_pipeline, "_fetch_street_view", return_value=True), \
                 patch.object(asset_pipeline, "_try_tavily_images", return_value="https://images.example/office.png"):
                count = asset_pipeline._collect_office_variants(
                    assets_db_path,
                    images_root,
                    "DemoCo",
                    "San Francisco, CA",
                    {"tavily_queries": ["DemoCo office"]},
                )

        variants = asset_store.list_variants(assets_db_path, "DemoCo", "office")
        selected = [v for v in variants if v["is_selected"]]
        self.assertEqual(count, 4)
        self.assertEqual(len(variants), 4)
        self.assertEqual(selected[0]["source_type"], "osm_map")
        self.assertEqual(selected[0]["local_path"], "/images/DemoCo/variants/office__osm_map.png")
        self.assertIn("street_view", {v["source_type"] for v in variants})
        self.assertIn("web_tavily", {v["source_type"] for v in variants})
        render_map.assert_called_once()

    def test_competitor_logo_strip_collection_creates_single_16_9_variant(self):
        assets_db_path = init_sqlite("init_assets_db.sql")
        self.addCleanup(lambda: os.path.exists(assets_db_path) and os.remove(assets_db_path))
        asset_store.ensure_assets_rows(assets_db_path, "DemoCo")

        colors = [(235, 85, 85), (85, 150, 235), (85, 190, 120)]

        def fake_download(url, dest, timeout=15):
            idx = int(re.search(r"comp(\d+)_logo", dest).group(1))
            Image.new("RGB", (240, 120), colors[idx]).save(dest)
            return True

        query_config = {
            "per_comp": [
                {"name": "Alpha", "playwright_url": "https://alpha.example"},
                {"name": "Beta", "playwright_url": "https://beta.example"},
                {"name": "Gamma", "playwright_url": "https://gamma.example"},
            ]
        }

        with tempfile.TemporaryDirectory() as images_root:
            with patch.object(asset_pipeline, "_download", side_effect=fake_download):
                count = asset_pipeline._collect_competitor_logo_strip_variants(
                    assets_db_path,
                    images_root,
                    "DemoCo",
                    query_config,
                )
            variants = asset_store.list_variants(assets_db_path, "DemoCo", "competitors_logo_strip")
            local_file = os.path.join(images_root, "DemoCo", "variants", os.path.basename(variants[0]["local_path"]))
            with Image.open(local_file) as img:
                size = img.size

        self.assertEqual(count, 1)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["source_type"], "logo_strip")
        self.assertEqual(size, (1280, 720))
        self.assertEqual(variants[0]["width"], 1280)
        self.assertEqual(variants[0]["height"], 720)
        self.assertIn("Alpha", variants[0]["prompt"])

    def test_website_screenshot_marks_failed_on_empty_url(self):
        """空 company_url 时标记 failed 并返回 0，不抛异常"""
        assets_db_path = init_sqlite("init_assets_db.sql")
        self.addCleanup(lambda: os.path.exists(assets_db_path) and os.remove(assets_db_path))
        asset_store.ensure_assets_rows(assets_db_path, "DemoCo")

        with tempfile.TemporaryDirectory() as images_root:
            count = asset_pipeline._collect_website_screenshot_variants(
                assets_db_path, images_root, "DemoCo", company_url="",
            )

        self.assertEqual(count, 0)
        asset = asset_store.get_asset(assets_db_path, "DemoCo", "website_screenshot")
        self.assertEqual(asset["status"], "failed")
        self.assertIn("地址为空", asset.get("fail_reason", ""))

    def test_website_screenshot_calls_playwright_with_valid_url(self):
        """有效 URL 时调用 Playwright 截图并返回变体"""
        assets_db_path = init_sqlite("init_assets_db.sql")
        self.addCleanup(lambda: os.path.exists(assets_db_path) and os.remove(assets_db_path))
        asset_store.ensure_assets_rows(assets_db_path, "DemoCo")

        def fake_capture(url, dest, **kw):
            # 创建一个有效 PNG 文件
            from PIL import Image
            Image.new("RGB", (1440, 1000), (200, 200, 250)).save(dest)
            from screenshot_client import ScreenshotResult
            return ScreenshotResult(ok=True, path=dest, fail_reason="")

        with tempfile.TemporaryDirectory() as images_root:
            with patch("screenshot_client.capture", side_effect=fake_capture):
                count = asset_pipeline._collect_website_screenshot_variants(
                    assets_db_path, images_root, "DemoCo",
                    company_url="https://example.com",
                )

        self.assertEqual(count, 1)
        variants = asset_store.list_variants(assets_db_path, "DemoCo", "website_screenshot")
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["source_type"], "playwright")
        self.assertEqual(variants[0]["is_selected"], 1)

    def test_tavily_collector_scores_all_candidates_and_records_rejections(self):
        assets_db_path = init_sqlite("init_assets_db.sql")
        self.addCleanup(lambda: os.path.exists(assets_db_path) and os.remove(assets_db_path))
        asset_store.ensure_assets_rows(assets_db_path, "DemoCo")

        def fake_download(url, dest, timeout=15):
            size = (120, 80) if "small" in url else (1200, 630)
            img = Image.new("RGB", size, (30, 120, 200))
            px = img.load()
            for x in range(size[0]):
                for y in range(size[1]):
                    px[x, y] = ((x * 3 + y) % 255, (y * 5 + x) % 255, (x + y) % 255)
            img.save(dest, "PNG")
            return True

        with tempfile.TemporaryDirectory() as images_root:
            with patch.object(asset_pipeline, "_tavily_image_urls", return_value=[
                "https://cdn.example/small.png",
                "https://demo.example/product-dashboard.png",
            ]), patch.object(asset_pipeline, "_download", side_effect=fake_download):
                accepted = asset_pipeline._collect_tavily_candidates(
                    assets_db_path,
                    images_root,
                    "DemoCo",
                    "product_main",
                    "DemoCo app screenshot",
                    limit=10,
                )

        variants = asset_store.list_variants(assets_db_path, "DemoCo", "product_main")
        rejected = [v for v in variants if v["reject_reason"]]
        accepted_variants = [v for v in variants if not v["reject_reason"]]
        self.assertEqual(accepted, 1)
        self.assertEqual(len(variants), 2)
        self.assertEqual(rejected[0]["reject_reason"], "尺寸过小")
        self.assertGreater(accepted_variants[0]["final_score"], 0)
        self.assertEqual(accepted_variants[0]["width"], 1200)

    def test_extract_og_image_prefers_official_social_image(self):
        class Resp:
            text = '<html><head><meta property="og:image" content="/share/product.png"></head></html>'

        with patch.object(asset_pipeline.requests, "get", return_value=Resp()):
            url = asset_pipeline._extract_og_image("https://demo.example/product")

        self.assertEqual(url, "https://demo.example/share/product.png")

    def test_resolve_office_location_prefers_official_precise_address(self):
        def fake_search(query, include_images=False):
            return {
                "results": [
                    {
                        "url": "https://random.example/midjourney",
                        "content": "Address: 156 2nd St, San Francisco, CA 94105",
                    },
                    {
                        "url": "https://docs.midjourney.com/hc/en-us/articles/terms",
                        "content": "Midjourney, Inc. Attn: Takedowns Department 611 Gateway Blvd. Ste 120 South San Francisco, CA, 94080-7066, US",
                    },
                ]
            }

        with patch.object(asset_pipeline, "_search_tavily_query", side_effect=fake_search):
            resolved = asset_pipeline._resolve_office_location(
                "Midjourney",
                "旧金山，美国",
                "https://www.midjourney.com",
            )

        self.assertEqual(resolved["location"], "611 Gateway Blvd. Ste 120 South San Francisco, CA, 94080-7066")
        self.assertEqual(resolved["source_url"], "https://docs.midjourney.com/hc/en-us/articles/terms")

    def test_geocode_search_text_removes_suite_noise(self):
        query = asset_pipeline._geocode_search_text(
            "611 Gateway Blvd. Ste 120 South San Francisco, CA, 94080-7066"
        )

        self.assertEqual(query, "611 Gateway Blvd South San Francisco CA 94080")


class FinalMarkdownFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.db_path = init_sqlite("init_final_db.sql")
        self.old_final = app_module.config.DB_PATH_FINAL
        app_module.config.DB_PATH_FINAL = self.db_path

    def tearDown(self):
        app_module.config.DB_PATH_FINAL = self.old_final
        os.remove(self.db_path)

    def test_final_save_accepts_full_markdown_and_exports_json(self):
        response = self.client.post(
            "/api/final/save",
            json={
                "company_name": "DemoCo",
                "card_index": 7,
                "card_set_key": "v2",
                "markdown_content": "# DemoCo\n\n**AI 工具**",
            },
        )
        self.assertEqual(response.status_code, 200)

        status = self.client.get("/api/final/status/DemoCo?set=v2")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["confirmed"], [7])
        self.assertEqual(status.get_json()["total"], 7)

        exported = self.client.get("/api/final/export/DemoCo?format=json&set=v2")
        self.assertEqual(exported.status_code, 200)
        payload = exported.get_json()
        self.assertEqual(payload["cards"]["7"]["markdown_content"], "# DemoCo\n\n**AI 工具**")
        self.assertEqual(payload["confirmed_count"], 1)


class SvgRenderRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.final_db_path = init_sqlite("init_final_db.sql")
        self.assets_db_path = init_sqlite("init_assets_db.sql")
        self.old_final = app_module.config.DB_PATH_FINAL
        self.old_assets = app_module.config.DB_PATH_ASSETS
        self.old_images = app_module.config.IMAGES_DIR
        app_module.config.DB_PATH_FINAL = self.final_db_path
        app_module.config.DB_PATH_ASSETS = self.assets_db_path
        self.images_dir = tempfile.mkdtemp()
        app_module.config.IMAGES_DIR = self.images_dir
        db.save_final_markdown(self.final_db_path, "DemoCo", 6, "## 卡片6：GTM与增长\n\n**用**： 获客\n**留**： 留存\n**赚**： 变现")
        asset_store.ensure_assets_rows(self.assets_db_path, "DemoCo")
        asset_store.upsert_asset(
            self.assets_db_path,
            "DemoCo",
            "flywheel",
            meta={"svg_data": {"center": "增长飞轮", "stages": [{"label": "用", "desc": "获客"}]}},
        )

    def tearDown(self):
        app_module.config.DB_PATH_FINAL = self.old_final
        app_module.config.DB_PATH_ASSETS = self.old_assets
        app_module.config.IMAGES_DIR = self.old_images
        os.remove(self.final_db_path)
        os.remove(self.assets_db_path)
        import shutil
        shutil.rmtree(self.images_dir)

    def test_render_svg_uses_cached_structured_data(self):
        with patch.object(app_module, "extract_flywheel_json", side_effect=AssertionError("should not extract")), \
             patch.object(app_module, "render_with_template", return_value=True) as render:
            response = self.client.post(
                "/api/image-studio/DemoCo/flywheel/render-svg",
                json={"template_id": "flywheel_default", "params": {}},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(render.call_args.args[0]["stages"][0]["label"], "用")


if __name__ == "__main__":
    unittest.main()
