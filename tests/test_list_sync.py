"""Tests for syncing another to-do list into an ICA list."""

import copy
import uuid
from datetime import timedelta

import pytest
from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ica.const import (
    CONF_AUTH_STATE,
    CONF_ICA_ID,
    CONF_ICA_PIN,
    CONF_LIST_SYNC_SOURCE,
    CONF_LIST_SYNC_TARGET,
    CONF_LIST_SYNCS,
    CONF_SHOPPING_LISTS,
    DOMAIN,
    account_unique_id,
)
from custom_components.ica.list_sync import clean_summary, plan_list_sync

from .conftest import AUTH_STATE, LIST_ID, PERSONAL_ID, PIN

SOURCE = "todo.mealie_veckohandling"
PAIR = {CONF_LIST_SYNC_SOURCE: SOURCE, CONF_LIST_SYNC_TARGET: LIST_ID}


def _parse(summary: str) -> dict:
    return {"summary": summary, "productName": summary}


def _ica_list(*rows: dict) -> dict:
    return {"offlineId": LIST_ID, "title": "Veckohandling", "rows": list(rows)}


def _open(uid: str, summary: str) -> dict:
    return {"uid": uid, "summary": summary, "status": "needs_action"}


def test_plan_creates_rows_for_new_items():
    sync, synced = plan_list_sync(
        _ica_list(), [_open("a", "Mjölk")], {}, _parse, new_row_id=lambda: "row-a"
    )

    assert sync["offlineId"] == LIST_ID
    assert [r["productName"] for r in sync["createdRows"]] == ["Mjölk"]
    row = sync["createdRows"][0]
    assert row["offlineId"] == "row-a"
    assert row["sourceId"] == -1
    assert row["isStrikedOver"] is False
    assert "changedRows" not in sync
    assert "deletedRows" not in sync
    assert synced == {"a": {"row_id": "row-a", "summary": "Mjölk"}}


def test_plan_deletes_the_row_of_an_item_that_is_no_longer_open():
    synced = {"a": {"row_id": "row-a", "summary": "Mjölk"}}
    rows = [{"offlineId": "ROW-A", "productName": "Mjölk"}]

    sync, synced = plan_list_sync(_ica_list(*rows), [], synced, _parse)

    # ICA returns offlineId in upper case
    assert sync["deletedRows"] == ["ROW-A"]
    assert synced == {}


def test_plan_does_not_re_add_a_row_deleted_in_ica():
    synced = {"a": {"row_id": "row-a", "summary": "Mjölk"}}

    sync, remembered = plan_list_sync(
        _ica_list(), [_open("a", "Mjölk")], synced, _parse
    )

    assert sync is None
    assert remembered == synced


def test_plan_forgets_an_item_once_it_is_gone_from_both_lists():
    synced = {"a": {"row_id": "row-a", "summary": "Mjölk"}}

    sync, remembered = plan_list_sync(_ica_list(), [], synced, _parse)

    assert sync is None
    assert remembered == {}


def test_plan_updates_the_row_of_an_edited_item():
    synced = {"a": {"row_id": "row-a", "summary": "Mjölk"}}
    rows = [{"offlineId": "row-a", "productName": "Mjölk", "isStrikedOver": True}]

    sync, synced = plan_list_sync(
        _ica_list(*rows), [_open("a", "Havremjölk")], synced, _parse
    )

    (row,) = sync["changedRows"]
    assert row["offlineId"] == "row-a"
    assert row["productName"] == "Havremjölk"
    # Checked off in ICA stays checked off
    assert row["isStrikedOver"] is True
    assert synced["a"]["summary"] == "Havremjölk"


def test_plan_leaves_other_rows_alone_and_is_idempotent():
    rows = [{"offlineId": "row-gurka", "productName": "Gurka"}]
    sync, synced = plan_list_sync(
        _ica_list(*rows), [_open("a", "Mjölk")], {}, _parse, new_row_id=lambda: "r"
    )
    assert "deletedRows" not in sync
    assert "changedRows" not in sync

    rows.extend(sync["createdRows"])
    sync, again = plan_list_sync(
        _ica_list(*rows), [_open("a", "Mjölk")], synced, _parse
    )
    assert sync is None
    assert again == synced


