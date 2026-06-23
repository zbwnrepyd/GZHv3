from __future__ import annotations

import os
import sys as _sys
import threading as _threading
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    url: str
    html: str
    status: str = "ok"
    error: str = ""


BLOCKED_MARKERS = (
    "just a moment",
    "cloudflare",
    "cf-browser-verification",
    "verify you are human",
    "checking your browser",
    "captcha",
    "access denied",
    "one last step",
    "solve the challenge",
    "enablejs",
    "if you're having trouble accessing google search",
)


def _page_to_html(page) -> str:
    for attr in ("html", "html_content", "content", "body", "text"):
        value = getattr(page, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if isinstance(value, bytes):
            try:
                value = value.decode(getattr(page, "encoding", None) or "utf-8", errors="ignore")
            except Exception:
                value = value.decode("utf-8", errors="ignore")
        if value is None:
            continue
        html = str(value)
        if html.strip() and html != str(page or ""):
            return html

    for method_name in ("prettify",):
        method = getattr(page, method_name, None)
        if not callable(method):
            continue
        try:
            html = str(method())
            if html.strip():
                return html
        except Exception:
            continue
    return str(page or "")


def _looks_blocked(html: str) -> bool:
    body = (html or "")[:4000].lower()
    return any(marker in body for marker in BLOCKED_MARKERS)


def _call_fetcher(fetcher_cls, method_names: tuple[str, ...], url: str, **kwargs):
    # 注入代理配置（如果环境变量有 HTTPS_PROXY/HTTP_PROXY 且调用方未显式传 proxy）
    if "proxy" not in kwargs:
        env_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
        if env_proxy:
            kwargs["proxy"] = env_proxy
    last_error = None
    for method_name in method_names:
        method = getattr(fetcher_cls, method_name, None)
        if not callable(method):
            continue
        try:
            return method(url, **kwargs)
        except TypeError as exc:
            last_error = exc
            # Only strip kwargs that are known to be optional, never strip solve_cloudflare
            reduced_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key not in {"network_idle"}
            }
            if reduced_kwargs != kwargs:
                try:
                    return method(url, **reduced_kwargs)
                except TypeError:
                    pass
            raise
    if last_error:
        raise last_error
    raise AttributeError(f"{fetcher_cls.__name__} has no supported fetch method")


# ---------------------------------------------------------------------------
# Lazy import of Scrapling fetcher classes (thread-safe, one-time).
# Import errors surface as ImportError with a helpful message.
# ---------------------------------------------------------------------------
_import_lock = _threading.Lock()
_Fetcher = None
_DynamicFetcher = None
_StealthyFetcher = None
_all_fetchers_imported = False


def _get_fetcher_class():
    """Return the basic Scrapling Fetcher class (curl-cffi)."""
    global _Fetcher
    if _Fetcher is not None:
        return _Fetcher
    with _import_lock:
        if _Fetcher is not None:
            return _Fetcher
        from scrapling.fetchers import Fetcher as _F
        _Fetcher = _F
        return _Fetcher


def _get_all_fetcher_classes():
    """Return (Fetcher, DynamicFetcher, StealthyFetcher), lazy-imported once."""
    global _Fetcher, _DynamicFetcher, _StealthyFetcher, _all_fetchers_imported
    if _all_fetchers_imported:
        return _Fetcher, _DynamicFetcher, _StealthyFetcher
    with _import_lock:
        if _all_fetchers_imported:
            return _Fetcher, _DynamicFetcher, _StealthyFetcher
        from scrapling.fetchers import DynamicFetcher as _DF, Fetcher as _F, StealthyFetcher as _SF
        _Fetcher = _F
        _DynamicFetcher = _DF
        _StealthyFetcher = _SF
        _all_fetchers_imported = True
        return _F, _DF, _SF


def _fetch_with_named_fetcher(url: str, fetcher: str, timeout_seconds: int) -> FetchResult:
    Fetcher, DynamicFetcher, StealthyFetcher = _get_all_fetcher_classes()

    timeout_ms = timeout_seconds * 1000
    if fetcher == "stealthy":
        page = _call_fetcher(
            StealthyFetcher,
            ("fetch", "get"),
            url,
            headless=True,
            network_idle=True,
            solve_cloudflare=True,
            timeout=timeout_ms,
        )
    elif fetcher == "dynamic":
        page = _call_fetcher(
            DynamicFetcher,
            ("fetch", "get"),
            url,
            headless=True,
            network_idle=True,
            timeout=timeout_ms,
        )
    else:
        page = _call_fetcher(Fetcher, ("get", "fetch"), url, timeout=timeout_seconds)
    return FetchResult(url=url, html=_page_to_html(page))


def fetch_html(url: str, *, fetcher: str = "auto", timeout_seconds: int = 10) -> FetchResult:
    """Fetch HTML through Scrapling when installed.

    Scrapling is optional because the main project still supports Python 3.9.
    Import errors are surfaced as a structured unavailable result.

    Fetcher selection:
      - "auto" / "fetcher": basic Fetcher only (curl-cffi, fast)
      - "dynamic": DynamicFetcher (headless browser, for JS-heavy pages)
      - "stealthy": StealthyFetcher (headless + Cloudflare solving, for protected pages)
    "auto" no longer escalates through all three — headless browsers are too
    expensive to try speculatively.  Use an explicit fetcher name when needed.
    """
    fetcher = (fetcher or "auto").strip().lower()
    if fetcher == "auto":
        fetcher = "fetcher"
    fetchers = (fetcher,)
    errors: list[str] = []

    try:
        for name in fetchers:
            try:
                result = _fetch_with_named_fetcher(url, name, timeout_seconds)
            except ImportError:
                raise
            except Exception as exc:
                errors.append(f"{name}: {str(exc)[:120]}")
                continue

            if result.status != "ok":
                errors.append(f"{name}: {result.error[:120]}")
                continue

            if result.html and (name == fetchers[-1] or not _looks_blocked(result.html)):
                return result
            errors.append(f"{name}: blocked or verification page")

        return FetchResult(
            url=url,
            html="",
            status="failed",
            error="; ".join(errors)[-200:],
        )
    except ImportError as exc:
        return FetchResult(
            url=url,
            html="",
            status="unavailable",
            error=(
                f"{exc}. Scrapling is optional and requires Python >=3.10; "
                f"current Python is {_sys.version_info.major}.{_sys.version_info.minor}. "
                "Install with: python3.12 -m pip install -r requirements-scrapling.txt "
                "and restart Flask with python3.12."
            ),
        )
    except Exception as exc:
        return FetchResult(url=url, html="", status="failed", error=str(exc)[:200])
