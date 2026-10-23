"""DataUpdateCoordinator for the ICA integration."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TypedDict

import homeassistant.util.dt as dt_util
import requests
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .background_worker import BackgroundWorker
from .caching import CacheEntry
from .const import (
    CACHING_SECONDS_SHORT_TERM,
    CONF_DIRTY_CACHE,
    CONF_ICA_ID,
    CONF_SHOPPING_LISTS,
    DEFAULT_ARTICLE_GROUP_ID,
    DOMAIN,
    ConflictMode,
    IcaEvents,
    entry_cache_key,
)
from .exceptions import IcaAuthError
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
    IcaProductOffer,
    IcaRecipe,
    IcaShoppingList,
    IcaShoppingListSync,
    IcaStore,
    IcaStoreOffer,
)
from .openfoodfacts import async_get_product
from .utils import (
    diff_list_rows,
    get_diff_obj,
    get_diffs,
    index_of,
    parse_aware_datetime,
    resolve_list_entity_ids,
    trim_props,
    try_parse_int,
)

_LOGGER = logging.getLogger(__name__)

# Offers are kept this long after they expired, so items in lists can still show them
OFFER_RETENTION = timedelta(days=30)


class IcaCoordinatorData(TypedDict):
    """Snapshot of the data the entities are built from."""

    shopping_lists: list[IcaShoppingList]
    baseitems: list[IcaBaseItem]


class IcaCoordinator(DataUpdateCoordinator[IcaCoordinatorData]):
    """Coordinator for updating task data from ICA."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        update_interval: timedelta,
        api: IcaAPIAsync,
    ) -> None:
        """Initialize the ICA coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api: IcaAPIAsync = api
        self._auth_initialized: bool | None = None
        # The options the integration was (re)loaded with. Used to tell option
        # changes that need a reload from ones that are applied already.
        self.applied_options: dict = dict(config_entry.options)

        self._worker = BackgroundWorker(hass, config_entry)
        config_entry.async_on_unload(self._worker.shutdown)

        self._session = async_get_clientsession(hass)

        key = entry_cache_key(config_entry)

        self._ica_articles = CacheEntry[list[IcaArticle]](
            hass, "articles", partial(self.api.get_articles)
        )
        self._ica_baseitems = CacheEntry[list[IcaBaseItem]](
            hass,
            f"{key}.baseitems",
            partial(self.api.get_baseitems),
            expiry_seconds=CACHING_SECONDS_SHORT_TERM,
        )
        self._ica_current_bonus = CacheEntry[IcaAccountCurrentBonus](
            hass, f"{key}.current_bonus", partial(self._get_current_bonus)
        )
        self._ica_favorite_stores = CacheEntry[list[IcaStore]](
            hass,
            f"{key}.favorite_stores",
            partial(self.api.get_favorite_stores),
        )
        self._ica_shopping_lists = CacheEntry[list[IcaShoppingList]](
            hass,
            f"{key}.shopping_lists",
            partial(self._async_update_tracked_shopping_lists),
            expiry_seconds=CACHING_SECONDS_SHORT_TERM,
        )
        self._ica_offers = CacheEntry[dict[str, IcaOfferDetails]](
            hass,
            f"{key}.offers",
            partial(self._update_offer_details),
        )
        self._ica_products = CacheEntry[dict[str, IcaProduct]](
            hass,
            "products",
            partial(self._update_products),
        )

    @property
    def account_id(self) -> str:
        """The ICA account (personal ID number). Only for API payloads, never logs."""
        return self.config_entry.data[CONF_ICA_ID]

    async def init_cache(self) -> None:
        """Initializes the cache from local files."""
        await self._ica_articles.init_value()
        await self._ica_baseitems.init_value()
        await self._ica_current_bonus.init_value()
        await self._ica_favorite_stores.init_value()
        await self._ica_shopping_lists.init_value()
        await self._ica_offers.init_value()
        await self._ica_products.init_value()

    def snapshot(self) -> IcaCoordinatorData:
        """The current data, as published to the entities."""
        return IcaCoordinatorData(
            shopping_lists=self._ica_shopping_lists.current_value() or [],
            baseitems=self._ica_baseitems.current_value() or [],
        )

    def _publish(self) -> None:
        """Inform the entities about data that changed outside of a regular update."""
        self.async_set_updated_data(self.snapshot())

    async def _get_tracked_shopping_lists(self) -> list[IcaShoppingList]:
        list_ids = self.config_entry.options.get(CONF_SHOPPING_LISTS) or []
        lists: list[IcaShoppingList] = []
        missing: list[str] = []
        for offline_id in list_ids:
            if not offline_id:
                continue
            try:
                shopping_list = await self.api.get_shopping_list(offline_id)
            except requests.exceptions.HTTPError as err:
                if err.response is not None and err.response.status_code == 404:
                    # List was deleted (e.g. in the ICA app) - stop tracking it instead of failing setup
                    _LOGGER.warning(
                        "Tracked shopping list %s no longer exists, untracking it",
                        offline_id,
                    )
                    missing.append(offline_id)
                    continue
                raise
            if shopping_list:
                lists.append(shopping_list)
        if missing:
            options = dict(self.config_entry.options)
            options[CONF_SHOPPING_LISTS] = [x for x in list_ids if x not in missing]
            # Applied already, so the options update must not trigger a reload
            self.applied_options = options
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=options
            )
        return lists

    def _list_entity_id(self, offline_id: str) -> str | None:
        registry = er.async_get(self.hass)
        entries = [
            (e.unique_id, e.entity_id)
            for e in er.async_entries_for_config_entry(
                registry, self.config_entry.entry_id
            )
        ]
        return resolve_list_entity_ids(
            entries, self.config_entry.entry_id, [offline_id]
        ).get(offline_id)

    def get_shopping_list(self, list_offline_id) -> IcaShoppingList | None:
        selected_lists = self._ica_shopping_lists.current_value() or []
        return next(
            (x for x in selected_lists if x["offlineId"] == list_offline_id), None
        )

    async def async_get_shopping_list(
        self, list_id, invalidate_cache: bool = False
    ) -> IcaShoppingList | None:
        selected_lists = await self.async_get_shopping_lists(invalidate_cache)
        return next((x for x in selected_lists if x["offlineId"] == list_id), None)

    async def async_get_shopping_lists(
        self, invalidate_cache: bool = False
    ) -> list[IcaShoppingList]:
        selected_lists = (
            await self._ica_shopping_lists.get_value(invalidate_cache) or []
        )
        if invalidate_cache:
            # Updated Shopping list cache outside of regular `_async_update_data-loop`, inform listeners...
            self._publish()
        return selected_lists

    def get_article_group(self, product_name) -> int:
        articles = self._ica_articles.current_value() or []
        product_name = product_name.casefold()
        for x in articles:
            if x.get("name", "").casefold() == product_name:
                return x.get("parentId") or DEFAULT_ARTICLE_GROUP_ID
        return DEFAULT_ARTICLE_GROUP_ID  # Unspecified

    _SUMMARY_RE = re.compile(
        r"^(?:(?P<min_quantity>\d+(?:[.,]\d+)?)\s*[-–]\s*)?"
        r"(?P<quantity>\d+(?:[.,]\d+)?)\s*"
        r"(?:(?P<unit>st|förp|kg|hg|g|l|dl|cl|ml|msk|tsk|krm)(?=\s|$))?\s*"
        r"(?P<name>.*\S)\s*$",
        re.IGNORECASE,
    )

    @staticmethod
    def format_quantity(quantity) -> str:
        """Format a quantity the Swedish way: 2 -> '2', 1.5 -> '1,5'."""
        try:
            q = float(quantity)
        except (TypeError, ValueError):
            return str(quantity)
        return str(int(q)) if q.is_integer() else f"{q:g}".replace(".", ",")

    def parse_summary(self, summary):
        """Split e.g. '2 gula lökar', '500 g nötfärs' or '1,5 l mjölk' into quantity/unit/name.

        - A unit only matches as a whole word ('1 gurka' is not '1 g urka').
        - The quantity is sent to ICA as a number (ICA rejects strings like '1,5').
        - Text without a leading number is kept as is.
        """
        summary = (summary or "").strip()
        ti = {"summary": summary, "productName": summary}
        r = self._SUMMARY_RE.match(summary)
        if r and r["name"]:
            try:
                quantity = float(r["quantity"].replace(",", "."))
            except (TypeError, ValueError):
                quantity = None
            if quantity is not None and quantity > 0:
                unit = r["unit"].lower() if r["unit"] else None
                ti["productName"] = r["name"]
                ti["quantity"] = quantity
                if unit:
                    ti["unit"] = unit
                ti["summary"] = " ".join(
                    x for x in (self.format_quantity(quantity), unit, r["name"]) if x
                )

        if articleGroupId := self.get_article_group(ti["productName"]):
            ti["articleGroupId"] = articleGroupId

        _LOGGER.debug("Parsed info from '%s' to %s", summary, ti)
        return ti

    def get_offer_info(self, offer_id) -> IcaOfferDetails | None:
        offers = self._ica_offers.current_value()
        return offers.get(offer_id) if isinstance(offers, dict) else None

    async def _update_offer_details(
        self, store_ids: list[str] | None = None
    ) -> dict[str, IcaOfferDetails]:
        now = dt_util.now()
        current = self._ica_offers.current_value()
        if not isinstance(current, dict):
            # Earlier versions could cache an empty list here
            current = {}
        target = current.copy()
        pre_count = len(current)

        if not store_ids:
            # No passed store_ids then use the favorite stores
            stores = await self._ica_favorite_stores.get_value() or []
            store_ids = [s["id"] for s in stores]

        offers_per_store = await self.api.get_offers(store_ids)
        if not offers_per_store:
            _LOGGER.warning("Failed to get offers from stores")
            return current

        product_registry = self._ica_products.current_value() or {}
        product_registry_old = product_registry.copy()
        product_count = len(product_registry)

        # Remove obsolete offers (some time after they expired)
        for offer_id, offer in current.items():
            self._copy_offer_products_to_registry(offer, product_registry)
            valid_to = parse_aware_datetime(
                (offer or {}).get("validTo"), dt_util.get_default_time_zone()
            )
            if valid_to and valid_to + OFFER_RETENTION < now:
                _LOGGER.debug("Removing obsolete offer: %s", offer_id)
                del target[offer_id]

        # Look up the "active" offers that was retrieved
        store_ids = list(offers_per_store.keys())
        offer_ids: set[str] = set()
        store_offers: dict[str, IcaStoreOffer] = {}
        for store in offers_per_store.values():
            for o in store["offers"]:
                offer_ids.add(o["id"])
                c = store_offers.get(o["id"]) or IcaStoreOffer()
                c.update(o)
                store_offers[o["id"]] = c

        if not offer_ids:
            _LOGGER.debug("No offers to lookup, then avoid querying API")
            return target

        full_offers = await self.api.search_offers(store_ids, sorted(offer_ids))
        if not full_offers:
            _LOGGER.warning("No details found for %s offers", len(offer_ids))
            return target

        new_offers: list[IcaOfferInfo] = []
        for f in full_offers:
            current_offer = target.get(f["id"]) or IcaOfferDetails()
            store_offer = store_offers.get(f["id"]) or IcaStoreOffer()

            offer = current_offer.copy()
            offer.update(store_offer)
            offer.update(f)
            target[offer["id"]] = offer
            if not current_offer:
                new_offers.append(IcaOfferInfo.map_from_offer_details(offer))
            self._copy_offer_products_to_registry(offer, product_registry)

        new_product_count = len(product_registry)
        if product_count != new_product_count:
            _LOGGER.debug(
                "Persisting %s new products", new_product_count - product_count
            )
            await self._update_products(product_registry)

        if diffs := get_diffs(
            product_registry_old, product_registry, include_values=False
        ):
            await self._worker.fire_or_queue_event(
                f"{DOMAIN}_product_event",
                {
                    "type": "products_changed",
                    "uid": self.account_id,
                    "timestamp": str(datetime.now(UTC)),
                    "pre_count": product_count,
                    "post_count": new_product_count,
                    "diffs": diffs,
                },
            )

        if diffs := get_diffs(current, target, include_values=False):
            await self._worker.fire_or_queue_event(
                f"{DOMAIN}_event",
                {
                    "type": "offers_changed",
                    "uid": self.account_id,
                    "timestamp": str(datetime.now(UTC)),
                    "pre_count": pre_count,
                    "post_count": len(target),
                    "diffs": diffs,
                },
            )

        if new_offers:
            await self._worker.fire_or_queue_event(
                IcaEvents.NEW_OFFERS,
                {
                    "type": "new_offers",
                    "uid": self.account_id,
                    "timestamp": str(datetime.now(UTC)),
                    "pre_count": pre_count,
                    "post_count": len(target),
                    "new_offers": new_offers,
                },
            )

        _LOGGER.debug(
            "Updated offer details, pre_count: %s, post_count: %s",
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
                    # Migrate products stored by earlier versions
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
        """Fetch data from the ICA API (if necessary).

        Raises `ConfigEntryAuthFailed` when the credentials are no longer valid, and
        `UpdateFailed` for other errors.
        """
        new_auth_state: AuthState | None = None
        dirty_cache: bool | None = None
        try:
            if self._auth_initialized is None:
                # Initialize Auth during first refresh
                new_auth_state = await self.api.ensure_login()
            elif self.should_refresh_login():
                _LOGGER.debug("Refreshing auth token due to expiry")
                new_auth_state = await self.api.ensure_login(refresh=True)

            try:
                await self._refresh_data(invalidate_cache)
            except requests.exceptions.HTTPError as err:
                if err.response is None or err.response.status_code != 401:
                    raise
                _LOGGER.debug("Data fetch was unauthorized, refreshing login")
                new_auth_state = await self.api.ensure_login(refresh=True)
                await self._refresh_data(invalidate_cache)

            self._auth_initialized = True
            # If cache was invalidated and successfully refreshed, the cache is clean
            dirty_cache = False if invalidate_cache is True else None
        except IcaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (requests.exceptions.RequestException, ValueError, KeyError) as err:
            raise UpdateFailed(f"Error communicating with the ICA API: {err}") from err
        finally:
            if new_auth_state or dirty_cache is not None:
                self._persist_state(new_auth_state, dirty_cache)

    async def async_refresh_all(self) -> None:
        """Refetch all data, ignoring the cache, and update the entities."""
        await self.refresh_data(invalidate_cache=True)
        self._publish()

    async def _async_setup(self) -> None:
        """Initialize coordinator."""
        await self.init_cache()

    async def _async_update_data(self) -> IcaCoordinatorData:
        """Fetch data from the ICA API."""
        dirty = self.config_entry.data.get(CONF_DIRTY_CACHE, False)
        await self.refresh_data(invalidate_cache=True if dirty else None)
        return self.snapshot()

    def _persist_state(
        self, auth_state: AuthState | None, dirty_cache: bool | None
    ) -> None:
        entry_data = dict(self.config_entry.data)
        if auth_state is not None:
            entry_data["auth_state"] = auth_state
        if dirty_cache is not None:
            entry_data[CONF_DIRTY_CACHE] = dirty_cache
        if self.hass.config_entries.async_update_entry(
            self.config_entry, data=entry_data
        ):
            _LOGGER.debug("Updated config entry data with new state")

    async def _async_update_tracked_shopping_lists(self) -> list[IcaShoppingList]:
        """Return ICA shopping lists fetched at most once."""
        current = self._ica_shopping_lists.current_value() or []
        updated = await self._get_tracked_shopping_lists()

        for shopping_list in updated:
            previous = next(
                (lst for lst in current if lst["id"] == shopping_list["id"]), None
            )
            old_rows = previous["rows"] if previous else []
            if previous is not None:
                # Skipped for lists seen for the first time, so initial load is silent
                changes = diff_list_rows(old_rows, shopping_list["rows"])
                if any(changes.values()):
                    await self._worker.fire_or_queue_event(
                        IcaEvents.LIST_ITEMS_CHANGED,
                        {
                            "entity_id": self._list_entity_id(
                                shopping_list["offlineId"]
                            ),
                            "offline_id": shopping_list["offlineId"],
                            **changes,
                        },
                    )
            if diffs := get_diffs(old_rows, shopping_list["rows"]):
                await self._worker.fire_or_queue_event(
                    f"{DOMAIN}_event",
                    {
                        "type": "shopping_list_updated",
                        "uid": self.account_id,
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
    ) -> IcaShoppingList:
        """Pushes the specified changes to ICA.

        Conflicts are resolved when building the sync request, see
        `IcaShoppingListEntity.async_generate_sync_request`.
        """
        updated_list = await self.api.sync_shopping_list(sync)
        return await self._dynamically_update_shopping_list_cache(updated_list)

    async def _dynamically_update_shopping_list_cache(
        self, updated_list: IcaShoppingList
    ) -> IcaShoppingList:
        state = list(self._ica_shopping_lists.current_value() or [])
        index = index_of(state, "offlineId", updated_list["offlineId"])
        if index >= 0:
            state[index] = updated_list
            await self._ica_shopping_lists.set_value(state)
            _LOGGER.debug("Dynamically updated Shopping list cache")
            self._publish()
            return updated_list

        # Could not dynamically update state, invoke API request to get the new state...
        _LOGGER.debug("Shopping list not cached, updating the cache via the API")
        return (
            await self.async_get_shopping_list(
                updated_list["offlineId"], invalidate_cache=True
            )
            or updated_list
        )

    def get_baseitems(self) -> list[IcaBaseItem]:
        """Return ICA favorite items (baseitems) from the cache."""
        return self._ica_baseitems.current_value() or []

    async def async_get_baseitems(self, invalidate_cache: bool = False):
        """Return ICA favorite items (baseitems) fetched at most once."""
        return await self._ica_baseitems.get_value(invalidate_cache)

    async def lookup_baseitem_per_identifier(
        self, identifier: str
    ) -> IcaBaseItem | None:
        """Return a favorite item for a barcode."""
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
        """Add a favorite item by barcode, or by name when it isn't a barcode."""
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

        sync = list(await self.async_get_baseitems() or [])
        item["sortOrder"] = (
            max((int(x.get("sortOrder") or 0) for x in sync), default=-1) + 1
        )
        sync.append(item)
        _LOGGER.debug("Adding favorite item: %s", item)
        return await self.sync_baseitems(sync)

    async def sync_baseitems(self, items: list[IcaBaseItem]) -> list[IcaBaseItem]:
        """Updates the account baseitems."""
        response = await self.api.sync_baseitems(items)
        if response:
            await self._ica_baseitems.set_value(response)
            _LOGGER.debug("Dynamically updated BaseItems cache")
            self._publish()
        return response

    async def _get_current_bonus(self):
        """Returns ICA bonus information"""
        current_bonus = await self.api.get_current_bonus()

        await self._worker.fire_or_queue_event(
            f"{DOMAIN}_event",
            {
                "type": "current_bonus_loaded",
                "uid": self.account_id,
                "data": current_bonus,
            },
        )
        return current_bonus

    async def async_get_recipe(self, recipe_id: int) -> IcaRecipe | None:
        """Return a specific ICA recipe."""
        return await self.api.get_recipe(recipe_id)

    async def get_product_info(self, identifier: str) -> IcaProduct | None:
        (r, code) = try_parse_int(identifier)
        if not (r and code):
            raise NotImplementedError(
                "Passing product identifiers as free-text is not yet supported"
            )
        # Keep leading zeros of the barcode
        code = identifier.strip()

        product_registry = self._ica_products.current_value() or {}
        old = product_registry.get(code) or {}
        product = (old or IcaProduct(ean_id=code)).copy()

        if not product.get("article"):
            ica_product_lookup = await self.api.lookup_barcode(code)
            if ica_product_lookup:
                product["article"] = ica_product_lookup

        if not product.get("open_food_facts"):
            open_food_fact_product = await async_get_product(self._session, code)
            if open_food_fact_product:
                product["open_food_facts"] = trim_props(open_food_fact_product)

        if (
            not product.get("article")
            and not product.get("open_food_facts")
            and not product.get("offers")
        ):
            # No product found, Invalid barcode?
            _LOGGER.info("No product matches for identifier: %s", identifier)
            return None

        # Commit any updated data
        product_registry[product["ean_id"]] = product
        _LOGGER.debug(
            "Persisting product changes to registry: %s",
            get_diff_obj(old, product, key="ean_id"),
        )
        await self._ica_products.set_value(product_registry)
        return product
