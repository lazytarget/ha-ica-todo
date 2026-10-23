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

    assert events[0].data["entity_id"] == "todo.ica_veckohandling"
    assert events[0].data["added"] == [{"uid": "row-ost", "summary": "Ost"}]


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
