#!/usr/bin/env python3
"""Asset coverage check — Goal 四 PR11.

Checks that all asset_keys in a RenderContract are registered and have valid statuses.

CLI: python3 scripts/asset_coverage_check.py --company <name> --set v3
Output: { ok, company, card_set, summary, failures }
"""

from __future__ import annotations
import argparse, json, os, sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, '..', 'webapp'))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, '..'))

from webapp.services.render_assembler import RenderAssembler


def _load_asset_registry() -> dict:
    """Load the asset key registry from contracts/asset_keys.json."""
    registry_path = os.path.join(
        os.path.dirname(__file__), '..', 'contracts', 'asset_keys.json'
    )
    with open(registry_path, 'r') as f:
        return json.load(f)


REQUIRED_ASSETS = {'logo'}


def check_asset_coverage(company: str, card_set: str = 'v3') -> dict:
    """Run asset coverage check.

    Returns: { ok, company, card_set, summary, failures }
    """
    registry = _load_asset_registry()
    assembler = RenderAssembler()
    contract = assembler.assemble(company, card_set)
    cards = contract.get('cards', [])
    failures = []
    assets_checked = 0
    assets_ready = 0
    assets_fallback = 0
    assets_missing = 0

    for card in cards:
        card_id = card.get('card_id', '?')
        for m in card.get('media', []):
            asset_key = m.get('asset_key', '?')
            assets_checked += 1

            # Check 1: Registered in asset_keys.json
            if asset_key not in registry:
                failures.append({
                    'card_id': card_id,
                    'asset_key': asset_key,
                    'issue': 'unregistered_asset_key',
                    'detail': f"Asset key '{asset_key}' not found in contracts/asset_keys.json",
                })
                continue

            asset_status = m.get('status', '?')

            # Check 2: Required assets must be ready
            if asset_key in REQUIRED_ASSETS:
                if asset_status == 'ready':
                    assets_ready += 1
                else:
                    failures.append({
                        'card_id': card_id,
                        'asset_key': asset_key,
                        'issue': 'required_asset_not_ready',
                        'detail': f"Required asset '{asset_key}' has status '{asset_status}', expected 'ready'",
                    })
                    assets_missing += 1
            else:
                # Check 3: Optional assets with fallback are allowed
                if asset_status == 'ready':
                    assets_ready += 1
                elif asset_status == 'fallback':
                    assets_fallback += 1
                elif asset_status in ('manual_needed', 'unavailable'):
                    assets_missing += 1

    ok = len(failures) == 0
    return {
        'ok': ok,
        'company': company,
        'card_set': card_set,
        'summary': {
            'assets_checked': assets_checked,
            'assets_ready': assets_ready,
            'assets_fallback': assets_fallback,
            'assets_missing': assets_missing,
        },
        'failures': failures,
    }


def main():
    parser = argparse.ArgumentParser(description='Check asset coverage')
    parser.add_argument('--company', required=True, help='Company name')
    parser.add_argument('--set', default='v3', help='Card set key (default: v3)')
    parser.add_argument('--output', help='Output JSON file path')
    args = parser.parse_args()

    result = check_asset_coverage(args.company, getattr(args, 'set'))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        import pathlib
        pathlib.Path(args.output).write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
