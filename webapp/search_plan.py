"""搜索计划生成 — 按意图生成多 query，覆盖 founders/funding/product/pricing/competitors 等。

deep 模式覆盖 10 类意图，standard 模式覆盖 6 类核心意图。
每类意图使用多个搜索别名（原始名、小写、首字母大写、域名等）生成 query。
"""
from __future__ import annotations
from dataclasses import dataclass
from config import config


@dataclass
class TavilyQuery:
    query: str
    intent: str
    term: str


@dataclass
class SearchPlan:
    tavily_queries: list[TavilyQuery]
    github_queries: list[str]
    youtube_queries: list[str]
    query_count: int


TAVILY_QUERY_TEMPLATES: dict[str, list[str]] = {
    "overview": [
        "{term} company about product business model",
        "{term} official website what does {term} do",
        "{term} AI startup company profile",
    ],
    "founders": [
        "{term} founder CEO background education previous company",
        "{term} founder interview biography LinkedIn profile",
        "{term} founding team background experience",
    ],
    "funding": [
        "{term} funding round seed series A B investors valuation amount",
        "{term} raised funding million TechCrunch Crunchbase PitchBook",
        "{term} funding history latest round",
    ],
    "product": [
        "{term} product features capabilities demo screenshot",
        "{term} use cases customers case study product tour",
        "{term} product launch announcement new feature",
    ],
    "pricing": [
        "{term} pricing plans subscription cost price page",
        "site:{host} pricing",
        "{term} pricing model business model",
    ],
    "competitors": [
        "{term} competitors alternatives comparison vs",
        "{term} market landscape competitive analysis",
        "{term} similar companies alternatives",
    ],
    # 运营数据专项：借鉴 data-analytics-skills 的“子问题 + 数据依赖”拆解
    "market_size": [
        "{term} TAM SAM SOM market size CAGR report",
        "{term} total addressable market serviceable obtainable market",
        "{term} market size growth rate CAGR industry report",
    ],
    "achievement": [
        "{term} milestone achievement award recognition notable",
        "{term} announced partnership customer signed deal",
    ],
    "product_tech_stack": [
        "{term} technology stack built using architecture infrastructure",
        "{term} AI model LLM API technical architecture engineering blog",
    ],
    # deep 模式额外意图
    "gtm": [
        "{term} go to market growth strategy customer acquisition",
        "{term} Product Hunt launch users growth viral",
        "{term} sales strategy enterprise B2B GTM motion",
    ],
    "timeline": [
        "{term} founded launch history timeline milestones",
        "{term} announcement rebrand acquisition pivot news",
    ],
    "community": [
        "{term} Product Hunt Hacker News Reddit Twitter review discussion",
    ],
    "interview": [
        "{term} founder CEO interview podcast YouTube video",
        "{term} founder keynote talk conference presentation",
    ],
    # v3 新增意图
    "customers": [
        "{term} customers case study enterprise clients testimonials",
        "{term} 客户案例 customer success stories",
        "{term} client list customers logos partners",
    ],
    "pricing_details": [
        "{term} pricing plans tiers detailed breakdown",
        "site:{host} pricing plans",
        "{term} pricing comparison free pro enterprise",
    ],
    "youtube_transcript": [
        "{term} founder interview product demo review",
        "{term} CEO keynote presentation conference talk",
        "{term} company overview explainer demo",
    ],
    "competitive_position": [
        "{term} competitive advantage differentiation market position",
        "{term} vs competitors comparison why {term} better",
        "{term} unique selling proposition competitive moat",
    ],
    "differentiated_opportunity": [
        "{term} market gap opportunity underserved segment",
        "{term} niche market blue ocean differentiation strategy",
        "{term} competitive white space expansion opportunity",
    ],
    "financial_metrics": [
        "{term} revenue ARR MRR financial performance metrics",
        "{term} annual recurring revenue growth rate financials",
        "{term} revenue run rate subscription income",
    ],
    "team_culture": [
        "{term} team culture engineering hiring talent",
        "{term} company culture values mission",
        "{term} engineering team tech talent hiring",
    ],
}


def _depth() -> str:
    return config.RESEARCH_DEPTH


def _query_budget() -> int:
    if _depth() == "deep":
        return config.TAVILY_QUERY_BUDGET_DEEP
    return config.TAVILY_QUERY_BUDGET_STANDARD


def build_search_plan(display_name: str, root_domain: str,
                      website_host: str, aliases: list[str]) -> SearchPlan:
    depth = _depth()
    budget = _query_budget()

    core_intents = ["overview", "founders", "funding",
                    "product", "pricing", "competitors",
                    "market_size",
                    "achievement", "product_tech_stack",
                    # v3 新增意图
                    "customers", "pricing_details", "youtube_transcript",
                    "competitive_position", "differentiated_opportunity",
                    "financial_metrics", "team_culture"]
    if depth == "deep":
        core_intents.extend(["gtm", "timeline", "community", "interview"])

    tavily_queries: list[TavilyQuery] = []
    terms = list(dict.fromkeys(aliases))[:5]

    def _append_query(intent: str, term: str, tmpl: str) -> None:
        if len(tavily_queries) >= budget:
            return
        q = tmpl.format(term=term, host=website_host,
                        root=root_domain)
        if any(existing.query == q for existing in tavily_queries):
            return
        tavily_queries.append(
            TavilyQuery(query=q, intent=intent, term=term))

    # 第一轮先覆盖全部意图，避免预算被早期意图耗尽。
    primary_term = terms[0] if terms else (display_name or root_domain or website_host or "")
    for intent in core_intents:
        templates = TAVILY_QUERY_TEMPLATES.get(intent, [])
        if templates and primary_term:
            _append_query(intent, primary_term, templates[0])

    for intent in core_intents:
        templates = TAVILY_QUERY_TEMPLATES.get(intent, [])
        for term in terms[:3]:
            # 每意图取第1个模板（保证广度覆盖所有意图），关键意图取2个
            limit = 2 if intent in ("funding", "product", "founders",
                                    "market_size") else 1
            for tmpl in templates[:limit]:
                if len(tavily_queries) >= budget:
                    break
                _append_query(intent, term, tmpl)
            if len(tavily_queries) >= budget:
                break
        if len(tavily_queries) >= budget:
            break

    github_queries: list[str] = []
    if root_domain:
        github_queries.append(f"{root_domain} in:name,description,readme")
    if display_name:
        github_queries.append(f"{display_name} in:name,description,readme")
    if website_host:
        github_queries.append(f"{website_host} in:readme")
    github_queries = list(dict.fromkeys(
        [q for q in github_queries if q.strip()]))

    youtube_queries: list[str] = []
    if display_name:
        youtube_queries.append(f"{display_name} founder interview")
    if root_domain:
        youtube_queries.append(f"{root_domain} founder interview")
    if display_name:
        youtube_queries.append(f"{display_name} product demo")
    if website_host:
        youtube_queries.append(f"{website_host} founder interview")
    youtube_queries = list(dict.fromkeys(
        [q for q in youtube_queries if q.strip()]))

    return SearchPlan(
        tavily_queries=tavily_queries,
        github_queries=github_queries,
        youtube_queries=youtube_queries,
        query_count=len(tavily_queries),
    )
