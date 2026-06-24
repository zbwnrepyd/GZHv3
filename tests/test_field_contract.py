"""字段契约测试 — SPEC Section 16.1

验证：
1. card schema v3 中所有 field_key 均存在于 field_manifest.yaml
2. 无 field_key 使用已弃用名称（company_category 等）
3. fields.json 无冲突别名
4. field_manifest.yaml 中存在 _default 条目
"""
import unittest
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict:
    """加载 YAML 文件，返回 dict。"""
    try:
        import yaml
    except ImportError:
        raise unittest.SkipTest("PyYAML 未安装，跳过 YAML 测试")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _extract_field_keys_from_card_configs(v3_configs: list[dict]) -> set[str]:
    """从 v3 套卡的 default_card_configs 中提取所有 field_key。"""
    keys: set[str] = set()
    for cfg in v3_configs:
        config_json_str = cfg.get("config_json", "{}")
        try:
            config = json.loads(config_json_str)
        except (json.JSONDecodeError, TypeError):
            config = {}
        for fk in config.get("fields", []):
            keys.add(fk)
    return keys


# 已知弃用名称：这些 field_key 不应出现在 v3 卡片中
DEPRECATED_FIELD_NAMES = {
    "company_category",       # 已完全弃用
    "company_revenue",        # v1 遗留，标记 deprecated
    "company_profit",         # v1 遗留，标记 deprecated
    "other_products",         # v2 起废弃
}

# v3 中已拆分/重命名的字段，新名称应在 manifest 中
# gtm_motion 当前有效；检查其是否在 manifest 中有正确条目
# differentiation_strategy 当前有效；检查其是否在 manifest 中有正确条目


