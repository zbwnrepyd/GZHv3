"""RenderAssembler — assembles RenderContract from multiple databases.

Priority: final layer > research layer
Missing fields → status: manual_needed or unavailable
Missing media → status: fallback or manual_needed
Never raises exception on missing data.
"""

import json
import os
import sys
import sqlite3
from pathlib import Path
from typing import Optional

# Allow importing from research/ sub-package
_WEBAPP = Path(__file__).resolve().parent.parent
if str(_WEBAPP) not in sys.path:
    sys.path.insert(0, str(_WEBAPP))

# Private/operational metrics that default to 'unavailable' when no data exists
_PRIVATE_METRIC_FIELDS = {
    'ltv', 'cac', 'ltv_cac_ratio', 'retention_rate', 'churn_rate',
    'arr', 'mrr', 'gross_margin', 'burn_rate', 'runway_months',
    'paying_users', 'active_users', 'registered_users', 'mau',
    'company_revenue', 'company_profit', 'revenue_metrics', 'growth_metrics',
}


_PLACEHOLDER_VALUES = {'', '暂缺', 'None', 'none', 'null', 'NULL', '[]', '{}'}


# Status → confidence_level mapping
_STATUS_TO_CONFIDENCE_LEVEL = {
    "confirmed": "verified",
    "derived": "estimated",
    "proxy": "estimated",
    "industry_avg": "benchmark",
    "llm_extracted": "estimated",
    "llm_located": "estimated",
    "manual_needed": "unavailable",
    "unavailable": "unavailable",
    "not_applicable": "unavailable",
    "conflict": "estimated",
    "draft": "unavailable",
    "hidden": "unavailable",
}


def _map_status_to_confidence_level(status: str, is_private: bool = False) -> str:
    """Map internal resolution status to user-facing confidence_level.

    Private metrics with no real data default to benchmark/unavailable.
    """
    if not status:
        return "unavailable"
    mapped = _STATUS_TO_CONFIDENCE_LEVEL.get(status, "unavailable")
    # Private metric industry_avg → benchmark (correct)
    # Private metric llm_extracted with no evidence → estimated (could be wrong, but ok for UX)
    return mapped


