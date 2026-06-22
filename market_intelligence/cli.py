from __future__ import annotations
import argparse, json, sys, os, time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEBAPP = os.path.join(_PROJECT_ROOT, 'webapp')
if _WEBAPP not in sys.path:
    sys.path.insert(0, _WEBAPP)

from .schemas.candidate import FieldCandidate

ALL_FIELDS = [
    "market_size_value", "market_size_currency", "market_size_year",
    "market_cagr", "tam_value", "funding_total", "funding_rounds",
    "last_funding_date", "revenue_estimate", "arr_range",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m market_intelligence", description="Market Intelligence — 市场情报模块：结构化采集→提取→估算→解析")
    p.add_argument("--company", required=True, help="公司名 (e.g. 'Cursor')")
    p.add_argument("--domain", required=True, help="公司域名 (e.g. 'cursor.com')")
    p.add_argument("--category", default="", help="公司品类 (e.g. 'AI coding assistant')")
    p.add_argument("--output", "-o", help="输出 JSON 文件路径")
    p.add_argument("--fields", help=f"逗号分隔字段 (默认全部 {len(ALL_FIELDS)} 个)")
    p.add_argument("--verbose", "-v", action="store_true", help="显示证据链")
    p.add_argument("--no-crunchbase", action="store_true", help="跳过 Crunchbase")
    p.add_argument("--no-web", action="store_true", help="跳过网页搜索")
    p.add_argument("--timeout", type=int, default=120, help="总超时秒数 (默认120)")
    return p


def run(args: argparse.Namespace) -> dict:
    company = {
        "display_name": args.company,
        "company_name": args.company,
        "domain": args.domain,
        "website_host": args.domain,
        "category": args.category,
        "company_key": args.domain.replace(".", "_"),
    }
    fields = [f.strip() for f in args.fields.split(",")] if args.fields else ALL_FIELDS

    t0 = time.time()
    all_docs = []
    evidence_meta = []

    # ── Phase 1: Collect ──
    collectors = []

    if not args.no_crunchbase:
        from .collectors.crunchbase import CrunchbaseCollector
        collectors.append(("crunchbase", CrunchbaseCollector()))

    if not args.no_web:
        from .collectors.tavily_market import TavilyMarketCollector
        collectors.append(("tavily_market", TavilyMarketCollector()))

    for cname, collector in collectors:
        try:
            docs = collector.collect(company)
            all_docs.extend(docs)
            evidence_meta.append({"source": cname, "docs": len(docs)})
            if args.verbose:
                print(f"[collect] {cname}: {len(docs)} docs", file=sys.stderr)
        except Exception as e:
            print(f"[collect] {cname} error: {e}", file=sys.stderr)

    if args.verbose:
        print(f"[collect] total: {len(all_docs)} docs ({time.time()-t0:.1f}s)", file=sys.stderr)

    # ── Phase 2: Extract ──
    from .extractors.market_number import MarketNumberExtractor

    candidates_by_field: dict[str, list[FieldCandidate]] = {f: [] for f in fields}
    extractor = MarketNumberExtractor()

    # Extract Crunchbase total_funding for special handling
    cb_total = None
    for doc in all_docs:
        meta = getattr(doc, 'metadata', {}) or {}
        tf = meta.get("crunchbase_data", {}).get("total_funding")
        if tf is not None:
            try:
                cb_total = float(tf)
            except (ValueError, TypeError):
                pass
            break

    for doc in all_docs:
        content = getattr(doc, 'content', '') or ''
        if len(content) < 100:
            continue
        url = getattr(doc, 'source_url', '')
        sf = getattr(doc, 'source_family', 'web_search')
        cands = extractor.extract(content, url, sf)
        for c in cands:
            if c.field_key in candidates_by_field:
                candidates_by_field[c.field_key].append(c)

    # ── Phase 3: Estimate ──
    from .estimators.bottom_up_tam import compute_bottom_up_tam
    from .estimators.comparable_market import estimate_from_comparables
    from .estimators.funding_calculator import compute_funding

    company_key = company["company_key"]
    category = company.get("category", "")

    # TAM via bottom-up
    tam_candidate = compute_bottom_up_tam(company_key, all_docs, category)
    candidates_by_field["tam_value"].append(tam_candidate)

    # Market size via comparables
    ms_candidate = estimate_from_comparables(all_docs, "market_size_value")
    candidates_by_field["market_size_value"].append(ms_candidate)

    # Funding fields
    funding_fields = compute_funding(company_key, all_docs, cb_total)
    for fk, fc in funding_fields.items():
        if isinstance(fc, list):
            candidates_by_field[fk].extend(fc)
        elif fk in candidates_by_field:
            candidates_by_field[fk].append(fc)

    # ── Phase 4: Resolve ──
    from .resolvers.field_resolver import MarketFieldResolver
    from .resolvers.confidence import ConfidenceScorer

    resolver = MarketFieldResolver()
    scorer = ConfidenceScorer()
    resolved = resolver.resolve(candidates_by_field)

    # ── Phase 5: Output ──
    output = {
        "company": args.company,
        "domain": args.domain,
        "category": args.category,
        "elapsed_s": round(time.time() - t0, 1),
        "evidence_summary": evidence_meta,
        "total_documents": len(all_docs),
        "fields": {},
    }

    for field_key, candidate in resolved.items():
        is_direct = candidate.source_type in ("structured", "filing")
        final_confidence = scorer.score(candidate, len(candidate.evidence_ids))
        final_status = scorer.map_to_status(final_confidence, is_direct)
        confidence_level = scorer.map_to_confidence_level(
            candidate, num_evidence=len(candidate.evidence_ids), is_direct=is_direct
        )

        entry = candidate.to_dict()
        entry["status"] = final_status
        entry["confidence"] = final_confidence
        entry["confidence_level"] = confidence_level

        if args.verbose and candidate.evidence_ids:
            entry["_evidence"] = [
                {
                    "url": getattr(d, 'source_url', '?'),
                    "title": getattr(d, 'title', ''),
                    "source_family": getattr(d, 'source_family', ''),
                    "snippet": getattr(d, 'content', '')[:200],
                }
                for d in all_docs[:10]  # first 10 docs as evidence
            ]

        output["fields"][field_key] = entry

    return output


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = run(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        import pathlib
        pathlib.Path(args.output).write_text(text + "\n", encoding='utf-8')
        print(f"Written to {args.output}")
    else:
        print(text)

    # Check: did we get any usable data?
    usable = sum(1 for f in result.get("fields", {}).values() if f.get("value") is not None and f.get("status") not in ("unavailable", "not_applicable"))
    total = len(result.get("fields", {}))
    print(f"\n{usable}/{total} fields have usable data", file=sys.stderr)
    return 0 if usable > 0 else 1
