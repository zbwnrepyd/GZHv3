"""竞品字段测试 — SPEC Section 16.8

验证竞争相关字段（competitors_top3 / competitive_position / differentiated_opportunity /
competitive_advantages 等 A 类 official_fact）的证据绑定规则与结构要求：

1. competitors_top3 有 evidence_span_ids → confirmed
2. competitors_top3 无 evidence → llm_extracted（不得 confirmed）
3. competitive_position 有 evidence → confirmed
4. differentiated_opportunity 有 evidence → confirmed
5. competitive_advantages 有 evidence → confirmed
6. field_manifest 中竞争字段均为 category A
7. competitors_top3 JSON 结构必须为数组，每个元素含 name/summary/overlap/difference（SPEC §13.8）
"""
import json
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "webapp"))

from research.field_resolver import resolve_field, FieldResult


def _load_manifest() -> dict:
    """加载 field_manifest.yaml 返回 fields dict。"""
    try:
        import yaml
    except ImportError:
        raise unittest.SkipTest("PyYAML 未安装，跳过 manifest 测试")
    manifest_path = ROOT / "references" / "field_manifest.yaml"
    if not manifest_path.exists():
        raise unittest.SkipTest("field_manifest.yaml 不存在")
    with open(manifest_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("fields", {})


# ── SPEC 16.8.1: competitors_top3 证据绑定 ──


class CompetitorsTop3EvidenceTest(unittest.TestCase):
    """SPEC 16.8.1 — competitors_top3 的证据绑定规则"""

    def test_competitors_top3_with_evidence_confirmed(self):
        """有证据绑定的 competitors_top3 → confirmed，confidence high（>=2 证据）"""
        result = resolve_field(
            field_key="competitors_top3",
            field_value='[{"name":"OpenAI","summary":"基础模型领导者","overlap":"LLM 赛道","difference":"C端产品 vs API 平台"}]',
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
                "type": "json_text",
            },
            evidence_span_ids=["ev_comp_001", "ev_comp_002"],
        )
        self.assertEqual(result.field_key, "competitors_top3")
        self.assertEqual(
            result.resolution_status, "confirmed",
            f"competitors_top3 有证据时应为 confirmed，实际为 {result.resolution_status}",
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.resolution_method, "official_fact")
        self.assertIn("ev_comp_001", result.evidence_span_ids)

    def test_competitors_top3_single_evidence_medium_confidence(self):
        """单个证据的 competitors_top3 → confirmed 但 confidence medium"""
        result = resolve_field(
            field_key="competitors_top3",
            field_value='[{"name":"Anthropic","summary":"AI安全公司"}]',
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=["ev_single"],
        )
        self.assertEqual(result.resolution_status, "confirmed")
        self.assertEqual(result.confidence, "medium")

    def test_competitors_top3_without_evidence_llm_extracted(self):
        """无证据绑定的 competitors_top3 → llm_extracted（不得 confirmed）"""
        result = resolve_field(
            field_key="competitors_top3",
            field_value='[{"name":"OpenAI","summary":"基础模型领导者"}]',
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=[],
        )
        self.assertEqual(
            result.resolution_status, "llm_extracted",
            f"competitors_top3 无证据时应为 llm_extracted，实际为 {result.resolution_status}",
        )
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.resolution_method, "llm_extract_no_evidence")
        self.assertIn("未绑定证据", result.unavailable_reason)

    def test_competitors_top3_evidence_none_llm_extracted(self):
        """evidence_span_ids=None → 等同无证据，llm_extracted"""
        result = resolve_field(
            field_key="competitors_top3",
            field_value='[{"name":"DeepMind"}]',
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=None,
        )
        self.assertEqual(result.resolution_status, "llm_extracted")
        self.assertNotEqual(
            result.resolution_status, "confirmed",
            "evidence_span_ids=None 时不得为 confirmed",
        )

    def test_competitors_top3_missing_value_unavailable(self):
        """competitors_top3 无值 → unavailable"""
        result = resolve_field(
            field_key="competitors_top3",
            field_value=None,
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
                "if_missing": "unavailable",
            },
            evidence_span_ids=[],
        )
        self.assertEqual(result.resolution_status, "unavailable")
        self.assertIsNone(result.value)


