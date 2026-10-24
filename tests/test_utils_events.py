"""Tests for the change detection and matching used by automation events/services."""

import importlib.util
import os
from datetime import datetime

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

get_shopping_list_item_changes = _utils.get_shopping_list_item_changes
match_offers_to_baseitems = _utils.match_offers_to_baseitems
is_offer_valid = _utils.is_offer_valid


def _row(offline_id, name, striked=False, **kwargs):
    return {
        "offlineId": offline_id,
        "productName": name,
        "isStrikedOver": striked,
        **kwargs,
    }


# ---------------------------------------------------------------------------
# Shopping list item changes
# ---------------------------------------------------------------------------


class TestShoppingListItemChanges:
    def test_no_changes(self):
        rows = [_row("a", "Mjölk"), _row("b", "Bröd", striked=True)]
        changes = get_shopping_list_item_changes(rows, [dict(r) for r in rows])
        assert not any(changes.values())

    def test_added_and_removed(self):
        old = [_row("a", "Mjölk"), _row("b", "Bröd")]
        new = [_row("a", "Mjölk"), _row("c", "Ost")]
        changes = get_shopping_list_item_changes(old, new)
        assert [r["productName"] for r in changes["added"]] == ["Ost"]
        assert [r["productName"] for r in changes["removed"]] == ["Bröd"]
        assert changes["completed"] == []
        assert changes["reopened"] == []

    def test_completed_and_reopened(self):
        old = [_row("a", "Mjölk"), _row("b", "Bröd", striked=True)]
        new = [_row("a", "Mjölk", striked=True), _row("b", "Bröd")]
        changes = get_shopping_list_item_changes(old, new)
        assert [r["productName"] for r in changes["completed"]] == ["Mjölk"]
        assert [r["productName"] for r in changes["reopened"]] == ["Bröd"]

    def test_removed_row_returns_old_version(self):
        old = [_row("a", "Mjölk", striked=True)]
        changes = get_shopping_list_item_changes(old, [])
        assert changes["removed"] == old

    def test_other_property_changes_are_ignored(self):
        old = [_row("a", "Mjölk", quantity=1)]
        new = [_row("a", "Mjölk", quantity=2)]
        assert not any(get_shopping_list_item_changes(old, new).values())

    def test_offline_id_is_case_insensitive(self):
        old = [_row("ABC-1", "Mjölk")]
        new = [_row("abc-1", "Mjölk", striked=True)]
        changes = get_shopping_list_item_changes(old, new)
        assert changes["added"] == []
        assert changes["removed"] == []
        assert len(changes["completed"]) == 1

    def test_handles_none_and_missing_offline_id(self):
        changes = get_shopping_list_item_changes(None, [{"productName": "X"}])
        assert not any(changes.values())


# ---------------------------------------------------------------------------
# Offer matching against favorite items (baseitems)
# ---------------------------------------------------------------------------


def _offer(offer_id, name, eans=()):
    return {
        "id": offer_id,
        "name": name,
        "eans": [{"id": e, "articleDescription": d} for e, d in eans],
    }


class TestMatchOffersToBaseitems:
    def test_matches_on_ean_ignoring_leading_zeros(self):
        offers = [
            _offer("1", "Bananer", [("4011800420710", "Banan")]),
            _offer("2", "Kaffe", [("7310050001234", "Kaffe")]),
        ]
        baseitems = [{"text": "Banan", "articleEan": "04011800420710"}]
        assert [o["id"] for o in match_offers_to_baseitems(offers, baseitems)] == ["1"]

    def test_matches_on_name_when_favorite_has_no_ean(self):
        offers = [
            _offer("1", "Tomater i kruka"),
            _offer("2", "Gurka"),
            _offer("3", "Grönsaker", [("123", "Tomat")]),
        ]
        baseitems = [{"text": "Tomater"}]
        assert [o["id"] for o in match_offers_to_baseitems(offers, baseitems)] == ["3"]

    def test_name_is_not_matched_for_favorites_with_ean(self):
        offers = [_offer("1", "Banan", [("999", "Banan")])]
        baseitems = [{"text": "Banan", "articleEan": "123"}]
        assert match_offers_to_baseitems(offers, baseitems) == []

    def test_no_baseitems(self):
        offers = [_offer("1", "Banan")]
        assert match_offers_to_baseitems(offers, []) == []
        assert match_offers_to_baseitems(offers, None) == []

    def test_offer_without_eans(self):
        offers = [{"id": "1", "name": "Mjölk", "eans": None}]
        baseitems = [{"text": "mjölk"}]
        assert match_offers_to_baseitems(offers, baseitems) == offers


# ---------------------------------------------------------------------------
# Offer validity
# ---------------------------------------------------------------------------


_OFFER = {"validFrom": "2026-10-19T00:00:00", "validTo": "2026-11-08T23:59:59"}


class TestIsOfferValid:
    def test_within_period(self):
        assert is_offer_valid(_OFFER, datetime(2026, 10, 24, 12, 0))

    def test_before_and_after_period(self):
        assert not is_offer_valid(_OFFER, datetime(2026, 10, 18, 23, 59))
        assert not is_offer_valid(_OFFER, datetime(2026, 11, 9, 0, 0))

    def test_missing_dates_are_open_ended(self):
        assert is_offer_valid({}, datetime(2026, 10, 24))
