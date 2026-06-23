import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP = os.path.join(ROOT, "webapp")
if WEBAPP not in sys.path:
    sys.path.insert(0, WEBAPP)


def test_openbb_resolves_project_metric_fields_to_endpoints():
    from research.adapters.openbb_adapter import OpenBBAdapter

    adapter = OpenBBAdapter()

    endpoints = adapter._resolve_endpoints([
        "company_revenue",
        "revenue_metrics",
        "growth_metrics",
        "gross_margin",
        "runway_months",
        "product_tech_stack",
    ])

    assert "/equity/fundamental/income" in endpoints
    assert "/equity/fundamental/metrics" in endpoints
    assert len(endpoints) == 2
