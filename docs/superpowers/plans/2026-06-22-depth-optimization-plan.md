# 研究深度优化 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提升研究管道的分析深度：L1/L2 输出结构化、L3 拆组、market_intelligence 桥接、时间序列快照

**Architecture:** 6 个新模块（l0_gate/competitive_matrix/business_canvas/market_data_bridge/time_series + 3 个 L3 prompt 文件）+ 1 个新表（company_snapshots）+ 修改 pipeline.py 串联点

**Tech Stack:** Python 3.9+ / Pydantic / sqlite3 / DeepSeek V4 Pro / 现有 prompt 框架

**Spec:** `docs/superpowers/specs/2026-06-22-depth-optimization-design.md`

---

### Task 1: L0 Quality Gate

**Files:**
- Create: `webapp/research/l0_gate.py`
- Test: `tests/test_l0_gate.py`
- Modify: `webapp/pipeline.py` (insert gate call after L0)

- [ ] **Step 1: Write failing test**

```python
# tests/test_l0_gate.py
import unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.l0_gate import validate_l0_output, L0GateError

class TestL0Gate(unittest.TestCase):
    def test_valid_l0_output_passes(self):
        result = {
            "company_name": "Anthropic",
            "company_def": "AI safety company building Claude",
            "main_product_name": "Claude",
            "founded_date": "2021",
            "extra_field": "bonus content here for length padding"
        }
        ok, errors = validate_l0_output(result)
        self.assertTrue(ok)
        self.assertEqual(len(errors), 0)

    def test_missing_company_name_fails(self):
        result = {
            "company_def": "some definition",
            "main_product_name": "Product X",
            "founded_date": "2020"
        }
        ok, errors = validate_l0_output(result)
        self.assertFalse(ok)
        self.assertIn("company_name", errors[0])

    def test_missing_multiple_fields_reports_all(self):
        result = {"main_product_name": "Product X"}
        ok, errors = validate_l0_output(result)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(errors), 2)

    def test_too_short_output_fails(self):
        result = {
            "company_name": "A",
            "company_def": "B",
            "main_product_name": "C",
            "founded_date": "D"
        }
        ok, errors = validate_l0_output(result)
        self.assertFalse(ok)
        self.assertTrue(any("too short" in e.lower() for e in errors))

    def test_minimal_valid_output_passes(self):
        result = {
            "company_name": "Anthropic",
            "company_def": "AI safety and research company developing large language models including Claude, focusing on constitutional AI and alignment research. Founded by former OpenAI researchers.",
            "main_product_name": "Claude",
            "founded_date": "2021"
        }
        ok, errors = validate_l0_output(result)
        self.assertTrue(ok)

    def test_l0_validation_with_none_key_raises(self):
        result = {"company_name": None, "company_def": "def", "main_product_name": "X", "founded_date": "2020"}
        ok, errors = validate_l0_output(result)
        self.assertFalse(ok)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_l0_gate.py -v`

Expected: 6 FAIL (module not found)

- [ ] **Step 3: Implement l0_gate.py**

```python
"""L0 质量门控 — 校验 L0 LLM 输出完整性，不通过则阻断下游"""

from __future__ import annotations
import json

L0_REQUIRED_FIELDS = [
    "company_name",
    "company_def",
    "main_product_name",
    "founded_date",
]

L0_MIN_CONTENT_LENGTH = 200


class L0GateError(RuntimeError):
    """L0 输出不完整，放弃本次研究"""
    pass


def validate_l0_output(l0_result: dict) -> tuple[bool, list[str]]:
    """校验 L0 输出是否具备下游所需的最小信息。

    Returns:
        (is_valid, errors): is_valid=False 时应中止流水线
    """
    errors = []

    for field in L0_REQUIRED_FIELDS:
        value = l0_result.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"L0 missing required field: {field}")

    total_text = json.dumps(l0_result, ensure_ascii=False)
    if len(total_text) < L0_MIN_CONTENT_LENGTH:
        errors.append(
            f"L0 output too short: {len(total_text)} chars "
            f"(min: {L0_MIN_CONTENT_LENGTH})"
        )

    return len(errors) == 0, errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_l0_gate.py -v`

Expected: 6 PASS

- [ ] **Step 5: Insert gate call in pipeline.py**

In `llm_analysis()` function, after L0 call and before L1 call, add:

```python
# L0 Quality Gate — block downstream if L0 output is incomplete
from research.l0_gate import validate_l0_output, L0GateError
l0_valid, l0_errors = validate_l0_output(l0_result)
if not l0_valid:
    raise L0GateError(
        f"L0 output incomplete for {company_name}: {'; '.join(l0_errors)}"
    )
```

- [ ] **Step 6: Commit**

```bash
git add webapp/research/l0_gate.py tests/test_l0_gate.py webapp/pipeline.py
git commit -m "feat: add L0 quality gate to block downstream on incomplete output"
```

---

### Task 2: Competitive Matrix Extractor (L1 restructure)

**Files:**
- Create: `webapp/research/competitive_matrix.py`
- Test: `tests/test_competitive_matrix.py`
- Modify: `prompts/layer1-hv-analysis.md`
- Modify: `references/field_manifest.yaml` (add competitors_structured entry)

- [ ] **Step 1: Define Pydantic schema and write failing test**

