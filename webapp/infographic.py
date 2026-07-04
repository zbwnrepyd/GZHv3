"""信息图渲染 — 增长飞轮 + 发展时间线

流程：LLM 生成结构化 JSON → SVG 模板确定性绘图 → Playwright 截成 PNG
"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from string import Template


# ═══════════════════════════════════════════════════════════════
# 增长飞轮 SVG 模板
# ═══════════════════════════════════════════════════════════════

FLYWHEEL_SVG = Template("""\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 $width $height" width="$width" height="$height">
  <defs>
    <marker id="arrowhead" viewBox="0 0 12 12" refX="9" refY="6" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
      <path d="M2 2L9 6L2 10" fill="none" stroke="$accent" stroke-width="3" stroke-linecap="round"/>
    </marker>
  </defs>

  <!-- 透明背景 -->
  <rect width="$width" height="$height" fill="transparent" rx="12"/>

  <!-- 飞轮箭头弧线 -->
  $arrows

  <!-- 阶段节点（纯文字，无圆圈） -->
  $stages
</svg>""")

_FLYWHEEL_STAGE = Template("""\
  <!-- $label -->
  <text x="$cx" y="$cy" text-anchor="middle" dominant-baseline="central"
        font-family="'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif"
        font-size="$font_size" font-weight="700" fill="#1B2A4A">$label</text>""")


def _build_flywheel_svg(data: dict, width: int = 800, height: int = 800) -> str:
    """根据结构化 JSON 构建飞轮 SVG — 白色透明背景 + 椭圆闭环箭头圈 + 纯文字标签"""
    stages = data.get("stages", [])
    n = len(stages)
    if n < 2:
        raise ValueError("飞轮至少需要 2 个阶段")

    cx, cy = width / 2, height / 2
    accent = "#29B8D4"
    font_size = 48
    max_label_len = max((len(s.get("label", "")) for s in stages), default=2)
    text_half_w = max_label_len * font_size * 0.6
    margin = max(text_half_w + 20, font_size * 1.5, 80)
    a = max((width / 2) - margin, 60)   # 水平半轴
    b = max((height / 2) - margin, 60)  # 垂直半轴
    import math

    # 阶段节点（纯文字，沿椭圆分布）
    stage_svgs = []
    for i, s in enumerate(stages):
        angle = -90 + (360 / n) * i
        rad = math.radians(angle)
        sx = cx + a * math.cos(rad)
        sy = cy + b * math.sin(rad)
        label = s.get("label", f"阶段{i + 1}")
        stage_svgs.append(_FLYWHEEL_STAGE.substitute(
            cx=f"{sx:.1f}", cy=f"{sy:.1f}", label=label, font_size=font_size,
        ))

    # 箭头弧线 — 椭圆弧
    arrow_svgs = []
    for i in range(n):
        a1_deg = -90 + (360 / n) * i + 18
        a2_deg = -90 + (360 / n) * ((i + 1) % n) - 18
        a1 = math.radians(a1_deg)
        a2 = math.radians(a2_deg)
        x1 = cx + a * math.cos(a1)
        y1 = cy + b * math.sin(a1)
        x2 = cx + a * math.cos(a2)
        y2 = cy + b * math.sin(a2)
        span = (a2_deg - a1_deg) % 360
        large = 1 if span > 180 else 0
        path = f"M{x1:.1f},{y1:.1f} A{a:.1f},{b:.1f} 0 {large} 1 {x2:.1f},{y2:.1f}"
        arrow_svgs.append(f"""  <path d="{path}" fill="none" stroke="{accent}" stroke-width="5" stroke-opacity="0.85" marker-end="url(#arrowhead)"/>""")

    return FLYWHEEL_SVG.substitute(
        accent=accent,
        width=str(width), height=str(height),
        arrows="\n".join(arrow_svgs),
        stages="\n".join(stage_svgs),
    )


# ═══════════════════════════════════════════════════════════════
# 发展时间线 SVG 模板
# ═══════════════════════════════════════════════════════════════

TIMELINE_SVG = Template("""\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 $total_h" width="800" height="$total_h">
  <defs>
    <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#29B8D4"/>
      <stop offset="100%" stop-color="rgba(41,184,212,0.30)"/>
    </linearGradient>
  </defs>

  <!-- 背景 -->
  <rect width="800" height="$total_h" fill="#0B1629" rx="12"/>

  <!-- 中线 -->
  <line x1="160" y1="60" x2="160" y2="${line_end}" stroke="url(#lineGrad)" stroke-width="2"/>

  $events
</svg>""")

_TIMELINE_EVENT = Template("""\
  <!-- $year -->
  <circle cx="160" cy="$y" r="6" fill="#29B8D4"/>
  <circle cx="160" cy="$y" r="14" fill="none" stroke="rgba(41,184,212,0.25)" stroke-width="1"/>
  <text x="110" y="${y_label}" text-anchor="end"
        font-family="'IBM Plex Mono','SF Mono',Menlo,monospace"
        font-size="15" font-weight="700" fill="#29B8D4">$year</text>
  <text x="200" y="$y_title" dominant-baseline="hanging"
        font-family="'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif"
        font-size="18" font-weight="700" fill="#FFFFFF">$title</text>
  <text x="200" y="$y_desc" dominant-baseline="hanging"
        font-family="'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif"
        font-size="13" fill="rgba(255,255,255,0.55)">
    $desc
  </text>""")


def _build_timeline_svg(data: dict) -> str:
    """根据结构化 JSON 构建时间线 SVG"""
    events = data.get("events", [])
    if not events:
        raise ValueError("时间线至少需要 1 个事件")

    row_h = 90
    top_pad = 60
    bottom_pad = 40
    total_h = top_pad + len(events) * row_h + bottom_pad
    line_end = total_h - 20

    event_svgs = []
    for i, ev in enumerate(events):
        y = top_pad + i * row_h + 45
        year = ev.get("year", "")
        title = ev.get("title", "")
        desc = ev.get("desc", "")
        if len(desc) > 60:
            desc = desc[:58] + "…"
        event_svgs.append(_TIMELINE_EVENT.substitute(
            y=y, year=year, title=title, desc=desc,
            y_label=y + 5, y_title=y - 8, y_desc=y + 18,
        ))

    return TIMELINE_SVG.substitute(
        total_h=total_h,
        line_end=line_end,
        events="\n".join(event_svgs),
    )


# ═══════════════════════════════════════════════════════════════
# Markdown → JSON（LLM 提取结构化数据）
# ═══════════════════════════════════════════════════════════════

FLYWHEEL_EXTRACT_PROMPT = """从以下 Markdown 内容中提取增长飞轮的结构化数据，返回 JSON：

