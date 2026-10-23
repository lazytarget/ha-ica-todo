import asyncio

from .icaapi import IcaAPI
from .icatypes import (
    AuthCredentials,
    AuthState,
    IcaAccountCurrentBonus,
    IcaArticle,
    IcaArticleOffer,
    IcaBaseItem,
    IcaProductCategory,
    IcaRecipe,
    IcaShoppingList,
    IcaShoppingListSync,
    IcaStore,
    OffersAndDiscountsForStore,
    ProductLookup,
)


async def run_async(func):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func)


class IcaAPIAsync:
    """Class to retrieve and hold the data for a Shopping list from ICA"""

    def __init__(
        self, credentials: AuthCredentials, auth_state: AuthState | None
    ) -> None:
        self._credentials = credentials
        self._auth_state = auth_state
        self._api = IcaAPI(self._credentials, self._auth_state)

    async def ensure_login(self, refresh: bool | None = None):
        return await run_async(lambda: self._api.ensure_login(refresh=refresh))

    def get_authenticated_user(self):
        return self._api.get_authenticated_user()

    async def get_shopping_lists(self) -> list[IcaShoppingList]:
        return await run_async(lambda: self._api.get_shopping_lists())

    async def get_shopping_list(self, list_id: str) -> IcaShoppingList:
        return await run_async(lambda: self._api.get_shopping_list(list_id))

    async def get_baseitems(self) -> list[IcaBaseItem]:
        return await run_async(lambda: self._api.get_baseitems())

    async def sync_baseitems(self, items: list[IcaBaseItem]) -> list[IcaBaseItem]:
        return await run_async(lambda: self._api.sync_baseitems(items))

    async def lookup_barcode(self, identifier) -> ProductLookup | None:
        return await run_async(lambda: self._api.lookup_barcode(identifier))

    async def search_articles(self, query: str) -> list:
        return await run_async(lambda: self._api.search_articles(query))

    async def get_articles(self) -> list[IcaArticle]:
        return await run_async(lambda: self._api.get_articles())

    async def get_store(self, store_id) -> IcaStore:
        return await run_async(lambda: self._api.get_store(store_id))

    async def get_favorite_stores(self) -> list[IcaStore]:
        return await run_async(lambda: self._api.get_favorite_stores())

    async def get_favorite_products(self):
        return await run_async(lambda: self._api.get_favorite_products())

    async def get_product_categories(self) -> list[IcaProductCategory]:
        return await run_async(lambda: self._api.get_product_categories())

    async def get_offers(
        self, store_ids: list[int]
    ) -> dict[str, OffersAndDiscountsForStore]:
        return await run_async(lambda: self._api.get_offers(store_ids))

    async def search_offers(
        self, store_ids: list[int], offer_ids: list[str]
    ) -> list[IcaArticleOffer]:
        return await run_async(lambda: self._api.search_offers(store_ids, offer_ids))

    async def get_current_bonus(self) -> IcaAccountCurrentBonus:
        return await run_async(lambda: self._api.get_current_bonus())

    async def get_recipe(self, recipe_id: int) -> IcaRecipe | None:
        return await run_async(lambda: self._api.get_recipe(recipe_id))

    async def get_random_recipes(self, nRecipes: int = 5) -> list[IcaRecipe]:
        return await run_async(lambda: self._api.get_random_recipes(nRecipes))

    async def create_shopping_list(
        self, offline_id: int, title: str, comment: str, store_sorting: bool = True
    ):
        return await run_async(
            lambda: self._api.create_shopping_list(
                offline_id, title, comment, store_sorting
            )
        )

    async def sync_shopping_list(self, data: IcaShoppingListSync) -> IcaShoppingList:
        return await run_async(lambda: self._api.sync_shopping_list(data))

    async def delete_shopping_list(self, offline_id):
        return await run_async(lambda: self._api.delete_shopping_list(offline_id))
