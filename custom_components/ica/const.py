"""Constants for the ICA component."""

from typing import Final
from enum import StrEnum

CONF_EXTRA_PROJECTS: Final = "custom_projects"
CONF_PROJECT_DUE_DATE: Final = "due_date_days"
CONF_PROJECT_LABEL_WHITELIST: Final = "labels"
CONF_PROJECT_WHITELIST: Final = "include_projects"

# Calendar Platform: Does this calendar event last all day?
ALL_DAY: Final = "all_day"
# Attribute: All tasks in this project
ALL_TASKS: Final = "all_tasks"
# Todoist API: "Completed" flag -- 1 if complete, else 0
CHECKED: Final = "checked"
# Attribute: Is this task complete?
COMPLETED: Final = "completed"
# Todoist API: What is this task about?
# Service Call: What is this task about?
CONTENT: Final = "content"
# Calendar Platform: Get a calendar event's description
DESCRIPTION: Final = "description"
# Calendar Platform: Used in the '_get_date()' method
DATETIME: Final = "dateTime"
DUE: Final = "due"
# Service Call: When is this task due (in natural language)?
DUE_DATE_STRING: Final = "due_date_string"
# Service Call: The language of DUE_DATE_STRING
DUE_DATE_LANG: Final = "due_date_lang"
# Service Call: When should user be reminded of this task (in natural language)?
REMINDER_DATE_STRING: Final = "reminder_date_string"
# Service Call: The language of REMINDER_DATE_STRING
REMINDER_DATE_LANG: Final = "reminder_date_lang"
# Service Call: The available options of DUE_DATE_LANG
DUE_DATE_VALID_LANGS: Final = ["en", "sv"]
# Attribute: When is this task due?
# Service Call: When is this task due?
DUE_DATE: Final = "due_date"
# Service Call: When should user be reminded of this task?
REMINDER_DATE: Final = "reminder_date"
# Attribute: Is this task due today?
DUE_TODAY: Final = "due_today"
# Calendar Platform: When a calendar event ends
END: Final = "end"
# Todoist API: Look up a Project/Label/Task ID
ID: Final = "id"
# Todoist API: Fetch all labels
# Service Call: What are the labels attached to this task?
LABELS: Final = "labels"
# Todoist API: "Name" value
NAME: Final = "name"
# Todoist API: "Full Name" value
FULL_NAME: Final = "full_name"
# Attribute: Is this task overdue?
OVERDUE: Final = "overdue"
# Attribute: What is this task's priority?
# Todoist API: Get a task's priority
# Service Call: What is this task's priority?
PRIORITY: Final = "priority"
# Todoist API: Look up the Project ID a Task belongs to
PROJECT_ID: Final = "project_id"
# Service Call: What Project do you want a Task added to?
PROJECT_NAME: Final = "project"
# Todoist API: Fetch all Projects
PROJECTS: Final = "projects"
# Calendar Platform: When does a calendar event start?
START: Final = "start"
# Calendar Platform: What is the next calendar event about?
SUMMARY: Final = "summary"
# Todoist API: Fetch all Tasks
TASKS: Final = "items"
# Todoist API: "responsible" for a Task
ASSIGNEE: Final = "assignee"
# Todoist API: Collaborators in shared projects
COLLABORATORS: Final = "collaborators"

SERVICE_NEW_TASK: Final = "new_task"


"""Constants for ICA shopping list"""

DOMAIN: Final = "ica"
CONFIG_ENTRY_NAME: Final = "ICA - %s"
CONF_ICA_ID: Final = "personal_id"
CONF_ICA_PIN: Final = "pin_code"
CONF_SHOPPING_LISTS: Final = "shopping_lists"
CONF_DIRTY_CACHE: Final = "dirty_cache"
CONF_NUM_RECIPES: Final = "recipe_count"

CONF_JSON_DATA_IN_DESC: Final = "json_data_in_desc"
CONF_MENU_MANAGE_SHOPPING_LISTS: Final = "manage_tracked_shopping_lists"

DEFAULT_SCAN_INTERVAL: Final = 5
CACHING_SECONDS_SHORT_TERM: Final = 300  # 5 minutes
CACHING_SECONDS_LONG_TERM: Final = 86400  # 24 hours

AUTH_TICKET: Final = "AuthenticationTicket"
GET_LISTS: Final = "ShoppingLists"
LIST_NAME: Final = "Title"
ITEM_LIST: Final = "Rows"
ITEM_NAME: Final = "ProductName"
IS_CHECKED: Final = "IsStrikedOver"

DEFAULT_ARTICLE_GROUP_ID: Final = 12


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
    GET_OFFERS = "get_offers"
    REFRESH_SHOPPING_LISTS = "refresh_shopping_lists"


class IcaEvents(StrEnum):
    NEW_OFFERS = f"{DOMAIN}_new_offers"
    FAVORITE_OFFERS = f"{DOMAIN}_favorite_offers"
    SHOPPING_LIST_CHANGED = f"{DOMAIN}_shopping_list_changed"
    SHOPPING_LIST_ITEM_ADDED = f"{DOMAIN}_shopping_list_item_added"
    SHOPPING_LIST_ITEM_REMOVED = f"{DOMAIN}_shopping_list_item_removed"
    SHOPPING_LIST_ITEM_COMPLETED = f"{DOMAIN}_shopping_list_item_completed"
    SHOPPING_LIST_ITEM_REOPENED = f"{DOMAIN}_shopping_list_item_reopened"


# Maps the keys from `utils.get_shopping_list_item_changes` to their event
SHOPPING_LIST_ITEM_EVENTS: Final = {
    "added": IcaEvents.SHOPPING_LIST_ITEM_ADDED,
    "removed": IcaEvents.SHOPPING_LIST_ITEM_REMOVED,
    "completed": IcaEvents.SHOPPING_LIST_ITEM_COMPLETED,
    "reopened": IcaEvents.SHOPPING_LIST_ITEM_REOPENED,
}


class IcaEventOrigin(StrEnum):
    """Where a shopping list change was made"""

    ICA = "ica"  # Outside of Home Assistant, e.g. in the ICA app
    HOME_ASSISTANT = "home_assistant"


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
