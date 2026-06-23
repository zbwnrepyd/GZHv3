"""自动图片采集管道 — logo / office / product / competitors / other_products"""
from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import shutil

import requests

from config import config
from path_safety import safe_path_segment
from asset_store import (
    ASSET_KEYS, ASSET_TO_CARD, CARD_ASSET_MAP,
    ensure_assets_rows, upsert_asset, get_asset,
    insert_variant, list_variants, select_variant,
)
from image_query import build_image_queries
from image_candidate import ImageCandidate
from image_quality import inspect_local_image, validate_candidate
from image_scorer import score_candidate
from pipeline import _search_tavily_query


def asset_dir(images_root: str, company_name: str, company_key: str = "") -> str:
    """返回某公司的图片目录，确保存在。优先用 company_key 做路径片段。"""
    seg = _safe_path_segment(company_key or company_name)
    d = os.path.join(images_root, seg)
    os.makedirs(d, exist_ok=True)
    return d


def _safe_path_segment(value) -> str:
    return safe_path_segment(value)


def _company_image_dir(images_root: str, company_name: str, *parts: str,
                       company_key: str = "") -> str:
    base = os.path.abspath(images_root)
    seg = _safe_path_segment(company_key or company_name)
    target = os.path.abspath(os.path.join(base, seg, *parts))
    if os.path.commonpath([base, target]) != base:
        raise ValueError("公司图片目录越界")
    return target


def _image_url_path(company_name: str, *parts: str, company_key: str = "") -> str:
    seg = _safe_path_segment(company_key or company_name)
    url_parts = [seg, *[str(p) for p in parts]]
    return "/images/" + "/".join(quote(p, safe="") for p in url_parts)


def _variant_url_path(company_name: str, filename: str, company_key: str = "") -> str:
    return _image_url_path(company_name, "variants", filename, company_key=company_key)


def _variant_path(images_root: str, company_name: str, asset_key: str, suffix,
                  company_key: str = "") -> str:
    """生成变体文件路径，确保 variants 子目录存在"""
    d = _company_image_dir(images_root, company_name, "variants", company_key=company_key)
    os.makedirs(d, exist_ok=True)
    safe_asset_key = _safe_path_segment(asset_key)
    safe_suffix = _safe_path_segment(suffix)
    return os.path.join(d, f"{safe_asset_key}__{safe_suffix}.png")


def _variant_browser_path(company_name: str, file_path: str, company_key: str = "") -> str:
    return _variant_url_path(company_name, os.path.basename(file_path), company_key=company_key)


def _collect_candidates(
    db_path: str, images_root: str, company_name: str, asset_key: str,
    sources: list[dict],
    max_candidates: int = 3,
    company_key: str = "",
) -> int:
    """
    依次尝试 sources，成功则写 image_variants。
    不 select，不写 company_assets.local_path。
    返回实际写入数量。
    """
    from asset_store import insert_variant
    count = 0
    for src in sources:
        if count >= max_candidates:
            break
        dest = _variant_path(images_root, company_name, asset_key, count,
                           company_key=company_key)
        ok, source_url = False, ""

        if src["type"] == "scrape":
            img_url = _scrape_page_hero_image(src.get("url", ""))
            if img_url:
                ok = _download(img_url, dest)
                source_url = img_url

        elif src["type"] == "playwright":
            if src.get("url"):
                try:
                    _playwright_screenshot(src["url"], dest)
                    ok = os.path.getsize(dest) > 512
                    source_url = src["url"]
                except Exception:
                    pass

        elif src["type"] == "tavily":
            img_url = _try_tavily_images(src["query"], dest)
            ok = bool(img_url)
            source_url = img_url or ""

        elif src["type"] == "clearbit":
            url = f"https://logo.clearbit.com/{src['domain']}"
            ok = _download(url, dest)
            source_url = url

        if ok:
            insert_variant(db_path, company_name, asset_key,
                           local_path=_variant_browser_path(company_name, dest, company_key=company_key),
                           source_type=f"screenshot_{src['type']}",
                           source_url=source_url,
                           company_key=company_key)
            count += 1
    return count


def _download(url: str, dest: str, timeout: int = 15) -> bool:
    """下载 URL 到本地文件，返回是否成功"""
    try:
        resp = requests.get(url, timeout=timeout,
                          headers={"User-Agent": "Mozilla/5.0"},
                          stream=True)
        if resp.status_code >= 400:
            return False
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return os.path.getsize(dest) > 512
    except Exception:
        return False


def _persist_local_candidate(
    db_path: str,
    company_name: str,
    asset_key: str,
    dest: str,
    source_type: str,
    source_url: str = "",
    source_page: str = "",
    title: str = "",
    alt_text: str = "",
    author: str = "",
    license_text: str = "",
    prompt: str = "",
    meta: dict | None = None,
) -> bool:
    """Inspect, validate, score, and persist a downloaded candidate variant."""
    from asset_store import insert_variant

    candidate = ImageCandidate(
        company_name=company_name,
        asset_key=asset_key,
        image_url=source_url or _variant_browser_path(company_name, dest),
        source_page=source_page or "",
        source_type=source_type,
        title=title or prompt,
        alt_text=alt_text,
        author=author,
        license=license_text,
        local_path=dest,
        meta=meta or {},
    )
    inspect_local_image(candidate)
    passed, reason = validate_candidate(candidate)
    if passed:
        score_candidate(candidate, product_names=[company_name])
    else:
        candidate.reject_reason = reason

    insert_variant(
        db_path,
        company_name,
        asset_key,
        local_path=_variant_browser_path(company_name, dest),
        source_type=source_type,
        source_url=source_url,
        source_page=source_page,
        author=author,
        license=license_text,
        prompt=prompt,
        width=candidate.width,
        height=candidate.height,
        file_size=candidate.file_size,
        aspect_ratio=candidate.aspect_ratio,
        quality_score=candidate.quality_score,
        relevance_score=candidate.relevance_score,
        source_score=candidate.source_score,
        final_score=candidate.final_score,
        reject_reason=candidate.reject_reason,
        meta=candidate.meta,
    )
    return passed


def _persist_generated_candidate(
    db_path: str,
    company_name: str,
    asset_key: str,
    dest: str,
    source_type: str,
    source_url: str = "",
    prompt: str = "",
    meta: dict | None = None,
) -> int:
    """Persist a trusted locally generated image without scraped-image rejection rules."""
    from asset_store import insert_variant

    candidate = ImageCandidate(
        company_name=company_name,
        asset_key=asset_key,
        image_url=_variant_browser_path(company_name, dest),
        source_page="",
        source_type=source_type,
        title=prompt,
        local_path=dest,
        meta=meta or {},
    )
    inspect_local_image(candidate)
    candidate.quality_score = 1.0
    candidate.relevance_score = 1.0
    candidate.source_score = 1.0
    candidate.final_score = 1.0
    return insert_variant(
        db_path,
        company_name,
        asset_key,
        local_path=_variant_browser_path(company_name, dest),
        source_type=source_type,
        source_url=source_url,
        prompt=prompt,
        width=candidate.width,
        height=candidate.height,
        file_size=candidate.file_size,
        aspect_ratio=candidate.aspect_ratio,
        quality_score=candidate.quality_score,
        relevance_score=candidate.relevance_score,
        source_score=candidate.source_score,
        final_score=candidate.final_score,
        meta=candidate.meta,
    )


def _collect_downloaded_candidate(
    db_path: str,
    images_root: str,
    company_name: str,
    asset_key: str,
    image_url: str,
    source_type: str,
    suffix: str,
    source_page: str = "",
    title: str = "",
    alt_text: str = "",
    prompt: str = "",
) -> bool:
    dest = _variant_path(images_root, company_name, asset_key, suffix)
    if not _download(image_url, dest, timeout=30):
        return False
    return _persist_local_candidate(
        db_path,
        company_name,
        asset_key,
        dest,
        source_type,
        source_url=image_url,
        source_page=source_page,
        title=title,
        alt_text=alt_text,
        prompt=prompt,
    )


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    return urlparse(url).netloc or ""


# ═══════════════════════════════════════════════════════════════
# 1. Logo
# ═══════════════════════════════════════════════════════════════

