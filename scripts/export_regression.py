#!/usr/bin/env python3
"""Export regression — Goal 四 PR12.

Runs coverage checks and verifies export pipeline for given companies.

CLI: python3 scripts/export_regression.py --companies Anthropic OpenAI --set v3
Output: { ok, per_company: {...}, failures: [] }
"""

from __future__ import annotations
import argparse, json, os, subprocess, sys, time, uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from webapp.services.render_assembler import RenderAssembler


def _get_enabled_card_count(company: str, card_set: str = 'v3') -> int:
    """Get number of enabled cards from the composition DB or RenderContract."""
    assembler = RenderAssembler()
    contract = assembler.assemble(company, card_set)
    return len(contract.get('cards', []))


def _run_screenshot(company: str, card_set: str = 'v3',
                    base_url: str = 'http://127.0.0.1:5050',
                    output_dir: str = None) -> dict:
    """Run Puppeteer screenshot for a company. Skips if node not available."""
    if output_dir is None:
        output_dir = f'/tmp/gzh_export_{uuid.uuid4().hex[:8]}'

    cmd = [
        'node', 'canvas/screenshot.js',
        '--company', company,
        '--set', card_set,
        '--base-url', base_url,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=os.path.join(os.path.dirname(__file__), '..'),
        )
        return {
            'ok': result.returncode == 0,
            'stdout': result.stdout[:2000],
            'stderr': result.stderr[:2000],
            'returncode': result.returncode,
        }
    except FileNotFoundError:
        return {
            'ok': None,
            'reason': 'node_not_found',
            'detail': 'Node.js not available in this environment',
        }
    except subprocess.TimeoutExpired:
        return {
            'ok': False,
            'reason': 'timeout',
            'detail': 'Screenshot process timed out',
        }


def run_export_regression(companies: list[str], card_set: str = 'v3',
                          base_url: str = 'http://127.0.0.1:5050') -> dict:
    """Run full export regression for a list of companies.

    For each company:
    1. Count enabled cards via RenderAssembler
    2. Run Puppeteer screenshot
    3. Verify output

    Returns: { ok, per_company, failures }
    """
    per_company = {}
    all_failures = []

    for company in companies:
        company_result = {'company': company, 'checks': {}}
        failures = []

        # Step 1: Coverage — card count
        try:
            card_count = _get_enabled_card_count(company, card_set)
            company_result['card_count'] = card_count
            if card_count == 0:
                failures.append({
                    'company': company,
                    'issue': 'zero_cards',
                    'detail': 'No cards assembled for this company',
                })
        except Exception as e:
            failures.append({
                'company': company,
                'issue': 'assembler_error',
                'detail': str(e),
            })
            company_result['card_count'] = 0

        # Step 2: Run Puppeteer screenshot
        screenshot_result = _run_screenshot(company, card_set, base_url)
        company_result['screenshot'] = screenshot_result

        if screenshot_result.get('ok') is False:
            failures.append({
                'company': company,
                'issue': 'screenshot_failed',
                'detail': screenshot_result.get('stderr', '')[:500],
            })
        elif screenshot_result.get('ok') is None:
            # Node not available — not a hard failure for CI/test env
            company_result['screenshot_skipped'] = True

        company_result['ok'] = len(failures) == 0
        company_result['failures'] = failures
        per_company[company] = company_result
        all_failures.extend(failures)

    return {
        'ok': len(all_failures) == 0,
        'card_set': card_set,
        'per_company': per_company,
        'failures': all_failures,
    }


def main():
    parser = argparse.ArgumentParser(description='Export regression check')
    parser.add_argument('--companies', required=True, nargs='+', help='Company names')
    parser.add_argument('--set', default='v3', help='Card set key')
    parser.add_argument('--base-url', default='http://127.0.0.1:5050', help='Flask base URL')
    parser.add_argument('--output', help='Output JSON file path')
    args = parser.parse_args()

    result = run_export_regression(args.companies, getattr(args, 'set'), args.base_url)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        import pathlib
        pathlib.Path(args.output).write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
