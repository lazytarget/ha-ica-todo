"""Fixtures for the ICA integration tests."""

from __future__ import annotations

import copy
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ica.const import (
    CONF_AUTH_STATE,
    CONF_ICA_ID,
    CONF_ICA_PIN,
    CONF_SHOPPING_LISTS,
    DOMAIN,
    account_unique_id,
)

PERSONAL_ID = "199001011234"
PIN = "1234"
LIST_ID = "LIST-1"

AUTH_STATE = {
    "client": {"client_id": "cid", "client_secret": "secret", "scope": "s"},
    "token": {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_in": 2592000,
        "expiry": "2099-01-01 00:00:00+00:00",
    },
    "user": {
        "given_name": "Test",
        "family_name": "Person",
        "person_name": "Test Person",
    },
}

SHOPPING_LIST = {
    "id": 1,
    "offlineId": LIST_ID,
    "title": "Veckohandling",
    "commentText": "Fredag",
    "rows": [
        {
            "id": 11,
            "offlineId": "row-gurka",
            "productName": "Gurka",
            "quantity": 1,
            "unit": "st",
            "isStrikedOver": False,
            "latestChange": "2024-01-01T10:00:00Z",
        },
        {
            "id": 12,
            "offlineId": "row-banan",
            "productName": "Banan",
            "isStrikedOver": False,
            "offerId": "offer-1",
            "latestChange": "2024-01-01T09:00:00Z",
        },
        {
            "id": 13,
            "offlineId": "row-mjolk",
            "productName": "Mjölk",
            "isStrikedOver": True,
            "latestChange": "2024-01-01T08:00:00Z",
        },
    ],
}

OFFER = {
    "id": "offer-1",
    "name": "Banan",
    "validTo": "2099-06-30T23:59:59",
    "eans": [{"id": "4011800420710", "articleDescription": "Banan"}],
    "category": {"articleGroupId": 5, "expandedArticleGroupId": 50},
}


class FakeIcaApi:
    """In-memory stand-in for `IcaAPIAsync`."""

    def __init__(self, credentials=None, auth_state=None) -> None:
        self.credentials = credentials
        self.auth_state = copy.deepcopy(AUTH_STATE)
        self.lists = {LIST_ID: copy.deepcopy(SHOPPING_LIST)}
        self.baseitems = [
            {"id": "base-1", "text": "Kaffe", "sortOrder": 0, "articleEan": "1"},
            {"id": "base-2", "text": "Mjölk", "sortOrder": 1, "articleEan": "2"},
        ]
        self.offers = [copy.deepcopy(OFFER)]
        self.syncs: list[dict] = []
        self.baseitem_syncs: list[list] = []
        self.login_error: Exception | None = None

    async def ensure_login(self, refresh=None):
        if self.login_error:
            raise self.login_error
        return self.auth_state

    def get_authenticated_user(self):
        return self.auth_state

    async def get_shopping_lists(self):
        return {"shoppingLists": list(self.lists.values())}

    async def get_shopping_list(self, list_id):
        return copy.deepcopy(self.lists[list_id])

    async def get_baseitems(self):
        return copy.deepcopy(self.baseitems)

    async def sync_baseitems(self, items):
        self.baseitem_syncs.append(copy.deepcopy(items))
        self.baseitems = copy.deepcopy(items)
        return copy.deepcopy(items)

    async def get_articles(self):
        return [{"name": "Gurka", "parentId": 3}]

    async def get_current_bonus(self):
        return {}

    async def get_favorite_stores(self):
        return [{"id": 1}]

    async def get_offers(self, store_ids):
        return {"1": {"offers": [{"id": o["id"]} for o in self.offers]}}

    async def search_offers(self, store_ids, offer_ids):
        return [copy.deepcopy(o) for o in self.offers if o["id"] in offer_ids]

    async def sync_shopping_list(self, data):
        self.syncs.append(copy.deepcopy(data))
        shopping_list = self.lists[data["offlineId"]]
        rows = shopping_list["rows"]
        for row in data.get("createdRows") or []:
            rows.append(copy.deepcopy(row))
        for row in data.get("changedRows") or []:
            for existing in rows:
                if existing["offlineId"] == row["offlineId"]:
                    existing.update(row)
        deleted = set(data.get("deletedRows") or [])
        shopping_list["rows"] = [r for r in rows if r["offlineId"] not in deleted]
        return copy.deepcopy(shopping_list)

    async def lookup_barcode(self, identifier):
        return None

    async def get_recipe(self, recipe_id):
        return {"id": recipe_id}

    async def create_shopping_list(
        self, offline_id, title, comment, store_sorting=True
    ):
        self.lists[offline_id.upper()] = {
            "id": 2,
            "offlineId": offline_id.upper(),
            "title": title,
            "commentText": comment,
            "rows": [],
        }
        return copy.deepcopy(self.lists[offline_id.upper()])

    async def delete_shopping_list(self, offline_id):
        self.lists.pop(offline_id, None)
        return True


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in all tests."""
    return


@pytest.fixture(autouse=True)
def isolated_config_dir(hass, tmp_path):
    """Write cache files to a temporary directory."""
    hass.config.config_dir = str(tmp_path)


@pytest.fixture
def fake_api() -> FakeIcaApi:
    return FakeIcaApi()


@pytest.fixture
def mock_api(fake_api):
    """Use the fake API wherever the integration creates an API client."""

    def factory(*args, **kwargs):
        fake_api.credentials = args[0] if args else None
        return fake_api

    with (
        patch("custom_components.ica.IcaAPIAsync", side_effect=factory),
        patch("custom_components.ica.config_flow.IcaAPIAsync", side_effect=factory),
    ):
        yield fake_api


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
        options={CONF_SHOPPING_LISTS: [LIST_ID], "scan_interval": 5},
    )


@pytest.fixture
async def loaded_entry(hass, config_entry, mock_api):
    """A set up ICA config entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    if hass.config_entries.async_get_entry(config_entry.entry_id):
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