def _extract_logo_from_website(website_url: str) -> str | None:
    """从官网 HTML 提取 logo 图片 URL。按可靠性优先级：
    1. <link rel="icon/apple-touch-icon">
    2. <meta property="og:image">
    3. <img> 含 logo 关键词（src/alt/class/id）
    4. header 内的第一个 img
    返回绝对 URL 或 None。
    """
    from bs4 import BeautifulSoup
    import re

    try:
        resp = requests.get(
            website_url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
            timeout=15, allow_redirects=True,
        )
    except Exception:
        return None

    if resp.status_code >= 400:
        return None

    base_url = resp.url  # 最终请求的 URL（处理了重定向）
    soup = BeautifulSoup(resp.text, "lxml")

    def _abs(src: str) -> str:
        """解析相对 URL"""
        if not src:
            return ""
        src = src.strip()
        if src.startswith("data:"):
            return ""
        if src.startswith("http"):
            return src
        if src.startswith("//"):
            return f"https:{src}"
        if src.startswith("/"):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{src}"
        return f"{base_url.rstrip('/')}/{src}"

    # 1. <link> 图标 — 优先大尺寸（apple-touch-icon > icon）
    for rel in ("apple-touch-icon", "apple-touch-icon-precomposed", "icon", "shortcut icon"):
        for tag in soup.find_all("link", rel=rel):
            href = tag.get("href", "")
            if href:
                return _abs(href)
        # 也检查 rel 含 "icon" 的情况 (如 "fluid-icon")
        for tag in soup.find_all("link"):
            r = (tag.get("rel") or [""])[0] if isinstance(tag.get("rel"), list) else tag.get("rel", "")
            if "icon" in str(r).lower() and tag.get("href"):
                icon_url = _abs(tag.get("href", ""))
                if icon_url:
                    return icon_url

    # 2. og:image
    for tag in soup.find_all("meta", property="og:image"):
        src = tag.get("content", "")
        if src:
            return _abs(src)

    # 3. <img> 含 logo 关键词
    logo_pattern = re.compile(r"logo|brand", re.IGNORECASE)
    candidates = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = img.get("alt") or ""
        cls = " ".join(img.get("class") or [])
        img_id = img.get("id") or ""
        combined = f"{src} {alt} {cls} {img_id}"
        if logo_pattern.search(combined):
            abs_url = _abs(src)
            if abs_url:
                w = int(img.get("width") or 0)
                h = int(img.get("height") or 0)
                candidates.append((w * h if w and h else 5000, abs_url))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    # 4. header 内第一个 img（兜底）
    header = soup.find("header") or soup.find("nav")
    if header:
        img = header.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or ""
            abs_url = _abs(src)
            if abs_url:
                return abs_url

    return None


def collect_logo(db_path: str, images_root: str, company_name: str,
                 company_url: str = "", website_url: str = "",
                 company_key: str = "") -> dict | None:
    domain = _domain_from_url(company_url or website_url)
    if not domain:
        return None

    from asset_store import insert_variant, select_variant
    from PIL import Image

    dest_dir = asset_dir(images_root, company_name)
    os.makedirs(dest_dir, exist_ok=True)

    def _image_size(path):
        """获取本地图片宽高和文件大小，返回 dict。"""
        try:
            with Image.open(path) as im:
                w, h = im.size
            return {"width": w, "height": h, "file_size": os.path.getsize(path)}
        except Exception:
            return None

    def _save_logo_variant(img_path, source_type, source_url, prompt="", auto_select=True):
        """下载好的 logo 写入变体库并设为 selected，更新 company_assets。"""
        # 确保文件在 variants 子目录，与 _variant_browser_path 对齐
        variant_dir = os.path.join(dest_dir, "variants")
        os.makedirs(variant_dir, exist_ok=True)
        variant_dest = os.path.join(variant_dir, os.path.basename(img_path))
        if os.path.abspath(img_path) != os.path.abspath(variant_dest):
            shutil.copy2(img_path, variant_dest)
            img_path = variant_dest

        info = _image_size(img_path)
        w = info["width"] if info else 0
        h = info["height"] if info else 0
        ratio = w / max(h, 1) if h else 1
        variant_id = insert_variant(
            db_path, company_name, "logo",
            local_path=_variant_browser_path(company_name, img_path, company_key=company_key),
            source_type=source_type,
            source_url=source_url,
            width=w, height=h,
            file_size=info.get("file_size", 0) if info else 0,
            aspect_ratio=ratio,
            final_score=90 if 0.7 <= ratio <= 1.5 else 70,
            prompt=prompt,
            company_key=company_key,
        )
        if variant_id and auto_select:
            select_variant(db_path, company_name, "logo", variant_id,
                          auto_selected=True, company_key=company_key)
            upsert_asset(db_path, company_name, "logo", status="ready")
        return variant_id

    # 策略0: 从官网 HTML 提取 logo（最可靠）
    url_to_visit = company_url or website_url
    if url_to_visit:
        logo_url = _extract_logo_from_website(url_to_visit)
        if logo_url:
            dest = os.path.join(dest_dir, "logo_web.png")
            if _download(logo_url, dest, timeout=15):
                vid = _save_logo_variant(dest, "website_extract", logo_url,
                                        prompt="官网提取 logo")
                if vid:
                    return {"local_path": None, "source_type": "website_extract",
                            "source_url": logo_url, "variant_id": vid}

    # 策略1: Clearbit Logo API
    sources = [
        ("clearbit", f"https://logo.clearbit.com/{domain}"),
        # 策略2: Google Favicon (fallback)
        ("favicon", f"https://www.google.com/s2/favicons?domain={domain}&sz=128"),
    ]

    for src_type, url in sources:
        dest = os.path.join(dest_dir, f"logo_{src_type}.png")
        if _download(url, dest, timeout=15):
            vid = _save_logo_variant(dest, src_type, url, prompt=f"{src_type} logo")
            if vid:
                return {"local_path": None, "source_type": src_type,
                        "source_url": url, "variant_id": vid}

    # 策略3: Tavily 搜 logo（只选方形/小尺寸图，过滤办公室照片）
    if company_name:
        logo_urls = _tavily_image_urls(
            f'"{company_name}" logo',
            max_results=5,
        )
        if logo_urls:
            best = None
            for i, img_url in enumerate(logo_urls[:5]):
                variant_dest = os.path.join(dest_dir, f"logo_tavily_{i}.png")
                if not _download(img_url, variant_dest, timeout=15):
                    continue
                info = _image_size(variant_dest)
                if not info:
                    continue
                w, h = info["width"], info["height"]
                ratio = w / max(h, 1)
                if ratio < 0.5 or ratio > 2.0:
                    continue
                if w > 2000 or h > 2000:
                    continue
                vid = _save_logo_variant(variant_dest, "web_tavily", img_url,
                                        prompt="Tavily logo search", auto_select=(best is None))
                if vid:
                    if best is None:
                        best = vid
            if best:
                return {"local_path": None, "source_type": "web_tavily", "variant_id": best}

    upsert_asset(db_path, company_name, "logo", status="failed")
    return None


# ═══════════════════════════════════════════════════════════════
# 2. Office / 地图
# ═══════════════════════════════════════════════════════════════

def _scrape_page_hero_image(page_url: str, company_name: str = "") -> str | None:
    """
    抓取指定页面，找面积最大且非 logo/icon 的 <img>，返回其 src URL。
    用于 About / Newsroom 页提取公司真实照片。
    """
    from bs4 import BeautifulSoup
    try:
        resp = requests.get(page_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")

        candidates = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src or src.startswith("data:"):
                continue
            if any(x in src.lower() for x in ["icon", "logo", "favicon", ".svg"]):
                continue
            if src.startswith("/"):
                base = urlparse(page_url)
                src = f"{base.scheme}://{base.netloc}{src}"
            elif not src.startswith("http"):
                continue
            w = int(img.get("width", 0) or 0)
            h = int(img.get("height", 0) or 0)
            score = w * h if w and h else 50000
            candidates.append((score, src))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]
    except Exception:
        return None