```json
{
  "center": "飞轮中心标题（简短，≤10字）",
  "stages": [
    {"label": "阶段1名（≤8字）", "desc": "阶段1简述（≤28字）"},
    ...
  ]
}
```

规则：
- center 取内容中飞轮的核心概念
- stages 取 3-5 个阶段，每个阶段的 label 简短、desc 精炼
- 只返回 JSON，不要其他文字

Markdown 内容：
"""

TIMELINE_EXTRACT_PROMPT = """从以下 Markdown 内容中提取发展沿袭时间线，返回 JSON：

```json
{
  "events": [
    {"year": "2020", "title": "事件标题（≤15字）", "desc": "简述（≤60字）"},
    ...
  ]
}
```

规则：
- 按时间从早到晚排列
- 每个事件 year/title 必填，desc 可选
- 提取 3-8 个关键事件
- 只返回 JSON，不要其他文字

Markdown 内容：
"""


def extract_flywheel_json(markdown: str, deepseek_call) -> dict | None:
    """用 LLM 从 Markdown 提取飞轮结构化 JSON"""
    try:
        result = deepseek_call(
            system_prompt=FLYWHEEL_EXTRACT_PROMPT,
            user_message=markdown,
            temperature=0.1,
            max_tokens=2048,
        )
        # 清理 markdown 代码块（兼容带/不带 trailing 空行的 LLM 输出）
        result = result.strip()
        if result.startswith("```"):
            lines = result.splitlines()
            lines = lines[1:]                          # 去掉 ```json 行
            if lines and lines[-1].strip() == "```":   # 去掉结尾 ``` 行（即使后有空格）
                lines = lines[:-1]
            result = "\n".join(lines)
        return json.loads(result.strip())
    except Exception:
        return None


def extract_timeline_json(markdown: str, deepseek_call) -> dict | None:
    """用 LLM 从 Markdown 提取时间线结构化 JSON"""
    try:
        result = deepseek_call(
            system_prompt=TIMELINE_EXTRACT_PROMPT,
            user_message=markdown,
            temperature=0.1,
            max_tokens=2048,
        )
        result = result.strip()
        if result.startswith("```"):
            lines = result.splitlines()
            lines = lines[1:]                          # 去掉 ```json 行
            if lines and lines[-1].strip() == "```":   # 去掉结尾 ``` 行（即使后有空格）
                lines = lines[:-1]
            result = "\n".join(lines)
        return json.loads(result.strip())
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# Playwright 渲染 SVG → PNG
# ═══════════════════════════════════════════════════════════════

def _html_to_png(html: str, dest: str, width: int = 800, height: int = 600, scale: int = 2):
    """用 Playwright 将 HTML 渲染为高清 PNG"""
    tmp = dest + ".html"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        from playwright.sync_api import sync_playwright
        from asset_pipeline import _find_chromium
        with sync_playwright() as p:
            exe = _find_chromium()
            if not exe:
                raise RuntimeError("找不到 Chromium。执行 'playwright install chromium'")
            browser = p.chromium.launch(
                headless=True, executable_path=exe,
                args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage","--disable-gpu"],
            )
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page.goto(f"file://{tmp}", wait_until="networkidle", timeout=15000)
            # Wait for web fonts to load (Google Fonts for SVG; ECharts uses system fonts)
            try:
                page.wait_for_function("document.fonts && document.fonts.ready", timeout=5000)
            except Exception:
                pass
            page.screenshot(path=dest, full_page=False, clip={
                "x": 0, "y": 0, "width": width, "height": height,
            })
            browser.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _svg_to_png(svg_content: str, dest: str, width: int = 800, height: int = 800, scale: int = 2):
    """用 Playwright 将 SVG 渲染为高清 PNG"""
    # NOTE: Google Fonts require network access; domestic deployments may need HTTPS_PROXY
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700;900&display=swap');
  body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: #FFFFFF; }}
  svg {{ display: block; }}
</style></head><body>{svg_content}</body></html>"""
    _html_to_png(html, dest, width, height, scale)


# ═══════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════

def render_with_template(
    data: dict, params: dict,
    template_id: str,
    dest: str,
) -> bool:
    """用指定模板 + 参数渲染 SVG → PNG"""
    from infographic_templates import get as get_template
    m = get_template(template_id)
    if not m:
        raise ValueError(f"模板 {template_id!r} 不存在")
    svg = m.build(data, params)
    card_w, card_h = 800, 800
    if "viewBox" in svg:
        import re
        m2 = re.search(r'viewBox="\d+\s+\d+\s+(\d+)\s+(\d+)"', svg)
        if m2:
            card_w, card_h = int(m2.group(1)), int(m2.group(2))
    _svg_to_png(svg, dest, width=card_w, height=card_h)
    return os.path.getsize(dest) > 512


def generate_flywheel_from_markdown(markdown: str, dest: str, deepseek_call) -> bool:
    """从 Markdown 提取 → 渲染飞轮 PNG"""
    data = extract_flywheel_json(markdown, deepseek_call)
    if not data:
        return False
    return render_flywheel(data, dest)


def generate_timeline_from_markdown(markdown: str, dest: str, deepseek_call) -> bool:
    """从 Markdown 提取 → 渲染时间线 PNG"""
    data = extract_timeline_json(markdown, deepseek_call)
    if not data:
        return False
    return render_timeline(data, dest)


