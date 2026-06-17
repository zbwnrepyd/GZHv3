"""Token 预算控制器 — 管理各层级 LLM 调用的输入 token 上限。

预算预设：
- L0: 标准 18000 / 深度 28000
- L1: 标准 8000
- L2: 标准 10000
- L3: 标准 12000
- 单事实字段: 800–1200
- 融资/创始人/客户字段: 1600
- 市场规模/TAM: 2200
- 竞品/生态位/GTM: 3000
"""
from __future__ import annotations
import re
from typing import Optional

# ── Token 估算常量 ──
# 中英文混合保守估计：~2.5 字符/token
CHARS_PER_TOKEN = 2.5

# ── 预算预设 ──
BUDGET_PRESETS = {
    # 层级预算
    "l0_standard": 18000,
    "l0_deep": 28000,
    "l1_standard": 8000,
    "l2_standard": 10000,
    "l3_standard": 12000,
    # ── SPEC v3 L0 子预算 ──
    "l0_sub_company_identity": 600,
    "l0_sub_source_audit": 1000,
    "l0_sub_market_context": 2200,
    "l0_sub_product_context": 2200,
    "l0_sub_founder_context": 1600,
    "l0_sub_customer_context": 1800,
    "l0_sub_gtm_context": 2200,
    "l0_sub_competition_context": 3000,
    "l0_sub_misc_buffer": 3400,
    # 字段级预算
    "field_default": 1200,
    "field_fact": 800,
    "field_funding": 1600,
    "field_founder": 1600,
    "field_customer": 1600,
    "field_market": 2200,
    "field_competitive": 3000,
    "field_ecosystem": 3000,
    "field_gtm": 3000,
    "field_analysis": 2500,
    # 卡片级预算
    "card_default": 4000,
    # 限制
    "max_chunks_per_field": 5,
    "max_chunks_per_url": 3,
    "max_chunks_per_source_family": 12,
    "max_evidence_per_field": 3,
}

# ── 字段到预算的映射 ──
_FIELD_BUDGET_MAP: dict[str, str] = {
    # 高预算字段
    "funding_info": "field_funding",
    "funding_rounds": "field_funding",
    "founder_name": "field_founder",
    "founder_bg": "field_founder",
    "founder_edu": "field_founder",
    "founder_achievement": "field_founder",
    "ideal_customer_profile": "field_customer",
    "customer_names": "field_customer",
    "customer_selection_reasons": "field_customer",
    "tam": "field_market",
    "market_size_value": "field_market",
    "market_cagr": "field_market",
    "market_landscape_summary": "field_market",
    "product_pain_points": "field_market",
    "product_core_features": "field_fact",
    "competitors_top3": "field_competitive",
    "competitive_position": "field_competitive",
    "competitive_advantages": "field_competitive",
    "differentiated_opportunity": "field_competitive",
    "ecosystem_niche": "field_ecosystem",
    "growth_strategy": "field_gtm",
    "gtm_strategy": "field_gtm",
    "growth_flywheel": "field_gtm",
    "acquisition_channels": "field_gtm",
    "competitive_landscape": "field_analysis",
    "company_analysis": "field_analysis",
}


def estimate_tokens(text: str) -> int:
    """保守估算文本 token 数（中英文混合，~2.5 字符/token）。"""
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def get_field_budget(field_key: str, manifest_entry: dict | None = None) -> int:
    """获取字段上下文预算。

    优先级: field_manifest > _FIELD_BUDGET_MAP > 默认
    """
    # field_manifest 中的显式配置
    if manifest_entry and manifest_entry.get("context_budget_tokens"):
        return int(manifest_entry["context_budget_tokens"])

    # 映射表
    budget_key = _FIELD_BUDGET_MAP.get(field_key)
    if budget_key:
        return BUDGET_PRESETS[budget_key]

    # 默认
    return BUDGET_PRESETS["field_default"]


def get_field_max_chunks(field_key: str, manifest_entry: dict | None = None) -> int:
    """获取字段最大 chunk 数。"""
    if manifest_entry and manifest_entry.get("max_evidence_chunks"):
        return int(manifest_entry["max_evidence_chunks"])
    return BUDGET_PRESETS["max_chunks_per_field"]


class TokenBudget:
    """Token 预算追踪器 — 追踪单次 LLM 调用的输入 token 使用量。"""

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        self.used_tokens = 0
        self.chunks_included = 0
        self.chunks_dropped = 0
        self._url_chunk_counts: dict[str, int] = {}
        self._source_family_chunk_counts: dict[str, int] = {}
        # P2: 子预算追踪（按 SPEC Section 11.1）
        self.sub_budgets: dict[str, dict] = {}  # {category: {used, limit}}

    def set_sub_budget(self, category: str, limit: int):
        """为上下文类别设置子预算上限。"""
        self.sub_budgets[category] = {"used": 0, "limit": limit}

    def check_sub_budget(self, category: str, tokens: int) -> bool:
        """检查子预算范围内是否可添加。"""
        if category not in self.sub_budgets:
            return True
        sb = self.sub_budgets[category]
        return sb["used"] + tokens <= sb["limit"]

    def use_sub_budget(self, category: str, tokens: int):
        """从子预算中消耗 token。"""
        if category in self.sub_budgets:
            self.sub_budgets[category]["used"] += tokens

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def is_full(self) -> bool:
        return self.used_tokens >= self.max_tokens

    def can_add(self, chunk_tokens: int) -> bool:
        return self.used_tokens + chunk_tokens <= self.max_tokens

    def add_chunk(self, chunk: dict) -> bool:
        """尝试添加一个 chunk。返回是否成功。"""
        tokens = chunk.get("token_estimate", 0)
        url = chunk.get("source_url", "")
        source_family = chunk.get("source_family", "")
        return self.add(tokens, url, source_family)

    def add(self, chunk_tokens: int, source_url: str = "", source_family: str = "") -> bool:
        """尝试添加一个 chunk 的 token 数。返回是否成功。"""
        if not self.can_add(chunk_tokens):
            self.chunks_dropped += 1
            return False

        # P2: URL 去重检查（每 URL 最多 MAX_CHUNKS_PER_URL 个 chunk）
        if source_url:
            url_count = self._url_chunk_counts.get(source_url, 0)
            if url_count >= BUDGET_PRESETS["max_chunks_per_url"]:
                self.chunks_dropped += 1
                return False
            self._url_chunk_counts[source_url] = url_count + 1

        # P2: Source family 去重检查（每 source_family 最多 MAX_CHUNKS_PER_SOURCE_FAMILY 个 chunk）
        if source_family:
            sf_count = self._source_family_chunk_counts.get(source_family, 0)
            max_per_sf = BUDGET_PRESETS.get("max_chunks_per_source_family", 12)
            if sf_count >= max_per_sf:
                self.chunks_dropped += 1
                return False
            self._source_family_chunk_counts[source_family] = sf_count + 1

        self.used_tokens += chunk_tokens
        self.chunks_included += 1
        return True

    def summary(self) -> dict:
        return {
            "budget": self.max_tokens,
            "used": self.used_tokens,
            "remaining": self.remaining,
            "chunks_included": self.chunks_included,
            "chunks_dropped": self.chunks_dropped,
            "sub_budgets": {
                cat: {"used": sb["used"], "limit": sb["limit"]}
                for cat, sb in self.sub_budgets.items()
            },
            "source_family_chunks": dict(self._source_family_chunk_counts),
        }
