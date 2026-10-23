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
    assert diff["added"] == [{"uid": "3", "summary": "Bread"}]
    assert diff["removed"] == ["2"]
    assert diff["changed"] == [
        {"uid": "1", "summary": "Milk", "changed_props": ["quantity"]}
    ]


def test_diff_list_rows_no_changes():
    rows = [{"offlineId": "1", "productName": "Milk", "latestChange": "a"}]
    same = [{"offlineId": "1", "productName": "Milk", "latestChange": "b"}]
    assert not any(_utils.diff_list_rows(rows, same).values())
