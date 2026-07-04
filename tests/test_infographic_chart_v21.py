"""v2 图表改造测试 — 验证 0-10 绝对坐标 + 5 泳道 + 全员标签 + 无 markPoint"""
from __future__ import annotations
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))
from infographic import (
    normalize_group_scores,
    _truncate_label,
    _point_priority,
    build_competitive_landscape_svg,
    build_stack_positioning_svg,
)
from infographic_templates import get as get_template


class NormalizationTests(unittest.TestCase):
    """normalize_group_scores 仍保留（供其他调用方使用），但图表不再默认使用归一化"""

    def test_normalize_raw_fields_unchanged(self):
        companies = [
            {"name": "A", "score_defensibility": 8, "score_incumbent_attention": 6},
            {"name": "B", "score_defensibility": 4, "score_incumbent_attention": 2},
        ]
        normed, meta = normalize_group_scores(
            companies, ["score_defensibility", "score_incumbent_attention"],
        )
        # raw 字段不变
        self.assertEqual(normed[0]["score_defensibility"], 8)
        self.assertEqual(normed[0]["score_incumbent_attention"], 6)
        self.assertEqual(normed[1]["score_defensibility"], 4)
        self.assertEqual(normed[1]["score_incumbent_attention"], 2)

    def test_normalize_produces_norm_fields(self):
        companies = [
            {"name": "A", "score_defensibility": 8, "score_incumbent_attention": 6},
            {"name": "B", "score_defensibility": 4, "score_incumbent_attention": 2},
        ]
        normed, _ = normalize_group_scores(
            companies, ["score_defensibility"],
        )
        self.assertIn("score_defensibility_norm", normed[0])
        self.assertIn("score_defensibility_norm", normed[1])

    def test_normalize_range_zero_to_one(self):
        companies = [
            {"name": "A", "score_defensibility": 10},
            {"name": "B", "score_defensibility": 0},
        ]
        normed, _ = normalize_group_scores(companies, ["score_defensibility"])
        vals = [c["score_defensibility_norm"] for c in normed]
        self.assertAlmostEqual(max(vals), 1.0, places=2)
        self.assertAlmostEqual(min(vals), 0.0, places=2)

    def test_normalize_all_equal_to_neutral(self):
        companies = [
            {"name": "A", "score_defensibility": 5},
            {"name": "B", "score_defensibility": 5},
        ]
        normed, meta = normalize_group_scores(companies, ["score_defensibility"])
        self.assertIn("score_defensibility", meta["all_equal_keys"])
        for c in normed:
            self.assertAlmostEqual(c["score_defensibility_norm"], 0.5, places=2)

    def test_normalize_all_null_returns_none(self):
        companies = [
            {"name": "A", "score_defensibility": None},
            {"name": "B", "score_defensibility": None},
        ]
        normed, meta = normalize_group_scores(companies, ["score_defensibility"])
        self.assertIsNone(meta["ranges"]["score_defensibility"]["min"])
        self.assertIsNone(normed[0]["score_defensibility_norm"])

    def test_truncate_label_short_name_passes_through(self):
        self.assertEqual(_truncate_label("OpenAI", 8), "OpenAI")

    def test_truncate_label_long_name_cut(self):
        self.assertEqual(_truncate_label("AnthropicAI", 7), "Anthrop…")

    def test_point_priority_target_first(self):
        points = [
            {"company_name": "B"}, {"company_name": "A"}, {"company_name": "Target"},
        ]
        result = _point_priority(points, "Target", 12)
        self.assertEqual(result[0]["company_name"], "Target")

    def test_point_priority_capped(self):
        points = [{"company_name": f"C{i}"} for i in range(20)]
        result = _point_priority(points, "C0", 5)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["company_name"], "C0")


