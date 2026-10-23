"""The ICA integration."""

from __future__ import annotations

import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .caching import cache_file_path
from .const import (
    CONF_AUTH_STATE,
    CONF_ICA_ID,
    CONF_ICA_PIN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENTRY_CACHE_NAMES,
    LEGACY_DEBUG_CACHE_KEYS,
    OPTION_KEYS,
    SHARED_CACHE_KEYS,
    account_unique_id,
    entry_cache_key,
)
from .coordinator import IcaCoordinator
from .icaapi_async import IcaAPIAsync
from .icatypes import AuthCredentials, AuthState
from .services import setup_global_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type IcaConfigEntry = ConfigEntry[IcaCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    setup_global_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IcaConfigEntry) -> bool:
    """Set up ICA from a config entry."""
    _LOGGER.debug(
        "Setting up ICA config entry %s (v%s.%s)",
        entry.entry_id,
        entry.version,
        entry.minor_version,
    )

    update_interval = datetime.timedelta(
        minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    credentials = AuthCredentials(
        username=entry.data[CONF_ICA_ID], password=entry.data[CONF_ICA_PIN]
    )
    auth_state: AuthState = entry.data.get(CONF_AUTH_STATE, {})
    api = IcaAPIAsync(credentials, auth_state)

    coordinator = IcaCoordinator(hass, entry, update_interval, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: IcaConfigEntry) -> None:
    """Reload when the options changed, unless they are applied already."""
    if dict(entry.options) != entry.runtime_data.applied_options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version > 1:
        # This means the user has downgraded from a future version
        return False

    if config_entry.minor_version < 2:
        new_data = {**config_entry.data}
        new_data.pop("access_token", None)
        new_data.pop("user", None)
        if isinstance(auth_state := new_data.get(CONF_AUTH_STATE), dict):
            new_data[CONF_AUTH_STATE] = {
                k: v for k, v in auth_state.items() if k != "userInfo"
            }
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, minor_version=2, version=1
        )

    if config_entry.minor_version < 3:
        # - Settings move from `data` to `options`
        # - The unique id and cache files no longer contain the personal ID number
        new_data = {**config_entry.data}
        new_options = {**config_entry.options}
        for key in OPTION_KEYS:
            if key in new_data:
                new_options.setdefault(key, new_data.pop(key))
        personal_id = str(new_data[CONF_ICA_ID])
        await hass.async_add_executor_job(
            _migrate_cache_files, hass, personal_id, entry_cache_key(config_entry)
        )
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options=new_options,
            unique_id=account_unique_id(personal_id),
            minor_version=3,
            version=1,
        )

    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        config_entry.version,
        config_entry.minor_version,
    )
    return True


def _migrate_cache_files(hass: HomeAssistant, old_key: str, new_key: str) -> None:
    for name in ENTRY_CACHE_NAMES:
        old_path = cache_file_path(hass, f"{old_key}.{name}")
        if old_path.exists():
            old_path.replace(cache_file_path(hass, f"{new_key}.{name}"))
    for key in LEGACY_DEBUG_CACHE_KEYS:
        cache_file_path(hass, key).unlink(missing_ok=True)


async def async_unload_entry(hass: HomeAssistant, entry: IcaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the cached data of a removed account."""
    remaining = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    await hass.async_add_executor_job(
        _remove_cache_files, hass, entry_cache_key(entry), not remaining
    )


def _remove_cache_files(hass: HomeAssistant, key: str, remove_shared: bool) -> None:
    keys = [f"{key}.{name}" for name in ENTRY_CACHE_NAMES]
    if remove_shared:
        keys += [*SHARED_CACHE_KEYS, *LEGACY_DEBUG_CACHE_KEYS]
    for cache_key in keys:
        cache_file_path(hass, cache_key).unlink(missing_ok=True)