# ═══════════════════════════════════════════════════════════════
# ECharts 散点图 — 竞争格局矩阵 + 产业链生态位图
# ═══════════════════════════════════════════════════════════════

_ECHARTS_VENDOR_PATH = os.path.join(
    os.path.dirname(__file__), "static", "vendor", "echarts.min.js"
)


def normalize_group_scores(
    companies: list[dict],
    raw_keys: list[str],
    *,
    suffix: str = "_norm",
    neutral: float = 0.5,
) -> tuple[list[dict], dict]:
    """非破坏式归一化：为每个 raw_key 新增 _norm 字段 (0..1)，原始字段不覆盖。"""
    meta = {"ranges": {}, "all_equal_keys": []}
    out = [dict(c) for c in companies]
    for key in raw_keys:
        vals = [float(c[key]) for c in out if c.get(key) is not None]
        if not vals:
            meta["ranges"][key] = {"min": None, "max": None}
            for c in out:
                c[f"{key}{suffix}"] = None
            continue
        lo, hi = min(vals), max(vals)
        meta["ranges"][key] = {"min": lo, "max": hi}
        if hi == lo:
            meta["all_equal_keys"].append(key)
            for c in out:
                c[f"{key}{suffix}"] = neutral if c.get(key) is not None else None
            continue
        for c in out:
            raw = c.get(key)
            c[f"{key}{suffix}"] = round((float(raw) - lo) / (hi - lo), 3) if raw is not None else None
    return out, meta


def _truncate_label(name: str, max_chars: int = 6) -> str:
    name = (name or "").strip()
    return name if len(name) <= max_chars else f"{name[:max_chars]}…"


def _point_priority(points: list[dict], target_company: str, max_companies: int) -> list[dict]:
    """确保 target 排第一，并截断到 max_companies。按 company_name 去重。"""
    target_key = (target_company or "").strip().lower()
    seen = set()
    keep = []
    for p in points:
        key = (p.get("company_name") or "").strip().lower()
        if key == target_key:
            keep.append(p)
            seen.add(key)
            break
    for p in points:
        key = (p.get("company_name") or "").strip().lower()
        if key not in seen:
            seen.add(key)
            keep.append(p)
        if len(keep) >= max_companies:
            break
    return keep



def _echarts_inline_js() -> str:
    """读取并缓存本地 ECharts JS，供 srcdoc/file:// 渲染路径内联使用。"""
    with open(_ECHARTS_VENDOR_PATH, encoding="utf-8") as f:
        return f.read()


def _echarts_script_tag() -> str:
    """Always use vendored ECharts (CLAUDE.md: 散点图用本地 vendor echarts)."""
    return f"<script>{_echarts_inline_js()}</script>"

# ── 辅助函数 ──

def _score(value, default=5.0) -> float:
    """安全读取评分值，钳制在 0–10。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(10.0, v))


def _map_stack_layer(value: str) -> str:
    """将 stack_layer 枚举值（英文/中文兼容）映射到 5 条泳道标签。"""
    mapping = {
        "vertical_app": "垂直应用",
        "distribution": "分发渠道",
        "middleware": "中间件层",
        "foundation_model": "模型层",
        "infrastructure": "基础设施层",
        "垂直应用": "垂直应用",
        "分发渠道": "分发渠道",
        "中间件": "中间件层",
        "基础模型": "模型层",
        "基础设施": "基础设施层",
        "应用层": "垂直应用",  # 旧版兼容
        "中间件层": "中间件层",
        "模型层": "模型层",
        "基础设施层": "基础设施层",
    }
    return mapping.get(str(value or ""), "垂直应用")


# 产业链泳道（从上到下：分发→垂直应用→中间件→模型→基础设施）
_STACK_LANE_LABELS = ["分发渠道", "垂直应用", "中间件层", "模型层", "基础设施层"]

# 泳道层级说明文字（Y 轴左侧，空间不足时可省略）
_STACK_LANE_DESC = {
    "分发渠道": "入口、插件市场与聚合平台",
    "垂直应用": "面向终端用户的应用与工作流",
    "中间件层": "连接模型与业务场景",
    "模型层": "提供核心智能能力",
    "基础设施层": "算力、数据与底层平台",
}


def _chart_empty_html(title: str, message: str = "暂无可用图表数据",
                      params: dict | None = None) -> str:
    p = params or {}
    theme = p.get("theme", "light")
    w = int(p.get("width") or 900)
    h = int(p.get("height") or 600)
    bg = "#0B1629" if theme == "dark" else "#FFFFFF"
    text_color = "#E8ECF1" if theme == "dark" else "#1B2A4A"
    muted = "rgba(255,255,255,0.52)" if theme == "dark" else "#64748b"
    accent = p.get("accent_color", "#29B8D4")
    safe_title = _html_escape(p.get("title") or title)
    safe_message = _html_escape(message)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:{bg};
    font-family:"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;color:{text_color}}}
  .wrap{{width:{w}px;height:{h}px;display:flex;align-items:center;justify-content:center;position:relative}}
  .grid{{position:absolute;inset:0;background-image:linear-gradient(rgba(41,184,212,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(41,184,212,.08) 1px,transparent 1px);background-size:40px 40px;opacity:.35}}
  .panel{{position:relative;text-align:center;border:1px solid rgba(41,184,212,.28);border-radius:8px;padding:34px 48px;background:rgba(255,255,255,.035)}}
  h1{{margin:0 0 12px;font-size:22px;letter-spacing:0;color:{text_color}}}
  p{{margin:0;color:{muted};font-size:14px}}
  .bar{{width:72px;height:2px;background:{accent};margin:0 auto 18px}}
</style></head><body>
<div class="wrap"><div class="grid"></div><div class="panel"><div class="bar"></div><h1>{safe_title}</h1><p>{safe_message}</p></div></div>
</body></html>"""


