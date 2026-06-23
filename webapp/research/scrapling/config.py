from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default) == "1"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class ScraplingCrawlerConfig:
    enabled: bool
    fetcher: str
    providers: list[str]
    search_delay_seconds: int
    max_queries_per_company: int
    results_per_query: int
    max_urls_per_company: int
    timeout_seconds: int
    max_concurrency: int


def load_config() -> ScraplingCrawlerConfig:
    return ScraplingCrawlerConfig(
        enabled=_env_bool("SCRAPLING_ENABLED", "0"),
        fetcher=os.environ.get("SCRAPLING_FETCHER", "auto").strip().lower(),
        providers=_env_list("SCRAPLING_SEARCH_PROVIDERS", "bing"),
        search_delay_seconds=_env_int("SCRAPLING_SEARCH_DELAY_SECONDS", 0),
        max_queries_per_company=_env_int("SCRAPLING_MAX_QUERIES_PER_COMPANY", 80),
        results_per_query=_env_int("SCRAPLING_RESULTS_PER_QUERY", 10),
        max_urls_per_company=_env_int("SCRAPLING_MAX_URLS_PER_COMPANY", 120),
        timeout_seconds=_env_int("SCRAPLING_TIMEOUT_SECONDS", 10),
        max_concurrency=max(1, _env_int("SCRAPLING_MAX_CONCURRENCY", 4)),
    )
