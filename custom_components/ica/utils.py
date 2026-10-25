import datetime as dt
import logging
from typing import Any, TypeVar

_DataT = TypeVar("_DataT", default=dict[Any, Any])


class EmptyLogger(logging.Logger):
    """Acts as an dumb logger that doesn't actually log anything"""

    def __init__(self):
        self.disabled = True


def trim_props(obj: _DataT, predicate=None) -> _DataT:
    if not obj:
        return obj
    predicate = predicate or (lambda k, v: v is not None and v != "")
    return {k: v for k, v in obj.items() if predicate(k, v)}


def to_dict(list_source, key: str = "id"):
    return {value[key]: value for value in list_source} if list_source else {}


def get_diffs(a, b, key: str = "id", include_values: bool = True):
    if isinstance(a, list):
        a = to_dict(a, key)
    if isinstance(b, list):
        b = to_dict(b, key)

    added = b.keys() - a.keys()
    removed = a.keys() - b.keys()
    diffs = [{"op": "+", key: row_id, "new": b[row_id]} for row_id in added]
    diffs.extend([{"op": "-", key: row_id, "old": a[row_id]} for row_id in removed])

    a_set = set(a)
    b_set = set(b)
    remaining = a_set.intersection(b_set)

    for row_id in remaining:
        old = a[row_id]
        new = b[row_id]
        props = []
        for k in new:
            d = new.get(k, None) != old.get(k, None)
            # todo: ignore changes in ordering when list. ICA quite oftenly change or send inconsistent sorting in the Ean-property
            if d:
                props.append(k)
        if props:
            if include_values:
                o = {value: old.get(value, None) for value in props}
                n = {value: new.get(value, None) for value in props}
                diffs.append(
                    {"op": "~", key: row_id, "changed_props": props, "old": o, "new": n}
                )
            else:
                diffs.append({"op": "~", key: row_id, "changed_props": props})
    return diffs


def get_diff_obj(old: dict, new: dict, key: str = "id", include_values: bool = True):
    added = not bool(old) and bool(new)
    removed = bool(old) and not bool(new)
    old = old or {}
    new = new or {}
    row_id = new.get(key) or old.get(key)
    if added:
        return {"op": "+", key: row_id, "new": new}
    if removed:
        return {"op": "-", key: row_id, "old": old}

    props = []
    for k in [*old, *new]:
        d = new.get(k, None) != old.get(k, None)
        # todo: ignore changes in ordering when list. ICA quite oftenly change or send inconsistent sorting in the Ean-property
        if d and k not in props:
            props.append(k)

    if props:
        if include_values:
            o = {value: old.get(value, None) for value in props}
            n = {value: new.get(value, None) for value in props}
            return {"op": "~", key: row_id, "changed_props": props, "old": o, "new": n}
        else:
            return {"op": "~", key: row_id, "changed_props": props}
    return None


def index_of(source: list[dict], key, value) -> int:
    """Return the index of the item with the given KeyValue pairing or -1 if not found."""
    return next(
        (index for index, item in enumerate(source) if item.get(key) == value),
        -1,
    )


def try_parse_int(value: Any) -> tuple[bool, int]:
    """Try parsing a value as int. Return as a tuple."""
    try:
        return (True, int(value))
    except ValueError:
        return (False, 0)


# ---------------------------------------------------------------------------
# Product name normalization for plural matching
# ---------------------------------------------------------------------------


