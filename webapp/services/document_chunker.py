"""Document Chunker — splits large documents into token-aware chunks (Goal 三)."""

import uuid


# Approximate: 1 token ≈ 4 characters for English, 1.5 for CJK
_CHARS_PER_TOKEN_EN = 4
_CHARS_PER_TOKEN_CJK = 1.5
_DEFAULT_CHUNK_TOKENS = 2000


def _estimate_tokens(text: str) -> int:
    """Rough token count estimation."""
    if not text:
        return 0
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
    en = len(text) - cjk
    return int(en / _CHARS_PER_TOKEN_EN + cjk / _CHARS_PER_TOKEN_CJK)


def chunk(text: str, company_id: str = "", document_id: str = "",
          target_chunk_tokens: int = _DEFAULT_CHUNK_TOKENS) -> list[dict]:
    """Split text into chunks of approximately target_chunk_tokens tokens each.

    Returns list of dicts with: chunk_id, document_id, company_id, chunk_text,
    token_count, chunk_order, section_title.
    """
    if not text:
        return []

    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = []
    current_tokens = 0
    order = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_tokens = _estimate_tokens(para)

        if current_tokens + para_tokens > target_chunk_tokens and current_chunk:
            # Finalize current chunk
            chunks.append(_make_chunk(
                company_id, document_id, '\n\n'.join(current_chunk),
                current_tokens, order
            ))
            order += 1
            current_chunk = [para]
            current_tokens = para_tokens
        else:
            current_chunk.append(para)
            current_tokens += para_tokens

    if current_chunk:
        chunks.append(_make_chunk(
            company_id, document_id, '\n\n'.join(current_chunk),
            current_tokens, order
        ))

    return chunks


def _make_chunk(company_id: str, document_id: str, text: str,
                token_count: int, order: int) -> dict:
    return {
        'chunk_id': str(uuid.uuid4())[:12],
        'document_id': document_id,
        'company_id': company_id,
        'chunk_text': text,
        'token_count': max(token_count, 1),
        'chunk_order': order,
        'section_title': None,
    }
