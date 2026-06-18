"""Unit tests for RenderAssembler — PR5."""

import json
import os
import sqlite3
import tempfile
import pytest

# Add project root and webapp to path so we can import webapp modules
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

from webapp.services.render_assembler import RenderAssembler

PRIVATE_METRIC_FIELDS = {
    'ltv', 'cac', 'ltv_cac_ratio', 'retention_rate', 'churn_rate',
    'arr', 'mrr', 'gross_margin', 'burn_rate', 'runway_months',
    'paying_users', 'active_users', 'registered_users', 'mau',
}


def _setup_test_dbs():
    """Create in-memory DBs with minimal schema for testing."""
    research_db = sqlite3.connect(':memory:')
    final_db = sqlite3.connect(':memory:')
    assets_db = sqlite3.connect(':memory:')
    composition_db = sqlite3.connect(':memory:')

    for db in (research_db, final_db, assets_db, composition_db):
        db.execute("PRAGMA foreign_keys = ON")

    # research_db: research table with v3 fields
    research_db.execute('''CREATE TABLE research (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        company_type TEXT,
        location TEXT,
        company_def TEXT,
        core_business TEXT,
        ltv TEXT,
        cac TEXT
    )''')

    # final_db: final_fields table
    final_db.execute('''CREATE TABLE final_fields (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        field_key TEXT NOT NULL,
        final_value TEXT,
        status TEXT DEFAULT 'draft',
        UNIQUE(company_name, field_key)
    )''')

    # assets_db: company_assets table
    assets_db.execute('''CREATE TABLE company_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        asset_key TEXT NOT NULL,
        local_path TEXT,
        status TEXT DEFAULT 'missing',
        UNIQUE(company_name, asset_key)
    )''')

    # composition_db: card_compositions + card_items + default_card_configs
    composition_db.execute('''CREATE TABLE card_compositions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        card_set_key TEXT NOT NULL DEFAULT 'v1',
        card_id TEXT NOT NULL,
        card_index INTEGER NOT NULL,
        card_title TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        template_id TEXT,
        UNIQUE(company_name, card_set_key, card_id)
    )''')
    composition_db.execute('''CREATE TABLE card_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        card_set_key TEXT NOT NULL DEFAULT 'v1',
        card_id TEXT NOT NULL,
        item_type TEXT NOT NULL,
        item_key TEXT NOT NULL,
        item_label TEXT,
        sort_order INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1
    )''')
    composition_db.execute('''CREATE TABLE default_card_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        set_key TEXT NOT NULL DEFAULT 'v1',
        card_id TEXT NOT NULL,
        card_index INTEGER NOT NULL,
        card_title TEXT NOT NULL,
        config_json TEXT NOT NULL,
        UNIQUE(set_key, card_id)
    )''')

    # Insert a simple v3 card for testing
    composition_db.execute('''INSERT OR REPLACE INTO default_card_configs
        (set_key, card_id, card_index, card_title, config_json)
        VALUES ('v3', 'v3_card_01', 1, '封面',
                '{"fields":["company_name","company_type"],"media":["logo"]}')''')
    composition_db.execute('''INSERT OR REPLACE INTO default_card_configs
        (set_key, card_id, card_index, card_title, config_json)
        VALUES ('v3', 'v3_card_02', 2, '公司简介',
                '{"fields":["company_def","location","core_business","ltv","cac"],"media":["website_screenshot"]}')''')

    # Card items for the test company
    for card_id, item_type, item_key, item_label in [
        ('v3_card_01', 'field', 'company_name', '公司名称'),
        ('v3_card_01', 'field', 'company_type', '公司类型'),
        ('v3_card_01', 'media', 'logo', 'Logo'),
        ('v3_card_02', 'field', 'company_def', '公司定义'),
        ('v3_card_02', 'field', 'location', '地点'),
        ('v3_card_02', 'field', 'core_business', '核心业务'),
        ('v3_card_02', 'field', 'ltv', 'LTV'),
        ('v3_card_02', 'field', 'cac', 'CAC'),
        ('v3_card_02', 'media', 'website_screenshot', '网站截图'),
    ]:
        composition_db.execute('''INSERT INTO card_items
            (company_name, card_set_key, card_id, item_type, item_key, item_label)
            VALUES ('TestCo', 'v3', ?, ?, ?, ?)''',
            (card_id, item_type, item_key, item_label))

    # Card compositions for the test company
    composition_db.execute('''INSERT OR REPLACE INTO card_compositions
        (company_name, card_set_key, card_id, card_index, card_title, enabled, template_id)
        VALUES ('TestCo', 'v3', 'v3_card_01', 1, '封面', 1, 'cover_v3')''')
    composition_db.execute('''INSERT OR REPLACE INTO card_compositions
        (company_name, card_set_key, card_id, card_index, card_title, enabled, template_id)
        VALUES ('TestCo', 'v3', 'v3_card_02', 2, '公司简介', 1, 'company_intro_v3')''')

    # Research data
    research_db.execute('''INSERT INTO research
        (company_name, company_type, location, company_def, core_business, ltv, cac)
        VALUES ('TestCo', 'SaaS', '北京', '测试公司定义', '核心业务描述', NULL, NULL)''')

    # Final data (overrides research for company_name)
    final_db.execute('''INSERT OR REPLACE INTO final_fields
        (company_name, field_key, final_value, status)
        VALUES ('TestCo', 'company_name', 'TestCo Final', 'confirmed')''')

    # Asset data
    assets_db.execute('''INSERT OR REPLACE INTO company_assets
        (company_name, asset_key, local_path, status)
        VALUES ('TestCo', 'logo', '/images/testco/logo.png', 'ready')''')

    for db in (research_db, final_db, assets_db, composition_db):
        db.commit()

    return research_db, final_db, assets_db, composition_db


