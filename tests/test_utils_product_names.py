"""Tests for product name normalization and plural matching."""

import importlib.util
import os

# Import utils.py directly
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

normalize_product_name = _utils.normalize_product_name
product_names_match = _utils.product_names_match


# ---------------------------------------------------------------------------
# Product name normalization
# ---------------------------------------------------------------------------


class TestNormalizeProductName:
    """Test the normalize_product_name function."""

    # Swedish plurals
    def test_swedish_or_plural(self):
        """Swedish -or plural (flicka → flickor)"""
        assert normalize_product_name("Kakor") == "kaka"
        assert normalize_product_name("Gurkor") == "gurka"

    def test_swedish_ar_plural(self):
        """Swedish -ar plural (pojk → pojkar)"""
        assert normalize_product_name("Pojkar") == "pojk"
        assert normalize_product_name("Ostar") == "ost"
        assert normalize_product_name("Fiskar") == "fisk"

    def test_swedish_ötter_plural(self):
        """Swedish -ötter plural (morot → morötter)"""
        assert normalize_product_name("Morötter") == "morot"
        assert normalize_product_name("Fötter") == "fot"

    def test_swedish_er_plural(self):
        """Swedish -er plural (tomater → tomat)"""
        assert normalize_product_name("Tomater") == "tomat"
        assert normalize_product_name("tomater") == "tomat"
        assert normalize_product_name("Bärer") == "bär"
        assert normalize_product_name("Aprikoser") == "aprikos"
        assert (
            normalize_product_name("Ananaser") == "ananas"
        )  # should not strip 's' from ananas

    def test_swedish_arna_plural(self):
        """Swedish definite plural -arna"""
        assert normalize_product_name("Pojkarna") == "pojk"
        assert normalize_product_name("Äppelarna") == "äppel"

    def test_swedish_erna_plural(self):
        """Swedish definite plural -erna"""
        assert normalize_product_name("Barnen") == "barn"  # -en suffix
        assert normalize_product_name("Äpplena") == "äpple"

    def test_swedish_orna_plural(self):
        """Swedish definite plural -orna"""
        assert normalize_product_name("Kakorna") == "kaka"
        assert normalize_product_name("Flickorna") == "flicka"

    def test_swedish_n_after_vowel(self):
        """Swedish -n suffix after vowel (äpplet → äpple)"""
        assert normalize_product_name("Äpplet") == "äpple"
        assert normalize_product_name("äpplen") == "äpple"
        # Should NOT strip -n after consonant
        assert normalize_product_name("Barn") == "barn"

    # English plurals
    def test_english_s_plural(self):
        """English -s plural (apple → apples)"""
        assert normalize_product_name("Apples") == "apple"
        assert normalize_product_name("Oranges") == "orange"
        assert normalize_product_name("Bananas") == "banana"
        assert normalize_product_name("Ananas") == "ananas"

    def test_english_es_plural(self):
        """English -es plural (box → boxes)"""
        assert normalize_product_name("Boxes") == "box"
        assert normalize_product_name("Tomatoes") == "tomato"  # -es suffix

    def test_english_ies_plural(self):
        """English -ies plural (berry → berries)"""
        assert normalize_product_name("Berries") == "berry"
        assert normalize_product_name("Cherries") == "cherry"
        assert normalize_product_name("Strawberries") == "strawberry"

    # Edge cases
    def test_singular_unchanged(self):
        """Singular forms should remain mostly unchanged"""
        assert normalize_product_name("Tomat") == "tomat"
        assert normalize_product_name("Apple") == "apple"
        assert normalize_product_name("Mjölk") == "mjölk"
        assert normalize_product_name("Smör") == "smör"
        assert normalize_product_name("Salt") == "salt"
        assert normalize_product_name("Kaffe") == "kaffe"

    def test_short_words_unchanged(self):
        """Very short words should not be normalized"""
        assert normalize_product_name("Ost") == "ost"
        assert normalize_product_name("Te") == "te"
        assert normalize_product_name("Is") == "is"  # ice, should keep the 's'

    def test_words_naturally_ending_in_s(self):
        """Words that naturally end in 's' should not be stripped"""
        assert normalize_product_name("Glass") == "glass"  # double-s preserved
        assert normalize_product_name("Ris") == "ris"
        assert (
            normalize_product_name("Ananas") == "ananas"
        )  # ends with 's' but is singular

    def test_preserves_minimum_length(self):
        """Normalization should preserve at least 3 chars in the stem"""
        # Should NOT strip if it would make stem too short
        result = normalize_product_name("Bars")
        assert len(result) >= 3

    def test_none_and_empty(self):
        """Handle None and empty strings gracefully"""
        assert normalize_product_name(None) == ""
        assert normalize_product_name("") == ""
        assert normalize_product_name("   ") == ""

    def test_case_insensitive(self):
        """Normalization should be case-insensitive"""
        assert normalize_product_name("TOMATER") == "tomat"
        assert normalize_product_name("Tomater") == "tomat"
        assert normalize_product_name("tomater") == "tomat"

    def test_whitespace_handling(self):
        """Should strip leading/trailing whitespace"""
        assert normalize_product_name("  Tomater  ") == "tomat"
        assert normalize_product_name("\tApples\n") == "apple"