def test_plan_skips_items_without_a_summary():
    sync, synced = plan_list_sync(
        _ica_list(), [_open("a", "  "), {"summary": "No uid"}], {}, _parse
    )

    assert sync is None
    assert synced == {}


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("6 ägg None", "6 ägg"),
        (" 1 dl Arla Ko® Standardmjölk None ", "1 dl Arla Ko® Standardmjölk"),
        ("Ost None None", "Ost"),
        ("2 st Mjölk", "2 st Mjölk"),
        ("Nonelösning", "Nonelösning"),
        (None, ""),
    ],
)
def test_clean_summary_strips_mealies_trailing_none(summary, expected):
    assert clean_summary(summary) == expected


def test_plan_strips_mealies_trailing_none():
    sync, synced = plan_list_sync(
        _ica_list(), [_open("a", "6 ägg None")], {}, _parse, new_row_id=lambda: "r"
    )

    assert [r["productName"] for r in sync["createdRows"]] == ["6 ägg"]
    assert synced == {"a": {"row_id": "r", "summary": "6 ägg"}}


class FakeSourceList(TodoListEntity):
    """A to-do list of another integration, like Mealie."""

    _attr_name = "Mealie Veckohandling"
    _attr_unique_id = "fake-source"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self) -> None:
        self.entity_id = SOURCE
        self._attr_todo_items: list[TodoItem] = []

    async def async_create_todo_item(self, item: TodoItem) -> None:
        self._attr_todo_items.append(
            TodoItem(
                summary=item.summary,
                uid=str(uuid.uuid4()),
                status=TodoItemStatus.NEEDS_ACTION,
            )
        )
        self.async_write_ha_state()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        self._attr_todo_items = [
            item if x.uid == item.uid else x for x in self._attr_todo_items
        ]
        self.async_write_ha_state()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        self._attr_todo_items = [x for x in self._attr_todo_items if x.uid not in uids]
        self.async_write_ha_state()


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="ICA - Test Person",
        version=1,
        minor_version=3,
        unique_id=account_unique_id(PERSONAL_ID),
        data={
            CONF_ICA_ID: PERSONAL_ID,
            CONF_ICA_PIN: PIN,
            CONF_AUTH_STATE: copy.deepcopy(AUTH_STATE),
        },
        options={
            CONF_SHOPPING_LISTS: [LIST_ID],
            "scan_interval": 5,
            CONF_LIST_SYNCS: [PAIR],
        },
    )


@pytest.fixture
async def source(hass, loaded_entry) -> FakeSourceList:
    entity = FakeSourceList()
    await hass.data["todo"].async_add_entities([entity])
    await hass.async_block_till_done()
    return entity


async def _add(hass, summary: str) -> None:
    await hass.services.async_call(
        "todo",
        "add_item",
        {"item": summary},
        target={"entity_id": SOURCE},
        blocking=True,
    )


async def _sync(hass) -> dict:
    return await hass.services.async_call(
        DOMAIN, "sync_lists", {}, blocking=True, return_response=True
    )


def _row(fake_api, product_name: str) -> dict | None:
    return next(
        (
            r
            for r in fake_api.lists[LIST_ID]["rows"]
            if r["productName"] == product_name
        ),
        None,
    )


async def test_items_are_added_to_ica_and_removed_when_checked_off(
    hass, source, mock_api
):
    rows_before = copy.deepcopy(mock_api.lists[LIST_ID]["rows"])
    await _add(hass, "2 st Ost")

    assert await _sync(hass) == {"created": 1, "changed": 0, "deleted": 0}
    row = _row(mock_api, "Ost")
    assert row["quantity"] == 2
    assert row["unit"] == "st"
    assert hass.states.get("todo.ica_veckohandling").state == "3"

    item = source.todo_items[0]
    await hass.services.async_call(
        "todo",
        "update_item",
        {"item": item.uid, "status": "completed"},
        target={"entity_id": SOURCE},
        blocking=True,
    )

    assert await _sync(hass) == {"created": 0, "changed": 0, "deleted": 1}
    assert mock_api.lists[LIST_ID]["rows"] == rows_before