def normalize_product_name(name: str | None) -> str:
    """Normalize a product name for fuzzy matching, handling Swedish and English plurals.

    This function strips common plural suffixes to allow matching between
    singular and plural forms (e.g., "Tomat" ↔ "Tomater", "Apple" ↔ "Apples").

    Swedish plural patterns (ordered by specificity):
      - erna, orna, arna  → remove 4 chars  (pojkarna → pojk)
      - or, ar, er        → remove 2 chars  (tomater → tomat)
      - et, en            → remove 2 chars  (äpplet → äpple, barnen → barn)
      - n after vowel     → remove 1 char   (äpplen → äpple)

    English plural patterns:
      - ies  → replace with 'y'  (berries → berry)
      - es   → remove 2 chars    (boxes → box, tomatoes → tomato)
      - s    → remove 1 char     (apples → apple)

    The function is conservative: it only strips suffixes when the remaining
    stem is at least 3 characters to avoid over-aggressive matching.

    Parameters
    ----------
    name : The product name to normalize.

    Returns
    -------
    The normalized (singular-like) form, lowercased and stripped.
    """
    if not name:
        return ""

    normalized = name.strip().lower()
    if len(normalized) < 4:
        return normalized  # Too short to safely normalize

    # Swedish: longer suffixes first (to avoid partial matches)
    if len(normalized) >= 6:
        for suffix in ("erna", "orna", "arna"):
            if normalized.endswith(suffix):
                stem = normalized[: -len(suffix)]
                if len(stem) >= 3:
                    if suffix == "orna":
                        # kakorna -> kaka, flickorna -> flicka
                        return stem + "a"
                    return stem

    # Swedish: -ena definite plural (äpplena -> äpplen -> äpple)
    if len(normalized) >= 6 and normalized.endswith("ena"):
        stem = normalized[:-1]  # drop only the trailing 'a'
        if len(stem) >= 3:
            if stem.endswith("n") and stem[-2] in "aeiouyåäö":
                final_stem = stem[:-1]
                if len(final_stem) >= 3:
                    return final_stem
            return stem

    # Swedish: umlaut plural -ötter (morötter -> morot, fötter -> fot)
    if len(normalized) >= 6 and normalized.endswith("ötter"):
        stem = normalized[:-5]
        if len(stem) >= 1:
            return f"{stem}ot"

    # Swedish: or, ar, er (plural endings)
    if len(normalized) >= 5:
        for suffix in ("or", "ar", "er"):
            if normalized.endswith(suffix):
                stem = normalized[:-2]
                if len(stem) >= 3:
                    # kakor -> kaka, gurkor -> gurka
                    if suffix == "or" and stem[-1] not in "aeiouyåäö":
                        return stem + "a"
                    return stem

    # NOTE: We do not strip trailing 'a' in general, to avoid turning
    # singular nouns like "gurka" into "gurk".

    # Swedish: et, en (definite forms: äpplet → äpple, barnen → barn)
    # Check these before "n after vowel" to avoid false matches on "en" suffix
    if len(normalized) >= 5:
        if normalized.endswith("et"):
            stem = normalized[:-2]
            if len(stem) >= 3:
                # If stem ends with consonant + "l", add back "e" (äppl → äpple)
                if stem[-1] == "l" and len(stem) >= 2 and stem[-2] not in "aeiouyåäö":
                    return stem + "e"
                return stem
        if normalized.endswith("en"):
            stem = normalized[:-2]
            if len(stem) >= 3:
                # If stem ends with consonant + "l", add back "e" (äppl → äpple)
                if stem[-1] == "l" and len(stem) >= 2 and stem[-2] not in "aeiouyåäö":
                    return stem + "e"
                return stem

    # Swedish: n after vowel (äpplen → äpple)
    if (
        len(normalized) >= 5
        and normalized.endswith("n")
        and normalized[-2] in "aeiouyåäö"
    ):
        stem = normalized[:-1]
        if len(stem) >= 3:
            return stem

    # English: ies → y (berries → berry)
    if len(normalized) >= 5 and normalized.endswith("ies"):
        stem = normalized[:-3] + "y"
        if len(stem) >= 3:
            return stem

    # English: s vs es disambiguation
    # For words ending in 's', determine whether to strip 's' or 'es'
    if len(normalized) >= 4 and normalized.endswith("s"):
        # "ananas" is singular even though it ends with 's' (but "bananas" is plural)
        if normalized.split()[-1] == "ananas":
            return normalized
        # First try removing just 's'
        stem_s = normalized[:-1]

        # If ends in 'es', might need to remove 'es' instead of just 's'
        if len(normalized) >= 5 and normalized.endswith("es"):
            stem_es = normalized[:-2]
            # Remove 'es' for words ending in x, z, s, o
            # (boxes → box, buzzes → buzz, tomatoes → tomato)
            # For other 'es' endings, prefer removing just 's' (apples → apple)
            if len(stem_es) >= 3 and stem_es[-1] in "xzso":
                return stem_es

        # Remove just 's' if it produces a valid stem
        if len(stem_s) >= 3 and not stem_s.endswith("s"):
            return stem_s

    return normalized


