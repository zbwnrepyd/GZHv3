import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP = os.path.join(ROOT, "webapp")
if WEBAPP not in sys.path:
    sys.path.insert(0, WEBAPP)


class _FakeResp:
    """模拟 requests.get 返回值，包含可检测的技术栈特征。"""
    status_code = 200
    headers = {
        "Content-Type": "text/html; charset=UTF-8",
        "Server": "nginx",
        "X-Powered-By": "Express",
        "cf-ray": "abc123",
    }
    text = (
        "<html><head>"
        '<script src="/assets/react-18.2.0.js"></script>'
        '<link href="/css/tailwind-3.4.css" rel="stylesheet">'
        "</head><body></body></html>"
    )


def test_whatweb_adapter_maps_text_output(monkeypatch):
    from research.adapters.whatweb_adapter import WhatWebAdapter
    import research.adapters.whatweb_adapter as module

    monkeypatch.setattr(module.requests, "get", lambda url, headers, timeout, allow_redirects: _FakeResp())

    docs = WhatWebAdapter().collect(
        {"display_name": "Example", "website_host": "example.com"},
        ["product_tech_stack"],
        {"timeout_seconds": 5},
    )

    assert len(docs) == 1
    assert docs[0].source_family == "whatweb"
    # Server→"Server", X-Powered-By→"X-Powered-By", cf-ray→"Cloudflare",
    # react.js→"React", tailwind.css→"Tailwind CSS"
    assert "React" in docs[0].content
    assert "Cloudflare" in docs[0].content
    assert docs[0].metadata["detected_count"] >= 3


def test_whatweb_adapter_returns_empty_when_url_unreachable(monkeypatch):
    from research.adapters.whatweb_adapter import WhatWebAdapter
    import research.adapters.whatweb_adapter as module

    def fake_get(url, headers, timeout, allow_redirects):
        raise Exception("Connection refused")

    monkeypatch.setattr(module.requests, "get", fake_get)

    docs = WhatWebAdapter().collect(
        {"display_name": "Example", "website_host": "example.com"},
        ["product_tech_stack"],
        {"timeout_seconds": 5},
    )

    assert docs == []


def test_whatweb_chunks_are_ranked_as_technical_profile():
    from research.context.document_chunker import chunk_document
    from research.context.evidence_ranker import score_chunks_batch

    chunks = chunk_document(
        {
            "id": 1,
            "source_type": "whatweb",
            "source_url": "https://example.com",
            "title": "WhatWeb Technology Profile",
            "raw_text": (
                "WhatWeb technology profile for Example:\n"
                "- HTTPServer[nginx]\n"
                "- JavaScript\n"
                "- JQuery[3.7.1]\n"
                "- Cloudflare\n"
            ) * 8,
        },
        "example",
    )
    scored = score_chunks_batch(
        chunks,
        {"display_name": "Example", "website_host": "example.com", "aliases": []},
    )

    assert scored
    assert scored[0]["chunk_type"] == "tech_profile"
    assert scored[0]["source_score"] >= 0.7
    assert scored[0]["is_noise"] == 0


def test_build_evidence_pool_keeps_adapter_docs():
    import pipeline
    from research.source_adapter import SourceDocument

    raw = {
        "company_name": "Example",
        "display_name": "Example",
        "website_host": "example.com",
        "_adapter_docs": [
            SourceDocument(
                source_family="whatweb",
                source_url="https://example.com",
                title="WhatWeb Technology Profile",
                content="WhatWeb technology profile for Example:\n- HTTPServer[nginx]\n- JavaScript\n- Cloudflare",
                raw_text="WhatWeb technology profile for Example:\n- HTTPServer[nginx]\n- JavaScript\n- Cloudflare",
                intent="tech_stack",
                source_score=0.72,
                entity_score=0.9,
            )
        ],
    }

    pool = pipeline._build_evidence_pool(raw)

    assert any(item.source == "whatweb" for item in pool)
    assert any("Cloudflare" in item.content for item in pool)
