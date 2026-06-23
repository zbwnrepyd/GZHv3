"""WhatWeb / 技术面适配器 — 本地 Python 实现。

通过 HTTP 请求目标官网，检测 HTTP 响应头与 HTML 中的技术栈特征，
不依赖外部二进制（WhatWeb）或 API Key。
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from ..source_adapter import ADAPTER_REGISTRY, SourceAdapter, SourceDocument

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ── 技术栈特征签名 ───────────────────────────────────────────────────────────

_HEADER_TECHS: dict[str, str] = {
    "server": "Server",
    "x-powered-by": "X-Powered-By",
    "x-aspnet-version": "ASP.NET",
    "x-generator": "Generator",
    "cf-ray": "Cloudflare",
    "x-cache": "CDN-Cache",
    "x-amz-cf-id": "AWS-CloudFront",
    "x-vercel-cache": "Vercel",
    "x-nextjs-cache": "Next.js",
    "x-lambda-id": "AWS-Lambda",
    "x-drupal-cache": "Drupal",
    "x-shopify-stage": "Shopify",
    "x-wix-request-id": "Wix",
    "x-squarespace": "Squarespace",
}

_HTML_TECHS: list[tuple[str, str]] = [
    # JS 框架
    (r'<script[^>]+src="[^"]*react[^"]*\.js', "React"),
    (r'<script[^>]+src="[^"]*vue[^"]*\.js', "Vue.js"),
    (r'<script[^>]+src="[^"]*angular[^"]*\.js', "Angular"),
    (r'<script[^>]+src="[^"]*svelte[^"]*\.js', "Svelte"),
    (r'<script[^>]+src="[^"]*jquery[^"]*\.js', "jQuery"),
    (r'<script[^>]+src="[^"]*alpine[^"]*\.js', "Alpine.js"),
    (r'<script[^>]+src="[^"]*preact[^"]*\.js', "Preact"),
    (r'__NEXT_DATA__', "Next.js"),
    (r'window\.__NUXT__', "Nuxt.js"),
    (r'data-reactroot', "React"),
    (r'id="__next"', "Next.js"),
    # 构建工具 / bundler
    (r'<script[^>]+src="[^"]*webpack[^"]*\.js', "webpack"),
    (r'<script[^>]+src="[^"]*vite[^"]*\.js', "Vite"),
    # CSS 框架
    (r'class="[^"]*tailwind', "Tailwind CSS"),
    (r'<link[^>]+href="[^"]*bootstrap[^"]*\.css', "Bootstrap"),
    (r'<link[^>]+href="[^"]*tailwind[^"]*\.css', "Tailwind CSS"),
    (r'<link[^>]+href="[^"]*bulma[^"]*\.css', "Bulma"),
    # 分析 / 监控
    (r'googletagmanager\.com', "Google Tag Manager"),
    (r'google-analytics\.com', "Google Analytics"),
    (r'gtag\(', "Google Analytics"),
    (r'cdn\.segment\.com', "Segment"),
    (r'cdn\.amplitude\.com', "Amplitude"),
    (r'cdn\.mixpanel\.com', "Mixpanel"),
    (r'static\.hotjar\.com', "Hotjar"),
    (r'sentry-cdn\.com', "Sentry"),
    (r'datadoghq-browser-agent', "Datadog"),
    # CDN / 基础设施
    (r'cdn\.cloudflare\.com', "Cloudflare CDN"),
    (r'cloudfront\.net', "AWS CloudFront"),
    (r'cdnjs\.cloudflare\.com', "cdnjs"),
    (r'unpkg\.com', "unpkg"),
    (r'jsdelivr\.net', "jsDelivr"),
    (r'netlify', "Netlify"),
    (r'vercel', "Vercel"),
    # 字体 / 设计
    (r'fonts\.googleapis\.com', "Google Fonts"),
    (r'fonts\.gstatic\.com', "Google Fonts"),
    (r'typekit\.net', "Adobe Fonts"),
    (r'fontawesome', "Font Awesome"),
    # 认证 / 支付
    (r'auth0', "Auth0"),
    (r'clerk\.js', "Clerk"),
    (r'stripe\.com', "Stripe"),
    (r'js\.chargebee\.com', "Chargebee"),
    # CMS
    (r'wp-content', "WordPress"),
    (r'wp-includes', "WordPress"),
    (r'/ghost/', "Ghost"),
    (r'contentful\.com', "Contentful"),
    (r'prismic\.io', "Prismic"),
    (r'sanity\.io', "Sanity"),
    # 其他
    (r'intercom', "Intercom"),
    (r'crisp\.chat', "Crisp"),
    (r'zendesk', "Zendesk"),
    (r'hubspot', "HubSpot"),
    (r'__lc\.', "LiveChat"),
]


def _detect_technologies(url: str, timeout: int) -> dict:
    """获取目标 URL 并检测技术栈，返回 {url, status, headers: {}, techs: []}。"""
    result: dict = {"url": url, "status": 0, "headers": {}, "techs": []}
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        result["status"] = resp.status_code
        result["headers"] = {k.lower(): v for k, v in resp.headers.items()}
        html = resp.text or ""
    except Exception as exc:
        logger.warning("WhatWebAdapter: fetch failed for %s: %s", url, exc)
        return result

    techs: list[str] = []

    # 1. HTTP 头特征
    for header_key, tech_name in _HEADER_TECHS.items():
        if header_key in result["headers"]:
            techs.append(tech_name)

    # 2. 检查 Set-Cookie 中的知名 cookie
    set_cookie = result["headers"].get("set-cookie", "")
    if "laravel_session" in set_cookie.lower():
        techs.append("Laravel")
    if "PHPSESSID" in set_cookie:
        techs.append("PHP")

    # 3. HTML 特征（大小写不敏感）
    html_lower = html[:200000].lower()
    for pattern, tech_name in _HTML_TECHS:
        if re.search(pattern, html_lower, flags=re.IGNORECASE):
            techs.append(tech_name)

    # 4. 从 HTML meta generator 提取
    m = re.search(r'<meta[^>]+name="generator"[^>]+content="([^"]+)"', html_lower)
    if m:
        techs.append(f"Generator: {m.group(1)}")

    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for t in techs:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    result["techs"] = unique
    return result


class WhatWebAdapter(SourceAdapter):
    """技术栈采集适配器（Python 原生，无需外部二进制）。"""

    source_family = "whatweb"
    max_documents = 1
    timeout_seconds = 20

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        ctx = self._build_identity_context(company_identity)
        website_host = ctx.get("website_host") or ctx.get("official_domain") or ""
        display_name = ctx.get("display_name") or website_host

        url: str = website_host.strip()
        if not url:
            return []
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        timeout = int(budget.get("timeout_seconds", self.timeout_seconds) or self.timeout_seconds)

        result = _detect_technologies(url, timeout)
        techs = result.get("techs", [])
        if not techs:
            logger.info("WhatWebAdapter: no technologies detected for %s", url)
            return []

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        domain = urlparse(url).netloc or website_host
        content = "\n".join([
            f"Technology profile for {display_name or domain}:",
            *[f"- {t}" for t in techs],
        ])

        return [SourceDocument(
            source_family=self.source_family,
            source_url=url,
            title=f"Technology Profile: {display_name or domain}",
            content=content,
            raw_text="\n".join(techs),
            intent="tech_stack",
            trust_tier="medium",
            source_score=0.72,
            entity_score=0.9,
            fetched_at=fetched_at,
            metadata={
                "publisher": "WhatWeb (Python native)",
                "website_host": website_host,
                "detected_count": len(techs),
                "technologies": techs,
                "http_status": result["status"],
            },
        )]

    def estimate_cost(self, field_targets: list[str], budget: dict) -> dict:
        return {
            "estimated_tokens": 1200,
            "estimated_queries": 1,
            "source_family": self.source_family,
        }


ADAPTER_REGISTRY["whatweb"] = WhatWebAdapter
