"""文档切块器 — 把清洗后的文档切成可召回的小块

切块规则：
- chunk_size: 700–1000 中文字符 / 500–800 英文词
- overlap: 100–150 字符
- 最小 chunk: 120 字符
- 最大 chunk: 1500 字符
- 单文档最多 80 个 chunk

chunk_type 枚举：
hero, about, pricing, customer, case_study, docs, blog, press,
market_report, tech_profile, github_readme, youtube_transcript, community_comment,
boilerplate, navigation, footer, cookie, legal, unknown

目标：
- 单 chunk token_estimate <= 500
- 低质量 chunk 占比可统计
- boilerplate/navigation/footer chunk 默认 is_noise=1
"""
from __future__ import annotations
import re
from typing import Optional
from .token_budget import estimate_tokens

# ── 配置 ──
CHUNK_TARGET_MIN = 700       # 目标最小长度（中文字符）
CHUNK_TARGET_MAX = 1000      # 目标最大长度（中文字符）
CHUNK_OVERLAP_MIN = 100      # 最小重叠
CHUNK_OVERLAP_MAX = 150      # 最大重叠
CHUNK_MIN_LENGTH = 120       # 最小 chunk 长度
CHUNK_MAX_LENGTH = 1500      # 最大 chunk 长度
MAX_CHUNKS_PER_DOC = 80      # 单文档最大 chunk 数

# ── chunk_type 推断规则 ──

_CHUNK_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("pricing", ["pricing", "plan", "subscription", "enterprise", "billing",
                 "pricing", "价格", "套餐"]),
    ("customer", ["customer", "client", "logo", "testimonial", "case study",
                  "客户", "案例", "合作"]),
    ("case_study", ["case study", "success story", "客户案例", "案例研究"]),
    ("hero", ["hero", "headline", "banner", "tagline", "slogan"]),
    ("about", ["about us", "about", "mission", "vision", "team", "culture",
               "关于我们", "使命", "愿景"]),
    ("docs", ["documentation", "api reference", "developer guide",
              "getting started", "docs", "文档", "API"]),
    ("blog", ["blog", "article", "post", "published", "博客", "文章"]),
    ("press", ["press release", "announces", "announced", "launches",
               "新闻稿", "宣布", "发布"]),
    ("market_report", ["market report", "industry report", "market size",
                       "market research", "市场报告", "行业报告"]),
    ("tech_profile", ["technology stack", "technology profile", "WhatWeb",
                      "HTTPServer", "JavaScript", "CDN",
                      "WAF", "framework", "analytics", "技术栈"]),
    ("github_readme", ["README", "installation", "install", "npm install",
                       "pip install", "git clone", "usage"]),
    ("youtube_transcript", ["transcript", "video", "youtube", "episode"]),
    ("footer", ["footer", "copyright", "all rights reserved", "privacy policy",
                 "terms of service", "cookie", "备案"]),
    ("navigation", ["navigation", "nav", "menu", "sidebar", "breadcrumb"]),
    ("boilerplate", ["subscribe", "newsletter", "follow us", "share this",
                     "related posts"]),
    ("legal", ["terms", "privacy", "cookie policy", "disclaimer", "GDPR"]),
    ("community_comment", ["comment", "reply", "upvote", "reddit", "hacker news"]),
]

_NOISE_CHUNK_TYPES = {"boilerplate", "navigation", "footer", "cookie",
                      "legal", "community_comment", "unknown"}


def _infer_chunk_type(text: str, source_type: str = "", title: str = "") -> str:
    """根据文本内容 + 来源类型推断 chunk_type。"""
    text_lower = text.lower()
    scores: dict[str, int] = {}

    for ctype, keywords in _CHUNK_TYPE_KEYWORDS:
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[ctype] = score

    # 来源类型优先
    if source_type in ("pricing_page",):
        scores["pricing"] = scores.get("pricing", 0) + 3
    if source_type in ("official_blog",):
        scores["blog"] = scores.get("blog", 0) + 2
    if source_type in ("github",):
        scores["github_readme"] = scores.get("github_readme", 0) + 2
    if source_type in ("youtube", "youtube_transcript"):
        scores["youtube_transcript"] = scores.get("youtube_transcript", 0) + 2
    if source_type in ("media_article",):
        scores["press"] = scores.get("press", 0) + 2
    if source_type in ("case_study",):
        scores["customer"] = scores.get("customer", 0) + 2
    if source_type in ("market_report", "database"):
        scores["market_report"] = scores.get("market_report", 0) + 2
    if source_type == "whatweb":
        scores["tech_profile"] = scores.get("tech_profile", 0) + 4

    if not scores:
        return "unknown"

    return max(scores, key=scores.get)


