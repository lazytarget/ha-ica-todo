from typing import Any, Generic, TypedDict, TypeVar

from .utils import try_parse_int

_DataT = TypeVar("_DataT", default=dict[str, Any])


class AuthCredentials(TypedDict):
    username: str
    password: str


class OAuthClient(TypedDict):
    client_id: str
    client_secret: str
    scope: str


class OAuthToken(TypedDict):
    """Represents the authentication state.

    Contains the OAuth client information, token, and user info.
    """

    id_token: str | None
    token_type: str
    access_token: str
    refresh_token: str
    scope: str
    expires_in: int
    # # Extra properties not defined in OAuth spec:
    expiry: str


class JwtUserInfo(dict):
    def __init__(self, decoded_jwt):
        self["given_name"] = decoded_jwt["given_name"]
        self["family_name"] = decoded_jwt["family_name"]
        self["person_name"] = (
            f"{decoded_jwt['given_name']} {decoded_jwt['family_name']}"
        )

    @property
    def person_name(self) -> str | None:
        return self["person_name"]


class AuthState(TypedDict):
    client: OAuthClient | None
    token: OAuthToken | None
    user: JwtUserInfo | None


class IcaBonusLevel(TypedDict):
    levelId: int
    pointValueFrom: int
    pointValueTom: int
    voucherValue: int


class IcaVoucher(TypedDict):
    title: str | None
    subTite: str | None
    description: str | None
    redeemedDate: str | None  # Only for used
    voucherCode: str | None  # example ["Monthly"]
    voucherType: str | None  # example ["Common"]
    sender: str | None  # example ["MonthlyBatch"]
    voucherAmount: int | None


class IcaVoucherList(TypedDict):
    active: list[IcaVoucher] | None
    used: list[IcaVoucher] | None


class IcaBalanceDetail(TypedDict):
    balanceDescription: str | None
    pointValue: int
    voucherValue: int
    sender: str | None


class IcaBalanceGroup(TypedDict):
    balanceCode: int | None
    balanceDescription: str | None
    pointValue: int
    voucherValue: int
    detailedBalances: list[IcaBalanceDetail] | None


class IcaAccountBalance(TypedDict):
    showPreliminaryBonus: bool | None
    preliminaryBonusText: str | None
    voucherMonth: str | None
    loyaltyMonth: str | None
    totalVoucherValue: int | None
    nextVoucherValue: int | None
    remainingPointsIncludingBoost: int | None
    remainingDays: int | None
    title: str | None
    groupedBalances: list[IcaBalanceGroup] | None


class IcaDiscountSummary(TypedDict):
    totalDiscount: int
    numberOfPurchases: int


class IcaAccountCurrentBonus(TypedDict):
    stammisBoostPreamble: str | None
    stammisBoostText: str | None
    stammisBoostBonusLevelText: str | None
    bonusLevels: list[IcaBonusLevel] | None
    vouchers: list[IcaVoucherList] | None
    accountBalance: IcaAccountBalance | None
    discountSummary: IcaDiscountSummary | None
    errorFetchingDiscount: bool | None


class Address(TypedDict):
    street: str | None
    zip: str | None
    city: str | None


class Coordinate(TypedDict):
    latitude: float | None
    longitude: float | None


class DayOpeningHours(TypedDict):
    title: str | None
    hours: str | None


class OpeningHours(TypedDict):
    today: str | None
    regularHours: list[DayOpeningHours] | None
    specialHours: list[DayOpeningHours] | None
    departmentHours: list[DayOpeningHours] | None
    serviceOpeningHours: list[DayOpeningHours] | None


class ArticleInfo(TypedDict):
    """Minimal information about an Article"""

    # name: str | None  # "articleName"
    # articleId: int | None
    articleGroupId: int | None
    expandedArticleGroupId: int | None


class ProductLookup(ArticleInfo):
    gtin: str | None  # "eanId / barcode"
    name: str | None  # "articleName"
    articleId: int | None
    # articleGroupId: int | None
    # expandedArticleGroupId: int | None


class OpenFoodFactsProduct(TypedDict):
    brand_owner: str | None
    brands: str | None
    quantity: str | None
    product_name: str | None
    product_type: str | None
    energy_kcal_value: int | None
    categories: list[str]


class IcaStore(TypedDict):
    id: int  # "storeId"
    marketingName: str | None
    address: Address | None
    phone: str | None
    coordinates: Coordinate | None
    webURL: str | None
    openingHours: OpeningHours | None


class IcaArticleCategory(TypedDict):
    articleGroupName: str | None
    articleGroupId: int | None
    expandedArticleGroupName: str | None
    expandedArticleGroupId: int | None


class ArticleOfferEanSlim(TypedDict):
    id: str | None  # "eanId"
    articleDescription: str | None


class ArticleOfferEan(ArticleOfferEanSlim):
    imageUrl: str | None


class ArticleOfferStoreSlim(TypedDict):
    id: str | None  # "storeId"
    referencePriceText: str | None


class ArticleOfferStore(ArticleOfferStoreSlim):
    isValidInStore: bool | None
    isValidOnline: bool | None


