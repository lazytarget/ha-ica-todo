import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .coordinator import IcaCoordinator
from .const import DOMAIN, IcaServices
from .icatypes import (
    IcaBaseItem,
    IcaOfferInfo,
    IcaRecipe,
    IcaShoppingList,
    ServiceCallResponse,
)

import logging

_LOGGER = logging.getLogger(__name__)

GET_BASEITEMS_SCHEMA = vol.Schema(
    {
        # vol.Required("integration"): cv.string
        vol.Required("integration"): vol.All(cv.ensure_list, [cv.string]),
    }
)

ADD_BASEITEM_SCHEMA = vol.Schema(
    {
        # vol.Required("integration"): cv.string
        vol.Required("integration"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("identifier"): cv.string,
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

GET_OFFERS_SCHEMA = vol.Schema(
    {
        vol.Optional("integration"): cv.string,
        vol.Optional("store_ids", default=[]): vol.All(
            cv.ensure_list, [vol.Coerce(int)]
        ),
        vol.Optional("favorites_only", default=False): cv.boolean,
    }
)

REFRESH_SHOPPING_LISTS_SCHEMA = vol.Schema(
    {
        vol.Optional("integration"): cv.string,
    }
)


def _get_loaded_coordinator(
    hass: HomeAssistant, entry_id: str | None = None
) -> IcaCoordinator:
    """Return the coordinator of the given config entry, or of the first one."""
    if entry_id:
        config_entry = hass.config_entries.async_get_entry(entry_id)
    else:
        config_entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    if not config_entry or config_entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="integration_not_found",
            translation_placeholders={"target": DOMAIN},
        )
    if config_entry.state != ConfigEntryState.LOADED:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="not_loaded",
            translation_placeholders={"target": config_entry.title},
        )
    return config_entry.coordinator or hass.data[DOMAIN][config_entry.entry_id]


def setup_global_services(hass: HomeAssistant) -> None:
    if not hass.services.has_service(DOMAIN, IcaServices.REFRESH_ALL):

        async def handle_refresh_all(call: ServiceCall):
            """Call will force the coordinator to refresh all data"""
            c = 0
            for config_entry in hass.config_entries.async_entries(DOMAIN):
                if config_entry.state != ConfigEntryState.LOADED:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="not_loaded",
                        translation_placeholders={"target": config_entry.title},
                    )
                coordinator: IcaCoordinator = (
                    config_entry.coordinator or hass.data[DOMAIN][config_entry.entry_id]
                )
                await coordinator.refresh_data(invalidate_cache=True)
                coordinator.async_update_listeners()
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
            config_entry: ConfigEntry | None
            for entry_id in call.data["integration"]:
                if not (config_entry := hass.config_entries.async_get_entry(entry_id)):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="integration_not_found",
                        translation_placeholders={"target": DOMAIN},
                    )
                if config_entry.state != ConfigEntryState.LOADED:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="not_loaded",
                        translation_placeholders={"target": config_entry.title},
                    )
                coordinator: IcaCoordinator = (
                    config_entry.coordinator or hass.data[DOMAIN][entry_id]
                )
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
            config_entry: ConfigEntry | None
            for entry_id in call.data["integration"]:
                if not (config_entry := hass.config_entries.async_get_entry(entry_id)):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="integration_not_found",
                        translation_placeholders={"target": DOMAIN},
                    )
                if config_entry.state != ConfigEntryState.LOADED:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="not_loaded",
                        translation_placeholders={"target": config_entry.title},
                    )
                coordinator: IcaCoordinator = (
                    config_entry.coordinator or hass.data[DOMAIN][entry_id]
                )
                baseitems = await coordinator.async_lookup_and_add_baseitem(identifier)
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

    # Non-entity based Services
    if not hass.services.has_service(DOMAIN, IcaServices.GET_RECIPE):
        async def handle_get_recipe(
            call: ServiceCall,
        ) -> ServiceCallResponse[IcaRecipe]:
            """Call will query ICA api after a specific Recipe"""
            config_entry: ConfigEntry = hass.config_entries.async_entries(DOMAIN)[0]
            coordinator: IcaCoordinator = (
                config_entry.coordinator or hass.data[DOMAIN][config_entry.entry_id]
            )

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

    # Non-entity based Services
    if not hass.services.has_service(DOMAIN, IcaServices.LOOKUP_PRODUCT):
        async def handle_lookup_product(
            call: ServiceCall,
        ) -> ServiceCallResponse[IcaRecipe]:
            """Call will query local Product registry and fill in with info from OpenFoodFacts."""
            config_entry: ConfigEntry = hass.config_entries.async_entries(DOMAIN)[0]
            coordinator: IcaCoordinator = (
                config_entry.coordinator or hass.data[DOMAIN][config_entry.entry_id]
            )
            identifier = call.data["identifier"]
            product_info = await coordinator.get_product_info(identifier)
            return ServiceCallResponse[IcaRecipe](success=bool(product_info), data=product_info)

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

    if not hass.services.has_service(DOMAIN, IcaServices.GET_OFFERS):

        async def handle_get_offers(
            call: ServiceCall,
        ) -> ServiceCallResponse[list[IcaOfferInfo]]:
            """Return the currently valid offers, optionally filtered."""
            coordinator = _get_loaded_coordinator(hass, call.data.get("integration"))
            offers = await coordinator.async_get_offers(
                store_ids=call.data["store_ids"],
                favorites_only=call.data["favorites_only"],
            )
            return ServiceCallResponse[list[IcaOfferInfo]](success=True, data=offers)

        hass.services.async_register(
            DOMAIN,
            IcaServices.GET_OFFERS,
            handle_get_offers,
            schema=GET_OFFERS_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, IcaServices.REFRESH_SHOPPING_LISTS):

        async def handle_refresh_shopping_lists(
            call: ServiceCall,
        ) -> ServiceCallResponse[list[IcaShoppingList]]:
            """Fetch the tracked shopping lists from ICA right away."""
            if entry_id := call.data.get("integration"):
                coordinators = [_get_loaded_coordinator(hass, entry_id)]
            else:
                coordinators = [
                    _get_loaded_coordinator(hass, config_entry.entry_id)
                    for config_entry in hass.config_entries.async_entries(DOMAIN)
                ]
            shopping_lists: list[IcaShoppingList] = []
            for coordinator in coordinators:
                shopping_lists.extend(await coordinator.async_refresh_shopping_lists())
            return ServiceCallResponse[list[IcaShoppingList]](
                success=True, data=shopping_lists
            )

        hass.services.async_register(
            DOMAIN,
            IcaServices.REFRESH_SHOPPING_LISTS,
            handle_refresh_shopping_lists,
            schema=REFRESH_SHOPPING_LISTS_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