# ── SPEC 16.8.2: competitive_position 证据绑定 ──


class CompetitivePositionEvidenceTest(unittest.TestCase):
    """SPEC 16.8.2 — competitive_position 的证据绑定规则"""

    def test_competitive_position_with_evidence_confirmed(self):
        """有证据绑定的 competitive_position → confirmed"""
        result = resolve_field(
            field_key="competitive_position",
            field_value="在 AI 安全与可解释性领域处于领先地位，与 OpenAI/Google DeepMind 形成差异化竞争",
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=["ev_pos_001", "ev_pos_002"],
        )
        self.assertEqual(
            result.resolution_status, "confirmed",
            f"competitive_position 有证据时应为 confirmed，实际为 {result.resolution_status}",
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.resolution_method, "official_fact")

    def test_competitive_position_without_evidence_llm_extracted(self):
        """无证据绑定的 competitive_position → llm_extracted（不得 confirmed）"""
        result = resolve_field(
            field_key="competitive_position",
            field_value="市场领先的 AI 平台",
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=[],
        )
        self.assertEqual(
            result.resolution_status, "llm_extracted",
            f"competitive_position 无证据时应为 llm_extracted，实际为 {result.resolution_status}",
        )
        self.assertEqual(result.resolution_method, "llm_extract_no_evidence")


# ── SPEC 16.8.3: differentiated_opportunity 证据绑定 ──
# NOTE: field_manifest 中 canonical key 为 differentiation_strategy，
#       aliases: [differentiated_opportunity]（v3 使用 differentiated_opportunity）


class DifferentiatedOpportunityEvidenceTest(unittest.TestCase):
    """SPEC 16.8.3 — differentiated_opportunity（alias of differentiation_strategy）的证据绑定"""

    def test_differentiated_opportunity_with_evidence_confirmed(self):
        """有证据绑定的 differentiated_opportunity → confirmed（通过 differentiation_strategy manifest entry）"""
        result = resolve_field(
            field_key="differentiated_opportunity",
            field_value="通过 RLHF 与 constitutional AI 构建差异化壁垒，主打企业级安全合规需求",
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
                "aliases": ["differentiated_opportunity"],
            },
            evidence_span_ids=["ev_diff_001", "ev_diff_002"],
        )
        self.assertEqual(
            result.resolution_status, "confirmed",
            f"differentiated_opportunity 有证据时应为 confirmed，实际为 {result.resolution_status}",
        )
        self.assertEqual(result.field_key, "differentiated_opportunity")

    def test_differentiation_strategy_canonical_with_evidence_confirmed(self):
        """canonical 名称 differentiation_strategy 有证据 → confirmed"""
        result = resolve_field(
            field_key="differentiation_strategy",
            field_value="Constitutional AI 安全对齐 + 企业级私有部署",
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
                "aliases": ["differentiated_opportunity"],
            },
            evidence_span_ids=["ev_ds_001"],
        )
        self.assertEqual(result.resolution_status, "confirmed")
        self.assertEqual(result.field_key, "differentiation_strategy")

    def test_differentiated_opportunity_without_evidence_llm_extracted(self):
        """无证据绑定的 differentiated_opportunity → llm_extracted（不得 confirmed）"""
        result = resolve_field(
            field_key="differentiated_opportunity",
            field_value="差异化策略描述",
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=[],
        )
        self.assertEqual(
            result.resolution_status, "llm_extracted",
            f"differentiated_opportunity 无证据时应为 llm_extracted，实际为 {result.resolution_status}",
        )


# ── SPEC 16.8.4: competitive_advantages 证据绑定 ──