class IcaOfferMechanics(TypedDict):
    type: str | None  # Example "Standard"
    quantity: float | None
    unitSign: str | None
    value1: str | None
    value2: str | None
    value3: str | None
    value4: str | None

    @classmethod
    def format_to_string(cls, mech: dict) -> str:
        # todo: rewrite `parsedMechanics` as string (like the ICA-app does)
        mech = mech or {}
        result = ""

        def format_value(v: str) -> str:
            (r, i) = try_parse_int(v)
            return f"{i}{mech.get('unitSign', '')}".strip() if r and i else v.strip()

        if mech.get("type") == "Standard":
            result = f"{result} {format_value(mech.get('value1'))}".strip()
            result = f"{result} {format_value(mech.get('value2'))}".strip()
            result = f"{result} {format_value(mech.get('value3'))}".strip()
            result = f"{result} {format_value(mech.get('value4'))}".strip()
        else:
            result = mech.get("type")
        return result or ""


class IcaStoreOffer(TypedDict):
    # From Offerdiscounts for specific store
    id: str | None  # "OfferId"
    category: IcaArticleCategory | None
    name: str | None  # "ArticleName / OfferName"
    brand: str | None
    packageInformation: str | None
    condition: str | None
    restriction: str | None
    referencePriceText: str | None
    isSelfScan: bool | None
    isPersonal: bool | None
    isUsed: bool | None
    isValidInStore: bool | None
    isValidOnline: bool | None
    validFrom: str | None
    validTo: str | None
    requiresLoyaltyCard: bool | None
    pictureUrl: str | None
    listImageUrl: str | None
    isProfileHighlight: bool | None
    isStoreHighlight: bool | None
    parsedMechanics: IcaOfferMechanics | None


class IcaArticleOffer(TypedDict):
    # From SearchOffers (based on StoreId and OfferIds)
    id: str | None  # "OfferId"
    category: IcaArticleCategory | None
    name: str | None  # "ArticleName / OfferName"
    brand: str | None
    packageInformation: str | None
    customerInformation: str | None
    condition: str | None
    disclaimer: str | None
    restriction: str | None
    referenceInfo: str | None
    isSelfScan: bool | None
    isPersonal: bool | None
    isUsed: bool | None
    eans: list[ArticleOfferEan] | None
    stores: list[ArticleOfferStore] | None
    validFrom: str | None
    validTo: str | None
    requiresLoyaltyCard: bool | None
    pictureUrl: str | None
    mediumImageUrl: str | None
    largeImageUrl: str | None
    parsedMechanics: IcaOfferMechanics | None


class IcaOfferDetails(IcaStoreOffer, IcaArticleOffer):
    """Describes everything about an ICA offer"""


class IcaOfferInfo(TypedDict):
    """Describes the basic things about a ICA offer"""

    id: str | None  # "OfferId"
    articleGroupId: int | None
    expandedArticleGroupId: int | None

    # Offer
    name: str | None  # "ArticleName / OfferName"
    brand: str | None
    packageInformation: str | None
    customerInformation: str | None
    condition: str | None
    disclaimer: str | None
    restriction: str | None
    referenceInfo: str | None
    referencePriceText: str | None
    offerPriceText: str | None  # comes from "parsedMechanics"

    ### Conditionals ###
    # isSelfScan: bool | None
    # isPersonal: bool | None
    isUsed: bool | None
    # requiresLoyaltyCard: bool | None
    validFrom: str | None
    validTo: str | None

    ### Products ###
    eans: list[ArticleOfferEanSlim] | None
    stores: list[ArticleOfferStoreSlim] | None

    @classmethod
    def map_from_offer_details(cls, offer: IcaOfferDetails):
        offerPriceText = IcaOfferMechanics.format_to_string(
            offer.get("parsedMechanics", None)
        )
        eans = [
            ArticleOfferEanSlim(
                id=x.get("id"), articleDescription=x.get("articleDescription")
            )
            for x in offer.get("eans", [])
        ]
        stores = [
            ArticleOfferStoreSlim(
                id=x.get("id"),
                referencePriceText=x.get("referencePriceText"),
            )
            for x in offer.get("stores", [])
        ]
        return IcaOfferInfo(
            id=offer.get("id"),
            articleGroupId=offer.get("category", {}).get("articleGroupId", 12),
            expandedArticleGroupId=offer.get("category", {}).get(
                "expandedArticleGroupId", 12
            ),
            name=offer.get("name"),
            brand=offer.get("brand"),
            packageInformation=offer.get("packageInformation"),
            customerInformation=offer.get("customerInformation"),
            condition=offer.get("condition"),
            disclaimer=offer.get("disclaimer"),
            restriction=offer.get("restriction"),
            referenceInfo=offer.get("referenceInfo"),
            referencePriceText=offer.get("referencePriceText"),
            offerPriceText=offerPriceText,
            ### Conditionals ###
            # isSelfScan: bool | None
            # isPersonal: bool | None
            isUsed=offer.get("isUsed"),
            # requiresLoyaltyCard: bool | None
            validFrom=offer.get("validFrom"),
            validTo=offer.get("validTo"),
            ### Products ###
            eans=eans,
            stores=stores,
        )


