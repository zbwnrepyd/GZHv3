from __future__ import annotations
import json, os, sys, urllib.request, urllib.error, urllib.parse
from .base import MarketCollector

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)


class TavilyMarketCollector(MarketCollector):
    source_name = "tavily_market"
    source_type = "web_search"

    DOMAIN_SCORES = {
        "grandviewresearch.com": 0.85, "gartner.com": 0.90, "idc.com": 0.88,
        "statista.com": 0.75, "forrester.com": 0.85,
        "techcrunch.com": 0.65, "reuters.com": 0.80, "bloomberg.com": 0.85,
        "crunchbase.com": 0.75, "pitchbook.com": 0.80, "cbinsights.com": 0.75,
        "a16z.com": 0.70, "sequoiacap.com": 0.70, "bvp.com": 0.70,
        "ycombinator.com": 0.60, "theinformation.com": 0.65,
        "fortune.com": 0.65, "wsj.com": 0.80, "ft.com": 0.80,
    }

    def _get_api_keys(self) -> list[str]:
        """Match pipeline.py: try TAVILY_API_KEYS first, then TAVILY_API_KEY.
        Both may contain comma-separated keys. Returns all available keys.
        """
        for env_var in ("TAVILY_API_KEYS", "TAVILY_API_KEY"):
            val = self._load_api_key(env_var)
            if val:
                return [k.strip() for k in val.split(",") if k.strip()]
        return []

    def collect(self, company: dict) -> list:
        api_keys = self._get_api_keys()
        if not api_keys:
            print("[tavily_market] TAVILY_API_KEY(S) not configured, skipping", file=sys.stderr)
            return []
        name = company.get("display_name") or company.get("company_name", "")
        category = company.get("category", "")
        domain = company.get("domain", "")
        queries = self._build_queries(name, category, domain)
        docs = []
        for query in queries[:8]:
            for key_idx, api_key in enumerate(api_keys):
                try:
                    results = self._search_tavily(query, api_key)
                    for r in results[:3]:
                        if r.get("url") and r.get("content") and len(r.get("content", "")) >= 100:
                            docs.append(self._to_doc(r, query))
                    break  # success — don't try remaining keys
                except urllib.error.HTTPError as e:
                    if e.code in (429, 432) and key_idx < len(api_keys) - 1:
                        continue  # quota exceeded, try next key
                    break  # non-quota error, don't retry
                except Exception:
                    if key_idx < len(api_keys) - 1:
                        continue  # timeout etc, try next key
                    break
        return docs

    def _build_queries(self, name: str, category: str, domain: str) -> list[str]:
        qs = []
        if category:
            qs.append(f"{category} market size 2025")
            qs.append(f"{category} TAM SAM market report forecast")
            qs.append(f"{category} CAGR growth rate industry")
            qs.append(f"{category} industry report 2025")
        qs.append(f'"{name}" market size valuation')
        qs.append(f'"{name}" revenue ARR estimate')
        qs.append(f'"{name}" funding round total investment')
        qs.append(f'"{name}" financials business model')
        return qs

    def _search_tavily(self, query: str, api_key: str) -> list[dict]:
        """Call Tavily API. Raises urllib.error.HTTPError on HTTP errors (caller handles rotation)."""
        url = "https://api.tavily.com/search"
        body = json.dumps({
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
            "max_results": 5,
        }).encode('utf-8')
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8')).get("results", [])

    def _to_doc(self, result: dict, query: str):
        url = result.get("url", "")
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        score = 0.5
        for known, s in self.DOMAIN_SCORES.items():
            if known in host:
                score = s
                break
        return self._make_doc(
            url=url, title=result.get("title", ""),
            content=result.get("content", "")[:50000],
            intent="market_report", trust_tier="medium", source_score=score,
            metadata={"tavily_query": query, "domain": host},
        )
