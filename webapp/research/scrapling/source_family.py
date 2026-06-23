from __future__ import annotations

from urllib.parse import urlparse


HIGH_TRUST_HOST_KEYWORDS = {
    "github.com": ("github", "high", 0.9),
    "producthunt.com": ("producthunt", "medium", 0.8),
    "sec.gov": ("sec", "high", 1.0),
    "companieshouse.gov.uk": ("companieshouse", "high", 1.0),
    "crunchbase.com": ("crunchbase", "medium", 0.75),
}


def classify_source(url: str, official_host: str = "") -> tuple[str, str, float]:
    host = urlparse(url or "").netloc.lower()
    official = (official_host or "").lower().removeprefix("www.")
    normalized_host = host.removeprefix("www.")
    if official and normalized_host == official:
        return "official", "high", 1.0
    for suffix, result in HIGH_TRUST_HOST_KEYWORDS.items():
        if normalized_host == suffix or normalized_host.endswith("." + suffix):
            return result
    if any(name in normalized_host for name in ("techcrunch.com", "forbes.com", "businesswire.com", "prnewswire.com")):
        return "media", "medium", 0.7
    return "open_web", "medium", 0.5