def product_names_match(name_a: str | None, name_b: str | None) -> bool:
    """Check if two product names match, accounting for pluralization.

    Returns ``True`` if the normalized forms are identical.
    """
    return normalize_product_name(name_a) == normalize_product_name(name_b)


# ---------------------------------------------------------------------------
# Unit conversion system
# Supported units: L, dl, cl, ml, krm, tsk, msk, kg, g, st, förp
# ---------------------------------------------------------------------------

# The default unit when none is specified — treated as "pieces" (styck).
DEFAULT_UNIT = "st"

# Volume – conversion factors to the base unit (ml)
_VOLUME_TO_ML: dict[str, float] = {
    "l": 1000.0,  # liter
    "dl": 100.0,  # deciliter
    "cl": 10.0,  # centiliter
    "ml": 1.0,  # milliliter
    "krm": 1.0,  # kryddmått  ≈ 1 ml  (a pinch)
    "tsk": 5.0,  # tesked            (teaspoon)
    "msk": 15.0,  # matsked           (tablespoon)
}

# Weight – conversion factors to the base unit (g)
_WEIGHT_TO_G: dict[str, float] = {
    "kg": 1000.0,
    "g": 1.0,
}

# Count units – each is its own isolated group (not inter-convertible).
# 'st'   = styck        (pieces)
# 'förp' = förpackning  (packs)
_COUNT_UNITS: set[str] = {"st", "förp"}

# Grouped table look-ups
_UNIT_GROUPS: dict[str, dict[str, float]] = {
    "volume": _VOLUME_TO_ML,
    "weight": _WEIGHT_TO_G,
}


def _normalize_unit(unit: str | None) -> str | None:
    """Lowercase / strip a unit string for comparison."""
    if unit is None:
        return None
    return unit.strip().lower()


def _effective_unit(unit: str | None) -> str:
    """Return *unit* if defined, otherwise fall back to ``DEFAULT_UNIT``."""
    return unit if unit is not None else DEFAULT_UNIT


def get_unit_group(unit: str | None) -> tuple[str | None, dict[str, float] | None]:
    """Return ``(group_name, conversion_table)`` for *unit*.

    Count units each get their own group (``"count:st"``, ``"count:förp"``)
    so that ``st`` and ``förp`` are **not** treated as inter-convertible.

    Returns ``(None, None)`` for unrecognised units.
    """
    norm = _normalize_unit(unit)
    if norm is None:
        return (None, None)
    for group_name, table in _UNIT_GROUPS.items():
        if norm in table:
            return (group_name, table)
    if norm in _COUNT_UNITS:
        return (f"count:{norm}", {norm: 1.0})
    return (None, None)


def are_units_compatible(unit_a: str | None, unit_b: str | None) -> bool:
    """Return ``True`` if two units can be converted between each other."""
    norm_a = _normalize_unit(unit_a)
    norm_b = _normalize_unit(unit_b)
    if norm_a is None and norm_b is None:
        return True
    if norm_a is None or norm_b is None:
        return False
    if norm_a == norm_b:
        return True
    group_a, _ = get_unit_group(unit_a)
    group_b, _ = get_unit_group(unit_b)
    return group_a is not None and group_a == group_b


def convert_quantity(quantity: float, from_unit: str, to_unit: str) -> float | None:
    """Convert *quantity* from *from_unit* to *to_unit*.

    Returns ``None`` when the units are incompatible.
    Conversions are rounded to 4 decimal places to avoid floating-point noise.
    """
    from_norm = _normalize_unit(from_unit)
    to_norm = _normalize_unit(to_unit)
    if from_norm is None or to_norm is None:
        return None
    if from_norm == to_norm:
        return quantity

    from_group, from_table = get_unit_group(from_unit)
    to_group, to_table = get_unit_group(to_unit)
    if from_group is None or to_group is None or from_group != to_group:
        return None

    base_value = quantity * from_table[from_norm]
    return round(base_value / to_table[to_norm], 4)


def _add_quantities(
    qty_a: float, unit_a: str, qty_b: float, unit_b: str
) -> tuple[float, str] | None:
    """Add two (quantity, unit) pairs. Returns ``(sum, target_unit)`` or ``None`` if incompatible."""
    converted = convert_quantity(qty_b, unit_b, unit_a)
    if converted is None:
        return None
    return (round(qty_a + converted, 4), unit_a)


