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
    "main_product_highlight": [
        "{company} product features capabilities",
        "{company} product unique selling point",
    ],
    "main_product_achievement": [
        "{company} product milestone achievement",
        "{company} product growth users traction",
    ],
    "product_core_features": [
        "{company} product features capabilities",
        "{company} product functionality overview",
    ],
    "product_pain_points": [
        "{company} solves problem pain point",
        "{company} customer pain points addressed",
    ],
    "product_usage_playbook": [
        "{company} product usage workflow tutorial",
        "{company} how to use guide demo",
    ],
    "product_tech_stack": [
        "{company} technology stack built with architecture",
        "{company} AI model infrastructure tech",
    ],
    "pricing_model": [
        "{company} pricing",
        "{company} pricing page",
    ],
    "pricing_summary": [
        "{company} pricing",
        "{company} plans pricing",
    ],
    "pricing_tiers": [
        "{company} pricing plans tiers pro enterprise",
        "{company} pricing comparison free vs paid",
    ],
    "pricing_strategy": [
        "{company} pricing strategy model",
        "{company} monetization business model",
    ],
    "customer_segment": [
        "{company} customers",
        "{company} customer segment",
    ],
    "customer_names": [
        "{company} customers case study",
        "{company} customer stories",
    ],
    "customer_selection_reasons": [
        "{company} why customers choose",
        "{company} customer testimonial review",
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
        "{company} top competitors comparison",
    ],
    "competitive_position": [
        "{company} competitive positioning advantage",
        "{company} market position differentiation",
    ],
    "competitors_summary": [
        "{company} competitive landscape overview",
        "{company} vs alternatives comparison",
    ],
    "differentiation_strategy": [
        "{company} differentiation strategy competitive advantage",
        "{company} unique selling proposition moat",
    ],
    "differentiated_opportunity": [
        "{company} market gap opportunity underserved",
        "{company} blue ocean niche expansion",
    ],
    "moat": [
        "{company} competitive moat defensibility",
        "{company} barriers to entry advantage",
    ],
    "company_achievement": [
        "{company} milestone awards recognition",
        "{company} notable achievement recognition",
    ],
    "company_achievements": [
        "{company} milestone awards recognition",
        "{company} notable achievement recognition",
    ],
    "core_competency": [
        "{company} core competency technology advantage",
        "{company} key capability differentiation",
    ],
    "tech_stack": [
        "{company} technology stack built with architecture",
        "{company} infrastructure tech stack engineering",
    ],
    "timeline_events": [
        "{company} founded history timeline milestones",
        "{company} company history major events",
    ],
    "gtm_strategy": [
        "{company} go-to-market strategy",
        "{company} growth strategy customer acquisition",
    ],
    "gtm_motion": [
        "{company} go-to-market motion sales strategy",
        "{company} enterprise B2B GTM approach",
    ],
    "growth_flywheel": [
        "{company} growth flywheel loop",
        "{company} viral growth engine",
    ],
    "acquisition_channels": [
        "{company} customer acquisition channels",
        "{company} marketing channels growth",
    ],
    "growth_strategy": [
        "{company} growth strategy expansion plan",
        "{company} scaling strategy future growth",
    ],
    "cold_start": [
        "{company} cold start initial customers",
        "{company} early traction first users",
    ],
    "market_opportunity": [
        "{company} market opportunity",
        "{company} market size potential",
    ],
    "market_cagr": [
        "{company} market CAGR growth rate industry report",
        "{company} market growth rate forecast",
    ],
    "market_size_value": [
        "{company} market size TAM SAM industry report",
        "{company} total addressable market value",
    ],
    "tam": [
        "{company} TAM total addressable market size",
        "{company} market size report industry",
    ],
    "regional_markets": [
        "{company} markets regions global presence",
        "{company} geographic expansion international",
    ],
    "regional_market_focus": [
        "{company} target markets regions expansion",
        "{company} geographic focus primary market",
    ],
    "ecosystem_positioning": [
        "{company} ecosystem platform positioning",
        "{company} AI ecosystem role position",
    ],
    "ecosystem_niche": [
        "{company} ecosystem niche specialization",
        "{company} vertical focus niche market",
    ],
    "github_metrics": [
        "{company} github",
        "{company} github stars repository",
    ],
    "producthunt_metrics": [
        "{company} Product Hunt",
        "{company} ProductHunt launch",
    ],
    "revenue_model": [
        "{company} revenue model business model",
        "{company} monetization how makes money",
    ],
    "team_size": [
        "{company} team size employees headcount",
        "{company} number of employees team",
    ],
    "team_highlight": [
        "{company} team talent engineering",
        "{company} leadership team executives",
    ],
    "founded_date": [
        "{company} founded year established",
        "{company} founding date incorporation",
    ],
    "core_business": [
        "{company} core business what does do",
        "{company} business model overview",
    ],
    "industry_positioning": [
        "{company} industry positioning category",
        "{company} market category sector",
    ],
    "market_track": [
        "{company} market track sector category",
        "{company} industry segment vertical",
    ],
    "market_subtrack": [
        "{company} market subcategory niche",
        "{company} subsegment specific vertical",
    ],
    "market_landscape_summary": [
        "{company} market landscape overview analysis",
        "{company} industry landscape competitive",
    ],
    "customer_segment_primary": [
        "{company} target customer primary audience",
        "{company} ideal customer profile ICP",
    ],
    "customer_segment_secondary": [
        "{company} secondary customer segment",
        "{company} additional customer verticals",
    ],
    "ideal_customer_profile": [
        "{company} ideal customer profile ICP",
        "{company} target buyer persona",
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
