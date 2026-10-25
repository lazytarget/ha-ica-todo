"""Tests for the ICA config, reauth and options flows."""

import pytest
import requests
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

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

from .conftest import LIST_ID, PERSONAL_ID, PIN


async def test_user_flow_creates_entry(hass, mock_api):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ICA_ID: f" {PERSONAL_ID} ", CONF_ICA_PIN: PIN, "scan_interval": 15},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ICA - Test Person"
    assert result["data"][CONF_ICA_ID] == PERSONAL_ID
    assert result["data"]["auth_state"]["token"]["access_token"] == "access-token"
    assert result["options"] == {"scan_interval": 15}
    entry = result["result"]
    assert entry.unique_id == account_unique_id(PERSONAL_ID)
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (IcaAuthError("bad"), "invalid_auth"),
        (requests.exceptions.ConnectionError("down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(hass, mock_api, error, expected):
    mock_api.login_error = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ICA_ID: PERSONAL_ID, CONF_ICA_PIN: PIN, "scan_interval": 5},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_reauth_updates_pin(hass, loaded_entry, mock_api):
    result = await loaded_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ICA_PIN: "9999"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert loaded_entry.data[CONF_ICA_PIN] == "9999"


async def test_reauth_invalid_pin(hass, loaded_entry, mock_api):
    result = await loaded_entry.start_reauth_flow(hass)
    mock_api.login_error = IcaAuthError("bad")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ICA_PIN: "0000"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    assert loaded_entry.data[CONF_ICA_PIN] == PIN


async def test_options_flow_changes_lists_and_reloads(hass, loaded_entry, mock_api):
    mock_api.lists["LIST-2"] = {
        "id": 2,
        "offlineId": "LIST-2",
        "title": "Fest",
        "rows": [],
    }
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 10,
            CONF_JSON_DATA_IN_DESC: True,
            "per_item_events": True,
            CONF_SHOPPING_LISTS: [LIST_ID, "LIST-2"],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_SHOPPING_LISTS] == [LIST_ID, "LIST-2"]
    assert loaded_entry.options["scan_interval"] == 10
    assert loaded_entry.options["per_item_events"] is True
    # The reload refetched the lists and cleared the dirty flag again
    assert loaded_entry.data[CONF_DIRTY_CACHE] is False
    assert hass.states.get("todo.ica_fest") is not None


async def test_lists_picked_right_after_setup_get_entities(hass, mock_api):
    """Issue #42: pick the lists to track a minute after adding the integration.

    Adding the integration tracks no lists, so the (empty) shopping list cache is
    fresh when the options are saved. The reload must not reuse it, or no todo
    entities are created for the chosen lists.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ICA_ID: PERSONAL_ID, CONF_ICA_PIN: PIN, "scan_interval": 5},
    )
    await hass.async_block_till_done()
    entry = result["result"]
    assert CONF_SHOPPING_LISTS not in entry.options
    # Only the favorites list exists, and the empty list of lists is cached
    assert hass.states.get("todo.ica_favorite_articles") is not None
    assert hass.states.get("todo.ica_veckohandling") is None
    assert entry.runtime_data.get_shopping_list(LIST_ID) is None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 5,
            CONF_JSON_DATA_IN_DESC: False,
            "per_item_events": False,
            CONF_SHOPPING_LISTS: [LIST_ID],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.states.get("todo.ica_veckohandling") is not None
    assert entry.data[CONF_DIRTY_CACHE] is False
    await hass.config_entries.async_unload(entry.entry_id)