def _html_escape(value: object) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _echarts_fit_style(bg: str, width: int = 900, height: int = 600) -> str:
    return f"""
  html,body{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:{bg};
    font-family:"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;}}
  body{{position:relative}}
  #chart-frame{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden;background:{bg}}}
  #chart{{width:{width}px;height:{height}px;flex:0 0 auto;transform-origin:center center}}
  #chart>div:first-child,#chart>div:first-child>canvas{{transform-origin:center center}}
  #chart>div:first-child>canvas{{display:block;width:100%!important;height:100%!important;object-fit:contain}}
"""


def _echarts_fit_script(chart_var: str = "chart",
                        width: int = 900, height: int = 600) -> str:
    return f"""
function fitChartCanvas(){{
  var frame=document.getElementById('chart-frame');
  var chartEl=document.getElementById('chart');
  if(!frame||!chartEl) return;
  var scale=Math.min(frame.clientWidth/{width}, frame.clientHeight/{height});
  if(!isFinite(scale)||scale<=0) scale=1;
  chartEl.style.transform='scale('+scale+')';
  if({chart_var}&&{chart_var}.resize) {chart_var}.resize();
}}
window.addEventListener('resize', fitChartCanvas);
fitChartCanvas();
"""


def _get_competitive_title(company_name: str, x: float, y: float) -> str:
    """根据目标公司坐标生成动态结论标题。"""
    if x < 5 and y >= 5:
        zone = "战略机会区"
        desc = "高护城河 × 低巨头压力"
    elif x >= 5 and y >= 5:
        zone = "硬仗区"
        desc = "高护城河 × 高巨头压力"
    elif x >= 5 and y < 5:
        zone = "高危区"
        desc = "低护城河 × 高巨头压力"
    else:
        zone = "边缘区"
        desc = "低护城河 × 低巨头压力"
    return f"{company_name}：{zone}｜{desc}"


def _get_stack_title(company_name: str, layer: str, vc: float) -> str:
    """根据目标公司变现能力生成动态结论标题。"""
    if vc >= 7:
        level = "高变现能力"
    elif vc >= 4:
        level = "中变现能力"
    else:
        level = "低变现能力"
    return f"{company_name}：{layer} / {level}"


def _build_focus_lane_layout(focus_index: int) -> tuple[dict[int, float], list[dict]]:
    """Return compressed y centers and continuous bands without background gaps."""
    other_height = 0.55
    focus_height = 1.4
    start = float(focus_index) - focus_height / 2 - focus_index * other_height
    centers: dict[int, float] = {}
    bands = []
    cursor = start
    for i, label in enumerate(_STACK_LANE_LABELS):
        height = focus_height if i == focus_index else other_height
        band_start = round(cursor, 3)
        band_end = round(cursor + height, 3)
        center = round((band_start + band_end) / 2, 3)
        centers[i] = center
        color = "rgba(41,184,212,0.10)" if i == focus_index else "rgba(148,163,184,0.40)"
        bands.append({
            "lane": label,
            "center": center,
            "start": band_start,
            "end": band_end,
            "height": height,
            "is_focus": i == focus_index,
            "color": color,
        })
        cursor = band_end
    return centers, bands


