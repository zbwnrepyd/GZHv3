from __future__ import annotations
import sys, os, json, re

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from config import config
from ..schemas.candidate import FieldCandidate


class MarketNumberExtractor:
    """Extract numeric market values from text using regex + optionally LLM."""

    PATTERNS = [
        (r'\$\s*([\d,.]+)\s*(billion|b|million|m|trillion|t)\b', 'market_size_value'),
        (r'(?:market|industry|sector)\s+(?:size|value|worth)\s+(?:of\s+)?\$?\s*([\d,.]+)\s*(billion|b|million|m|trillion|t)?', 'market_size_value'),
        (r'(?:TAM|total\s+addressable\s+market)\s+(?:of\s+)?\$?\s*([\d,.]+)\s*(billion|b|million|m|trillion|t)?', 'tam_value'),
        (r'(?:CAGR|compound\s+annual\s+growth\s+rate)\s+(?:of\s+)?([\d,.]+)\s*%', 'market_cagr'),
        (r'(?:raised|funding|investment)\s+(?:of\s+)?\$?\s*([\d,.]+)\s*(billion|b|million|m|trillion|t)?', 'funding_total'),
        (r'(?:revenue|ARR|annual\s+recurring\s+revenue)\s+(?:of\s+)?\$?\s*([\d,.]+)\s*(billion|b|million|m|trillion|t)?', 'revenue_estimate'),
    ]

    UNIT_MULTIPLIERS = {'billion': 1e9, 'b': 1e9, 'million': 1e6, 'm': 1e6, 'trillion': 1e12, 't': 1e12, 'k': 1e3, 'thousand': 1e3}

    def extract(self, text: str, source_url: str = "", source_type: str = "web_search") -> list[FieldCandidate]:
        candidates = []
        text_lower = text.lower()
        for pattern, field_key in self.PATTERNS:
            for match in re.finditer(pattern, text_lower):
                try:
                    num = float(match.group(1).replace(',', ''))
                except (ValueError, IndexError):
                    continue
                unit = match.group(2) if match.lastindex and match.lastindex >= 2 else None
                if unit and unit in self.UNIT_MULTIPLIERS:
                    num *= self.UNIT_MULTIPLIERS[unit]
                start = max(0, match.start() - 40)
                end = min(len(text), match.end() + 80)
                snippet = text[start:end].strip()
                candidates.append(FieldCandidate(
                    field_key=field_key, value=num, value_text=self._fmt(num), currency="USD",
                    source_type=source_type, status="llm_located", confidence=0.3,
                    source_url=source_url, segment=snippet[:120],
                ))
        return candidates

    def _fmt(self, v: float) -> str:
        if v >= 1e12: return f"${v/1e12:.1f}T"
        if v >= 1e9:  return f"${v/1e9:.1f}B"
        if v >= 1e6:  return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"

    def extract_with_llm(self, text: str, max_chars: int = 12000, source_url: str = "", source_type: str = "web_search") -> list[FieldCandidate]:
        trimmed = text[:max_chars]
        if len(trimmed) < 200:
            return self.extract(trimmed, source_url, source_type)
        prompt_path = os.path.join(_PROJECT_ROOT, 'market_intelligence', 'prompts', 'market_extract.md')
        system_prompt = open(prompt_path).read() if os.path.exists(prompt_path) else ""
        try:
            from deepseek_client import call_deepseek
            response = call_deepseek(config.DEEPSEEK_API_KEY, system_prompt, f"从以下文本中提取市场相关数字：\n\n{trimmed}", temperature=0.1, max_tokens=2048, timeout=60, max_retries=2)
            return self._parse_llm_response(response, source_url, source_type)
        except Exception as e:
            print(f"[market_number] LLM failed: {e}", file=sys.stderr)
            return self.extract(trimmed, source_url, source_type)

    def _parse_llm_response(self, response: str, source_url: str, source_type: str) -> list[FieldCandidate]:
        try:
            js = response.find('{'); je = response.rfind('}') + 1
            data = json.loads(response[js:je]) if js >= 0 and je > js else {}
        except json.JSONDecodeError:
            return []
        if not data.get("found"): return []
        candidates = []
        for ext in data.get("extractions", []):
            val = ext.get("value")
            if val is None: continue
            unit = ext.get("unit", "")
            if unit and unit.lower() in self.UNIT_MULTIPLIERS:
                val *= self.UNIT_MULTIPLIERS[unit.lower()]
            candidates.append(FieldCandidate(
                field_key=ext.get("field", "market_size_value"), value=val,
                value_text=f"${val/1e9:.1f}B" if val >= 1e9 else f"${val/1e6:.1f}M",
                currency=ext.get("currency", "USD"), year=ext.get("year"),
                source_type=source_type, source_url=source_url, status="llm_located",
                confidence=ext.get("confidence", 0.35), segment=ext.get("scope", ""),
            ))
        return candidates