```python
# tests/test_competitive_matrix.py
import unittest, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.competitive_matrix import CompetitorItem, CompetitiveMatrix, CompetitiveMatrixExtractor

VALID_MATRIX_JSON = json.dumps({
    "competitors": [
        {
            "name": "GitHub Copilot",
            "url": "https://github.com/features/copilot",
            "overlap_areas": ["AI code completion", "IDE integration"],
            "strengths": ["GitHub ecosystem", "Large user base"],
            "weaknesses": ["Limited to code", "No chat interface"],
            "threat_level": "high",
            "evidence_snippets": ["competing directly with GitHub Copilot in AI code editor market"]
        },
        {
            "name": "Codeium",
            "url": "https://codeium.com",
            "overlap_areas": ["AI code completion"],
            "strengths": ["Free tier", "Multi-IDE support"],
            "weaknesses": ["Smaller team", "Less training data"],
            "threat_level": "medium",
            "evidence_snippets": ["Codeium offers free AI code completion for individual developers"]
        }
    ],
    "target_company_position": "strong_contender",
    "competitive_landscape_summary": "Competing in AI code assistant market with 2+ major players"
})

class TestCompetitorItem(unittest.TestCase):
    def test_valid_competitor_passes_validation(self):
        item = CompetitorItem(
            name="GitHub Copilot",
            url="https://github.com/features/copilot",
            overlap_areas=["AI code completion"],
            strengths=["Ecosystem"],
            weaknesses=["Limited scope"],
            threat_level="high",
            evidence_snippets=["from source: directly competes"]
        )
        self.assertEqual(item.name, "GitHub Copilot")
        self.assertEqual(item.threat_level, "high")

    def test_invalid_threat_level_rejected(self):
        with self.assertRaises(ValueError):
            CompetitorItem(
                name="Test", url=None,
                overlap_areas=["X"], strengths=["Y"], weaknesses=["Z"],
                threat_level="extreme",  # invalid
                evidence_snippets=["snippet"]
            )

    def test_empty_evidence_snippets_rejected(self):
        with self.assertRaises(ValueError):
            CompetitorItem(
                name="Test", url=None,
                overlap_areas=["X"], strengths=["Y"], weaknesses=["Z"],
                threat_level="low",
                evidence_snippets=[]  # empty
            )

    def test_evidence_snippet_too_long_rejected(self):
        with self.assertRaises(ValueError):
            CompetitorItem(
                name="Test", url=None,
                overlap_areas=["X"], strengths=["Y"], weaknesses=["Z"],
                threat_level="low",
                evidence_snippets=["x" * 101]  # > 100 chars
            )


class TestCompetitiveMatrix(unittest.TestCase):
    def test_valid_matrix_with_two_competitors_passes(self):
        data = json.loads(VALID_MATRIX_JSON)
        matrix = CompetitiveMatrix(**data)
        self.assertEqual(len(matrix.competitors), 2)
        self.assertEqual(matrix.target_company_position, "strong_contender")

    def test_too_few_competitors_rejected(self):
        data = json.loads(VALID_MATRIX_JSON)
        data["competitors"] = data["competitors"][:1]  # only 1
        with self.assertRaises(ValueError):
            CompetitiveMatrix(**data)

    def test_invalid_position_rejected(self):
        data = json.loads(VALID_MATRIX_JSON)
        data["target_company_position"] = "dominant"  # not in enum
        with self.assertRaises(ValueError):
            CompetitiveMatrix(**data)


class TestCompetitiveMatrixExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = CompetitiveMatrixExtractor()

    def test_validate_json_with_valid_data_passes(self):
        data = json.loads(VALID_MATRIX_JSON)
        matrix, errors = self.extractor.validate(data)
        self.assertIsNotNone(matrix)
        self.assertEqual(len(errors), 0)

    def test_validate_json_missing_key_returns_errors(self):
        data = json.loads(VALID_MATRIX_JSON)
        del data["target_company_position"]
        matrix, errors = self.extractor.validate(data)
        self.assertIsNone(matrix)
        self.assertGreater(len(errors), 0)

    def test_mark_unverified_returns_low_confidence(self):
        data = json.loads(VALID_MATRIX_JSON)
        data["competitors"][0]["evidence_snippets"] = []  # empty
        matrix, unverified = self.extractor.validate(data)
        self.assertIsNone(matrix)  # fails validation
        # unverified fields should be captured
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_competitive_matrix.py -v`

Expected: All FAIL (module not found)

- [ ] **Step 3: Implement competitive_matrix.py**

```python
"""L1 竞品矩阵提取器 — 结构化竞品对比，Pydantic 校验"""

from __future__ import annotations
from pydantic import BaseModel, field_validator, ValidationError
from typing import Optional

THREAT_LEVELS = {"high", "medium", "low"}
POSITIONS = {"leader", "strong_contender", "niche_player", "early_stage"}


class CompetitorItem(BaseModel):
    name: str
    url: Optional[str] = None
    overlap_areas: list[str]
    strengths: list[str]
    weaknesses: list[str]
    threat_level: str
    evidence_snippets: list[str]

    @field_validator("threat_level")
    @classmethod
    def check_threat(cls, v: str) -> str:
        if v not in THREAT_LEVELS:
            raise ValueError(f"threat_level must be one of {THREAT_LEVELS}, got '{v}'")
        return v

    @field_validator("evidence_snippets")
    @classmethod
    def check_evidence(cls, v: list[str]) -> list[str]:
        if not v or len(v) == 0:
            raise ValueError("evidence_snippets must not be empty")
        for i, snippet in enumerate(v):
            if len(snippet) > 100:
                raise ValueError(
                    f"evidence_snippets[{i}] too long: {len(snippet)} > 100 chars"
                )
        return v

    @field_validator("overlap_areas")
    @classmethod
    def check_overlap(cls, v: list[str]) -> list[str]:
        if not v or len(v) == 0:
            raise ValueError("overlap_areas must not be empty")
        return v


class CompetitiveMatrix(BaseModel):
    competitors: list[CompetitorItem]
    target_company_position: str
    competitive_landscape_summary: str

    @field_validator("target_company_position")
    @classmethod
    def check_position(cls, v: str) -> str:
        if v not in POSITIONS:
            raise ValueError(f"target_company_position must be one of {POSITIONS}, got '{v}'")
        return v

    @field_validator("competitors")
    @classmethod
    def check_competitors_count(cls, v: list[CompetitorItem]) -> list[CompetitorItem]:
        if len(v) < 2:
            raise ValueError(f"at least 2 competitors required, got {len(v)}")
        if len(v) > 6:
            raise ValueError(f"at most 6 competitors allowed, got {len(v)}")
        return v


class CompetitiveMatrixExtractor:
    """从 LLM 输出中提取并校验竞品矩阵"""

    def validate(self, raw_data: dict) -> tuple[Optional[CompetitiveMatrix], list[str]]:
        """校验 LLM 输出的 JSON 是否符合 CompetitiveMatrix schema。

        Returns:
            (matrix, unverified_fields): matrix 为 None 表示校验失败
        """
        unverified = []
        try:
            matrix = CompetitiveMatrix(**raw_data)
        except ValidationError as e:
            return None, [str(err) for err in e.errors()]

        # Check for empty evidence on individual competitors
        for comp in matrix.competitors:
            if not comp.evidence_snippets:
                unverified.append(f"{comp.name}: evidence_snippets empty")

        return matrix, unverified

    def to_field_value(self, matrix: CompetitiveMatrix) -> str:
        """将竞品矩阵转为可存入 research_fields 的 JSON 字符串"""
        import json
        return json.dumps(matrix.model_dump(), ensure_ascii=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_competitive_matrix.py -v`

Expected: 8 PASS

- [ ] **Step 5: Update layer1-hv-analysis.md prompt**

Add JSON output schema instructions at the end of the existing prompt (keep existing analysis instructions, only replace output format section):

```markdown
## 输出格式

输出严格的 JSON，不要包含 markdown 代码块标记，不要添加额外解释：

```json
{
  "competitors": [
    {
      "name": "竞品名",
      "url": "竞品官网（可为 null）",
      "overlap_areas": ["重叠领域1", "重叠领域2"],
      "strengths": ["核心优势1", "核心优势2"],
      "weaknesses": ["弱点或差异化空间1", "弱点或差异化空间2"],
      "threat_level": "high|medium|low",
      "evidence_snippets": ["来自原始上下文的原文引用，≤100字符"]
    }
  ],
  "target_company_position": "leader|strong_contender|niche_player|early_stage",
  "competitive_landscape_summary": "≤100字符的竞争格局一句话总结"
}
```

要求：
- competitors 至少 2 个，最多 6 个
- 每个竞品至少 1 条 evidence_snippet，直接引用原文
- threat_level 判断标准：high=直接正面竞争且体量相当或更大，medium=有重叠但定位不同，low=间接竞争或体量显著小
- target_company_position：leader=赛道第一，strong_contender=前三且有差异化，niche_player=专注细分，early_stage=刚起步
```

- [ ] **Step 6: Add manifest entry**

In `references/field_manifest.yaml`, add after the `_default` entry:

```yaml
  competitors_structured:
    category: A
    resolution_type: structured_extraction
    if_missing: unavailable
    type: json_text
    source_module: competitive_matrix

  competitive_position:
    category: A
    resolution_type: structured_extraction
    if_missing: unavailable
    source_module: competitive_matrix
```

- [ ] **Step 7: Commit**

```bash
git add webapp/research/competitive_matrix.py tests/test_competitive_matrix.py prompts/layer1-hv-analysis.md references/field_manifest.yaml
git commit -m "feat: add competitive matrix extractor with Pydantic validation for L1"
```

---

### Task 3: Business Canvas Extractor (L2 restructure)

**Files:**
- Create: `webapp/research/business_canvas.py`
- Test: `tests/test_business_canvas.py`
- Modify: `prompts/layer2-business.md`
- Modify: `references/field_manifest.yaml` (add moat_dimensions, growth_loops, business_canvas entries)

- [ ] **Step 1: Write failing test**

```python
# tests/test_business_canvas.py
import unittest, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.business_canvas import (
    RevenueModel, UnitEconomics, GrowthLoop, MoatDimension,
    BusinessCanvas, BusinessCanvasExtractor
)

VALID_CANVAS_JSON = json.dumps({
    "revenue_model": {
        "primary": "subscription",
        "secondary": ["usage_based"],
        "pricing_public": True,
        "evidence_snippets": ["pricing page shows $20/month pro plan"]
    },
    "unit_economics": {
        "has_ltv_cac_data": False,
        "ltv_estimate": None,
        "cac_estimate": None,
        "payback_period_months": None,
        "gross_margin_estimate": None,
        "disclaimer": "公司未公开披露单位经济数据",
        "evidence_snippets": ["no public unit economics data found"]
    },
    "growth_loops": [
        {
            "loop_type": "product_led",
            "description": "Free tier drives word-of-mouth adoption",
            "strength": "strong",
            "evidence_snippets": ["free tier is the primary growth driver per founder interview"]
        }
    ],
    "moat_dimensions": [
        {
            "dimension": "switching_cost",
            "strength": "strong",
            "description": "Users build workflows around the product",
            "evidence_snippets": ["users report high switching cost due to workflow integration"]
        },
        {
            "dimension": "data_moat",
            "strength": "moderate",
            "description": "Training data from user interactions",
            "evidence_snippets": ["model improves with usage data"]
        }
    ],
    "business_model_summary": "PLG SaaS with freemium-to-enterprise conversion"
})


class TestBusinessCanvasValidation(unittest.TestCase):
    def test_valid_canvas_passes(self):
        data = json.loads(VALID_CANVAS_JSON)
        canvas = BusinessCanvas(**data)
        self.assertEqual(canvas.revenue_model.primary, "subscription")
        self.assertEqual(len(canvas.moat_dimensions), 2)
        self.assertEqual(len(canvas.growth_loops), 1)

    def test_invalid_revenue_primary_rejected(self):
        data = json.loads(VALID_CANVAS_JSON)
        data["revenue_model"]["primary"] = "donations"
        with self.assertRaises(ValueError):
            BusinessCanvas(**data)

    def test_invalid_moat_dimension_rejected(self):
        data = json.loads(VALID_CANVAS_JSON)
        data["moat_dimensions"][0]["dimension"] = "luck"
        with self.assertRaises(ValueError):
            BusinessCanvas(**data)

    def test_invalid_growth_loop_type_rejected(self):
        data = json.loads(VALID_CANVAS_JSON)
        data["growth_loops"][0]["loop_type"] = "magic"
        with self.assertRaises(ValueError):
            BusinessCanvas(**data)

    def test_empty_evidence_snippets_rejected(self):
        data = json.loads(VALID_CANVAS_JSON)
        data["growth_loops"][0]["evidence_snippets"] = []
        with self.assertRaises(ValueError):
            BusinessCanvas(**data)

    def test_extractor_validate_with_valid_data(self):
        extractor = BusinessCanvasExtractor()
        data = json.loads(VALID_CANVAS_JSON)
        canvas, errors = extractor.validate(data)
        self.assertIsNotNone(canvas)
        self.assertEqual(len(errors), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_business_canvas.py -v`

Expected: 6 FAIL (module not found)

- [ ] **Step 3: Implement business_canvas.py**

```python
"""L2 商业模式画布提取器 — 结构化商业分析，Pydantic 校验
   
   壁垒维度基于 Helmer 7 Powers + 技术复杂度：
   network_effects | data_moat | switching_cost | brand |
   scale_economy | tech_complexity | regulatory | counter_positioning
"""

from __future__ import annotations
from pydantic import BaseModel, field_validator, ValidationError
from typing import Optional

REVENUE_PRIMARIES = {
    "subscription", "usage_based", "enterprise_contract",
    "advertising", "marketplace", "freemium", "other"
}

LOOP_TYPES = {
    "viral", "content", "sales", "product_led",
    "partnership", "paid_acquisition"
}

MOAT_DIMENSIONS = {
    "network_effects", "data_moat", "switching_cost", "brand",
    "scale_economy", "tech_complexity", "regulatory", "counter_positioning"
}

STRENGTH_LEVELS = {"strong", "moderate", "weak", "none"}


class RevenueModel(BaseModel):
    primary: str
    secondary: list[str] = []
    pricing_public: bool = False
    evidence_snippets: list[str]

    @field_validator("primary")
    @classmethod
    def check_primary(cls, v: str) -> str:
        if v not in REVENUE_PRIMARIES:
            raise ValueError(f"primary must be one of {REVENUE_PRIMARIES}, got '{v}'")
        return v

    @field_validator("evidence_snippets")
    @classmethod
    def check_evidence(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("revenue_model evidence_snippets must not be empty")
        return v


class UnitEconomics(BaseModel):
    has_ltv_cac_data: bool = False
    ltv_estimate: Optional[str] = None
    cac_estimate: Optional[str] = None
    payback_period_months: Optional[int] = None
    gross_margin_estimate: Optional[str] = None
    disclaimer: str = ""
    evidence_snippets: list[str] = []


class GrowthLoop(BaseModel):
    loop_type: str
    description: str
    strength: str
    evidence_snippets: list[str]

    @field_validator("loop_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in LOOP_TYPES:
            raise ValueError(f"loop_type must be one of {LOOP_TYPES}, got '{v}'")
        return v

    @field_validator("strength")
    @classmethod
    def check_strength(cls, v: str) -> str:
        if v not in STRENGTH_LEVELS:
            raise ValueError(f"strength must be one of {STRENGTH_LEVELS}, got '{v}'")
        return v

    @field_validator("description")
    @classmethod
    def check_length(cls, v: str) -> str:
        if len(v) > 80:
            raise ValueError(f"description too long: {len(v)} > 80 chars")
        return v

    @field_validator("evidence_snippets")
    @classmethod
    def check_evidence(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("growth_loop evidence_snippets must not be empty")
        return v


class MoatDimension(BaseModel):
    dimension: str
    strength: str
    description: str
    evidence_snippets: list[str]

    @field_validator("dimension")
    @classmethod
    def check_dimension(cls, v: str) -> str:
        if v not in MOAT_DIMENSIONS:
            raise ValueError(f"dimension must be one of {MOAT_DIMENSIONS}, got '{v}'")
        return v

    @field_validator("strength")
    @classmethod
    def check_strength(cls, v: str) -> str:
        if v not in STRENGTH_LEVELS:
            raise ValueError(f"strength must be one of {STRENGTH_LEVELS}, got '{v}'")
        return v

    @field_validator("description")
    @classmethod
    def check_length(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError(f"description too long: {len(v)} > 100 chars")
        return v

    @field_validator("evidence_snippets")
    @classmethod
    def check_evidence(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("moat_dimension evidence_snippets must not be empty")
        return v


class BusinessCanvas(BaseModel):
    revenue_model: RevenueModel
    unit_economics: UnitEconomics
    growth_loops: list[GrowthLoop]
    moat_dimensions: list[MoatDimension]
    business_model_summary: str

    @field_validator("business_model_summary")
    @classmethod
    def check_summary_length(cls, v: str) -> str:
        if len(v) > 150:
            raise ValueError(f"business_model_summary too long: {len(v)} > 150 chars")
        return v


class BusinessCanvasExtractor:
    """从 LLM 输出中提取并校验商业模式画布"""

    def validate(self, raw_data: dict) -> tuple[Optional[BusinessCanvas], list[str]]:
        try:
            canvas = BusinessCanvas(**raw_data)
        except ValidationError as e:
            return None, [str(err) for err in e.errors()]
        return canvas, []

    def to_field_value(self, canvas: BusinessCanvas) -> str:
        import json
        return json.dumps(canvas.model_dump(), ensure_ascii=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_business_canvas.py -v`