def _build_competitive_landscape_html(
    companies: list[dict], highlight: str,
    params: dict | None = None,
) -> str:
    """竞争格局定位图 HTML — 绝对 0–10 坐标 + 象限背景 + 目标公司高亮 + 动态结论标题。

    X 轴 = score_incumbent_attention（巨头关注度，0–10 绝对分）
    Y 轴 = score_defensibility（护城河强度，0–10 绝对分）
    """
    p = dict(params or {})
    p.setdefault("max_companies", 8)
    accent = p.get("accent_color", "#29B8D4")
    width = int(p.get("width") or 800)
    height = int(p.get("height") or 600)
    t_size = int(p.get("title_size") or 20)
    a_size = int(p.get("axis_size") or 13)
    l_size = int(p.get("label_size") or 12)
    theme = p.get("theme", "light")
    max_cos = int(p.get("max_companies", 8))

    bg = "#FFFFFF" if theme == "light" else "#0B1629"
    text_color = "#1B2A4A" if theme == "light" else "#E8ECF1"
    muted = "#6B7280" if theme == "light" else "rgba(255,255,255,0.55)"
    line_color = "#E5E7EB" if theme == "light" else "rgba(255,255,255,0.10)"
    q_bg_alpha = "0.10" if theme == "light" else "0.08"
    q_label_color = "rgba(0,0,0,0.32)" if theme == "light" else "rgba(255,255,255,0.22)"

    # 域过滤（使用原始 0–10 分，不做归一化）
    domain = [
        c for c in companies
        if c.get("score_defensibility") is not None
        and c.get("score_incumbent_attention") is not None
    ]
    domain = _point_priority(domain, highlight, max_cos)

    # 构建数据点（直接使用原始 0–10 分作为坐标）
    points = []
    for c in domain:
        n = str(c.get("display_name") or c.get("company_name") or "")
        is_hi = (c.get("company_name") or "").strip().lower() == highlight.strip().lower()
        is_estimated = bool(c.get("estimated_position"))
        x_raw = _score(c.get("score_incumbent_attention"))
        y_raw = _score(c.get("score_defensibility"))
        points.append({
            "name": n,
            "value": [x_raw, y_raw],
            "is_highlight": is_hi,
            "is_estimated": is_estimated,
        })

    # 动态标题
    target_point = _find_highlight_point(points, highlight)
    if target_point:
        tx = target_point["value"][0]
        ty = target_point["value"][1]
        title_text = _get_competitive_title(target_point["name"], tx, ty)
    else:
        title_text = p.get("title", "竞争格局定位图")

    no_data = not points
    ds_json = json.dumps(points, ensure_ascii=False)
    title_json = json.dumps(title_text, ensure_ascii=False)

    result = '<!DOCTYPE html>\n'
    result += '<html><head><meta charset="utf-8">\n<style>\n'
    result += _echarts_fit_style(bg, width, height)
    result += '\n</style></head><body>\n'
    result += '<div id="chart-frame"><div id="chart"></div></div>\n'
    result += _echarts_script_tag() + '\n<script>\n'
    result += 'var points=' + ds_json + ';\n'
    result += 'var series=[{\n'
    result += '  type:"scatter", data:points,\n'
    result += '  symbolSize:function(val,params){\n'
    result += '    if(params.data&&params.data.is_highlight) return 22;\n'
    result += '    if(params.data&&params.data.is_estimated) return 16;\n'
    result += '    return 14;\n'
    result += '  },\n'
    result += '  itemStyle:{\n'
    result += '    color:function(params){\n'
    result += '      if(params.data&&params.data.is_highlight) return "' + accent + '";\n'
    result += '      if(params.data&&params.data.is_estimated) return "rgba(27,42,74,0.28)";\n'
    result += '      return "rgba(27,42,74,0.35)";\n'
    result += '    },\n'
    result += '    opacity:function(params){\n'
    result += '      if(params.data&&params.data.is_highlight) return 1;\n'
    result += '      if(params.data&&params.data.is_estimated) return 0.55;\n'
    result += '      return 0.65;\n'
    result += '    },\n'
    result += '    borderColor:function(params){\n'
    result += '      if(params.data&&params.data.is_highlight) return "#FFFFFF";\n'
    result += '      if(params.data&&params.data.is_estimated) return "rgba(27,42,74,0.4)";\n'
    result += '      return "transparent";\n'
    result += '    },\n'
    result += '    borderWidth:function(params){\n'
    result += '      if(params.data&&params.data.is_highlight) return 2;\n'
    result += '      if(params.data&&params.data.is_estimated) return 1.5;\n'
    result += '      return 0;\n'
    result += '    },\n'
    result += '    borderType:function(params){\n'
    result += '      return params.data&&params.data.is_estimated?"dashed":"solid";\n'
    result += '    },\n'
    result += '  },\n'
    result += '  label:{\n'
    result += '    show:true,\n'
    result += '    formatter:function(params){return params.data?params.data.name:"";},\n'
    result += '    fontSize:' + str(l_size) + ',fontWeight:"bold",color:"#1B2A4A",\n'
    result += '    backgroundColor:"rgba(255,255,255,0.92)",borderRadius:4,padding:[3,6],\n'
    result += '    position:"right",\n'
    result += '  },\n'
    result += '  labelLayout:{hideOverlap:true,moveOverlap:"shiftY"},\n'
    result += '  markLine:{\n'
    result += '    silent:true,symbol:"none",\n'
    result += '    lineStyle:{type:"dashed",color:"rgba(27,42,74,0.18)",width:1},\n'
    result += '    data:[{xAxis:5,label:{show:false}},{yAxis:5,label:{show:false}}],\n'
    result += '  },\n'
    result += '  markArea:{\n'
    result += '    silent:true,\n'
    result += '    data:[\n'
    result += '      [{xAxis:0,yAxis:5,itemStyle:{color:"rgba(40,200,120,' + q_bg_alpha + ')"}},{xAxis:5,yAxis:10}],\n'
    result += '      [{xAxis:5,yAxis:5,itemStyle:{color:"rgba(255,140,0,' + q_bg_alpha + ')"}},{xAxis:10,yAxis:10}],\n'
    result += '      [{xAxis:5,yAxis:0,itemStyle:{color:"rgba(220,50,50,' + q_bg_alpha + ')"}},{xAxis:10,yAxis:5}],\n'
    result += '      [{xAxis:0,yAxis:0,itemStyle:{color:"rgba(180,180,180,' + q_bg_alpha + ')"}},{xAxis:5,yAxis:5}],\n'
    result += '    ],\n'
    result += '  },\n'
    result += '}];\n\n'
    result += 'var opt={\n'
    result += '  animation:false,\n'
    result += '  backgroundColor:"' + bg + '",\n'
    result += '  title:{text:' + title_json + ',left:24,top:18,\n'
    result += '    textStyle:{color:"' + text_color + '",fontSize:' + str(t_size) + ',fontWeight:"bold"}},\n'
    result += '  tooltip:{trigger:"item",\n'
    result += '    formatter:function(p){\n'
    result += '      var d=p.data||{};\n'
    result += '      var est=d.is_estimated?" ≈（估算）":"";\n'
    result += '      return "<b>"+d.name+est+"</b><br/>"\n'
    result += '        +"巨头关注度："+(d.value[0]!=null?d.value[0].toFixed(1)+" / 10":"-")+"<br/>"\n'
    result += '        +"护城河强度："+(d.value[1]!=null?d.value[1].toFixed(1)+" / 10":"-");\n'
    result += '    }\n'
    result += '  },\n'
    result += '  legend:{show:false},\n'
    result += '  grid:{left:72,right:32,top:72,bottom:72},\n'
    result += '  xAxis:{\n'
    result += '    type:"value",min:0,max:10,scale:false,boundaryGap:false,\n'
    result += '    name:"巨头关注度 →",nameLocation:"middle",nameGap:32,\n'
    result += '    nameTextStyle:{color:"' + text_color + '",fontSize:14,fontWeight:"bold"},\n'
    result += '    axisLine:{lineStyle:{color:"' + line_color + '"}},\n'
    result += '    axisLabel:{color:"' + muted + '",fontSize:11,\n'
    result += '      formatter:function(v){if(v===0)return"低";if(v===5)return"中";if(v===10)return"高";return"";}},\n'
    result += '    splitLine:{lineStyle:{color:"' + line_color + '",type:"dashed"}},\n'
    result += '    splitNumber:5,\n'
    result += '  },\n'
    result += '  yAxis:{\n'
    result += '    type:"value",min:0,max:10,scale:false,boundaryGap:false,\n'
    result += '    name:"护城河强度 ↑",nameLocation:"middle",nameGap:44,\n'
    result += '    nameTextStyle:{color:"' + text_color + '",fontSize:14,fontWeight:"bold"},\n'
    result += '    axisLine:{lineStyle:{color:"' + line_color + '"}},\n'
    result += '    axisLabel:{color:"' + muted + '",fontSize:11,\n'
    result += '      formatter:function(v){if(v===0)return"低";if(v===5)return"中";if(v===10)return"高";return"";}},\n'
    result += '    splitLine:{lineStyle:{color:"' + line_color + '",type:"dashed"}},\n'
    result += '    splitNumber:5,\n'
    result += '  },\n'
    result += '  series:series,\n'
    # 象限标签（大号灰色透明文字）
    result += '  graphic:[\n'
    # Q1 战略机会区（左上：x<5, y≥5）
    result += '    {type:"text",left:246,top:186,style:{text:"战略机会区",fill:"rgba(40,200,120,0.18)",fontSize:28,fontWeight:900,textAlign:"center",textVerticalAlign:"middle"}},\n'
    # Q2 硬仗区（右上：x≥5, y≥5）
    result += '    {type:"text",left:594,top:186,style:{text:"硬仗区",fill:"rgba(255,140,0,0.18)",fontSize:28,fontWeight:900,textAlign:"center",textVerticalAlign:"middle"}},\n'
    # Q3 高危区（右下：x≥5, y<5）
    result += '    {type:"text",left:594,top:414,style:{text:"高危区",fill:"rgba(220,50,50,0.18)",fontSize:28,fontWeight:900,textAlign:"center",textVerticalAlign:"middle"}},\n'
    # Q4 边缘区（左下：x<5, y<5）
    result += '    {type:"text",left:246,top:414,style:{text:"边缘区",fill:"rgba(180,180,180,0.18)",fontSize:28,fontWeight:900,textAlign:"center",textVerticalAlign:"middle"}},\n'
    if no_data:
        result += '    {type:"text",left:"center",top:"middle",style:{text:"暂无可用图表数据",fill:"' + muted + '",fontSize:18,fontWeight:700,textAlign:"center"}},\n'
    if any(p.get("is_estimated") for p in points):
        result += '    {type:"text",left:76,top:' + str(height - 28) + ',style:{text:"≈ 估算位置",fill:"rgba(27,42,74,0.35)",fontSize:11,fontWeight:500}},\n'
    result += '  ],\n'
    result += '};\n'
    result += "var chart=echarts.init(document.getElementById('chart'));\n"
    result += "chart.setOption(opt);\n"
    result += _echarts_fit_script("chart", width, height) + '\n'
    result += "</script></body></html>"

    return result