def _extract_og_image(page_url: str) -> str | None:
    """Extract og:image/twitter:image from an official page."""
    from bs4 import BeautifulSoup
    try:
        resp = requests.get(page_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        selectors = [
            ("meta", {"property": "og:image"}),
            ("meta", {"name": "og:image"}),
            ("meta", {"name": "twitter:image"}),
            ("meta", {"property": "twitter:image"}),
        ]
        for tag_name, attrs in selectors:
            tag = soup.find(tag_name, attrs=attrs)
            src = tag.get("content") if tag else ""
            if src:
                if src.startswith("//"):
                    return f"{urlparse(page_url).scheme}:{src}"
                if src.startswith("/"):
                    base = urlparse(page_url)
                    return f"{base.scheme}://{base.netloc}{src}"
                if src.startswith("http"):
                    return src
        return None
    except Exception:
        return None


def collect_office(db_path: str, images_root: str, company_name: str,
                   location: str = "", query_config: dict = None) -> dict | None:
    """
    图片搜索词 v2：
    1. 优先抓官网 About/Newsroom 页提取 hero image
    2. Tavily 搜新闻/媒体图（含公司名，真实照片）
    3. OSM 静态地图兜底
    不用通用图（Lorem Flickr / Picsum）。
    """
    dest_dir = asset_dir(images_root, company_name)
    dest = os.path.join(dest_dir, "office.png")
    cfg = query_config or {}

    # 1. 抓官网 About / Newsroom 页 hero image
    for url in cfg.get("scrape_urls", []):
        img_url = _scrape_page_hero_image(url, company_name)
        if img_url and _download(img_url, dest):
            upsert_asset(db_path, company_name, "office",
                         local_path=f"/images/{company_name}/office.png",
                         source_type="web_scrape", source_url=img_url, status="ready")
            return {"local_path": f"/images/{company_name}/office.png"}

    # 2. Tavily 搜新闻/媒体图
    for query in cfg.get("tavily_queries", []):
        img_url = _try_tavily_images(query, dest)
        if img_url:
            upsert_asset(db_path, company_name, "office",
                         local_path=f"/images/{company_name}/office.png",
                         source_type="web_search", source_url=img_url, status="ready")
            return {"local_path": f"/images/{company_name}/office.png"}

    # 3. OSM 静态地图兜底
    if location:
        map_dest = os.path.join(dest_dir, "office_map.png")
        if _render_osm_map(location, map_dest):
            upsert_asset(db_path, company_name, "office",
                        local_path=f"/images/{company_name}/office_map.png",
                        source_type="osm_map", source_url="", status="ready",
                        meta={"note": "地图替代（未找到办公楼照片）"})
            return {"local_path": f"/images/{company_name}/office_map.png"}

    upsert_asset(db_path, company_name, "office", status="failed")
    return None


# ═══════════════════════════════════════════════════════════════
# 3. 主产品截图（Playwright）
# ═══════════════════════════════════════════════════════════════

def capture_product(db_path: str, images_root: str, company_name: str,
                    website_url: str = "", query_config: dict = None) -> dict | None:
    """
    图片搜索词 v2：
    1. Playwright 截产品页（优先 main_product_img_src，其次官网）
    2. Tavily 搜产品界面图
    不用通用图。
    """
    dest_dir = asset_dir(images_root, company_name)
    dest = os.path.join(dest_dir, "product_main.png")
    cfg = query_config or {}

    # 1. Playwright 截图
    for url in cfg.get("playwright_urls", []):
        if not url:
            continue
        try:
            _playwright_screenshot(url, dest)
            if os.path.getsize(dest) > 512:
                upsert_asset(db_path, company_name, "product_main",
                            local_path=f"/images/{company_name}/product_main.png",
                            source_type="screenshot", source_url=url, status="ready")
                return {"local_path": f"/images/{company_name}/product_main.png"}
        except Exception:
            pass

    # 2. Tavily 搜产品界面图
    for query in cfg.get("tavily_queries", []):
        img_url = _try_tavily_images(query, dest)
        if img_url:
            upsert_asset(db_path, company_name, "product_main",
                         local_path=f"/images/{company_name}/product_main.png",
                         source_type="web_search", source_url=img_url, status="ready")
            return {"local_path": f"/images/{company_name}/product_main.png"}

    upsert_asset(db_path, company_name, "product_main", status="failed")
    return None


# ═══════════════════════════════════════════════════════════════
# 4. 其他产品图（搜索 + 拼接）
# ═══════════════════════════════════════════════════════════════

def collect_other_products(db_path: str, images_root: str, company_name: str,
                           query_config: dict = None) -> dict | None:
    """
    图片搜索词 v2：
    1. Playwright 截各产品页（有 URL 时优先）
    2. Tavily 搜产品界面图
    3. 搜不到该产品跳过
    4. 水平拼接所有找到的图
    不用通用图。
    """
    cfg = query_config or {}
    per_product = cfg.get("per_product", [])
    if not per_product:
        upsert_asset(db_path, company_name, "products_other", status="failed")
        return None

    dest_dir = asset_dir(images_root, company_name)
    product_images = []

    for i, item in enumerate(per_product):
        name = item.get("name", f"product-{i}")
        tmp_dest = os.path.join(dest_dir, f"_tmp_product_{i}.png")

        # 1. Playwright 截产品页（有 URL 时）
        if item.get("playwright_url"):
            try:
                _playwright_screenshot(item["playwright_url"], tmp_dest)
                if os.path.getsize(tmp_dest) > 512:
                    product_images.append(tmp_dest)
                    continue
            except Exception:
                pass

        # 2. Tavily 搜产品界面图
        found = False
        for query in item.get("tavily_queries", []):
            img_url = _try_tavily_images(query, tmp_dest)
            if img_url and os.path.getsize(tmp_dest) > 512:
                product_images.append(tmp_dest)
                found = True
                break

        if not found:
            # 清理空的临时文件
            try:
                os.remove(tmp_dest)
            except OSError:
                pass

    if not product_images:
        upsert_asset(db_path, company_name, "products_other", status="failed")
        return None

    dest = os.path.join(dest_dir, "products_other.png")
    try:
        _composite_horizontal(product_images, dest)
        upsert_asset(db_path, company_name, "products_other",
                    local_path=f"/images/{company_name}/products_other.png",
                    source_type="composite", source_url="", status="ready")
        for tmp in product_images:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return {"local_path": f"/images/{company_name}/products_other.png"}
    except Exception:
        upsert_asset(db_path, company_name, "products_other", status="failed")
        return None


# ═══════════════════════════════════════════════════════════════
# 5. 竞品 Logo 拼图
# ═══════════════════════════════════════════════════════════════

def compose_competitors(db_path: str, images_root: str, company_name: str,
                        query_config: dict = None) -> dict | None:
    """
    图片搜索词 v2：
    1. Playwright 截竞品官网（有 URL 时优先）
    2. Tavily 搜竞品产品截图
    3. Clearbit logo 兜底（竞品卡专属）
    4. Grid 拼图
    不用通用图。
    """
    cfg = query_config or {}
    per_comp = cfg.get("per_comp", [])
    if not per_comp:
        upsert_asset(db_path, company_name, "competitors", status="failed")
        return None

    dest_dir = asset_dir(images_root, company_name)
    comp_images = []

    for i, item in enumerate(per_comp):
        name = item.get("name", f"competitor-{i}")
        tmp_dest = os.path.join(dest_dir, f"_tmp_comp_{i}.png")

        # 1. Playwright 截竞品官网
        if item.get("playwright_url"):
            try:
                _playwright_screenshot(item["playwright_url"], tmp_dest)
                if os.path.getsize(tmp_dest) > 512:
                    comp_images.append(tmp_dest)
                    continue
            except Exception:
                pass

        # 2. Tavily 搜竞品产品截图
        found = False
        for query in item.get("tavily_queries", []):
            img_url = _try_tavily_images(query, tmp_dest)
            if img_url and os.path.getsize(tmp_dest) > 512:
                comp_images.append(tmp_dest)
                found = True
                break

        if found:
            continue

        # 3. Clearbit logo 兜底
        domain = _guess_domain(name)
        if domain:
            logo_url = f"https://logo.clearbit.com/{domain}"
            if _download(logo_url, tmp_dest):
                comp_images.append(tmp_dest)
                continue
            # Google Favicon 再兜底
            fav_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
            if _download(fav_url, tmp_dest):
                comp_images.append(tmp_dest)
                continue

        # 清理
        try:
            os.remove(tmp_dest)
        except OSError:
            pass

    if not comp_images:
        upsert_asset(db_path, company_name, "competitors", status="failed")
        return None

    dest = os.path.join(dest_dir, "competitors.png")
    try:
        _composite_grid(comp_images, dest)
        upsert_asset(db_path, company_name, "competitors",
                    local_path=f"/images/{company_name}/competitors.png",
                    source_type="composite", source_url="", status="ready")
        for tmp in comp_images:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return {"local_path": f"/images/{company_name}/competitors.png"}
    except Exception:
        upsert_asset(db_path, company_name, "competitors", status="failed")
        return None


# ═══════════════════════════════════════════════════════════════
# 主入口：采集全部
# ═══════════════════════════════════════════════════════════════

def collect_all_assets(db_path: str, images_root: str, company_name: str,
                       company_data: dict) -> dict[str, dict]:
    """
    company_data: 从 research_db 或 final_db 拿到的字段 dict
    包含: company_url/website_url, location, other_products(JSON), competitors(JSON)
    """
    ensure_assets_rows(db_path, company_name)
    results = {}

    company_url = _extract_company_url(company_data)
    website_url = company_url
    location = company_data.get("location") or ""

    # 构建搜索词配置
    query_config = build_image_queries(company_data)

    # 1. Logo
    r = collect_logo(db_path, images_root, company_name, company_url, website_url,
                     company_key=company_data.get("company_key", ""))
    results["logo"] = r

    # 2. Office
    r = collect_office(db_path, images_root, company_name, location,
                       query_config=query_config.get("office"))
    results["office"] = r

    # 3. 主产品截图
    r = capture_product(db_path, images_root, company_name, website_url,
                        query_config=query_config.get("product_main"))
    results["product_main"] = r

    # 4. 其他产品
    r = collect_other_products(db_path, images_root, company_name,
                               query_config=query_config.get("products_other"))
    results["products_other"] = r

    # 5. 竞品图
    r = compose_competitors(db_path, images_root, company_name,
                            query_config=query_config.get("competitors"))
    results["competitors"] = r

    # 6-7. flywheel / timeline 不在此自动采集，由 infographic.py 处理
    for key in ("flywheel", "timeline"):
        r = get_asset(db_path, company_name, key)
        results[key] = r

    return results


def _collect_assets_as_variants(db_path: str, images_root: str, company_name: str,
                                 company_data: dict):
    """
    变体模式采集：每个槽位生成多个候选写入 image_variants，
    不直接写 company_assets.local_path（等定稿台 select）。
    在文字生成完成后调用。
    """
    from asset_store import insert_variant, upsert_asset
    query_config = build_image_queries(company_data)
    company_url = _extract_company_url(company_data)
    website_url = company_url
    location = company_data.get("location") or ""

    ensure_assets_rows(db_path, company_name)

    # Logo — 保持原有逻辑（单候选，直接写 company_assets）
    collect_logo(db_path, images_root, company_name, company_url, website_url,
                 company_key=company_data.get("company_key", ""))

    # Office — 多候选采集
    off_cfg = query_config.get("office", {})
    off_sources = []
    for url in off_cfg.get("scrape_urls", []):
        off_sources.append({"type": "scrape", "url": url})
    for q in off_cfg.get("tavily_queries", []):
        off_sources.append({"type": "tavily", "query": q})
    n_off = _collect_candidates(db_path, images_root, company_name, "office", off_sources)
    if n_off == 0 and location:
        # OSM 地图兜底
        dest = _variant_path(images_root, company_name, "office", "osm")
        if _render_osm_map(location, dest):
            insert_variant(db_path, company_name, "office",
                           local_path=_variant_browser_path(company_name, dest),
                           source_type="osm_map")
            n_off = 1
    upsert_asset(db_path, company_name, "office", status="ready" if n_off > 0 else "failed")

    # Product main — 多候选
    prod_cfg = query_config.get("product_main", {})
    prod_sources = []
    for url in prod_cfg.get("playwright_urls", []):
        if url:
            prod_sources.append({"type": "playwright", "url": url})
    for q in prod_cfg.get("tavily_queries", []):
        prod_sources.append({"type": "tavily", "query": q})
    n_prod = _collect_candidates(db_path, images_root, company_name, "product_main", prod_sources)
    upsert_asset(db_path, company_name, "product_main", status="ready" if n_prod > 0 else "failed")

    # Other products — 每产品 2 候选
    other_cfg = query_config.get("products_other", {})
    per_product = other_cfg.get("per_product", [])
    any_other = False
    for i, item in enumerate(per_product[:4]):
        name = item.get("name", f"product-{i}")
        asset_key = f"products_other__{name}"
        upsert_asset(db_path, company_name, asset_key, status="pending")
        sources = []
        if item.get("playwright_url"):
            sources.append({"type": "playwright", "url": item["playwright_url"]})
        for q in item.get("tavily_queries", []):
            sources.append({"type": "tavily", "query": q})
        n = _collect_candidates(db_path, images_root, company_name, asset_key, sources, max_candidates=2)
        if n > 0:
            upsert_asset(db_path, company_name, asset_key, status="ready")
            any_other = True
    if not any_other:
        upsert_asset(db_path, company_name, "products_other", status="failed")

    # Competitors — 每竞品 2 候选 + clearbit 兜底
    comp_cfg = query_config.get("competitors", {})
    per_comp = comp_cfg.get("per_comp", [])
    any_comp = False
    for i, item in enumerate(per_comp[:3]):
        name = item.get("name", f"competitor-{i}")
        asset_key = f"competitors__{name}"
        upsert_asset(db_path, company_name, asset_key, status="pending")
        sources = []
        if item.get("playwright_url"):
            sources.append({"type": "playwright", "url": item["playwright_url"]})
        for q in item.get("tavily_queries", []):
            sources.append({"type": "tavily", "query": q})
        domain = _guess_domain(name)
        if domain:
            sources.append({"type": "clearbit", "domain": domain})
        n = _collect_candidates(db_path, images_root, company_name, asset_key, sources, max_candidates=2)
        if n > 0:
            upsert_asset(db_path, company_name, asset_key, status="ready")
            any_comp = True
    if not any_comp:
        upsert_asset(db_path, company_name, "competitors", status="failed")


# ═══════════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════════

def _parse_json_field(value) -> list | None:
    """安全解析 JSON 字符串"""
    if not value:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _guess_domain(company_name: str) -> str:
    """从公司名推测域名（简化）"""
    name = company_name.lower().strip()
    # 常见映射
    known = {
        "openai": "openai.com",
        "anthropic": "anthropic.com",
        "google": "google.com",
        "meta": "meta.com",
        "microsoft": "microsoft.com",
        "amazon": "amazon.com",
        "apple": "apple.com",
        "nvidia": "nvidia.com",
        "stability ai": "stability.ai",
        "midjourney": "midjourney.com",
        "deepseek": "deepseek.com",
        "cursor": "cursor.com",
        "notion": "notion.so",
        "linear": "linear.app",
        "vercel": "vercel.com",
        "zuma": "zuma.com",
    }
    if name in known:
        return known[name]
    # 清理 → 假设 .com
    clean = name.replace(" ", "").replace("-", "").replace(".", "")
    if clean and len(clean) >= 3:
        return f"{clean}.com"
    return ""


def _get_tavily_keys() -> list[str]:
    keys = getattr(config, "TAVILY_API_KEYS", None)
    if keys:
        return keys
    return [config.TAVILY_API_KEY] if config.TAVILY_API_KEY else []


def _is_tavily_quota_response(resp) -> bool:
    text = getattr(resp, "text", "") or ""
    return resp.status_code in (429, 432) or "usage limit" in text.lower() or "quota" in text.lower()


def _try_tavily_images(query: str, dest: str) -> str | None:
    """通过 Tavily Search API 搜索图片（include_images=True）"""
    try:
        for img_url in _tavily_image_urls(query, limit=10):
            if _download(img_url, dest):
                return img_url
        return None
    except Exception:
        return None


def _tavily_image_urls(query: str, limit: int = 10) -> list[str]:
    """Return up to ``limit`` Tavily image URLs without downloading them."""
    try:
        api_keys = _get_tavily_keys()
        if not api_keys:
            return []

        data = None
        for index, api_key in enumerate(api_keys):
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "include_images": True,
                    "max_results": min(max(limit, 1), 10),
                },
                timeout=15,
            )
            if resp.status_code >= 400:
                if _is_tavily_quota_response(resp) and index < len(api_keys) - 1:
                    continue
                return []
            data = resp.json()
            break

        if not data:
            return []
        urls = []
        for img in data.get("images", [])[:limit]:
            img_url = img.get("url", "") if isinstance(img, dict) else str(img)
            if img_url and img_url.startswith("http") and img_url not in urls:
                urls.append(img_url)
        return urls
    except Exception:
        return []


