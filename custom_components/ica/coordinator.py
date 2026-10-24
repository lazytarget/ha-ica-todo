"""DataUpdateCoordinator for the Todoist component."""

import logging
import traceback
import re
from typing import Optional
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial

import requests
import homeassistant.util.dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .background_worker import BackgroundWorker
from .caching import CacheEntry
from .const import (
    CACHING_SECONDS_SHORT_TERM,
    CONF_DIRTY_CACHE,
    CONF_ICA_ID,
    CONF_SHOPPING_LISTS,
    DEFAULT_ARTICLE_GROUP_ID,
    DOMAIN,
    SHOPPING_LIST_ITEM_EVENTS,
    ConflictMode,
    IcaEventOrigin,
    IcaEvents,
    OpenFoodFacts,
)
from .icaapi_async import IcaAPIAsync
from .icatypes import (
    ArticleInfo,
    AuthState,
    IcaAccountCurrentBonus,
    IcaArticle,
    IcaBaseItem,
    IcaOfferDetails,
    IcaOfferInfo,
    IcaOfferMechanics,
    IcaProduct,
    IcaProductCategory,
    IcaProductOffer,
    IcaRecipe,
    IcaShoppingList,
    IcaShoppingListEntry,
    IcaShoppingListSync,
    IcaStore,
    IcaStoreOffer,
    OpenFoodFactsProduct,
)
from .utils import (
    get_diff_obj,
    get_diffs,
    get_shopping_list_item_changes,
    index_of,
    is_offer_valid,
    match_offers_to_baseitems,
    trim_props,
    try_parse_int,
)

_LOGGER = logging.getLogger(__name__)


