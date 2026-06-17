"""YouTube Transcript SourceAdapter — YouTube Data API search + transcript fetch.

通过 YouTube Data API v3 搜索视频，用 youtube-transcript-api 抓取字幕/转录文本。
最多返回 3 个视频的 SourceDocument（source_family=youtube_transcript）。

复用 pipeline.py 中已验证的 _search_youtube / _fetch_youtube_transcripts 逻辑。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Optional

# 将 webapp 目录加入 sys.path 以确保在 webapp/ 内外均可导入 pipeline
import os as _os
_webapp_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _webapp_dir not in sys.path:
    sys.path.insert(0, _webapp_dir)

logger = logging.getLogger(__name__)


# ── 延迟导入 pipeline 私有函数 ────────────────────────────────────────────────
# 延迟导入避免在模块加载时触发 pipeline 的顶层副作用（config 读取、DB 初始化等）。

_search_youtube = None
_fetch_youtube_transcripts = None
_vid_of = None


def _lazy_import_pipeline():
    """延迟导入 pipeline.py 中的 YouTube 采集函数。"""
    global _search_youtube, _fetch_youtube_transcripts, _vid_of
    if _search_youtube is not None:
        return
    try:
        from pipeline import (
            _search_youtube as _sy,
            _fetch_youtube_transcripts as _fyt,
            _vid_of as _vo,
        )
        _search_youtube = _sy
        _fetch_youtube_transcripts = _fyt
        _vid_of = _vo
    except ImportError as e:
        logger.warning("无法导入 pipeline YouTube 函数: %s，将使用内置实现", e)


# ── 内置回退实现（当 pipeline 不可用时）────────────────────────────────────────


def _builtin_search_youtube(queries: list[str], api_key: str, timeout: tuple = (15, 45)) -> dict:
    """内置 YouTube Data API v3 搜索 + 转录获取。"""
    import requests

    if not api_key:
        return {"items": [], "note": "no API key", "errors": []}

    merged = []
    errors = []
    seen = set()

    for q in [x for x in (queries or []) if x.strip()]:
        if q in seen:
            continue
        seen.add(q)
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": q,
                    "type": "video",
                    "maxResults": 5,
                    "key": api_key,
                },
                timeout=timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    item["_query"] = q
                    merged.append(item)
            else:
                errors.append({"query": q, "error": resp.status_code})
        except Exception as e:
            errors.append({"query": q, "error": str(e)})

    # 按 videoId 去重
    deduped = []
    seen_ids = set()
    for item in merged:
        vid = _builtin_vid_of(item).strip()
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            deduped.append(item)

    # 抓取字幕
    transcripts = _builtin_fetch_transcripts([_builtin_vid_of(i) for i in deduped if _builtin_vid_of(i)])
    for item in deduped:
        t = transcripts.get(_builtin_vid_of(item), "")
        if t:
            item["_transcript"] = t

    return {"items": deduped, "errors": errors}


def _builtin_vid_of(item: dict) -> str:
    vid = item.get("id", {})
    return (vid.get("videoId") or str(vid) or "") if isinstance(vid, dict) else str(vid or "")


def _builtin_fetch_transcripts(video_ids: list[str]) -> dict[str, str]:
    """批量抓取 YouTube 视频字幕，返回 {video_id: transcript_text}。"""
    if not video_ids:
        return {}
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        _yt_api = YouTubeTranscriptApi()
    except (ImportError, Exception):
        logger.warning("youtube_transcript_api 不可用，跳过字幕抓取")
        return {}

    results = {}
    for vid in video_ids:
        if not vid or vid in results:
            continue
        try:
            fetched = _yt_api.fetch(vid, languages=['zh-Hans', 'zh', 'en', 'ja', 'ko'])
            snippets = getattr(fetched, 'snippets', []) or []
            lines = []
            total = 0
            for seg in snippets:
                text = getattr(seg, 'text', '').strip()
                if not text or (text.startswith("[") and text.endswith("]")):
                    continue
                lines.append(text)
                total += len(text)
                if total > 3000:
                    lines.append("...")
                    break
            if lines:
                results[vid] = " ".join(lines)
        except Exception:
            pass
    return results


# ── 适配器实现 ────────────────────────────────────────────────────────────────


from ..source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY


class YoutubeTranscriptAdapter(SourceAdapter):
    """YouTube 转录适配器。

    采集策略:
    1. 根据公司 display_name + field_targets 构造搜索查询
    2. 调用 YouTube Data API v3 搜索视频（最多 5 个/查询）
    3. 通过 youtube-transcript-api 获取视频字幕
    4. 映射为 SourceDocument 返回（最多 max_documents 个）

    限额:
    - 默认 max_documents=3（最多 3 个视频）
    - YouTube Data API 每次搜索消耗 100 配额单位
    """

    source_family = "youtube_transcript"

    # ── 查询模板 ──
    _QUERY_TEMPLATES = [
        "{name} interview",
        "{name} founder story",
        "{name} product demo",
        "{name} business model explained",
        "{name} funding announcement",
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # YouTube 采集默认最多 3 个视频
        self.max_documents = kwargs.get("max_documents", 3)
        self.timeout_seconds = kwargs.get("timeout_seconds", 30)

    # ── 核心接口 ──

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行 YouTube 采集。

        Args:
            company_identity: 公司身份信息。
            field_targets: 目标字段键列表（用于调整查询策略）。
            budget: 预算约束 {"max_documents": N, "max_queries": N, "timeout_seconds": N}。

        Returns:
            SourceDocument 列表。
        """
        ctx = self._build_identity_context(company_identity)
        display_name = ctx["display_name"]

        if not display_name:
            logger.warning("YoutubeTranscriptAdapter: 缺少 display_name，跳过采集")
            return []

        # ── 预算控制 ──
        max_docs = budget.get("max_documents", self.max_documents)
        max_queries = budget.get("max_queries", 3)
        timeout = budget.get("timeout_seconds", self.timeout_seconds)

        # ── 构造搜索查询 ──
        queries = self._build_queries(display_name, field_targets, max_queries)
        logger.info("YouTube 搜索 %d 条查询: %s", len(queries), queries)

        # ── 调用 YouTube API ──
        _lazy_import_pipeline()
        if _search_youtube is not None:
            try:
                result = _search_youtube(queries)
            except Exception as e:
                logger.warning("pipeline._search_youtube 调用失败: %s，回退到内置实现", e)
                api_key = self._get_api_key()
                result = _builtin_search_youtube(queries, api_key, timeout=(timeout, timeout * 2))
        else:
            api_key = self._get_api_key()
            result = _builtin_search_youtube(queries, api_key, timeout=(timeout, timeout * 2))

        items = result.get("items", [])
        errors = result.get("errors", [])
        note = result.get("note", "")

        if note:
            logger.info("YouTube 采集提示: %s", note)
        if errors:
            logger.warning("YouTube 采集部分失败: %s", errors[:3])

        if not items:
            logger.info("YouTube: 未找到相关视频 (query_count=%d)", len(queries))
            return []

        # ── 映射为 SourceDocument ──
        docs = []
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for item in items[:max_docs]:
            doc = self._item_to_document(item, display_name, ctx, fetched_at)
            if doc:
                docs.append(doc)

        logger.info("YouTube: 采集完成，返回 %d 个 SourceDocument", len(docs))
        return docs

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算 YouTube 采集成本。

        YouTube Data API:
        - search: 100 units/query
        - transcript: 免费（youtube-transcript-api 不消耗配额）
        - 默认配额 10,000 units/day

        Returns:
            {"estimated_tokens": int, "estimated_queries": int, "source_family": str}
        """
        max_queries = budget.get("max_queries", 3)
        max_docs = budget.get("max_documents", self.max_documents)

        # 每个视频转录约 3000 字符 ≈ 750 tokens
        estimated_tokens = max_docs * 750
        estimated_queries = max_queries

        return {
            "estimated_tokens": estimated_tokens,
            "estimated_queries": estimated_queries,
            "source_family": self.source_family,
        }

    # ── 内部方法 ──

    def _build_queries(
        self, display_name: str, field_targets: list[str], max_queries: int
    ) -> list[str]:
        """根据公司名和字段目标构造搜索查询。

        策略:
        - 基础查询: "{name} interview"（始终包含）
        - 按 field_targets 追加相关查询
        - 最多 max_queries 条
        """
        queries = []

        # 基础查询（总是包含）
        queries.append(f"{display_name} interview")

        # 按字段目标追加查询
        field_query_map = {
            "company_description": f"{display_name} company story",
            "products": f"{display_name} product demo",
            "founder_name": f"{display_name} founder interview",
            "funding_total": f"{display_name} funding",
            "business_model": f"{display_name} business model explained",
            "competitors": f"{display_name} vs competitors",
            "moat": f"{display_name} competitive advantage",
            "traction": f"{display_name} growth metrics",
        }

        for field in field_targets:
            if len(queries) >= max_queries:
                break
            q = field_query_map.get(field)
            if q and q not in queries:
                queries.append(q)

        # 如果还没填满，从模板中补充
        for tmpl in self._QUERY_TEMPLATES:
            if len(queries) >= max_queries:
                break
            q = tmpl.format(name=display_name)
            if q not in queries:
                queries.append(q)

        return queries[:max_queries]

    def _item_to_document(
        self,
        item: dict,
        display_name: str,
        ctx: dict,
        fetched_at: str,
    ) -> Optional[SourceDocument]:
        """将 YouTube API 搜索结果项转换为 SourceDocument。"""
        snippet = item.get("snippet", {})
        vid = (_builtin_vid_of(item) or "").strip()
        if not vid:
            return None

        url = f"https://www.youtube.com/watch?v={vid}"
        title = snippet.get("title", "")
        desc = snippet.get("description", "") or ""
        transcript = item.get("_transcript", "") or ""
        published_at = snippet.get("publishedAt", "")

        # 内容优先级: 转录文本 > 描述
        if transcript and desc:
            content = f"[Transcript]\n{transcript}\n\n[Description]\n{desc[:500]}"
        elif transcript:
            content = transcript
        else:
            content = desc[:3000]

        # 可信度: YouTube 属于中等可信度（第三方内容）
        trust_tier = "medium"

        # 来源评分: 基于域名
        source_score = 0.55  # YouTube 默认中等评分
        entity_score = 0.0   # 由 evidence_ranker 后续计算

        return SourceDocument(
            source_family=self.source_family,
            source_url=url,
            title=title,
            content=content,
            raw_text=f"{title}\n{desc[:2000]}\n{transcript}",
            intent="interview",
            trust_tier=trust_tier,
            source_score=source_score,
            entity_score=entity_score,
            published_at=published_at,
            fetched_at=fetched_at,
            metadata={
                "publisher": snippet.get("channelTitle", ""),
                "video_id": vid,
                "has_transcript": bool(transcript),
                "query": item.get("_query", ""),
            },
        )

    @staticmethod
    def _get_api_key() -> str:
        """获取 YouTube API Key。"""
        try:
            from config import config
            return getattr(config, "YOUTUBE_API_KEY", "") or ""
        except ImportError:
            pass

        # fallback: 直接读环境变量
        import os
        return os.environ.get("YOUTUBE_API_KEY", "")


# ── 注册到全局注册表 ─────────────────────────────────────────────────────────

ADAPTER_REGISTRY["youtube_transcript"] = YoutubeTranscriptAdapter