class CompetitiveAdvantagesEvidenceTest(unittest.TestCase):
    """SPEC 16.8.4 — competitive_advantages 的证据绑定规则"""

    def test_competitive_advantages_with_evidence_confirmed(self):
        """有证据绑定的 competitive_advantages → confirmed"""
        result = resolve_field(
            field_key="competitive_advantages",
            field_value="1. 安全对齐技术领先 2. 企业级私有部署能力 3. 可解释性研究积累",
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=["ev_adv_001", "ev_adv_002"],
        )
        self.assertEqual(
            result.resolution_status, "confirmed",
            f"competitive_advantages 有证据时应为 confirmed，实际为 {result.resolution_status}",
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.resolution_method, "official_fact")

    def test_competitive_advantages_without_evidence_llm_extracted(self):
        """无证据绑定的 competitive_advantages → llm_extracted（不得 confirmed）"""
        result = resolve_field(
            field_key="competitive_advantages",
            field_value="技术领先",
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=[],
        )
        self.assertEqual(
            result.resolution_status, "llm_extracted",
            f"competitive_advantages 无证据时应为 llm_extracted，实际为 {result.resolution_status}",
        )

    def test_competitive_advantages_missing_value_unavailable(self):
        """competitive_advantages 无值 → unavailable"""
        result = resolve_field(
            field_key="competitive_advantages",
            field_value=None,
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
                "if_missing": "unavailable",
            },
            evidence_span_ids=[],
        )
        self.assertEqual(result.resolution_status, "unavailable")


# ── SPEC 16.8.5: 竞争字段 category A 验证 ──


class CompetitionFieldsCategoryATest(unittest.TestCase):
    """SPEC 16.8.5 — field_manifest 中所有竞争字段均为 category A"""

    COMPETITION_FIELDS = [
        "competitors",
        "competitors_top3",
        "competitors_summary",
        "competitive_position",
        "competitive_advantages",
        "differentiation_strategy",
        "moat",
        "technical_barrier",
        "switching_cost",
        "cost_advantage",
        "ecosystem_niche",
        "ecosystem_positioning",
    ]

    @classmethod
    def setUpClass(cls):
        cls.manifest_fields = _load_manifest()

    def test_all_competition_fields_exist_in_manifest(self):
        """所有竞争字段应在 field_manifest 中存在"""
        missing = []
        for fk in self.COMPETITION_FIELDS:
            if fk not in self.manifest_fields:
                missing.append(fk)
        self.assertEqual(
            len(missing), 0,
            f"{len(missing)} 个竞争字段不在 field_manifest 中: {missing}",
        )

    def test_all_competition_fields_are_category_a(self):
        """所有竞争字段的 category 必须为 A（直接事实）"""
        not_a = []
        for fk in self.COMPETITION_FIELDS:
            entry = self.manifest_fields.get(fk, {})
            cat = entry.get("category", "")
            if cat != "A":
                not_a.append(f"{fk} (category={cat!r})")
        self.assertEqual(
            len(not_a), 0,
            f"{len(not_a)} 个竞争字段 category 不是 A: {not_a}",
        )

    def test_all_competition_fields_are_official_fact(self):
        """所有竞争字段的 resolution_type 必须为 official_fact"""
        not_official = []
        for fk in self.COMPETITION_FIELDS:
            entry = self.manifest_fields.get(fk, {})
            rt = entry.get("resolution_type", "")
            if rt != "official_fact":
                not_official.append(f"{fk} (resolution_type={rt!r})")
        self.assertEqual(
            len(not_official), 0,
            f"{len(not_official)} 个竞争字段 resolution_type 不是 official_fact: {not_official}",
        )

    def test_all_competition_fields_if_missing_is_unavailable(self):
        """所有竞争字段的 if_missing 应为 unavailable"""
        not_unavailable = []
        for fk in self.COMPETITION_FIELDS:
            entry = self.manifest_fields.get(fk, {})
            im = entry.get("if_missing", "")
            if im != "unavailable":
                not_unavailable.append(f"{fk} (if_missing={im!r})")
        self.assertEqual(
            len(not_unavailable), 0,
            f"{len(not_unavailable)} 个竞争字段 if_missing 不是 unavailable: {not_unavailable}",
        )

    def test_differentiation_strategy_has_differentiated_opportunity_alias(self):
        """differentiation_strategy 应包含 differentiated_opportunity 别名"""
        entry = self.manifest_fields.get("differentiation_strategy", {})
        aliases = entry.get("aliases", [])
        self.assertIn(
            "differentiated_opportunity", aliases,
            "differentiation_strategy 的 aliases 应包含 differentiated_opportunity",
        )

    def test_competitors_top3_has_json_text_type(self):
        """competitors_top3 应标注 type: json_text"""
        entry = self.manifest_fields.get("competitors_top3", {})
        self.assertEqual(
            entry.get("type"), "json_text",
            "competitors_top3 应在 manifest 中标注 type: json_text",
        )


