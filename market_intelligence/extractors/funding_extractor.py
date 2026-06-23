from __future__ import annotations
import sys, os, re
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from ..schemas.candidate import FieldCandidate


class FundingExtractor:

    DATE_PATTERNS = [
        (r'(\d{4})-(\d{2})-(\d{2})', '%Y-%m-%d'),
        (r'(\d{4})年(\d{1,2})月(\d{1,2})日', '%Y-%m-%d'),
        (r'(\d{4})\.(\d{1,2})\.(\d{1,2})', '%Y.%m.%d'),
        (r'([A-Z][a-z]{2,8})\s+(\d{1,2}),?\s+(\d{4})', '%B %d %Y'),
    ]

    def extract_funding_total(self, docs: list, crunchbase_total: float | None = None) -> list[FieldCandidate]:
        candidates = []
        if crunchbase_total is not None and crunchbase_total > 0:
            candidates.append(FieldCandidate(field_key="funding_total", value=crunchbase_total, value_text=f"${crunchbase_total/1e6:.1f}M" if crunchbase_total < 1e9 else f"${crunchbase_total/1e9:.1f}B", currency="USD", source_type="structured", status="derived", confidence=0.85, source_url="https://www.crunchbase.com"))
        for doc in docs:
            content = getattr(doc, 'content', '') or ''
            if not content: continue
            for match in re.findall(r'(?:total\s+funding|raised|融资总额).*?\$?\s*([\d,.]+)\s*(billion|b|million|m)?', content.lower()):
                try:
                    num = float(match[0].replace(',', ''))
                    unit = match[1] if len(match) > 1 else None
                    if unit in ('billion', 'b'): num *= 1e9
                    elif unit in ('million', 'm'): num *= 1e6
                    candidates.append(FieldCandidate(field_key="funding_total", value=num, value_text=f"${num/1e6:.1f}M" if num < 1e9 else f"${num/1e9:.1f}B", currency="USD", source_type=getattr(doc, 'source_family', 'web_search'), status="llm_located", confidence=0.35, source_url=getattr(doc, 'source_url', '')))
                except (ValueError, IndexError): continue
        return candidates

    def extract_funding_rounds(self, docs: list) -> list[FieldCandidate]:
        for doc in docs:
            content = getattr(doc, 'content', '') or ''
            if 'Round 1:' in content or 'Round 2:' in content:
                count = content.count('Round ')
                return [FieldCandidate(field_key="funding_rounds", value=count, value_text=str(count), source_type="structured", status="derived", confidence=0.8, source_url=getattr(doc, 'source_url', ''))]
        return []

    def extract_last_funding_date(self, docs: list) -> list[FieldCandidate]:
        latest = None; latest_src = ""
        for doc in docs:
            content = getattr(doc, 'content', '') or ''
            for pat, fmt in self.DATE_PATTERNS:
                for m in re.findall(pat, content):
                    try:
                        ds = f"{m[0]}-{m[1].zfill(2) if len(m)>1 else '01'}-{m[2].zfill(2) if len(m)>2 else '01'}"
                        d = datetime.strptime(ds, '%Y-%m-%d')
                        if latest is None or d > latest: latest = d; latest_src = getattr(doc, 'source_url', '')
                    except (ValueError, IndexError): continue
        if latest:
            return [FieldCandidate(field_key="last_funding_date", value=latest.strftime('%Y-%m-%d'), value_text=latest.strftime('%Y-%m-%d'), year=latest.year, source_type="structured", status="derived", confidence=0.7, source_url=latest_src)]
        return []

    def extract_all(self, docs: list, crunchbase_total: float | None = None) -> dict[str, list[FieldCandidate]]:
        return {"funding_total": self.extract_funding_total(docs, crunchbase_total), "funding_rounds": self.extract_funding_rounds(docs), "last_funding_date": self.extract_last_funding_date(docs)}
