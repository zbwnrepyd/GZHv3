"""OpenBB 来源适配器 — 金融数据采集（benchmark / metric 数据）。

通过 OpenBB Python API 直接获取公司财务指标、行业基准和市场数据，
返回 source_family=openbb 的 SourceDocument 列表。

Max 5 docs，trust_tier=high（金融一手数据）。
本地嵌入模式（类比 Scrapling），不需要独立 OpenBB REST 服务。
"""

from __future__ import annotations

import logging
import os
import sys as _sys
import threading
from datetime import datetime, timezone
from typing import Optional

try:
    from openbb import obb
    from openbb_core.app.model.abstract.error import OpenBBError
    _OPENBB_AVAILABLE = True
    _OPENBB_IMPORT_ERROR = ""
except ImportError as _e:
    obb = None  # type: ignore
    OpenBBError = Exception  # type: ignore
    _OPENBB_AVAILABLE = False
    _OPENBB_IMPORT_ERROR = str(_e)

from ..source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY

logger = logging.getLogger(__name__)

# OpenBB 数据提供商（可通过环境变量覆盖）。
# yfinance 为免费默认；fmp/intrinio 等需对应 API Key
_OBB_PROVIDER = os.environ.get("OPENBB_PROVIDER", "yfinance")

# yfinance 底层非线程安全，Pipeline 用 ThreadPoolExecutor 并发跑适配器
_obb_lock = threading.Lock()

# ── endpoint → obb 方法调度表 ─────────────────────────────────────────────

_OBB_METHOD_MAP: dict[str, str] = {
    "/equity/profile":              "profile",
    "/equity/fundamental/metrics":  "fundamental_metrics",
    "/equity/fundamental/income":   "fundamental_income",
    "/equity/fundamental/balance":  "fundamental_balance",
}


def _call_obb_method(endpoint: str, ticker: str) -> Optional[dict]:
    """通过 OpenBB Python API 直接获取金融数据，返回 model_dump() dict。

    线程安全（yfinance 底层非线程安全），OpenBBError 静默返回 None。
    """
    method_key = _OBB_METHOD_MAP.get(endpoint)
    if not method_key:
        logger.warning("OpenBBAdapter: unknown endpoint %s", endpoint)
        return None

    try:
        with _obb_lock:
            if method_key == "profile":
                obbject = obb.equity.profile(symbol=ticker, provider=_OBB_PROVIDER)
            elif method_key == "fundamental_metrics":
                obbject = obb.equity.fundamental.metrics(symbol=ticker, provider=_OBB_PROVIDER)
            elif method_key == "fundamental_income":
                obbject = obb.equity.fundamental.income(symbol=ticker, provider=_OBB_PROVIDER)
            elif method_key == "fundamental_balance":
                obbject = obb.equity.fundamental.balance(symbol=ticker, provider=_OBB_PROVIDER)
            else:
                return None

        # OBBject.results 是 list[BaseModel]，model_dump() 转为 dict
        results = getattr(obbject, "results", None)
        if not results:
            return None

        first = results[0] if isinstance(results, list) and results else results
        data = first.model_dump() if hasattr(first, "model_dump") else dict(first)
        return data if isinstance(data, dict) else None

    except OpenBBError as exc:
        logger.debug("OpenBBAdapter: OpenBB error for %s/%s: %s", ticker, endpoint, exc)
        return None
    except Exception as exc:
        logger.warning("OpenBBAdapter: unexpected error for %s/%s: %s", ticker, endpoint, exc)
        return None