def _is_usable_value(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return text not in _PLACEHOLDER_VALUES


def _slugify(name: str) -> str:
    """Simple slug: lowercase, non-alphanumeric → dash."""
    import re
    slug = re.sub(r'[^a-zA-Z0-9一-鿿]+', '-', name.lower()).strip('-')
    return slug or name.lower()


class RenderAssembler:
    """Assembles RenderContract from research, final, assets, and composition DBs."""

    def __init__(
        self,
        research_db_path: str = None,
        final_db_path: str = None,
        assets_db_path: str = None,
        composition_db_path: str = None,
    ):
        # Default paths relative to project root
        _project_root = Path(__file__).resolve().parent.parent.parent
        self._research_db_path = research_db_path or str(_project_root / 'db' / 'research_db.sqlite')
        self._final_db_path = final_db_path or str(_project_root / 'db' / 'final_db.sqlite')
        self._assets_db_path = assets_db_path or str(_project_root / 'db' / 'assets_db.sqlite')
        self._composition_db_path = composition_db_path or str(_project_root / 'db' / 'composition_db.sqlite')

        self._research_conn: Optional[sqlite3.Connection] = None
        self._final_conn: Optional[sqlite3.Connection] = None
        self._assets_conn: Optional[sqlite3.Connection] = None
        self._composition_conn: Optional[sqlite3.Connection] = None

    def _get_research_conn(self) -> sqlite3.Connection:
        if self._research_conn is None:
            self._research_conn = sqlite3.connect(self._research_db_path)
        self._research_conn.row_factory = sqlite3.Row
        return self._research_conn

    def _get_final_conn(self) -> sqlite3.Connection:
        if self._final_conn is None:
            self._final_conn = sqlite3.connect(self._final_db_path)
        self._final_conn.row_factory = sqlite3.Row
        return self._final_conn

    def _get_assets_conn(self) -> sqlite3.Connection:
        if self._assets_conn is None:
            self._assets_conn = sqlite3.connect(self._assets_db_path)
        self._assets_conn.row_factory = sqlite3.Row
        return self._assets_conn

    def _get_composition_conn(self) -> sqlite3.Connection:
        if self._composition_conn is None:
            self._composition_conn = sqlite3.connect(self._composition_db_path)
        self._composition_conn.row_factory = sqlite3.Row
        return self._composition_conn

    # ── public API ──────────────────────────────────────────────

    def assemble(self, company_name: str, card_set: str = 'v3') -> dict:
        """Assemble a full RenderContract for one company and card_set.

        Never raises — returns a contract with warnings on any issue.
        """
        warnings = []
        company_id = _slugify(company_name)

        # Load card definitions
        cards_def = self._load_cards_def(company_name, card_set)

        # Build cards
        cards = []
        for card_def in cards_def:
            try:
                card = self._build_card(company_name, card_def)
                cards.append(card)
            except Exception as e:
                warnings.append(f"Card {card_def.get('card_id', '?')} failed: {e}")

        if not cards:
            warnings.insert(0, f"No cards assembled for company '{company_name}' (set={card_set})")

        return {
            'version': '1.0',
            'company': {
                'company_id': company_id,
                'name': company_name,
                'slug': company_id,
            },
            'card_set': card_set,
            'cards': cards,
            'warnings': warnings,
        }

    # ── internal ────────────────────────────────────────────────

    def _load_cards_def(self, company_name: str, card_set: str) -> list[dict]:
        """Load card definitions from composition DB (card_items), falling back to defaults."""
        comp_conn = self._get_composition_conn()

        # Check if this company has card_items
        cur = comp_conn.execute(
            'SELECT COUNT(*) as cnt FROM card_items WHERE company_name=? AND card_set_key=?',
            (company_name, card_set)
        )
        row = cur.fetchone()
        has_items = row and row['cnt'] > 0

        if has_items:
            return self._load_from_card_items(company_name, card_set)

        # Fallback to default_card_configs
        return self._load_from_defaults(card_set)

    def _load_from_card_items(self, company_name: str, card_set: str) -> list[dict]:
        comp_conn = self._get_composition_conn()
        cur = comp_conn.execute('''
            SELECT cc.card_id, cc.card_title, cc.template_id
            FROM card_compositions cc
            WHERE cc.company_name=? AND cc.card_set_key=? AND cc.enabled=1
            ORDER BY cc.card_index
        ''', (company_name, card_set))
        cards = []
        for row in cur.fetchall():
            card_id = row['card_id']
            # Load items for this card
            items_cur = comp_conn.execute('''
                SELECT item_type, item_key, item_label
                FROM card_items
                WHERE company_name=? AND card_set_key=? AND card_id=? AND enabled=1
                ORDER BY sort_order
            ''', (company_name, card_set, card_id))
            fields = []
            media = []
            for item in items_cur.fetchall():
                if item['item_type'] == 'field':
                    fields.append(item['item_key'])
                elif item['item_type'] == 'media':
                    media.append(item['item_key'])
            cards.append({
                'card_id': card_id,
                'title': row['card_title'],
                'fields': fields,
                'media': media,
                'template_id': row['template_id'] or 'v3_default',
            })
        return cards

    def _load_from_defaults(self, card_set: str) -> list[dict]:
        comp_conn = self._get_composition_conn()
        cur = comp_conn.execute('''
            SELECT card_id, card_title, card_index, config_json
            FROM default_card_configs
            WHERE set_key=?
            ORDER BY card_index
        ''', (card_set,))
        cards = []
        for row in cur.fetchall():
            try:
                config = json.loads(row['config_json'])
            except (json.JSONDecodeError, TypeError):
                config = {}
            cards.append({
                'card_id': row['card_id'],
                'title': row['card_title'],
                'fields': config.get('fields', []),
                'media': config.get('media', []),
                'template_id': config.get('template_id', 'v3_default'),
            })
        return cards

    def _build_card(self, company_name: str, card_def: dict) -> dict:
        """Build one card dict from its definition."""
        card_id = card_def['card_id']
        title = card_def['title']
        fields = card_def.get('fields', [])
        media_keys = card_def.get('media', [])
        template_id = card_def.get('template_id', 'v3_default')

        # Resolve field values
        items = []
        for field_key in fields:
            item = self._resolve_field(company_name, field_key)
            items.append(item)

        # Resolve media
        media = []
        for asset_key in media_keys:
            m = self._resolve_media(company_name, asset_key)
            media.append(m)

        return {
            'card_id': card_id,
            'title': title,
            'items': items,
            'media': media,
            'layout': {
                'template_id': template_id,
                'variant': 'wide',
            },
        }

    def _resolve_field(self, company_name: str, field_key: str) -> dict:
        """Resolve a field value: final > research.

        Returns dict with field_key, label, value, status, confidence, evidence_count, source.
        """
        is_private = field_key in _PRIVATE_METRIC_FIELDS

        # 1. Try final_db final_fields
        final_value = None
        final_status = None
        try:
            final_conn = self._get_final_conn()
            cur = final_conn.execute(
                'SELECT final_value, status FROM final_fields WHERE company_name=? AND field_key=?',
                (company_name, field_key)
            )
            row = cur.fetchone()
            if row and _is_usable_value(row['final_value']):
                final_value = row['final_value']
                final_status = row['status'] or 'draft'
        except Exception:
            pass

        if final_value is not None and final_status != 'draft':
            resolved_status = final_status if final_status in _VALID_FIELD_STATUSES else 'derived'
            return {
                'field_key': field_key,
                'label': field_key.replace('_', ' ').title(),
                'value': final_value,
                'status': resolved_status,
                'confidence': 0.9,
                'confidence_level': _map_status_to_confidence_level(resolved_status, is_private),
                'evidence_count': 1,
                'source': 'final',
            }

        # 2. Try v3 read model in research_db.final_card_values
        final_card_value = self._resolve_final_card_value(company_name, field_key)
        if final_card_value:
            status = final_card_value['status']
            return {
                'field_key': field_key,
                'label': field_key.replace('_', ' ').title(),
                'value': final_card_value['value'],
                'status': status,
                'confidence': final_card_value['confidence'],
                'confidence_level': _map_status_to_confidence_level(status, is_private),
                'evidence_count': 0,
                'source': 'final_card_values',
            }

        # 3. Try normalized research_fields before legacy wide table.
        research_field = self._resolve_research_field(company_name, field_key)
        if research_field:
            status = research_field['status']
            return {
                'field_key': field_key,
                'label': field_key.replace('_', ' ').title(),
                'value': research_field['value'],
                'status': status,
                'confidence': 0.5,
                'confidence_level': _map_status_to_confidence_level(status, is_private),
                'evidence_count': 0,
                'source': 'research_fields',
            }

        # 4. Legacy wide research table fallback.
        research_value = None
        try:
            research_conn = self._get_research_conn()
            cur = research_conn.execute(
                'SELECT * FROM research WHERE company_name=?',
                (company_name,)
            )
            row = cur.fetchone()
            if row:
                # Try to access field_key as column (old wide table)
                try:
                    research_value = row[field_key]
                except (IndexError, KeyError):
                    pass
        except Exception:
            pass

        if _is_usable_value(research_value):
            return {
                'field_key': field_key,
                'label': field_key.replace('_', ' ').title(),
                'value': str(research_value),
                'status': 'llm_extracted',
                'confidence': 0.5,
                'confidence_level': 'estimated',
                'evidence_count': 0,
                'source': 'research',
            }

        # 3. Missing — choose status based on field type
        if is_private:
            status = 'unavailable'
            conf_level = 'unavailable'
        else:
            status = 'manual_needed'
            conf_level = 'unavailable'

        return {
            'field_key': field_key,
            'label': field_key.replace('_', ' ').title(),
            'value': None,
            'status': status,
            'confidence': 0.0,
            'confidence_level': conf_level,
            'evidence_count': 0,
            'source': 'none',
        }

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        try:
            return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        except Exception:
            return set()

    def _company_key_candidates(self, company_name: str) -> list[str]:
        candidates = [_slugify(company_name), company_name.lower()]
        try:
            conn = self._get_research_conn()
            research_cols = self._table_columns(conn, 'research')
            if 'company_key' in research_cols:
                row = conn.execute(
                    """
                    SELECT company_key FROM research
                    WHERE company_name=? AND company_key IS NOT NULL AND TRIM(company_key)!=''
                    ORDER BY id DESC LIMIT 1
                    """,
                    (company_name,),
                ).fetchone()
                if row and row['company_key']:
                    candidates.insert(0, row['company_key'])
            fields_cols = self._table_columns(conn, 'research_fields')
            if 'company_key' in fields_cols:
                row = conn.execute(
                    """
                    SELECT company_key FROM research_fields
                    WHERE company_name=? AND company_key IS NOT NULL AND TRIM(company_key)!=''
                    ORDER BY id DESC LIMIT 1
                    """,
                    (company_name,),
                ).fetchone()
                if row and row['company_key']:
                    candidates.insert(0, row['company_key'])
        except Exception:
            pass
        seen = set()
        unique = []
        for candidate in candidates:
            key = str(candidate or '').strip()
            if key and key not in seen:
                unique.append(key)
                seen.add(key)
        return unique

    def _resolve_final_card_value(self, company_name: str, field_key: str) -> Optional[dict]:
        try:
            conn = self._get_research_conn()
            cols = self._table_columns(conn, 'final_card_values')
            required = {'company_key', 'field_key', 'final_value'}
            if not required.issubset(cols):
                return None
            company_keys = self._company_key_candidates(company_name)
            if not company_keys:
                return None
            placeholders = ','.join(['?'] * len(company_keys))
            cur = conn.execute(
                f"""
                SELECT final_value, status, confidence, resolution_status
                FROM final_card_values
                WHERE company_key IN ({placeholders}) AND field_key=?
                  AND final_value IS NOT NULL
                  AND TRIM(CAST(final_value AS TEXT)) NOT IN ('', '暂缺', 'None', 'none', 'null', 'NULL', '[]', '{{}}')
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                [*company_keys, field_key],
            )
            row = cur.fetchone()
            if not row or not _is_usable_value(row['final_value']):
                return None
            status = row['status'] or row['resolution_status'] or 'derived'
            if status not in _VALID_FIELD_STATUSES:
                status = row['resolution_status'] or 'derived'
            if status not in _VALID_FIELD_STATUSES:
                status = 'derived'
            confidence_raw = str(row['confidence'] or '').strip().lower()
            confidence = {'high': 0.9, 'medium': 0.7, 'low': 0.45}.get(confidence_raw, 0.7)
            return {
                'value': str(row['final_value']),
                'status': status,
                'confidence': confidence,
            }
        except Exception:
            return None

    def _resolve_research_field(self, company_name: str, field_key: str) -> Optional[dict]:
        try:
            conn = self._get_research_conn()
            cols = self._table_columns(conn, 'research_fields')
            required = {'company_name', 'version', 'field_key', 'field_value'}
            if not required.issubset(cols):
                return None
            status_col = 'resolution_status' if 'resolution_status' in cols else "''"
            company_keys = self._company_key_candidates(company_name) if 'company_key' in cols else []
            clauses = ['company_name=?']
            params = [company_name]
            if company_keys:
                placeholders = ','.join(['?'] * len(company_keys))
                clauses.append(f'company_key IN ({placeholders})')
                params.extend(company_keys)
            cur = conn.execute(
                f"""
                SELECT field_value, {status_col} AS status, version
                FROM research_fields
                WHERE ({' OR '.join(clauses)}) AND field_key=?
                  AND field_value IS NOT NULL
                  AND TRIM(CAST(field_value AS TEXT)) NOT IN ('', '暂缺', 'None', 'none', 'null', 'NULL', '[]', '{{}}')
                ORDER BY
                  CASE version WHEN 'spread' THEN 0 WHEN 'business' THEN 1 WHEN 'standard' THEN 2 ELSE 3 END,
                  id DESC
                LIMIT 1
                """,
                [*params, field_key],
            )
            row = cur.fetchone()
            if not row or not _is_usable_value(row['field_value']):
                return None
            status = row['status'] or 'llm_extracted'
            if status not in _VALID_FIELD_STATUSES:
                status = 'llm_extracted'
            return {
                'value': str(row['field_value']),
                'status': status,
            }
        except Exception:
            return None

    def _resolve_media(self, company_name: str, asset_key: str) -> dict:
        """Resolve a media asset from assets_db.

        Returns dict with asset_key, url, status, source.
        """
        try:
            assets_conn = self._get_assets_conn()
            cur = assets_conn.execute(
                'SELECT local_path, status FROM company_assets WHERE company_name=? AND asset_key=?',
                (company_name, asset_key)
            )
            row = cur.fetchone()
            if row:
                asset_status = row['status'] or 'missing'
                # Map asset status to contract media status
                status_map = {
                    'ready': 'ready',
                    'generating': 'fallback',
                    'failed': 'fallback',
                    'missing': 'fallback',
                }
                contract_status = status_map.get(asset_status, 'fallback')
                url = row['local_path'] or None
                return {
                    'asset_key': asset_key,
                    'url': url,
                    'status': contract_status,
                    'source': 'selected_asset',
                }
        except Exception:
            pass

        # Asset not found — fallback
        return {
            'asset_key': asset_key,
            'url': None,
            'status': 'fallback',
            'source': 'none',
        }


_VALID_FIELD_STATUSES = {
    'confirmed', 'derived', 'proxy', 'industry_avg',
    'llm_extracted', 'manual_needed', 'unavailable',
    'not_applicable',
}
