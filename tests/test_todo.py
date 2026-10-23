"""Tests for the ICA to-do entities and list services."""

from datetime import datetime

import pytest
from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.exceptions import ServiceValidationError

from custom_components.ica.const import DOMAIN

from .conftest import LIST_ID

LIST_ENTITY = "todo.ica_veckohandling"
FAVORITES_ENTITY = "todo.ica_favorite_articles"


def _entity(hass, entity_id):
    return hass.data["todo"].get_entity(entity_id)


async def _items(hass, entity_id):
    response = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    return response[entity_id]["items"]


async def test_items_show_quantity_and_offer_due(hass, loaded_entry):
    items = {item["uid"]: item for item in await _items(hass, LIST_ENTITY)}

    assert items["row-gurka"]["summary"] == "1 st Gurka"
    assert items["row-mjolk"]["status"] == "completed"
    # Due date comes from the offer's (naive, local time) validTo
    due = datetime.fromisoformat(items["row-banan"]["due"])
    assert due.tzinfo is not None
    assert (due.year, due.month, due.day) == (2099, 6, 30)


async def test_offer_is_not_written_into_the_cached_rows(hass, loaded_entry):
    cached = loaded_entry.runtime_data.get_shopping_list(LIST_ID)
    banan = next(r for r in cached["rows"] if r["offlineId"] == "row-banan")
    assert "offer" not in banan
    assert "due" not in banan


async def test_add_item_parses_quantity(hass, loaded_entry, mock_api):
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": LIST_ENTITY, "item": "1,5 kg Potatis"},
        blocking=True,
    )

    created = mock_api.syncs[-1]["createdRows"][0]
    assert created["productName"] == "Potatis"
    assert created["quantity"] == 1.5
    assert created["unit"] == "kg"
    assert "summary" not in created
    summaries = [i["summary"] for i in await _items(hass, LIST_ENTITY)]
    assert "1,5 kg Potatis" in summaries


async def test_update_item_sends_timestamp_string(hass, loaded_entry, mock_api):
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": LIST_ENTITY, "item": "row-gurka", "status": "completed"},
        blocking=True,
    )
    changed = mock_api.syncs[-1]["changedRows"][0]
    assert changed["isStrikedOver"] is True
    assert isinstance(changed["latestChange"], str)
    assert changed["latestChange"].endswith("Z")
    assert "+00:00" not in changed["latestChange"]


async def test_upsert_merge_sends_created_and_changed_rows(
    hass, loaded_entry, mock_api
):
    response = await hass.services.async_call(
        DOMAIN,
        "upsert_shopping_list",
        {
            "entity_id": LIST_ENTITY,
            "rows": ["2 st Gurkor", '{"productName": "Ägg", "quantity": 12}'],
            "conflict_mode": "MERGE",
        },
        blocking=True,
        return_response=True,
    )

    assert response[LIST_ENTITY]["success"] is True
    sync = mock_api.syncs[-1]
    assert [r["productName"] for r in sync["changedRows"]] == ["Gurka"]
    assert sync["changedRows"][0]["quantity"] == 3
    assert sync["changedRows"][0]["offlineId"] == "row-gurka"
    assert [r["productName"] for r in sync["createdRows"]] == ["Ägg"]


async def test_upsert_ignore_without_changes_does_not_sync(
    hass, loaded_entry, mock_api
):
    response = await hass.services.async_call(
        DOMAIN,
        "upsert_shopping_list",
        {"entity_id": LIST_ENTITY, "rows": ["Gurka"], "conflict_mode": "IGNORE"},
        blocking=True,
        return_response=True,
    )
    assert response[LIST_ENTITY]["success"] is True
    assert mock_api.syncs == []


async def test_upsert_on_favorites_is_rejected(hass, loaded_entry):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "upsert_shopping_list",
            {"entity_id": FAVORITES_ENTITY, "rows": ["Gurka"]},
            blocking=True,
            return_response=True,
        )


async def test_add_offer_to_list(hass, loaded_entry, mock_api):
    await hass.services.async_call(
        DOMAIN,
        "add_offers_to_shopping_list",
        {"entity_id": LIST_ENTITY, "offer_ids": ["offer-1", "unknown"]},
        blocking=True,
        return_response=True,
    )
    created = mock_api.syncs[-1]["createdRows"]
    assert len(created) == 1
    assert created[0]["offerId"] == "offer-1"
    assert created[0]["productEan"] == "4011800420710"
    assert created[0]["articleGroupId"] == 5


async def test_favorite_update_of_unknown_item_does_not_touch_others(
    hass, loaded_entry, mock_api
):
    entity = _entity(hass, FAVORITES_ENTITY)
    with pytest.raises(ServiceValidationError):
        await entity.async_update_todo_item(
            TodoItem(uid="missing", summary="Te", status=TodoItemStatus.NEEDS_ACTION)
        )
    assert mock_api.baseitem_syncs == []


async def test_favorite_rename_and_delete(hass, loaded_entry, mock_api):
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": FAVORITES_ENTITY, "item": "base-2", "rename": "Havremjölk"},
        blocking=True,
    )
    assert mock_api.baseitems[1]["text"] == "Havremjölk"
    assert mock_api.baseitems[0]["text"] == "Kaffe"

    await hass.services.async_call(
        "todo",
        "remove_item",
        {"entity_id": FAVORITES_ENTITY, "item": "base-1"},
        blocking=True,
    )
    assert [x["id"] for x in mock_api.baseitems] == ["base-2"]
    assert hass.states.get(FAVORITES_ENTITY).state == "1"


async def test_add_favorite_item_by_name(hass, loaded_entry, mock_api):
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": FAVORITES_ENTITY, "item": "Te"},
        blocking=True,
    )
    added = mock_api.baseitems[-1]
    assert added["text"] == "Te"
    assert added["sortOrder"] == 2


async def test_create_and_delete_shopping_list(hass, loaded_entry, mock_api):
    events = []
    hass.bus.async_listen("ica_lists_changed", events.append)

    response = await hass.services.async_call(
        DOMAIN,
        "create_shopping_list",
        {"integration": loaded_entry.entry_id, "title": "Fest"},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    offline_id = response["offline_id"]
    assert offline_id.upper() in loaded_entry.options["shopping_lists"]
    assert events[-1].data["entities"] == {offline_id: "todo.ica_fest"}
    assert hass.states.get("todo.ica_fest") is not None

    await hass.services.async_call(
        DOMAIN,
        "delete_shopping_list",
        {"entity_id": "todo.ica_fest"},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert offline_id.upper() not in loaded_entry.options["shopping_lists"]
    assert hass.states.get("todo.ica_fest") is None


async def test_refresh_all(hass, loaded_entry, mock_api):
    mock_api.lists[LIST_ID]["rows"].append(
        {"id": 14, "offlineId": "row-new", "productName": "Ost", "isStrikedOver": False}
    )
    response = await hass.services.async_call(
        DOMAIN, "refresh_all", {}, blocking=True, return_response=True
    )
    assert response == {"updated_integrations": 1}
    assert "Ost" in [i["summary"] for i in await _items(hass, LIST_ENTITY)]
