from __future__ import annotations
import sys, os, json

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from config import config


def extract_tam_params(docs: list, category: str = "") -> dict:
    """Use LLM to extract bottom-up TAM parameters from evidence documents.
    Returns dict with keys: total_users, penetration_rate, arpu, region, segment, year, explanation, source_urls, confidence.
    Returns empty dict on failure — caller handles unavailable status.
    """
    combined = "\n\n---\n\n".join(
        f"[{getattr(d, 'source_url', '?')}]\n{getattr(d, 'content', '')[:3000]}"
        for d in docs[:6]
    )
    if len(combined) < 200:
        return {}

    prompt_path = os.path.join(_PROJECT_ROOT, 'market_intelligence', 'prompts', 'parameter_extract.md')
    system_prompt = open(prompt_path).read() if os.path.exists(prompt_path) else "Extract TAM parameters from text."
    user_msg = f"Company category: {category}\n\nEvidence:\n{combined[:12000]}"

    try:
        from deepseek_client import call_deepseek
        response = call_deepseek(config.DEEPSEEK_API_KEY, system_prompt, user_msg, temperature=0.1, max_tokens=2048, timeout=60, max_retries=2)
    except Exception as e:
        print(f"[parameter_extractor] LLM failed: {e}", file=sys.stderr)
        return {}

    try:
        js = response.find('{'); je = response.rfind('}') + 1
        data = json.loads(response[js:je]) if js >= 0 and je > js else {}
    except json.JSONDecodeError:
        return {}

    if not data.get("found"):
        return {}

    params = data.get("parameters", {})
    users = (params.get("total_addressable_users") or {}).get("value")
    pen = (params.get("penetration_rate") or {}).get("value")
    arpu = (params.get("arpu") or {}).get("value")

    return {
        "total_users": users,
        "penetration_rate": pen,
        "arpu": arpu,
        "region": data.get("region", "全球"),
        "segment": data.get("segment", category),
        "year": data.get("year"),
        "explanation": data.get("explanation", ""),
        "source_urls": [],
        "confidence": min(
            (params.get("total_addressable_users") or {}).get("confidence", 0.5),
            (params.get("penetration_rate") or {}).get("confidence", 0.5),
            (params.get("arpu") or {}).get("confidence", 0.5),
        ),
    }