def _collect_tavily_candidates(db_path: str, images_root: str, company_name: str,
                               asset_key: str, query: str, limit: int = 10) -> int:
    """Download, inspect, score, and persist up to 10 Tavily image candidates."""
    accepted = 0
    for i, img_url in enumerate(_tavily_image_urls(query, limit=limit)[:limit]):
        dest = _variant_path(images_root, company_name, asset_key, f"tv_{int(time.time())}_{i}")
        if not _download(img_url, dest, timeout=30):
            continue
        if _persist_local_candidate(
            db_path,
            company_name,
            asset_key,
            dest,
            "web_tavily",
            source_url=img_url,
            source_page=img_url,
            prompt=query,
            meta={"query": query},
        ):
            accepted += 1
    return accepted


def _render_osm_map(location: str, dest: str, label: str = "", legend: str = "") -> bool:
    """用 OSM 静态图 + HTML pin overlay 生成地图，失败再回退 Leaflet 截图。"""
    tmp_map = None
    try:
        # Geocode
        geo_query = _geocode_search_text(location)
        geo_url = f"https://nominatim.openstreetmap.org/search?q={geo_query}&format=json&limit=1"
        resp = requests.get(geo_url, headers={"User-Agent": "aistartups-cn/1.0"}, timeout=10)
        data = resp.json()
        if not data:
            return False

        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        display_name = label or data[0].get("display_name", location)
        legend_text = legend or location

        # Guizang map component: static map raster + HTML pin/legend overlay.
        map_url = (f"https://staticmap.openstreetmap.de/staticmap.php"
                   f"?center={lat},{lon}&zoom=14&size=800x400&maptype=mapnik"
                   f"&markers={lat},{lon},red-pushpin")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_map = f.name
        if _render_osm_tile_composite(lat, lon, tmp_map) or _download(map_url, tmp_map):
            if _render_static_map_card(f"file://{tmp_map}", legend_text, display_name, dest):
                return True

        # 回退：Leaflet HTML + Playwright
        return _render_map_via_playwright(lat, lon, display_name, dest)
    except Exception:
        return False
    finally:
        if tmp_map:
            try:
                os.unlink(tmp_map)
            except Exception:
                pass


def _render_osm_tile_composite(lat: float, lon: float, dest: str,
                               width: int = 800, height: int = 400,
                               zoom: int = 14) -> bool:
    """Compose OSM raster tiles locally so the final card has no map UI chrome."""
    try:
        import math
        from io import BytesIO
        from PIL import Image

        tile_size = 256
        scale = tile_size * (2 ** zoom)
        center_x = (lon + 180.0) / 360.0 * scale
        sin_lat = math.sin(math.radians(lat))
        center_y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale

        left = center_x - width / 2
        top = center_y - height / 2
        first_x = int(math.floor(left / tile_size))
        first_y = int(math.floor(top / tile_size))
        last_x = int(math.floor((left + width) / tile_size))
        last_y = int(math.floor((top + height) / tile_size))

        canvas = Image.new("RGB", (width, height), (232, 234, 236))
        max_tile = 2 ** zoom
        headers = {"User-Agent": "aistartups-cn/1.0"}
        loaded = 0
        for x in range(first_x, last_x + 1):
            for y in range(first_y, last_y + 1):
                if y < 0 or y >= max_tile:
                    continue
                tile_x = x % max_tile
                url = f"https://tile.openstreetmap.org/{zoom}/{tile_x}/{y}.png"
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code >= 400:
                    continue
                tile = Image.open(BytesIO(resp.content)).convert("RGB")
                px = int(x * tile_size - left)
                py = int(y * tile_size - top)
                canvas.paste(tile, (px, py))
                loaded += 1

        if loaded == 0:
            return False
        canvas.save(dest, "PNG")
        return os.path.exists(dest) and os.path.getsize(dest) > 512
    except Exception:
        return False