class IcaProductOffer(TypedDict):
    """An even more minified version of IcaOfferInfo"""

    id: str | None  # Offer Id
    name: str | None  # Offer name
    brand: str | None
    packageInformation: str | None
    priceText: str | None  # comes from "parsedMechanics"
    referencePriceText: str | None
    refrenceInfo: str | None


class IcaProduct(TypedDict):
    ean_id: str  # "eanId / barcode"
    ean_name: str | None  # description of the Ean article
    article: ProductLookup | ArticleInfo | None
    open_food_facts: OpenFoodFactsProduct | None
    offers: dict[str, IcaProductOffer] | None


class IcaBaseItem(TypedDict):
    id: str  # "offlineId"
    text: str  # Freetext or ArticleName
    articleId: int | None
    articleGroupId: int | None
    articleGroupIdExtended: int | None
    articleEan: str | None
    sortOrder: int | None


# obsolete?
class IcaOffer(TypedDict):
    # OfferId: str | None
    id: str | None  # "OfferId"
    StoreId: int | None
    StoreIds: list[int] | None
    ArticleGroupId: int | None
    OfferType: str | None
    ImageUlr: str | None
    PriceComparison: str | None
    SizeOrQuantiry: str | None
    ProductName: str | None
    OfferTypeTitle: str | None
    Disclaimer: str | None
    OfferCondition: str | None
    LoadedOnCard: bool
    OfferUsed: bool
    Expired: bool
    # Articles: list[OfferArticle] | None


class OffersAndDiscountsForStore(TypedDict):
    discounts: list | None
    offers: list[IcaStoreOffer] | None


class IcaShoppingListEntryRecipeRef(TypedDict):
    id: int  # "recipeId"
    quantity: float
    unit: str


class IcaShoppingListEntry(TypedDict):
    id: int | None  # "RowId"
    offlineId: str | None
    productName: str
    quantity: (
        float | None
    )  # the quantity of the item. Can be None if no quantity specified.
    unit: (
        str | None
    )  # the quantity unit, e.g. "kg", "st", "liter" or similar. Not standardized, just what ICA sends and shows in the app. Can be None if no quantity/unit specified.
    recipes: list[IcaShoppingListEntryRecipeRef] | None
    recipeId: str | None
    offerId: str | None
    productEan: str | None
    isStrikedOver: bool  # Whether the item is marked as "bought"
    internalOrder: int | None
    articleGroupId: int | None
    articleGroupIdExtended: int | None
    latestChange: str | None
    sourceId: int | None
    isSmartItem: bool | None


class IcaShoppingList(TypedDict):
    id: int | None
    offlineId: str | None
    title: str | None
    commentText: str | None
    sortingStore: int | None
    rows: list[IcaShoppingListEntry]
    latestChange: str | None
    isPrivate: bool | None
    isSmartList: bool | None


class IcaShoppingListSync(TypedDict):
    offlineId: str  # offlineId of the ShoppingList
    changedShoppingListProperties: dict[str, any] | None
    createdRows: list[IcaShoppingListEntry] | None
    changedRows: list[IcaShoppingListEntry] | None
    deletedRows: list[str] | None  # list of offlineIds


class IcaProductCategory(TypedDict):
    Id: int | None
    Name: str | None
    ParentId: int | None
    LastSyncDate: str | None


class IcaArticle(TypedDict):
    id: int
    name: str
    pluralName: str | None
    parentId: int | None
    parentIdExtended: int | None
    status: int | None
    latestChange: str | None
    maxiFormatCategoryId: str | None
    maxiFormatCategoryName: str | None
    kvantumFormatCategoryId: str | None
    kvantumFormatCategoryName: str | None
    supermarketFormatCategoryId: str | None
    supermarketFormatCategoryName: str | None
    naraFormatCategoryId: str | None
    naraFormatCategoryName: str | None


class IcaCommonArticle(TypedDict):
    Id: int | None
    ProductName: str | None
    ArticleId: int | None
    ArticleGroupId: int | None
    ArticleGroupIdExtended: int | None
    FormatCategoryMaxi: str | None
    FormatCategoryKvantum: str | None
    FormatCategorySuperMarket: str | None
    FormatCategoryNara: str | None


class IcaFavoriteRecipe(TypedDict):
    RecipeId: int | None
    CreationDate: str | None


class IcaIngredient(TypedDict):
    Text: str | None
    IngredientsId: int | None
    Quantity: int | None
    Unit: str | None
    Ingredient: str | None


class IcaIngredientGroup(TypedDict):
    GroupName: str | None
    Ingredients: str | None


class IcaRecipe(TypedDict):
    Id: int | None
    Title: str | None
    ImageId: int | None
    YouTubeId: str | None
    IngredientGroups: list[IcaIngredientGroup]
    PreambleHTML: str | None
    CurrentUserRating: float | None
    AverageRating: float | None
    Difficulty: str | None
    CookingTime: str | None
    Portions: int | None


class ServiceCallResponse(TypedDict, Generic[_DataT]):
    success: bool
    data: _DataT | None = None
