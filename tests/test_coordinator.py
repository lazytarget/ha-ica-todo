"""Tests for the ICA coordinator, API client and cache."""

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from custom_components.ica import http_requests
from custom_components.ica.caching import CacheEntry, cache_file_path
from custom_components.ica.icaapi import IcaAPI
from custom_components.ica.utils import parse_aware_datetime, utc_timestamp

from .conftest import LIST_ID


async def test_no_offer_details_keeps_cached_offers(hass, loaded_entry, mock_api):
    coordinator = loaded_entry.runtime_data
    assert coordinator.get_offer_info("offer-1")

    async def no_details(store_ids, offer_ids):
        return []

    mock_api.search_offers = no_details
    offers = await coordinator._update_offer_details()
    assert isinstance(offers, dict)
    assert "offer-1" in offers


async def test_no_offers_keeps_cached_offers(hass, loaded_entry, mock_api):
    coordinator = loaded_entry.runtime_data
    mock_api.offers = []
    offers = await coordinator._update_offer_details()
    assert isinstance(offers, dict)
    assert "offer-1" in offers


async def test_expired_offers_are_removed(hass, loaded_entry, mock_api):
    coordinator = loaded_entry.runtime_data
    await coordinator._ica_offers.set_value(
        {
            "old": {"id": "old", "validTo": "2020-01-01T23:59:59"},
            "recent": {"id": "recent", "validTo": utc_timestamp()},
        }
    )
    offers = await coordinator._update_offer_details()
    assert "old" not in offers
    assert "recent" in offers
    assert "offer-1" in offers


async def test_new_offers_event(hass, loaded_entry, mock_api):
    events = []
    hass.bus.async_listen("ica_new_offers", events.append)
    mock_api.offers.append({"id": "offer-2", "name": "Ost", "eans": []})

    await loaded_entry.runtime_data._update_offer_details()
    await hass.async_block_till_done()

    assert [o["id"] for o in events[0].data["new_offers"]] == ["offer-2"]


async def test_list_items_changed_event(hass, loaded_entry, mock_api):
    events = []
    hass.bus.async_listen("ica_list_items_changed", events.append)
    mock_api.lists[LIST_ID]["rows"].append(
        {"id": 14, "offlineId": "row-ost", "productName": "Ost", "isStrikedOver": False}
    )

    await loaded_entry.runtime_data.async_refresh_all()
    await hass.async_block_till_done()

    data = events[0].data
    assert data["entity_id"] == "todo.ica_veckohandling"
    assert data["config_entry_id"] == loaded_entry.entry_id
    assert data["shopping_list_name"] == "Veckohandling"
    assert data["origin"] == "ica"
    assert [(e["uid"], e["summary"]) for e in data["added"]] == [("row-ost", "Ost")]
    assert data["added"][0]["item"]["productName"] == "Ost"


async def test_list_items_changed_event_for_changes_made_in_home_assistant(
    hass, loaded_entry, mock_api
):
    events = []
    hass.bus.async_listen("ica_list_items_changed", events.append)

    await loaded_entry.runtime_data.sync_shopping_list(
        {
            "offlineId": LIST_ID,
            "changedRows": [{"offlineId": "row-gurka", "isStrikedOver": True}],
        }
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["origin"] == "home_assistant"
    assert [e["uid"] for e in events[0].data["completed"]] == ["row-gurka"]
    assert events[0].data["reopened"] == []


async def test_no_list_items_changed_event_when_nothing_changed(
    hass, loaded_entry, mock_api
):
    events = []
    hass.bus.async_listen("ica_list_items_changed", events.append)

    await loaded_entry.runtime_data.async_refresh_all()
    await hass.async_block_till_done()

    assert events == []


async def test_favorite_offers_event(hass, loaded_entry, mock_api):
    events = []
    hass.bus.async_listen("ica_favorite_offers", events.append)
    mock_api.baseitems.append({"id": "base-3", "text": "Ost", "articleEan": "0123"})
    await loaded_entry.runtime_data.async_get_baseitems(invalidate_cache=True)
    mock_api.offers.append(
        {
            "id": "offer-2",
            "name": "Ost",
            "eans": [{"id": "123", "articleDescription": "Ost"}],
        }
    )
    mock_api.offers.append({"id": "offer-3", "name": "Skinka", "eans": []})

    await loaded_entry.runtime_data._update_offer_details()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["config_entry_id"] == loaded_entry.entry_id
    assert events[0].data["offer_ids"] == ["offer-2"]


ITEM_EVENTS = (
    "ica_shopping_list_item_added",
    "ica_shopping_list_item_removed",
    "ica_shopping_list_item_completed",
    "ica_shopping_list_item_reopened",
)


async def test_per_item_events_are_off_by_default(hass, loaded_entry, mock_api):
    events = []
    for event_type in ITEM_EVENTS:
        hass.bus.async_listen(event_type, events.append)
    mock_api.lists[LIST_ID]["rows"].append(
        {"id": 14, "offlineId": "row-ost", "productName": "Ost", "isStrikedOver": False}
    )

    await loaded_entry.runtime_data.async_refresh_all()
    await hass.async_block_till_done()

    assert events == []


async def test_per_item_events_when_enabled(hass, loaded_entry, mock_api):
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, "per_item_events": True}
    )
    await hass.async_block_till_done()  # the options change reloads the entry
    events = {}
    for event_type in ITEM_EVENTS:
        hass.bus.async_listen(
            event_type, lambda e: events.setdefault(e.event_type, []).append(e.data)
        )
    combined = []
    hass.bus.async_listen("ica_list_items_changed", combined.append)
    rows = mock_api.lists[LIST_ID]["rows"]
    rows.append(
        {"id": 14, "offlineId": "row-ost", "productName": "Ost", "isStrikedOver": False}
    )
    rows[:] = [r for r in rows if r["offlineId"] != "row-banan"]
    for row in rows:
        if row["offlineId"] == "row-gurka":
            row["isStrikedOver"] = True
        if row["offlineId"] == "row-mjolk":
            row["isStrikedOver"] = False

    await loaded_entry.runtime_data.async_refresh_all()
    await hass.async_block_till_done()

    assert set(events) == set(ITEM_EVENTS)
    added = events["ica_shopping_list_item_added"][0]
    assert added["product_name"] == "Ost"
    assert added["item"]["offlineId"] == "row-ost"
    assert added["origin"] == "ica"
    assert added["config_entry_id"] == loaded_entry.entry_id
    assert added["entity_id"] == "todo.ica_veckohandling"
    assert added["shopping_list_name"] == "Veckohandling"
    assert events["ica_shopping_list_item_removed"][0]["product_name"] == "Banan"
    assert events["ica_shopping_list_item_completed"][0]["product_name"] == "Gurka"
    assert events["ica_shopping_list_item_reopened"][0]["product_name"] == "Mjölk"
    # The combined event is still fired once
    assert len(combined) == 1


