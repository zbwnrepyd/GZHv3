"""CompaniesHouse 来源适配器 — UK Companies House API 官方注册数据采集。

通过 Companies House REST API 搜索公司注册信息，返回 source_family=companieshouse
的 SourceDocument 列表。提供英国公司官方备案数据：注册详情、高管信息、财报归档等。

API 文档: https://developer-specs.company-information.service.gov.uk/
Base URL: https://api.company-information.service.gov.uk
认证方式: HTTP Basic Auth，username=API Key，password 留空

Max 5 docs. Trust tier: high (official registry).
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

from ..source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY

logger = logging.getLogger(__name__)

# ── 适配器配置 ────────────────────────────────────────────────────────────────

API_BASE_URL = "https://api.company-information.service.gov.uk"
MAX_DOCS_DEFAULT = 5
TIMEOUT_DEFAULT = 20

# 文档 intent 映射: API 端点 -> 采集意图
INTENT_SEARCH_RESULT = "company_registry_entry"
INTENT_COMPANY_PROFILE = "company_registry_detail"
INTENT_FILING_HISTORY = "financial_filing"


class CompaniesHouseAdapter(SourceAdapter):
    """UK Companies House 来源适配器。

    通过 Companies House REST API 采集英国公司官方注册数据。
    Max 5 docs。trust_tier = "high"（官方注册机构）。

    API Key 来自环境变量 COMPANIES_HOUSE_API_KEY。
    未配置 Key 时 log warning 并返回空列表。

    Usage:
        adapter = CompaniesHouseAdapter(timeout_seconds=20, max_documents=5)
        docs = adapter.collect(
            company_identity={"display_name": "Revolut", "website_host": "revolut.com"},
            field_targets=["founding_date", "company_status", "financials"],
            budget={"max_documents": 5},
        )
    """

    source_family: str = "companieshouse"
    API_KEY_ENV_VAR: str = "COMPANIES_HOUSE_API_KEY"
    timeout_seconds: int = TIMEOUT_DEFAULT
    max_documents: int = MAX_DOCS_DEFAULT

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.max_documents = kwargs.get("max_documents", MAX_DOCS_DEFAULT)
        self.timeout_seconds = kwargs.get("timeout_seconds", TIMEOUT_DEFAULT)

    # ── 核心采集 ──────────────────────────────────────────────────────────────

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行 Companies House API 采集。

        流程:
        1. 检查 API Key 是否存在 -> 否则 log warning 返回空列表
        2. 用 company display_name 搜索公司
        3. 取第一个匹配结果获取 company_number
        4. 获取公司详情（注册信息、高管等）
        5. 获取 filing history（财报归档）

        Args:
            company_identity: 公司身份信息，至少包含 display_name。
            field_targets: 目标字段键列表（如 founding_date、company_status 等）。
            budget: 预算约束 dict，可包含:
                - max_documents: 最大返回文档数（上限 5）

        Returns:
            SourceDocument 列表，不超过 max_documents。
            采集失败时返回空列表（不抛异常）。
        """
        identity = self._build_identity_context(company_identity)
        display_name = identity.get("display_name", "")

        if not display_name:
            logger.warning("CompaniesHouseAdapter: no display_name in company_identity, skipping")
            return []

        # ── API Key 检查 ──
        api_key = os.environ.get(self.API_KEY_ENV_VAR, "").strip()
        if not api_key:
            logger.warning(
                "Adapter not configured: set %s",
                self.API_KEY_ENV_VAR,
            )
            return []

        max_docs = min(
            budget.get("max_documents", self.max_documents),
            self.max_documents,
        )

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents: list[SourceDocument] = []

        session = requests.Session()
        session.auth = (api_key, "")  # Basic Auth: API key as username, empty password
        session.headers.update({
            "Accept": "application/json",
            "User-Agent": f"AIStartupsResearch/1.0 ({display_name})",
        })

        try:
            # ── Step 1: 搜索公司 ──
            search_url = f"{API_BASE_URL}/search/companies"
            search_params = {
                "q": display_name,
                "items_per_page": 3,
            }
            search_resp = self._api_get(session, search_url, params=search_params)
            if search_resp is None:
                return documents

            items = search_resp.get("items", [])
            if not items:
                logger.info(
                    "CompaniesHouseAdapter: no company found for '%s'",
                    display_name,
                )
                return documents

            # 添加搜索结果文档 (doc 1/5)
            if len(documents) < max_docs:
                top_item = items[0]
                company_number = top_item.get("company_number", "")
                search_doc = SourceDocument(
                    source_family=self.source_family,
                    source_url=(
                        f"{API_BASE_URL}/search/companies?q={display_name}"
                    ),
                    title=f"CompaniesHouse search: {display_name}",
                    content=self._format_search_result(top_item),
                    raw_text=str(top_item),
                    intent=INTENT_SEARCH_RESULT,
                    trust_tier="high",
                    source_score=0.95,
                    entity_score=0.9,
                    fetched_at=fetched_at,
                    metadata={
                        "company_number": company_number,
                        "total_results": search_resp.get("total_results", 0),
                    },
                )
                documents.append(search_doc)

            # ── Step 2: 公司详情 ──
            if company_number and len(documents) < max_docs:
                profile_url = f"{API_BASE_URL}/company/{company_number}"
                profile_resp = self._api_get(session, profile_url)
                if profile_resp is not None:
                    profile_doc = SourceDocument(
                        source_family=self.source_family,
                        source_url=profile_url,
                        title=f"CompaniesHouse profile: {display_name}",
                        content=self._format_company_profile(profile_resp),
                        raw_text=str(profile_resp),
                        intent=INTENT_COMPANY_PROFILE,
                        trust_tier="high",
                        source_score=0.95,
                        entity_score=0.95,
                        fetched_at=fetched_at,
                        metadata={
                            "company_number": company_number,
                            "company_status": profile_resp.get("company_status", ""),
                            "type": profile_resp.get("type", ""),
                            "jurisdiction": profile_resp.get("jurisdiction", ""),
                        },
                    )
                    documents.append(profile_doc)

            # ── Step 3: Filing History ──
            if company_number and len(documents) < max_docs:
                filing_url = f"{API_BASE_URL}/company/{company_number}/filing-history"
                filing_params = {"items_per_page": 5}
                filing_resp = self._api_get(
                    session, filing_url, params=filing_params
                )
                if filing_resp is not None:
                    filing_items = filing_resp.get("items", [])
                    if filing_items:
                        filing_doc = SourceDocument(
                            source_family=self.source_family,
                            source_url=filing_url,
                            title=f"CompaniesHouse filings: {display_name}",
                            content=self._format_filing_history(filing_items),
                            raw_text=str(filing_items),
                            intent=INTENT_FILING_HISTORY,
                            trust_tier="high",
                            source_score=0.95,
                            entity_score=0.85,
                            fetched_at=fetched_at,
                            metadata={
                                "company_number": company_number,
                                "filing_count": filing_resp.get("total_count", 0),
                            },
                        )
                        documents.append(filing_doc)

        except requests.Timeout:
            logger.warning(
                "CompaniesHouseAdapter: request timeout for '%s' (%ss)",
                display_name,
                self.timeout_seconds,
            )
        except requests.ConnectionError as e:
            logger.warning(
                "CompaniesHouseAdapter: connection error for '%s': %s",
                display_name,
                e,
            )
        except Exception:
            logger.warning(
                "CompaniesHouseAdapter: unexpected error for '%s'",
                display_name,
                exc_info=True,
            )
        finally:
            session.close()

        logger.info(
            "CompaniesHouseAdapter: collected %d docs for '%s'",
            len(documents),
            display_name,
        )
        return documents

    # ── 成本估算 ──────────────────────────────────────────────────────────────

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算 Companies House API 调用成本。

        Companies House API 免费，无需认证费用。
        每次采集最多 3 次 API 调用（搜索 + 详情 + filing history）。

        Args:
            field_targets: 目标字段键列表。
            budget: 预算约束 dict。

        Returns:
            {"estimated_tokens": int, "estimated_queries": int, "source_family": str}
        """
        max_docs = budget.get("max_documents", self.max_documents)
        # 每个 doc 平均 ~2000 tokens 的 JSON 格式化文本
        estimated_tokens = max_docs * 2000
        # 搜索 + 详情 + filing history = 最多 3 次 API 调用
        estimated_queries = min(max_docs, 3)

        return {
            "estimated_tokens": estimated_tokens,
            "estimated_queries": estimated_queries,
            "source_family": self.source_family,
        }

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    def _api_get(
        self,
        session: requests.Session,
        url: str,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """执行 GET 请求并返回 JSON 响应。

        统一处理超时、网络错误、HTTP 错误状态码。

        Args:
            session: requests.Session 实例（已配置 auth）。
            url: API 端点 URL。
            params: 查询参数 dict。

        Returns:
            解析后的 JSON dict。失败时返回 None。
        """
        try:
            resp = session.get(
                url,
                params=params,
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 429:
                logger.warning(
                    "CompaniesHouseAdapter: rate limited (429) on %s", url
                )
                return None
            if resp.status_code == 404:
                logger.debug(
                    "CompaniesHouseAdapter: not found (404) on %s", url
                )
                return None
            if resp.status_code >= 400:
                logger.debug(
                    "CompaniesHouseAdapter: HTTP %s on %s",
                    resp.status_code,
                    url,
                )
                return None
            return resp.json()
        except requests.Timeout:
            logger.debug(
                "CompaniesHouseAdapter: timeout on %s (%ss)",
                url,
                self.timeout_seconds,
            )
            return None
        except requests.ConnectionError as e:
            logger.debug(
                "CompaniesHouseAdapter: connection error on %s: %s",
                url,
                e,
            )
            return None
        except ValueError as e:
            # JSON 解析失败
            logger.debug(
                "CompaniesHouseAdapter: JSON parse error on %s: %s",
                url,
                e,
            )
            return None
        except Exception:
            logger.warning(
                "CompaniesHouseAdapter: unexpected error on %s",
                url,
                exc_info=True,
            )
            return None

    # ── 内容格式化 ────────────────────────────────────────────────────────────

    @staticmethod
    def _format_search_result(item: dict) -> str:
        """格式化搜索结果条目为可读文本。

        Args:
            item: Companies House search items 中的单条结果。

        Returns:
            格式化后的文本，不超过 5000 字符。
        """
        lines = []
        company_number = item.get("company_number", "")
        title = item.get("title", "")
        company_status = item.get("company_status", "")
        company_type = item.get("company_type", "")
        address = item.get("address", {})

        if title:
            lines.append(f"Company Name: {title}")
        if company_number:
            lines.append(f"Company Number: {company_number}")
        if company_status:
            lines.append(f"Status: {company_status}")
        if company_type:
            lines.append(f"Type: {company_type}")

        if address:
            addr_parts = [
                address.get("address_line_1", ""),
                address.get("address_line_2", ""),
                address.get("locality", ""),
                address.get("postal_code", ""),
                address.get("country", ""),
            ]
            addr_str = ", ".join(p for p in addr_parts if p)
            if addr_str:
                lines.append(f"Registered Office: {addr_str}")

        date_of_creation = item.get("date_of_creation", "")
        if date_of_creation:
            lines.append(f"Date of Creation: {date_of_creation}")

        description = item.get("description", "")
        if description:
            lines.append(f"Description: {description}")

        text = "\n".join(lines)
        if len(text) > 5000:
            text = text[:4997] + "..."
        return text

    @staticmethod
    def _format_company_profile(profile: dict) -> str:
        """格式化公司详情为可读文本。

        Args:
            profile: Companies House company profile JSON。

        Returns:
            格式化后的文本，不超过 5000 字符。
        """
        lines = []
        company_name = profile.get("company_name", "")
        company_number = profile.get("company_number", "")
        company_status = profile.get("company_status", "")
        company_type = profile.get("type", "")
        jurisdiction = profile.get("jurisdiction", "")

        if company_name:
            lines.append(f"Company Name: {company_name}")
        if company_number:
            lines.append(f"Company Number: {company_number}")
        if company_status:
            lines.append(f"Status: {company_status}")
        if company_type:
            lines.append(f"Type: {company_type}")
        if jurisdiction:
            lines.append(f"Jurisdiction: {jurisdiction}")

        date_of_creation = profile.get("date_of_creation", "")
        if date_of_creation:
            lines.append(f"Date of Creation: {date_of_creation}")

        # Registered office address
        reg_office = profile.get("registered_office_address", {})
        if reg_office:
            addr_parts = [
                reg_office.get("address_line_1", ""),
                reg_office.get("address_line_2", ""),
                reg_office.get("locality", ""),
                reg_office.get("postal_code", ""),
                reg_office.get("country", ""),
            ]
            addr_str = ", ".join(p for p in addr_parts if p)
            if addr_str:
                lines.append(f"Registered Office: {addr_str}")

        # Accounts info
        accounts = profile.get("accounts", {})
        if accounts:
            next_due = accounts.get("next_due_on", "")
            last_made_up = accounts.get("last_accounts", {}).get("made_up_to", "")
            if next_due:
                lines.append(f"Next Accounts Due: {next_due}")
            if last_made_up:
                lines.append(f"Last Accounts Made Up To: {last_made_up}")

        # Confirmation statement
        conf_stmt = profile.get("confirmation_statement", {})
        if conf_stmt:
            next_due = conf_stmt.get("next_due_on", "")
            if next_due:
                lines.append(f"Next Confirmation Statement Due: {next_due}")

        # SIC codes (industry classification)
        sic_codes = profile.get("sic_codes", [])
        if sic_codes:
            lines.append(f"SIC Codes: {', '.join(sic_codes)}")

        # Previous company names
        prev_names = profile.get("previous_company_names", [])
        if prev_names:
            names = [n.get("name", "") for n in prev_names if n.get("name")]
            if names:
                lines.append(f"Previous Names: {'; '.join(names)}")

        text = "\n".join(lines)
        if len(text) > 5000:
            text = text[:4997] + "..."
        return text

    @staticmethod
    def _format_filing_history(items: list[dict]) -> str:
        """格式化 filing history 为可读文本。

        Args:
            items: filing-history 端点返回的 items 列表。

        Returns:
            格式化后的文本，不超过 5000 字符。
        """
        lines = []
        for i, item in enumerate(items[:10]):
            category = item.get("category", "")
            description = item.get("description", "")
            date_str = item.get("date", "")
            action_date = item.get("action_date", "")

            line = f"[{date_str}] {category}: {description}"
            if action_date and action_date != date_str:
                line += f" (effective: {action_date})"
            lines.append(line)

        text = "Filing History:\n" + "\n".join(lines)
        if len(text) > 5000:
            text = text[:4997] + "..."
        return text


# ── 注册到全局注册表 ──

ADAPTER_REGISTRY["companieshouse"] = CompaniesHouseAdapter
