"""来源适配器集合 — 每种 source_family 一个 SourceAdapter 子类。

适配器按需导入，通过 ADAPTER_REGISTRY 按 source_family 激活。
"""
from __future__ import annotations

from research.adapters.official_site_adapter import OfficialSiteAdapter
from research.adapters.tavily_search_adapter import TavilySearchAdapter

__all__ = [
    "OfficialSiteAdapter",
    "TavilySearchAdapter",
]