def test_list_caches_expire_before_the_next_update(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    interval = coordinator.update_interval.total_seconds()
    expected = min(300, interval - 30)
    assert coordinator._ica_shopping_lists._expiry_seconds == expected
    assert coordinator._ica_baseitems._expiry_seconds == expected


async def test_deleted_list_is_untracked_without_reload(hass, loaded_entry, mock_api):
    import requests

    async def missing(list_id):
        response = MagicMock(status_code=404)
        raise requests.exceptions.HTTPError(response=response)

    mock_api.get_shopping_list = missing
    with patch.object(hass.config_entries, "async_reload") as reload:
        await loaded_entry.runtime_data.async_refresh_all()
        await hass.async_block_till_done()

    assert loaded_entry.options["shopping_lists"] == []
    reload.assert_not_called()


def test_sync_sends_all_row_changes():
    api = IcaAPI({"username": "u", "password": "p"}, None, session=MagicMock())
    with patch("custom_components.ica.icaapi.post") as post:
        api.sync_shopping_list(
            {
                "offlineId": LIST_ID,
                "createdRows": [{"productName": "Ägg"}],
                "changedRows": [{"offlineId": "row-gurka", "quantity": 3}],
            }
        )
    sent = post.call_args.args[3]
    assert sent == {
        "createdRows": [{"productName": "Ägg"}],
        "changedRows": [{"offlineId": "row-gurka", "quantity": 3}],
    }


@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_requests_have_timeouts(method):
    session = MagicMock()
    response = getattr(session, method).return_value
    response.status_code = 200
    response.ok = True
    response.json.return_value = {}
    response.text = "{}"

    getattr(http_requests, method)(session, "https://example.invalid", "key")

    assert getattr(session, method).call_args.kwargs["timeout"]


async def test_corrupt_cache_file_is_ignored(hass):
    path = cache_file_path(hass, "test.corrupt")

    def write():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"timestamp": "2024-')

    await hass.async_add_executor_job(write)

    async def factory():
        return ["fresh"]

    entry = CacheEntry(hass, "test.corrupt", factory)
    assert await entry.get_value() == ["fresh"]
    assert '"fresh"' in await hass.async_add_executor_job(path.read_text)


async def test_cache_loads_fresh_value_from_file(hass):
    calls = []

    async def factory():
        calls.append(1)
        return ["api"]

    first = CacheEntry(hass, "test.fresh", factory)
    assert await first.get_value() == ["api"]

    second = CacheEntry(hass, "test.fresh", factory)
    assert await second.get_value() == ["api"]
    assert len(calls) == 1


def test_utc_timestamp_format():
    when = dt.datetime(
        2024, 3, 10, 13, 0, 5, 123, tzinfo=dt.timezone(dt.timedelta(hours=1))
    )
    assert utc_timestamp(when) == "2024-03-10T12:00:05Z"


def test_parse_aware_datetime():
    stockholm = dt.timezone(dt.timedelta(hours=2))
    assert parse_aware_datetime("2024-06-30T23:59:59", stockholm).tzinfo == stockholm
    assert parse_aware_datetime("2024-06-30T21:59:59Z").tzinfo == dt.UTC
    assert parse_aware_datetime(None) is None
    assert parse_aware_datetime("not a date") is None


@pytest.mark.parametrize(
    ("summary", "name", "quantity", "unit"),
    [
        ("2 st Gurka", "Gurka", 2, "st"),
        ("1 gurka", "gurka", 1, None),
        ("500g mjöl", "mjöl", 500, "g"),
        ("1,5 l Mjölk", "Mjölk", 1.5, "l"),
        ("2-3 gurka", "gurka", 3, None),
        ("2 gula lökar", "gula lökar", 2, None),
        ("7 up", "up", 7, None),
    ],
)
async def test_parse_summary_quantity(
    hass, loaded_entry, summary, name, quantity, unit
):
    ti = loaded_entry.runtime_data.parse_summary(summary)
    assert ti["productName"] == name
    assert ti["quantity"] == quantity
    assert ti.get("unit") == unit


@pytest.mark.parametrize(
    "summary",
    [
        "7up",
        "100% juice",
        "2x Gurka",
        "7-Eleven",
        "3-pack toapapper",
        "5:2 yoghurt",
        "500 g",
        "Mjölk",
    ],
)
async def test_parse_summary_keeps_names_that_start_with_a_digit(
    hass, loaded_entry, summary
):
    ti = loaded_entry.runtime_data.parse_summary(summary)
    assert ti["productName"] == summary
    assert ti["summary"] == summary
    assert "quantity" not in ti
