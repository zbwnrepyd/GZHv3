"""Context Ranker — scores chunks for relevance to a company (Goal 三).

Company-specific content scores higher than generic industry content.
"""

import re


def rank(chunks: list[dict], company_id: str = "") -> list[dict]:
    """Score and reorder chunks by relevance to the given company.

    Scoring factors:
    - Company name mentions (+30)
    - Product/brand terms (+20)
    - Contains financial figures (+10)
    - Generic penalty for purely industry-level text (-5)

    Returns chunks with an added 'score' field (0-100 scale).
    """
    scored = []
    for ch in chunks:
        text = ch.get('chunk_text', '')
        score = _score_chunk(text, company_id)
        ch_with_score = dict(ch)
        ch_with_score['score'] = score
        scored.append(ch_with_score)

    # Sort by score descending
    scored.sort(key=lambda c: c['score'], reverse=True)
    return scored


def _score_chunk(text: str, company_id: str = "") -> float:
    """Score a single chunk's relevance (0-100)."""
    if not text:
        return 0.0

    score = 50.0  # baseline

    # Company name mentions
    if company_id:
        # Check for company name (case-insensitive)
        name_hits = len(re.findall(re.escape(company_id), text, re.IGNORECASE))
        score += min(name_hits * 15, 30)

        # Check for domain mentions
        domain = company_id.replace('-', '').replace('_', '')
        if len(domain) > 3:
            domain_hits = len(re.findall(re.escape(domain), text, re.IGNORECASE))
            score += min(domain_hits * 5, 10)

    # Product/brand signals
    product_signals = ['product', 'feature', 'launch', 'release', 'announce',
                       'pricing', 'subscription', 'enterprise', 'customer']
    for signal in product_signals:
        if signal in text.lower():
            score += 2

    # Financial figures
    money_pattern = r'\$[\d,.]+[BMK]?|\d+%\s*(growth|revenue|margin|ARR|MRR)'
    if re.search(money_pattern, text, re.IGNORECASE):
        score += 10

    # Generic industry content penalty
    generic_signals = ['industry trends', 'market is expected', 'according to analysts',
                       'the industry has seen', 'many companies in this space']
    generic_count = sum(1 for s in generic_signals if s in text.lower())
    score -= generic_count * 3

    return max(0.0, min(100.0, score))
