"""Tests for setup, migration and removal of the ICA integration."""

import json
import logging

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ica.caching import cache_file_path
from custom_components.ica.const import (
    CONF_DIRTY_CACHE,
    CONF_ICA_ID,
    CONF_ICA_PIN,
    CONF_JSON_DATA_IN_DESC,
    CONF_SHOPPING_LISTS,
    DOMAIN,
    account_unique_id,
)
from custom_components.ica.exceptions import IcaAuthError

from .conftest import AUTH_STATE, LIST_ID, PERSONAL_ID, PIN


async def test_setup_creates_entities(hass, loaded_entry):
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data.data["shopping_lists"][0]["offlineId"] == LIST_ID

    favorites = hass.states.get("todo.ica_favorite_articles")
    assert favorites is not None
    assert favorites.state == "2"

    shopping_list = hass.states.get("todo.ica_veckohandling")
    assert shopping_list is not None
    assert shopping_list.state == "2"  # two items not striked over
    assert shopping_list.attributes["offline_id"] == LIST_ID
    assert shopping_list.attributes["comment"] == "Fredag"


async def test_secrets_are_not_logged(hass, config_entry, mock_api, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.ica")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert PERSONAL_ID not in caplog.text
    assert "access-token" not in caplog.text
    assert "refresh-token" not in caplog.text
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_cache_files_do_not_contain_personal_id(hass, loaded_entry):
    storage = hass.config.path(".storage")
    files = await hass.async_add_executor_job(
        lambda: [p.name for p in __import__("pathlib").Path(storage).iterdir()]
    )
    ica_files = [f for f in files if f.startswith("ica.")]
    assert ica_files
    assert not [f for f in ica_files if PERSONAL_ID in f]


async def test_auth_failure_starts_reauth(hass, config_entry, mock_api):
    mock_api.login_error = IcaAuthError("bad pin")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f for f in flows if f["context"]["source"] == SOURCE_REAUTH]


async def test_migrate_from_v1_2(hass, mock_api):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=2,
        unique_id=f"{DOMAIN}__{PERSONAL_ID}",
        data={
            CONF_ICA_ID: PERSONAL_ID,
            CONF_ICA_PIN: PIN,
            "auth_state": AUTH_STATE,
            "scan_interval": 10,
            CONF_SHOPPING_LISTS: [LIST_ID],
            CONF_JSON_DATA_IN_DESC: True,
            CONF_DIRTY_CACHE: False,
        },
    )
    entry.add_to_hass(hass)

    old_cache = cache_file_path(hass, f"{PERSONAL_ID}.baseitems")
    legacy_debug = cache_file_path(hass, "offers_changed--base-data")

    def write_old_files():
        old_cache.parent.mkdir(parents=True, exist_ok=True)
        old_cache.write_text(
            json.dumps(
                {
                    "timestamp": "2099-01-01T00:00:00",
                    "key": "x",
                    "value": [{"id": "cached", "text": "Cached", "sortOrder": 0}],
                }
            )
        )
        legacy_debug.write_text("{}")

    await hass.async_add_executor_job(write_old_files)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 3
    assert entry.unique_id == account_unique_id(PERSONAL_ID)
    assert PERSONAL_ID not in entry.unique_id
    assert entry.options == {
        "scan_interval": 10,
        CONF_SHOPPING_LISTS: [LIST_ID],
        CONF_JSON_DATA_IN_DESC: True,
    }
    assert CONF_SHOPPING_LISTS not in entry.data
    assert not await hass.async_add_executor_job(old_cache.exists)
    assert not await hass.async_add_executor_job(legacy_debug.exists)
    new_cache = cache_file_path(hass, f"{entry.entry_id}.baseitems")
    assert await hass.async_add_executor_job(new_cache.exists)

    await hass.config_entries.async_unload(entry.entry_id)


async def test_remove_entry_deletes_cache_files(hass, loaded_entry):
    baseitems = cache_file_path(hass, f"{loaded_entry.entry_id}.baseitems")
    articles = cache_file_path(hass, "articles")
    assert await hass.async_add_executor_job(baseitems.exists)

    await hass.config_entries.async_remove(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert not await hass.async_add_executor_job(baseitems.exists)
    assert not await hass.async_add_executor_job(articles.exists)