class CompetitiveChartV2Tests(unittest.TestCase):
    """v2 chart_competitive 渲染验证 — 0-10 绝对坐标"""

    def test_chart_uses_zero_to_ten_axes(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": 7, "score_defensibility": 8, "funding_stage_score": 6},
            {"company_name": "OtherCo", "score_incumbent_attention": 4, "score_defensibility": 3, "funding_stage_score": 4},
        ], "TestCo", {"theme": "light"})
        # 以 animation:false 为锚，只检查我们的 option 代码
        opt_start = html.find("animation:false")
        opt_section = html[opt_start:] if opt_start > 0 else html
        self.assertIn("min:0,max:10", opt_section)
        # 不应有 min:0,max:1 后跟非数字字符（排除 max:10 的子串匹配）
        self.assertNotIn("min:0,max:1,", opt_section)

    def test_chart_tooltip_absolute_scores(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": 7, "score_defensibility": 8, "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("巨头关注度", html)
        self.assertIn("护城河强度", html)
        self.assertIn(" / 10", html)

    def test_chart_has_markline_at_five(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": 7, "score_defensibility": 8, "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("xAxis:5", html)
        self.assertIn("yAxis:5", html)
        self.assertNotIn("xAxis:0.5", html)

    def test_chart_animation_disabled(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": 7, "score_defensibility": 8, "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("animation:false", html)

    def test_chart_no_data_handles_gracefully(self):
        html = build_competitive_landscape_svg([], "TestCo", {"theme": "light"})
        self.assertIn("暂无可用图表数据", html)
        self.assertIn("echarts.init", html)

    def test_chart_drops_null_incumbent_attention(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": None, "score_defensibility": 8, "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("暂无可用图表数据", html)

    def test_chart_respects_max_companies(self):
        companies = [
            {"company_name": f"C{i}", "score_incumbent_attention": i % 10, "score_defensibility": i % 10, "funding_stage_score": 5}
            for i in range(20)
        ]
        html = build_competitive_landscape_svg(companies, "C0", {"theme": "light", "max_companies": 8})
        self.assertIn("echarts.init", html)
        self.assertNotIn("暂无可用图表数据", html)

    def test_chart_dynamic_title(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": 3, "score_defensibility": 8, "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("战略机会区", html)
        self.assertIn("TestCo", html)

    def test_chart_all_labels_shown(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": 7, "score_defensibility": 8, "funding_stage_score": 6},
            {"company_name": "OtherCo", "score_incumbent_attention": 4, "score_defensibility": 3, "funding_stage_score": 4},
        ], "TestCo", {"theme": "light"})
        # 所有公司名都应出现在 HTML 中（标签全部显示）
        self.assertIn("OtherCo", html)

    def test_chart_default_size_800x600(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": 7, "score_defensibility": 8, "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("800px", html)
        self.assertIn("600px", html)

    def test_chart_x_axis_name(self):
        html = build_competitive_landscape_svg([
            {"company_name": "TestCo", "score_incumbent_attention": 7, "score_defensibility": 8, "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("巨头关注度", html)


class EcosystemChartV2Tests(unittest.TestCase):
    """chart_ecosystem v2 测试 — 5 泳道 + 0-10 绝对坐标 + 无 markPoint + 全员标签"""

    def test_dynamic_title(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 8.5, "stack_layer": "vertical_app", "funding_stage_score": 6},
            {"company_name": "OtherCo", "score_value_capture": 4.0, "stack_layer": "middleware", "funding_stage_score": 4},
        ], "TestCo", {"theme": "light"})
        self.assertIn("TestCo", html)
        self.assertIn("变现能力", html)

    def test_title_fallback(self):
        html = build_stack_positioning_svg([
            {"company_name": "OtherCo", "score_value_capture": 4.0, "stack_layer": "middleware", "funding_stage_score": 4},
        ], "GhostCo", {"theme": "light"})
        self.assertIn("AI 栈生态位图", html)

    def test_zero_to_ten_axis(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        opt_start = html.find("animation:false")
        opt_section = html[opt_start:] if opt_start > 0 else html
        self.assertTrue("min:0,max:10" in opt_section)

    def test_tooltip_absolute_scores(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("变现能力", html)
        self.assertIn(" / 10", html)

    def test_null_stack_layer_handled(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": None, "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("暂无可用图表数据", html)

    def test_category_y_inverse(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("inverse:true", html)

    def test_five_lanes(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("分发渠道", html)
        self.assertIn("垂直应用", html)
        self.assertIn("中间件层", html)
        self.assertIn("模型层", html)
        self.assertIn("基础设施层", html)

    def test_distribution_separate_from_vertical_app(self):
        """分发渠道不应被映射到垂直应用"""
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 5, "stack_layer": "distribution", "funding_stage_score": 5},
        ], "TestCo", {"theme": "light"})
        # distribution 应显示为 分发渠道 而非 垂直应用
        self.assertIn("分发渠道", html)

    def test_default_size_800x600(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("800px", html)
        self.assertIn("600px", html)

    def test_no_markpoint(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        # 只检查我们的 option 代码（以 animation:false 为锚），排除 vendor ECharts 库
        opt_start = html.find("animation:false")
        opt_section = html[opt_start:] if opt_start > 0 else html
        self.assertNotIn("markPoint", opt_section)

    def test_all_labels_shown(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 6},
            {"company_name": "OtherCo", "score_value_capture": 4, "stack_layer": "middleware", "funding_stage_score": 4},
        ], "TestCo", {"theme": "light"})
        self.assertIn("OtherCo", html)

    def test_bottom_guide(self):
        # 底部引导文字已删除；验证无数据提示仍正常
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 6},
        ], "TestCo", {"theme": "light"})
        self.assertIn("TestCo", html)

    def test_fixed_symbol_size(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "vertical_app", "funding_stage_score": 9},
            {"company_name": "OtherCo", "score_value_capture": 3, "stack_layer": "infrastructure", "funding_stage_score": 1},
        ], "TestCo", {"theme": "light"})
        self.assertIn("symbolSize", html)
        self.assertIn("is_highlight", html)

    def test_focus_lane_keeps_target_position_and_dims_compressed_other_lanes(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "middleware", "funding_stage_score": 9},
            {"company_name": "TopLane", "score_value_capture": 4, "stack_layer": "distribution", "funding_stage_score": 1},
            {"company_name": "BottomLane", "score_value_capture": 3, "stack_layer": "infrastructure", "funding_stage_score": 1},
        ], "TestCo", {"theme": "light"})
        opt_start = html.find("var series=")
        opt_section = html[opt_start:] if opt_start > 0 else html

        self.assertIn('"name": "TestCo", "value": [7.0, 2.0]', opt_section)
        self.assertIn('"name": "TopLane", "value": [4.0, 0.475]', opt_section)
        self.assertIn('"name": "BottomLane", "value": [3.0, 3.525]', opt_section)
        self.assertIn('focusLaneIndex=2', opt_section)
        self.assertIn('rgba(148,163,184,0.40)', opt_section)

    def test_focus_lane_layout_uses_continuous_bands_without_white_gaps(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "middleware", "funding_stage_score": 9},
            {"company_name": "TopLane", "score_value_capture": 4, "stack_layer": "distribution", "funding_stage_score": 1},
            {"company_name": "BottomLane", "score_value_capture": 3, "stack_layer": "infrastructure", "funding_stage_score": 1},
        ], "TestCo", {"theme": "light"})
        opt_start = html.find("var series=")
        opt_section = html[opt_start:] if opt_start > 0 else html

        self.assertIn('"start": 0.2, "end": 0.75', opt_section)
        self.assertIn('"start": 0.75, "end": 1.3', opt_section)
        self.assertIn('"start": 1.3, "end": 2.7', opt_section)
        self.assertIn('"start": 2.7, "end": 3.25', opt_section)
        self.assertIn('"start": 3.25, "end": 3.8', opt_section)
        self.assertIn('type:"value",min:0.2,max:3.8', opt_section)

    def test_focus_lane_is_wider_and_other_lanes_have_equal_height(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "middleware", "funding_stage_score": 9},
            {"company_name": "TopLane", "score_value_capture": 4, "stack_layer": "distribution", "funding_stage_score": 1},
            {"company_name": "BottomLane", "score_value_capture": 3, "stack_layer": "infrastructure", "funding_stage_score": 1},
        ], "TestCo", {"theme": "light"})
        opt_start = html.find("var series=")
        opt_section = html[opt_start:] if opt_start > 0 else html

        self.assertIn('"height": 0.55', opt_section)
        self.assertIn('"height": 1.4', opt_section)
        self.assertIn('"name": "TopLane", "value": [4.0, 0.475]', opt_section)
        self.assertIn('"name": "TestCo", "value": [7.0, 2.0]', opt_section)
        self.assertIn('"name": "BottomLane", "value": [3.0, 3.525]', opt_section)

    def test_lane_names_use_left_graphic_labels_and_fonts_are_doubled(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "middleware", "funding_stage_score": 9},
        ], "TestCo", {"theme": "light", "title_size": 16, "axis_size": 12, "label_size": 13})
        opt_start = html.find("var series=")
        opt_section = html[opt_start:] if opt_start > 0 else html

        self.assertIn("laneLabels.map", opt_section)
        self.assertIn('fontSize:26', opt_section)
        self.assertIn('fontSize:24', opt_section)
        self.assertIn('fontSize:32', opt_section)
        self.assertIn('axisLabel:{show:false}', opt_section)
        self.assertIn('left:18', opt_section)

    def test_focus_lane_competitor_labels_move_away_from_target_label(self):
        html = build_stack_positioning_svg([
            {"company_name": "TestCo", "score_value_capture": 7, "stack_layer": "middleware", "funding_stage_score": 9},
            {"company_name": "OtherCo", "score_value_capture": 6, "stack_layer": "middleware", "funding_stage_score": 5},
            {"company_name": "UpperCo", "score_value_capture": 5, "stack_layer": "vertical_app", "funding_stage_score": 5},
            {"company_name": "LowerCo", "score_value_capture": 5, "stack_layer": "foundation_model", "funding_stage_score": 5},
        ], "TestCo", {"theme": "light"})
        opt_start = html.find("var series=")
        opt_section = html[opt_start:] if opt_start > 0 else html

        self.assertIn('"name": "TestCo"', opt_section)
        self.assertIn('"label": {"position": "right", "distance": 14}', opt_section)
        self.assertIn('"name": "OtherCo"', opt_section)
        self.assertIn('"label": {"position": "left", "distance": 14}', opt_section)
        self.assertIn('"name": "UpperCo"', opt_section)
        self.assertIn('"label": {"position": "top", "distance": 12}', opt_section)
        self.assertIn('"name": "LowerCo"', opt_section)
        self.assertIn('"label": {"position": "bottom", "distance": 12}', opt_section)
        self.assertIn('labelLayout:{hideOverlap:true,moveOverlap:"shiftY"}', opt_section)
        self.assertIn('opt.series.push({type:"scatter",data:[],z:-10', opt_section)


class FlywheelTemplateTests(unittest.TestCase):
    def test_circular_flywheel_wraps_long_stage_text(self):
        template = get_template("flywheel_circular")
        self.assertIsNotNone(template)
        svg = template.build({
            "stages": [
                {"label": "高意向用户进入内容自动化工作流", "desc": "形成稳定获客线索"},
                {"label": "产品使用数据反哺模型和模板", "desc": "提升生成质量"},
                {"label": "成功案例带来更多垂直行业客户", "desc": "扩大分发"},
                {"label": "客户复用资产并邀请团队协作", "desc": "提高留存"},
            ],
        }, {"width": 800, "height": 800, "label_size": 36, "show_desc": True})

        self.assertIn("<tspan", svg)
        self.assertIn('class="flywheel-stage-label"', svg)
        self.assertNotIn("高意向用户进入内容自动化工作流 | 形成稳定获客线索</text>", svg)


if __name__ == "__main__":
    unittest.main()