def _render_static_map_card(map_url: str, location: str, label: str, dest: str) -> bool:
    """Render a static OSM raster inside a Guizang-style map block."""
    import tempfile

    safe_location = str(location or "Company location").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_label = str(label or location or "Location").split(",")[0].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=800,initial-scale=1">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #f2f2f2; font-family: Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; }}
  .map-block {{
    position: relative;
    width: 800px;
    height: 400px;
    overflow: hidden;
    background: #e8eaec;
  }}
  .map-block > img {{
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
    filter: saturate(0) contrast(1.06) brightness(1.02);
  }}
  .map-block::after {{
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    background:
      linear-gradient(90deg, rgba(242,242,242,.72), rgba(242,242,242,.12) 42%, rgba(242,242,242,.28)),
      radial-gradient(circle at 50% 50%, rgba(41,184,212,.16), transparent 26%);
    mix-blend-mode: multiply;
  }}
  .map-pin {{
    position: absolute;
    left: 50%;
    top: 50%;
    z-index: 3;
    transform: translate(-50%, -50%);
  }}
  .map-pin .dot {{
    width: 16px;
    height: 16px;
    border-radius: 999px;
    background: #29B8D4;
    border: 3px solid #fff;
    box-shadow: 0 6px 18px rgba(0,0,0,.28);
  }}
  .map-pin .line {{
    position: absolute;
    left: 8px;
    top: 8px;
    width: 72px;
    height: 1px;
    background: rgba(11,15,23,.55);
  }}
  .map-pin .card {{
    position: absolute;
    left: 84px;
    top: -22px;
    width: 220px;
    padding: 10px 12px;
    background: rgba(255,255,255,.92);
    border: 1px solid rgba(11,15,23,.18);
    box-shadow: 0 14px 30px rgba(0,0,0,.12);
  }}
  .map-pin .name {{
    font-size: 16px;
    font-weight: 700;
    line-height: 1.18;
    color: #0B0F17;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .map-pin .meta {{
    display: block;
    margin-top: 4px;
    color: #5E6878;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .12em;
    text-transform: uppercase;
  }}
  .map-legend {{
    position: absolute;
    right: 14px;
    bottom: 12px;
    z-index: 3;
    padding: 6px 9px;
    background: rgba(255,255,255,.82);
    border: 1px solid rgba(11,15,23,.16);
    color: #4b5563;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .12em;
  }}
</style>
</head>
<body>
  <div class="map-block" id="map-card">
    <img src="{map_url}" alt="{safe_location}">
    <div class="map-pin">
      <div class="dot"></div><div class="line"></div>
      <div class="card"><div class="name">{safe_label}</div><span class="meta">COMPANY LOCATION</span></div>
    </div>
    <div class="map-legend">OSM STATIC · {safe_location}</div>
  </div>
</body>
</html>"""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        with sync_playwright() as p:
            exe = _find_chromium()
            launch_args = {"headless": True}
            if exe:
                launch_args["executable_path"] = exe
            else:
                launch_args["channel"] = "chrome"
            browser = p.chromium.launch(**launch_args)
            page = browser.new_page(viewport={"width": 800, "height": 400})
            page.goto(f"file://{html_path}", wait_until="networkidle", timeout=30000)
            page.wait_for_function(
                "() => { const img = document.querySelector('#map-card img'); return img && img.complete && img.naturalWidth > 0; }",
                timeout=10000,
            )
            page.locator("#map-card").screenshot(path=dest)
            browser.close()
        return os.path.exists(dest) and os.path.getsize(dest) > 512
    except Exception:
        return False
    finally:
        try:
            os.unlink(html_path)
        except Exception:
            pass


def _render_map_via_playwright(lat: float, lon: float, label: str, dest: str) -> bool:
    """用 Leaflet + Playwright 截图生成地图图片（Leaflet CDN 需网络，国内环境需 HTTPS_PROXY）"""
    import tempfile

    safe_label = label.replace("'", "\\'")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=800,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body {{ margin:0; }}
  #map {{ width:800px; height:400px; }}
  .leaflet-control-attribution {{ font-size:10px; }}
</style>
</head>
<body>
<div id="map"></div>
<script>
  const map = L.map('map', {{ zoomControl: true, attributionControl: true }}).setView([{lat}, {lon}], 14);
  var tileLayer = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);
  L.marker([{lat}, {lon}]).addTo(map)
    .bindPopup('{safe_label}')
    .openPopup();
  // Signal when tile layer finishes loading
  tileLayer.on('load', function() {{ document.title = 'ready'; }});
</script>
</body>
</html>"""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        with sync_playwright() as p:
            # 优先用 _find_chromium() 找本地缓存，否则回退到系统 Chrome
            exe = _find_chromium()
            launch_args = {"headless": True}
            if exe:
                launch_args["executable_path"] = exe
            else:
                launch_args["channel"] = "chrome"
            browser = p.chromium.launch(**launch_args)
            page = browser.new_page(viewport={"width": 800, "height": 400})
            page.goto(f"file://{html_path}", wait_until="networkidle", timeout=30000)
            try:
                page.wait_for_function("document.title === 'ready'", timeout=10000)
            except Exception:
                pass  # tiles may have loaded before event fired
            page.screenshot(path=dest, type="png")
            browser.close()
        return os.path.exists(dest) and os.path.getsize(dest) > 512
    except Exception:
        return False
    finally:
        try:
            os.unlink(html_path)
        except Exception:
            pass


def _find_chromium() -> str:
    """在本地 Playwright 缓存或系统中查找可用的 Chromium 可执行文件"""
    import glob as _glob
    from config import config

    # 1. 优先使用配置/环境变量指定的路径
    if config.PLAYWRIGHT_CHROMIUM_PATH and os.path.exists(config.PLAYWRIGHT_CHROMIUM_PATH):
        return config.PLAYWRIGHT_CHROMIUM_PATH

    # 2. macOS: Playwright 默认缓存路径
    base = os.path.expanduser("~/Library/Caches/ms-playwright")
    for d in sorted(
        _glob.glob(f"{base}/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
        reverse=True,
    ):
        if os.path.exists(d):
            return d

    # 3. Linux: Playwright 默认缓存路径
    linux_base = os.path.expanduser("~/.cache/ms-playwright")
    for d in sorted(
        _glob.glob(f"{linux_base}/chromium-*/chrome-linux/chrome"),
        reverse=True,
    ):
        if os.path.exists(d):
            return d

    # 4. Linux: 尝试系统安装的 chromium
    for system_path in ("chromium", "chromium-browser",
                        "/usr/bin/chromium", "/usr/bin/chromium-browser",
                        "/snap/bin/chromium"):
        found = shutil.which(system_path) if not system_path.startswith("/") else system_path
        if found and os.path.exists(found):
            return found

    return ""


def _playwright_screenshot(url: str, dest: str, width: int = 900, height: int = 600,
                           hide_selectors=None, full_viewport: bool = False):
    """Playwright screenshot with login/captcha/empty-page validation."""
    from screenshot_client import capture
    result = capture(url, dest, provider=getattr(config, "SCREENSHOT_PROVIDER", "local"),
                     viewport=(width, height), full_page=False,
                     hide_selectors=hide_selectors, full_viewport=full_viewport)
    if not result.ok:
        raise RuntimeError(result.fail_reason or "截图失败")


def _composite_horizontal(image_paths: list[str], dest: str, max_height: int = 400):
    """多张图水平拼接"""
    from PIL import Image
    images = []
    for p in image_paths:
        img = Image.open(p).convert("RGBA")
        h_ratio = max_height / img.height
        new_w = int(img.width * h_ratio)
        images.append(img.resize((new_w, max_height), Image.LANCZOS))

    total_w = sum(img.width for img in images) + (len(images) - 1) * 8  # 8px gap
    canvas = Image.new("RGBA", (total_w, max_height), (255, 255, 255, 255))
    x = 0
    for img in images:
        canvas.paste(img, (x, 0), img if img.mode == "RGBA" else None)
        x += img.width + 8

    canvas.save(dest, "PNG")


def _composite_grid(image_paths: list[str], dest: str, tile_size: int = 200,
                    max_cols: int = 3):
    """Logo 网格拼图（白色背景，居中排列）"""
    from PIL import Image

    n = len(image_paths)
    cols = min(n, max_cols)
    rows = (n + cols - 1) // cols

    canvas_w = cols * tile_size + (cols - 1) * 12 + 24
    canvas_h = rows * tile_size + (rows - 1) * 12 + 24
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))

    for i, p in enumerate(image_paths):
        img = Image.open(p).convert("RGBA")
        # 缩放到 tile 内
        img.thumbnail((tile_size - 20, tile_size - 20), Image.LANCZOS)
        col = i % cols
        row = i // cols
        x = 12 + col * (tile_size + 12) + (tile_size - img.width) // 2
        y = 12 + row * (tile_size + 12) + (tile_size - img.height) // 2
        canvas.paste(img, (x, y), img if img.mode == "RGBA" else None)

    canvas.save(dest, "PNG")