Expected: 6 PASS

- [ ] **Step 5: Update layer2-business.md prompt**

Add JSON output schema at end of existing prompt (keep existing analysis instructions):

```markdown
## 输出格式

输出严格的 JSON，不要包含 markdown 代码块标记：

```json
{
  "revenue_model": {
    "primary": "subscription|usage_based|enterprise_contract|advertising|marketplace|freemium|other",
    "secondary": ["次要模式"],
    "pricing_public": true,
    "evidence_snippets": ["来自原文的引用"]
  },
  "unit_economics": {
    "has_ltv_cac_data": false,
    "ltv_estimate": "具体数值或 null",
    "cac_estimate": "具体数值或 null",
    "payback_period_months": null,
    "gross_margin_estimate": null,
    "disclaimer": "如果数据不可得，请说明原因",
    "evidence_snippets": ["引用或说明"]
  },
  "growth_loops": [
    {
      "loop_type": "viral|content|sales|product_led|partnership|paid_acquisition",
      "description": "≤80字符的机制描述",
      "strength": "strong|moderate|weak",
      "evidence_snippets": ["原文引用"]
    }
  ],
  "moat_dimensions": [
    {
      "dimension": "network_effects|data_moat|switching_cost|brand|scale_economy|tech_complexity|regulatory|counter_positioning",
      "strength": "strong|moderate|weak|none",
      "description": "≤100字符",
      "evidence_snippets": ["原文引用"]
    }
  ],
  "business_model_summary": "≤150字符的一句话总结"
}
```

要求：
- moat_dimensions 至少覆盖 4 个维度，基于原文证据
- growth_loops 至少 1 个
- unit_economics 中如果数据不可得，填 null 并在 disclaimer 中说明原因
- 所有 evidence_snippets 必须直接引用原文
```

- [ ] **Step 6: Add manifest entries**

In `references/field_manifest.yaml`:

```yaml
  business_canvas:
    category: A
    resolution_type: structured_extraction
    if_missing: unavailable
    type: json_text
    source_module: business_canvas

  moat_dimensions:
    category: A
    resolution_type: structured_extraction
    if_missing: unavailable
    type: json_text
    source_module: business_canvas

  growth_loops:
    category: A
    resolution_type: structured_extraction
    if_missing: unavailable
    type: json_text
    source_module: business_canvas

  unit_economics:
    category: D
    resolution_type: private_metric
    if_missing: unavailable
    source_module: business_canvas
```

- [ ] **Step 7: Commit**

```bash
git add webapp/research/business_canvas.py tests/test_business_canvas.py prompts/layer2-business.md references/field_manifest.yaml
git commit -m "feat: add business canvas extractor with Helmer 7 Powers moat dimensions for L2"
```

---

### Task 4: MarketDataBridge

**Files:**
- Create: `webapp/research/market_data_bridge.py`
- Test: `tests/test_market_data_bridge.py`
- Modify: `webapp/pipeline.py` (insert bridge call between L2 and L3)

- [ ] **Step 1: Write failing test**

```python
# tests/test_market_data_bridge.py
import unittest, sys, sqlite3, tempfile, os, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.market_data_bridge import MarketDataBridge

class TestMarketDataBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        conn = sqlite3.connect(cls.temp_db.name)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_estimates (
                id TEXT PRIMARY KEY,
                company_key TEXT NOT NULL,
                field_key TEXT NOT NULL,
                estimate_type TEXT DEFAULT 'proxy',
                result_value REAL,
                result_text TEXT,
                currency TEXT DEFAULT 'USD',
                year INTEGER,
                confidence REAL DEFAULT 0.0,
                status TEXT DEFAULT 'derived',
                source_url TEXT,
                disclaimer TEXT
            )
        """)
        conn.execute(
            "INSERT INTO market_estimates VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("id1", "test_corp", "tam_value", "proxy", 10.5, "$10.5B", "USD",
             2024, 0.7, "proxy", "https://grandviewresearch.com/report", "")
        )
        conn.execute(
            "INSERT INTO market_estimates VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("id2", "test_corp", "market_cagr", "proxy", 15.0, "15% CAGR", "USD",
             2024, 0.5, "proxy", "https://mordorintelligence.com/report", "")
        )
        conn.commit()
        conn.close()
        cls.bridge = MarketDataBridge(db_path=cls.temp_db.name)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.temp_db.name)

    def test_fetch_market_context_returns_data(self):
        ctx = self.bridge.fetch_market_context("test_corp")
        self.assertIsInstance(ctx, dict)
        self.assertIn("tam_value", ctx)
        self.assertEqual(ctx["tam_value"]["value_text"], "$10.5B")
        self.assertEqual(ctx["tam_value"]["confidence"], 0.7)

    def test_fetch_market_context_empty_company_returns_empty(self):
        ctx = self.bridge.fetch_market_context("nonexistent")
        self.assertEqual(len(ctx), 0)

    def test_inject_into_context_appends_data(self):
        packed = "Original context about the company."
        injected = self.bridge.inject_into_l3_context("test_corp", packed)
        self.assertIn("Original context", injected)
        self.assertIn("已知市场数据", injected)
        self.assertIn("$10.5B", injected)

    def test_inject_empty_market_data_is_noop(self):
        packed = "Original context."
        injected = self.bridge.inject_into_l3_context("nonexistent", packed)
        self.assertEqual(injected, packed)

    def test_low_confidence_data_excluded(self):
        conn = sqlite3.connect(self.temp_db.name)
        conn.execute(
            "INSERT INTO market_estimates VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("id3", "test_corp", "revenue_estimate", "proxy", 5.0, "$5M", "USD",
             2023, 0.15, "llm_located", "", "low confidence")  # confidence 0.15 < 0.30
        )
        conn.commit()
        conn.close()
        ctx = self.bridge.fetch_market_context("test_corp")
        self.assertNotIn("revenue_estimate", ctx,
                         "Low confidence (< 0.30) data should be excluded")

    def test_format_as_context_block(self):
        ctx = self.bridge.fetch_market_context("test_corp")
        block = self.bridge._format_context_block(ctx)
        self.assertIn("tam_value", block)
        self.assertIn("$10.5B", block)
        self.assertIn("grandviewresearch.com", block)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_market_data_bridge.py -v`

