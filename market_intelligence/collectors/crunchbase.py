from __future__ import annotations
import json, os, sys, urllib.request, urllib.error
from .base import MarketCollector

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)


class CrunchbaseCollector(MarketCollector):
    source_name = "crunchbase"
    source_type = "structured"
    BASE_URL = "https://api.crunchbase.com/api/v4"

    def collect(self, company: dict) -> list:
        api_key = self._load_api_key("CRUNCHBASE_API_KEY")
        if not api_key:
            print("[crunchbase] CRUNCHBASE_API_KEY not configured, skipping", file=sys.stderr)
            return []
        name = company.get("display_name") or company.get("company_name", "")
        domain = company.get("domain") or company.get("website_host", "")
        docs = []
        try:
            org = self._search_org(name, domain, api_key)
            if not org:
                return []
            docs.append(self._profile_to_doc(org, name))
            org_id = (org.get("identifier", {}) or {}).get("uuid") or org.get("uuid", "")
            if org_id:
                docs.extend(self._fetch_funding(org_id, name, api_key))
        except Exception as e:
            print(f"[crunchbase] Error: {e}", file=sys.stderr)
        return docs

    def _search_org(self, name: str, domain: str, api_key: str) -> dict | None:
        url = f"{self.BASE_URL}/searches/organizations?user_key={api_key}"
        body = json.dumps({
            "field_ids": [
                "identifier", "short_description", "categories", "rank",
                "location_identifiers", "num_employees_enum", "revenue_range",
                "website_url", "linkedin_url", "twitter_url", "founded_on",
                "last_funding_type", "last_funding_total", "total_funding_usd",
                "num_funding_rounds", "investor_list"
            ],
            "query": [{"type": "predicate", "field_id": "website_url", "operator_id": "contains", "values": [domain]}],
            "limit": 1,
        }).encode('utf-8')
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                entities = json.loads(resp.read().decode('utf-8')).get("entities", [])
                return entities[0] if entities else None
        except urllib.error.HTTPError as e:
            print(f"[crunchbase] HTTP {e.code} searching org: {name}", file=sys.stderr)
        except Exception as e:
            print(f"[crunchbase] Search error: {e}", file=sys.stderr)
        return None

    def _fetch_funding(self, org_id: str, name: str, api_key: str) -> list:
        url = f"{self.BASE_URL}/entities/organizations/{org_id}/cards/funding_rounds?user_key={api_key}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                rounds = (data.get("cards", {}) or {}).get("fields", [])
                if not rounds:
                    return []
                lines = []
                total = 0
                for i, r in enumerate(rounds):
                    rid = (r.get("identifier", {}) or {}).get("value", f"round-{i}")
                    rname = (r.get("funding_round_identifier", {}) or {}).get("value", "")
                    amt = (r.get("investment_usd", {}) or {}).get("value") or 0
                    valn = (r.get("valuation_usd", {}) or {}).get("value")
                    date = (r.get("announced_on", {}) or {}).get("value", "")
                    lead = (r.get("lead_investor", {}) or {}).get("value", "")
                    inv_raw = (r.get("investors", {}) or {}).get("value") or ""
                    investors = inv_raw if isinstance(inv_raw, str) else ", ".join(str(x) for x in inv_raw) if isinstance(inv_raw, list) else str(inv_raw)
                    total += float(amt) if amt else 0
                    lines.append(f"Round {i+1}: {rname} | Date: {date} | Amount: ${amt} | Valuation: {valn} | Lead: {lead} | Investors: {investors}")
                content = f"Total funding: ${total}\n\n" + "\n".join(lines)
                return [self._make_doc(
                    url=f"https://www.crunchbase.com/organization/{org_id}/company_financials",
                    title=f"{name} — Crunchbase Funding Rounds",
                    content=content, intent="funding_rounds", trust_tier="medium", source_score=0.75,
                    metadata={"crunchbase_org_id": org_id, "num_rounds": len(rounds), "total_funding_usd": total},
                )]
        except urllib.error.HTTPError as e:
            print(f"[crunchbase] HTTP {e.code} fetching rounds for {name}", file=sys.stderr)
        except Exception as e:
            print(f"[crunchbase] Funding fetch error: {e}", file=sys.stderr)
        return []

    def _profile_to_doc(self, org: dict, name: str):
        props = org.get("properties", org)
        desc = props.get("short_description", "") or ""
        cats = props.get("categories", []) or []
        cat_names = ", ".join(c.get("value", c) if isinstance(c, dict) else str(c) for c in cats)
        founded = (props.get("founded_on", {}) or {}).get("value", "") if isinstance(props.get("founded_on"), dict) else props.get("founded_on", "")
        employees = props.get("num_employees_enum", "") or ""
        rev = props.get("revenue_range", "") or ""
        tf = (props.get("total_funding_usd", {}) or {}).get("value") if isinstance(props.get("total_funding_usd"), dict) else props.get("total_funding_usd")
        rounds = props.get("num_funding_rounds", "") or ""
        website = (props.get("website_url", {}) or {}).get("value", "") if isinstance(props.get("website_url"), dict) else props.get("website_url", "")
        ident = org.get("identifier", {}) or {}
        uuid = ident.get("uuid", "")
        content = f"Name: {name}\nDescription: {desc}\nCategories: {cat_names}\nFounded: {founded}\nEmployees: {employees}\nRevenue Range: {rev}\nTotal Funding: ${tf}\nFunding Rounds: {rounds}\nWebsite: {website}\n"
        return self._make_doc(
            url=f"https://www.crunchbase.com/organization/{uuid}",
            title=f"{name} — Crunchbase Profile", content=content, intent="company_profile",
            trust_tier="medium", source_score=0.70,
            metadata={"crunchbase_data": {"founded": founded, "employees": employees, "total_funding": tf, "num_rounds": rounds, "categories": cat_names, "revenue_range": rev}},
        )
