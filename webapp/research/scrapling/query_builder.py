from __future__ import annotations

from dataclasses import dataclass


PUBLIC_FIELD_QUERY_TEMPLATES = {
    "company_name": [
        "{company} official website",
        "{company} company profile",
    ],
    "website_url": [
        "{company} official website",
        "{company} homepage",
    ],
    "location": [
        "{company} headquarters location",
        "{company} office location",
    ],
    "founder_name": [
        "{company} founder",
        "{company} cofounder CEO",
    ],
    "founder_bg": [
        "{company} founder background",
        "{company} founder biography",
    ],
    "founder_edu": [
        "{company} founder education",
        "{company} founder university",
    ],
    "funding_info": [
        "{company} funding total investors",
        "{company} raises series funding",
    ],
    "funding_rounds": [
        "{company} funding rounds",
        "{company} series a series b funding",
    ],
    "main_product_name": [
        "{company} product",
        "{company} main product",
    ],
    "main_product_def": [
        "{company} product overview",
        "{company} product features",
    ],
    "pricing_model": [
        "{company} pricing",
        "{company} pricing page",
    ],
    "pricing_summary": [
        "{company} pricing",
        "{company} plans pricing",
    ],
    "customer_segment": [
        "{company} customers",
        "{company} customer segment",
    ],
    "customer_names": [
        "{company} customers case study",
        "{company} customer stories",
    ],
    "customers": [
        "{company} customers case study",
        "{company} customer stories",
    ],
    "competitors": [
        "{company} competitors alternatives",
        "{company} market competitors",
    ],
    "competitors_top3": [
        "{company} competitors alternatives",
        "{company} top competitors",
    ],
    "github_metrics": [
        "{company} github",
        "{company} github stars",
    ],
    "producthunt_metrics": [
        "{company} Product Hunt",
        "{company} ProductHunt launch",
    ],
    "market_opportunity": [
        "{company} market opportunity",
        "{company} market size",
    ],
}

PRIVATE_FIELDS = {
    "ltv", "cac", "ltv_cac_ratio", "arr", "mrr", "revenue",
    "company_revenue", "gross_margin", "burn_rate", "retention_rate",
    "churn_rate", "runway_months",
}


@dataclass(frozen=True)
class FieldQuery:
    field_key: str
    query: str
    provider_intent: str


def build_field_queries(
    company_identity: dict,
    field_targets: list[str],
    *,
    max_queries_per_field: int = 1,
) -> list[FieldQuery]:
    """Build conservative field-level web queries for public facts."""
    company = (
        company_identity.get("display_name")
        or company_identity.get("canonical_name")
        or company_identity.get("company_name")
        or ""
    ).strip()
    if not company:
        return []

    queries: list[FieldQuery] = []
    seen: set[str] = set()
    for field_key in field_targets:
        if field_key in PRIVATE_FIELDS:
            continue
        templates = PUBLIC_FIELD_QUERY_TEMPLATES.get(field_key)
        if not templates:
            readable_field = field_key.replace("_", " ")
            templates = [f"{{company}} {readable_field}"]
        for template in templates[:max_queries_per_field]:
            query = template.format(company=company).strip()
            normalized = query.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            queries.append(FieldQuery(
                field_key=field_key,
                query=query,
                provider_intent=f"field:{field_key}",
            ))
    return queries