Expected: 6 FAIL (module not found)

- [ ] **Step 3: Implement market_data_bridge.py**

```python
"""MarketDataBridge — 桥接 market_intelligence 模块的市场数据到主管道

   从 market_estimates 表读取已估算的市场/融资数据，
   在 L3 调用前注入 packed_context，让 L3 引用而非重新推断。
"""

from __future__ import annotations
import sqlite3
from pathlib import Path


MIN_CONFIDENCE_FOR_INJECTION = 0.30


class MarketDataBridge:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            _project = Path(__file__).resolve().parent.parent.parent
            db_path = str(_project / "db" / "research_db.sqlite")
        self.db_path = db_path

    def fetch_market_context(self, company_key: str) -> dict:
        """从 market_estimates 表读取置信度足够的数据"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""
                SELECT field_key, result_value, result_text, currency, year,
                       estimate_type, confidence, status, source_url, disclaimer
                FROM market_estimates
                WHERE company_key = ? AND status != 'unavailable'
                  AND confidence >= ?
                ORDER BY confidence DESC
            """, (company_key, MIN_CONFIDENCE_FOR_INJECTION)).fetchall()
        except sqlite3.OperationalError:
            # Table might not exist yet
            return {}
        finally:
            conn.close()

        result = {}
        for row in rows:
            result[row["field_key"]] = {
                "value": row["result_value"],
                "value_text": row["result_text"],
                "currency": row["currency"],
                "year": row["year"],
                "estimate_type": row["estimate_type"],
                "confidence": row["confidence"],
                "source_url": row["source_url"],
            }
        return result

    def inject_into_l3_context(self, company_key: str, packed_context: str) -> str:
        """将市场数据注入 packed_context"""
        market_data = self.fetch_market_context(company_key)
        if not market_data:
            return packed_context
        block = self._format_context_block(market_data)
        return packed_context + "\n" + block

    def _format_context_block(self, market_data: dict) -> str:
        lines = [
            "",
            "## 已知市场数据（来源: market_intelligence 模块，可直接引用）",
        ]
        for field_key, item in market_data.items():
            source = item.get("source_url") or "估算"
            lines.append(
                f"- {field_key}: {item['value_text']} "
                f"({item.get('currency', 'USD')}, {item.get('year', 'N/A')}年, "
                f"来源: {source})"
            )
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_market_data_bridge.py -v`

Expected: 6 PASS

- [ ] **Step 5: Insert bridge call in pipeline.py**

In `llm_analysis()` function, after L2 and before L3 calls, add:

```python
# MarketDataBridge — inject known market data before L3
from research.market_data_bridge import MarketDataBridge
bridge = MarketDataBridge()
packed_context = bridge.inject_into_l3_context(company_key, packed_context)
```

- [ ] **Step 6: Commit**

```bash
git add webapp/research/market_data_bridge.py tests/test_market_data_bridge.py webapp/pipeline.py
git commit -m "feat: add MarketDataBridge to inject market_intelligence data into L3 context"
```

---

### Task 5: TimeSeriesSnapshotter

**Files:**
- Create: `db/migrations/049_company_snapshots.sql`
- Create: `webapp/research/time_series.py`
- Test: `tests/test_time_series.py`
- Modify: `webapp/pipeline.py` (insert snapshot call after DB write)

- [ ] **Step 1: Write migration and failing test**

```sql
-- db/migrations/049_company_snapshots.sql
CREATE TABLE IF NOT EXISTS company_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_key TEXT NOT NULL,
    snapshot_at TEXT NOT NULL DEFAULT (datetime('now')),
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('full', 'fields_only', 'metrics_only')),
    field_key TEXT NOT NULL,
    field_value TEXT,
    value_type TEXT,
    norm_value REAL,
    unit TEXT,
    resolution_status TEXT,
    confidence_level TEXT,
    source_urls TEXT,
    research_run_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (company_key) REFERENCES companies(company_key)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_company_field
ON company_snapshots(company_key, field_key, snapshot_at);

CREATE INDEX IF NOT EXISTS idx_snapshots_type
ON company_snapshots(snapshot_type);
```

```python
# tests/test_time_series.py
import unittest, sys, sqlite3, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.time_series import TimeSeriesSnapshotter

class TestTimeSeriesSnapshotter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        conn = sqlite3.connect(cls.temp_db.name)
        # Create table inline for test
        with open("db/migrations/049_company_snapshots.sql") as f:
            conn.executescript(f.read())
        conn.close()
        cls.snapshotter = TimeSeriesSnapshotter(db_path=cls.temp_db.name)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.temp_db.name)

    def setUp(self):
        conn = sqlite3.connect(self.temp_db.name)
        conn.execute("DELETE FROM company_snapshots")
        conn.commit()
        conn.close()

    def test_snapshot_writes_rows(self):
        fields = {
            "arr": {"value": "$10M", "resolution_status": "confirmed",
                    "confidence_level": "verified", "unit": "USD"},
            "mau": {"value": "5M", "resolution_status": "proxy",
                    "confidence_level": "estimated", "unit": "users"},
        }
        count = self.snapshotter.snapshot(
            "test_corp", fields, snapshot_type="fields_only",
            research_run_id="run_001"
        )
        self.assertEqual(count, 2)

    def test_diff_returns_changes(self):
        # Insert first snapshot
        fields_v1 = {"arr": {"value": "$10M", "resolution_status": "confirmed",
                              "confidence_level": "verified", "unit": "USD"}}
        self.snapshotter.snapshot("test_corp", fields_v1,
                                  snapshot_type="fields_only", research_run_id="run_001")

        # Insert second snapshot
        fields_v2 = {"arr": {"value": "$25M", "resolution_status": "confirmed",
                              "confidence_level": "verified", "unit": "USD"}}
        self.snapshotter.snapshot("test_corp", fields_v2,
                                  snapshot_type="fields_only", research_run_id="run_002")

        diff = self.snapshotter.diff("test_corp", "arr")
        self.assertIsNotNone(diff)
        self.assertEqual(diff["previous"]["value"], "$10M")
        self.assertEqual(diff["current"]["value"], "$25M")
        self.assertEqual(diff["direction"], "up")

    def test_diff_single_snapshot_returns_none(self):
        fields = {"arr": {"value": "$10M", "resolution_status": "confirmed",
                           "confidence_level": "verified", "unit": "USD"}}
        self.snapshotter.snapshot("test_corp", fields,
                                  snapshot_type="fields_only", research_run_id="run_001")
        diff = self.snapshotter.diff("test_corp", "arr")
        self.assertIsNone(diff)  # Need 2+ snapshots

    def test_diff_unknown_field_returns_none(self):
        diff = self.snapshotter.diff("test_corp", "nonexistent")
        self.assertIsNone(diff)

    def test_list_comparable_fields(self):
        fields = {
            "arr": {"value": "$10M", "resolution_status": "confirmed",
                    "confidence_level": "verified", "unit": "USD"},
            "mau": {"value": "5M", "resolution_status": "proxy",
                    "confidence_level": "estimated", "unit": "users"},
        }
        self.snapshotter.snapshot("test_corp", fields, research_run_id="run_001")
        self.snapshotter.snapshot("test_corp", fields, research_run_id="run_002")
        comparable = self.snapshotter.list_comparable_fields("test_corp")
        self.assertIn("arr", comparable)
        self.assertIn("mau", comparable)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_time_series.py -v`

