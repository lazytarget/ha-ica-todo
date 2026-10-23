"""Constants for the ICA component."""

import hashlib
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

DOMAIN: Final = "ica"
CONFIG_ENTRY_NAME: Final = "ICA - %s"
CONF_ICA_ID: Final = "personal_id"
CONF_ICA_PIN: Final = "pin_code"
CONF_SHOPPING_LISTS: Final = "shopping_lists"
CONF_DIRTY_CACHE: Final = "dirty_cache"
CONF_JSON_DATA_IN_DESC: Final = "json_data_in_desc"
CONF_AUTH_STATE: Final = "auth_state"

# Settings that live in `entry.options` (changed via the options flow)
OPTION_KEYS: Final = (CONF_SHOPPING_LISTS, CONF_JSON_DATA_IN_DESC, "scan_interval")

DEFAULT_SCAN_INTERVAL: Final = 5
CACHING_SECONDS_SHORT_TERM: Final = 300  # 5 minutes
CACHING_SECONDS_LONG_TERM: Final = 86400  # 24 hours

DEFAULT_ARTICLE_GROUP_ID: Final = 12

# Per-account cache files, `.storage/ica.<account key>.<name>.json`
ENTRY_CACHE_NAMES: Final = (
    "baseitems",
    "current_bonus",
    "favorite_stores",
    "shopping_lists",
    "offers",
)
# Cache files shared by all accounts
SHARED_CACHE_KEYS: Final = ("articles", "products")
# Debug dumps written by earlier versions
LEGACY_DEBUG_CACHE_KEYS: Final = (
    "products_changed--diffs",
    "offers_changed--base-data",
    "offers_changed--diffs",
    "offers_changed--new-offers",
)


def account_unique_id(personal_id: str) -> str:
    """Config entry unique id for an ICA account, without the personal ID number in clear."""
    digest = hashlib.sha256(personal_id.strip().encode()).hexdigest()
    return f"{DOMAIN}__{digest[:32]}"


def entry_cache_key(entry: "ConfigEntry") -> str:
    """Prefix of the cache files of a config entry."""
    return entry.entry_id


class ConflictMode(StrEnum):
    APPEND = "APPEND"
    MERGE = "MERGE"
    IGNORE = "IGNORE"


CONFLICT_MODES = [ConflictMode.APPEND, ConflictMode.MERGE, ConflictMode.IGNORE]


class IcaServices(StrEnum):
    """Services for the ICA integration"""

    REFRESH_ALL = "refresh_all"
    GET_RECIPE = "get_recipe"
    LOOKUP_PRODUCT = "lookup_product"
    # GET_STORE_DISCOUNTS = "get_store_discounts"
    GET_BASEITEMS = "get_baseitems"
    ADD_BASEITEM = "add_baseitem"
    # LOOKUP_BARCODE = "lookup_barcode"
    SEARCH_ARTICLES = "search_articles"
    UPSERT_SHOPPING_LIST = "upsert_shopping_list"
    ADD_OFFERS_TO_SHOPPING_LIST = "add_offers_to_shopping_list"
    CREATE_SHOPPING_LIST = "create_shopping_list"
    DELETE_SHOPPING_LIST = "delete_shopping_list"


class IcaEvents(StrEnum):
    NEW_OFFERS = f"{DOMAIN}_new_offers"
    LISTS_CHANGED = f"{DOMAIN}_lists_changed"
    LIST_ITEMS_CHANGED = f"{DOMAIN}_list_items_changed"


class API:
    class AppRegistration:
        APP_REGISTRATION_ENDPOINT: Final = "register"
        CLIENT_ID: Final = "ica-app-dcr-registration"
        CLIENT_SECRET: Final = (
            "uxLHTBvZ-Z2fV-SbrHl1E-tz7vB3jQFrwAdSLlbVMMu1rxDdvJU0s8KGu9d1wLS4"
        )

    class URLs:
        """URLs and API Endpoints"""

        BASE_URL: Final = "https://ims.icagruppen.se"

        OAUTH2_AUTHORIZE_ENDPOINT: Final = "oauth/v2/authorize"
        OAUTH2_TOKEN_ENDPOINT: Final = "oauth/v2/token"

        LOGIN_ENDPOINT: Final = "authn/authenticate/IcaCustomers"

        QUERY_BASE: Final = "https://apimgw-pub.ica.se"

        # ShoppingListService
        MY_BASEITEMS_ENDPOINT: Final = (
            "sverige/digx/mobile/shoppinglistservice/v1/baseitems"
        )
        SYNC_MY_BASEITEMS_ENDPOINT: Final = (
            "sverige/digx/mobile/shoppinglistservice/v1/baseitems"
        )
        ARTICLES_ENDPOINT: Final = "sverige/digx/mobile/shoppinglistservice/v1/articles"

        # OfferService
        OFFERS_SEARCH_ENDPOINT: Final = (
            "sverige/digx/mobile/offerservice/v1/offers/search"
        )

        # ProductService
        PRODUCT_BARCODE_LOOKUP_ENDPOINT: Final = (
            "sverige/digx/mobile/productservice/v1/product/{}"
        )

        # ArticleSearchService
        ARTICLE_SEARCH_ENDPOINT: Final = (
            "sverige/digx/shoppinglistarticlesearch/v1/search"
        )


MY_LISTS_ENDPOINT: Final = "sverige/digx/mobile/shoppinglistservice/v1/shoppinglists"  # "user/offlineshoppinglists"
MY_LIST_ENDPOINT: Final = "sverige/digx/mobile/shoppinglistservice/v1/shoppinglists/{}"
MY_LIST_SYNC_ENDPOINT: Final = (
    "sverige/digx/mobile/shoppinglistservice/v1/shoppinglists/{}/sync"
)
MY_CARDS_ENDPOINT: Final = (
    "sverige/digx/mobile/cardservice/v1/card/cardaccounts?api-version=2"
)
MY_BONUS_ENDPOINT: Final = "sverige/digx/mobile/bonusservice/v1/bonus/current"
MY_STORES_ENDPOINT: Final = "sverige/digx/mobile/storeservice/v1/favorites"
MY_RECIPES_ENDPOINT: Final = "sverige/digx/mobile/recipeservice/v1/favorites"
MY_COMMON_ARTICLES_ENDPOINT: Final = (
    "sverige/digx/mobile/shoppinglistservice/v1/shoppinglists/common"
)
STORE_ENDPOINT: Final = "sverige/digx/mobile/storeservice/v1/stores/{}"
STORE_SEARCH_ENDPOINT: Final = "stores/search?Filters&Phrase={}"
STORE_OFFERS_ENDPOINT: Final = "sverige/digx/mobile/offerservice/v1/offersdiscounts/{}"
OFFERS_ENDPOINT: Final = "offers?Stores={}"
ARTICLEGROUPS_ENDPOINT: Final = (
    "sverige/digx/mobile/shoppinglistservice/v1/articles/articlegroups?lastsyncdate={}"
)
RECIPE_ENDPOINT: Final = (
    "sverige/digx/mobile/recipeservice/v1/recipes/{}?api-version=2.0"
)
RANDOM_RECIPES_ENDPOINT: Final = (
    "sverige/digx/mobile/recipeservice/v1/recipes/random?numberofrecipes={}"
)


class OpenFoodFacts:
    APIv2 = "https://world.openfoodfacts.org/api/v2/product/{}.json"
    DEFAULT_FIELDS: Final = [
        "brand_owner",
        "brands",
        "quantity",
        "product_name",
        "product_type",
        "expiration_date",
        "categories_hierarchy",
        "nutriments",
    ]