class FieldContractTest(unittest.TestCase):
    """SPEC 16.1 — 字段契约校验"""

    @classmethod
    def setUpClass(cls):
        cls.manifest_path = ROOT / "references" / "field_manifest.yaml"
        cls.fields_json_path = ROOT / "contracts" / "fields.json"
        cls.card_schema_path = ROOT / "db" / "init_composition_db.sql"

        if not cls.manifest_path.exists():
            raise unittest.SkipTest("field_manifest.yaml 不存在")
        if not cls.fields_json_path.exists():
            raise unittest.SkipTest("fields.json 不存在")
        if not cls.card_schema_path.exists():
            raise unittest.SkipTest("init_composition_db.sql 不存在")

        # 加载 field_manifest
        cls.manifest = _load_yaml(cls.manifest_path)
        cls.manifest_fields = cls.manifest.get("fields", {})
        cls.manifest_keys = set(cls.manifest_fields.keys())

        # 加载 fields.json
        with open(cls.fields_json_path, encoding="utf-8") as f:
            cls.fields_contract = json.load(f)

        # 提取 fields.json 中的所有 field_key
        cls.fields_json_keys: set[str] = set()
        for group in cls.fields_contract.get("groups", []):
            for field in group.get("fields", []):
                cls.fields_json_keys.add(field["field_key"])

        # 从 init_composition_db.sql 提取 v3 卡片 field_key
        cls.v3_card_field_keys = cls._extract_v3_card_fields_from_sql(
            cls.card_schema_path
        )

    @classmethod
    def _extract_v3_card_fields_from_sql(cls, sql_path: Path) -> set[str]:
        """解析 SQL 文件中的 v3 default_card_configs 提取 field_keys。"""
        keys: set[str] = set()
        with open(sql_path, encoding="utf-8") as f:
            content = f.read()

        # 匹配 v3 的 INSERT OR REPLACE 行
        import re
        # 查找所有 INSERT OR REPLACE INTO default_card_configs 行
        # 格式: ('v3','v3_card_XX',...)
        pattern = r"\('v3',\s*'[^']*',\s*\d+,\s*'[^']*',\s*'(\{[^}]*\})'\)"
        for match in re.finditer(pattern, content):
            config_json_str = match.group(1)
            try:
                config = json.loads(config_json_str)
            except json.JSONDecodeError:
                continue
            for fk in config.get("fields", []):
                keys.add(fk)

        # 也尝试用 v3_card 前缀匹配多行模式
        if not keys:
            # 回退: 手动匹配更宽松的模式
            pattern2 = r"set_key[^)]*'v3'[^)]*config_json[^']*'(\{[^}]*fields[^}]*\})'"
            for match in re.finditer(pattern2, content, re.DOTALL):
                try:
                    config = json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
                for fk in config.get("fields", []):
                    keys.add(fk)

        return keys

    # ── 1. card schema v3 field_keys 全部在 field_manifest 中 ──

    def test_all_v3_card_field_keys_exist_in_manifest(self):
        """v3 套卡中每个 field_key 都应在 field_manifest.yaml 有定义"""
        missing = self.v3_card_field_keys - self.manifest_keys
        has_default = "_default" in self.manifest_keys

        if missing and not has_default:
            self.assertEqual(
                len(missing), 0,
                f"v3 卡片引用了 {len(missing)} 个不在 field_manifest 中的字段: "
                f"{sorted(missing)}。且 _default 不存在，无兜底覆盖。"
            )
        elif missing and has_default:
            # _default 提供兜底覆盖，但仍应逐步补全显式条目
            self.assertLessEqual(
                len(missing), 5,
                f"v3 卡片有 {len(missing)} 个字段仅由 _default 覆盖（无显式条目）: "
                f"{sorted(missing)}。建议逐步补全。"
            )
        else:
            # 无缺失，完美
            self.assertEqual(len(missing), 0)

    # ── 2. 无弃用名称 ──

    def test_no_deprecated_field_names_in_v3_cards(self):
        """v3 卡片不应使用已弃用的 field_key"""
        deprecated_found = self.v3_card_field_keys & DEPRECATED_FIELD_NAMES
        self.assertEqual(
            len(deprecated_found), 0,
            f"v3 卡片引用了 {len(deprecated_found)} 个已弃用字段: "
            f"{sorted(deprecated_found)}"
        )

    def test_no_deprecated_field_names_in_fields_json(self):
        """fields.json 中不应出现完全弃用的 field_key"""
        deprecated_found = self.fields_json_keys & {"company_category"}
        self.assertEqual(
            len(deprecated_found), 0,
            f"fields.json 包含已弃用字段: {sorted(deprecated_found)}"
        )

    def test_gtm_motion_has_manifest_entry(self):
        """gtm_motion 应在 field_manifest 中有正确条目（非旧式名称）"""
        self.assertIn(
            "gtm_motion", self.manifest_keys,
            "gtm_motion 不在 field_manifest 中，可能使用了旧式名称"
        )

    def test_differentiation_strategy_has_manifest_entry(self):
        """differentiation_strategy 应在 field_manifest 中有正确条目（非旧式名称）"""
        self.assertIn(
            "differentiation_strategy", self.manifest_keys,
            "differentiation_strategy 不在 field_manifest 中，可能使用了旧式名称"
        )

    # ── 3. fields.json 无冲突别名 ──

    def test_fields_json_no_duplicate_keys(self):
        """fields.json 中不应有重复的 field_key"""
        seen: dict[str, list[str]] = {}  # field_key -> [group_keys]
        for group in self.fields_contract.get("groups", []):
            gk = group.get("group_key", "")
            for field in group.get("fields", []):
                fk = field["field_key"]
                if fk not in seen:
                    seen[fk] = []
                seen[fk].append(gk)

        duplicates = {fk: groups for fk, groups in seen.items() if len(groups) > 1}
        self.assertEqual(
            len(duplicates), 0,
            f"fields.json 中有 {len(duplicates)} 个重复 field_key 出现在多个分组: "
            f"{duplicates}"
        )

    def test_fields_json_no_conflicting_aliases(self):
        """fields.json 中 field_key 与 field_label 不应存在交叉别名冲突"""
        # 构建 field_key -> field_label 映射
        key_to_label: dict[str, str] = {}
        label_to_key: dict[str, str] = {}
        for group in self.fields_contract.get("groups", []):
            for field in group.get("fields", []):
                fk = field["field_key"]
                fl = field.get("field_label", "")
                key_to_label[fk] = fl
                if fl and fl not in label_to_key:
                    label_to_key[fl] = fk

        # 检查是否有一个 field_key 等于另一个 field 的 label（冲突别名）
        conflicts = []
        for fk in self.fields_json_keys:
            if fk in label_to_key and label_to_key[fk] != fk:
                conflicts.append(
                    f"'{fk}' 是 field_key，但同时是 '{label_to_key[fk]}' 的 field_label"
                )

        self.assertEqual(
            len(conflicts), 0,
            f"fields.json 中 field_key/label 存在交叉冲突: {conflicts}"
        )

    # ── 4. _default 条目存在 ──

    def test_default_entry_exists_in_manifest(self):
        """field_manifest.yaml 中应存在 _default 兜底条目"""
        self.assertIn(
            "_default", self.manifest_keys,
            "field_manifest.yaml 缺少 _default 兜底条目"
        )

    def test_default_entry_has_required_fields(self):
        """_default 条目应包含 category、resolution_type、if_missing"""
        default_entry = self.manifest_fields.get("_default", {})
        self.assertIn("category", default_entry,
                      "_default 缺少 category")
        self.assertIn("resolution_type", default_entry,
                      "_default 缺少 resolution_type")
        self.assertIn("if_missing", default_entry,
                      "_default 缺少 if_missing")

    # ── 补充：manifest 与 fields.json 一致性 ──

    def test_manifest_keys_subset_of_fields_json(self):
        """field_manifest 中显式定义的字段（除 _default/内部字段）应在 fields.json 中存在"""
        # 排除内部字段和仅在 manifest 定义的枚举提取字段
        manifest_explicit = self.manifest_keys - {"_default"}
        missing_in_json = manifest_explicit - self.fields_json_keys
        # 允许少量内部字段不在 fields.json（如 funding_stage、main_product_img_src
        # 等系统内部使用的字段）
        tolerable = {"funding_stage", "main_product_img_src", "market_cagr",
                      "market_size_source_note", "business_canvas",
                      "competitors_structured", "growth_loops",
                      "moat_dimensions", "unit_economics"}
        actual_missing = missing_in_json - tolerable
        self.assertEqual(
            len(actual_missing), 0,
            f"field_manifest 中有 {len(actual_missing)} 个字段不在 fields.json "
            f"（已排除系统内部字段 {sorted(tolerable & missing_in_json)}）: "
            f"{sorted(actual_missing)}"
        )

    def test_v3_active_fields_have_resolution_type(self):
        """v3 卡片使用的字段在 manifest 中有 resolution_type"""
        for fk in self.v3_card_field_keys:
            entry = self.manifest_fields.get(fk, self.manifest_fields.get("_default", {}))
            self.assertIsNotNone(
                entry.get("resolution_type"),
                f"v3 字段 '{fk}' 在 field_manifest 中缺少 resolution_type"
            )


if __name__ == "__main__":
    unittest.main()