async def test_syncs_automatically_when_the_source_changes(hass, source, mock_api):
    await _add(hass, "Ägg")
    assert _row(mock_api, "Ägg") is None

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()

    assert _row(mock_api, "Ägg") is not None
    # Nothing left to do afterwards
    assert await _sync(hass) == {"created": 0, "changed": 0, "deleted": 0}


async def test_row_deleted_in_ica_is_not_added_again(hass, source, mock_api):
    await _add(hass, "Ägg")
    await _sync(hass)
    row = _row(mock_api, "Ägg")

    await hass.services.async_call(
        "todo",
        "remove_item",
        {"item": [row["offlineId"]]},
        target={"entity_id": "todo.ica_veckohandling"},
        blocking=True,
    )

    assert await _sync(hass) == {"created": 0, "changed": 0, "deleted": 0}
    assert _row(mock_api, "Ägg") is None


async def test_unavailable_source_deletes_nothing(hass, source, mock_api):
    await _add(hass, "Ägg")
    await _sync(hass)

    hass.states.async_set(SOURCE, "unavailable")

    assert await _sync(hass) == {"created": 0, "changed": 0, "deleted": 0}
    assert _row(mock_api, "Ägg") is not None


async def test_synced_items_are_remembered_across_reloads(
    hass, source, loaded_entry, mock_api
):
    await _add(hass, "Ägg")
    await _sync(hass)

    assert await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert await _sync(hass) == {"created": 0, "changed": 0, "deleted": 0}

    await hass.services.async_call(
        "todo",
        "remove_item",
        {"item": [source.todo_items[0].uid]},
        target={"entity_id": SOURCE},
        blocking=True,
    )
    assert await _sync(hass) == {"created": 0, "changed": 0, "deleted": 1}
    assert _row(mock_api, "Ägg") is None


async def _start_add_list_sync(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_list_sync"}
    )


async def test_options_flow_adds_a_list_sync(hass, source, loaded_entry):
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_LIST_SYNCS: []}
    )
    await hass.async_block_till_done()

    result = await _start_add_list_sync(hass, loaded_entry)
    assert result["step_id"] == "add_list_sync"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIST_SYNC_SOURCE: SOURCE}
    )
    assert result["step_id"] == "add_list_sync_target"
    assert result["description_placeholders"] == {"source": "Mealie Veckohandling"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIST_SYNC_TARGET: LIST_ID}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_LIST_SYNCS] == [PAIR]
    assert loaded_entry.runtime_data.list_sync is not None


async def test_options_flow_suggests_the_list_named_like_the_source(
    hass, source, loaded_entry, mock_api
):
    mock_api.lists["LIST-2"] = {
        "id": 2,
        "offlineId": "LIST-2",
        "title": "Fest",
        "rows": [],
    }
    hass.config_entries.async_update_entry(
        loaded_entry,
        options={**loaded_entry.options, CONF_SHOPPING_LISTS: ["LIST-2", LIST_ID]},
    )
    await hass.async_block_till_done()

    result = await _start_add_list_sync(hass, loaded_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIST_SYNC_SOURCE: SOURCE}
    )

    target = next(k for k in result["data_schema"].schema if k == CONF_LIST_SYNC_TARGET)
    assert target.default() == LIST_ID


async def test_options_flow_rejects_a_duplicate_list_sync(hass, source, loaded_entry):
    result = await _start_add_list_sync(hass, loaded_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIST_SYNC_SOURCE: SOURCE}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIST_SYNC_TARGET: LIST_ID}
    )

    assert result["errors"] == {"base": "list_sync_exists"}


async def test_options_flow_rejects_an_ica_list_as_source(hass, loaded_entry):
    result = await _start_add_list_sync(hass, loaded_entry)

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_LIST_SYNC_SOURCE: "todo.ica_veckohandling"}
        )


async def test_options_flow_removes_a_list_sync(hass, source, loaded_entry):
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert "remove_list_sync" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_list_sync"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIST_SYNCS: [f"{SOURCE}|{LIST_ID.lower()}"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_LIST_SYNCS] == []
    assert loaded_entry.runtime_data.list_sync is None
