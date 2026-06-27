"""定向补搜模块 — 对 search_once 类字段做最多一轮定向搜索

策略:
  - 只对 A/C 类公开可采集字段补搜
  - 每个字段最多 1 轮，每轮最多 4-5 个 query
  - 数据密集型字段(tam/CAGR等)使用 advanced 搜索深度 + 5 结果/query
  - 文本类字段使用 basic 深度 + 3 结果/query
  - 搜到的内容经 LLM 提取结构化值，不是简单拼接 snippet
  - 找不到就按 unavailable_policy.md 标记，不继续消耗 API
  - 搜索后记录 search_executed=1
"""

from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional


# ── 补搜 query 模板 ──
# key: field_key → list of query templates
_SEARCH_QUERY_TEMPLATES: dict[str, list[str]] = {
    "tam": [
        "{company} market size TAM total addressable market",
        "{company} {industry} market size report",
        "{industry} market size TAM 2024 2025 2026",
        "{company} revenue market opportunity billion",
    ],
    "sam": [
        "{company} serviceable addressable market SAM",
        "{company} target market size {industry}",
    ],
    "som": [
        "{company} serviceable obtainable market SOM",
        "{company} market share {industry} percentage",
    ],
    "market_cagr": [
        "{industry} market CAGR growth rate forecast",
        "{company} {industry} industry growth rate",
        "{industry} market growth rate 2024 2025 2026 compound annual",
    ],
    "product_core_features": [
        "{company} product features capabilities",
        "{company} what does it do {product_name} features",
        "{company} key features {product_name} overview",
    ],
    "acquisition_channels": [
        "{company} go to market strategy customer acquisition",
        "{company} marketing channels growth strategy",
        "{company} how they acquire customers",
    ],
    "cold_start": [
        "{company} cold start strategy early traction",
        "{company} how did they get first users initial growth",
        "founder interview {company} go to market early days",
    ],
    "regional_market_focus": [
        "{company} market region focus geographic",
        "{company} geographic expansion strategy markets",
    ],
    "regional_markets": [
        "{company} regional markets presence countries",
        "{company} international expansion global markets",
    ],
    "pricing_tiers": [
        "{company} pricing plans tiers cost",
        "{company} pricing page {product_name} price",
        "{company} how much does it cost pricing model",
    ],
    "product_tech_stack": [
        "{company} tech stack technology built with",
        "{company} {product_name} technical architecture stack",
    ],
    "customer_names": [
        "{company} customers list clients",
        "{company} case studies customers {product_name}",
        "{company} enterprise customers logos",
    ],
    "company_achievements": [
        "{company} achievements milestones awards",
        "{company} company milestones notable recognition",
    ],
    "company_achievement": [
        "{company} achievements milestones awards",
        "{company} notable accomplishments recognition",
    ],
    "competitors": [
        "{company} competitors alternatives comparison",
        "{company} vs competitors {industry} alternative",
    ],
    "competitors_top3": [
        "{company} top competitors alternatives {industry}",
        "{company} main competitors market landscape",
    ],
    "customer_choice_evidence": [
        "{company} customer testimonials why choose",
        "{company} customer reviews Gartner G2 Capterra",
        "{company} customer success stories case study",
    ],
    "ideal_customer_profile": [
        "{company} ideal customer profile target audience",
        "{company} target users persona ICP",
    ],
    "customer_segment_primary": [
        "{company} target market segment primary customers",
        "{company} primary customer segment who uses {product_name}",
    ],
    "customer_segment_secondary": [
        "{company} secondary market segments expansion",
        "{company} additional customer segments verticals",
    ],
    "timeline_events": [
        "{company} history timeline founded milestones",
        "{company} company history key events funding product launch",
    ],
    "data_confidence": [
        "{company} data privacy security compliance",
        "{company} SOC2 GDPR compliance certifications security",
    ],
}


# ── 数据密集型字段: 使用 advanced 搜索深度 + 更多结果 ──
_DATA_INTENSIVE_FIELDS: set[str] = {
    "tam", "sam", "som", "market_cagr",
    "product_core_features",
}

# 需要 LLM 提取的字段 (数字/结构化数据)
_LLM_EXTRACT_FIELDS: set[str] = {
    "tam", "sam", "som", "market_cagr",
    "acquisition_channels",
    "cold_start",
    "competitors",
    "competitors_top3",
}


@dataclass
class SearchResult:
    field_key: str
    queries_executed: list[str]
    raw_results: list[dict] = field(default_factory=list)  # [{url, title, snippet, raw_content}]
    extracted_value: str | None = None
    success: bool = False
    error: str = ""


def _build_queries(field_key: str, company: str, industry: str = "",
                   product_name: str = "") -> list[str]:
    """为字段构建搜索 query 列表（最多 5 条）。"""
    templates = _SEARCH_QUERY_TEMPLATES.get(field_key, [
        "{company} {field_key}",
        "{company} {field_key} information",
    ])

    queries = []
    for tmpl in templates[:5]:
        q = tmpl.format(
            company=company,
            industry=industry or "",
            product_name=product_name or "",
            field_key=field_key.replace("_", " "),
        )
        queries.append(q)

    return queries


