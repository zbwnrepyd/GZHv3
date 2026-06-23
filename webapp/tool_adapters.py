"""Optional external data-tool adapters.

Adapters never read secrets from code. Callers pass API keys explicitly from
environment/config. Without credentials they return an auditable skipped row.
"""
from __future__ import annotations

import requests


def _skipped(source_family: str, reason: str = "missing_credentials") -> dict:
    return {"status": "skipped", "source_family": source_family, "reason": reason, "items": []}


def wappalyzer_lookup(url: str, api_key: str = "") -> dict:
    if not api_key:
        return _skipped("wappalyzer")
    resp = requests.get(
        "https://api.wappalyzer.com/v2/lookup/",
        params={"urls": url},
        headers={"x-api-key": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    return {"status": "ok", "source_family": "wappalyzer", "items": resp.json()}


def similarweb_traffic(domain: str, api_key: str = "") -> dict:
    if not api_key:
        return _skipped("similarweb")
    resp = requests.get(
        f"https://api.similarweb.com/v1/website/{domain}/total-traffic-and-engagement/visits",
        params={"api_key": api_key, "main_domain_only": "false"},
        timeout=20,
    )
    resp.raise_for_status()
    return {"status": "ok", "source_family": "similarweb", "items": resp.json()}


def semrush_domain_overview(domain: str, api_key: str = "") -> dict:
    if not api_key:
        return _skipped("semrush")
    resp = requests.get(
        "https://api.semrush.com/",
        params={"type": "domain_ranks", "key": api_key, "export_columns": "Dn,Rk,Or,Ot", "domain": domain},
        timeout=20,
    )
    resp.raise_for_status()
    return {"status": "ok", "source_family": "semrush", "items": resp.text}


def openbb_dataset_stub(domain: str) -> dict:
    return _skipped("openbb", "not_configured")


def crawl4ai_extract_stub(url: str) -> dict:
    return _skipped("crawl4ai", "not_configured")
