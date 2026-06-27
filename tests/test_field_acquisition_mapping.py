"""
Test suite for field_acquisition_map.json.

Verifies the N:N field-to-acquisition-method mapping is complete, consistent,
and aligned with contracts/fields.json and contracts/card_sets/v3.json.
"""
import json
import os
import pytest


# -- helpers ------------------------------------------------------------------

def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_json(relpath):
    path = os.path.join(_project_root(), relpath)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def fields_json():
    return _load_json("contracts/fields.json")


@pytest.fixture(scope="module")
def v3_cards_json():
    return _load_json("contracts/card_sets/v3.json")


@pytest.fixture(scope="module")
def acq_map_json():
    return _load_json("references/field_acquisition_map.json")


# -- collect derived data -----------------------------------------------------

@pytest.fixture(scope="module")
def fields_json_keys(fields_json):
    """Set of all field_key values in contracts/fields.json."""
    keys = set()
    for group in fields_json["groups"]:
        for f in group["fields"]:
            keys.add(f["field_key"])
    return keys


@pytest.fixture(scope="module")
def fields_json_deprecated(fields_json):
    """Set of field_key values that are deprecated in fields.json."""
    deprecated = set()
    for group in fields_json["groups"]:
        for f in group["fields"]:
            if f.get("deprecated"):
                deprecated.add(f["field_key"])
    return deprecated


@pytest.fixture(scope="module")
def v3_card_field_ids(v3_cards_json):
    """Set of all field_key values referenced across all v3 cards."""
    ids = set()
    for card in v3_cards_json["cards"]:
        for fk in card.get("fields", []):
            ids.add(fk)
    return ids


@pytest.fixture(scope="module")
def v3_field_to_card_ids(v3_cards_json):
    """Map field_key -> list of card_id values."""
    mapping = {}
    for card in v3_cards_json["cards"]:
        cid = card["card_id"]
        for fk in card.get("fields", []):
            mapping.setdefault(fk, []).append(cid)
    return mapping


@pytest.fixture(scope="module")
def acq_map_fields(acq_map_json):
    return acq_map_json["fields"]


@pytest.fixture(scope="module")
def acq_map_methods(acq_map_json):
    return set(acq_map_json["acquisition_methods"].keys())


@pytest.fixture(scope="module")
def acq_map_categories(acq_map_json):
    return set(acq_map_json["categories"].keys())


# -- tests --------------------------------------------------------------------

class TestFieldCoverage:
    """Bi-directional coverage between fields.json and the acquisition map."""

    def test_all_fields_json_in_acquisition_map(self, fields_json_keys, acq_map_fields):
        """Every field in fields.json MUST exist in the acquisition map."""
        missing = fields_json_keys - set(acq_map_fields.keys())
        assert not missing, (
            f"Fields in fields.json missing from acquisition map ({len(missing)}): "
            + ", ".join(sorted(missing))
        )

    def test_all_map_fields_in_fields_json(self, fields_json_keys, acq_map_fields):
        """No extra fields in the map that aren't in fields.json."""
        extra = set(acq_map_fields.keys()) - fields_json_keys
        assert not extra, (
            f"Fields in acquisition map not in fields.json ({len(extra)}): "
            + ", ".join(sorted(extra))
        )

    def test_field_count_matches(self, fields_json_keys, acq_map_fields):
        """The acquisition map MUST contain exactly the same number of fields as fields.json."""
        expected = len(fields_json_keys)
        actual = len(acq_map_fields)
        assert actual == expected, (
            f"Field count mismatch: acquisition map has {actual} fields, "
            f"fields.json has {expected} fields"
        )


class TestMethodCompleteness:
    """Every field must have at least one acquisition method with a primary role."""

    def test_all_fields_have_at_least_one_method(self, acq_map_fields):
        """No field has an empty methods array."""
        empty = []
        for fk, fdef in acq_map_fields.items():
            methods = fdef.get("methods", [])
            if len(methods) == 0:
                empty.append(fk)
        assert not empty, (
            f"Fields with no acquisition methods ({len(empty)}): "
            + ", ".join(sorted(empty))
        )

    def test_all_fields_have_primary_method(self, acq_map_fields):
        """Every field MUST have at least one method with role='primary'."""
        no_primary = []
        for fk, fdef in acq_map_fields.items():
            methods = fdef.get("methods", [])
            has_primary = any(m.get("role") == "primary" for m in methods)
            if not has_primary:
                no_primary.append(fk)
        assert not no_primary, (
            f"Fields without a primary acquisition method ({len(no_primary)}): "
            + ", ".join(sorted(no_primary))
        )

    def test_all_v3_card_fields_have_primary_method(
        self, v3_card_field_ids, acq_map_fields
    ):
        """Every field used in a v3 card MUST have at least one primary method."""
        no_primary = []
        for fk in v3_card_field_ids:
            fdef = acq_map_fields.get(fk, {})
            methods = fdef.get("methods", [])
            has_primary = any(m.get("role") == "primary" for m in methods)
            if not has_primary:
                no_primary.append(fk)
        assert not no_primary, (
            f"V3 card fields without a primary acquisition method ({len(no_primary)}): "
            + ", ".join(sorted(no_primary))
        )


