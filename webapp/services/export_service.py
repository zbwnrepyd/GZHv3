"""导出服务 — render-data → HTML → Puppeteer PNG → ZIP"""
from __future__ import annotations
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path


# 全局任务状态（内存）
_export_jobs: dict[str, dict] = {}


def create_job(company: str, card_ids: list[str] | None = None,
               fmt: str = "png", scale: int = 2, card_set_key: str = "v1") -> str:
    """创建导出任务，返回 job_id"""
    job_id = f"exp_{uuid.uuid4().hex[:8]}"
    _export_jobs[job_id] = {
        "job_id": job_id,
        "company_name": company,
        "card_ids": card_ids or [],
        "format": fmt,
        "scale": scale,
        "card_set_key": card_set_key,
        "status": "pending",
        "files": [],
        "download_url": "",
        "error": "",
        "created_at": time.time(),
    }
    return job_id


def get_job(job_id: str) -> dict | None:
    return _export_jobs.get(job_id)


def _get_final_values(final_db: str, company: str, card_set_key: str) -> dict[str, str]:
    import sqlite3
    values: dict[str, str] = {}
    with sqlite3.connect(final_db) as conn:
        conn.row_factory = sqlite3.Row
        has_set_key = any(
            row["name"] == "card_set_key"
            for row in conn.execute("PRAGMA table_info(final_fields)").fetchall()
        )
        if has_set_key:
            rows = conn.execute(
                """SELECT field_key, final_value FROM final_fields
                   WHERE company_name=? AND status != 'hidden'
                   AND (card_set_key=? OR card_set_key IS NULL OR card_set_key='')""",
                (company, card_set_key),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT field_key, final_value FROM final_fields
                   WHERE company_name=? AND status != 'hidden'""",
                (company,),
            ).fetchall()
        for row in rows:
            values[row["field_key"]] = row["final_value"] or ""
    return values


def _get_research_field_values(research_db: str, company: str) -> dict[str, str]:
    import sqlite3
    values: dict[str, str] = {}
    with sqlite3.connect(research_db) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT field_key, field_value FROM research_fields
                   WHERE company_name=? AND version='standard'""",
                (company,),
            ).fetchall()
            for row in rows:
                values[row["field_key"]] = row["field_value"] or ""
        except sqlite3.Error:
            pass
    return values


def _format_bundle_value(value: str) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]"):
        try:
            items = json.loads(text)
            if isinstance(items, list):
                lines = []
                for item in items:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("title") or item.get("round") or item.get("type") or ""
                        detail = item.get("summary") or item.get("description") or item.get("amount") or item.get("url") or ""
                        lines.append(f"- **{name}**：{detail}" if detail else f"- {name or json.dumps(item, ensure_ascii=False)}")
                    else:
                        lines.append(f"- {item}")
                return "\n".join(lines)
        except Exception:
            return text
    return text


def build_page_payload(
    company: str,
    page_no: int,
    card_set_key: str = "v3",
    composition_db: str | None = None,
    final_db: str | None = None,
    research_db: str | None = None,
) -> dict:
    """Build one page payload from default card config and final/research fields."""
    from config import config
    from repositories.card_config_repo import get_default_card_configs

    composition_db = composition_db or config.DB_PATH_COMPOSITION
    final_db = final_db or config.DB_PATH_FINAL
    research_db = research_db or config.DB_PATH_RESEARCH
    configs = get_default_card_configs(composition_db, set_key=card_set_key)
    by_page = {cfg["card_index"]: cfg for cfg in configs}
    schema = by_page.get(page_no)
    if not schema:
        raise ValueError(f"page_no not found for {card_set_key}: {page_no}")
    config_json = schema.get("config") or {}
    final_values = _get_final_values(final_db, company, card_set_key)
    research_values = _get_research_field_values(research_db, company)
    fields = {}
    for field_key in config_json.get("fields", []):
        fields[field_key] = final_values.get(field_key, research_values.get(field_key, ""))
    return {
        "company_name": company,
        "card_set_key": card_set_key,
        "page_no": page_no,
        "card_id": schema["card_id"],
        "title": schema["card_title"],
        "template_id": config_json.get("template_id", ""),
        "fields": fields,
        "media": config_json.get("media", []),
        "evidence_footnotes": [],
    }


