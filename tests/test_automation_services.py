"""Tests for the offer and refresh services."""

from .conftest import LIST_ID


async def test_get_offers_returns_valid_offers(hass, loaded_entry, mock_api):
    result = await hass.services.async_call(
        "ica", "get_offers", {}, blocking=True, return_response=True
    )

    assert result["success"] is True
    assert [o["id"] for o in result["data"]] == ["offer-1"]


async def test_get_offers_leaves_out_expired_offers(hass, loaded_entry, mock_api):
    coordinator = loaded_entry.runtime_data
    offers = await coordinator._ica_offers.get_value()
    await coordinator._ica_offers.set_value(
        {
            **offers,
            "old": {**offers["offer-1"], "id": "old", "validTo": "2020-01-01T23:59:59"},
        }
    )

    result = await hass.services.async_call(
        "ica", "get_offers", {}, blocking=True, return_response=True
    )

    assert [o["id"] for o in result["data"]] == ["offer-1"]


async def test_get_offers_favorites_only(hass, loaded_entry, mock_api):
    coordinator = loaded_entry.runtime_data
    call = {"favorites_only": True}

    result = await hass.services.async_call(
        "ica", "get_offers", call, blocking=True, return_response=True
    )
    assert result["data"] == []

    mock_api.baseitems.append(
        {"id": "base-3", "text": "Banan", "articleEan": "04011800420710"}
    )
    await coordinator.async_get_baseitems(invalidate_cache=True)
    result = await hass.services.async_call(
        "ica", "get_offers", call, blocking=True, return_response=True
    )
    assert [o["id"] for o in result["data"]] == ["offer-1"]


async def test_refresh_shopping_lists_picks_up_changes(hass, loaded_entry, mock_api):
    events = []
    hass.bus.async_listen("ica_list_items_changed", events.append)
    mock_api.lists[LIST_ID]["rows"].append(
        {"id": 14, "offlineId": "row-ost", "productName": "Ost", "isStrikedOver": False}
    )

    result = await hass.services.async_call(
        "ica", "refresh_shopping_lists", {}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()

    assert result["success"] is True
    assert [lst["offlineId"] for lst in result["data"]] == [LIST_ID]
    assert [e["uid"] for e in events[0].data["added"]] == ["row-ost"]
    assert events[0].data["origin"] == "ica"
