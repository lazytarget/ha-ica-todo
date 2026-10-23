"""Tests for unit conversion and IcaShoppingListEntry merging utilities."""

import importlib.util
import os

import pytest

# Import utils.py directly to avoid pulling in the full ica package
# (which depends on homeassistant).
_utils_path = os.path.join(
    os.path.dirname(__file__),
    "..",
    "custom_components",
    "ica",
    "utils.py",
)
_spec = importlib.util.spec_from_file_location("ica_utils", _utils_path)
_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils)

are_units_compatible = _utils.are_units_compatible
convert_quantity = _utils.convert_quantity
get_unit_group = _utils.get_unit_group
merge_shopping_list_entries = _utils.merge_shopping_list_entries
_merge_recipe_refs = _utils._merge_recipe_refs


# ---------------------------------------------------------------------------
# Unit group detection
# ---------------------------------------------------------------------------


class TestGetUnitGroup:
    def test_volume_units(self):
        for u in ("L", "dl", "cl", "ml", "krm", "tsk", "msk"):
            group, table = get_unit_group(u)
            assert group == "volume", f"{u} should be in the volume group"
            assert table is not None

    def test_weight_units(self):
        for u in ("kg", "g"):
            group, _ = get_unit_group(u)
            assert group == "weight"

    def test_count_units_are_isolated(self):
        g_st, _ = get_unit_group("st")
        g_forp, _ = get_unit_group("förp")
        assert g_st == "count:st"
        assert g_forp == "count:förp"
        assert g_st != g_forp  # NOT inter-convertible

    def test_none_unit(self):
        assert get_unit_group(None) == (None, None)

    def test_unknown_unit(self):
        assert get_unit_group("banana") == (None, None)

    def test_case_insensitive(self):
        group, _ = get_unit_group("DL")
        assert group == "volume"


# ---------------------------------------------------------------------------
# Unit compatibility
# ---------------------------------------------------------------------------


class TestAreUnitsCompatible:
    def test_same_unit(self):
        assert are_units_compatible("dl", "dl") is True

    def test_same_group_volume(self):
        assert are_units_compatible("dl", "ml") is True
        assert are_units_compatible("L", "msk") is True
        assert are_units_compatible("tsk", "cl") is True

    def test_same_group_weight(self):
        assert are_units_compatible("kg", "g") is True

    def test_cross_group(self):
        assert are_units_compatible("kg", "ml") is False
        assert are_units_compatible("dl", "g") is False

    def test_count_not_cross_convertible(self):
        assert are_units_compatible("st", "förp") is False

    def test_count_same_unit(self):
        assert are_units_compatible("st", "st") is True
        assert are_units_compatible("förp", "förp") is True

    def test_both_none(self):
        assert are_units_compatible(None, None) is True

    def test_one_none(self):
        assert are_units_compatible("dl", None) is False
        assert are_units_compatible(None, "g") is False


# ---------------------------------------------------------------------------
# Quantity conversion
# ---------------------------------------------------------------------------


class TestConvertQuantity:
    def test_same_unit_noop(self):
        assert convert_quantity(5, "dl", "dl") == 5

    def test_dl_to_ml(self):
        assert convert_quantity(2, "dl", "ml") == 200

    def test_ml_to_dl(self):
        assert convert_quantity(250, "ml", "dl") == 2.5

    def test_l_to_dl(self):
        assert convert_quantity(1, "L", "dl") == 10

    def test_msk_to_ml(self):
        assert convert_quantity(2, "msk", "ml") == 30

    def test_tsk_to_msk(self):
        # 1 tsk = 5 ml, 1 msk = 15 ml → 3 tsk = 1 msk
        assert convert_quantity(3, "tsk", "msk") == pytest.approx(1.0)

    def test_krm_to_tsk(self):
        # 1 krm = 1 ml, 1 tsk = 5 ml → 5 krm = 1 tsk
        assert convert_quantity(5, "krm", "tsk") == pytest.approx(1.0)

    def test_kg_to_g(self):
        assert convert_quantity(1.5, "kg", "g") == 1500

    def test_g_to_kg(self):
        assert convert_quantity(500, "g", "kg") == 0.5

    def test_incompatible(self):
        assert convert_quantity(1, "kg", "dl") is None

    def test_count_incompatible(self):
        assert convert_quantity(1, "st", "förp") is None

    def test_none_unit(self):
        assert convert_quantity(1, None, "dl") is None
        assert convert_quantity(1, "dl", None) is None


# ---------------------------------------------------------------------------
# Recipe reference merging
# ---------------------------------------------------------------------------