def _page_to_markdown(page: dict) -> str:
    lines = [f"## {page['page_no']}. {page['title']}", ""]
    for key, value in page.get("fields", {}).items():
        formatted = _format_bundle_value(value)
        if formatted:
            lines.append(f"**{key}**：")
            lines.append(formatted)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_minimal_pdf(path: Path, title: str, pages: list[dict]) -> None:
    text = title + "\n" + "\n".join(f"{p['page_no']}. {p['title']}" for p in pages)
    stream = f"BT /F1 12 Tf 72 760 Td ({_pdf_escape(text[:800])}) Tj ET"
    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj",
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        f"5 0 obj << /Length {len(stream.encode('latin-1', 'ignore'))} >> stream\n{stream}\nendstream endobj",
    ]
    content = "%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(content.encode("latin-1")))
        content += obj + "\n"
    xref = len(content.encode("latin-1"))
    content += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n"
    for off in offsets[1:]:
        content += f"{off:010d} 00000 n \n"
    content += f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(content.encode("latin-1", "ignore"))


def _pdf_escape(text: str) -> str:
    safe = text.encode("latin-1", "ignore").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\n", " /  ")


def build_notion_blocks(pages: list[dict]) -> dict:
    children = []
    for page in pages:
        page_children = []
        for key, value in page.get("fields", {}).items():
            formatted = _format_bundle_value(value)
            if formatted:
                page_children.append({
                    "type": "paragraph",
                    "rich_text": [{"type": "text", "text": {"content": f"{key}: {formatted}"}}],
                })
        children.append({
            "type": "heading_2",
            "rich_text": [{"type": "text", "text": {"content": f"{page['page_no']}. {page['title']}"}}],
            "children": page_children,
        })
    return {"type": "notion_block_tree", "children": children}


