from __future__ import annotations
import os, sys, abc

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

# Load .env into os.environ so urllib picks up HTTP_PROXY/HTTPS_PROXY
_ENV_PATH = os.path.join(_PROJECT_ROOT, '.env')
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                _k = _k.strip()
                _v = _v.strip().strip('"').strip("'")
                if _k not in os.environ:
                    os.environ[_k] = _v

from research.source_adapter import SourceDocument


class MarketCollector(abc.ABC):
    """采集器基类 — 匹配 SourceAdapter 模式：原子、不抛异常、失败返回 []。"""
    source_name: str = ""
    source_type: str = ""  # structured | filing | web_search | investor_report | estimation

    @abc.abstractmethod
    def collect(self, company: dict) -> list[SourceDocument]:
        """采集证据文档。任何失败返回 [] — 不抛异常。"""
        ...

    def _load_api_key(self, env_var: str) -> str | None:
        key = os.environ.get(env_var)
        if key:
            return key
        env_path = os.path.join(_PROJECT_ROOT, '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f'{env_var}='):
                        return line.split('=', 1)[1].strip().strip('"').strip("'")
        return None

    def _make_doc(
        self, url: str, title: str, content: str, *,
        intent: str = "", trust_tier: str = "medium",
        source_score: float = 0.5, entity_score: float = 0.7,
        metadata: dict | None = None,
    ) -> SourceDocument:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return SourceDocument(
            source_family=self.source_name,
            source_url=url,
            title=title or "",
            content=content[:50000] if content else "",
            raw_text=content or "",
            intent=intent or self.source_type,
            trust_tier=trust_tier,
            source_score=source_score,
            entity_score=entity_score,
            metadata=metadata or {},
            fetched_at=now,
        )
