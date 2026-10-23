import logging
import uuid

import homeassistant.helpers.config_validation as cv
import requests
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .const import CONF_DIRTY_CACHE, CONF_SHOPPING_LISTS, DOMAIN, IcaEvents, IcaServices
from .coordinator import IcaCoordinator
from .icatypes import IcaBaseItem, IcaProduct, IcaRecipe, ServiceCallResponse
from .utils import build_lists_changed_event, resolve_list_entity_ids

_LOGGER = logging.getLogger(__name__)

GET_BASEITEMS_SCHEMA = vol.Schema(
    {
        vol.Required("integration"): vol.All(cv.ensure_list, [cv.string]),
    }
)

ADD_BASEITEM_SCHEMA = vol.Schema(
    {
        vol.Required("integration"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("identifier"): cv.string,
    }
)

CREATE_SHOPPING_LIST_SCHEMA = vol.Schema(
    {
        vol.Required("integration"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("title"): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional("comment", default=""): cv.string,
        vol.Optional("track", default=True): cv.boolean,
    }
)

DELETE_SHOPPING_LIST_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    }
)

LOOKUP_PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Required("identifier"): cv.string,
    }
)

SEARCH_ARTICLES_SCHEMA = vol.Schema(
    {
        vol.Required("query"): cv.string,
    }
)


def _get_coordinator(hass: HomeAssistant, entry_id: str) -> IcaCoordinator:
    """The coordinator of a loaded ICA config entry."""
    config_entry = hass.config_entries.async_get_entry(entry_id)
    if not config_entry or config_entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="integration_not_found",
            translation_placeholders={"target": entry_id},
        )
    if config_entry.state != ConfigEntryState.LOADED:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="not_loaded",
            translation_placeholders={"target": config_entry.title},
        )
    return config_entry.runtime_data


def _get_any_coordinator(hass: HomeAssistant) -> IcaCoordinator:
    """The coordinator of the first loaded ICA config entry."""
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.state is ConfigEntryState.LOADED:
            return config_entry.runtime_data
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="not_loaded",
        translation_placeholders={"target": DOMAIN},
    )


def _update_tracked_lists(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add: str | None = None,
    remove: str | None = None,
) -> None:
    """Track or untrack a list. The caller reloads the entry afterwards."""
    tracked = list(config_entry.options.get(CONF_SHOPPING_LISTS) or [])
    # ICA returns offlineId in upper case - compare case-insensitively
    if remove:
        tracked = [x for x in tracked if str(x).lower() != str(remove).lower()]
    if add and add.lower() not in [str(x).lower() for x in tracked]:
        tracked.append(add)
    options = {**config_entry.options, CONF_SHOPPING_LISTS: tracked}
    # The caller reloads, so the options update itself must not trigger a reload
    config_entry.runtime_data.applied_options = options
    hass.config_entries.async_update_entry(
        config_entry,
        data={**config_entry.data, CONF_DIRTY_CACHE: True},
        options=options,
    )


def _fire_lists_changed(
    hass: HomeAssistant,
    config_entry_id: str,
    created: list[str],
    deleted: list[str],
) -> None:
    """Fire `ica_lists_changed` with the entity ids currently registered for the lists."""
    registry = er.async_get(hass)
    entries = [
        (e.unique_id, e.entity_id)
        for e in er.async_entries_for_config_entry(registry, config_entry_id)
    ]
    entities = resolve_list_entity_ids(entries, config_entry_id, created)
    hass.bus.async_fire(
        IcaEvents.LISTS_CHANGED,
        build_lists_changed_event(config_entry_id, created, deleted, entities),
    )


async def _reload_and_fire_lists_changed(
    hass: HomeAssistant,
    config_entry_id: str,
    created: list[str],
    deleted: list[str],
) -> None:
    """Reload the config entry, then signal that the todo entities are registered."""
    try:
        await hass.config_entries.async_reload(config_entry_id)
    except Exception:
        _LOGGER.exception("Reload of ICA config entry failed")
    # Fire regardless, so listeners are not left waiting. `entities` shows what exists.
    _fire_lists_changed(hass, config_entry_id, created, deleted)