class IcaCoordinator(DataUpdateCoordinator[list[IcaShoppingListEntry]]):
    """Coordinator for updating task data from ICA."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        logger: logging.Logger,
        update_interval: timedelta,
        api: IcaAPIAsync,
        nRecipes: int = 0,
    ) -> None:
        """Initialize the ICA coordinator."""
        super().__init__(hass, logger, name="ICA", update_interval=update_interval)
        self.SCAN_INTERVAL = update_interval
        self._config_entry = config_entry
        self.api: IcaAPIAsync = api
        self._auth_initialized: bool | None = None
        self._hass = hass
        self._nRecipes: int = nRecipes
        self._stores: list[IcaStore] | None = None
        self._productCategories: list[IcaProductCategory] | None = None
        self._icaBaseItems: list | None = None
        self._icaRecipes: list[IcaRecipe] | None = None

        self._worker = BackgroundWorker(hass, config_entry)
        config_entry.async_on_unload(self._worker.shutdown)

        self._openFoodFactsSession = async_get_clientsession(self._hass)
        # config_entry.async_on_unload(self._openFoodFactsSession.close)

        config_entry_key = self._config_entry.data[CONF_ICA_ID]
        # Expire just before the next scheduled update, so that every update fetches
        # fresh data. Otherwise an update can land right before expiry and skip it.
        short_term_expiry = min(
            CACHING_SECONDS_SHORT_TERM, max(update_interval.total_seconds() - 30, 0)
        )

        self._ica_articles = CacheEntry[list[IcaArticle]](
            hass, "articles", partial(self.api.get_articles)
        )
        self._ica_baseitems = CacheEntry[list[IcaBaseItem]](
            hass,
            f"{config_entry_key}.baseitems",
            partial(self.api.get_baseitems),
            expiry_seconds=short_term_expiry,
        )
        self._ica_current_bonus = CacheEntry[IcaAccountCurrentBonus](
            hass, f"{config_entry_key}.current_bonus", partial(self._get_current_bonus)
        )
        self._ica_favorite_stores = CacheEntry[list[IcaStore]](
            hass,
            f"{config_entry_key}.favorite_stores",
            partial(self.api.get_favorite_stores),
        )
        self._ica_shopping_lists = CacheEntry[list[IcaShoppingList]](
            hass,
            f"{config_entry_key}.shopping_lists",
            partial(self._async_update_tracked_shopping_lists),
            expiry_seconds=short_term_expiry,
        )
        self._ica_offers = CacheEntry[dict[str, IcaOfferDetails]](
            hass,
            f"{config_entry_key}.offers",
            partial(self._update_offer_details),
            # FOR-DEBUGGING: expiry_seconds=CACHING_SECONDS_SHORT_TERM,
        )
        self._ica_products = CacheEntry[dict[str, IcaProduct]](
            hass,
            "products",
            partial(self._update_products),
        )

    async def init_cache(self) -> None:
        """Initializes the cache from local files."""
        try:
            await self._ica_articles.init_value()
            await self._ica_baseitems.init_value()
            await self._ica_current_bonus.init_value()
            await self._ica_favorite_stores.init_value()
            await self._ica_shopping_lists.init_value()
            await self._ica_offers.init_value()
            await self._ica_products.init_value()
        except Exception as e:
            _LOGGER.error("Cache initialization failed: %s", e)
            raise

    async def _get_tracked_shopping_lists(self) -> list[IcaShoppingList]:
        if not (list_ids := self._config_entry.data.get(CONF_SHOPPING_LISTS, [])):
            return None
        lists: list[IcaShoppingList] = []
        for offline_id in list_ids:
            if not offline_id:
                continue
            shopping_list = await self.api.get_shopping_list(offline_id)
            if shopping_list:
                lists.append(shopping_list)
        return lists

    def get_shopping_list(self, list_offline_id) -> IcaShoppingList | None:
        selected_lists = self._ica_shopping_lists.current_value() or []
        for x in filter(lambda x: x["offlineId"] == list_offline_id, selected_lists):
            return x
        return None

    async def async_get_shopping_list(
        self, list_id, invalidate_cache: bool = False
    ) -> IcaShoppingList:
        selected_lists = await self.async_get_shopping_lists(invalidate_cache) or []
        for x in filter(lambda x: x["offlineId"] == list_id, selected_lists):
            return x
        return None

    async def async_get_shopping_lists(
        self, invalidate_cache: bool = False
    ) -> list[IcaShoppingList]:
        selected_lists = (
            await self._ica_shopping_lists.get_value(invalidate_cache) or []
        )
        if invalidate_cache:
            # Updated Shopping list cache outside of regular `_async_update_data-loop`, inform listeners...
            self.async_update_listeners()
        return selected_lists

    async def async_refresh_shopping_lists(self) -> list[IcaShoppingList]:
        """Fetch the tracked shopping lists from ICA right away, bypassing the cache."""
        if self.should_refresh_login():
            new_auth_state = await self.api.ensure_login(refresh=True)
            self._try_persist_new_state(self._config_entry, new_auth_state, None)
        return await self.async_get_shopping_lists(invalidate_cache=True)

    def get_article_group(self, product_name) -> int:
        articles = self._ica_articles.current_value() or []
        if not articles:
            return DEFAULT_ARTICLE_GROUP_ID  # Unspecified

        product_name = product_name.casefold()
        for x in filter(
            lambda x: x.get("name", "").casefold() == product_name, articles
        ):
            return x.get("parentId") or DEFAULT_ARTICLE_GROUP_ID
        return DEFAULT_ARTICLE_GROUP_ID  # Unspecified

        # articleGroups = {
        #     "välling": 9,
        #     "kaffe": 9,
        #     "maskindiskmedel": 11,
        #     "hushållspapper": 11,
        #     "toapapper": 11,
        #     "blöjor": 11,
        # }
        # return articleGroups.get(str.lower(productName), DEFAULT_ARTICLE_GROUP_ID)

    def parse_summary(self, summary):
        r = re.search(
            # r"^(?P<min_quantity>\d-)?(?P<quantity>[0-9,.]*)? ?(?P<unit>st|förp|kg|hg|g|l|dl|cl|ml|msk|tsk|krm)? ?(?P<name>.+)$",       v2
            r"^(?P<a>((?P<min_quantity>\d-)?(?P<quantity>[0-9,.]*)? )|(?P<b>))(?P<unit>st|förp|kg|hg|g|l|dl|cl|ml|msk|tsk|krm)? ?(?P<name>.+)$",
            summary,
        )
        quantity = r["quantity"]
        unit = r["unit"]
        productName = r["name"] or summary
        articleGroupId = self.get_article_group(productName)

        ti = {"summary": summary, "productName": productName}
        if unit:
            ti["unit"] = unit
        if quantity:
            ti["quantity"] = quantity
        if unit:
            ti["unit"] = unit
        if articleGroupId:
            ti["articleGroupId"] = articleGroupId

        if ti.get("quantity"):
            if ti.get("unit"):
                ti["summary"] = f"{ti['quantity']} {ti['unit']} {productName}"
            else:
                ti["summary"] = f"{ti['quantity']} {productName}"

        _LOGGER.info("Parsed info from '%s' to %s", summary, ti)
        return ti

    def get_offer_info(self, offer_id) -> IcaOfferDetails | None:
        offers = self._ica_offers.current_value() or {}
        return offers.get(offer_id, None)

    async def _update_offer_details(
        self, store_ids: list[str] = None
    ) -> dict[str, IcaOfferDetails]:
        now = datetime.now()
        current = (
            self._ica_offers.current_value() or {}
        )  # Get current value without refreshing. Possible infinite loop
        target = current.copy()
        pre_count = len(current)

        if not store_ids:
            # No passed store_ids then use the favorite stores
            stores = await self.async_get_favorite_stores()
            store_ids = [s["id"] for s in stores]

        offers_per_store = await self.api.get_offers(store_ids)
        _LOGGER.debug("Fetched offers for stores: %s", store_ids)

        if not offers_per_store:
            _LOGGER.warning("Failed to get offers from stores!")
            return current

        product_registry = self._ica_products.current_value() or {}
        product_registry_old = product_registry.copy()
        product_count = len(product_registry)

        # Remove obsolete offers... (+30 days from expiration)
        for offer_id in list(current):
            offer = current[offer_id]
            self._copy_offer_products_to_registry(offer, product_registry)

            offer_due = (
                datetime.fromisoformat(offer["validTo"]) + timedelta(days=30)
                if offer and offer.get("validTo")
                else datetime.max
            )
            if offer_due < now:
                _LOGGER.warning("Removing obsolete offer: %s", offer)
                del target[offer_id]

        # Look up the "active" offers that was retrieved
        store_ids = list(offers_per_store.keys())
        offer_ids = []
        store_offers: dict[str, IcaStoreOffer] = {}
        for store_id in offers_per_store:
            store = offers_per_store[store_id]
            oids = [
                o["id"]
                for o in store["offers"]
                # if o and o.get("isUsed", None) is not True
            ]
            offer_ids = sorted(list(set(offer_ids)) + list(set(oids)))
            for o in store["offers"]:
                c = store_offers.get(o["id"]) or IcaStoreOffer()
                c.update(o)
                store_offers[o["id"]] = c

        if not offer_ids:
            _LOGGER.warning("No offers to lookup, then avoid querying API")
            return []

        full_offers = await self.api.search_offers(store_ids, offer_ids)
        if not full_offers:
            _LOGGER.warning("No existing offers found. Is this true??")
            return []

        new_offers: list[IcaOfferInfo] = []
        for f in full_offers:
            current_offer = target.get(f["id"]) or IcaOfferDetails()
            store_offer = store_offers.get(f["id"]) or IcaStoreOffer()

            offer = current_offer.copy()
            offer.update(store_offer)
            offer.update(f)
            target[offer["id"]] = offer
            if not current_offer:
                offer_info = IcaOfferInfo.map_from_offer_details(offer)
                new_offers.append(offer_info)
            self._copy_offer_products_to_registry(offer, product_registry)
        new_product_count = len(product_registry)
        if product_count != new_product_count:
            _LOGGER.info(
                "Persisting %s new products", new_product_count - product_count
            )
            await self._update_products(product_registry)

        diffs = get_diffs(product_registry_old, product_registry, include_values=False)
        if diffs:
            event_data = {
                "type": "products_changed",
                "uid": self._config_entry.data[CONF_ICA_ID],
                "timestamp": str(datetime.now(timezone.utc)),
                "pre_count": product_count,
                "post_count": new_product_count,
                "diffs": diffs,
            }
            await CacheEntry(
                self._hass, "products_changed--diffs", partial(lambda _: None)
            ).set_value(event_data)
            await self._worker.fire_or_queue_event(
                f"{DOMAIN}_product_event", event_data
            )

        # Prepare for publish of change event
        await CacheEntry(
            self._hass, "offers_changed--base-data", partial(lambda _: None)
        ).set_value(
            {
                "timestamp": str(datetime.now(timezone.utc)),
                "old": current,
                "new": target,
            }
        )

        diffs = get_diffs(current, target, include_values=False)
        _LOGGER.debug("OFFERS DIFFS: %s", diffs)
        if diffs:
            event_data = {
                "type": "offers_changed",
                "uid": self._config_entry.data[CONF_ICA_ID],
                "timestamp": str(datetime.now(timezone.utc)),
                "pre_count": pre_count,
                "post_count": len(target),
                "diffs": diffs,
            }
            await CacheEntry(
                self._hass, "offers_changed--diffs", partial(lambda _: None)
            ).set_value(event_data)
            await self._worker.fire_or_queue_event(f"{DOMAIN}_event", event_data)

        # Notify new offers
        if new_offers:
            event_data = {
                "type": "new_offers",
                "uid": self._config_entry.data[CONF_ICA_ID],
                "timestamp": str(datetime.now(timezone.utc)),
                "pre_count": pre_count,
                "post_count": len(target),
                "new_offers": new_offers,
            }
            # todo: notify: Auto add automation if new ean's have been added to an offer?
            # todo: ...and remove if no longer exists?
            await self._worker.fire_or_queue_event(IcaEvents.NEW_OFFERS, event_data)
            # print to file for debugging purposes
            await CacheEntry(
                self._hass, "offers_changed--new-offers", partial(lambda _: None)
            ).set_value(event_data)

            # Notify new offers on the user's favorite items
            if favorite_offers := match_offers_to_baseitems(
                new_offers, self._ica_baseitems.current_value()
            ):
                await self._worker.fire_or_queue_event(
                    IcaEvents.FAVORITE_OFFERS,
                    {
                        "config_entry_id": self._config_entry.entry_id,
                        "offer_ids": [o["id"] for o in favorite_offers],
                        "offers": favorite_offers,
                    },
                )

        _LOGGER.warning(
            "Updated offer details! pre_count: %s, post_count: %s",
            pre_count,
            len(target),
        )
        return target

    def _copy_offer_products_to_registry(
        self,
        offer: IcaOfferDetails,
        product_registry: dict[str, IcaProduct],
    ):
        for ean in offer.get("eans", []):
            ean_id = ean.get("id", None)
            if ean_id and not product_registry.get(ean_id):
                cat = offer.get("category", {})
                article = (
                    ArticleInfo(
                        name=None,  # needs to be input via ProductService lookup
                        articleId=None,  # needs to be input via ProductService lookup
                        articleGroupId=cat.get("articleGroupId"),
                        expandedArticleGroupId=cat.get("expandedArticleGroupId"),
                    )
                    if cat
                    else None
                )
                product_offer = IcaProductOffer(
                    id=offer.get("id"),
                    name=offer.get("name"),
                    brand=offer.get("brand"),
                    packageInformation=offer.get("packageInformation"),
                    priceText=IcaOfferMechanics.format_to_string(
                        offer.get("parsedMechanics", None)
                    ),
                    referencePriceText=offer.get("referencePriceText"),
                    refrenceInfo=offer.get("referenceInfo"),
                )
                product = product_registry.get(ean_id) or IcaProduct()
                product.update(
                    ean_id=ean_id,
                    ean_name=ean.get("articleDescription"),
                    article=trim_props(article),
                    offers=product.get("offers") or {},
                )
                if old_offer := product.get("offer", None):
                    _LOGGER.warning("Reformatting offers on Ean: %s", ean_id)
                    product["offers"][old_offer["id"]] = old_offer
                    del product["offer"]
                product["offers"][product_offer["id"]] = product_offer
                product_registry[ean_id] = product

    async def _update_products(
        self,
        new_products: dict[str, IcaProduct] | None = None,
    ) -> dict[str, IcaProduct]:
        product_registry = self._ica_products.current_value() or {}
        if not new_products:
            # Ran through refresh loop
            # todo: look up Products with an article.articleId and article.name ?
            # todo: as this might not be urgent, partition lookups in paged-batches
            return product_registry

        product_registry.update(new_products)
        await self._ica_products.set_value(product_registry)
        return product_registry

    def should_refresh_login(self):
        auth_state = self.api.get_authenticated_user()
        if not auth_state or not auth_state.get("token"):
            return True
        token = auth_state["token"]
        expiry = (
            dt_util.parse_datetime(token["expiry"])
            if token and token.get("expiry", None)
            else None
        )
        if not expiry:
            return True
        now = dt_util.utcnow()
        # Set earlier expiry, to ensure refresh before token gets killed
        expires_in_seconds = token.get("expires_in", 2592000)
        expiry_margin_seconds = expires_in_seconds * 0.2
        expiry = expiry - timedelta(seconds=expiry_margin_seconds)
        return expiry < now

    async def _refresh_data(self, invalidate_cache: bool | None = None) -> None:
        # Get common ICA data first
        await self._ica_articles.get_value(invalidate_cache)
        await self._ica_baseitems.get_value(invalidate_cache)

        # Get user specific data
        await self._ica_current_bonus.get_value(invalidate_cache)
        await self._ica_shopping_lists.get_value(invalidate_cache)

        # Get store offers
        await self._ica_favorite_stores.get_value(invalidate_cache)
        await self._ica_offers.get_value(invalidate_cache)

    async def refresh_data(self, invalidate_cache: bool | None = None) -> None:
        """Fetch data from the ICA API (if necessary)."""
        new_auth_state = None
        dirty_cache = None
        if self._auth_initialized is None:
            # Initialize Auth during first refresh
            new_auth_state = await self.api.ensure_login()
        elif self.should_refresh_login():
            # Refresh login (due to expiry)
            _LOGGER.info("Refreshing auth token due to expiry")
            new_auth_state = await self.api.ensure_login(refresh=True)

        try:
            await self._refresh_data(invalidate_cache)
        except requests.exceptions.HTTPError as err:
            if err.response.status_code == 401:
                # Initiate re-login
                _LOGGER.info(
                    "Data fetch resulted in status %s. Refreshing login...",
                    err.response.status_code,
                )
                new_auth_state = await self.api.ensure_login(refresh=True)
                # Retry loading data (with new auth state)
                _LOGGER.info(
                    "Login seems to have been successfully refreshed, explicitly fetching new data..."
                )
                await self._refresh_data(invalidate_cache)
                # If cache was invalidated and successfully refreshed, then set dirty_cache flag to False
                dirty_cache = False if invalidate_cache is True else None
                return None
            # For other status codes, raise error directly
            _LOGGER.warning(
                "Got %s response during data update. Err: %s",
                err.response.status_code,
                err,
            )
            raise
        except Exception as err:
            _LOGGER.error("Exception when getting data. Err: %s", err)
            _LOGGER.error(traceback.format_exc())
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        else:
            # No exceptions during fetch, auth is valid
            if not self._auth_initialized:
                self._auth_initialized = True
            # If cache was invalidated and successfully refreshed, then set dirty_cache flag to False
            dirty_cache = False if invalidate_cache is True else None
        finally:
            if new_auth_state or dirty_cache is not None:
                self._try_persist_new_state(
                    self._config_entry, new_auth_state, dirty_cache
                )

    async def _async_setup(self) -> None:
        """Initialize coordinator."""
        await self.init_cache()

    async def _async_update_data(self) -> None:
        """Fetch data from the ICA API."""
        if self._config_entry.data.get(CONF_DIRTY_CACHE, False):
            await self.refresh_data(invalidate_cache=True)
        else:
            await self.refresh_data()

    def _try_persist_new_state(
        self,
        entry: ConfigEntry,
        auth_state: AuthState | None,
        dirty_cache: bool | None,
    ) -> bool | None:
        entry_data = entry.data.copy()
        if auth_state is not None:
            entry_data["auth_state"] = auth_state
        if dirty_cache is not None:
            entry_data[CONF_DIRTY_CACHE] = dirty_cache

        if self._hass.config_entries.async_update_entry(entry, data=entry_data):
            _LOGGER.info("Successfully updated config entry data with new state.")
            return True
        else:
            _LOGGER.debug("No changes when persisting state to config_entry data.")
            return False

    async def _async_update_tracked_shopping_lists(self) -> list[IcaShoppingList]:
        """Return ICA shopping lists fetched at most once."""
        current = self._ica_shopping_lists.current_value() or []
        updated = await self._get_tracked_shopping_lists() or []
        # if not updated:
        #     raise ValueError("Failed to get a valid shopping list from the API")

        for shopping_list in updated or []:
            old_rows = next(
                (lst["rows"] for lst in current if lst["id"] == shopping_list["id"]),
                None,
            )
            if old_rows is not None:
                # Skip on the first fetch of a list, as every row would count as added
                await self._fire_shopping_list_events(
                    shopping_list, old_rows, IcaEventOrigin.ICA
                )
            old_rows = old_rows or []
            new_rows = shopping_list["rows"]
            if diffs := get_diffs(old_rows, new_rows):
                await self._worker.fire_or_queue_event(
                    f"{DOMAIN}_event",
                    {
                        "type": "shopping_list_updated",
                        "uid": self._config_entry.data[CONF_ICA_ID],
                        "shopping_list_id": shopping_list["id"],
                        "shopping_list_name": shopping_list["title"],
                        "diffs": diffs,
                    },
                )
        return updated

    async def sync_shopping_list(
        self,
        sync: IcaShoppingListSync,
        conflict_mode: ConflictMode = ConflictMode.APPEND,
        instant_submit: bool = True,
    ) -> IcaShoppingList:
        """Pushes the specified changes to ICA. Might apply some conflict logic on the before. In the future changes could be batched together before being sumbmitted."""

        # TODO: Ensure that one of the fields are set 'changedRows', 'createdRows', 'deletedRows'
        # TODO: Apply conflict_mode logic
        # TODO: Batch changes before submitting after X seconds
        # TODO: Apply ordering

        # Push sync to API
        updated_list = await self.api.sync_shopping_list(sync)

        # todo: no need to await?, just queue it in background...
        await self._dynamically_update_shopping_list_cache(updated_list)
        return updated_list

    async def _dynamically_update_shopping_list_cache(
        self, updated_list: IcaShoppingList
    ) -> IcaShoppingList:
        state = self._ica_shopping_lists.current_value().copy()
        index = index_of(state, "offlineId", updated_list["offlineId"])
        if index >= 0:
            await self._fire_shopping_list_events(
                updated_list, state[index]["rows"], IcaEventOrigin.HOME_ASSISTANT
            )
            state[index] = updated_list
            await self._ica_shopping_lists.set_value(state)
            _LOGGER.info("Dynamically updated Shopping list cache")
            self.async_update_listeners()
        else:
            # Could not dynamically update state, invoke API request to get the new state...
            updated_list = await self.async_get_shopping_list(
                updated_list["offlineId"], invalidate_cache=True
            )
            _LOGGER.warning(
                "Could not dynamically update Shopping List cache. Updated via API instead..."
            )
        return updated_list

    async def _fire_shopping_list_events(
        self,
        shopping_list: IcaShoppingList,
        old_rows: list[IcaShoppingListEntry],
        origin: IcaEventOrigin,
    ) -> None:
        """Fires an event per changed row, plus one summarizing the changes."""
        changes = get_shopping_list_item_changes(old_rows, shopping_list["rows"])
        if not any(changes.values()):
            return
        # Leave out the offer details that the todo entity adds to the cached rows
        changes = {
            change: [{k: v for k, v in row.items() if k != "offer"} for row in rows]
            for change, rows in changes.items()
        }

        offline_id = shopping_list["offlineId"]
        base_data = {
            "config_entry_id": self._config_entry.entry_id,
            "entity_id": er.async_get(self._hass).async_get_entity_id(
                "todo", DOMAIN, f"{self._config_entry.entry_id}-{offline_id}"
            ),
            "shopping_list_id": offline_id,
            "shopping_list_name": shopping_list["title"],
            "origin": origin,
        }
        for change, event_type in SHOPPING_LIST_ITEM_EVENTS.items():
            for row in changes[change]:
                await self._worker.fire_or_queue_event(
                    event_type,
                    {**base_data, "product_name": row.get("productName"), "item": row},
                )
        await self._worker.fire_or_queue_event(
            IcaEvents.SHOPPING_LIST_CHANGED, {**base_data, **changes}
        )

    async def async_get_offers(
        self, store_ids: list[int] | None = None, favorites_only: bool = False
    ) -> list[IcaOfferInfo]:
        """Return the currently valid offers in the favorite stores."""
        now = datetime.now()
        all_offers = await self._ica_offers.get_value() or {}
        offers = [
            IcaOfferInfo.map_from_offer_details(o)
            for o in all_offers.values()
            if is_offer_valid(o, now)
        ]
        if store_ids:
            offers = [
                o
                for o in offers
                if any(s.get("id") in store_ids for s in o.get("stores") or [])
            ]
        if favorites_only:
            offers = match_offers_to_baseitems(
                offers, await self._ica_baseitems.get_value()
            )
        return sorted(offers, key=lambda o: o.get("validTo") or "")

    def get_baseitems(self):
        """Return ICA favorite items (baseitems) fetched at most once."""
        return self._ica_baseitems.current_value()

    async def async_get_baseitems(self, invalidate_cache: bool = False):
        """Return ICA favorite items (baseitems) fetched at most once."""
        return await self._ica_baseitems.get_value(invalidate_cache)

    async def lookup_baseitem_per_identifier(
        self, identifier: str
    ) -> IcaBaseItem | None:
        """Return a specific ICA recipe."""
        product = await self.api.lookup_barcode(identifier)
        if not product:
            return None
        return IcaBaseItem(
            id=str(uuid.uuid4()),
            text=product["name"],
            articleId=product["articleId"],
            articleGroupId=product.get("articleGroupId", DEFAULT_ARTICLE_GROUP_ID),
            articleGroupIdExtended=product.get(
                "expandedArticleGroupId", DEFAULT_ARTICLE_GROUP_ID
            ),
            articleEan=product["gtin"],
        )

    async def async_lookup_and_add_baseitem(self, identifier: str) -> list[IcaBaseItem]:
        """Return a specific ICA recipe."""
        (r, i) = try_parse_int(identifier)
        if r and i:
            # Successful parse
            item = await self.lookup_baseitem_per_identifier(identifier)
            if not item:
                raise ValueError(f"Product with ean '{identifier}' was not found")
        else:
            # Not a valid Barcode was passed. Treat as a free-text instead...
            item = IcaBaseItem(
                id=str(uuid.uuid4()),
                text=identifier,
            )

        sync = self._ica_baseitems.current_value().copy()
        current_sort_order = int(sync[-1]["sortOrder"] if len(sync) > 0 else -1)
        item["sortOrder"] = current_sort_order + 1
        sync.append(item)
        _LOGGER.info("ITEM: %s", item)
        return await self.sync_baseitems(sync)

    async def sync_baseitems(self, items: list[IcaBaseItem]) -> list[IcaBaseItem]:
        """Updates the account baseitems."""
        response = await self.api.sync_baseitems(items)
        if response:
            await self._ica_baseitems.set_value(response)
            _LOGGER.info("Dynamically updated BaseItems cache")
            self.async_update_listeners()
        return response

    async def async_get_articles(self):
        """Return pre-canned articles to add to shopping list (with article group)."""
        return await self._ica_articles.get_value()

    async def async_get_product_categories(self) -> list[IcaProductCategory]:
        """Return ICA product categories fetched at most once."""
        if self._productCategories is None:
            self._productCategories = await self.api.get_product_categories()
        return self._productCategories

    async def async_get_favorite_stores(self) -> list[IcaStore]:
        """Return ICA favorite stores."""
        return await self._ica_favorite_stores.get_value()

    async def _get_current_bonus(self):
        """Returns ICA bonus information"""
        current_bonus = await self.api.get_current_bonus()

        # Fire event
        await self._worker.fire_or_queue_event(
            f"{DOMAIN}_event",
            {
                "type": "current_bonus_loaded",
                "uid": self._config_entry.data[CONF_ICA_ID],
                "data": current_bonus,
            },
        )
        return current_bonus

    async def async_get_recipe(self, recipe_id: int) -> IcaRecipe | None:
        """Return a specific ICA recipe."""
        return await self.api.get_recipe(recipe_id)

    # async def async_get_recipes(self, nRecipes: int) -> list[IcaRecipe]:
    #     """Return ICA recipes."""
    #     if self._icaRecipes is None and self._nRecipes:
    #         self._icaRecipes = await self.api.get_random_recipes(nRecipes)
    #     return self._icaRecipes

    async def get_product_info(self, identifier: str) -> IcaProduct:
        (r, code) = try_parse_int(identifier)
        if r and code:
            # Successful parse
            code = str(code)
        else:
            # Not a valid Barcode was passed. Treat as a free-text instead...
            raise NotImplementedError(
                "Passing product identifiers as free-text is not yet supported"
            )

        product_registry = self._ica_products.current_value() or {}
        old = product_registry.get(code) or {}
        product = (
            old
            or IcaProduct(
                ean_id=code,
            )
        ).copy()

        if not product.get("article"):
            ica_product_lookup = await self.api.lookup_barcode(code)
            if ica_product_lookup:
                product["article"] = ica_product_lookup

        if not product.get("open_food_facts"):
            open_food_fact_product = await self.get_product_from_open_food_facts(code)
            if open_food_fact_product:
                product["open_food_facts"] = trim_props(open_food_fact_product)

        if (
            not product.get("article")
            and not product.get("open_food_facts")
            and not product.get("offers")
        ):
            # No product found, Invalid barcode?
            _LOGGER.warning("No matches for identifier: %s", identifier)
            return None

        # Commit any updated data
        product_registry[product["ean_id"]] = product
        _LOGGER.info(
            "Persisting product changes to registry: %s",
            get_diff_obj(old, product, key="ean_id"),
        )
        await self._ica_products.set_value(product_registry)
        return product

    async def get_product_from_open_food_facts(
        self,
        code: str,
        fields: Optional[list[str]] = None,
        raise_if_invalid: bool = False,
    ) -> Optional[OpenFoodFactsProduct]:
        """Return a product.

        If the product does not exist, None is returned.

        :param code: barcode of the product
        :param fields: a list of fields to return. If None, all fields are
            returned.
        :param raise_if_invalid: if True, a ValueError is raised if the
            barcode is invalid, defaults to False.
        :return: the API response
        """
        if not code or not isinstance(code, str):
            raise ValueError("code must be a non-empty string")
        url = OpenFoodFacts.APIv2.format(code)
        if fields := fields or OpenFoodFacts.DEFAULT_FIELDS:
            # requests escape comma in URLs, as expected, but openfoodfacts
            # server does not recognize escaped commas.
            # See
            # https://github.com/openfoodfacts/openfoodfacts-server/issues/1607
            url += f"?fields={','.join(fields)}"

        response = await self._openFoodFactsSession.get(
            url,
            headers={"User-Agent": "ha-ica-todo"},
            timeout=10,
        )

        try:
            if response.status == 404 and not raise_if_invalid:
                return None
            response.raise_for_status()
        except BaseException as ex:
            _LOGGER.error(
                "Error getting info from OpenFoodFacts. HTTP [GET] Resp: %s -> %s",
                response.status,
                response.text,
            )
            raise ex
        else:
            resp = await response.json()
            if resp is None:
                # product not found
                return None
            if resp.get("status", None) is None:
                raise ValueError(
                    "Seems like the API call to OpenFoodFacts failed. HTTP [GET] Resp: %s -> %s",
                    response.status,
                    response.text,
                )
            if resp["status"] == 0:
                # invalid barcode
                if raise_if_invalid:
                    raise ValueError(f"invalid barcode: {code}")
                return None

            p = resp["product"] if resp is not None else None
            nutriments = p.get("nutriments", {})
            return OpenFoodFactsProduct(
                brand_owner=p.get("brand_owner"),
                brands=p.get("brands"),
                product_name=p.get("product_name"),
                product_type=p.get("product_type"),
                quantity=p.get("quantity"),
                energy_kcal_value=nutriments.get(
                    "energy-kcal_value", nutriments.get("energy-kcal_100g")
                ),
                categories=p.get("categories_hierarchy"),
            )