def _split_by_sentences(text: str, target_max: int = CHUNK_TARGET_MAX) -> list[str]:
    """按句子边界切分，尽量让每个 chunk 不超过 target_max。"""
    # 按段落分组
    paragraphs = text.split("\n")
    chunks = []
    current = ""
    current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            if current:
                current += "\n\n"
                current_len += 2
            continue

        para_len = len(para)

        # 段落太短，直接拼接
        if current_len + para_len <= target_max:
            current += para + "\n"
            current_len += para_len + 1
        else:
            # 当前 chunk 已有内容，保存
            if current.strip():
                chunks.append(current.strip())
            # 段落太长，按句子切
            if para_len > target_max:
                sentences = re.split(r'(?<=[。！？.!?\n])\s*', para)
                sub_chunk = ""
                sub_len = 0
                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    sl = len(sent)
                    if sub_len + sl <= target_max:
                        sub_chunk += sent
                        sub_len += sl
                    else:
                        if sub_chunk.strip():
                            chunks.append(sub_chunk.strip())
                        if sl > CHUNK_MAX_LENGTH:
                            # 强行截断
                            sub_chunk = sent[:CHUNK_MAX_LENGTH]
                            chunks.append(sub_chunk.strip())
                            sub_chunk = ""
                            sub_len = 0
                        else:
                            sub_chunk = sent
                            sub_len = sl
                if sub_chunk.strip():
                    current = sub_chunk + "\n"
                    current_len = sub_len
                else:
                    current = ""
                    current_len = 0
            else:
                current = para + "\n"
                current_len = para_len + 1

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _add_overlap(chunks: list[str], overlap: int = CHUNK_OVERLAP_MIN) -> list[str]:
    """给相邻 chunk 添加重叠文本。"""
    if len(chunks) <= 1 or overlap <= 0:
        return chunks

    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        curr = chunks[i]
        # 从前一个 chunk 尾部取 overlap 字符作为当前 chunk 的前缀
        if len(prev) > overlap:
            prefix = prev[-overlap:]
            # 找句子边界
            boundary_match = re.search(r'[。！？.!?\n]', prefix)
            if boundary_match:
                prefix = prefix[boundary_match.end():]
            if prefix:
                curr = prefix + " " + curr
        result.append(curr)

    return result


def chunk_document(
    document: dict,
    company_key: str,
) -> list[dict]:
    """将清洗后的文档切为 chunk 列表。

    Args:
        document: {
            "id": document_id,
            "source_type": str,
            "source_url": str,
            "title": str,
            "raw_text": str,  # 已清洗
        }
        company_key: 公司标识

    Returns:
        [
            {
                "document_id": int,
                "company_key": str,
                "source_type": str,
                "source_url": str,
                "title": str,
                "chunk_text": str,
                "chunk_type": str,
                "token_estimate": int,
            }
        ]
    """
    text = (document.get("raw_text") or "").strip()
    if not text:
        return []

    doc_id = document.get("id", 0)
    source_type = document.get("source_type", "")
    source_url = document.get("source_url", "")
    title = document.get("title", "")

    # 短文档不切
    if len(text) <= CHUNK_TARGET_MAX:
        token_est = estimate_tokens(text)
        if token_est > 500:
            # token 仍然多，尝试按 sentence 切
            parts = _split_by_sentences(text, CHUNK_TARGET_MAX)
        else:
            parts = [text]
    else:
        parts = _split_by_sentences(text, CHUNK_TARGET_MAX)

    # 过滤过短的 chunk
    filtered = [p for p in parts if len(p) >= CHUNK_MIN_LENGTH]

    # 添加重叠
    filtered = _add_overlap(filtered, CHUNK_OVERLAP_MIN)

    # 限制数量
    if len(filtered) > MAX_CHUNKS_PER_DOC:
        filtered = filtered[:MAX_CHUNKS_PER_DOC]

    # 构建结果
    chunks = []
    for chunk_text in filtered:
        # 截断过长 chunk
        if len(chunk_text) > CHUNK_MAX_LENGTH:
            chunk_text = chunk_text[:CHUNK_MAX_LENGTH]

        ctype = _infer_chunk_type(chunk_text, source_type, title)
        token_est = estimate_tokens(chunk_text)

        chunks.append({
            "document_id": doc_id,
            "company_key": company_key,
            "source_type": source_type,
            "source_url": source_url,
            "title": title,
            "chunk_text": chunk_text,
            "chunk_type": ctype,
            "token_estimate": token_est,
            # 噪音标记将在 evidence_ranker 中设置
            "is_noise": 1 if ctype in _NOISE_CHUNK_TYPES else 0,
        })

    return chunks
