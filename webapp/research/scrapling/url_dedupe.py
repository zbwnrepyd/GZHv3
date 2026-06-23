from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


DROP_QUERY_PREFIXES = ("utm_",)
DROP_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonicalize_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in DROP_QUERY_KEYS or lowered.startswith(DROP_QUERY_PREFIXES):
            continue
        query_pairs.append((key, value))
    query = urlencode(sorted(query_pairs))
    return urlunparse((scheme, host, path, "", query, ""))


def dedupe_urls(urls: list[str], limit: int = 50) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        canonical = canonicalize_url(url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        result.append(canonical)
        if len(result) >= limit:
            break
    return result