def _score_level(score: float) -> str:
    """将原始 0-10 评分映射为低/中/高。"""
    if score is None:
        return "?"
    if score < 4:
        return "低"
    if score < 7:
        return "中"
    return "高"


def _find_highlight_point(points: list[dict], highlight: str) -> dict | None:
    """在 points 列表中查找目标公司数据点。"""
    hl = (highlight or "").strip().lower()
    for p in points:
        if p.get("is_highlight"):
            return p
    for p in points:
        if (p.get("name") or "").strip().lower() == hl:
            return p
    return None


def _build_ecosystem_positioning_html(
    companies: list[dict], highlight: str,
    params: dict | None = None,
) -> str:
    """AI 栈生态位图 HTML — 绝对 0–10 坐标 + 5 条泳道 + 同泳道垂直错开 + 动态结论标题。

    X 轴 = score_value_capture（变现能力，0–10 绝对分）
    Y 轴 = value 轴（0–4）+ 同泳道 jitter 防重叠
    """
    p = dict(params or {})
    p.setdefault("max_companies", 8)
    accent = p.get("accent_color", "#29B8D4")
    width = int(p.get("width") or 800)
    height = int(p.get("height") or 600)
    t_size = int(p.get("title_size") or 20)
    a_size = int(p.get("axis_size") or 13)
    l_size = int(p.get("label_size") or 12)
    title_font_size = t_size * 2
    axis_font_size = a_size * 2
    label_font_size = l_size * 2
    theme = p.get("theme", "light")
    max_cos = int(p.get("max_companies", 8))

    bg = "#FFFFFF" if theme == "light" else "#0B1629"
    text_color = "#1B2A4A" if theme == "light" else "#E8ECF1"
    muted = "#6B7280" if theme == "light" else "rgba(255,255,255,0.55)"
    line_color = "#E5E7EB" if theme == "light" else "rgba(255,255,255,0.10)"

    # -- 泳道 → 数值索引映射 --
    lane_index = {label: i for i, label in enumerate(_STACK_LANE_LABELS)}  # 0..4

    # -- 数据：使用原始 0–10 分，不做归一化 --
    domain = [
        c for c in companies
        if c.get("score_value_capture") is not None
        and c.get("stack_layer") is not None
    ]
    domain = _point_priority(domain, highlight, max_cos)

    focus_li = 1
    highlight_key = highlight.strip().lower()
    for c in domain:
        if (c.get("company_name") or "").strip().lower() == highlight_key:
            focus_layer = _map_stack_layer(c.get("stack_layer"))
            focus_li = lane_index.get(focus_layer, 1)
            break
    lane_centers, lane_bands = _build_focus_lane_layout(focus_li)
    lane_label_map = {
        f"{band['center']:.1f}": band["lane"]
        for band in lane_bands
    }
    y_min = lane_bands[0]["start"] if lane_bands else -0.5
    y_max = lane_bands[-1]["end"] if lane_bands else 4.5

    # -- 按泳道分组，同泳道内按 X 排序后加 Y 偏移（垂直错开防重叠）--
    lane_groups: dict[int, list[dict]] = {}
    for c in domain:
        sl = _map_stack_layer(c.get("stack_layer"))
        li = lane_index.get(sl, 1)
        lane_groups.setdefault(li, []).append(c)

    points = []
    for li, group in lane_groups.items():
        group.sort(key=lambda c: _score(c.get("score_value_capture")))
        non_highlight = [
            c for c in group
            if (c.get("company_name") or "").strip().lower() != highlight_key
        ]
        non_highlight_index = {
            id(c): idx for idx, c in enumerate(non_highlight)
        }
        n_other = len(non_highlight)
        for j, c in enumerate(group):
            n = str(c.get("display_name") or c.get("company_name") or "")
            sx_raw = _score(c.get("score_value_capture"))
            is_hi = (c.get("company_name") or "").strip().lower() == highlight.strip().lower()
            base_y = lane_centers.get(li, float(li))
            if is_hi or n_other == 0:
                y_val = base_y
            else:
                span = 0.34 if li != focus_li else 0.62
                idx = non_highlight_index[id(c)]
                y_val = base_y + (idx - (n_other - 1) / 2) * (span / max(n_other, 1))
            points.append({
                "name": n,
                "value": [sx_raw, round(y_val, 3)],
                "is_highlight": is_hi,
                "lane": _STACK_LANE_LABELS[li],
                "raw_lane_index": li,
            })

    # -- 动态标题 --
    target = _find_highlight_point(points, highlight)
    for idx, point in enumerate(points):
        if point.get("is_highlight"):
            point["label"] = {"position": "right", "distance": 14}
            continue
        if point.get("raw_lane_index") == focus_li:
            # 焦点泳道内，竞品标签放到点左侧，避免压住目标公司标签。
            point["label"] = {"position": "left", "distance": 14}
        else:
            label_position = "top" if point.get("raw_lane_index", focus_li) < focus_li else "bottom"
            point["label"] = {
                "position": label_position,
                "distance": 12,
            }
    if target:
        vc = target["value"][0]
        layer_name = target.get("lane") or _STACK_LANE_LABELS[focus_li]
        title_text = _get_stack_title(target["name"], layer_name, vc)
    else:
        title_text = p.get("title", "AI 栈生态位图")

    # 拆成两个 series：目标公司在 series[1]（后渲染=上层），竞品在 series[0]
    target_points = [p for p in points if p.get("is_highlight")]
    other_points = [p for p in points if not p.get("is_highlight")]
    target_json = json.dumps(target_points, ensure_ascii=False)
    other_json = json.dumps(other_points, ensure_ascii=False)
    lane_label_map_json = json.dumps(lane_label_map, ensure_ascii=False)
    lane_bands_json = json.dumps(lane_bands, ensure_ascii=False)
    lane_labels_json = json.dumps([
        {"name": band["lane"], "center": band["center"], "is_focus": band["is_focus"]}
        for band in lane_bands
    ], ensure_ascii=False)

    no_data = not points
    title_json = json.dumps(title_text, ensure_ascii=False)
    # -- ECharts JS 组件 --
    # series[0] = 竞品（底层），series[1] = 目标公司（上层），series[2] = 泳道背景（最底）
    series_js = (
        'var series=[{'
        'name:"竞品",type:"scatter",data:' + other_json + ','
        'symbolSize:12,'
        'itemStyle:{color:"rgba(27,42,74,0.30)",opacity:0.65,borderColor:"transparent",borderWidth:0},'
        'label:{show:true,formatter:function(p){return p.data?p.data.name:"";},'
        'fontSize:' + str(label_font_size) + ',fontWeight:"bold",color:"#1B2A4A",'
        'backgroundColor:"#FFFFFF",borderRadius:4,padding:[3,6],'
        'position:"right",distance:10},'
        'labelLayout:{hideOverlap:true,moveOverlap:"shiftY"},'
        '},{'
        'name:"目标公司",type:"scatter",data:' + target_json + ','
        'symbolSize:22,'
        'itemStyle:{color:"' + accent + '",opacity:1,borderColor:"#FFFFFF",borderWidth:2},'
        'z:10,'
        'label:{show:true,formatter:function(p){return p.data?p.data.name:"";},'
        'fontSize:' + str(label_font_size) + ',fontWeight:"bold",color:"#1B2A4A",'
        'backgroundColor:"#FFFFFF",borderRadius:4,padding:[3,6],'
        'position:"right",distance:10},'
        'labelLayout:{hideOverlap:true,moveOverlap:"shiftY"},'
        'markArea:{'
        'silent:true,'
        'data:[[{xAxis:7},{xAxis:10}]],'
        'itemStyle:{color:"rgba(40,180,100,0.07)"},'
        '},'
        '}];'
    )

    # xAxis — 0-10 绝对分，formatter 显示 低/中/高
    xaxis_js = (
        'xAxis:{'
        'type:"value",min:0,max:10,scale:false,boundaryGap:false,'
        'name:"变现能力 →",nameLocation:"middle",nameGap:36,'
        'nameTextStyle:{color:"' + text_color + '",fontSize:' + str(axis_font_size) + ',fontWeight:"bold"},'
        'axisLine:{lineStyle:{color:"' + line_color + '",width:1.5}},'
        'axisLabel:{'
        'color:"' + muted + '",fontSize:' + str(axis_font_size) + ','
        'formatter:function(v){if(v===0)return"低";if(v===5)return"中";if(v===10)return"高";return"";}'
        '},'
        'splitLine:{lineStyle:{color:"' + line_color + '",type:"dashed"}},'
        'splitNumber:5,'
        '},'
    )

    # yAxis — value 轴，自定义标签为泳道名（+ 交替背景 + 分隔线放 extra series）
    yaxis_js = (
        'yAxis:{'
        'type:"value",min:' + str(y_min) + ',max:' + str(y_max) + ',interval:0.5,inverse:true,'
        'axisLine:{lineStyle:{color:"' + line_color + '",width:1.5}},'
        'axisLabel:{show:false},'
        'splitLine:{show:false},'
        '},'
    )

    # 焦点泳道高亮；其他泳道底色 40% 灰，并按 50% 高度绘制。
    lane_extra = (
        'markArea:{silent:true,data:laneBands.map(function(b){return '
        '[{xAxis:0,yAxis:b.start,itemStyle:{color:b.color}},{xAxis:10,yAxis:b.end}];})},'
        'markLine:{silent:true,symbol:"none",'
        'lineStyle:{color:"' + line_color + '",type:"solid",width:1},'
        'label:{show:false},'
        'data:laneBands.flatMap(function(b){return [{yAxis:b.start},{yAxis:b.end}];})},'
    )

    grid_js = 'grid:{left:170,right:40,top:92,bottom:92},'

    title_js = (
        'title:{text:' + title_json + ',left:24,top:18,'
        'textStyle:{color:"' + text_color + '",fontSize:' + str(title_font_size) + ',fontWeight:"bold"}},'
    )

    if no_data:
        graphic_js = (
            'graphic:[{type:"text",left:"center",top:"middle",'
            'style:{text:"暂无可用图表数据",fill:"' + muted + '",fontSize:18,fontWeight:700,textAlign:"center"}}],'
        )
    else:
        graphic_js = 'graphic:[],'

    # -- 完整 HTML --
    result = '<!DOCTYPE html>\n'
    result += '<html><head><meta charset="utf-8">\n<style>\n'
    result += _echarts_fit_style(bg, width, height)
    result += '\n</style></head><body>\n'
    result += '<div id="chart-frame"><div id="chart"></div></div>\n'
    result += _echarts_script_tag() + '\n<script>\n'
    result += series_js + '\n\n'
    result += 'var focusLaneIndex=' + str(focus_li) + ';\n'
    result += 'var laneBands=' + lane_bands_json + ';\n'
    result += 'var laneLabels=' + lane_labels_json + ';\n'
    result += 'var opt={\n'
    result += '  animation:false,\n'
    result += '  backgroundColor:"' + bg + '",\n'
    result += '  ' + title_js + '\n'
    result += '  tooltip:{trigger:"item",\n'
    result += '    formatter:function(p){\n'
    result += '      var d=p.data||{};\n'
    result += '      var layerName=d.lane||"";\n'
    result += '      return "<b>"+d.name+"</b><br/>"\n'
    result += '        +"层级："+layerName+"<br/>"\n'
    result += '        +"变现能力："+(d.value[0]!=null?d.value[0].toFixed(1)+" / 10":"-");\n'
    result += '    }\n'
    result += '  },\n'
    result += '  legend:{show:false},\n'
    result += '  ' + grid_js + '\n'
    result += '  ' + xaxis_js + '\n'
    result += '  ' + yaxis_js + '\n'
    result += '  series:series,\n'
    result += '  ' + graphic_js + '\n'
    result += '};\n'
    # 额外 series 承载泳道交替背景 + 分隔线
    result += 'opt.series.push({type:"scatter",data:[],z:-10,' + lane_extra + '});\n'
    result += "var chart=echarts.init(document.getElementById('chart'));\n"
    result += "chart.setOption(opt);\n"
    result += """
function applyLaneLabels(){
  var labels = laneLabels.map(function(b){
    var point = chart.convertToPixel({xAxisIndex:0,yAxisIndex:0}, [0, b.center]);
    return {
      id:"lane-label-"+b.name,
      type:"text",
      left:18,
      top:point[1]-13,
      style:{
        text:b.name,
        fill:"#1B2A4A",
        fontSize:""" + str(label_font_size) + """,
        fontWeight:900,
        textAlign:"right",
        textVerticalAlign:"middle"
      }
    };
  });
  chart.setOption({graphic: labels});
}
applyLaneLabels();
chart.on("finished", applyLaneLabels);
window.addEventListener("resize", applyLaneLabels);
"""
    result += _echarts_fit_script("chart", width, height) + '\n'
    result += "</script></body></html>"

    return result



