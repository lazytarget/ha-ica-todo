"""Client for looking up products in Open Food Facts."""

import logging

from aiohttp import ClientSession

from .const import OpenFoodFacts
from .icatypes import OpenFoodFactsProduct

_LOGGER = logging.getLogger(__name__)


async def async_get_product(
    session: ClientSession,
    code: str,
    fields: list[str] | None = None,
    raise_if_invalid: bool = False,
) -> OpenFoodFactsProduct | None:
    """Return a product, or None if it does not exist.

    :param code: barcode of the product
    :param fields: a list of fields to return. If None, the default fields are returned.
    :param raise_if_invalid: if True, a ValueError is raised if the barcode is invalid.
    """
    if not code or not isinstance(code, str):
        raise ValueError("code must be a non-empty string")
    url = OpenFoodFacts.APIv2.format(code)
    if fields := fields or OpenFoodFacts.DEFAULT_FIELDS:
        # The openfoodfacts server does not recognize escaped commas, see
        # https://github.com/openfoodfacts/openfoodfacts-server/issues/1607
        url += f"?fields={','.join(fields)}"

    async with session.get(
        url, headers={"User-Agent": "ha-ica-todo"}, timeout=10
    ) as response:
        if response.status == 404 and not raise_if_invalid:
            return None
        if not response.ok:
            _LOGGER.warning(
                "Error getting info from OpenFoodFacts. HTTP [GET] %s -> %s: %s",
                url,
                response.status,
                (await response.text())[:500],
            )
        response.raise_for_status()
        resp = await response.json()

    if resp is None:
        return None
    if resp.get("status") is None:
        raise ValueError(f"Unexpected response from OpenFoodFacts for '{code}'")
    if resp["status"] == 0:
        # invalid barcode
        if raise_if_invalid:
            raise ValueError(f"invalid barcode: {code}")
        return None

    p = resp.get("product") or {}
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
