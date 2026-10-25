"""Tests for event payload helpers and list row diffing."""

import importlib.util
import os

_utils_path = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "ica", "utils.py"
)
_spec = importlib.util.spec_from_file_location("ica_utils_events", _utils_path)
_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils)


def test_resolve_list_entity_ids_case_insensitive():
    entries = [
        ("entry1-ABC-123", "todo.ica_milk"),
        ("entry1-baseitems", "todo.ica_favorite_articles"),
        ("entry2-ABC-123", "todo.other"),
    ]
    result = _utils.resolve_list_entity_ids(entries, "entry1", ["abc-123", "nope"])
    assert result == {"abc-123": "todo.ica_milk"}


def test_build_lists_changed_event():
    assert _utils.build_lists_changed_event("e", ["a"], None, {"a": "todo.x"}) == {
        "config_entry_id": "e",
        "created": ["a"],
        "deleted": [],
        "entities": {"a": "todo.x"},
    }


def _row(offline_id, name, striked=False, **kwargs):
    return {
        "offlineId": offline_id,
        "productName": name,
        "isStrikedOver": striked,
        **kwargs,
    }


def test_diff_list_rows():
    old = [
        {"offlineId": "1", "productName": "Milk", "quantity": 1, "latestChange": "a"},
        {"offlineId": "2", "productName": "Eggs"},
    ]
    new = [
        {"offlineId": "1", "productName": "Milk", "quantity": 2, "latestChange": "b"},
        {"offlineId": "3", "productName": "Bread"},
    ]
    diff = _utils.diff_list_rows(old, new)
    assert diff["added"] == [{"uid": "3", "summary": "Bread", "item": new[1]}]
    assert diff["removed"] == [{"uid": "2", "summary": "Eggs", "item": old[1]}]
    assert diff["changed"] == [
        {"uid": "1", "summary": "Milk", "changed_props": ["quantity"], "item": new[0]}
    ]
    assert diff["completed"] == []
    assert diff["reopened"] == []


def test_diff_list_rows_no_changes():
    rows = [{"offlineId": "1", "productName": "Milk", "latestChange": "a"}]
    same = [{"offlineId": "1", "productName": "Milk", "latestChange": "b"}]
    assert not any(_utils.diff_list_rows(rows, same).values())


def test_diff_list_rows_completed_and_reopened():
    old = [_row("a", "Mjölk"), _row("b", "Bröd", striked=True)]
    new = [_row("a", "Mjölk", striked=True), _row("b", "Bröd")]
    diff = _utils.diff_list_rows(old, new)
    assert [e["summary"] for e in diff["completed"]] == ["Mjölk"]
    assert [e["summary"] for e in diff["reopened"]] == ["Bröd"]
    # Also reported as changed, with the flag as the changed property
    assert [e["changed_props"] for e in diff["changed"]] == [
        ["isStrikedOver"],
        ["isStrikedOver"],
    ]


def test_diff_list_rows_other_property_changes_are_not_completed():
    diff = _utils.diff_list_rows(
        [_row("a", "Mjölk", quantity=1)], [_row("a", "Mjölk", quantity=2)]
    )
    assert len(diff["changed"]) == 1
    assert diff["completed"] == []
    assert diff["reopened"] == []


def test_diff_list_rows_item_leaves_out_offer_details():
    old = [_row("a", "Mjölk")]
    new = [_row("a", "Mjölk", offer={"id": "o1"})]
    # Offer details are added by the todo entity and are not a row change
    assert not any(_utils.diff_list_rows(old, new).values())
    added = _utils.diff_list_rows([], new)["added"]
    assert "offer" not in added[0]["item"]


def test_diff_list_rows_offline_id_is_case_insensitive():
    old = [_row("ABC-1", "Mjölk")]
    new = [_row("abc-1", "Mjölk", striked=True)]
    diff = _utils.diff_list_rows(old, new)
    assert diff["added"] == []
    assert diff["removed"] == []
    assert len(diff["completed"]) == 1


def test_diff_list_rows_handles_none_and_missing_offline_id():
    assert not any(_utils.diff_list_rows(None, [{"productName": "X"}]).values())
