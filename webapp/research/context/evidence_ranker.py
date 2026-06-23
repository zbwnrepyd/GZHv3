"""证据打分器 — 给 chunk 打分，不让噪音进入 LLM

打分公式:
    final_score =
        0.30 * source_score
      + 0.20 * entity_score
      + 0.25 * field_relevance_score
      + 0.10 * freshness_score
      + 0.15 * info_density_score
      - 0.30 * noise_score

阈值:
- final_score < 0.35 的 chunk 不进入 LLM
- noise_score >= 0.7 的 chunk 不进入 LLM
- 每个 field_key 只取 Top-K chunk
- 同一 URL 最多贡献 3 个 chunk
- 社区来源不能用于 confirmed 事实字段
"""
from __future__ import annotations
import re
from typing import Optional

# ── 来源权威度 ──
_SOURCE_AUTHORITY: dict[str, float] = {
    "official_site": 1.0,
    "official_blog": 0.9,
    "press_release": 0.85,
    "pricing_page": 0.85,
    "case_study": 0.8,
    "financial_database": 0.9,
    "database": 0.8,
    "market_report": 0.75,
    "trusted_media": 0.7,
    "media_article": 0.6,
    "docs": 0.7,
    "whatweb": 0.72,
    "github": 0.55,
    "youtube": 0.5,
    "youtube_transcript": 0.5,
    "search": 0.4,
    "community": 0.2,
    "social_media": 0.15,
    "unknown": 0.3,
}

# 低权威来源（不能用于 confirmed 事实字段）
_LOW_AUTHORITY_SOURCES = {"community", "social_media", "unknown"}