def setup_global_services(hass: HomeAssistant) -> None:
    if not hass.services.has_service(DOMAIN, IcaServices.REFRESH_ALL):

        async def handle_refresh_all(call: ServiceCall):
            """Call will force the coordinator to refresh all data"""
            c = 0
            for config_entry in hass.config_entries.async_entries(DOMAIN):
                coordinator = _get_coordinator(hass, config_entry.entry_id)
                await coordinator.async_refresh_all()
                c += 1
            return {"updated_integrations": c}

        hass.services.async_register(
            DOMAIN,
            IcaServices.REFRESH_ALL,
            handle_refresh_all,
            schema=vol.Schema({}),
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, IcaServices.GET_BASEITEMS):

        async def handle_get_baseitems(
            call: ServiceCall,
        ) -> ServiceCallResponse[list[IcaBaseItem]]:
            """Call will query ICA api after the user's favorite items"""
            for entry_id in call.data["integration"]:
                coordinator = _get_coordinator(hass, entry_id)
                baseitems = await coordinator.async_get_baseitems(invalidate_cache=True)
                return ServiceCallResponse[list[IcaBaseItem]](
                    success=bool(baseitems), data=baseitems or []
                )
            return None

        hass.services.async_register(
            DOMAIN,
            IcaServices.GET_BASEITEMS,
            handle_get_baseitems,
            schema=GET_BASEITEMS_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, IcaServices.ADD_BASEITEM):

        async def handle_add_baseitem(
            call: ServiceCall,
        ) -> ServiceCallResponse[list[IcaBaseItem]]:
            """Call will add item to the user's favorite items"""
            identifier = call.data["identifier"]
            for entry_id in call.data["integration"]:
                coordinator = _get_coordinator(hass, entry_id)
                try:
                    baseitems = await coordinator.async_lookup_and_add_baseitem(
                        identifier
                    )
                except ValueError as err:
                    raise ServiceValidationError(str(err)) from err
                return ServiceCallResponse[list[IcaBaseItem]](
                    success=bool(baseitems), data=baseitems or []
                )
            return ServiceCallResponse[list[IcaBaseItem]](success=False)

        hass.services.async_register(
            DOMAIN,
            IcaServices.ADD_BASEITEM,
            handle_add_baseitem,
            schema=ADD_BASEITEM_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, IcaServices.CREATE_SHOPPING_LIST):

        async def handle_create_shopping_list(call: ServiceCall):
            """Create a new shopping list in the ICA account, and optionally track it."""
            title: str = call.data["title"].strip()
            comment: str = call.data.get("comment", "")
            track: bool = call.data.get("track", True)
            if not title:
                raise ServiceValidationError("A title is required")

            coordinator = _get_coordinator(hass, call.data["integration"][0])
            config_entry = coordinator.config_entry

            offline_id = str(uuid.uuid4())
            try:
                created = await coordinator.api.create_shopping_list(
                    offline_id, title, comment
                )
            except requests.exceptions.RequestException as err:
                _LOGGER.exception("Failed to create ICA shopping list '%s'", title)
                raise HomeAssistantError(
                    f"Failed to create ICA shopping list '{title}': {err}"
                ) from err
            _LOGGER.info("Created ICA shopping list '%s' (%s)", title, offline_id)

            if track:
                # ICA returns offlineId in upper case - track it the same way as the entity unique_id
                tracked_id = offline_id
                if isinstance(created, dict) and created.get("offlineId"):
                    tracked_id = str(created["offlineId"])
                _update_tracked_lists(hass, config_entry, add=tracked_id)
                # Refresh the cached lists before reloading, since the to-do
                # entities are created from that cache during setup.
                try:
                    await coordinator.async_get_shopping_lists(invalidate_cache=True)
                except (requests.exceptions.RequestException, HomeAssistantError):
                    _LOGGER.warning(
                        "Could not refresh shopping list cache before reload",
                        exc_info=True,
                    )
                hass.async_create_background_task(
                    _reload_and_fire_lists_changed(
                        hass, config_entry.entry_id, [offline_id], []
                    ),
                    f"ica_lists_changed_{offline_id}",
                )
            else:
                _fire_lists_changed(hass, config_entry.entry_id, [offline_id], [])

            return {
                "success": True,
                "offline_id": offline_id,
                "title": title,
                "tracked": track,
                "data": created,
            }

        hass.services.async_register(
            DOMAIN,
            IcaServices.CREATE_SHOPPING_LIST,
            handle_create_shopping_list,
            schema=CREATE_SHOPPING_LIST_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, IcaServices.DELETE_SHOPPING_LIST):

        async def handle_delete_shopping_list(call: ServiceCall):
            """Delete a tracked shopping list from the ICA account and stop tracking it."""
            entity_id: str = call.data["entity_id"]
            registry = er.async_get(hass)
            entity = registry.async_get(entity_id)
            if not entity or entity.platform != DOMAIN or not entity.config_entry_id:
                raise ServiceValidationError(
                    f"'{entity_id}' is not an ICA shopping list"
                )
            prefix = f"{entity.config_entry_id}-"
            if not entity.unique_id.startswith(prefix) or entity.unique_id.endswith(
                "-baseitems"
            ):
                raise ServiceValidationError(
                    f"'{entity_id}' is not an ICA shopping list that can be deleted"
                )
            offline_id = entity.unique_id[len(prefix) :]

            coordinator = _get_coordinator(hass, entity.config_entry_id)
            config_entry = coordinator.config_entry

            try:
                await coordinator.api.delete_shopping_list(offline_id)
            except requests.exceptions.RequestException as err:
                _LOGGER.exception("Failed to delete ICA shopping list %s", offline_id)
                raise HomeAssistantError(
                    f"Failed to delete ICA shopping list '{entity_id}': {err}"
                ) from err
            _LOGGER.info("Deleted ICA shopping list %s (%s)", entity_id, offline_id)

            # Stop tracking the list, refresh cache, drop the entity and reload
            _update_tracked_lists(hass, config_entry, remove=offline_id)
            try:
                await coordinator.async_get_shopping_lists(invalidate_cache=True)
            except (requests.exceptions.RequestException, HomeAssistantError):
                _LOGGER.warning(
                    "Could not refresh shopping list cache before reload",
                    exc_info=True,
                )
            registry.async_remove(entity_id)
            hass.async_create_background_task(
                _reload_and_fire_lists_changed(
                    hass, config_entry.entry_id, [], [offline_id]
                ),
                f"ica_lists_changed_{offline_id}",
            )

            return {"success": True, "entity_id": entity_id, "offline_id": offline_id}

        hass.services.async_register(
            DOMAIN,
            IcaServices.DELETE_SHOPPING_LIST,
            handle_delete_shopping_list,
            schema=DELETE_SHOPPING_LIST_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    # Non-entity based Services
    if not hass.services.has_service(DOMAIN, IcaServices.GET_RECIPE):

        async def handle_get_recipe(
            call: ServiceCall,
        ) -> ServiceCallResponse[IcaRecipe]:
            """Call will query ICA api after a specific Recipe"""
            coordinator = _get_any_coordinator(hass)
            recipe_id = call.data["recipe_id"]
            recipe = await coordinator.async_get_recipe(recipe_id)
            return ServiceCallResponse[IcaRecipe](success=bool(recipe), data=recipe)

        hass.services.async_register(
            DOMAIN,
            IcaServices.GET_RECIPE,
            handle_get_recipe,
            schema=vol.Schema({vol.Required("recipe_id"): cv.string}),
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, IcaServices.LOOKUP_PRODUCT):

        async def handle_lookup_product(
            call: ServiceCall,
        ) -> ServiceCallResponse[IcaProduct]:
            """Call will query local Product registry and fill in with info from OpenFoodFacts."""
            coordinator = _get_any_coordinator(hass)
            try:
                product_info = await coordinator.get_product_info(
                    call.data["identifier"]
                )
            except NotImplementedError as err:
                raise ServiceValidationError(str(err)) from err
            return ServiceCallResponse[IcaProduct](
                success=bool(product_info), data=product_info
            )

        hass.services.async_register(
            DOMAIN,
            IcaServices.LOOKUP_PRODUCT,
            handle_lookup_product,
            schema=LOOKUP_PRODUCT_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, IcaServices.SEARCH_ARTICLES):

        async def handle_search_articles(call: ServiceCall):
            """Search ICA's article database by free-text query."""
            config_entry: ConfigEntry = hass.config_entries.async_entries(DOMAIN)[0]
            coordinator: IcaCoordinator = (
                config_entry.coordinator or hass.data[DOMAIN][config_entry.entry_id]
            )
            query = call.data["query"]
            await coordinator.api.ensure_login()
            results = await coordinator.api.search_articles(query)
            return ServiceCallResponse(success=bool(results), data=results)

        hass.services.async_register(
            DOMAIN,
            IcaServices.SEARCH_ARTICLES,
            handle_search_articles,
            schema=SEARCH_ARTICLES_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