def render_export_bundle(
    company: str,
    card_set_key: str = "v3",
    composition_db: str | None = None,
    final_db: str | None = None,
    research_db: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """Export v3 pages to Markdown, a PDF placeholder, and Notion block JSON."""
    from config import config

    composition_db = composition_db or config.DB_PATH_COMPOSITION
    final_db = final_db or config.DB_PATH_FINAL
    research_db = research_db or config.DB_PATH_RESEARCH
    output = Path(output_dir or (Path(__file__).resolve().parents[2] / "output" / "bundles" / company))
    output.mkdir(parents=True, exist_ok=True)

    page_count = 8 if card_set_key != "v2" else 7
    pages = [
        build_page_payload(company, page_no, card_set_key, composition_db, final_db, research_db)
        for page_no in range(1, page_count + 1)
    ]
    markdown_path = output / f"{company}_{card_set_key}.md"
    markdown_path.write_text("\n".join(_page_to_markdown(p) for p in pages), encoding="utf-8")
    pdf_path = output / f"{company}_{card_set_key}.pdf"
    _write_minimal_pdf(pdf_path, f"{company} {card_set_key}", pages)
    notion_payload = build_notion_blocks(pages)
    notion_path = output / f"{company}_{card_set_key}_notion.json"
    notion_path.write_text(json.dumps(notion_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "pages": pages,
        "markdown": str(markdown_path),
        "pdf": str(pdf_path),
        "notion": notion_payload,
        "notion_json": str(notion_path),
    }


def run_export(job_id: str, project_root: str):
    """后台执行导出任务"""
    job = _export_jobs.get(job_id)
    if not job:
        return

    job["status"] = "running"
    company = job["company_name"]
    card_ids = job["card_ids"]
    fmt = job.get("format", "png")
    scale = job.get("scale", 2)
    set_key = job.get("card_set_key", "v1")

    try:
        # 加载 render-data
        import sqlite3
        from config import config

        # 获取启用卡片
        from repositories.card_config_repo import get_enabled_cards, get_card_items, get_card
        from repositories.template_repo import get_template
        from repositories.layout_repo import get_layout

        cards = []
        if card_ids:
            for cid in card_ids:
                card = get_card(config.DB_PATH_COMPOSITION, company, cid, card_set_key=set_key)
                if card and card.get("enabled"):
                    items = get_card_items(config.DB_PATH_COMPOSITION, company, cid, card_set_key=set_key)
                    card["items"] = items
                    cards.append(card)
        else:
            cards = get_enabled_cards(config.DB_PATH_COMPOSITION, company, card_set_key=set_key)
            for card in cards:
                card["items"] = get_card_items(config.DB_PATH_COMPOSITION, company, card["card_id"], card_set_key=set_key)

        # 加载模板和排版
        for card in cards:
            tid = card.get("template_id")
            if tid:
                tpl = get_template(config.DB_PATH_TEMPLATE, tid)
                card["template_json"] = tpl.get("template_json") if tpl else None
            layout = get_layout(config.DB_PATH_TEMPLATE, company, card["card_id"])
            if layout:
                card["layout_json"] = layout.get("layout_json")
                # 应用 layout overrides 到 template
                if card.get("template_json") and layout.get("layout_json"):
                    overrides = layout["layout_json"].get("overrides", {})
                    regions = card["template_json"].get("regions", [])
                    for r in regions:
                        rid = r.get("id", "")
                        if rid in overrides:
                            _deep_merge_region(r, overrides[rid])

        if not cards:
            job["status"] = "failed"
            job["error"] = "没有可导出的卡片"
            return

        # 解析每个卡片的内容
        from repositories.field_repo import get_final_field_value, get_research_field_value, _EMPTY_FINAL
        from asset_store import ensure_assets_rows, get_asset
        ensure_assets_rows(config.DB_PATH_ASSETS, company)

        output_dir = Path(project_root) / "output" / "cards" / company / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        files = []

        for card in cards:
            # 解析 items
            resolved_items = []
            for item in card.get("items", []):
                resolved = dict(item)
                if item["item_type"] == "field":
                    raw = get_final_field_value(config.DB_PATH_FINAL, company, item["item_key"])
                    if raw is _EMPTY_FINAL:
                        resolved["value"] = ""
                    elif raw is not None:
                        resolved["value"] = raw
                    else:
                        resolved["value"] = get_research_field_value(config.DB_PATH_RESEARCH, company, item["item_key"]) or ""
                elif item["item_type"] == "media":
                    media = get_asset(config.DB_PATH_ASSETS, company, item["item_key"]) or {}
                    resolved["url"] = media.get("local_path", "")
                resolved_items.append(resolved)

            # 生成 HTML
            html = _build_card_html(card, resolved_items)

            # 保存 HTML 文件
            html_path = output_dir / f"{card['card_id']}.html"
            html_path.write_text(html, encoding="utf-8")

            # Playwright 截图（走 HTTP 拦截模式，图片从本地文件系统加载，等同浏览器效果）
            png_path = output_dir / f"{card['card_id']}.png"
            tpl = card.get("template_json")
            if isinstance(tpl, str):
                try: tpl = json.loads(tpl)
                except Exception: tpl = _default_template()
            canvas = (tpl or {}).get("canvas", {"width": 900, "height": 1200})
            w, h = canvas.get("width", 900), canvas.get("height", 1200)

            try:
                _html_to_png_http(html, str(png_path), project_root,
                                  width=w, height=h, scale=scale)
                if png_path.exists() and png_path.stat().st_size > 512:
                    files.append(str(png_path))
                else:
                    files.append(str(html_path))
            except Exception:
                files.append(str(html_path))

        # 多文件导出统一打包，避免“全部卡片 + PNG”下载时只返回第一张。
        if len(files) > 1:
            zip_path = output_dir / f"{company}_{set_key}_cards.zip"
            _create_zip(files, str(zip_path))
            job["download_url"] = f"/api/export/{company}/download/{job_id}"
            job["files"] = [str(zip_path)]
        else:
            job["download_url"] = f"/api/export/{company}/download/{job_id}"
            job["files"] = files

        job["status"] = "done"
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)


def _html_to_png_http(html: str, dest: str, project_root: str,
                      width: int = 900, height: int = 1200, scale: int = 2):
    """用 Playwright setContent + 图片拦截，等同浏览器渲染效果"""
    from playwright.sync_api import sync_playwright
    from asset_pipeline import _find_chromium
    images_dir = str((Path(project_root) / "images").resolve())

    # 注入 <base> 让相对路径 /images/... 解析为 http://127.0.0.1:5050/images/...
    base_tag = '<base href="http://127.0.0.1:5050/">'
    html = html.replace("<head>", f"<head>{base_tag}", 1)
    if base_tag not in html:
        html = html.replace("<html>", f"<html><head>{base_tag}</head>", 1)

    with sync_playwright() as p:
        exe = _find_chromium()
        if not exe:
            raise RuntimeError("找不到 Chromium。执行 'playwright install chromium'")
        browser = p.chromium.launch(
            headless=True, executable_path=exe,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            page = browser.new_page(viewport={"width": width, "height": height},
                                    device_scale_factor=scale)
            # 拦截 /images/ 请求，从本地文件系统返回
            page.route("**/images/**", lambda route: _serve_local_image(route, images_dir))
            page.set_content(html, wait_until="networkidle", timeout=20000)
            try:
                page.wait_for_function("document.fonts && document.fonts.ready", timeout=5000)
            except Exception:
                pass
            page.screenshot(path=dest, full_page=False, clip={
                "x": 0, "y": 0, "width": width, "height": height,
            })
        finally:
            browser.close()


def _serve_local_image(route, images_dir: str):
    """Playwright route 拦截：将 /images/xxx 映射到本地 images_dir/xxx"""
    import urllib.parse
    url_path = urllib.parse.urlparse(route.request.url).path
    local_path = _local_image_path_for_url(url_path, images_dir)
    if not local_path:
        route.abort()
        return
    if local_path.is_file():
        ext = local_path.suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".svg": "image/svg+xml", ".gif": "image/gif"}
        with local_path.open("rb") as f:
            route.fulfill(
                status=200,
                content_type=mime_map.get(ext, "application/octet-stream"),
                body=f.read(),
            )
    else:
        route.abort()


def _local_image_path_for_url(url_path: str, images_dir: str) -> Path | None:
    """将浏览器 /images/... 路径安全映射到项目 images 目录内。"""
    import urllib.parse
    rel = urllib.parse.unquote(str(url_path or "").split("?", 1)[0]).lstrip("/")
    if rel == "images":
        return None
    if rel.startswith("images/"):
        rel = rel[len("images/"):]
    if not rel:
        return None
    base = Path(images_dir).resolve()
    target = (base / rel).resolve()
    if target != base and base in target.parents:
        return target
    return None


def _build_card_html(card: dict, items: list[dict]) -> str:
    """用 template + items 生成卡片 HTML"""
    layout_json = card.get("layout_json") or {}
    if isinstance(layout_json, str):
        try:
            layout_json = json.loads(layout_json)
        except Exception:
            layout_json = {}
    if layout_json.get("mode") == "markdown_first" and layout_json.get("markdown"):
        return _build_markdown_card_html(card, items, layout_json)

    template = card.get("template_json")
    # template_json may already be loaded as dict by run_export
    if isinstance(template, str):
        try: template = json.loads(template)
        except Exception: template = None
    if not template:
        template = _default_template()

    canvas = template.get("canvas", {"width": 900, "height": 1200})
    bg = template.get("background", {"type": "color", "value": "#FFFFFF"})
    bg_style = _bg_style(bg)
    regions = template.get("regions", [])
    decorations = template.get("decorations", [])

    # 按 role 分组
    role_map = {}
    for item in items:
        role = item.get("display_role", "body")
        role_map.setdefault(role, []).append(item)

    # 构建 region HTML
    region_html_parts = []
    for r in regions:
        role = r.get("role", "body")
        rtype = r.get("type", "text")
        style = _region_style(r)

        if rtype in ("image", "chart", "logo"):
            candidates = role_map.get(role) or role_map.get("hero_image") or role_map.get("chart") or []
            url = candidates[0].get("url", "") if candidates else ""
            if url:
                fit = (r.get("style") or {}).get("objectFit", "contain")
                region_html_parts.append(
                    f'<img src="{_esc_attr(url)}" style="{style}object-fit:{fit};display:block" alt="">')
            else:
                region_html_parts.append(
                    f'<div style="{style}display:flex;align-items:center;justify-content:center;color:rgba(0,0,0,0.1);font-size:14px">[{role}]</div>')
        elif rtype == "shape":
            region_html_parts.append(f'<div style="{style}"></div>')
        elif r.get("value") is not None:
            ta = (r.get("style") or {}).get("textAlign", "left")
            lh = (r.get("style") or {}).get("lineHeight", 1.55)
            region_html_parts.append(
                f'<div style="{style}text-align:{ta};line-height:{lh};white-space:pre-wrap;word-wrap:break-word">{_esc(str(r.get("value") or ""))}</div>')
        else:
            texts = [item.get("value", "") for item in role_map.get(role, role_map.get("body", []))]
            combined = "\n\n".join(t for t in texts if t)
            ta = (r.get("style") or {}).get("textAlign", "left")
            lh = (r.get("style") or {}).get("lineHeight", 1.55)
            region_html_parts.append(
                f'<div style="{style}text-align:{ta};line-height:{lh};white-space:pre-wrap;word-wrap:break-word">{_esc(combined)}</div>')

    deco_html = ""
    for d in decorations:
        if d.get("type") == "noise":
            deco_html += f'<div style="position:absolute;inset:0;opacity:{d.get("opacity",0.05)};pointer-events:none;z-index:1;background-image:url(\'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><filter id=%22n%22><feTurbulence type=%22fractalNoise%22 baseFrequency=%220.7%22/></filter><rect width=%22200%22 height=%22200%22 filter=%22url(%23n)%22 opacity=%220.5%22/></svg>\');background-size:200px"></div>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:{canvas.get("width",900)}px; height:{canvas.get("height",1200)}px; overflow:hidden; position:relative; {bg_style} }}
</style></head><body>
  {deco_html}
  {"".join(region_html_parts)}
</body></html>"""


def _build_markdown_card_html(card: dict, items: list[dict], layout_json: dict) -> str:
    """用 Markdown-first layout 生成导出 HTML。"""
    style = {
        "fontSize": 32,
        "lineHeight": 1.6,
        "paragraphGap": 22,
        "padding": 74,
        "bgColor": "#FFFFFF",
        "textColor": "#172033",
        "accentColor": "#29B8D4",
        "imageMaxHeight": 360,
    }
    style.update(layout_json.get("style") or {})
    markdown = str(layout_json.get("markdown") or "")
    media_by_key = {
        item.get("item_key"): item
        for item in items
        if item.get("item_type") == "media"
    }
    body = _render_markdown_to_html(markdown, media_by_key)
    font_size = _num(style.get("fontSize"), 30)
    line_height = _num(style.get("lineHeight"), 1.45)
    paragraph_gap = _num(style.get("paragraphGap"), 16)
    padding = _num(style.get("padding"), 64)
    image_max_h = _num(style.get("imageMaxHeight"), 360)
    bg_color = style.get("bgColor") or "#FFFFFF"
    text_color = style.get("textColor") or _readable_text_color(bg_color)
    accent_color = style.get("accentColor") or "#29B8D4"
    is_observation_cover = (
        style.get("skin") == "ai_observation_cover"
        or layout_json.get("template_id") == "cover_ai_observation_v4"
    )
    body_class = "layout-skin-observation" if is_observation_cover else ""
    observation_skin_css = ""
    if is_observation_cover:
        observation_skin_css = """
  body.layout-skin-observation {
    background: #061A3A;
  }
  body.layout-skin-observation::after {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    background:
      linear-gradient(90deg, transparent 0 76%, rgba(90, 215, 255, .12) 76% 89%, rgba(247, 251, 255, .08) 89% 92%, transparent 92%),
      linear-gradient(180deg, rgba(255,255,255,.08), transparent 22%, transparent 76%, rgba(255,255,255,.08));
  }
  body.layout-skin-observation::before {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 2;
    opacity: .10;
    mix-blend-mode: screen;
    background-image: url('data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22180%22 height=%22180%22><filter id=%22n%22><feTurbulence type=%22fractalNoise%22 baseFrequency=%221.05%22 numOctaves=%223%22 stitchTiles=%22stitch%22/></filter><rect width=%22180%22 height=%22180%22 filter=%22url(%23n)%22 opacity=%220.70%22/></svg>');
    background-size: 180px 180px;
  }
  body.layout-skin-observation .layout-md-card {
    z-index: 1;
    padding: 96px;
  }
  body.layout-skin-observation .layout-md-card::before,
  body.layout-skin-observation .layout-md-card::after {
    content: "";
    position: absolute;
    left: 96px;
    right: 96px;
    height: 2px;
    background: rgba(247, 251, 255, .72);
  }
  body.layout-skin-observation .layout-md-card::before { top: 92px; background: #5AD7FF; }
  body.layout-skin-observation .layout-md-card::after { bottom: 198px; }
  body.layout-skin-observation .layout-md-body {
    position: relative;
    z-index: 1;
    padding-top: 42px;
  }
  body.layout-skin-observation h1 {
    max-width: 708px;
    font-size: 88px;
    line-height: 1.02;
    margin: 34px 0 22px;
    color: #F7FBFF;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
  body.layout-skin-observation h2 {
    max-width: 620px;
    font-size: 30px;
    line-height: 1.1;
    margin: 0;
    color: #5AD7FF;
    font-weight: 800;
  }
  body.layout-skin-observation p {
    max-width: 580px;
    color: rgba(247, 251, 255, .72);
    font-weight: 700;
    overflow-wrap: anywhere;
  }
  body.layout-skin-observation .layout-md-spacer { min-height: 210px; }
"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; width: 900px; height: 1200px; overflow: hidden; }}
  body {{
    background: {bg_color};
    color: {text_color};
    font-family: "Noto Sans SC", "Instrument Sans", sans-serif;
    font-size: {font_size}px;
    line-height: {line_height};
    letter-spacing: 0;
  }}
  .layout-md-card {{
    position: relative;
    width: 900px;
    height: 1200px;
    padding: {padding}px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}
  .layout-md-body {{
    flex: 1;
    display: flex;
    flex-direction: column;
  }}
  .layout-md-spacer {{ flex: 1; }}
  .layout-md-body > * {{ margin: 0 0 {paragraph_gap}px; }}
  .layout-md-body > *:last-child {{ margin-bottom: 0; }}
  h1, h2, h3 {{ margin-top: 0; }}
  h1 {{
    font-size: {round(font_size * 1.9)}px;
    line-height: 1.08;
    font-weight: 900;
    color: {text_color};
    margin-bottom: {round(paragraph_gap * 1.4)}px;
  }}
  h2 {{ font-size: {round(font_size * 1.28)}px; line-height: 1.16; color: {accent_color}; font-weight: 800; }}
  h3 {{ font-size: {round(font_size * 1.05)}px; line-height: 1.2; color: {text_color}; font-weight: 700; }}
  p, li, blockquote {{ word-wrap: break-word; }}
  ul {{ padding-left: 1.2em; }}
  blockquote {{
    border-left: 6px solid {accent_color};
    padding: 10px 14px;
    background: rgba(41, 184, 212, .09);
    border-radius: 0 8px 8px 0;
  }}
  strong {{ font-weight: 900; }}
  em {{ font-style: italic; }}
  a {{ color: {accent_color}; text-decoration: none; }}
  img.layout-md-image, .layout-asset img {{
    display: block;
    max-width: 100%;
    max-height: {image_max_h}px;
    object-fit: contain;
    border-radius: 10px;
  }}
  .layout-asset {{
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 120px;
    border-radius: 12px;
    background: rgba(15, 23, 42, .04);
    overflow: hidden;
  }}
  .layout-asset-missing {{
    padding: 18px;
    color: rgba(15, 23, 42, .38);
    border: 1px dashed rgba(15, 23, 42, .18);
  }}
{observation_skin_css}
</style></head><body class="{body_class}">
  <article class="layout-md-card" data-od-id="card-root">
    <div class="layout-md-body">{body}</div>
  </article>
</body></html>"""


def _render_markdown_to_html(markdown: str, media_by_key: dict) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    html = []
    list_open = False

    def close_list():
        nonlocal list_open
        if list_open:
            html.append("</ul>")
            list_open = False

    def _unwrap_inline(line):
        m = re.match(r"^(<(span|mark|center)\b[^>]*>)(.*?)(</\2>)$", line, re.I)
        return (m.group(1), m.group(4), m.group(3).strip()) if m else None

    def _extract_font_size(open_tag):
        m = re.search(r"font-size:\s*(\d+)px", open_tag or "", re.I)
        return f' style="font-size:{m.group(1)}px"' if m else ""

    def _heading_tag(level, wrap, inner):
        extra = _extract_font_size(wrap[0]) if wrap else ""
        content = _inline_markdown(inner)
        if wrap:
            clean_open = re.sub(r"font-size:\s*\d+px;?", "", wrap[0], flags=re.I)
            return f"{clean_open}<h{level}{extra}>{content}</h{level}>{wrap[1]}"
        return f"<h{level}>{content}</h{level}>"

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            close_list()
            continue
        wrap = _unwrap_inline(line)
        body = wrap[2] if wrap else line
        asset_match = re.match(r"^\{\{([a-zA-Z0-9_:-]+)\}\}$", body)
        image_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", body)
        if asset_match:
            close_list()
            html.append(_asset_html(asset_match.group(1), media_by_key))
        elif image_match:
            close_list()
            if wrap:
                html.append(f'{wrap[0]}<p><img class="layout-md-image" src="{_esc_attr(image_match.group(2))}" alt="{_esc_attr(image_match.group(1))}"></p>{wrap[1]}')
            else:
                html.append(f'<p><img class="layout-md-image" src="{_esc_attr(image_match.group(2))}" alt="{_esc_attr(image_match.group(1))}"></p>')
        elif body.startswith("# "):
            close_list()
            html.append(_heading_tag(1, wrap, body[2:]))
        elif body.startswith("## "):
            close_list()
            html.append(_heading_tag(2, wrap, body[3:]))
        elif body.startswith("### "):
            close_list()
            html.append(_heading_tag(3, wrap, body[4:]))
        elif body == "---":
            close_list()
            if wrap:
                html.append(f'{wrap[0]}<div class="layout-md-spacer"></div>{wrap[1]}')
            else:
                html.append('<div class="layout-md-spacer"></div>')
        elif body.startswith("> "):
            close_list()
            if wrap:
                html.append(f'{wrap[0]}<blockquote>{_inline_markdown(body[2:])}</blockquote>{wrap[1]}')
            else:
                html.append(f"<blockquote>{_inline_markdown(body[2:])}</blockquote>")
        elif re.match(r"^[-*]\s+", body):
            if not list_open:
                html.append("<ul>")
                list_open = True
            item_text = re.sub(r"^[-*]\s+", "", body)
            if wrap:
                html.append(f'{wrap[0]}<li>{_inline_markdown(item_text)}</li>{wrap[1]}')
            else:
                html.append(f"<li>{_inline_markdown(item_text)}</li>")
        else:
            close_list()
            html.append(f"<p>{_inline_markdown(line)}</p>")
    close_list()
    return "\n".join(html)


def _inline_markdown(text: str) -> str:
    preserved = []

    def preserve(match):
        token = f"@@HTML_{len(preserved)}@@"
        preserved.append(match.group(0))
        return token

    # 先保护 <span>/<mark> 整标签 和 <br> 标签，避免被转义
    safe = re.sub(r"<(span|mark)\b[^>]*>.*?</\1>", preserve, text, flags=re.I)
    safe = re.sub(r"<br\s*/?>", preserve, safe, flags=re.I)
    safe = _esc(safe)
    safe = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", safe)
    safe = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{_esc_attr(m.group(2))}">{m.group(1)}</a>',
        safe,
    )
    for idx, html in enumerate(preserved):
        safe = safe.replace(f"@@HTML_{idx}@@", _sanitize_inline_html(html))
    return safe


def _asset_html(key: str, media_by_key: dict) -> str:
    media = media_by_key.get(key) or {}
    url = media.get("url") or media.get("local_path") or ""
    if not url:
        return f'<div class="layout-asset layout-asset-missing">{{{{{_esc(key)}}}}} 未选择素材</div>'
    return (
        f'<figure class="layout-asset" data-asset-key="{_esc_attr(key)}">'
        f'<img src="{_esc_attr(url)}" alt="{_esc_attr(media.get("media_label") or key)}">'
        f"</figure>"
    )


def _sanitize_inline_html(html: str) -> str:
    html = re.sub(r"<(?!/?(span|mark|br)\b)", "&lt;", html, flags=re.I)
    html = re.sub(r"\son[a-z]+\s*=", " data-blocked=", html, flags=re.I)
    html = re.sub(r"javascript:", "", html, flags=re.I)
    return html


def _num(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _readable_text_color(hex_color: str) -> str:
    m = re.match(r"^#?([0-9a-fA-F]{6})$", str(hex_color or "").strip())
    if not m:
        return "#172033"
    raw = m.group(1)
    red = int(raw[0:2], 16)
    green = int(raw[2:4], 16)
    blue = int(raw[4:6], 16)
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#F8FAFC" if luminance < 0.52 else "#172033"


def _default_template() -> dict:
    return {
        "canvas": {"width": 900, "height": 1200},
        "background": {"type": "color", "value": "#FFFFFF"},
        "regions": [
            {"id": "title", "type": "text", "role": "title", "x": 68, "y": 80, "w": 764, "h": 90,
             "style": {"fontFamily": "Noto Sans SC", "fontSize": 48, "fontWeight": 700, "color": "#111", "textAlign": "left"}},
            {"id": "body", "type": "text", "role": "body", "x": 68, "y": 200, "w": 764, "h": 920,
             "style": {"fontFamily": "Noto Sans SC", "fontSize": 24, "fontWeight": 400, "color": "#333", "lineHeight": 1.55}},
        ],
        "decorations": [],
    }


def _bg_style(bg: dict) -> str:
    if not bg:
        return "background:#FFFFFF;"
    t = bg.get("type", "color")
    v = bg.get("value", "#FFFFFF")
    if t == "gradient":
        return f"background:{v};"
    if t == "image":
        return f"background:url({v}) center/cover;"
    return f"background:{v};"


def _region_style(r: dict) -> str:
    s = r.get("style") or {}
    css = [
        f"position:absolute",
        f"left:{r.get('x',0)}px",
        f"top:{r.get('y',0)}px",
        f"width:{r.get('w',100)}px",
        f"height:{r.get('h',100)}px",
    ]
    if s.get("fontFamily"): css.append(f"font-family:'{s['fontFamily']}','Noto Sans SC',sans-serif")
    if s.get("fontSize"): css.append(f"font-size:{s['fontSize']}px")
    if s.get("fontWeight"): css.append(f"font-weight:{s['fontWeight']}")
    if s.get("color"): css.append(f"color:{s['color']}")
    if s.get("letterSpacing"): css.append(f"letter-spacing:{s['letterSpacing']}")
    if s.get("opacity") is not None: css.append(f"opacity:{s['opacity']}")
    if s.get("borderRadius"): css.append(f"border-radius:{s['borderRadius']}px")
    if s.get("borderWidth") and s.get("borderColor"):
        css.append(f"border:{s['borderWidth']}px solid {s['borderColor']}")
    if s.get("shadow"): css.append(f"box-shadow:{s['shadow']}")
    if s.get("backgroundColor"): css.append(f"background:{s['backgroundColor']}")
    css.append("overflow:hidden")
    return ";".join(css) + ";"


def _deep_merge_region(base: dict, override: dict):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge_region(base[k], v)
        else:
            base[k] = v


def _create_zip(file_paths: list[str], dest: str):
    import zipfile
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in file_paths:
            zf.write(fp, os.path.basename(fp))


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace('"', "&quot;")
