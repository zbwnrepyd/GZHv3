"""RenderAssembler — assembles RenderContract from multiple databases.

Priority: final layer > research layer
Missing fields → status: manual_needed or unavailable
Missing media → status: fallback or manual_needed
Never raises exception on missing data.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

# Private/operational metrics that default to 'unavailable' when no data exists
_PRIVATE_METRIC_FIELDS = {
    'ltv', 'cac', 'ltv_cac_ratio', 'retention_rate', 'churn_rate',
    'arr', 'mrr', 'gross_margin', 'burn_rate', 'runway_months',
    'paying_users', 'active_users', 'registered_users', 'mau',
    'company_revenue', 'company_profit', 'revenue_metrics', 'growth_metrics',
}


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

        # 1. Try final_db
        final_value = None
        final_status = None
        try:
            final_conn = self._get_final_conn()
            cur = final_conn.execute(
                'SELECT final_value, status FROM final_fields WHERE company_name=? AND field_key=?',
                (company_name, field_key)
            )
            row = cur.fetchone()
            if row and row['final_value'] is not None and row['final_value'] != '':
                final_value = row['final_value']
                final_status = row['status'] or 'draft'
        except Exception:
            pass

        if final_value is not None and final_status != 'draft':
            return {
                'field_key': field_key,
                'label': field_key.replace('_', ' ').title(),
                'value': final_value,
                'status': final_status if final_status in _VALID_FIELD_STATUSES else 'derived',
                'confidence': 0.9,
                'evidence_count': 1,
                'source': 'final',
            }

        # 2. Try research_db
        research_value = None
        try:
            research_conn = self._get_research_conn()
            cur = research_conn.execute(
                'SELECT * FROM research WHERE company_name=?',
                (company_name,)
            )
            row = cur.fetchone()
            if row:
                # Try to access field_key as column
                try:
                    research_value = row[field_key]
                except (IndexError, KeyError):
                    # Try research_fields table
                    cur2 = research_conn.execute(
                        'SELECT field_value FROM research_fields WHERE company_name=? AND field_key=?',
                        (company_name, field_key)
                    )
                    rf_row = cur2.fetchone()
                    if rf_row:
                        research_value = rf_row['field_value']
        except Exception:
            pass

        if research_value is not None and str(research_value).strip():
            return {
                'field_key': field_key,
                'label': field_key.replace('_', ' ').title(),
                'value': str(research_value),
                'status': 'llm_extracted',
                'confidence': 0.5,
                'evidence_count': 0,
                'source': 'research',
            }

        # 3. Missing — choose status based on field type
        if is_private:
            status = 'unavailable'
        else:
            status = 'manual_needed'

        return {
            'field_key': field_key,
            'label': field_key.replace('_', ' ').title(),
            'value': None,
            'status': status,
            'confidence': 0.0,
            'evidence_count': 0,
            'source': 'none',
        }

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
