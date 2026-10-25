"""Config flow for ICA integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import requests
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTH_STATE,
    CONF_DIRTY_CACHE,
    CONF_ICA_ID,
    CONF_ICA_PIN,
    CONF_JSON_DATA_IN_DESC,
    CONF_PER_ITEM_EVENTS,
    CONF_SHOPPING_LISTS,
    CONFIG_ENTRY_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    account_unique_id,
)
from .exceptions import IcaAuthError
from .icaapi_async import IcaAPIAsync
from .icatypes import AuthCredentials, AuthState

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ICA_ID): str,
        vol.Required(CONF_ICA_PIN): str,
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=1)
        ),
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_ICA_PIN): str})


async def _async_login(personal_id: str, pin: str) -> tuple[AuthState, Any]:
    """Log in to ICA. Returns the auth state and the account's shopping lists."""
    api = IcaAPIAsync(AuthCredentials(username=personal_id, password=pin), None)
    await api.ensure_login()
    shopping_lists = await api.get_shopping_lists()
    return api.get_authenticated_user(), shopping_lists


def _login_error(err: Exception) -> str:
    if isinstance(err, IcaAuthError):
        return "invalid_auth"
    if isinstance(err, requests.exceptions.RequestException):
        response = getattr(err, "response", None)
        if response is not None and response.status_code == 401:
            return "invalid_auth"
        return "cannot_connect"
    return "unknown"


class IcaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ICA."""

    VERSION = 1
    MINOR_VERSION = 3

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            personal_id = user_input[CONF_ICA_ID].strip()
            await self.async_set_unique_id(account_unique_id(personal_id))
            self._abort_if_unique_id_configured()

            try:
                auth_state, _ = await _async_login(
                    personal_id, user_input[CONF_ICA_PIN]
                )
            except Exception as err:
                errors["base"] = _login_error(err)
                if errors["base"] == "unknown":
                    _LOGGER.exception("Unexpected exception during ICA login")
            else:
                user = auth_state.get("user")
                return self.async_create_entry(
                    title=CONFIG_ENTRY_NAME
                    % (user["person_name"] if user else "account"),
                    data={
                        CONF_ICA_ID: personal_id,
                        CONF_ICA_PIN: user_input[CONF_ICA_PIN],
                        CONF_AUTH_STATE: auth_state,
                    },
                    options={CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauth flow when the stored credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new PIN."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                auth_state, _ = await _async_login(
                    entry.data[CONF_ICA_ID], user_input[CONF_ICA_PIN]
                )
            except Exception as err:
                errors["base"] = _login_error(err)
                if errors["base"] == "unknown":
                    _LOGGER.exception("Unexpected exception during ICA login")
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_ICA_PIN: user_input[CONF_ICA_PIN],
                        CONF_AUTH_STATE: auth_state,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"account": entry.title},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return IcaOptionsFlowHandler()


class IcaOptionsFlowHandler(OptionsFlow):
    """Handle an options flow for ICA."""

    def __init__(self) -> None:
        """Initialize Ica options flow"""
        self._shopping_lists: list[dict] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        options = dict(self.config_entry.options)

        if user_input is not None:
            tracked_before = list(options.get(CONF_SHOPPING_LISTS) or [])
            options.update(user_input)
            options.setdefault(CONF_SHOPPING_LISTS, [])
            if tracked_before != options[CONF_SHOPPING_LISTS]:
                # Other lists are tracked, so refetch them after the reload
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_DIRTY_CACHE: True},
                )
            # Saving the options reloads the integration (see `_async_options_updated`)
            return self.async_create_entry(data=options)

        errors: dict[str, str] = {}
        if self._shopping_lists is None:
            try:
                self._shopping_lists = await self._async_get_shopping_lists()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Could not fetch the ICA shopping lists: %s", err)
                errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=1)),
                vol.Required(
                    CONF_JSON_DATA_IN_DESC,
                    default=options.get(CONF_JSON_DATA_IN_DESC, False),
                ): bool,
                vol.Required(
                    CONF_PER_ITEM_EVENTS,
                    default=options.get(CONF_PER_ITEM_EVENTS, False),
                ): bool,
                # Without the lists from ICA, the tracked lists are left unchanged
                **(
                    self._shopping_list_selector_schema(self._shopping_lists)
                    if self._shopping_lists
                    else {}
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def _async_get_shopping_lists(self) -> list[dict]:
        # Re-uses the API client of the loaded entry, which is already logged in.
        # Fetches all lists of the account, not only the tracked ones.
        coordinator = self.config_entry.runtime_data
        data = await coordinator.api.get_shopping_lists()
        lists = (data or {}).get("shoppingLists") or []
        return [x for x in lists if x.get("offlineId") and x.get("title")]

    def _shopping_list_selector_schema(self, lists: list[dict]) -> dict:
        # Match tracked ids to the available lists case-insensitively (ICA returns
        # upper case ids) and drop ids of lists that no longer exist
        available = {str(x["offlineId"]).lower(): x["offlineId"] for x in lists}
        tracked = [
            available[str(x).lower()]
            for x in self.config_entry.options.get(CONF_SHOPPING_LISTS) or []
            if str(x).lower() in available
        ]
        return {
            vol.Optional(CONF_SHOPPING_LISTS, default=tracked): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            label=shopping_list["title"],
                            value=shopping_list["offlineId"],
                        )
                        for shopping_list in lists
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            ),
        }
