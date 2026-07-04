#!/usr/bin/env python3
"""Card content coverage check — Goal 四 PR11.

Checks that every card in a RenderContract has complete, renderable content.

CLI: python3 scripts/card_content_coverage_check.py --company <name> --set v3
Output: { ok, company, card_set, summary, failures }
"""

from __future__ import annotations
import argparse, json, os, sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, '..', 'webapp'))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, '..'))

from webapp.services.render_assembler import RenderAssembler


PLACEHOLDER_VALUES = {'', '暂缺', '待研究数据', 'None', 'none', 'null', 'NULL', '[]', '{}'}
MIN_VALUE_COVERAGE_RATIO = 0.85


def _has_renderable_value(value) -> bool:
    if value is None:
        return False
    return str(value).strip() not in PLACEHOLDER_VALUES


def check_card_coverage(company: str, card_set: str = 'v3') -> dict:
    """Run coverage check against a company's RenderContract.

    Returns: { ok, company, card_set, summary, failures }
    """
    assembler = RenderAssembler()
    contract = assembler.assemble(company, card_set)
    cards = contract.get('cards', [])
    failures = []
    cards_with_items = 0
    total_fields = 0
    fields_resolved = 0
    fields_with_values = 0
    cards_with_layout = 0

    for card in cards:
        card_id = card.get('card_id', '?')
        items = card.get('items', [])
        media = card.get('media', [])
        layout = card.get('layout', {})

        # Check 1: Has at least 1 item
        if len(items) == 0:
            failures.append({
                'card_id': card_id,
                'issue': 'no_items',
                'detail': 'Card has zero items',
            })
        else:
            cards_with_items += 1

        # Check 2: Every field_key has a resolvable status
        for item in items:
            total_fields += 1
            fk = item.get('field_key', '?')
            status = item.get('status', 'draft')
            if _has_renderable_value(item.get('value')):
                fields_with_values += 1
            if status in ('confirmed', 'derived', 'proxy', 'industry_avg', 'llm_extracted', 'manual_needed'):
                fields_resolved += 1
            elif status in ('unavailable', 'not_applicable'):
                pass  # Legitimately unavailable — not a failure
            else:
                failures.append({
                    'card_id': card_id,
                    'field_key': fk,
                    'issue': 'unresolvable_field',
                    'detail': f"Status '{status}' is not a renderable state",
                })

        # Check 3: Required media keys have a status
        for m in media:
            asset_key = m.get('asset_key', '?')
            asset_status = m.get('status', '?')
            if asset_status not in ('ready', 'fallback', 'manual_needed', 'unavailable', 'not_applicable'):
                failures.append({
                    'card_id': card_id,
                    'asset_key': asset_key,
                    'issue': 'invalid_media_status',
                    'detail': f"Media status '{asset_status}' is not valid",
                })

        # Check 4: Layout has template_id and variant
        if layout.get('template_id') and layout.get('variant'):
            cards_with_layout += 1
        else:
            failures.append({
                'card_id': card_id,
                'issue': 'incomplete_layout',
                'detail': 'Layout missing template_id or variant',
            })

    value_coverage_ratio = round(fields_with_values / total_fields, 4) if total_fields else 0.0
    if total_fields and value_coverage_ratio < MIN_VALUE_COVERAGE_RATIO:
        failures.append({
            'issue': 'low_value_coverage',
            'detail': f"Value coverage {value_coverage_ratio:.1%} is below {MIN_VALUE_COVERAGE_RATIO:.0%}",
        })

    ok = len(failures) == 0 and len(cards) > 0
    return {
        'ok': ok,
        'company': company,
        'card_set': card_set,
        'summary': {
            'cards_total': len(cards),
            'cards_with_items': cards_with_items,
            'total_fields': total_fields,
            'fields_resolved': fields_resolved,
            'fields_with_values': fields_with_values,
            'value_coverage_ratio': value_coverage_ratio,
            'cards_with_complete_layout': cards_with_layout,
        },
        'failures': failures,
    }


def main():
    parser = argparse.ArgumentParser(description='Check card content coverage')
    parser.add_argument('--company', required=True, help='Company name')
    parser.add_argument('--set', default='v3', help='Card set key (default: v3)')
    parser.add_argument('--output', help='Output JSON file path')
    args = parser.parse_args()

    result = check_card_coverage(args.company, getattr(args, 'set'))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        import pathlib
        pathlib.Path(args.output).write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