# ---------------------------------------------------------------------------
# Product name matching
# ---------------------------------------------------------------------------


class TestProductNamesMatch:
    """Test the product_names_match function."""

    def test_exact_match(self):
        """Exact matches should match"""
        assert product_names_match("Tomat", "Tomat") is True
        assert product_names_match("Apple", "Apple") is True

    def test_case_insensitive_match(self):
        """Case should not matter"""
        assert product_names_match("Tomat", "tomat") is True
        assert product_names_match("APPLE", "apple") is True

    def test_singular_plural_swedish(self):
        """Swedish singular ↔ plural should match"""
        assert product_names_match("Tomat", "Tomater") is True
        assert product_names_match("Tomater", "Tomat") is True
        assert product_names_match("Äpple", "Äpplen") is True
        assert product_names_match("Gurka", "Gurkor") is True

    def test_singular_plural_english(self):
        """English singular ↔ plural should match"""
        assert product_names_match("Apple", "Apples") is True
        assert product_names_match("Apples", "Apple") is True
        assert product_names_match("Berry", "Berries") is True
        assert product_names_match("Box", "Boxes") is True

    def test_different_products_no_match(self):
        """Different products should not match"""
        assert product_names_match("Tomat", "Gurka") is False
        assert product_names_match("Apple", "Orange") is False
        assert product_names_match("Mjölk", "Smör") is False

    def test_whitespace_variants_match(self):
        """Whitespace differences should still match"""
        assert product_names_match("  Tomat  ", "Tomat") is True
        assert product_names_match("Apple", "  Apple  ") is True

    def test_none_handling(self):
        """None values should match each other but not real values"""
        assert product_names_match(None, None) is True
        assert product_names_match(None, "Tomat") is False
        assert product_names_match("Apple", None) is False

    def test_empty_string_handling(self):
        """Empty strings should match each other but not real values"""
        assert product_names_match("", "") is True
        assert product_names_match("", "Tomat") is False
        assert product_names_match("Apple", "") is False

    def test_realistic_shopping_scenarios(self):
        """Real-world shopping list scenarios"""
        # User adds "Tomater" (plural), recipe adds "Tomat" (singular) → merge
        assert product_names_match("Tomater", "Tomat") is True

        # User adds "Mjölk", recipe adds "Mjölk" → merge
        assert product_names_match("Mjölk", "Mjölk") is True

        # Different products → don't merge
        assert product_names_match("Äpple", "Päron") is False

        # English recipe adds "Eggs", user list has "Egg" → merge
        assert product_names_match("Egg", "Eggs") is True

        # Variation in capitalization → merge
        assert product_names_match("Potatis", "POTATIS") is True

    def test_definite_forms_swedish(self):
        """Swedish definite forms should also match"""
        # "Äpplet" (the apple) should match "Äpple" (apple)
        assert product_names_match("Äpplet", "Äpple") is True
        # "Äpplena" (the apples) should match "Äpple"
        assert product_names_match("Äpplena", "Äpple") is True

    def test_mixed_language_no_false_positives(self):
        """Should not create false positives between languages"""
        # Different products in different languages
        assert product_names_match("Ris", "Rice") is False
        assert product_names_match("Bröd", "Bread") is False
