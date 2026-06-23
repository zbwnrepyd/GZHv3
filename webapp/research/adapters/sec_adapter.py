"""SEC EDGAR 来源适配器 — 查询上市公司 SEC 备案文件。

通过 SEC EDGAR API 搜索公司 10-K、S-1 等备案文件，
返回 source_family=sec 的 SourceDocument 列表，最多 5 条备案。

API: 先通过 company_tickers.json 解析 CIK，再调用 submissions API 获取备案列表。
trust_tier: high（官方备案文件）。
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import requests

from research.source_adapter import SourceAdapter, SourceDocument, ADAPTER_REGISTRY

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────────

SEC_BASE_URL = "https://data.sec.gov"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
USER_AGENT = (
    "AI-Research-Assistant/1.0 (contact@example.com)"
)

# 目标表单类型及其优先级（数字越小越优先）
FORM_TYPE_PRIORITY: dict[str, int] = {
    "10-K": 1,
    "10-K405": 1,
    "10-KSB": 1,
    "10-KT": 1,
    "S-1": 2,
    "S-1/A": 2,
    "S-1MEF": 2,
    "10-Q": 3,
    "10-QSB": 3,
    "8-K": 4,
    "6-K": 5,
    "20-F": 2,   # 外国公司年报，等同 10-K
    "40-F": 2,   # 加拿大公司年报
}

FORM_DESCRIPTIONS: dict[str, str] = {
    "10-K": "Annual Report (10-K)",
    "10-K405": "Annual Report (10-K405)",
    "10-KSB": "Annual Report - Small Business",
    "10-KT": "Transition Report",
    "S-1": "Registration Statement (S-1)",
    "S-1/A": "Registration Statement Amendment",
    "S-1MEF": "Registration Statement - MEF",
    "10-Q": "Quarterly Report (10-Q)",
    "10-QSB": "Quarterly Report - Small Business",
    "8-K": "Current Report (8-K)",
    "6-K": "Foreign Issuer Report (6-K)",
    "20-F": "Annual Report - Foreign (20-F)",
    "40-F": "Annual Report - Canadian (40-F)",
}


# ── SecAdapter ──────────────────────────────────────────────────────────────────

class SecAdapter(SourceAdapter):
    """SEC EDGAR 来源适配器。

    通过 SEC EDGAR API 查询上市公司备案文件（10-K、S-1 等）。
    官方备案文件，可信度为 high。
    最多返回 5 条备案。

    Usage:
        adapter = SecAdapter(timeout_seconds=30, max_documents=5)
        docs = adapter.collect(
            company_identity={"display_name": "Apple Inc.", "website_host": "apple.com"},
            field_targets=["financials", "business_description", "risk_factors"],
            budget={"max_documents": 5, "timeout_seconds": 30},
        )
    """

    source_family: str = "sec"
    API_KEY_ENV_VAR: str = "SEC_API_KEY"

    timeout_seconds: int = 30
    max_documents: int = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 硬上限 5 条备案
        self.max_documents = min(kwargs.get("max_documents", 5), 5)
        self._session: Optional[requests.Session] = None

    # ── session 懒加载 ──────────────────────────────────────────────────────────

    @property
    def session(self) -> requests.Session:
        """懒加载 requests.Session，统一设置 User-Agent 和 Accept 头。

        SEC 要求所有 API 请求必须携带描述性的 User-Agent 头，
        否则返回 403 Forbidden。
        """
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
        return self._session

    # ── 核心接口 ────────────────────────────────────────────────────────────────

    def collect(
        self,
        company_identity: dict,
        field_targets: list[str],
        budget: dict,
    ) -> list[SourceDocument]:
        """执行 SEC EDGAR 备案采集。

        Args:
            company_identity: 公司身份信息，至少包含 display_name。
            field_targets: 目标字段键列表（用于日志记录）。
            budget: 预算约束 dict，可包含:
                - max_documents: 最大返回文档数（上限 5）
                - timeout_seconds: 单次请求超时秒数

        Returns:
            SourceDocument 列表。API Key 缺失或采集失败时返回空列表。
        """
        # ── API Key 检查 ──
        api_key = os.environ.get(self.API_KEY_ENV_VAR)
        if not api_key:
            logger.warning(
                "SecAdapter: Adapter not configured: set %s",
                self.API_KEY_ENV_VAR,
            )
            self.last_summary = {
                "status": "not_configured",
                "count": 0,
                "detail": f"未配置 API Key（{self.API_KEY_ENV_VAR}）",
            }
            return []

        identity = self._build_identity_context(company_identity)
        display_name = identity.get("display_name", "")

        if not display_name:
            logger.warning(
                "SecAdapter: no display_name in company_identity=%s",
                company_identity,
            )
            return []

        max_docs = min(
            budget.get("max_documents", self.max_documents),
            self.max_documents,
        )
        timeout = budget.get("timeout_seconds", self.timeout_seconds)

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents: list[SourceDocument] = []

        try:
            # ── Step 1: 查找公司 CIK ──
            cik = self._resolve_cik(display_name, timeout)
            if not cik:
                logger.info(
                    "SecAdapter: could not resolve CIK for '%s'",
                    display_name,
                )
                return []

            # ── Step 2: 获取备案列表 ──
            filings = self._fetch_filings(cik, timeout)
            if not filings:
                logger.info(
                    "SecAdapter: no filings found for CIK %s (%s)",
                    cik, display_name,
                )
                return []

            # ── Step 3: 排序、筛选、截断 ──
            filings = self._rank_and_filter_filings(filings, max_docs)

            # ── Step 4: 映射为 SourceDocument ──
            for filing in filings:
                doc = self._filing_to_source_document(
                    filing, display_name, cik, fetched_at
                )
                if doc:
                    documents.append(doc)

            logger.info(
                "SecAdapter: collected %d filings for %s (CIK %s)",
                len(documents), display_name, cik,
            )

        except requests.Timeout:
            logger.warning(
                "SecAdapter: request timed out for %s", display_name
            )
        except requests.ConnectionError as e:
            logger.warning(
                "SecAdapter: connection error for %s: %s", display_name, e
            )
        except Exception as e:
            logger.error(
                "SecAdapter: unexpected error for %s: %s",
                display_name, e,
                exc_info=True,
            )

        return documents

    def estimate_cost(
        self,
        field_targets: list[str],
        budget: dict,
    ) -> dict:
        """估算 SEC EDGAR API 调用成本。

        SEC EDGAR 是免费公共 API，无 API 费用。
        估算 token 消耗基于备案文本量。
        """
        max_docs = budget.get("max_documents", self.max_documents)
        # 每份备案 description/摘要约 2000 tokens
        estimated_tokens = max_docs * 2000
        return {
            "estimated_tokens": estimated_tokens,
            "estimated_queries": 2,  # company_tickers + submissions
            "source_family": self.source_family,
        }

    # ── CIK 解析 ────────────────────────────────────────────────────────────────

    def _resolve_cik(self, company_name: str, timeout: int) -> Optional[str]:
        """根据公司名从 SEC company_tickers.json 解析 CIK。

        策略:
        1. 精确匹配公司名
        2. 公司名包含关系匹配
        3. 关键词拆分匹配

        Args:
            company_name: 公司展示名（如 "Apple Inc."）。
            timeout: HTTP 超时秒数。

        Returns:
            10 位补零 CIK 字符串（如 "0000320193"），未找到返回 None。
        """
        try:
            resp = self.session.get(
                COMPANY_TICKERS_URL,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.Timeout:
            logger.warning("SecAdapter: company_tickers.json request timed out")
            return None
        except requests.ConnectionError as e:
            logger.warning("SecAdapter: company_tickers.json connection failed: %s", e)
            return None
        except Exception as e:
            logger.warning("SecAdapter: failed to fetch company_tickers.json: %s", e)
            return None

        if not data:
            return None

        name_lower = company_name.lower().strip()
        # 去掉常见后缀以提高匹配率
        name_clean = re.sub(
            r'\b(inc\.?|corp\.?|corporation|llc\.?|ltd\.?|limited|plc|s\.?a\.?|s\.?a\.?b\.?|ag|nv|bv|gmbh|co\.?|company)\b',
            '',
            name_lower,
            flags=re.IGNORECASE,
        ).strip().rstrip(',').strip()

        # 收集所有候选：(cik_str, title_lower)
        candidates: list[tuple[str, str]] = []
        for cik_str, info in data.items():
            title = (info.get("title", "") if isinstance(info, dict) else "").lower()
            if title:
                candidates.append((cik_str, title))

        if not candidates:
            return None

        # 第 1 轮: 精确匹配
        for cik_str, title in candidates:
            if title == name_lower:
                return self._pad_cik(cik_str)

        # 第 2 轮: 清洗后的名称精确匹配
        for cik_str, title in candidates:
            title_clean = re.sub(
                r'\b(inc\.?|corp\.?|corporation|llc\.?|ltd\.?|limited|plc|s\.?a\.?|s\.?a\.?b\.?|ag|nv|bv|gmbh|co\.?|company)\b',
                '',
                title,
                flags=re.IGNORECASE,
            ).strip().rstrip(',').strip()
            if title_clean == name_clean:
                return self._pad_cik(cik_str)

        # 第 3 轮: 清洗名包含关系（公司名包含在公司全名中，或反之）
        for cik_str, title in candidates:
            title_clean = re.sub(
                r'\b(inc\.?|corp\.?|corporation|llc\.?|ltd\.?|limited|plc|s\.?a\.?|s\.?a\.?b\.?|ag|nv|bv|gmbh|co\.?|company)\b',
                '',
                title,
                flags=re.IGNORECASE,
            ).strip().rstrip(',').strip()
            if name_clean and title_clean:
                if name_clean in title_clean or title_clean in name_clean:
                    return self._pad_cik(cik_str)

        # 第 4 轮: 关键词匹配（公司名首词匹配）
        name_first_word = name_clean.split()[0] if name_clean.split() else ""
        if name_first_word and len(name_first_word) > 2:
            for cik_str, title in candidates:
                if title.startswith(name_first_word):
                    return self._pad_cik(cik_str)

        return None

    @staticmethod
    def _pad_cik(cik: str) -> str:
        """将 CIK 补零至 10 位（SEC EDGAR API 要求）。"""
        cik = str(cik).strip()
        return cik.zfill(10)

    # ── 备案获取 ────────────────────────────────────────────────────────────────

    def _fetch_filings(
        self,
        cik: str,
        timeout: int,
    ) -> list[dict]:
        """从 SEC submissions API 获取公司备案列表。

        GET https://data.sec.gov/submissions/CIK{cik}.json

        Args:
            cik: 10 位补零 CIK。
            timeout: HTTP 超时秒数。

        Returns:
            备案 dict 列表（含 form, filingDate, primaryDocument 等字段）。
            失败时返回空列表。
        """
        url = f"{SEC_BASE_URL}/submissions/CIK{cik}.json"

        try:
            resp = self.session.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.Timeout:
            logger.warning("SecAdapter: CIK %s submissions timed out", cik)
            return []
        except requests.ConnectionError as e:
            logger.warning(
                "SecAdapter: CIK %s submissions connection failed: %s", cik, e
            )
            return []
        except Exception as e:
            logger.warning(
                "SecAdapter: CIK %s submissions request failed: %s", cik, e
            )
            return []

        # SEC submissions API 返回结构:
        # {
        #   "filings": {
        #     "recent": {
        #       "accessionNumber": [...],
        #       "filingDate": [...],
        #       "reportDate": [...],
        #       "form": [...],
        #       "primaryDocument": [...],
        #       ...
        #     }
        #   }
        # }
        filings_data = data.get("filings", {})
        recent = filings_data.get("recent", {})
        if not recent:
            return []

        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])
        accession_numbers = recent.get("accessionNumber", [])
        report_dates = recent.get("reportDate", [])
        items = recent.get("items", [])

        results: list[dict] = []
        for i in range(len(forms)):
            form_type = forms[i] if i < len(forms) else ""
            if form_type not in FORM_TYPE_PRIORITY:
                continue

            filing = {
                "form": form_type,
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "report_date": report_dates[i] if i < len(report_dates) else "",
                "primary_document": primary_docs[i] if i < len(primary_docs) else "",
                "accession_number": accession_numbers[i] if i < len(accession_numbers) else "",
                "items": items[i] if i < len(items) else "",
                "cik": cik,
            }
            results.append(filing)

        return results

    # ── 排序筛选 ────────────────────────────────────────────────────────────────

    def _rank_and_filter_filings(
        self,
        filings: list[dict],
        max_docs: int,
    ) -> list[dict]:
        """对备案列表排序、去重、截断。

        排序规则:
        1. 按表单优先级升序（10-K/S-1 > 10-Q > 8-K）
        2. 同表单按 filing_date 降序（最新的在前）
        3. 同公司同表单只保留最新一份

        Args:
            filings: 备案 dict 列表。
            max_docs: 最大保留数。

        Returns:
            排序去重后的备案列表。
        """
        # 按 form_type 去重：同类型只保留 filing_date 最新的
        best_by_form: dict[str, dict] = {}
        for f in filings:
            form = f["form"]
            if form not in best_by_form:
                best_by_form[form] = f
            else:
                # 保留更新日期的
                existing_date = best_by_form[form].get("filing_date", "")
                this_date = f.get("filing_date", "")
                if this_date > existing_date:
                    best_by_form[form] = f

        unique_filings = list(best_by_form.values())

        # 排序：按表单优先级升序，同优先级按日期降序
        def _sort_key(f: dict) -> tuple:
            priority = FORM_TYPE_PRIORITY.get(f["form"], 99)
            date_str = f.get("filing_date", "")
            # 日期降序：取负值或反转字符串比较
            return (priority, _invert_date(date_str))

        unique_filings.sort(key=_sort_key)

        return unique_filings[:max_docs]

    # ── 映射为 SourceDocument ────────────────────────────────────────────────────

    def _filing_to_source_document(
        self,
        filing: dict,
        display_name: str,
        cik: str,
        fetched_at: str,
    ) -> Optional[SourceDocument]:
        """将单条 SEC 备案映射为 SourceDocument。

        Args:
            filing: SEC 备案 dict（来自 _fetch_filings 的格式化输出）。
            display_name: 公司展示名。
            cik: 10 位 CIK。
            fetched_at: 采集时间戳。

        Returns:
            SourceDocument 实例，映射失败返回 None。
        """
        form_type = filing.get("form", "")
        filing_date = filing.get("filing_date", "")
        accession = filing.get("accession_number", "")
        primary_doc = filing.get("primary_document", "")

        if not form_type:
            return None

        # 构建 SEC 归档页面 URL
        # 格式: https://www.sec.gov/Archives/edgar/data/{cik_no_leading_zeros}/{accession_dashless}/{primary_doc}
        cik_raw = str(int(cik))  # 去掉前导零
        accession_dashless = accession.replace("-", "") if accession else ""

        if cik_raw and accession_dashless and primary_doc:
            source_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik_raw}/{accession_dashless}/{primary_doc}"
            )
        elif cik_raw:
            # 回退：公司级归档列表页
            source_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar?"
                f"action=getcompany&CIK={cik_raw}&type={form_type}"
            )
        else:
            source_url = ""

        # filing summary 页（HTML 可读版本）
        if cik_raw and accession:
            filing_url = (
                f"https://www.sec.gov/cgi-bin/viewer?"
                f"action=view&cik={cik_raw}&accession_number={accession}"
            )
        else:
            filing_url = source_url

        # 标题
        form_desc = FORM_DESCRIPTIONS.get(form_type, f"SEC Filing ({form_type})")
        title = f"{display_name} - {form_desc}"

        # content: filing 摘要信息（SEC 不返回全文，content 为基础元数据摘要）
        part_items = [title]
        if filing_date:
            part_items.append(f"Filing Date: {filing_date}")
        if filing.get("report_date"):
            part_items.append(f"Report Date: {filing['report_date']}")
        if filing.get("items"):
            part_items.append(f"Items: {filing['items']}")
        content = "\n".join(part_items)

        # raw_text: 同上（SEC EDGAR API 的 submissions 端点不返回全文，
        # 全文需通过 archive URL 单独抓取）
        raw_text = content

        # intent 映射
        intent_map = {
            "10-K": "annual_report",
            "10-K405": "annual_report",
            "10-KSB": "annual_report",
            "10-KT": "annual_report",
            "20-F": "annual_report",
            "40-F": "annual_report",
            "S-1": "registration_statement",
            "S-1/A": "registration_statement",
            "S-1MEF": "registration_statement",
            "10-Q": "quarterly_report",
            "10-QSB": "quarterly_report",
            "8-K": "current_report",
            "6-K": "foreign_report",
        }
        intent = intent_map.get(form_type, "sec_filing")

        return SourceDocument(
            source_family=self.source_family,
            source_url=source_url,
            title=title,
            content=content,
            raw_text=raw_text,
            intent=intent,
            trust_tier="high",
            source_score=1.0,     # SEC 官方备案，来源权威性满分
            entity_score=0.95,    # 由 CIK 精确匹配，实体相关性极高
            published_at=filing_date,
            fetched_at=fetched_at,
            metadata={
                "publisher": "U.S. Securities and Exchange Commission",
                "display_name": display_name,
                "cik": cik,
                "form_type": form_type,
                "accession_number": accession,
                "filing_url": filing_url,
            },
        )


# ── 辅助函数 ────────────────────────────────────────────────────────────────────

def _invert_date(date_str: str) -> str:
    """反转日期字符串用于降序排序。

    输入格式: "YYYY-MM-DD" 或 "YYYY-MM-DDTHH:MM:SS" 或空字符串。
    空日期排到最后。

    Example:
        "2024-03-15" → 变为 "7985-96-84"（ASCII 逆向）
        "" → 空字符串（排最后）
    """
    if not date_str:
        return ""
    # 将 ASCII 字符映射为反转值（'0'→'9', '9'→'0' 等），用于降序
    inverted: list[str] = []
    for ch in date_str:
        if '0' <= ch <= '9':
            inverted.append(chr(ord('9') - (ord(ch) - ord('0'))))
        else:
            inverted.append(ch)  # 保留 '-' 和 'T' 等分隔符
    return ''.join(inverted)


# ── 注册到 ADAPTER_REGISTRY ──

ADAPTER_REGISTRY[SecAdapter.source_family] = SecAdapter