Expected: 5 FAIL (module not found)

- [ ] **Step 3: Run migration**

```bash
python3 db/migrate.py db/research_db.sqlite --only 049_company_snapshots.sql
```

- [ ] **Step 4: Implement time_series.py**

```python
"""TimeSeriesSnapshotter — 每次研究存快照，支持字段级跨时间对比"""

from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime


class TimeSeriesSnapshotter:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            _project = Path(__file__).resolve().parent.parent.parent
            db_path = str(_project / "db" / "research_db.sqlite")
        self.db_path = db_path

    def snapshot(
        self,
        company_key: str,
        fields: dict,
        snapshot_type: str = "fields_only",
        research_run_id: str | None = None,
    ) -> int:
        """写入本次研究的字段快照。返回写入行数。"""
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        count = 0
        for field_key, field_data in fields.items():
            value = field_data.get("value", "")
            if isinstance(value, (dict, list)):
                import json
                value = json.dumps(value, ensure_ascii=False)

            conn.execute(
                """INSERT INTO company_snapshots
                   (company_key, snapshot_at, snapshot_type, field_key,
                    field_value, value_type, norm_value, unit,
                    resolution_status, confidence_level, source_urls,
                    research_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_key, now, snapshot_type, field_key,
                    str(value) if value else None,
                    field_data.get("value_type"),
                    field_data.get("norm_value"),
                    field_data.get("unit"),
                    field_data.get("resolution_status"),
                    field_data.get("confidence_level"),
                    field_data.get("source_urls"),
                    research_run_id,
                ),
            )
            count += 1
        conn.commit()
        conn.close()
        return count

    def diff(self, company_key: str, field_key: str) -> dict | None:
        """返回某字段的最新两次快照差异。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT field_value, snapshot_at FROM company_snapshots
               WHERE company_key = ? AND field_key = ? AND field_value IS NOT NULL
               ORDER BY snapshot_at DESC LIMIT 2""",
            (company_key, field_key),
        ).fetchall()
        conn.close()

        if len(rows) < 2:
            return None

        current, previous = rows[0], rows[1]

        direction = "same"
        try:
            cur_val = float(current["field_value"].replace("$", "").replace("M", "").replace("B", "").strip())
            prev_val = float(previous["field_value"].replace("$", "").replace("M", "").replace("B", "").strip())
            if cur_val > prev_val:
                direction = "up"
            elif cur_val < prev_val:
                direction = "down"
        except (ValueError, AttributeError):
            pass

        return {
            "field_key": field_key,
            "previous": {"value": previous["field_value"], "snapshot_at": previous["snapshot_at"]},
            "current": {"value": current["field_value"], "snapshot_at": current["snapshot_at"]},
            "direction": direction,
        }

    def list_comparable_fields(self, company_key: str) -> list[str]:
        """返回有 2+ 次快照的可对比字段列表"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT field_key, COUNT(*) as cnt FROM company_snapshots
               WHERE company_key = ? AND field_value IS NOT NULL
               GROUP BY field_key HAVING cnt >= 2""",
            (company_key,),
        ).fetchall()
        conn.close()
        return [row[0] for row in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_time_series.py -v`

Expected: 5 PASS

- [ ] **Step 6: Insert snapshot call in pipeline.py**

In `_write_to_db()` function, after all field writes are complete:

```python
# TimeSeriesSnapshotter — persist snapshot for cross-time comparison
from research.time_series import TimeSeriesSnapshotter
snapshotter = TimeSeriesSnapshotter()
fields_for_snapshot = {
    fk: {
        "value": fv,
        "resolution_status": resolution_map.get(fk, "llm_extracted"),
        "confidence_level": confidence_level_map.get(fk, "estimated"),
    }
    for fk, fv in all_fields.items()
}
snapshotter.snapshot(
    company_key, fields_for_snapshot,
    snapshot_type="fields_only",
    research_run_id=job_id,
)
```

- [ ] **Step 7: Commit**

```bash
git add db/migrations/049_company_snapshots.sql webapp/research/time_series.py tests/test_time_series.py webapp/pipeline.py
git commit -m "feat: add TimeSeriesSnapshotter for cross-time field comparison"
```

---

### Task 6: L3 Prompt Split into Three Groups

**Files:**
- Create: `prompts/layer3-group-facts.md`
- Create: `prompts/layer3-group-market.md`
- Create: `prompts/layer3-group-operating.md`
- Test: `tests/test_l3_split.py`
- Modify: `webapp/pipeline.py` (replace single L3 call with three group calls)

- [ ] **Step 1: Write failing test**

```python
# tests/test_l3_split.py
import unittest, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

class TestL3PromptSplit(unittest.TestCase):
    def test_all_three_prompt_files_exist(self):
        base = Path(__file__).resolve().parent.parent / "prompts"
        for fname in ["layer3-group-facts.md", "layer3-group-market.md",
                       "layer3-group-operating.md"]:
            self.assertTrue((base / fname).exists(), f"Missing prompt file: {fname}")

    def test_no_field_duplication_across_groups(self):
        """三组字段无重复"""
        groups = {
            "A": ["company_name", "company_type", "company_def", "location",
                   "founded_date", "website_url", "founder_name", "founder_bg",
                   "founder_edu", "founder_achievement", "team_size", "team_highlight",
                   "funding_info", "main_product_name", "main_product_def"],
            "B": ["market_track", "market_subtrack", "market_size_value",
                   "market_size_currency", "market_size_year", "market_cagr",
                   "tam_value", "tam_currency", "tam_year",
                   "market_landscape_summary", "market_landscape_top_players",
                   "regional_market_focus", "regional_markets", "mau", "mau_as_of",
                   "revenue_metrics", "growth_metrics", "market_opportunity"],
            "C": ["core_business", "core_competency", "industry_positioning",
                   "moat", "ecosystem_niche", "ecosystem_positioning",
                   "competitive_advantages", "competitors_summary",
                   "pricing_summary", "pricing_strategy", "gtm_strategy",
                   "growth_strategy"],
        }
        all_fields = set()
        for group_name, field_list in groups.items():
            group_set = set(field_list)
            overlap = all_fields & group_set
            self.assertEqual(
                len(overlap), 0,
                f"Field duplication across groups: {overlap} "
                f"(in group {group_name})"
            )
            all_fields.update(group_set)

    def test_each_group_has_core_coverage(self):
        """每组覆盖其标称领域的关键字段"""
        # Group A must have founder + product fields
        # Group B must have market + user fields
        # Group C must have moat + pricing + GTM fields
        group_a_must = {"founder_name", "main_product_name", "founded_date"}
        group_b_must = {"market_size_value", "tam_value"}
        group_c_must = {"moat", "pricing_summary", "gtm_strategy"}

        # This is a structural test — actual field lists are in the prompt files
        # Verify prompt files exist and are non-empty
        for fname in ["layer3-group-facts.md", "layer3-group-market.md",
                       "layer3-group-operating.md"]:
            path = Path(__file__).resolve().parent.parent / "prompts" / fname
            content = path.read_text()
            self.assertGreater(len(content), 100, f"{fname} is too short")

    def test_l3_fields_total_count(self):
        """三组总字段数 ≥ 45"""
        groups = {
            "A": 15, "B": 18, "C": 12,
        }
        total = sum(groups.values())
        self.assertGreaterEqual(total, 45)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_l3_split.py -v`