class OpenBBAdapter(SourceAdapter):
    """OpenBB 金融数据适配器（本地 Python API 嵌入模式）。

    直接调用 obb.equity.*() 采集公司财务指标（估值、利润率、增长率等）
    和行业基准数据。返回 SourceDocument 列表供证据层链路消费。

    使用方式:
        adapter = OpenBBAdapter(timeout_seconds=20, max_documents=5)
        docs = adapter.collect(
            company_identity={"display_name": "Anthropic", "website_host": "anthropic.com"},
            field_targets=["valuation", "revenue_growth", "margin"],
            budget={"max_documents": 5},
        )
    """

    # ── 类级别常量 ──
    source_family: str = "openbb"

    # ── 字段 → OpenBB endpoint 映射 ──────────────────────────────────────────
    # 根据 field_targets 决定采集哪些财务指标维度。
    _FIELD_ENDPOINT_MAP: dict = {
        # 估值指标
        "valuation":          "/equity/fundamental/metrics",
        "market_cap":         "/equity/fundamental/metrics",
        "enterprise_value":   "/equity/fundamental/metrics",
        # 盈利能力
        "revenue":            "/equity/fundamental/income",
        "company_revenue":    "/equity/fundamental/income",
        "revenue_metrics":    "/equity/fundamental/income",
        "revenue_growth":     "/equity/fundamental/income",
        "margin":             "/equity/fundamental/metrics",
        "gross_margin":       "/equity/fundamental/metrics",
        "net_margin":         "/equity/fundamental/metrics",
        "profitability":      "/equity/fundamental/metrics",
        "ebitda":             "/equity/fundamental/income",
        # 增长
        "growth_rate":        "/equity/fundamental/metrics",
        "growth_metrics":     "/equity/fundamental/metrics",
        "yoy_growth":         "/equity/fundamental/income",
        # 财务健康
        "cash_position":      "/equity/fundamental/balance",
        "debt":               "/equity/fundamental/balance",
        "runway":             "/equity/fundamental/metrics",
        "runway_months":      "/equity/fundamental/metrics",
        # 行业基准
        "industry_benchmark": "/equity/fundamental/metrics",
        "sector_average":     "/equity/fundamental/metrics",
        # 公司概况
        "company_profile":    "/equity/profile",
        "sector":             "/equity/profile",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # OpenBB 适配器默认最多 5 个文档（金融 benchmark/metric 数据）
        self.max_documents = kwargs.get("max_documents", 5)
        self.last_summary: dict = {}

    # ── collect ──────────────────────────────────────────────────────────────

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行 OpenBB 金融数据采集。

        Args:
            company_identity: 公司身份信息，至少包含 display_name / website_host。
            field_targets: 目标字段键列表（如 valuation、revenue_growth、margin 等）。
            budget: 预算约束，可用键:
                - max_documents: 最大返回文档数（默认 5）

        Returns:
            SourceDocument 列表。无 ticker 或采集失败时返回空列表（不抛异常）。
        """
        if not _OPENBB_AVAILABLE:
            logger.warning(
                "OpenBBAdapter: openbb package not installed (%s). "
                "Install with: pip install openbb",
                _OPENBB_IMPORT_ERROR,
            )
            return []

        # ── 1. 解析身份 ──
        try:
            identity = self._build_identity_context(company_identity)
            display_name = identity.get("display_name", "")
            root_domain = identity.get("root_domain", "")
            website_host = identity.get("website_host", "")

            if not display_name and not website_host:
                logger.warning(
                    "OpenBBAdapter: no display_name or website_host in "
                    "company_identity=%s", company_identity
                )
                return []
        except Exception as e:
            logger.error("OpenBBAdapter: failed to parse company_identity: %s", e)
            return []

        # 推断 ticker（私有公司无 ticker → 返回空）
        ticker = self._infer_ticker(display_name, root_domain)
        if not ticker:
            logger.debug(
                "OpenBBAdapter: could not infer ticker for display_name=%s "
                "root_domain=%s", display_name, root_domain,
            )
            return []

        # ── 2. 解析预算 ──
        max_docs = budget.get("max_documents", self.max_documents)
        max_docs = min(max_docs, self.max_documents)

        # ── 3. 确定查询端点 ──
        endpoints = self._resolve_endpoints(field_targets)
        if not endpoints:
            logger.info(
                "OpenBBAdapter: no matching OpenBB endpoints for field_targets=%s, "
                "company=%s", field_targets, display_name
            )
            return []

        logger.info(
            "OpenBBAdapter: starting collection — %d endpoints, "
            "max_docs=%d, company=%s, ticker=%s",
            len(endpoints), max_docs, display_name, ticker,
        )

        # ── 4. 逐端点查询 ──
        docs: list[SourceDocument] = []
        seen_keys: set[str] = set()
        failed_endpoints = 0

        for endpoint in endpoints:
            if len(docs) >= max_docs:
                break

            try:
                result_data = _call_obb_method(endpoint, ticker)
            except Exception as exc:
                failed_endpoints += 1
                logger.warning(
                    "OpenBBAdapter: endpoint failed [%d/%d] — "
                    "endpoint=%s ticker=%s error=%s",
                    failed_endpoints, len(endpoints),
                    endpoint, ticker, exc,
                )
                continue

            if not result_data:
                failed_endpoints += 1
                logger.debug(
                    "OpenBBAdapter: endpoint returned empty — endpoint=%s ticker=%s",
                    endpoint, ticker,
                )
                continue

            # 将 API 响应转为 SourceDocument
            try:
                doc = self._response_to_source_document(
                    result_data, endpoint, display_name, ticker
                )
                dedup_key = f"{endpoint}:{ticker}"
                if doc and dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    docs.append(doc)
            except Exception as e:
                logger.warning(
                    "OpenBBAdapter: failed to map response for endpoint=%s: %s",
                    endpoint, e,
                )
                continue

        # ── 5. 汇总 ──
        logger.info(
            "OpenBBAdapter: collection complete — %d docs, "
            "%d/%d endpoints ok, company=%s",
            len(docs), len(endpoints) - failed_endpoints, len(endpoints),
            display_name,
        )

        return self._truncate_list(docs)

    # ── estimate_cost ────────────────────────────────────────────────────────

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算 OpenBB API 调用成本。

        本地 Python API 无网络请求费用；token 估算基于预期数据量。

        Args:
            field_targets: 目标字段键列表。
            budget: 预算约束 dict。

        Returns:
            {"estimated_tokens": int, "estimated_queries": int, "source_family": str}
        """
        endpoints = self._resolve_endpoints(field_targets)
        estimated_queries = len(endpoints)
        estimated_tokens = estimated_queries * 2000

        return {
            "estimated_tokens": estimated_tokens,
            "estimated_queries": estimated_queries,
            "source_family": self.source_family,
        }

    # ── 内部端点解析 ──────────────────────────────────────────────────────────

    def _resolve_endpoints(self, field_targets: list[str]) -> list[str]:
        """根据 field_targets 确定需要调用的 OpenBB 端点列表（去重）。

        未匹配到端点的字段被忽略（OpenBB 不覆盖所有字段类型）。
        """
        if not field_targets:
            return []

        endpoints: list[str] = []
        seen: set[str] = set()
        for field in field_targets:
            ep = self._FIELD_ENDPOINT_MAP.get(field)
            if ep and ep not in seen:
                seen.add(ep)
                endpoints.append(ep)

        return endpoints

    # ── 响应映射 ─────────────────────────────────────────────────────────────

    def _response_to_source_document(
        self,
        data: dict,
        endpoint: str,
        display_name: str,
        ticker: str,
    ) -> Optional[SourceDocument]:
        """将 obb.*() 返回的 model_dump() dict 映射为 SourceDocument。

        Args:
            data: model_dump() 返回的单条结果 dict。
            endpoint: 逻辑端点路径（如 /equity/fundamental/metrics）。
            display_name: 公司展示名。
            ticker: 股票代码。

        Returns:
            SourceDocument 或 None（数据无效时）。
        """
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 构造可读标题
        endpoint_label = endpoint.lstrip("/").replace("/", " ")
        title = f"OpenBB {endpoint_label} — {display_name} ({ticker})"

        # content: 将数据格式化为可读文本
        content = self._format_financial_data(data)

        # raw_text: 完整 JSON 字符串
        raw_text = self._safe_json_dumps(data)

        # source_url: openbb:// scheme 标识 Python API 调用
        source_url = f"openbb://{endpoint}?symbol={ticker}&provider={_OBB_PROVIDER}"

        return SourceDocument(
            source_family=self.source_family,
            source_url=source_url,
            title=title,
            content=content,
            raw_text=raw_text,
            intent=self._endpoint_to_intent(endpoint),
            trust_tier="high",
            source_score=0.90,
            entity_score=0.5,
            final_score=0.0,
            published_at="",
            fetched_at=fetched_at,
            metadata={
                "publisher": "OpenBB",
                "display_name": display_name,
                "ticker": ticker,
                "endpoint": endpoint,
                "provider": _OBB_PROVIDER,
            },
        )

    # ── 工具方法 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _infer_ticker(display_name: str, root_domain: str) -> str:
        """从公司名或域名推断股票 ticker。

        策略:
        1. domain 主干大写（如 anthropic.com → ANTHROPIC）
        2. display_name 中提取首字母缩写
        3. 直接使用 display_name 大写

        注：私有公司无 ticker，返回搜索关键词供 API 尝试。
        """
        if root_domain:
            parts = root_domain.split(".")
            if parts:
                ticker = parts[0].upper()
                if ticker and ticker != "WWW":
                    return ticker

        if display_name:
            words = display_name.split()
            if len(words) >= 2:
                abbrev = "".join(w[0].upper() for w in words if w)
                if len(abbrev) >= 2:
                    return abbrev
            return display_name.upper().replace(" ", "")

        return ""

    @staticmethod
    def _format_financial_data(data: dict) -> str:
        """将 model_dump() 返回的 dict 格式化为人类可读的文本。

        提取关键指标并转为 "key: value" 行格式，
        控制在合理长度内以供 LLM 消费。

        model_dump() 直接返回单条记录的 dict，不含外层 results 包裹。
        """
        lines: list[str] = []

        for key, value in data.items():
            if isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    if isinstance(sub_val, (int, float, str, bool)):
                        lines.append(f"{key}.{sub_key}: {sub_val}")
            elif isinstance(value, (int, float, str, bool)):
                lines.append(f"{key}: {value}")
            elif isinstance(value, list):
                if len(value) > 0:
                    lines.append(f"{key}: [{len(value)} items]")
                else:
                    lines.append(f"{key}: []")
            elif value is None:
                pass  # 跳过 None 值

        return "\n".join(lines)

    @staticmethod
    def _safe_json_dumps(data: dict) -> str:
        """安全序列化 JSON，失败返回空字符串。"""
        try:
            import json
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception:
            return str(data)

    @staticmethod
    def _endpoint_to_intent(endpoint: str) -> str:
        """将端点路径映射为采集意图标签。"""
        if "profile" in endpoint:
            return "company_profile"
        if "income" in endpoint:
            return "income_statement"
        if "balance" in endpoint:
            return "balance_sheet"
        if "metrics" in endpoint:
            return "financial_metrics"
        return "financial_data"


# ── 注册到 ADAPTER_REGISTRY ──

ADAPTER_REGISTRY[OpenBBAdapter.source_family] = OpenBBAdapter