# ---------------------------------------------------------------------------
# Merging IcaShoppingListEntry dicts
# ---------------------------------------------------------------------------


def _merge_recipe_refs(
    base_recipes: list[dict] | None,
    other_recipes: list[dict] | None,
) -> list[dict] | None:
    """Merge two recipe-reference lists.

    * Quantities for the same recipe ID are summed (with unit conversion).
    * Non-overlapping recipe references are kept as-is.
    * Returns ``None`` when both inputs are empty/``None``.
    """
    if not base_recipes and not other_recipes:
        return None
    if not other_recipes:
        return [dict(r) for r in base_recipes] if base_recipes else None
    if not base_recipes:
        return [dict(r) for r in other_recipes]

    merged: dict[int, dict] = {}
    for ref in base_recipes:
        merged[ref.get("id")] = dict(ref)

    for ref in other_recipes:
        rid = ref.get("id")
        if rid not in merged:
            merged[rid] = dict(ref)
            continue

        existing = merged[rid]
        existing_qty = existing.get("quantity", 0) or 0
        other_qty = ref.get("quantity", 0) or 0
        existing_unit = _effective_unit(existing.get("unit"))
        other_unit = _effective_unit(ref.get("unit"))

        added = _add_quantities(existing_qty, existing_unit, other_qty, other_unit)
        if added is not None:
            existing["quantity"] = added[0]
            existing["unit"] = added[1]
        # else: incompatible units for same recipe – keep existing as-is
        # TODO: Add as separate entry instead?

    return list(merged.values())


def merge_shopping_list_entries(base: dict, other: dict) -> dict:
    """Merge two ``IcaShoppingListEntry`` dicts into a new dict.

    *base* is the primary (existing) entry; *other* is merged **into** it.

    Merging behaviour
    -----------------
    **quantity / unit**
      Quantities are summed when the units are compatible.  A missing unit
      is treated as ``"st"`` (pieces) so that ``None``-unit entries are never
      silently mixed with volume or weight entries.

    **recipes**
      Recipe reference lists are combined.  Quantities for the same
      ``recipeId`` are added together (with unit conversion when needed).

    **other fields**
      Nullable metadata (``productEan``, ``articleGroupId``, …) is carried
      over from *other* only when *base* has ``None``.

    Neither input dict is mutated.
    """
    result = dict(base)

    base_qty: float | None = base.get("quantity")
    other_qty: float | None = other.get("quantity")

    # --- Merge quantity & unit ---
    if base_qty is None and other_qty is not None and other.get("unit"):
        # Only *other* has an explicit amount (e.g. "500 g") – adopt it wholesale
        result["quantity"] = other_qty
        result["unit"] = _effective_unit(other.get("unit"))
    else:
        # A missing quantity implies "1 piece", so adding "Salt" twice gives 2 st
        base_qty = 1 if base_qty is None else base_qty
        other_qty = 1 if other_qty is None else other_qty
        base_unit = _effective_unit(base.get("unit"))
        other_unit = _effective_unit(other.get("unit"))

        added = _add_quantities(base_qty, base_unit, other_qty, other_unit)
        if added is not None:
            result["quantity"] = added[0]
            result["unit"] = added[1]
        else:
            # Incompatible units – keep base values, but materialise the defaults
            result["quantity"] = base_qty
            result["unit"] = base_unit

    # --- Merge recipe references ---
    merged_recipes = _merge_recipe_refs(base.get("recipes"), other.get("recipes"))
    if merged_recipes is not None:
        result["recipes"] = merged_recipes

    # --- Carry over nullable metadata from *other* where *base* is None ---
    for field in ("productEan", "articleGroupId", "articleGroupIdExtended", "offerId"):
        if result.get(field) is None and other.get(field) is not None:
            result[field] = other[field]

    return result


def resolve_list_entity_ids(
    registry_entries, config_entry_id: str, offline_ids
) -> dict[str, str]:
    """Map shopping list offline IDs to todo entity IDs.

    `registry_entries` is an iterable of `(unique_id, entity_id)` tuples. Matching is
    case-insensitive since ICA returns offline IDs in upper case. Offline IDs without
    a registered entity are omitted.
    """
    prefix = f"{config_entry_id}-"
    by_offline_id = {
        unique_id[len(prefix) :].casefold(): entity_id
        for unique_id, entity_id in registry_entries
        if unique_id.startswith(prefix)
    }
    return {
        offline_id: by_offline_id[offline_id.casefold()]
        for offline_id in offline_ids
        if offline_id.casefold() in by_offline_id
    }