class TestRenderAssembler:
    """PR5 unit tests for RenderAssembler."""

    @pytest.fixture
    def assembler(self):
        research_db, final_db, assets_db, composition_db = _setup_test_dbs()
        a = RenderAssembler(
            research_db_path=':memory:',
            final_db_path=':memory:',
            assets_db_path=':memory:',
            composition_db_path=':memory:',
        )
        # Inject our pre-built connections
        a._research_conn = research_db
        a._final_conn = final_db
        a._assets_conn = assets_db
        a._composition_conn = composition_db
        yield a
        for db in (research_db, final_db, assets_db, composition_db):
            db.close()

    def test_render_assembler_prefers_final_value(self, assembler):
        """Final layer value should override research layer value."""
        contract = assembler.assemble('TestCo', 'v3')
        cover_card = next(c for c in contract['cards'] if c['card_id'] == 'v3_card_01')
        name_item = next(i for i in cover_card['items'] if i['field_key'] == 'company_name')
        # Final DB has 'TestCo Final', research has 'TestCo'
        assert name_item['value'] == 'TestCo Final', \
            f"Expected final value 'TestCo Final', got '{name_item['value']}'"
        assert name_item['status'] == 'confirmed'
        assert name_item['source'] == 'final'

    def test_render_assembler_missing_private_metric_unavailable(self, assembler):
        """Private metrics without data should be unavailable, not guessed."""
        contract = assembler.assemble('TestCo', 'v3')
        intro_card = next(c for c in contract['cards'] if c['card_id'] == 'v3_card_02')
        # LTV and CAC are private metrics, no data in DB
        ltv_item = next((i for i in intro_card['items'] if i['field_key'] == 'ltv'), None)
        cac_item = next((i for i in intro_card['items'] if i['field_key'] == 'cac'), None)
        assert ltv_item is not None, "LTV item should exist in card"
        assert ltv_item['status'] == 'unavailable', \
            f"Expected 'unavailable' for private metric LTV, got '{ltv_item['status']}'"
        assert cac_item is not None, "CAC item should exist in card"
        assert cac_item['status'] == 'unavailable', \
            f"Expected 'unavailable' for private metric CAC, got '{cac_item['status']}'"

    def test_render_assembler_missing_media_returns_fallback(self, assembler):
        """Missing media should have fallback or manual_needed status, never crash."""
        contract = assembler.assemble('TestCo', 'v3')
        intro_card = next(c for c in contract['cards'] if c['card_id'] == 'v3_card_02')
        # website_screenshot is in the card but not in assets_db
        ws_media = next((m for m in intro_card['media'] if m['asset_key'] == 'website_screenshot'), None)
        assert ws_media is not None, "website_screenshot media should exist in card"
        assert ws_media['status'] in ('fallback', 'manual_needed', 'unavailable'), \
            f"Expected fallback/manual_needed/unavailable for missing media, got '{ws_media['status']}'"

    def test_render_assembler_returns_contract_structure(self, assembler):
        """Assembled contract must have required top-level keys."""
        contract = assembler.assemble('TestCo', 'v3')
        assert 'version' in contract
        assert 'company' in contract
        assert 'card_set' in contract
        assert 'cards' in contract
        assert 'warnings' in contract
        assert contract['card_set'] == 'v3'
        assert contract['company']['name'] == 'TestCo'
        assert len(contract['cards']) > 0

    def test_render_assembler_no_exception_on_missing_company(self, assembler):
        """Assembler must never raise on missing company — return cards with unavailable fields."""
        contract = assembler.assemble('NonExistentCo', 'v3')
        assert 'cards' in contract
        assert len(contract['cards']) > 0, "Should return default cards even for unknown company"
        # All field items should have missing data status
        for card in contract['cards']:
            for item in card['items']:
                assert item['status'] in ('manual_needed', 'unavailable'), \
                    f"Expected missing status, got '{item['status']}' for {item['field_key']}"
