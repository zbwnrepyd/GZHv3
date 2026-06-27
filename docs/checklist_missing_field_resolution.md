# SPEC Missing Field Resolution — 字段修复 Checklist（最终）

> 基于 docs/SPEC_missing_field_resolution.md 2026-06-25
> 验证时间: 2026-06-25

## 问题 A: v2 评分字段（12个） PR-1

| # | 字段名 | 来源 | 修复方式 | 状态 |
|---|--------|------|---------|------|
| A1 | incumbent_overlap | L3 moat/competitive_position | scoring_inference (LLM) | ✅ |
| A2 | workflow_lock_in | L3 moat/ecosystem_niche | scoring_inference (LLM) | ✅ |
| A3 | data_lock_in | L3 moat/data_flywheel | scoring_inference (LLM) | ✅ |
| A4 | technical_uniqueness | L3 core_competency/tech_stack | scoring_inference (LLM) | ✅ |
| A5 | distribution_lock | L3 ecosystem_niche | scoring_inference (LLM) | ✅ |
| A6 | brand_or_community | L3 moat | scoring_inference (LLM) | ✅ |
| A7 | market_size | L3 market_opportunity | scoring_inference (LLM) | ✅ |
| A8 | strategic_dependency | L3 moat/competitive_position | scoring_inference (LLM) | ✅ |
| A9 | user_visibility | L3 customer_segment/company_type | scoring_inference (LLM) | ✅ |
| A10 | pricing_power | L3 pricing_strategy | scoring_inference (LLM) | ✅ |
| A11 | gross_margin | L3 pricing_strategy | scoring_inference (LLM) | ✅ |
| A12 | customer_budget_level | L3 customer_segment | scoring_inference (LLM) | ✅ |

## 问题 B: 文本字段推导（15个） PR-2

| # | 字段名 | 来源字段 | 修复方式 | 状态 |
|---|--------|---------|---------|------|
| B1 | switching_cost | moat | derivation_pass (LLM) | ✅ |
| B2 | data_flywheel | growth_flywheel | derivation_pass (规则) | ✅ |
| B3 | differentiation_strategy | differentiated_opportunity | derivation_pass (LLM) | ✅ |
| B4 | gtm_motion | gtm_strategy | derivation_pass (规则) | ✅ |
| B5 | ideal_customer_profile | customer_segment | derivation_pass (LLM) | ✅ |
| B6 | product_pain_points | main_product_highlight + competitive_advantages | derivation_pass (LLM) | ✅ |
| B7 | proprietary_data_asset | moat | derivation_pass (规则) | ✅ |
| B8 | revenue_model | pricing_strategy + pricing_summary | derivation_pass (LLM) | ✅ |
| B9 | technical_barrier | tech_stack + moat | derivation_pass (LLM) | ✅ |
| B10 | timeline_events | funding_info | derivation_pass (LLM) | ✅ |
| B11 | customer_segment_primary | customer_segment | derivation_pass (LLM) | ✅ |
| B12 | customer_segment_secondary | customer_segment | derivation_pass (LLM) | ✅ |
| B13 | customer_selection_reasons | competitive_advantages + moat | derivation_pass (LLM) | ✅ |
| B14 | incumbent_direct_competitor | market_landscape_top_players | derivation_pass (规则) | ✅ |
| B15 | workflow_integration_level | ecosystem_niche + moat | derivation_pass (规则) | ✅ |

## 问题 C: Hook 段落生成（3个） PR-3

| # | 字段名 | 来源 | 修复方式 | 状态 |
|---|--------|------|---------|------|
| C1 | hook_paragraph_1 | L3 standard 全量字段 | hook_writer (LLM) | ✅ |
| C2 | hook_paragraph_2 | L3 standard 全量字段 | hook_writer (LLM) | ✅ |
| C3 | hook_paragraph_3 | L3 standard 全量字段 | hook_writer (LLM) | ✅ |

## Manifest 修改（3项） PR-3

| # | 变更 | 状态 |
|---|------|------|
| M1 | hook_paragraph_1: official_fact→llm_generated, unavailable→draft | ✅ |
| M2 | hook_paragraph_2: official_fact→llm_generated, unavailable→draft | ✅ |
| M3 | hook_paragraph_3: official_fact→llm_generated, unavailable→draft | ✅ |

## SPEC 约束验证（7项）

| # | 约束 | 状态 |
|---|------|------|
| C1 | LLM 使用 call_deepseek() | ✅ |
| C2 | 新步骤 try/except 非阻断 | ✅ |
| C3 | 不修改 _extract_enum_fields() | ✅ |
| C4 | 不修改 compute_scores() | ✅ |
| C5 | 不修改 layer3-group-a/b/c prompt | ✅ |
| C6 | 写入 research_fields→insert_research_fields_batch() | ✅ (通过 parsed→all_records 现有流程) |
| C7 | pytest tests/ -v 全通过 | ✅ 903 passed |

## 回归验证

| # | 检查项 | 状态 |
|---|--------|------|
| R1 | pytest tests/ -v 全量通过 | ✅ 903 passed, 4 skipped |
| R2 | pipeline.py 编译通过 | ✅ |
| R3 | scoring_inference.py 编译通过 | ✅ |
| R4 | derivation_pass.py 编译通过 | ✅ |
| R5 | hook_writer.py 编译通过 | ✅ |
| R6 | layer_hook.md 已创建 | ✅ |
| R7 | field_manifest.yaml 已修改 | ✅ |

## 新建文件清单

| 文件 | 用途 |
|------|------|
| webapp/research/scoring_inference.py | PR-1: Post-L3 v2 评分枚举推断 |
| webapp/research/derivation_pass.py | PR-2: 文本字段规则+LLM推导 |
| webapp/research/hook_writer.py | PR-3: 钩子段落LLM生成 |
| prompts/layer_hook.md | PR-3: Hook写作Prompt |
| tests/test_scoring_inference.py | PR-1: 6 tests |
| tests/test_derivation_pass.py | PR-2: 14 tests |
| tests/test_hook_writer.py | PR-3: 6 tests |

## 修改文件清单

| 文件 | 变更 |
|------|------|
| webapp/pipeline.py | 三处插入: PR-1 scoring_inference + PR-2 derivation_pass + PR-3 hook_writer |
| references/field_manifest.yaml | hook_paragraph_1/2/3: resolution_type + if_missing 修改 |

## SPEC 与代码不一致（已修正）

| # | 不一致 | 处理 |
|---|--------|------|
| D1 | SPEC derivation_pass.py 代码缺少 data_flywheel/proprietary_data_asset/workflow_integration_level 三个推导函数 | 已补充规则推导函数 |
| D2 | SPEC 测试 monkeypatch 路径 `research.scoring_inference.call_deepseek` 因延迟导入不生效 | 改为 `deepseek_client.call_deepseek` |
