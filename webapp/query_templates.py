"""Field-oriented query templates for v3 research."""
from __future__ import annotations


FIELD_INTENT_MAP: dict[str, str] = {
    "market_track": "market_size",
    "market_subtrack": "market_size",
    "market_landscape_summary": "market_size",
    "market_landscape_top_players": "competition",
    "market_size_value": "market_size",
    "market_size_currency": "market_size",
    "market_size_year": "market_size",
    "market_cagr": "market_size",
    "tam_value": "market_size",
    "tam_currency": "market_size",
    "tam_year": "market_size",
    "product_tech_stack": "tech_stack",
    "product_core_features": "product",
    "product_pain_points": "product",
    "pricing_summary": "pricing_details",
    "pricing_tiers": "pricing_details",
    "mau": "user_metrics",
    "retention_rate": "retention_metrics",
    "customer_names": "customers",
    "customer_selection_reasons": "customers",
    "customer_choice_evidence": "customers",
    "funding_rounds": "funding",
    "company_achievements": "achievement",
    "competitors_top3": "competition",
    "competitive_position": "competition",
    "differentiated_opportunity": "differentiated_opportunity",
    "competitive_advantages": "competitive_position",
}

INTENT_TEMPLATES: dict[str, list[str]] = {
    "market_size": [
        "{term} TAM SAM SOM market size CAGR report",
        "{term} AI market size CAGR",
    ],
    "tech_stack": [
        "{term} tech stack architecture engineering blog",
        "site:{host} engineering architecture",
    ],
    "product": [
        "{term} product features use cases",
        "site:{host} product features",
    ],
    "pricing_details": [
        "{term} pricing plans tiers",
        "site:{host} pricing",
    ],
    "user_metrics": [
        "{term} MAU active users growth metrics",
    ],
    "retention_metrics": [
        "{term} retention rate churn cohort",
    ],
    "customers": [
        "{term} customers case study testimonials",
        "site:{host} customers case study",
    ],
    "funding": [
        "{term} funding rounds investors valuation",
    ],
    "achievement": [
        "{term} milestones achievements awards",
    ],
    "competition": [
        "{term} competitors alternatives market landscape",
        "{term} vs competitors comparison",
    ],
    "competitive_position": [
        "{term} competitive advantage differentiation market position",
    ],
    "differentiated_opportunity": [
        "{term} market gap underserved segment opportunity",
    ],
    "youtube_transcript": [
        "{term} founder interview product demo YouTube",
    ],
}


def build_field_queries(identity: dict, field_keys: list[str]) -> list[dict]:
    aliases = identity.get("aliases") or []
    primary = identity.get("display_name") or (aliases[0] if aliases else "") or identity.get("root_domain") or ""
    host = identity.get("website_host") or identity.get("root_domain") or ""
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for field_key in field_keys:
        intent = FIELD_INTENT_MAP.get(field_key, "overview")
        templates = INTENT_TEMPLATES.get(intent, ["{term} {field_key}"])
        for tmpl in templates:
            query = tmpl.format(term=primary, host=host, root=identity.get("root_domain") or "", field_key=field_key).strip()
            key = (field_key, intent, query)
            if query and key not in seen:
                seen.add(key)
                rows.append({
                    "field_key": field_key,
                    "intent": intent,
                    "query": query,
                    "term": primary,
                    "backend": "tavily",
                })
    return rows