def build_stack_positioning_svg(companies: list[dict], highlight: str,
                                 params: dict | None = None) -> str:
    """产业链生态位图 HTML（ECharts 离散轴散点图）"""
    return _build_ecosystem_positioning_html(companies, highlight, params)



def build_competitive_landscape_svg(companies: list[dict], highlight: str,
                                     params: dict | None = None) -> str:
    """竞争格局矩阵 HTML（ECharts 四象限散点图）"""
    return _build_competitive_landscape_html(companies, highlight, params)


def render_competitive_landscape(companies: list[dict], highlight: str, dest: str,
                                  params: dict | None = None) -> bool:
    try:
        p = params or {}
        w = int(p.get("width") or 800)
        h = int(p.get("height") or 600)
        html = build_competitive_landscape_svg(companies, highlight, params)
        _html_to_png(html, dest, width=w, height=h, scale=2)
        return os.path.getsize(dest) > 1024
    except Exception:
        return False


def render_stack_positioning(companies: list[dict], highlight: str, dest: str,
                              params: dict | None = None) -> bool:
    try:
        p = params or {}
        w = int(p.get("width") or 800)
        h = int(p.get("height") or 600)
        html = build_stack_positioning_svg(companies, highlight, params)
        _html_to_png(html, dest, width=w, height=h, scale=2)
        return os.path.getsize(dest) > 1024
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# 飞轮 / 时间线渲染（SVG 模板 → Playwright PNG）
# ═══════════════════════════════════════════════════════════════

def render_flywheel(data: dict, dest: str) -> bool:
    """从 JSON 渲染飞轮 SVG → PNG，返回是否成功"""
    try:
        svg = _build_flywheel_svg(data)
        _svg_to_png(svg, dest, width=800, height=800)
        return os.path.getsize(dest) > 512
    except Exception:
        return False


def render_timeline(data: dict, dest: str) -> bool:
    """从 JSON 渲染时间线 SVG → PNG，返回是否成功"""
    try:
        svg = _build_timeline_svg(data)
        n = len(data.get("events", []))
        total_h = 60 + n * 90 + 40
        _svg_to_png(svg, dest, width=800, height=total_h)
        return os.path.getsize(dest) > 512
    except Exception:
        return False