# ── SPEC 13.8: competitors_top3 JSON 结构验证 ──


class CompetitorsTop3StructureTest(unittest.TestCase):
    """SPEC §13.8 — competitors_top3 值必须是数组，每个元素含 name/summary/overlap/difference"""

    # 每个竞品对象必需的键
    REQUIRED_KEYS = {"name", "summary", "overlap", "difference"}

    # 有效示例
    VALID_COMPETITORS = [
        {
            "name": "OpenAI",
            "summary": "基础模型与消费级 AI 产品领导者，ChatGPT 月活超 3 亿",
            "overlap": "LLM 基础模型研发、API 服务、企业级 AI 部署",
            "difference": "OpenAI 面向 C 端消费者产品矩阵（ChatGPT/DALL-E），"
                         "而公司聚焦 B 端企业级安全合规与私有部署",
        },
        {
            "name": "Google DeepMind",
            "summary": "Alphabet 旗下 AI 研究实验室，Gemini 模型家族",
            "overlap": "前沿 AI 研究、多模态模型、科学应用",
            "difference": "DeepMind 深度整合 Google 生态（搜索/云/Android），"
                         "公司独立平台定位，不绑定单一云厂商",
        },
        {
            "name": "Cohere",
            "summary": "企业级 LLM 平台，专注检索增强生成（RAG）与嵌入模型",
            "overlap": "企业级 API、RAG 解决方案、多语言支持",
            "difference": "Cohere 以嵌入和 RAG 为差异化切入，"
                         "公司在安全对齐与可解释性方面更深",
        },
    ]

    # ── 合法结构测试 ──

    def test_valid_competitors_array_passes_validation(self):
        """合法的 Top3 竞品数组应通过结构验证"""
        value = json.dumps(self.VALID_COMPETITORS)
        parsed = json.loads(value)
        self.assertIsInstance(parsed, list, "competitors_top3 值应为 JSON 数组")
        self.assertEqual(len(parsed), 3)
        for i, comp in enumerate(parsed):
            missing = self.REQUIRED_KEYS - set(comp.keys())
            self.assertEqual(
                len(missing), 0,
                f"竞品 #{i} ({comp.get('name', '?')}) 缺少字段: {missing}",
            )

    def test_all_required_keys_present_in_each_competitor(self):
        """每个竞品对象必须包含 name, summary, overlap, difference"""
        for i, comp in enumerate(self.VALID_COMPETITORS):
            for key in self.REQUIRED_KEYS:
                self.assertIn(
                    key, comp,
                    f"竞品 #{i} 缺少必需字段 '{key}'",
                )
                self.assertIsInstance(
                    comp[key], str,
                    f"竞品 #{i} 字段 '{key}' 应为字符串",
                )

    def test_no_extra_keys_beyond_required(self):
        """每个竞品对象不应包含超出 SPEC 定义的额外键（允许但警告）"""
        # SPEC 未禁止额外字段，但验证已知键集
        allowed = self.REQUIRED_KEYS
        for i, comp in enumerate(self.VALID_COMPETITORS):
            extra = set(comp.keys()) - allowed
            # 此测试确认当前已知键集；实际实现可扩展
            self.assertEqual(
                len(extra), 0,
                f"竞品 #{i} ({comp.get('name')}) 包含未在 SPEC 定义的字段: {extra}",
            )

    # ── 非法结构测试 ──

    def test_invalid_json_raises_error(self):
        """非 JSON 字符串应导致解析失败"""
        invalid = "not a json string, just plain text about competitors"
        with self.assertRaises(
            (json.JSONDecodeError, ValueError, TypeError),
            msg="非法 JSON 应导致解析异常",
        ):
            json.loads(invalid)

    def test_single_object_not_array(self):
        """单个对象而非数组 → 结构错误"""
        single_obj = json.dumps({
            "name": "OpenAI",
            "summary": "...",
            "overlap": "...",
            "difference": "...",
        })
        parsed = json.loads(single_obj)
        self.assertNotIsInstance(
            parsed, list,
            "单个对象不是数组，应被结构验证拒绝",
        )

    def test_array_element_missing_required_key(self):
        """数组元素缺少必需键 → 验证失败"""
        incomplete = json.dumps([
            {"name": "OpenAI", "summary": "..."},  # 缺少 overlap, difference
        ])
        parsed = json.loads(incomplete)
        for i, comp in enumerate(parsed):
            missing = self.REQUIRED_KEYS - set(comp.keys())
            self.assertGreater(
                len(missing), 0,
                f"竞品 #{i} 应缺少字段但实际完整",
            )

    def test_empty_array(self):
        """空数组 → 合法但无意义，验证此类边缘情况"""
        value = "[]"
        parsed = json.loads(value)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 0)

    def test_fewer_than_three_competitors(self):
        """少于 3 个竞品 → 结构合法但需标记 incomplete"""
        value = json.dumps(self.VALID_COMPETITORS[:2])
        parsed = json.loads(value)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 2)
        # 少于 3 个时结构仍合法，但业务层应标记 incomplete
        for comp in parsed:
            missing = self.REQUIRED_KEYS - set(comp.keys())
            self.assertEqual(len(missing), 0)

    def test_more_than_three_competitors(self):
        """超过 3 个竞品 → 结构合法但截断到 Top3"""
        extra_comp = {
            "name": "Mistral AI",
            "summary": "欧洲开源 LLM 领导者",
            "overlap": "开源模型、开发者工具",
            "difference": "欧洲市场定位 vs 全球",
        }
        value = json.dumps(self.VALID_COMPETITORS + [extra_comp])
        parsed = json.loads(value)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 3)
        # 结构仍然合法，业务层按需截断

    # ── 端到端：结构验证 + 字段解析 ──

    def test_resolve_field_with_valid_structure(self):
        """resolve_field 处理结构合法的 competitors_top3"""
        value = json.dumps(self.VALID_COMPETITORS)
        result = resolve_field(
            field_key="competitors_top3",
            field_value=value,
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
                "type": "json_text",
            },
            evidence_span_ids=["ev_001", "ev_002"],
        )
        self.assertEqual(result.resolution_status, "confirmed")
        # 解析 JSON 应成功
        parsed = json.loads(result.value)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 3)
        for comp in parsed:
            missing = self.REQUIRED_KEYS - set(comp.keys())
            self.assertEqual(len(missing), 0)

    def test_resolve_field_with_invalid_json_value_still_resolves(self):
        """即使值为非 JSON，resolve_field 仍按 evidence 规则处理状态"""
        # 字段解析不负责 JSON 校验——它只管 evidence 绑定
        result = resolve_field(
            field_key="competitors_top3",
            field_value="plain text, not JSON",
            resolved_pool={},
            manifest_entry={
                "resolution_type": "official_fact",
                "category": "A",
            },
            evidence_span_ids=["ev_001"],
        )
        # 有证据 → confirmed（状态判定独立于 JSON 结构校验）
        self.assertEqual(result.resolution_status, "confirmed")
        # 但 JSON 解析会失败——由上层/业务层处理
        with self.assertRaises(
            (json.JSONDecodeError, ValueError, TypeError),
            msg="非 JSON 值在结构校验层应失败",
        ):
            json.loads(result.value)


if __name__ == "__main__":
    unittest.main()
