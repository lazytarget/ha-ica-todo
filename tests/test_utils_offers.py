"""Tests for the offer matching and validity helpers used by the offer services."""

import datetime as dt
import importlib.util
import os
from zoneinfo import ZoneInfo

# Import utils.py directly to avoid pulling in the full ica package
# (which depends on homeassistant).
_utils_path = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "ica", "utils.py"
)
_spec = importlib.util.spec_from_file_location("ica_utils_offers", _utils_path)
_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils)

match_offers_to_baseitems = _utils.match_offers_to_baseitems
is_offer_valid = _utils.is_offer_valid

STOCKHOLM = ZoneInfo("Europe/Stockholm")


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


_OFFER = {"validFrom": "2026-10-19T00:00:00", "validTo": "2026-11-08T23:59:59"}


class TestIsOfferValid:
    def test_within_period(self):
        now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=STOCKHOLM)
        assert is_offer_valid(_OFFER, now, STOCKHOLM)

    def test_before_and_after_period(self):
        before = dt.datetime(2026, 10, 18, 23, 59, tzinfo=STOCKHOLM)
        after = dt.datetime(2026, 11, 9, 0, 0, tzinfo=STOCKHOLM)
        assert not is_offer_valid(_OFFER, before, STOCKHOLM)
        assert not is_offer_valid(_OFFER, after, STOCKHOLM)

    def test_timestamps_without_offset_are_read_in_the_default_timezone(self):
        # 23:30 UTC is already the next day in Stockholm (CET), 23:59:59 local is not
        now = dt.datetime(2026, 11, 8, 23, 30, tzinfo=dt.UTC)
        assert not is_offer_valid(_OFFER, now, STOCKHOLM)

    def test_missing_dates_are_open_ended(self):
        assert is_offer_valid({}, dt.datetime(2026, 10, 24, tzinfo=dt.UTC), dt.UTC)
