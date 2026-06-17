"""OpenBB 来源适配器 — 金融数据采集（benchmark / metric 数据）。

通过 OpenBB API 获取公司财务指标、行业基准和市场数据，
返回 source_family=openbb 的 SourceDocument 列表。

Max 5 docs，trust_tier=high（金融一手数据）。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

from ..source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY

logger = logging.getLogger(__name__)

# OpenBB API base URL（可通过环境变量覆盖）
_OPENBB_BASE_URL = os.environ.get("OPENBB_BASE_URL", "https://api.openbb.dev/v1")


class OpenBBAdapter(SourceAdapter):
    """OpenBB 金融数据适配器。

    封装 OpenBB API 调用，采集公司财务指标（估值、利润率、增长率等）
    和行业基准数据。返回 SourceDocument 列表供证据层链路消费。

    使用方式:
        adapter = OpenBBAdapter(timeout_seconds=20, max_documents=5)
        docs = adapter.collect(
            company_identity={"display_name": "Anthropic", "website_host": "anthropic.com"},
            field_targets=["valuation", "revenue_growth", "margin"],
            budget={"max_documents": 5, "timeout_seconds": 30},
        )
    """

    # ── 类级别常量 ──
    source_family: str = "openbb"
    API_KEY_ENV_VAR: str = "OPENBB_API_KEY"

    # ── 字段 → OpenBB endpoint 映射 ──────────────────────────────────────────
    # 根据 field_targets 决定采集哪些财务指标维度。
    # 实际 OpenBB API 提供 equity/fundamental 系列端点。
    _FIELD_ENDPOINT_MAP: dict = {
        # 估值指标
        "valuation":          "/equity/fundamental/metrics",
        "market_cap":         "/equity/fundamental/metrics",
        "enterprise_value":   "/equity/fundamental/metrics",
        # 盈利能力
        "revenue":            "/equity/fundamental/income",
        "revenue_growth":     "/equity/fundamental/income",
        "margin":             "/equity/fundamental/metrics",
        "gross_margin":       "/equity/fundamental/metrics",
        "net_margin":         "/equity/fundamental/metrics",
        "profitability":      "/equity/fundamental/metrics",
        "ebitda":             "/equity/fundamental/income",
        # 增长
        "growth_rate":        "/equity/fundamental/metrics",
        "yoy_growth":         "/equity/fundamental/income",
        # 财务健康
        "cash_position":      "/equity/fundamental/balance",
        "debt":               "/equity/fundamental/balance",
        "runway":             "/equity/fundamental/metrics",
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
        # 内部 requests Session（延迟初始化）
        self._session: Optional[requests.Session] = None

    # ── session 管理 ──────────────────────────────────────────────────────────

    def _get_session(self) -> requests.Session:
        """获取或创建带认证头的 requests.Session。"""
        if self._session is None:
            self._session = requests.Session()
            api_key = os.environ.get(self.API_KEY_ENV_VAR, "")
            if api_key:
                self._session.headers.update({
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                })
            else:
                self._session.headers.update({
                    "Accept": "application/json",
                })
            # 全局超时兜底
            self._session.timeout = self.timeout_seconds
        return self._session

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
                - timeout_seconds: 单次 API 超时（默认 20）

        Returns:
            SourceDocument 列表。无 API Key 或采集失败时返回空列表（不抛异常）。
        """
        # ── 0. 检查 API Key ──
        api_key = os.environ.get(self.API_KEY_ENV_VAR, "")
        if not api_key:
            logger.warning(
                "Adapter not configured: set %s environment variable",
                self.API_KEY_ENV_VAR,
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

        # ── 2. 解析预算 ──
        max_docs = budget.get("max_documents", self.max_documents)
        max_docs = min(max_docs, self.max_documents)
        timeout = budget.get("timeout_seconds", self.timeout_seconds)

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
            "max_docs=%d, company=%s",
            len(endpoints), max_docs, display_name,
        )

        # ── 4. 逐端点查询 ──
        session = self._get_session()
        session.timeout = timeout
        docs: list[SourceDocument] = []
        seen_urls: set[str] = set()
        failed_endpoints = 0

        for endpoint in endpoints:
            if len(docs) >= max_docs:
                break

            try:
                result_data = self._call_endpoint(
                    session, endpoint, display_name, root_domain
                )
            except Exception as exc:
                failed_endpoints += 1
                logger.warning(
                    "OpenBBAdapter: endpoint failed [%d/%d] — "
                    "endpoint=%s company=%s error=%s",
                    failed_endpoints, len(endpoints),
                    endpoint, display_name, exc,
                )
                continue

            if not result_data:
                failed_endpoints += 1
                logger.debug(
                    "OpenBBAdapter: endpoint returned empty — endpoint=%s company=%s",
                    endpoint, display_name,
                )
                continue

            # 将 API 响应转为 SourceDocument
            try:
                doc = self._response_to_source_document(
                    result_data, endpoint, display_name, root_domain
                )
                if doc and doc.source_url not in seen_urls:
                    seen_urls.add(doc.source_url)
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

        OpenBB API 通常有免费层。每次调用返回约 2000 tokens 的 JSON 数据。

        Args:
            field_targets: 目标字段键列表。
            budget: 预算约束 dict。

        Returns:
            {"estimated_tokens": int, "estimated_queries": int, "source_family": str}
        """
        endpoints = self._resolve_endpoints(field_targets)
        estimated_queries = len(endpoints)
        # 每次 API 调用约 2000 tokens 的 JSON 响应
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

    # ── API 调用 ─────────────────────────────────────────────────────────────

    def _call_endpoint(
        self,
        session: requests.Session,
        endpoint: str,
        display_name: str,
        root_domain: str,
    ) -> Optional[dict]:
        """调用单个 OpenBB API 端点，返回 JSON 响应。

        根据 display_name 或 root_domain 查找公司 ticker/标识符。
        网络错误直接上抛，由 collect() 捕获处理。

        Args:
            session: 带认证头的 requests.Session。
            endpoint: API 端点路径（如 /equity/fundamental/metrics）。
            display_name: 公司展示名。
            root_domain: 公司根域名（用于推断 ticker）。

        Returns:
            API JSON 响应 dict，失败返回 None。
        """
        url = f"{_OPENBB_BASE_URL}{endpoint}"

        # 尝试从域名推断 ticker：取根域名的主干部分大写
        ticker = self._infer_ticker(display_name, root_domain)
        if not ticker:
            logger.debug(
                "OpenBBAdapter: could not infer ticker for display_name=%s "
                "root_domain=%s", display_name, root_domain,
            )
            return None

        try:
            resp = session.get(
                url,
                params={"symbol": ticker},
                timeout=session.timeout or self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()

            if not isinstance(data, dict):
                logger.debug(
                    "OpenBBAdapter: unexpected response type for %s: %s",
                    ticker, type(data).__name__,
                )
                return None

            return data

        except requests.exceptions.Timeout:
            logger.warning(
                "OpenBBAdapter: request timeout for ticker=%s endpoint=%s",
                ticker, endpoint,
            )
            return None
        except requests.exceptions.HTTPError as e:
            logger.warning(
                "OpenBBAdapter: HTTP error for ticker=%s endpoint=%s: %s",
                ticker, endpoint, e,
            )
            return None
        except requests.exceptions.ConnectionError as e:
            logger.warning(
                "OpenBBAdapter: connection error for ticker=%s: %s",
                ticker, e,
            )
            return None
        except Exception as e:
            logger.warning(
                "OpenBBAdapter: unexpected error for ticker=%s endpoint=%s: %s",
                ticker, endpoint, e,
            )
            return None

    # ── 响应映射 ─────────────────────────────────────────────────────────────

    def _response_to_source_document(
        self,
        data: dict,
        endpoint: str,
        display_name: str,
        root_domain: str,
    ) -> Optional[SourceDocument]:
        """将 OpenBB API 响应映射为 SourceDocument。

        Args:
            data: OpenBB API 返回的 JSON dict。
            endpoint: 请求的端点路径。
            display_name: 公司展示名。
            root_domain: 公司根域名。

        Returns:
            SourceDocument 或 None（数据无效时）。
        """
        ticker = self._infer_ticker(display_name, root_domain)
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 构造可读标题
        endpoint_label = endpoint.lstrip("/").replace("/", " ")
        title = f"OpenBB {endpoint_label} — {display_name} ({ticker})"

        # content: 将 JSON 序列化为可读文本
        content = self._format_financial_data(data)

        # raw_text: 完整 JSON 字符串
        raw_text = self._safe_json_dumps(data)

        # source_url: 基于 endpoint 构造
        source_url = f"{_OPENBB_BASE_URL}{endpoint}?symbol={ticker}"

        return SourceDocument(
            source_family=self.source_family,
            source_url=source_url,
            title=title,
            content=content,
            raw_text=raw_text,
            intent=self._endpoint_to_intent(endpoint),
            trust_tier="high",  # OpenBB 金融数据为高可信度
            source_score=0.90,   # 金融数据 API 默认高来源分
            entity_score=0.5,    # 实体匹配分由 evidence_ranker 校准
            final_score=0.0,     # 综合得分由 evidence_ranker 计算
            published_at="",     # API 响应中通常不含发布日期
            fetched_at=fetched_at,
            metadata={
                "publisher": "OpenBB",
                "display_name": display_name,
                "ticker": ticker,
                "endpoint": endpoint,
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
            # 去掉 TLD，取主干大写
            parts = root_domain.split(".")
            if parts:
                ticker = parts[0].upper()
                if ticker and ticker != "WWW":
                    return ticker

        if display_name:
            # 首字母缩写（如 "OpenAI Inc" → "OAI"）
            words = display_name.split()
            if len(words) >= 2:
                abbrev = "".join(w[0].upper() for w in words if w)
                if len(abbrev) >= 2:
                    return abbrev
            # 直接大写
            return display_name.upper().replace(" ", "")

        return ""

    @staticmethod
    def _format_financial_data(data: dict) -> str:
        """将 OpenBB API 响应格式化为人类可读的文本。

        提取关键指标并转为 "key: value" 行格式，
        控制在合理长度内以供 LLM 消费。
        """
        lines: list[str] = []

        # 遍历顶层和嵌套的数值字段
        for key, value in data.items():
            if isinstance(value, dict):
                # 嵌套对象展开
                for sub_key, sub_val in value.items():
                    if isinstance(sub_val, (int, float, str, bool)):
                        lines.append(f"{key}.{sub_key}: {sub_val}")
            elif isinstance(value, (int, float, str, bool)):
                lines.append(f"{key}: {value}")
            elif isinstance(value, list):
                # 列表取摘要
                if len(value) > 0:
                    lines.append(f"{key}: [{len(value)} items]")
                else:
                    lines.append(f"{key}: []")

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