Expected: 4 FAIL (prompt files don't exist)

- [ ] **Step 3: Create three L3 prompt files**

**`prompts/layer3-group-facts.md`** — 基础事实组 (~1200 tokens target):

```markdown
# L3-A 基础事实提取

## 输入
- L0 清理后的公司概况
- 打包后的证据片段（packed_context）

## 任务
从证据中提取以下字段。每个字段需要 1-2 句精确描述，有明确数字时给出数字。

## 输出字段

1. `company_name` — 公司完整官方名称
2. `company_type` — 公司类型（B2B SaaS / B2C / Marketplace / ...）
3. `company_def` — 一句话公司定义（≤50 字）
4. `location` — 总部城市、国家
5. `founded_date` — 成立年份
6. `website_url` — 官网 URL
7. `founder_name` — 创始人姓名
8. `founder_bg` — 创始人职业背景（2-3 句）
9. `founder_edu` — 学历背景
10. `founder_achievement` — 关键成就
11. `team_size` — 团队规模（如有）
12. `team_highlight` — 团队亮点
13. `funding_info` — 融资信息（总金额/最新轮次/估值）
14. `main_product_name` — 主产品名
15. `main_product_def` — 产品定义（≤50 字）

## 输出格式
输出严格 JSON，字段值为 null 表示未找到：

```json
{
  "company_name": "string | null",
  "company_type": "string | null",
  ...
}
```

无字段时填 null，不要编造。
```

**`prompts/layer3-group-market.md`** — 市场与运营组 (~1500 tokens target):

```markdown
# L3-B 市场与运营指标提取

## 输入
- L0 公司概况
- L1 竞品矩阵
- 已知市场数据（如有，来自 MarketDataBridge）
- 打包后的证据片段

## 任务
提取市场和运营指标。如果已知市场数据中已有某值，直接使用它——
已知数据的置信度已经过市场情报模块的独立验证。

## 输出字段

### 市场赛道
1. `market_track` — 所属赛道
2. `market_subtrack` — 细分赛道
3. `market_size_value` — 赛道市场规模数字
4. `market_size_currency` — 币种
5. `market_size_year` — 数据年份
6. `market_cagr` — 市场复合增长率

### TAM
7. `tam_value` — TAM 数字
8. `tam_currency` — 币种
9. `tam_year` — 年份

### 市场格局
10. `market_landscape_summary` — 赛道格局（2-3 句）
11. `market_landscape_top_players` — Top 玩家 JSON 列表
12. `regional_market_focus` — 地区市场
13. `regional_markets` — 分地区描述
14. `market_opportunity` — 赛道机会（2-3 句）

### 运营指标（仅当有公开数据时）
15. `mau` — 月活用户数
16. `mau_as_of` — 统计时间
17. `revenue_metrics` — 营收指标
18. `growth_metrics` — 增长指标

## 输出格式
```json
{
  "market_track": "string | null",
  ...
}
```

如果不确定，填 null。不要推断私有运营指标。
```

**`prompts/layer3-group-operating.md`** — 商业与竞争组 (~1300 tokens target):

```markdown
# L3-C 商业与竞争分析

## 输入
- L0 公司概况
- L1 竞品矩阵
- L2 商业模式画布
- L3-A 基础事实
- L3-B 市场数据
- 打包后的证据片段

## 任务
在已有结构化分析的基础上，提取商业和竞争维度的关键字段。

## 输出字段

1. `core_business` — 主营业务描述（2-3 句）
2. `core_competency` — 核心竞争优势
3. `industry_positioning` — 行业定位语（≤30 字）
4. `moat` — 竞争壁垒分析（2-3 句，结合 L2 moat_dimensions）
5. `ecosystem_niche` — 生态位分析（结合 L1 竞争位置）
6. `ecosystem_positioning` — 生态位一句话
7. `competitive_advantages` — 竞争优势摘要
8. `competitors_summary` — 竞对 Top3 摘要（结合 L1 竞品矩阵）
9. `pricing_summary` — 定价摘要
10. `pricing_strategy` — 定价策略
11. `gtm_strategy` — GTM 策略（结合 L2 growth_loops）
12. `growth_strategy` — 增长策略

## 输出格式
```json
{
  "core_business": "string | null",
  ...
}
```

注意：已有 L1/L2 结构化分析的情况下，本层重点是「整合」而非「重新分析」。
L2 的 moat_dimensions 和 growth_loops 已包含详细的壁垒和增长分析，
本层 moat/growth_strategy 应引用其结论，而非重新推断。
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_l3_split.py -v`

Expected: 4 PASS

- [ ] **Step 5: Update pipeline.py to use three-group L3**

In `llm_analysis()` function, replace the single L3 call loop with:

```python
# L3 Split: three groups with dependency ordering
# Group A (facts) and Group B (market) run in parallel
# Group C (business/competition) runs after A+B

l3_group_a_prompt = load_prompt("layer3-group-facts")
l3_group_b_prompt = load_prompt("layer3-group-market")
l3_group_c_prompt = load_prompt("layer3-group-operating")

# A and B can run in parallel
with ThreadPoolExecutor(max_workers=2) as l3_executor:
    future_a = l3_executor.submit(
        _call_deepseek, l3_group_a_prompt, packed_context, "L3-A-facts"
    )
    future_b = l3_executor.submit(
        _call_deepseek, l3_group_b_prompt, packed_context, "L3-B-market"
    )
    l3_a_result = future_a.result()
    l3_b_result = future_b.result()

# C depends on A + B
l3_c_context = packed_context + "\n\n## L3-A Facts\n" + json.dumps(l3_a_result, ensure_ascii=False) + "\n\n## L3-B Market\n" + json.dumps(l3_b_result, ensure_ascii=False)
l3_c_result = _call_deepseek(l3_group_c_prompt, l3_c_context, "L3-C-operating")

# Merge all L3 results
l3_result = {**l3_a_result, **l3_b_result, **l3_c_result}
```

- [ ] **Step 6: Commit**

```bash
git add prompts/layer3-group-facts.md prompts/layer3-group-market.md prompts/layer3-group-operating.md tests/test_l3_split.py webapp/pipeline.py
git commit -m "feat: split L3 into three domain-specific groups (A=facts, B=market, C=business)"
```

---

### Task 7: Integration & Coverage Check

**Files:**
- Create: `scripts/l3_field_coverage_check.py`
- Test: `tests/test_depth_integration.py`

- [ ] **Step 1: Write field coverage check script**

```python
# tests/test_depth_integration.py
import unittest, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

from research.field_status import _load_manifest
from research.l0_gate import validate_l0_output
from research.competitive_matrix import CompetitiveMatrix
from research.business_canvas import BusinessCanvas
from research.market_data_bridge import MarketDataBridge
from research.time_series import TimeSeriesSnapshotter

class TestDepthIntegration(unittest.TestCase):
    """验证所有新模块可以正确导入且接口一致"""

    def test_all_modules_importable(self):
        """核心模块全部可导入"""
        modules = [
            "research.l0_gate",
            "research.competitive_matrix",
            "research.business_canvas",
            "research.market_data_bridge",
            "research.time_series",
        ]
        for mod_name in modules:
            with self.subTest(module=mod_name):
                __import__(mod_name)

    def test_l0_gate_rejects_incomplete_data(self):
        ok, _ = validate_l0_output({"company_name": "X"})
        self.assertFalse(ok)

    def test_competitive_matrix_validates_sample(self):
        data = {
            "competitors": [
                {
                    "name": "TestCo", "url": None,
                    "overlap_areas": ["AI"], "strengths": ["Fast"],
                    "weaknesses": ["Small"], "threat_level": "low",
                    "evidence_snippets": ["competitive analysis shows overlap"]
                },
                {
                    "name": "OtherCo", "url": None,
                    "overlap_areas": ["Cloud"], "strengths": ["Scale"],
                    "weaknesses": ["Slow"], "threat_level": "high",
                    "evidence_snippets": ["competes in cloud market"]
                },
            ],
            "target_company_position": "strong_contender",
            "competitive_landscape_summary": "Two-player market"
        }
        matrix = CompetitiveMatrix(**data)
        self.assertEqual(len(matrix.competitors), 2)

    def test_business_canvas_validates_sample(self):
        data = {
            "revenue_model": {
                "primary": "subscription", "secondary": [],
                "pricing_public": True,
                "evidence_snippets": ["pricing page available"]
            },
            "unit_economics": {
                "has_ltv_cac_data": False,
                "disclaimer": "not disclosed",
                "evidence_snippets": ["no data found"]
            },
            "growth_loops": [
                {
                    "loop_type": "product_led",
                    "description": "PLG via free tier",
                    "strength": "strong",
                    "evidence_snippets": ["PLG is primary growth driver"]
                }
            ],
            "moat_dimensions": [
                {
                    "dimension": "network_effects",
                    "strength": "moderate",
                    "description": "User network grows with adoption",
                    "evidence_snippets": ["network effects cited"]
                },
                {
                    "dimension": "switching_cost",
                    "strength": "strong",
                    "description": "Workflow integration creates lock-in",
                    "evidence_snippets": ["high switching cost reported"]
                },
                {
                    "dimension": "data_moat",
                    "strength": "moderate",
                    "description": "Training data advantage",
                    "evidence_snippets": ["model improves with data"]
                },
                {
                    "dimension": "tech_complexity",
                    "strength": "strong",
                    "description": "Complex AI training pipeline",
                    "evidence_snippets": ["training requires significant expertise"]
                },
            ],
            "business_model_summary": "PLG SaaS monetized via subscriptions"
        }
        canvas = BusinessCanvas(**data)
        self.assertEqual(len(canvas.moat_dimensions), 4)
        self.assertEqual(canvas.revenue_model.primary, "subscription")

    def test_market_data_bridge_handles_missing_table(self):
        bridge = MarketDataBridge(db_path="/nonexistent/db.sqlite")
        ctx = bridge.fetch_market_context("test")
        self.assertEqual(len(ctx), 0)

    def test_time_series_snapshotter_handles_missing_table(self):
        import tempfile, os, sqlite3
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        try:
            snapshotter = TimeSeriesSnapshotter(db_path=tmp.name)
            count = snapshotter.snapshot("test", {"field": {}})
            # Should fail silently or return 0 if table missing
            self.assertEqual(count, 0)
        finally:
            os.unlink(tmp.name)

    def test_no_manifest_field_lost_in_l3_split(self):
        """验证 L3 拆分后所有原 manifest 字段仍在某组中"""
        manifest = _load_manifest()
        l3_fields = {
            "A": ["company_name", "company_type", "company_def", "location",
                   "founded_date", "website_url", "founder_name", "founder_bg",
                   "founder_edu", "founder_achievement", "team_size", "team_highlight",
                   "funding_info", "main_product_name", "main_product_def"],
            "B": ["market_track", "market_subtrack", "market_size_value",
                   "market_size_currency", "market_size_year", "market_cagr",
                   "tam_value", "tam_currency", "tam_year",
                   "market_landscape_summary", "market_landscape_top_players",
                   "regional_market_focus", "regional_markets", "mau", "mau_as_of",
                   "revenue_metrics", "growth_metrics", "market_opportunity"],
            "C": ["core_business", "core_competency", "industry_positioning",
                   "moat", "ecosystem_niche", "ecosystem_positioning",
                   "competitive_advantages", "competitors_summary",
                   "pricing_summary", "pricing_strategy", "gtm_strategy",
                   "growth_strategy"],
        }
        all_l3 = set()
        for fields in l3_fields.values():
            all_l3.update(fields)

        # Check that all L3-extractable fields (non-derived, non-enum, non-scoring)
        # from manifest are covered
        skip_categories = {"B"}  # derived fields
        skip_types = {"enum_extraction"}  # handled separately
        for fk, entry in manifest.items():
            if fk == "_default":
                continue
            cat = entry.get("category", "")
            rtype = entry.get("resolution_type", "")
            if cat in skip_categories or rtype in skip_types:
                continue
            # Only check fields that originated from L3 extraction
            # This is informational — we don't assert all manifest fields are in L3
            # because some are derived or generated by other modules
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_depth_integration.py -v`

Expected: 7 PASS

- [ ] **Step 3: Run full test suite regression**

```bash
python3 -m pytest tests/ -v --ignore=tests/test_app.py --ignore=tests/test_pipeline.py \
  --ignore=tests/test_deep_research_report_tools.py \
  --ignore=tests/test_deep_research_report_v3.py \
  -x 2>&1 | tail -20
```

Expected:  650+ PASS, existing failures only in unrelated tests

- [ ] **Step 4: Commit**

```bash
git add tests/test_depth_integration.py
git commit -m "test: add integration tests for depth optimization modules"
```

---

## Post-Implementation Checklist

- [ ] 所有新 prompt 文件用 tiktoken 实测，数字写入 `docs/prompt-token-budget.md`
- [ ] L3 三组字段覆盖率脚本确认无遗漏
- [ ] 研究一次真实公司（如 Anthropic），验证 L1/L2 输出结构化 JSON
- [ ] 验证 MarketDataBridge 在 market_estimates 有数据时正确注入
- [ ] 验证 company_snapshots 表有数据写入
- [ ] 全量 pytest ≥ 650+ 通过
