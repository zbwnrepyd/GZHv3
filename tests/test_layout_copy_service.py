import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "webapp"))

from services.layout_copy_service import (
    generate_layout_copy_for_company,
    _humanizer_zh_system_prompt,
)
from repositories.layout_repo import get_layout


def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    return path


class LayoutCopyServiceTests(unittest.TestCase):
    def setUp(self):
        self.research_db = _tmp_db()
        self.final_db = _tmp_db()
        self.composition_db = _tmp_db()
        self.template_db = _tmp_db()
        self._init_schema()

    def tearDown(self):
        for path in (self.research_db, self.final_db, self.composition_db, self.template_db):
            if os.path.exists(path):
                os.remove(path)

    def _init_schema(self):
        with sqlite3.connect(self.research_db) as conn:
            conn.execute("""
                CREATE TABLE research_fields (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  company_name TEXT,
                  company_key TEXT,
                  version TEXT,
                  field_key TEXT,
                  field_label TEXT,
                  field_value TEXT,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        with sqlite3.connect(self.final_db) as conn:
            conn.execute("""
                CREATE TABLE final_fields (
                  company_name TEXT,
                  field_key TEXT,
                  field_label TEXT,
                  final_value TEXT,
                  source_version TEXT,
                  status TEXT,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(company_name, field_key)
                )
            """)
            conn.executemany(
                """INSERT INTO final_fields
                   (company_name, field_key, field_label, final_value, source_version, status)
                   VALUES ('DemoCo', ?, ?, ?, 'standard', 'confirmed')""",
                [
                    ("company_name", "公司名", "DemoCo"),
                    ("company_type", "公司类型", "AI 工具，增长率 42%"),
                ],
            )
        with sqlite3.connect(self.composition_db) as conn:
            conn.execute("""
                CREATE TABLE card_compositions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  company_name TEXT,
                  card_set_key TEXT,
                  card_id TEXT,
                  card_index INTEGER,
                  card_title TEXT,
                  template_id TEXT,
                  enabled INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE card_items (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  company_name TEXT,
                  card_set_key TEXT,
                  card_id TEXT,
                  item_type TEXT,
                  item_key TEXT,
                  item_label TEXT,
                  display_role TEXT,
                  sort_order INTEGER,
                  enabled INTEGER DEFAULT 1
                )
            """)
            conn.execute(
                """INSERT INTO card_compositions
                   (company_name, card_set_key, card_id, card_index, card_title, template_id, enabled)
                   VALUES ('DemoCo', 'v4', 'v4_card_01', 1, '公司基本面', 'tpl', 1)"""
            )
            conn.executemany(
                """INSERT INTO card_items
                   (company_name, card_set_key, card_id, item_type, item_key, item_label, display_role, sort_order, enabled)
                   VALUES ('DemoCo', 'v4', 'v4_card_01', 'field', ?, ?, 'body', ?, 1)""",
                [
                    ("company_name", "公司名", 1),
                    ("company_type", "公司类型", 2),
                ],
            )
        with sqlite3.connect(self.template_db) as conn:
            conn.execute("""
                CREATE TABLE card_layout_instances (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  company_name TEXT NOT NULL,
                  card_id TEXT NOT NULL,
                  template_id TEXT,
                  layout_json TEXT NOT NULL,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(company_name, card_id)
                )
            """)

    def test_generate_layout_copy_writes_three_paragraph_markdown_and_preserves_numbers(self):
        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                payload = json.loads(user_message)
                self.assertEqual(payload["card"]["card_id"], "v4_card_01")
                return json.dumps({
                    "card_id": "v4_card_01",
                    "paragraphs": ["DemoCo 是 AI 工具公司。", "它面向内容生产场景。", "这里故意漏掉增长率。"],
                }, ensure_ascii=False)
            else:
                # step2: humanizer identity pass
                user = json.loads(user_message)
                return json.dumps(user, ensure_ascii=False)

        result = generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )
        layout = get_layout(self.template_db, "DemoCo", "v4_card_01")
        markdown = layout["layout_json"]["markdown"]

        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(len(markdown.split("\n\n")), 3)
        self.assertIn("42%", markdown)
        self.assertEqual(layout["layout_json"]["mode"], "markdown_first")

    def test_generate_layout_copy_preserves_media_tokens_in_layout_markdown(self):
        with sqlite3.connect(self.composition_db) as conn:
            conn.execute(
                """INSERT INTO card_items
                   (company_name, card_set_key, card_id, item_type, item_key, item_label, display_role, sort_order, enabled)
                   VALUES ('DemoCo', 'v4', 'v4_card_01', 'media', 'logo', 'Logo', 'logo', 0, 1)"""
            )

        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                payload = json.loads(user_message)
                return json.dumps({
                    "card_id": payload["card"]["card_id"],
                    "paragraphs": ["DemoCo 是 AI 工具公司。", "它面向内容生产场景。", "增长率 42%。"],
                }, ensure_ascii=False)
            else:
                user = json.loads(user_message)
                return json.dumps(user, ensure_ascii=False)

        generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )
        layout = get_layout(self.template_db, "DemoCo", "v4_card_01")
        markdown = layout["layout_json"]["markdown"]
        prose_blocks = [block for block in markdown.split("\n\n") if not block.startswith("{{")]

        self.assertIn("{{logo}}", markdown)
        self.assertEqual(len(prose_blocks), 3)

    def test_layout_copy_prompt_applies_elsewhere_before_humanizer(self):
        """两步 LLM：step1 的 system_prompt 含 elsewhere-perspective，step2 含 humanizer-zh 模式。"""
        step1_prompts = []
        step2_prompts = []

        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                step1_prompts.append(system_prompt)
                payload = json.loads(user_message)
                return json.dumps({
                    "card_id": payload["card"]["card_id"],
                    "paragraphs": ["DemoCo 是 AI 工具公司。", "它面向内容生产场景。", "增长率 42%。"],
                }, ensure_ascii=False)
            else:
                step2_prompts.append(system_prompt)
                user = json.loads(user_message)
                return json.dumps({
                    "card_id": user.get("card_id", ""),
                    "paragraphs": user.get("paragraphs", []),
                }, ensure_ascii=False)

        generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )

        self.assertEqual(len(step1_prompts), 1, "step1 LLM 应被调用1次")
        self.assertEqual(len(step2_prompts), 1, "step2 humanizer LLM 应被调用1次")
        self.assertIn("elsewhere-perspective", step1_prompts[0])
        self.assertIn("AI 腔", step2_prompts[0])

    def test_layout_copy_prompt_has_market_card_structure_controls(self):
        """赛道三段结构在 step1（串接）prompt 中。"""
        step1_prompts = []

        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                step1_prompts.append(system_prompt)
                payload = json.loads(user_message)
                return json.dumps({
                    "card_id": payload["card"]["card_id"],
                    "paragraphs": ["DemoCo 是 AI 工具公司。", "它面向内容生产场景。", "增长率 42%。"],
                }, ensure_ascii=False)
            else:
                user = json.loads(user_message)
                return json.dumps({
                    "card_id": user.get("card_id", ""),
                    "paragraphs": user.get("paragraphs", []),
                }, ensure_ascii=False)

        generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )
        prompt = step1_prompts[0]

        self.assertIn("卡片赛道情况", prompt)
        self.assertIn("罗列数据与事实", prompt)
        self.assertIn("分析与结论", prompt)
        self.assertIn("不自己编造", prompt)
        self.assertIn("事件数要≥1", prompt)
        self.assertIn("变化数要≥1", prompt)
        self.assertIn("天花板受限的红海市场", prompt)

    # ── TDD 新增测试 ──

    def test_two_step_llm_step1_before_step2(self):
        """验证 step1 (elsewhere 串接) 的 LLM 调用先于 step2 (humanizer)。"""
        call_order = []

        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                call_order.append("step1")
                payload = json.loads(user_message)
                return json.dumps({
                    "card_id": payload["card"]["card_id"],
                    "paragraphs": ["第一段。", "第二段。", "第三段。"],
                }, ensure_ascii=False)
            else:
                call_order.append("step2")
                user = json.loads(user_message)
                return json.dumps({
                    "card_id": user.get("card_id", ""),
                    "paragraphs": user.get("paragraphs", []),
                }, ensure_ascii=False)

        generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )

        self.assertEqual(call_order, ["step1", "step2"],
                         f"调用顺序应为 [step1, step2]，实际 {call_order}")

    def test_step2_humanizer_receives_step1_output(self):
        """验证 step2 humanizer 的输入是 step1 输出的 paragraphs。"""
        step1_paragraphs = ["DemoCo 是 AI 工具公司。", "面向内容生产场景。", "增长率 42%。"]
        humanizer_input = []

        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                payload = json.loads(user_message)
                return json.dumps({
                    "card_id": payload["card"]["card_id"],
                    "paragraphs": step1_paragraphs,
                }, ensure_ascii=False)
            else:
                user = json.loads(user_message)
                humanizer_input.append(user)
                return json.dumps({
                    "card_id": user.get("card_id", ""),
                    "paragraphs": user.get("paragraphs", []),
                }, ensure_ascii=False)

        generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )

        self.assertEqual(len(humanizer_input), 1)
        self.assertEqual(humanizer_input[0]["paragraphs"], step1_paragraphs)

    def test_humanizer_zh_prompt_has_ai_pattern_keywords(self):
        """验证 Humanizer-zh prompt 包含24种模式的关键词。"""
        prompt = _humanizer_zh_system_prompt()
        self.assertIn("AI 腔", prompt)
        self.assertIn("AI 写作痕迹", prompt)
        self.assertIn("填充短语", prompt)
        self.assertIn("破折号", prompt)
        # 验证包含 Humanizer-zh 特有的处理流程描述
        self.assertIn("仔细阅读", prompt)

    def test_market_card_v4_card_02_has_all_13_fields_in_llm_input(self):
        """验证 v4_card_02（赛道切口）的13个字段全部传入 LLM。"""
        # 先改卡片为 v4_card_02 类型
        with sqlite3.connect(self.composition_db) as conn:
            conn.execute("DELETE FROM card_items")
            conn.execute("UPDATE card_compositions SET card_id='v4_card_02', card_title='赛道切口'")
            v4_card_02_fields = [
                ("market_track", "赛道"),
                ("market_subtrack", "细分赛道"),
                ("market_landscape_summary", "赛道市场格局"),
                ("market_landscape_top_players", "Top玩家列表"),
                ("market_size_value", "赛道市场规模"),
                ("market_size_currency", "市场规模币种"),
                ("market_size_year", "市场规模口径年份"),
                ("market_cagr", "年复合增长率"),
                ("tam_value", "TAM 数值"),
                ("tam_currency", "TAM 币种"),
                ("tam_year", "TAM 口径年份"),
                ("market_opportunity", "赛道机会"),
                ("company_def", "公司定义"),
            ]
            for i, (fk, fl) in enumerate(v4_card_02_fields, 1):
                conn.execute(
                    """INSERT INTO card_items
                       (company_name, card_set_key, card_id, item_type, item_key, item_label, display_role, sort_order, enabled)
                       VALUES ('DemoCo', 'v4', 'v4_card_02', 'field', ?, ?, 'body', ?, 1)""",
                    (fk, fl, i),
                )
            # 为这些字段补充 final_fields 数据
        with sqlite3.connect(self.final_db) as conn:
            for fk, fl in v4_card_02_fields:
                conn.execute(
                    """INSERT OR REPLACE INTO final_fields
                       (company_name, field_key, field_label, final_value, source_version, status)
                       VALUES ('DemoCo', ?, ?, ?, 'standard', 'confirmed')""",
                    (fk, fl, f"{fl}测试值"),
                )

        llm_input = []

        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                payload = json.loads(user_message)
                llm_input.append(payload)
                return json.dumps({
                    "card_id": payload["card"]["card_id"],
                    "paragraphs": ["赛道分析段。", "事件段。", "变化机会段。"],
                }, ensure_ascii=False)
            else:
                user = json.loads(user_message)
                return json.dumps({
                    "card_id": user.get("card_id", ""),
                    "paragraphs": user.get("paragraphs", []),
                }, ensure_ascii=False)

        generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )

        self.assertEqual(len(llm_input), 1)
        facts = llm_input[0]["card"]["facts"]
        field_keys_in_input = {f["field_key"] for f in facts}
        expected_keys = {fk for fk, _ in v4_card_02_fields}
        self.assertEqual(field_keys_in_input, expected_keys,
                         f"v4_card_02 的13个字段应全部传入 LLM，缺少: {expected_keys - field_keys_in_input}")

    def test_generate_layout_copy_retries_when_ai_returns_truncated_json(self):
        """step1 JSON 解析失败时重试，step2 正常执行，总共3次 LLM 调用。"""
        calls = []

        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                calls.append("step1")
                if calls.count("step1") == 1:
                    return '{"card_id":"v4_card_01","paragraphs":["DemoCo 是 AI 工具公司。","第二段'
                return json.dumps({
                    "card_id": "v4_card_01",
                    "paragraphs": ["DemoCo 是 AI 工具公司。", "第二段保留事实。", "增长率 42% 被保留。"],
                }, ensure_ascii=False)
            else:
                calls.append("step2")
                user = json.loads(user_message)
                return json.dumps(user, ensure_ascii=False)

        result = generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )
        layout = get_layout(self.template_db, "DemoCo", "v4_card_01")

        self.assertEqual(len(calls), 3, f"应3次LLM调用: step1失败+step1重试+step2, 实际 {calls}")
        self.assertEqual(result["warnings"], [])
        self.assertIn("第二段保留事实", layout["layout_json"]["markdown"])

    def test_generate_layout_copy_falls_back_to_fact_preserving_copy_after_ai_parse_failures(self):
        """step1 两次都返回无效 JSON 时，使用事实兜底文案。"""
        def fake_llm(system_prompt, user_message):
            if "elsewhere-perspective" in system_prompt:
                return '{"card_id":"v4_card_01","paragraphs":["未闭合'
            else:
                return 'also broken'

        result = generate_layout_copy_for_company(
            research_db_path=self.research_db,
            final_db_path=self.final_db,
            composition_db_path=self.composition_db,
            template_db_path=self.template_db,
            company_name="DemoCo",
            card_set_key="v4",
            call_llm=fake_llm,
        )
        layout = get_layout(self.template_db, "DemoCo", "v4_card_01")
        markdown = layout["layout_json"]["markdown"]

        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("公司名：DemoCo", markdown)
        self.assertIn("增长率 42%", markdown)


if __name__ == "__main__":
    unittest.main()