class TestDeprecatedConsistency:
    """Deprecated fields in fields.json MUST be marked deprecated in the map."""

    def test_deprecated_fields_marked(
        self, fields_json_deprecated, acq_map_fields
    ):
        """Every deprecated field in fields.json must have deprecated=true in the map."""
        not_marked = []
        for fk in fields_json_deprecated:
            fdef = acq_map_fields.get(fk, {})
            if not fdef.get("deprecated"):
                not_marked.append(fk)
        assert not not_marked, (
            f"Deprecated fields in fields.json not marked deprecated in map "
            f"({len(not_marked)}): " + ", ".join(sorted(not_marked))
        )

    def test_no_false_deprecated_in_map(
        self, fields_json_deprecated, acq_map_fields
    ):
        """Fields NOT deprecated in fields.json should NOT be deprecated in the map."""
        false_positives = []
        for fk, fdef in acq_map_fields.items():
            if fdef.get("deprecated") and fk not in fields_json_deprecated:
                false_positives.append(fk)
        assert not false_positives, (
            f"Fields marked deprecated in map but NOT deprecated in fields.json "
            f"({len(false_positives)}): " + ", ".join(sorted(false_positives))
        )


class TestMethodAndCategoryValidity:
    """All method and category references must be known values."""

    def test_no_unknown_acquisition_methods(self, acq_map_fields, acq_map_methods):
        """Every method name in every field must be in the known methods list."""
        unknown = set()
        for fk, fdef in acq_map_fields.items():
            for m in fdef.get("methods", []):
                if m["method"] not in acq_map_methods:
                    unknown.add(m["method"])
        assert not unknown, (
            f"Unknown acquisition methods ({len(unknown)}): "
            + ", ".join(sorted(unknown))
        )

    def test_no_unknown_categories(self, acq_map_fields, acq_map_categories):
        """Every category assigned to a field must be in the known categories list."""
        unknown = set()
        for fk, fdef in acq_map_fields.items():
            cat = fdef.get("category")
            if cat and cat not in acq_map_categories:
                unknown.add(cat)
        assert not unknown, (
            f"Unknown categories ({len(unknown)}): " + ", ".join(sorted(unknown))
        )

    def test_all_fields_have_valid_category(self, acq_map_fields):
        """Every field must have a category string."""
        missing = [fk for fk, fdef in acq_map_fields.items() if not fdef.get("category")]
        assert not missing, (
            f"Fields missing category ({len(missing)}): " + ", ".join(sorted(missing))
        )


class TestV3CardConsistency:
    """Fields used in v3 cards must be properly marked in the acquisition map."""

    def test_v3_card_fields_marked_in_v3_cards(
        self, v3_card_field_ids, acq_map_fields
    ):
        """Fields referenced in v3 cards must have in_v3_cards=true and non-empty v3_card_ids."""
        bad = []
        for fk in v3_card_field_ids:
            fdef = acq_map_fields.get(fk, {})
            if not fdef.get("in_v3_cards"):
                bad.append(f"{fk} (in_v3_cards=False)")
            elif not fdef.get("v3_card_ids"):
                bad.append(f"{fk} (v3_card_ids is empty)")
        assert not bad, (
            f"V3 card fields with incorrect map markings ({len(bad)}): "
            + "; ".join(sorted(bad))
        )

    def test_non_v3_card_fields_not_marked(
        self, fields_json_keys, v3_card_field_ids, acq_map_fields
    ):
        """Fields NOT in v3 cards must have in_v3_cards=false and empty v3_card_ids."""
        non_v3 = fields_json_keys - v3_card_field_ids
        bad = []
        for fk in non_v3:
            fdef = acq_map_fields.get(fk, {})
            if fdef.get("in_v3_cards"):
                bad.append(f"{fk} (in_v3_cards=True but not in any v3 card)")
            if fdef.get("v3_card_ids"):
                bad.append(f"{fk} (v3_card_ids non-empty but not in any v3 card)")
        assert not bad, (
            f"Non-v3-card fields with incorrect map markings ({len(bad)}): "
            + "; ".join(sorted(bad))
        )

    def test_v3_card_ids_match_actual_usage(
        self, v3_field_to_card_ids, acq_map_fields
    ):
        """For each v3 card field, the map's v3_card_ids must match the actual card set."""
        mismatches = []
        for fk, expected_ids in v3_field_to_card_ids.items():
            fdef = acq_map_fields.get(fk, {})
            actual_ids = set(fdef.get("v3_card_ids", []))
            expected_set = set(expected_ids)
            if actual_ids != expected_set:
                mismatches.append(
                    f"{fk}: expected {sorted(expected_set)}, got {sorted(actual_ids)}"
                )
        assert not mismatches, (
            f"V3 card ID mismatches ({len(mismatches)}): " + "; ".join(mismatches)
        )


class TestMethodRoles:
    """Method role values must be from a known set."""

    VALID_ROLES = {"primary", "secondary", "fallback", "supplemental"}

    def test_all_method_roles_valid(self, acq_map_fields):
        """Every method role must be one of the known valid roles."""
        bad = []
        for fk, fdef in acq_map_fields.items():
            for m in fdef.get("methods", []):
                role = m.get("role")
                if role not in self.VALID_ROLES:
                    bad.append(f"{fk}.{m['method']}={role}")
        assert not bad, (
            f"Methods with unknown roles ({len(bad)}): " + "; ".join(sorted(bad))
        )


class TestStructuralIntegrity:
    """The acquisition map JSON itself must be structurally sound."""

    def test_version_present(self, acq_map_json):
        assert "version" in acq_map_json, "Map is missing 'version' key"

    def test_description_present(self, acq_map_json):
        assert "description" in acq_map_json, "Map is missing 'description' key"

    def test_acquisition_methods_defined(self, acq_map_json):
        am = acq_map_json.get("acquisition_methods", {})
        assert len(am) > 0, "acquisition_methods is empty"

    def test_categories_defined(self, acq_map_json):
        cats = acq_map_json.get("categories", {})
        assert len(cats) > 0, "categories is empty"