class TestMergeRecipeRefs:
    def test_both_none(self):
        assert _merge_recipe_refs(None, None) is None

    def test_only_base(self):
        base = [{"id": 1, "quantity": 2, "unit": "dl"}]
        result = _merge_recipe_refs(base, None)
        assert len(result) == 1
        assert result[0]["quantity"] == 2

    def test_only_other(self):
        other = [{"id": 1, "quantity": 3, "unit": "dl"}]
        result = _merge_recipe_refs(None, other)
        assert len(result) == 1
        assert result[0]["quantity"] == 3

    def test_disjoint_recipes(self):
        base = [{"id": 1, "quantity": 2, "unit": "dl"}]
        other = [{"id": 2, "quantity": 3, "unit": "dl"}]
        result = _merge_recipe_refs(base, other)
        assert len(result) == 2

    def test_same_recipe_same_unit(self):
        base = [{"id": 1, "quantity": 2, "unit": "dl"}]
        other = [{"id": 1, "quantity": 3, "unit": "dl"}]
        result = _merge_recipe_refs(base, other)
        assert len(result) == 1
        assert result[0]["quantity"] == 5
        assert result[0]["unit"] == "dl"

    def test_same_recipe_compatible_units(self):
        base = [{"id": 1, "quantity": 2, "unit": "dl"}]
        other = [{"id": 1, "quantity": 100, "unit": "ml"}]
        result = _merge_recipe_refs(base, other)
        assert len(result) == 1
        assert result[0]["quantity"] == pytest.approx(3.0)  # 2 dl + 100 ml = 3 dl
        assert result[0]["unit"] == "dl"  # base unit preserved

    def test_same_recipe_incompatible_units_keeps_base(self):
        base = [{"id": 1, "quantity": 2, "unit": "dl"}]
        other = [{"id": 1, "quantity": 100, "unit": "g"}]
        result = _merge_recipe_refs(base, other)
        assert len(result) == 1
        assert result[0]["quantity"] == 2  # unchanged


# ---------------------------------------------------------------------------
# Shopping list entry merging
# ---------------------------------------------------------------------------


