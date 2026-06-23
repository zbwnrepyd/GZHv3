"""来源适配器基类 — 为每种 source_family 提供统一采集接口。

SPEC Section 8: 每个来源族（official_site/tavily_search/github 等）封装为 SourceAdapter 子类，
通过标准 collect() 接口返回 SourceDocument 列表，供证据层链路消费。

设计原则:
- 单适配器负责单一来源族，采集逻辑内聚
- 统一 budget 控制: {max_documents, max_tokens, max_depth_seconds}
- 统一输出: list[SourceDocument]，经 document_store 入库后流入 clean→chunk→rank→pack 链路
- ADAPTER_REGISTRY 按 source_family 注册，供 orchestrator/pipeline 按需激活
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ── SourceDocument dataclass ────────────────────────────────────────────────

@dataclass
class SourceDocument:
    """来源文档统一数据结构。

    一条 SourceDocument 代表一次采集产出的单篇文档（网页/PDF/API 响应等）。
    各适配器填充公共字段后统一入库 source_documents 表。
    """
    source_family: str
    """来源族标识: official_site | tavily_search | tavily_extract | github |
    producthunt | youtube | sec | openbb | companieshouse | whatweb"""

    source_url: str
    """文档来源 URL（官网页面、搜索命中链接、GitHub Issue URL 等）"""

    title: str
    """文档标题（网页 <title>、搜索结果标题、PDF 文件名等）"""

    content: str
    """清洗后的正文文本，最大 50000 字符。
    经 document_cleaner 预处理（去广告/导航/页脚/脚本）。"""

    raw_text: str = ""
    """清洗前的原始文本（未截断，用于后续审计和重处理）。
    与 content 分离以满足"raw_text 不进 LLM"的硬约束。"""

    intent: str = ""
    """采集意图标签。用于区分同一 source_family 下不同采集目的。
    例如: 'company_overview' | 'product_detail' | 'financial_data'"""

    trust_tier: str = "medium"
    """可信度层级: high | medium | low。
    - high: 官网一手资料、SEC 官方备案、GitHub 官方仓库 README 等
    - medium: 媒体报道、第三方数据库、技术博客等
    - low: 论坛讨论、匿名来源、低信誉域名等"""

    source_score: float = 0.5
    """来源质量分 (0.0–1.0)。基于域名权威性、内容原创性等评估。"""

    entity_score: float = 0.5
    """实体匹配分 (0.0–1.0)。文档内容与目标公司/产品的相关性评分。"""

    final_score: float = 0.0
    """综合得分 (0.0–1.0)。source_score 与 entity_score 的加权组合，
    由 evidence_ranker 在评分阶段计算。"""

    published_at: str = ""
    """发布日期。ISO 8601 格式 (YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SSZ)，
    未知时为空字符串。"""

    fetched_at: str = ""
    """采集时间。ISO 8601 格式 (YYYY-MM-DDTHH:MM:SSZ)。
    由适配器在采集完成时设置。"""

    metadata: dict = field(default_factory=dict)
    """扩展元数据。适配器可附加任意键值对（如 SEO 关键词、robots 状态、语言等）。
    不入 LLM 上下文，仅用于调试和审计。"""

    def __post_init__(self):
        # 截断 content 至 50000 字符上限
        if len(self.content) > 50000:
            self.content = self.content[:49997] + "..."

    @property
    def is_high_trust(self) -> bool:
        """是否为高可信度来源。"""
        return self.trust_tier == "high"

    @property
    def has_score(self) -> bool:
        """是否已完成评分（final_score > 0 表示已进入 rank 阶段）。"""
        return self.final_score > 0.0

    def to_db_row(self, run_id: str = "", company_key: str = "") -> dict:
        """转换为 source_documents 表行字典。"""
        return {
            "run_id": run_id,
            "company_key": company_key,
            "source_type": self.source_family,
            "source_url": self.source_url,
            "title": self.title,
            "publisher": self.metadata.get("publisher", ""),
            "published_at": self.published_at,
            "raw_text": self.raw_text,
            "trust_tier": self.trust_tier,
            "intent": self.intent,
        }


# ── SourceAdapter ABC ──────────────────────────────────────────────────────

class SourceAdapter(ABC):
    """来源适配器抽象基类。

    每个 source_family 对应一个子类实现。适配器负责:
    1. 根据 company_identity 和 field_targets 确定采集策略
    2. 调用外部 API / 抓取逻辑收集原始文档
    3. 返回统一的 SourceDocument 列表

    使用方式:
        adapter = TavilySearchAdapter(timeout_seconds=25, max_documents=14)
        docs = adapter.collect(
            company_identity={"display_name": "Anthropic", "website_host": "anthropic.com"},
            field_targets=["company_description", "products", "funding"],
            budget={"max_documents": 14, "max_tokens": 80000, "max_depth_seconds": 120},
        )
    """

    # ── 子类必须设置 ──
    source_family: str = ""
    """来源族标识字符串。子类 __init__ 中或类级别设置。"""

    # ── 可覆盖配置 ──
    timeout_seconds: int = 30
    """单次请求超时（秒）。"""

    max_documents: int = 20
    """单次 collect() 最大返回文档数。"""

    def __init__(self, **kwargs):
        self.timeout_seconds = kwargs.get("timeout_seconds", self.timeout_seconds)
        self.max_documents = kwargs.get("max_documents", self.max_documents)

    # ── 核心接口 ──

    @abstractmethod
    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行采集，返回 SourceDocument 列表。

        Args:
            company_identity: 公司身份信息，至少包含 display_name / website_host。
            field_targets: 目标字段键列表，适配器据此调整搜索策略。
            budget: 预算约束 dict，可包含:
                - max_documents: 最大返回文档数
                - max_tokens: 最大 token 预算
                - max_depth_seconds: 最大时间预算（秒）
                - priority: 优先级标记 (high|normal|low)

        Returns:
            SourceDocument 列表，不超过 max_documents。
            采集失败时返回空列表（不抛异常）。
        """
        ...

    @abstractmethod
    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算本次采集成本。

        Args:
            field_targets: 目标字段键列表。
            budget: 预算约束 dict。

        Returns:
            {
                "estimated_tokens": int,   # 预估消耗 token 数
                "estimated_queries": int,  # 预估 API 调用次数
                "source_family": str,      # 来源族标识
            }
        """
        ...

    # ── 辅助方法 ──

    def _build_identity_context(self, company_identity: dict) -> dict:
        """从 company_identity 提取标准化上下文。

        提取 display_name、website_host、root_domain、aliases，
        供子类在采集逻辑中使用。

        Args:
            company_identity: 原始公司身份 dict。

        Returns:
            {
                "display_name": str,
                "website_host": str,
                "root_domain": str,
                "aliases": list[str],
            }
        """
        display_name = company_identity.get("display_name", "")
        website_url = company_identity.get("website_url", "")
        website_host = company_identity.get("website_host", "")

        # 从 website_url 推断 website_host
        if not website_host and website_url:
            website_host = self._extract_host(website_url)

        # 推断 root_domain（去掉 www 等前缀）
        root_domain = website_host
        if root_domain.startswith("www."):
            root_domain = root_domain[4:]

        aliases = company_identity.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]

        return {
            "display_name": display_name or "",
            "website_host": website_host,
            "root_domain": root_domain,
            "aliases": aliases,
        }

    @staticmethod
    def _extract_host(url: str) -> str:
        """从 URL 中提取 host（不含协议和路径）。"""
        if not url:
            return ""
        # 去掉协议
        s = url
        for prefix in ("https://", "http://"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        # 去掉路径、查询、片段
        for sep in ("/", "?", "#"):
            idx = s.find(sep)
            if idx >= 0:
                s = s[:idx]
        return s.strip().lower()

    def _truncate_list(self, docs: list[SourceDocument]) -> list[SourceDocument]:
        """按 max_documents 截断文档列表。"""
        if len(docs) > self.max_documents:
            return docs[: self.max_documents]
        return docs


# ── ADAPTER_REGISTRY ───────────────────────────────────────────────────────

ADAPTER_REGISTRY: dict[str, type[SourceAdapter]] = {}
"""全模块共享的来源适配器注册表。

映射 source_family (str) -> SourceAdapter 子类。
采集流程通过此注册表按需获取适配器实例。

注册方式:
    from research.source_adapter import SourceAdapter, ADAPTER_REGISTRY

    class TavilySearchAdapter(SourceAdapter):
        source_family = "tavily_search"
        ...

    ADAPTER_REGISTRY["tavily_search"] = TavilySearchAdapter

使用方式:
    adapter_cls = ADAPTER_REGISTRY.get("tavily_search")
    if adapter_cls:
        adapter = adapter_cls(timeout_seconds=25, max_documents=14)
        docs = adapter.collect(...)
"""