def _get_search_params(field_key: str) -> dict:
    """根据字段类型返回搜索参数。

    数据密集型字段: advanced 深度 + 5 结果/query (返回 raw_content)
    文本类字段: basic 深度 + 3 结果/query (snippet 足够)
    """
    if field_key in _DATA_INTENSIVE_FIELDS:
        return {"search_depth": "advanced", "max_results": 5}
    return {"search_depth": "basic", "max_results": 3}


def _search_tavily(queries: list[str], field_key: str = "") -> list[dict]:
    """执行 Tavily 搜索，返回合并结果。

    根据字段类型自动调整搜索深度和结果数:
    - 数据密集型 → advanced + 5 结果
    - 文本类 → basic + 3 结果
    """
    api_keys_str = os.environ.get("TAVILY_API_KEYS", os.environ.get("TAVILY_API_KEY", ""))
    if not api_keys_str:
        print("[targeted_search] No Tavily API key configured, skipping search")
        return []

    api_keys = [k.strip() for k in api_keys_str.split(",") if k.strip()]
    proxy = os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY", ""))
    params = _get_search_params(field_key)

    all_results = []
    seen_urls = set()

    for query in queries:
        for key in api_keys:
            try:
                import requests
                resp = requests.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": key,
                        "query": query,
                        "search_depth": params["search_depth"],
                        "max_results": params["max_results"],
                        "include_answer": params["search_depth"] == "advanced",
                        "include_raw_content": params["search_depth"] == "advanced",
                    },
                    proxies={"https": proxy, "http": proxy} if proxy else None,
                    timeout=30,  # advanced 搜索需要更多时间
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for r in data.get("results", []):
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append({
                                "url": url,
                                "title": r.get("title", ""),
                                "snippet": r.get("content", ""),
                                "raw_content": r.get("raw_content", ""),
                                "query": query,
                            })
                    # 也收集 Tavily answer (advanced 模式下)
                    answer = data.get("answer", "")
                    if answer and answer not in seen_urls:
                        all_results.append({
                            "url": "tavily://answer",
                            "title": f"AI Answer for: {query}",
                            "snippet": answer,
                            "raw_content": answer,
                            "query": query,
                        })
                    break  # Success
                elif resp.status_code == 429:
                    continue  # Try next key
            except Exception as e:
                print(f"[targeted_search] Tavily error (key={key[:8]}...): {e}")
                continue

        time.sleep(0.5)  # Rate limit between queries

    return all_results


def _extract_with_llm(field_key: str, raw_text: str, company: str) -> str | None:
    """对搜索结果做 LLM 二次提取，获取结构化字段值。

    仅对 _LLM_EXTRACT_FIELDS 中的字段做 LLM 提取，其他字段直接返回合并文本。
    """
    if field_key not in _LLM_EXTRACT_FIELDS:
        return raw_text[:1500] if raw_text else None

    try:
        from config import config
        from deepseek_client import call_deepseek

        prompts = {
            "tam": (
                "从以下搜索结果中提取公司的TAM(总可寻址市场)数据。"
                "返回格式: '$XB' 或 '$X亿' 加年份。如果没有明确数字，返回'未找到'。"
                f"\n\n搜索结果:\n{raw_text[:3000]}\n\nTAM:"
            ),
            "sam": (
                "从以下搜索结果中提取公司的SAM(可服务市场)数据。"
                "返回格式: '$XB' 或 '$X亿'。如果没有明确数字，返回'未找到'。"
                f"\n\n搜索结果:\n{raw_text[:3000]}\n\nSAM:"
            ),
            "som": (
                "从以下搜索结果中提取公司的SOM(可获取市场)/市场份额信息。"
                "返回百分比或金额。如果没有，返回'未找到'。"
                f"\n\n搜索结果:\n{raw_text[:3000]}\n\nSOM:"
            ),
            "market_cagr": (
                "从以下搜索结果中提取{industry}市场的CAGR(年复合增长率)。"
                "返回格式: 'XX% (2024-2030)' 或类似。如果没有明确数字，返回'未找到'。"
                f"\n\n搜索结果:\n{raw_text[:3000]}\n\nCAGR:"
            ),
            "acquisition_channels": (
                f"从以下搜索结果中提取{company}的客户获取渠道。"
                "列出2-5个主要渠道(如: 内容营销、PLG、销售团队、合作伙伴等)。"
                "用中文逗号分隔。"
                f"\n\n搜索结果:\n{raw_text[:3000]}\n\n获客渠道:"
            ),
            "cold_start": (
                f"从以下搜索结果中提取{company}的冷启动/早期增长策略。"
                "用1-2句中文说明他们如何获得第一批用户。"
                f"\n\n搜索结果:\n{raw_text[:3000]}\n\n冷启动策略:"
            ),
            "competitors": (
                f"从以下搜索结果中列出{company}的主要竞品。"
                "返回3-5个竞品名称，逗号分隔。"
                f"\n\n搜索结果:\n{raw_text[:2000]}\n\n竞品:"
            ),
            "competitors_top3": (
                f"从以下搜索结果中列出{company}的Top3最强竞品。"
                "按竞争威胁排序，逗号分隔。"
                f"\n\n搜索结果:\n{raw_text[:2000]}\n\nTop3竞品:"
            ),
        }

        prompt = prompts.get(field_key, "")
        if not prompt:
            return raw_text[:1500]

        result = call_deepseek(
            config.DEEPSEEK_API_KEY,
            "你是一个商业数据分析师。从搜索结果中提取精确信息。只返回结果，不要解释。信息不足时返回'未找到'。",
            prompt,
            temperature=0.1,
            max_tokens=200,
        )
        return result.strip() if result else None
    except Exception as e:
        print(f"[targeted_search] LLM extract failed for {field_key}: {e}")
        return raw_text[:1500] if raw_text else None