class TestMergeShoppingListEntries:
    def test_basic_same_unit(self):
        base = {"productName": "Mjölk", "quantity": 2, "unit": "L"}
        other = {"productName": "Mjölk", "quantity": 1, "unit": "L"}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 3
        assert result["unit"] == "L"

    def test_compatible_volume_units(self):
        base = {"productName": "Grädde", "quantity": 2, "unit": "dl"}
        other = {"productName": "Grädde", "quantity": 100, "unit": "ml"}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == pytest.approx(3.0)
        assert result["unit"] == "dl"  # base unit

    def test_compatible_weight_units(self):
        base = {"productName": "Mjöl", "quantity": 1, "unit": "kg"}
        other = {"productName": "Mjöl", "quantity": 500, "unit": "g"}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == pytest.approx(1.5)
        assert result["unit"] == "kg"

    def test_swedish_volume_units(self):
        base = {"productName": "Socker", "quantity": 2, "unit": "msk"}
        other = {"productName": "Socker", "quantity": 1, "unit": "tsk"}
        result = merge_shopping_list_entries(base, other)
        # 2 msk + 1 tsk = 30 ml + 5 ml = 35 ml = 35/15 msk ≈ 2.3333 msk
        assert result["quantity"] == pytest.approx(2.3333, abs=1e-3)
        assert result["unit"] == "msk"

    def test_incompatible_units_keeps_base(self):
        base = {"productName": "Ägg", "quantity": 6, "unit": "st"}
        other = {"productName": "Ägg", "quantity": 200, "unit": "g"}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 6  # unchanged
        assert result["unit"] == "st"

    def test_count_units_same(self):
        base = {"productName": "Ägg", "quantity": 6, "unit": "st"}
        other = {"productName": "Ägg", "quantity": 3, "unit": "st"}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 9
        assert result["unit"] == "st"

    def test_count_units_different(self):
        """'st' and 'förp' are not inter-convertible."""
        base = {"productName": "Ägg", "quantity": 1, "unit": "förp"}
        other = {"productName": "Ägg", "quantity": 6, "unit": "st"}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 1  # unchanged
        assert result["unit"] == "förp"

    def test_base_none_quantity_adopts_other(self):
        base = {"productName": "Smör", "quantity": None, "unit": None}
        other = {"productName": "Smör", "quantity": 500, "unit": "g"}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 500
        assert result["unit"] == "g"

    def test_base_none_quantity_other_none_unit(self):
        """A missing quantity counts as 1 st, so 1 st + 2 st = 3 st."""
        base = {"productName": "Salt", "quantity": None, "unit": None}
        other = {"productName": "Salt", "quantity": 2, "unit": None}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 3
        assert result["unit"] == "st"  # defaulted

    def test_other_none_quantity(self):
        base = {"productName": "Smör", "quantity": 500, "unit": "g"}
        other = {"productName": "Smör", "quantity": None, "unit": None}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 500
        assert result["unit"] == "g"

    def test_both_none_quantity(self):
        """Adding an item without quantity twice gives 2 st."""
        base = {"productName": "Salt", "quantity": None, "unit": None}
        other = {"productName": "Salt", "quantity": None, "unit": None}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 2
        assert result["unit"] == "st"

    def test_base_none_quantity_incompatible_other_keeps_base(self):
        base = {"productName": "Smör", "quantity": 1, "unit": "förp"}
        other = {"productName": "Smör", "quantity": None, "unit": None}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 1
        assert result["unit"] == "förp"

    def test_no_unit_both_have_quantity(self):
        """Both entries have quantity but no explicit unit – defaults to 'st', so they sum."""
        base = {"productName": "X", "quantity": 2, "unit": None}
        other = {"productName": "X", "quantity": 3, "unit": None}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 5
        assert result["unit"] == "st"  # defaulted

    def test_base_has_no_unit_other_has_incompatible(self):
        """Base has no unit (→ 'st'), other has 'dl' → incompatible, base unchanged."""
        base = {"productName": "X", "quantity": 2, "unit": None}
        other = {"productName": "X", "quantity": 3, "unit": "dl"}
        result = merge_shopping_list_entries(base, other)
        assert (
            result["quantity"] == 2
        )  # unchanged (st vs dl)  -> # TODO: Should create new entry?
        assert result["unit"] == "st"

    def test_base_has_no_unit_other_also_st(self):
        """Base has no unit (→ 'st'), other is explicitly 'st' → compatible."""
        base = {"productName": "X", "quantity": 2, "unit": None}
        other = {"productName": "X", "quantity": 3, "unit": "st"}
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 5
        assert result["unit"] == "st"

    def test_recipe_merge(self):
        base = {
            "productName": "Grädde",
            "quantity": 4,
            "unit": "dl",
            "recipes": [{"id": 10, "quantity": 2, "unit": "dl"}],
        }
        other = {
            "productName": "Grädde",
            "quantity": 2,
            "unit": "dl",
            "recipes": [{"id": 20, "quantity": 1, "unit": "dl"}],
        }
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 6
        assert len(result["recipes"]) == 2

    def test_recipe_merge_overlapping(self):
        base = {
            "productName": "Grädde",
            "quantity": 4,
            "unit": "dl",
            "recipes": [{"id": 10, "quantity": 2, "unit": "dl"}],
        }
        other = {
            "productName": "Grädde",
            "quantity": 2,
            "unit": "dl",
            "recipes": [{"id": 10, "quantity": 3, "unit": "dl"}],
        }
        result = merge_shopping_list_entries(base, other)
        assert result["quantity"] == 6
        assert len(result["recipes"]) == 1
        assert result["recipes"][0]["quantity"] == 5

    def test_carry_over_nullable_fields(self):
        base = {
            "productName": "Mjölk",
            "quantity": 1,
            "unit": "L",
            "productEan": None,
            "articleGroupId": 42,
            "offerId": None,
        }
        other = {
            "productName": "Mjölk",
            "quantity": 1,
            "unit": "L",
            "productEan": "7310860000001",
            "articleGroupId": 99,  # should NOT overwrite base's non-None value
            "offerId": "offer-123",
        }
        result = merge_shopping_list_entries(base, other)
        assert result["productEan"] == "7310860000001"
        assert result["articleGroupId"] == 42  # base preserved
        assert result["offerId"] == "offer-123"

    def test_does_not_mutate_inputs(self):
        base = {"productName": "A", "quantity": 1, "unit": "dl", "recipes": None}
        other = {"productName": "A", "quantity": 2, "unit": "dl", "recipes": None}
        base_copy = dict(base)
        other_copy = dict(other)
        merge_shopping_list_entries(base, other)
        assert base == base_copy
        assert other == other_copy

    def test_full_realistic_merge(self):
        """Simulate merging two entries from different recipes for the same product."""
        base = {
            "id": 100,
            "offlineId": "abc-123",
            "productName": "Vetemjöl",
            "quantity": 5,
            "unit": "dl",
            "recipes": [{"id": 1, "quantity": 3, "unit": "dl"}],
            "productEan": "7310860000010",
            "isStrikedOver": False,
            "articleGroupId": 12,
            "articleGroupIdExtended": None,
        }
        other = {
            "id": None,
            "offlineId": "def-456",
            "productName": "Vetemjöl",
            "quantity": 200,
            "unit": "ml",
            "recipes": [
                {"id": 2, "quantity": 100, "unit": "ml"},
                {"id": 1, "quantity": 50, "unit": "ml"},
            ],
            "productEan": None,
            "isStrikedOver": False,
            "articleGroupId": None,
            "articleGroupIdExtended": 55,
        }
        result = merge_shopping_list_entries(base, other)

        # Quantity: 5 dl + 200 ml = 5 dl + 2 dl = 7 dl
        assert result["quantity"] == pytest.approx(7.0)
        assert result["unit"] == "dl"

        # Base identity preserved
        assert result["id"] == 100
        assert result["offlineId"] == "abc-123"

        # Recipes: recipe 1 merged, recipe 2 added
        assert len(result["recipes"]) == 2
        r1 = next(r for r in result["recipes"] if r["id"] == 1)
        r2 = next(r for r in result["recipes"] if r["id"] == 2)
        # Recipe 1: 3 dl + 50 ml = 3 dl + 0.5 dl = 3.5 dl
        assert r1["quantity"] == pytest.approx(3.5)
        assert r1["unit"] == "dl"
        # Recipe 2: 100 ml (as-is from other)
        assert r2["quantity"] == 100
        assert r2["unit"] == "ml"

        # Carry-over
        assert result["productEan"] == "7310860000010"  # base non-None
        assert result["articleGroupId"] == 12
        assert result["articleGroupIdExtended"] == 55  # carried from other