# ── 信息密度检测 ──
_INFO_DENSITY_PATTERNS = [
    # 数字 + 单位
    (r"\b\d+[\.,]?\d*\s*(%|million|billion|thousand|万|亿|M|B|K|k)\b", 0.1),
    # 金额
    (r"\b\$[\d,\.]+\s*(million|billion|M|B|K|k)?\b", 0.15),
    (r"\b\d+万\b", 0.1),
    (r"\b\d+亿\b", 0.1),
    # 百分比
    (r"\b\d+[\.,]?\d*\s*%\b", 0.1),
    # 日期
    (r"\b(20[12]\d|202[0-6])\b", 0.05),
    (r"\b(Q[1-4]\s*20[12]\d|FY\s*20[12]\d)\b", 0.08),
    # 公司/产品名（大写开头）
    (r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", 0.02),
    # 客户名模式
    (r"\b(客户|包括|合作|伙伴|包括但不限于)\b", 0.05),
    # 融资关键词
    (r"\b(Series\s+[A-E]|种子轮|天使轮|A轮|B轮|C轮|IPO|上市|收购|被收购)\b", 0.08),
    # 产品功能动词
    (r"\b(launch|release|announce|发布|上线|推出|开源|open\s*source)\b", 0.05),
]


def _compute_source_score(source_type: str, trust_tier: str = "") -> float:
    """计算来源权威度分数 (0–1)。"""
    if trust_tier in ("official",):
        return 0.95
    if trust_tier in ("trusted_media", "financial_database"):
        return 0.85
    if trust_tier in ("community",):
        return 0.25
    return _SOURCE_AUTHORITY.get(source_type, 0.3)


def _compute_entity_score(
    chunk_text: str,
    title: str,
    source_url: str,
    company_identity: dict,
) -> float:
    """计算实体匹配度分数 (0–1)。是否确实在讲目标公司。"""
    text = (chunk_text + " " + title + " " + source_url).lower()
    display_name = (company_identity.get("display_name") or "").lower()
    aliases = [a.lower() for a in (company_identity.get("aliases") or [])]
    website_host = (company_identity.get("website_host") or "").lower()

    if not display_name:
        return 0.3

    score = 0.0

    # 精确公司名匹配
    if display_name in text:
        score += 0.5
    elif display_name.replace(" ", "") in text:
        score += 0.3

    # 简称/别名
    for alias in aliases:
        if alias and len(alias) >= 3 and alias in text:
            score += 0.2
            break

    # 域名出现
    if website_host and website_host in text:
        score += 0.15

    # URL 中包含公司名
    if display_name.replace(" ", "").lower() in source_url.lower():
        score += 0.1

    return min(score, 1.0)


def _compute_field_relevance(
    chunk_text: str,
    title: str,
    field_key: str = "",
    keywords: list[str] | None = None,
) -> float:
    """计算字段相关性分数 (0–1)。"""
    text = (chunk_text + " " + title).lower()

    if not field_key and not keywords:
        return 0.1

    # 字段关键词（从 field_key 拆分）
    field_tokens = set()
    if field_key:
        for token in field_key.replace("_", " ").split():
            if len(token) >= 2:
                field_tokens.add(token.lower())

    # 额外关键词
    extra_keywords = [kw.lower() for kw in (keywords or []) if len(kw) >= 2]

    all_keywords = list(field_tokens) + extra_keywords
    if not all_keywords:
        return 0.1

    # 计算命中率
    hits = sum(1 for kw in all_keywords if kw in text)
    hit_rate = hits / max(len(all_keywords), 1)

    # 字段名直接出现（强信号）
    if field_key and field_key.lower() in text:
        hit_rate = max(hit_rate, 0.6)

    return min(hit_rate, 1.0)


def _compute_freshness_score(
    chunk_text: str,
    title: str = "",
    published_at: str = "",
) -> float:
    """计算时效性分数 (0–1)。近期信息得分更高。"""
    text = chunk_text + " " + title

    # 年份检测
    years = re.findall(r"\b(20[12]\d|202[0-6])\b", text)
    if years:
        latest = max(int(y) for y in years)
        current_year = 2026
        age = current_year - latest
        if age <= 0:
            return 1.0
        elif age <= 2:
            return 0.8
        elif age <= 4:
            return 0.5
        else:
            return 0.2

    # 有发布时间
    if published_at:
        try:
            year = int(published_at[:4])
            age = 2026 - year
            if age <= 1:
                return 0.9
            elif age <= 3:
                return 0.6
            else:
                return 0.3
        except (ValueError, IndexError):
            pass

    return 0.3


def _compute_info_density(chunk_text: str) -> float:
    """计算信息密度分数 (0–1)。检测数字、日期、实体等。"""
    if not chunk_text.strip():
        return 0.0

    score = 0.0
    for pattern, weight in _INFO_DENSITY_PATTERNS:
        matches = len(re.findall(pattern, chunk_text))
        if matches > 0:
            score += min(weight * matches, weight * 3)

    # 长度惩罚：太短信息量低
    text_len = len(chunk_text)
    if text_len < 100:
        score *= 0.5
    elif text_len < 200:
        score *= 0.7

    return min(score, 1.0)


def _compute_noise_score(
    chunk_type: str,
    clean_noise_flags: list[str] | None = None,
) -> float:
    """计算噪音分数 (0–1)。值越高噪音越大。"""
    score = 0.0

    # chunk_type 基础噪音
    noise_base = {
        "boilerplate": 0.9,
        "navigation": 0.95,
        "footer": 0.9,
        "cookie": 1.0,
        "legal": 0.95,
        "community_comment": 0.7,
        "youtube_transcript": 0.25,
        "unknown": 0.3,
    }
    score = max(score, noise_base.get(chunk_type, 0.0))

    # 噪音标记加成
    if clean_noise_flags:
        flag_weights = {
            "cookie_banner": 0.3,
            "cookie_page": 0.3,
            "privacy_page": 0.3,
            "terms_page": 0.3,
            "legal_page": 0.3,
            "auth_page": 0.3,
            "footer_copyright": 0.2,
            "navigation": 0.2,
            "newsletter_cta": 0.15,
            "cta_button": 0.1,
            "social_media_cta": 0.1,
            "author_bio": 0.1,
            "related_links": 0.1,
            "advertisement": 0.25,
            "youtube_greeting": 0.15,
            "youtube_outro": 0.1,
            "sponsor_mention": 0.2,
        }
        for flag in clean_noise_flags:
            score = max(score, flag_weights.get(flag, 0.0))

    return min(score, 1.0)


def score_chunk(
    chunk: dict,
    company_identity: dict,
    field_key: str = "",
    keywords: list[str] | None = None,
) -> dict:
    """给单个 chunk 打分。

    Args:
        chunk: 从 document_chunker 输出的 chunk dict
        company_identity: {"display_name", "aliases", "website_host"}
        field_key: 可选，目标字段
        keywords: 可选，字段关键词

    Returns:
        chunk 加上评分字段的 dict
    """
    chunk_text = chunk.get("chunk_text", "")
    title = chunk.get("title", "")
    source_url = chunk.get("source_url", "")
    source_type = chunk.get("source_type", "")
    chunk_type = chunk.get("chunk_type", "unknown")

    source_score = _compute_source_score(source_type, chunk.get("trust_tier", ""))
    entity_score = _compute_entity_score(chunk_text, title, source_url, company_identity)
    field_relevance = _compute_field_relevance(chunk_text, title, field_key, keywords)
    freshness = _compute_freshness_score(chunk_text, title)
    info_density = _compute_info_density(chunk_text)
    noise = _compute_noise_score(chunk_type)

    final_score = (
        0.30 * source_score
        + 0.20 * entity_score
        + 0.25 * field_relevance
        + 0.10 * freshness
        + 0.15 * info_density
        - 0.30 * noise
    )
    # 确保在 [0, 1] 区间
    final_score = max(0.0, min(final_score, 1.0))

    # 判断是否噪音
    is_noise = (
        chunk.get("is_noise") == 1
        or noise >= 0.7
        or final_score < 0.35
    )

    result = dict(chunk)
    result.update({
        "source_score": round(source_score, 3),
        "entity_score": round(entity_score, 3),
        "field_relevance_score": round(field_relevance, 3),
        "freshness_score": round(freshness, 3),
        "info_density_score": round(info_density, 3),
        "noise_score": round(noise, 3),
        "final_score": round(final_score, 3),
        "is_noise": 1 if is_noise else 0,
    })
    return result


def score_chunks_batch(
    chunks: list[dict],
    company_identity: dict,
    field_key: str = "",
    keywords: list[str] | None = None,
) -> list[dict]:
    """批量打分，并过滤低质 chunk。

    Returns:
        [{chunk + scores}, ...]
    """
    scored = [
        score_chunk(c, company_identity, field_key, keywords)
        for c in chunks
    ]
    return scored


def is_field_confirmable_source(source_type: str) -> bool:
    """判断来源是否可用于 confirmed 事实字段。"""
    return source_type not in _LOW_AUTHORITY_SOURCES