def _compose_competitor_logo_strip(logos: list[dict], dest: str,
                                   width: int = 1280, height: int = 720):
    """Compose up to three competitor logos into a 16:9 horizontal strip."""
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    margin_x = 90
    slot_gap = 36
    slot_count = 3
    slot_w = (width - margin_x * 2 - slot_gap * (slot_count - 1)) // slot_count
    slot_h = 430
    top = 120
    label_y = top + slot_h + 36

    for i, item in enumerate(logos[:slot_count]):
        left = margin_x + i * (slot_w + slot_gap)
        img = Image.open(item["path"]).convert("RGBA")
        img.thumbnail((slot_w - 88, slot_h - 120), Image.LANCZOS)
        x = left + (slot_w - img.width) // 2
        y = top + (slot_h - img.height) // 2 - 8
        canvas.paste(img, (x, y), img)
        name = str(item.get("name") or f"竞品{i + 1}")[:28]
        try:
            bbox = draw.textbbox((0, 0), name)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = len(name) * 10
        draw.text((left + (slot_w - text_w) // 2, label_y), name, fill=(30, 41, 59))

    draw.text((margin_x, 54), "Competitor Logos", fill=(15, 23, 42))
    canvas.save(dest, "PNG")


# ═══════════════════════════════════════════════════════════════
# 图片采集管道 — 多源变体采集器
# ═══════════════════════════════════════════════════════════════

def _geocode_location(location: str) -> tuple | None:
    """Geocode location string via OSM Nominatim. Returns (lat, lon) or None."""
    try:
        geo_query = _geocode_search_text(location)
        geo_url = f"https://nominatim.openstreetmap.org/search?q={geo_query}&format=json&limit=1"
        resp = requests.get(geo_url, headers={"User-Agent": "aistartups-cn/1.0"}, timeout=10)
        data = resp.json()
        if not data:
            return None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None


def _geocode_search_text(location: str) -> str:
    """Remove suite/legal-notice fragments that make Nominatim miss exact addresses."""
    text = re.sub(r"\s+", " ", str(location or "")).strip()
    text = re.sub(r"\b(?:Ste|Suite|Unit|#)\s*[A-Za-z0-9-]+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d{5})(?:-\d{4})\b", r"\1", text)
    text = text.replace(".", "")
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_street_view(lat: float, lon: float, api_key: str, dest: str,
                       heading: int = 0, size: str = "800x400", fov: int = 90) -> bool:
    """Download a Google Street View image. Returns True on success."""
    from urllib.parse import urlencode
    params = urlencode({
        "location": f"{lat},{lon}",
        "size": size,
        "heading": heading,
        "fov": fov,
        "key": api_key,
    })
    url = f"https://maps.googleapis.com/maps/api/streetview?{params}"
    return _download(url, dest, timeout=20)


_US_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9 .'-]+?\s+"
    r"(?:St|Street|Ave|Avenue|Blvd|Boulevard|Road|Rd|Dr|Drive|Way|Lane|Ln)"
    r"\.?(?:\s+(?:Ste|Suite|Unit|#)\s*[A-Za-z0-9-]+)?"
    r"(?:,\s*|\s+)[A-Za-z .'-]+,\s*[A-Z]{2},?\s*\d{5}(?:-\d{4})?",
    re.IGNORECASE,
)


def _is_specific_location(location: str) -> bool:
    text = str(location or "").strip()
    if not text:
        return False
    if re.search(r"\d{1,6}\s+\w+", text):
        return True
    return len([p for p in re.split(r"[,，]", text) if p.strip()]) >= 4


def _official_domain_tokens(company_url: str) -> set[str]:
    domain = _domain_from_url(company_url)
    parts = domain.lower().split(".") if domain else []
    return {p for p in parts if p not in {"www", "com", "ai", "io", "app", "co"}}


def _extract_address(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    match = _US_ADDRESS_RE.search(clean)
    if not match:
        return ""
    return match.group(0).strip(" ,.")


def _resolve_office_location(company_name: str, location: str, company_url: str = "") -> dict:
    """Prefer a precise office/legal address over city-level HQ locations."""
    if _is_specific_location(location):
        return {"location": location, "source_url": "", "source": "research_location"}

    domain_tokens = _official_domain_tokens(company_url)
    if not domain_tokens:
        return {"location": location, "source_url": "", "source": "city_fallback"}
    queries = [
        f"{company_name} headquarters address",
        f"{company_name} office address",
        f"{company_name} company address",
    ]
    best = None
    for query in queries:
        result = _search_tavily_query(query, include_images=False)
        for item in result.get("results") or []:
            address = _extract_address(" ".join([
                item.get("title") or "",
                item.get("content") or "",
                item.get("raw_content") or "",
            ]))
            if not address:
                continue
            url = item.get("url") or ""
            host = _domain_from_url(url).lower()
            is_official = any(token and token in host for token in domain_tokens)
            score = 100 if is_official else 50
            candidate = {"location": address, "source_url": url, "source": "tavily_address", "score": score}
            if best is None or candidate["score"] > best["score"]:
                best = candidate
    if best:
        best.pop("score", None)
        return best
    return {"location": location, "source_url": "", "source": "city_fallback"}


def _collect_office_variants(db_path: str, images_root: str, company_name: str,
                             location: str, query_config: dict, company_url: str = "",
                             company_key: str = "") -> int:
    """Office asset: map first, then supplemental street-view/Tavily candidates."""
    from asset_store import insert_variant

    count = 0
    map_variant_id = None
    resolved = _resolve_office_location(company_name, location, company_url)
    map_location = resolved.get("location") or location

    if map_location:
        dest = _variant_path(images_root, company_name, "office", "osm_map")
        if _render_osm_map(map_location, dest, label=company_name, legend=map_location):
            map_variant_id = insert_variant(
                db_path, company_name, "office",
                local_path=_variant_browser_path(company_name, dest),
                source_type="osm_map",
                source_url=resolved.get("source_url") or "",
                prompt=map_location,
                meta={"location_source": resolved.get("source"), "map_location": map_location},
            )
            count += 1

    # Supplemental Google Street View variants.
    if config.GOOGLE_MAPS_API_KEY and map_location:
        latlon = _geocode_location(map_location)
        if latlon:
            lat, lon = latlon
            for heading in [0, 90]:
                dest = _variant_path(images_root, company_name, "office", f"gsv_{heading}")
                if _fetch_street_view(lat, lon, config.GOOGLE_MAPS_API_KEY, dest, heading=heading):
                    insert_variant(
                        db_path, company_name, "office",
                        local_path=_variant_browser_path(company_name, dest),
                        source_type="street_view",
                        source_url=f"gsv:{lat},{lon},heading={heading}",
                    )
                    count += 1

    # Supplemental Tavily building/office photos.
    for q in (query_config.get("tavily_queries") or [])[:2]:
        dest = _variant_path(images_root, company_name, "office", f"tv_{count}")
        src_url = _try_tavily_images(q, dest)
        if src_url:
            insert_variant(
                db_path, company_name, "office",
                local_path=_variant_browser_path(company_name, dest),
                source_type="web_tavily",
                source_url=src_url,
            )
            count += 1

    # Supplemental homepage screenshot (full viewport, hide cookie banners).
    if company_url:
        try:
            from screenshot_client import DEFAULT_HIDE_SELECTORS
            dest = _variant_path(images_root, company_name, "office", "screenshot_homepage")
            _playwright_screenshot(company_url, dest, width=900, height=600,
                                   hide_selectors=DEFAULT_HIDE_SELECTORS, full_viewport=True)
            if os.path.exists(dest) and os.path.getsize(dest) > 512:
                insert_variant(
                    db_path, company_name, "office",
                    local_path=_variant_browser_path(company_name, dest),
                    source_type="playwright",
                    source_url=company_url,
                    source_page=company_url,
                    prompt="官网首页截图",
                )
                count += 1
        except Exception:
            pass  # Non-blocking

    if map_variant_id:
        select_variant(db_path, company_name, "office", map_variant_id)

    return count


def _extract_hero_images_from_page(url: str, max_images: int = 3) -> list[str]:
    """从页面抓取产品/主视觉大图（> 400px，非 logo/icon/favicon）。
    优先主内容区，其次 hero banner，最后全页。"""
    from bs4 import BeautifulSoup
    import re

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
            timeout=15, allow_redirects=True,
        )
    except Exception:
        return []

    if resp.status_code >= 400:
        return []

    base_url = resp.url
    soup = BeautifulSoup(resp.text, "lxml")

    def _abs(src: str) -> str:
        if not src or src.startswith("data:"):
            return ""
        src = src.strip()
        if src.startswith("http"):
            return src
        if src.startswith("//"):
            return f"https:{src}"
        if src.startswith("/"):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{src}"
        return f"{base_url.rstrip('/')}/{src}"

    exclude = re.compile(r"logo|icon|favicon|avatar|\.svg", re.IGNORECASE)
    results = []

    # 优先搜索区域：main > [class*=hero/banner] > body
    search_areas = []
    main = soup.find("main")
    if main:
        search_areas.append(main)
    for tag in soup.find_all(class_=re.compile(r"hero|banner", re.IGNORECASE)):
        search_areas.append(tag)
    search_areas.append(soup)

    seen = set()
    for area in search_areas:
        for img in area.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            abs_url = _abs(src)
            if not abs_url or abs_url in seen:
                continue
            alt = img.get("alt") or ""
            cls = " ".join(img.get("class") or [])
            if exclude.search(f"{alt} {cls} {abs_url}"):
                continue
            w = int(img.get("width") or 0)
            h = int(img.get("height") or 0)
            # 有明确尺寸且太小 → 跳过；无尺寸属性的不跳过（常见于响应式图片）
            if w and h and (w < 400 or h < 300):
                continue
            seen.add(abs_url)
            results.append(abs_url)
            if len(results) >= max_images:
                return results

    return results


def _collect_product_main_variants(db_path: str, images_root: str, company_name: str,
                                   query_config: dict, company_key: str = "") -> int:
    """Card 4: 官网 hero 图提取 + OG + Playwright + Tavily -> scored variants."""

    count = 0

    # 策略0: 从官网抓取产品主图（hero/banner 区域大图）
    for url in (query_config.get("playwright_urls") or [])[:2]:
        if not url or not url.startswith("http"):
            continue
        for hero_url in _extract_hero_images_from_page(url):
            if hero_url and count < 6:
                if _collect_downloaded_candidate(
                    db_path, images_root, company_name, "product_main", hero_url,
                    "official_hero_image", f"hero_{count}", source_page=url,
                    prompt="official website hero image",
                ):
                    count += 1

    # Official/product page OG image.
    for url in (query_config.get("playwright_urls") or [])[:2]:
        if not url or not url.startswith("http"):
            continue
        og_url = _extract_og_image(url)
        if og_url:
            if _collect_downloaded_candidate(
                db_path, images_root, company_name, "product_main", og_url,
                "official_og_image", f"og_{count}", source_page=url, prompt="official product og:image",
            ):
                count += 1

    # Playwright screenshots.
    for url in (query_config.get("playwright_urls") or [])[:2]:
        if not url or not url.startswith("http"):
            continue
        dest = _variant_path(images_root, company_name, "product_main", f"pw_{count}")
        try:
            _playwright_screenshot(url, dest)
            if os.path.exists(dest):
                if _persist_local_candidate(
                    db_path, company_name, "product_main", dest, "playwright",
                    source_url=url, source_page=url, prompt="product page screenshot",
                ):
                    count += 1
                else:
                    # rejected candidates are still saved for explainability.
                    pass
        except Exception:
            pass

    # Tavily: up to 10 images per query, persisted as accepted/rejected candidates.
    for q in (query_config.get("tavily_queries") or [])[:4]:
        if count >= 6:
            break
        count += _collect_tavily_candidates(
            db_path, images_root, company_name, "product_main", q, limit=10,
        )

    return count


def _collect_products_other_variants(db_path: str, images_root: str, company_name: str,
                                     query_config: dict, company_key: str = "") -> int:
    """Card 5: Per product OG + Playwright + Tavily -> scored variants."""

    count = 0
    for i, item in enumerate((query_config.get("per_product") or [])[:4]):
        if count >= 6:
            break
        name = item.get("name", f"product-{i}")

        # Playwright
        pw_url = item.get("playwright_url", "")
        if pw_url and pw_url.startswith("http"):
            og_url = _extract_og_image(pw_url)
            if og_url and count < 6:
                if _collect_downloaded_candidate(
                    db_path, images_root, company_name, "products_other", og_url,
                    "official_og_image", f"prod{i}_og", source_page=pw_url, prompt=name,
                ):
                    count += 1
            dest = _variant_path(images_root, company_name, "products_other", f"prod{i}_pw")
            try:
                _playwright_screenshot(pw_url, dest)
                if os.path.exists(dest):
                    if _persist_local_candidate(
                        db_path, company_name, "products_other", dest, "playwright",
                        source_url=pw_url, source_page=pw_url, prompt=name,
                    ):
                        count += 1
            except Exception:
                pass

        # Tavily
        for q in (item.get("tavily_queries") or [])[:2]:
            if count >= 6:
                break
            count += _collect_tavily_candidates(
                db_path, images_root, company_name, "products_other", q, limit=10,
            )

    return count


def _collect_competitors_variants(db_path: str, images_root: str, company_name: str,
                                  query_config: dict, company_key: str = "") -> int:
    """Card 7: Per competitor OG + Playwright + Tavily + Clearbit fallback."""

    count = 0
    for i, item in enumerate((query_config.get("per_comp") or [])[:3]):
        if count >= 6:
            break
        name = item.get("name", f"competitor-{i}")

        # Playwright
        pw_url = item.get("playwright_url", "")
        if pw_url and pw_url.startswith("http"):
            og_url = _extract_og_image(pw_url)
            if og_url and count < 6:
                if _collect_downloaded_candidate(
                    db_path, images_root, company_name, "competitors", og_url,
                    "official_og_image", f"comp{i}_og", source_page=pw_url, prompt=name,
                ):
                    count += 1
            dest = _variant_path(images_root, company_name, "competitors", f"comp{i}_pw")
            try:
                _playwright_screenshot(pw_url, dest)
                if os.path.exists(dest):
                    if _persist_local_candidate(
                        db_path, company_name, "competitors", dest, "playwright",
                        source_url=pw_url, source_page=pw_url, prompt=name,
                    ):
                        count += 1
            except Exception:
                pass

        # Tavily
        for q in (item.get("tavily_queries") or [])[:2]:
            if count >= 6:
                break
            count += _collect_tavily_candidates(
                db_path, images_root, company_name, "competitors", q, limit=10,
            )

        # Clearbit logo fallback
        domain = _guess_domain(name)
        if domain:
            dest = _variant_path(images_root, company_name, "competitors", f"comp{i}_cb")
            if _download(f"https://logo.clearbit.com/{domain}", dest):
                if _persist_local_candidate(
                    db_path, company_name, "competitors", dest, "clearbit",
                    source_url=f"https://logo.clearbit.com/{domain}", prompt=name,
                ):
                    count += 1

    return count


def _collect_competitor_logo_strip_variants(db_path: str, images_root: str, company_name: str,
                                            query_config: dict, company_key: str = "") -> int:
    """Card 7: one 16:9 horizontal strip made from up to three competitor logos."""
    comp_items = (query_config.get("per_comp") or [])[:3]
    if not comp_items:
        return 0

    logos = []
    tmp_paths = []
    for i, item in enumerate(comp_items):
        name = item.get("name", f"competitor-{i + 1}")
        url_domain = urlparse(item.get("playwright_url") or "").netloc.replace("www.", "")
        domain = url_domain or _guess_domain(name)
        if not domain:
            continue
        dest = _variant_path(images_root, company_name, "competitors_logo_strip", f"comp{i}_logo")
        logo_urls = [
            f"https://logo.clearbit.com/{domain}",
            f"https://www.google.com/s2/favicons?domain={domain}&sz=256",
        ]
        for logo_url in logo_urls:
            if _download(logo_url, dest):
                logos.append({"name": name, "path": dest, "source_url": logo_url})
                tmp_paths.append(dest)
                break

    if not logos:
        return 0

    dest = _variant_path(images_root, company_name, "competitors_logo_strip", "logo_strip")
    _compose_competitor_logo_strip(logos, dest, width=1280, height=720)
    names = " / ".join(item["name"] for item in logos)
    variant_id = _persist_generated_candidate(
        db_path,
        company_name,
        "competitors_logo_strip",
        dest,
        "logo_strip",
        source_url=";".join(item.get("source_url", "") for item in logos),
        prompt=names,
        meta={"layout": "horizontal_16_9", "competitors": [item["name"] for item in logos]},
    )
    for tmp in tmp_paths:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return 1 if variant_id else 0


def _extract_company_url(company_data: dict) -> str:
    """从 company_data 中提取官网 URL，兼容多种字段名。
    优先级：company_url > website_url > website > official_website > homepage_url > url
    """
    for key in ("company_url", "website_url", "website", "official_website", "homepage_url", "url"):
        val = company_data.get(key, "")
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _collect_website_screenshot_variants(
    db_path: str, images_root: str, company_name: str,
    company_url: str = "", company_key: str = "",
) -> int:
    """官网首页截图：Playwright 全 viewport 截图（含 cookie banner 隐藏）。"""
    if not company_url:
        upsert_asset(db_path, company_name, "website_screenshot",
                    status="failed", fail_reason="公司网站地址为空", company_key=company_key)
        return 0

    dest = _variant_path(images_root, company_name, "website_screenshot", "homepage")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    try:
        from screenshot_client import capture, DEFAULT_HIDE_SELECTORS
        result = capture(
            company_url, dest, provider=getattr(config, "SCREENSHOT_PROVIDER", "local"),
            viewport=(1440, 1000), full_page=False,
            hide_selectors=DEFAULT_HIDE_SELECTORS, full_viewport=True,
        )
        if not result.ok:
            upsert_asset(db_path, company_name, "website_screenshot",
                        status="failed", fail_reason=result.fail_reason,
                        company_key=company_key)
            return 0
    except Exception as e:
        import traceback
        print(f"[官网截图异常] {company_name}: {traceback.format_exc()}", flush=True)
        upsert_asset(db_path, company_name, "website_screenshot",
                    status="failed", fail_reason=str(e), company_key=company_key)
        return 0

    if not os.path.exists(dest) or os.path.getsize(dest) <= 512:
        upsert_asset(db_path, company_name, "website_screenshot",
                    status="failed", fail_reason="截图文件为空或过小",
                    company_key=company_key)
        return 0

    # 读取截图尺寸和文件大小，写入变体记录（失败不中断采集）
    img_width = None
    img_height = None
    img_file_size = None
    img_aspect_ratio = None
    try:
        from PIL import Image
        with Image.open(dest) as im:
            img_width, img_height = im.size
        img_file_size = Path(dest).stat().st_size
        if img_height and img_height > 0:
            img_aspect_ratio = round(img_width / img_height, 4)
    except Exception:
        import traceback
        print(f"[官网截图-元数据] {company_name}: 读取尺寸失败\n{traceback.format_exc()}", flush=True)

    variant_id = insert_variant(
        db_path, company_name, "website_screenshot",
        local_path=_variant_browser_path(company_name, dest),
        source_type="playwright",
        source_url=company_url,
        source_page=company_url,
        prompt="官网首页截图",
        width=img_width,
        height=img_height,
        file_size=img_file_size,
        aspect_ratio=img_aspect_ratio,
        company_key=company_key,
    )
    if variant_id:
        select_variant(db_path, company_name, "website_screenshot", variant_id,
                      auto_selected=True, company_key=company_key)
    return 1


def _scrape_page_images(url: str, min_width: int = 200) -> list[dict]:
    """用 Playwright 抓取页面中所有满足最小宽度的 img 元素。"""
    imgs = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            imgs = page.evaluate("""(minW) => {
                return Array.from(document.querySelectorAll('img'))
                    .filter(img => img.naturalWidth >= minW || img.width >= minW)
                    .map(img => ({
                        src: img.src || img.getAttribute('data-src') || '',
                        width: img.naturalWidth || img.width || 0,
                        height: img.naturalHeight || img.height || 0,
                        alt: img.alt || ''
                    }))
                    .filter(x => x.src && x.src.startsWith('http'));
            }""", min_width)
            browser.close()
    except Exception:
        pass
    return imgs


def _collect_founder_photo_variants(
    db_path: str, images_root: str, company_name: str,
    company_data: dict, company_key: str = "",
) -> int:
    """创始人照片采集 — 三级策略：Tavily 搜 → About 页 → 失败标记。
    不在研究阶段自动触发，由 image studio 按需调用。"""
    founder_name = (company_data.get("founder_name") or "").strip()
    office_hints = company_data.get("office_photo_hints") or {}
    about_url = (office_hints.get("about_url") or "").strip()
    linkedin_url = (office_hints.get("linkedin_url") or "").strip()

    # ── 过滤工具 ──
    def _is_portrait_candidate(local_path: str) -> bool:
        """检查图片是否满足人像照基本条件：aspect 0.6-1.8, width ≥ 200, 非 logo/产品截图。"""
        try:
            from PIL import Image
            img = Image.open(local_path)
            w, h = img.size
            if w < 200:
                return False
            ratio = w / h if h > 0 else 0
            if ratio < 0.6 or ratio > 1.8:
                return False
            # 用 image_scorer 排除 logo/产品截图
            try:
                from image_scorer import score_candidate
                meta = score_candidate(local_path, product_names=[])
                content_type = (meta.get("content_type") or "").lower()
                if content_type in ("logo", "screenshot", "diagram"):
                    return False
            except Exception:
                pass  # 评分不可用时不拦截
            return True
        except Exception:
            return False

    accepted = 0
    used_urls = set()

    # ── Tier 1: Tavily 搜索创始人照片 ──
    if founder_name:
        query = f"{founder_name} {company_name} headshot photo"
        try:
            for i, img_url in enumerate(_tavily_image_urls(query, limit=8)):
                if img_url in used_urls:
                    continue
                used_urls.add(img_url)
                dest = _variant_path(images_root, company_name, "founder_photo", f"tv_{int(time.time())}_{i}")
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if not _download(img_url, dest, timeout=30):
                    continue
                if not _is_portrait_candidate(dest):
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                    continue
                if _persist_local_candidate(
                    db_path, company_name, "founder_photo", dest,
                    "web_tavily", source_url=img_url, source_page=img_url,
                    prompt=query, meta={"query": query, "tier": 1},
                ):
                    accepted += 1
        except Exception:
            pass  # Tavily 失败不阻断后续

    # ── Tier 2: Playwright 抓取 About 页人像 ──
    if about_url and accepted == 0:
        try:
            imgs = _scrape_page_images(about_url, min_width=200)
            for j, img_info in enumerate(imgs[:6]):
                src = img_info.get("src", "")
                if not src or src in used_urls:
                    continue
                used_urls.add(src)
                dest = _variant_path(images_root, company_name, "founder_photo", f"about_{int(time.time())}_{j}")
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if not _download(src, dest, timeout=30, referer=about_url):
                    continue
                if not _is_portrait_candidate(dest):
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                    continue
                if _persist_local_candidate(
                    db_path, company_name, "founder_photo", dest,
                    "playwright", source_url=src, source_page=about_url,
                    prompt=f"About page: {about_url}", meta={"tier": 2, "source_page": about_url},
                ):
                    accepted += 1
        except Exception:
            pass

    # ── Tier 3: LinkedIn（占位，暂不实施 — 反爬风险高）──
    # linkedin_url 保留为未来扩展点

    # ── 结果写入 ──
    if accepted > 0:
        variants = list_variants(db_path, company_name, "founder_photo", company_key=company_key)
        if variants and not any(v.get("is_selected") for v in variants):
            ready = [v for v in variants if not v.get("reject_reason")]
            if ready:
                select_variant(db_path, company_name, "founder_photo", ready[0]["id"],
                              auto_selected=True, company_key=company_key)
        upsert_asset(db_path, company_name, "founder_photo",
                    status="ready", company_key=company_key)
    else:
        upsert_asset(db_path, company_name, "founder_photo",
                    status="failed",
                    fail_reason="未找到符合条件的人像照片（aspect 0.6-1.8, width≥200, 非logo/截图）",
                    company_key=company_key)
    return accepted


# 管道入口
def collect_image_variants_pipeline(
    db_path: str, images_root: str, company_name: str,
    company_data: dict,
    progress_callback=None, job_id: str = None,
    asset_key: str = "",
) -> dict[str, int]:
    """研究流水线图片采集阶段入口。逐一采集素材需求变体并报告进度。
    如果指定 asset_key，只采集该槽位。"""
    query_config = build_image_queries(company_data)
    location = company_data.get("location", "")
    company_url = _extract_company_url(company_data)
    company_key = company_data.get("company_key", "")

    ensure_assets_rows(db_path, company_name, company_key=company_key)

    stages = [
        ("website_screenshot", "官网首页截图", lambda ck=company_key: _collect_website_screenshot_variants(
            db_path, images_root, company_name, company_url, company_key=ck)),
        ("product_main", "主产品截图", lambda ck=company_key: _collect_product_main_variants(
            db_path, images_root, company_name, query_config.get("product_main", {}),
            company_key=ck)),
        ("products_other", "其他产品截图", lambda ck=company_key: _collect_products_other_variants(
            db_path, images_root, company_name, query_config.get("products_other", {}),
            company_key=ck)),
        ("competitors", "竞争格局截图", lambda ck=company_key: _collect_competitors_variants(
            db_path, images_root, company_name, query_config.get("competitors", {}),
            company_key=ck)),
        ("competitors_logo_strip", "三个竞品 Logo 横排图", lambda ck=company_key: _collect_competitor_logo_strip_variants(
            db_path, images_root, company_name, query_config.get("competitors", {}),
            company_key=ck)),
    ]

    # 如果指定了 asset_key，只跑对应阶段
    if asset_key:
        if asset_key == "office":
            stages.append(("office", "公司位置地图", lambda ck=company_key: _collect_office_variants(
                db_path, images_root, company_name, location, query_config.get("office", {}), company_url,
                company_key=ck)))
        stages = [(k, l, c) for k, l, c in stages if k == asset_key]

    results = {}
    for i, (asset_key, label, collector) in enumerate(stages):
        if progress_callback:
            progress_callback("图片采集", {
                "message": label,
                "card": i + 1,
                "total": len(stages),
            })
        try:
            n = collector()
            results[asset_key] = n
            if n > 0:
                variants = list_variants(db_path, company_name, asset_key, company_key=company_key)
                if variants and not any(v.get("is_selected") for v in variants):
                    ready = [v for v in variants if not v.get("reject_reason")]
                    if ready:
                        select_variant(db_path, company_name, asset_key, ready[0]["id"],
                                      auto_selected=True, company_key=company_key)
            upsert_asset(db_path, company_name, asset_key,
                        status="ready" if n > 0 else "failed",
                        company_key=company_key)
            if progress_callback:
                progress_callback("图片采集", {
                    "message": f"{label}完成：{n} 张候选图",
                    "card": i + 1,
                    "total": len(stages),
                    "count": n,
                })
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[图片采集-{label}] {company_name}: {tb}", flush=True)
            results[asset_key] = 0
            upsert_asset(db_path, company_name, asset_key, status="failed",
                        fail_reason=f"{e}",
                        company_key=company_key)
            if progress_callback:
                progress_callback("图片采集", {
                    "message": f"{label}失败：{e}",
                    "card": i + 1,
                    "total": len(stages),
                })

    return results