def build_lists_changed_event(
    config_entry_id: str,
    created: list[str] | None = None,
    deleted: list[str] | None = None,
    entities: dict[str, str] | None = None,
) -> dict:
    """Payload for the `ica_lists_changed` event."""
    return {
        "config_entry_id": config_entry_id,
        "created": list(created or []),
        "deleted": list(deleted or []),
        "entities": dict(entities or {}),
    }


def diff_list_rows(old_rows, new_rows) -> dict[str, list]:
    """Compare shopping list rows by `offlineId` (case-insensitive).

    Returns `added`, `removed`, `changed`, `completed` and `reopened`. Each
    entry is `{uid, summary, item}` with `item` the full row (the new version,
    or the old one when removed). `changed` also has `changed_props`.
    `completed`/`reopened` are the rows whose `isStrikedOver` flipped; they are
    also in `changed`. Empty when nothing differs.
    """

    def index(rows):
        return {
            str(r["offlineId"]).casefold(): r for r in rows or [] if r.get("offlineId")
        }

    def entry(row, **extra):
        return {
            "uid": row["offlineId"],
            "summary": row.get("productName"),
            **extra,
            "item": {k: v for k, v in row.items() if k != "offer"},
        }

    old, new = index(old_rows), index(new_rows)
    result: dict[str, list] = {
        "added": [entry(row) for uid, row in new.items() if uid not in old],
        "removed": [entry(row) for uid, row in old.items() if uid not in new],
        "changed": [],
        "completed": [],
        "reopened": [],
    }
    for uid, row in new.items():
        if uid not in old:
            continue
        before = old[uid]
        # `offer` is added by the todo entity, `latestChange` changes on every sync
        props = [
            k
            for k in row
            if k not in ("latestChange", "offer") and row.get(k) != before.get(k)
        ]
        if not props:
            continue
        result["changed"].append(entry(row, changed_props=props))
        if row.get("isStrikedOver") and not before.get("isStrikedOver"):
            result["completed"].append(entry(row))
        elif before.get("isStrikedOver") and not row.get("isStrikedOver"):
            result["reopened"].append(entry(row))
    return result


def match_offers_to_baseitems(
    offers: list[dict] | None, baseitems: list[dict] | None
) -> list[dict]:
    """Return the offers that match any of the favorite items (baseitems).

    A favorite with an EAN matches offers that include that EAN (ignoring
    leading zeros). A favorite without an EAN matches on its name against the
    offer name or the article names of the offer, accounting for plurals.
    """
    eans: set[str] = set()
    names: set[str] = set()
    for item in baseitems or []:
        if ean := item.get("articleEan"):
            eans.add(str(ean).lstrip("0"))
        elif text := item.get("text"):
            names.add(normalize_product_name(text))
    eans.discard("")
    names.discard("")
    if not eans and not names:
        return []

    def is_match(offer: dict) -> bool:
        for ean in offer.get("eans") or []:
            if str(ean.get("id") or "").lstrip("0") in eans:
                return True
            if normalize_product_name(ean.get("articleDescription")) in names:
                return True
        return normalize_product_name(offer.get("name")) in names

    return [offer for offer in offers or [] if is_match(offer)]


def is_offer_valid(offer: dict, now: dt.datetime, default_tz: dt.tzinfo) -> bool:
    """Whether the offer is valid at `now` (timezone aware).

    Offer timestamps without an offset are read in `default_tz`.
    """
    valid_from = parse_aware_datetime(offer.get("validFrom"), default_tz)
    valid_to = parse_aware_datetime(offer.get("validTo"), default_tz)
    started = valid_from is None or valid_from <= now
    ended = valid_to is not None and valid_to < now
    return started and not ended


def utc_timestamp(now: dt.datetime | None = None) -> str:
    """ICA style UTC timestamp, e.g. '2024-03-10T12:00:00Z'."""
    now = now or dt.datetime.now(dt.UTC)
    return now.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_aware_datetime(
    value: str | None, default_tz: dt.tzinfo = dt.UTC
) -> dt.datetime | None:
    """Parse an ISO timestamp, assuming `default_tz` when it has no offset."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=default_tz)