def search_field(field_key: str, company: str,
                 industry: str = "", product_name: str = "",
                 db_path: str = "") -> SearchResult:
    """对单个字段执行一轮定向补搜。

    Args:
        field_key: 目标字段
        company: 公司名
        industry: 行业
        product_name: 产品名
        db_path: 数据库路径

    Returns:
        SearchResult
    """
    # 检查是否已搜索过
    if db_path:
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT search_executed FROM field_resolution_logs "
                "WHERE company_name=? AND field_key=? AND search_executed=1 "
                "LIMIT 1",
                (company, field_key),
            ).fetchone()
            conn.close()
            if row:
                return SearchResult(
                    field_key=field_key,
                    queries_executed=[],
                    success=False,
                    error="already searched — 不重复补搜",
                )
        except Exception:
            pass

    queries = _build_queries(field_key, company, industry, product_name)
    if not queries:
        return SearchResult(
            field_key=field_key,
            queries_executed=[],
            success=False,
            error="no query templates",
        )

    params = _get_search_params(field_key)
    print(f"[targeted_search] {field_key}: {len(queries)} queries "
          f"(depth={params['search_depth']}, max_results={params['max_results']})...")
    raw_results = _search_tavily(queries, field_key)

    if raw_results:
        # 优先用 raw_content (advanced 模式)，其次用 snippet
        texts = []
        for r in raw_results:
            raw = r.get("raw_content", "")
            if raw and len(raw) > 50:
                texts.append(raw[:1000])
            elif r.get("snippet"):
                texts.append(r["snippet"][:500])
        combined = "\n---\n".join(texts[:10])

        # LLM 提取结构化值
        extracted = _extract_with_llm(field_key, combined, company)

        return SearchResult(
            field_key=field_key,
            queries_executed=queries,
            raw_results=raw_results,
            extracted_value=extracted[:2000] if extracted else combined[:2000],
            success=True,
        )

    return SearchResult(
        field_key=field_key,
        queries_executed=queries,
        success=False,
        error="no results from Tavily",
    )


def search_all(search_once_fields: list[str],
               company: str,
               industry: str = "",
               product_name: str = "",
               db_path: str = "",
               progress_callback=None,
               ) -> dict[str, SearchResult]:
    """批量补搜 search_once 类字段。

    Returns:
        {field_key: SearchResult}
    """
    results: dict[str, SearchResult] = {}
    total = len(search_once_fields)

    # 按数据密集型优先排序
    sorted_fields = sorted(
        search_once_fields,
        key=lambda fk: (fk not in _DATA_INTENSIVE_FIELDS, fk)
    )

    for i, fk in enumerate(sorted_fields):
        if progress_callback:
            progress_callback(i + 1, total, fk)

        result = search_field(fk, company, industry, product_name, db_path)
        results[fk] = result

        if result.success:
            val_preview = (result.extracted_value or "")[:80]
            print(f"[targeted_search] {fk}: ✓ {len(result.raw_results)} results → "
                  f"\"{val_preview}...\"")
        else:
            print(f"[targeted_search] {fk}: ✗ {result.error}")

    success_count = sum(1 for r in results.values() if r.success)
    print(f"[targeted_search] done: {success_count}/{total} fields found results")
    return results


def extract_value_from_search_results(search_results: dict[str, SearchResult],
                                       confirmed_fields: dict[str, str] | None = None,
                                       ) -> dict[str, str]:
    """从搜索结果中提取字段值。

    已经过 LLM 提取的值直接使用，未提取的字段使用拼接 snippet。
    """
    extracted: dict[str, str] = {}
    for fk, sr in search_results.items():
        if sr.success and sr.extracted_value:
            val = sr.extracted_value.strip()
            if val and val not in ("未找到", "暂无", "None"):
                extracted[fk] = val
    return extracted
