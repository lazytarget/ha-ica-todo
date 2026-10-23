"""A todo platform for ICA shopping lists."""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
import voluptuous as vol
from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_JSON_DATA_IN_DESC,
    CONFLICT_MODES,
    DEFAULT_ARTICLE_GROUP_ID,
    DOMAIN,
    ConflictMode,
    IcaServices,
)
from .coordinator import IcaCoordinator
from .icatypes import (
    IcaShoppingList,
    IcaShoppingListEntry,
    IcaShoppingListSync,
    ServiceCallResponse,
)
from .utils import (
    index_of,
    merge_shopping_list_entries,
    parse_aware_datetime,
    product_names_match,
    utc_timestamp,
)

if TYPE_CHECKING:
    from . import IcaConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IcaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ICA shopping list platform config entry."""
    coordinator = entry.runtime_data
    shopping_lists: list[IcaShoppingList] = await coordinator.async_get_shopping_lists()
    async_add_entities(
        [
            IcaBaseItemListEntity(coordinator, entry),
            *(
                IcaShoppingListEntity(
                    coordinator,
                    entry,
                    shopping_list["offlineId"],
                    shopping_list["title"],
                )
                for shopping_list in shopping_lists
            ),
        ]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        IcaServices.ADD_OFFERS_TO_SHOPPING_LIST,
        {
            vol.Required("offer_ids"): vol.All(cv.ensure_list, [str]),
            vol.Optional("conflict_mode"): vol.In(CONFLICT_MODES),
        },
        _handle_add_offers_to_shopping_list,
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        IcaServices.UPSERT_SHOPPING_LIST,
        {
            vol.Required("rows"): vol.All(cv.ensure_list, [str]),
            vol.Optional("conflict_mode"): vol.In(CONFLICT_MODES),
        },
        _handle_upsert_shopping_list,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _ensure_shopping_list(entity) -> IcaShoppingListEntity:
    if not isinstance(entity, IcaShoppingListEntity):
        raise ServiceValidationError(
            f"'{entity.entity_id}' is not an ICA shopping list"
        )
    return entity


async def _handle_add_offers_to_shopping_list(
    entity, call: ServiceCall
) -> ServiceCallResponse[IcaShoppingList]:
    """Add existing offers to an ICA shopping list."""
    entity = _ensure_shopping_list(entity)
    coordinator = entity.coordinator
    created_rows = []
    conflict_mode = call.data.get("conflict_mode", ConflictMode.APPEND)
    for offer_id in call.data["offer_ids"]:
        if not offer_id or ("," in offer_id):
            _LOGGER.warning("Invalid `offer_id` passed: %s", offer_id)
            continue
        offer = coordinator.get_offer_info(offer_id)
        if not offer:
            _LOGGER.warning("Offer not found: %s", offer_id)
            continue
        cat = offer.get("category", {})
        eans = offer.get("eans") or []
        created_rows.append(
            IcaShoppingListEntry(
                internalOrder=999,
                productName=offer["name"],
                isStrikedOver=False,
                sourceId=-1,
                articleGroupId=cat.get("articleGroupId", DEFAULT_ARTICLE_GROUP_ID),
                articleGroupIdExtended=cat.get(
                    "expandedArticleGroupId", DEFAULT_ARTICLE_GROUP_ID
                ),
                offerId=offer_id,
                latestChange=utc_timestamp(),
                # With several EANs it's unknown which product is wanted
                productEan=eans[0].get("id") if len(eans) == 1 else None,
                offlineId=str(uuid.uuid4()),
            )
        )

    if not created_rows:
        return ServiceCallResponse[IcaShoppingList](success=False, data=None)
    updated_list = await entity.async_create_shopping_list_items(
        created_rows, conflict_mode=conflict_mode
    )
    return ServiceCallResponse[IcaShoppingList](success=True, data=updated_list)


async def _handle_upsert_shopping_list(
    entity, call: ServiceCall
) -> ServiceCallResponse[IcaShoppingList]:
    """Add or update rows in an ICA shopping list."""
    entity = _ensure_shopping_list(entity)
    rows = call.data["rows"]
    conflict_mode = call.data.get("conflict_mode", ConflictMode.APPEND)
    if not rows:
        return ServiceCallResponse[IcaShoppingList](success=False, data=None)

    sync = await entity.async_generate_sync_request(rows, conflict_mode=conflict_mode)
    if sync is None:
        # Nothing to change, e.g. all rows were ignored due to the conflict mode
        return ServiceCallResponse[IcaShoppingList](
            success=True, data=entity.coordinator.get_shopping_list(entity.offline_id)
        )
    updated_list = await entity.coordinator.sync_shopping_list(
        sync, conflict_mode=conflict_mode
    )
    return ServiceCallResponse[IcaShoppingList](success=True, data=updated_list)


class IcaEntity(CoordinatorEntity[IcaCoordinator]):
    """Base class for ICA entities, grouped under one device per account."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IcaCoordinator, config_entry: IcaConfigEntry):
        super().__init__(coordinator=coordinator)
        self._config_entry = config_entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name="ICA",
            manufacturer="ICA",
            model="ICA account",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _json_data_in_description(self) -> bool:
        return bool(self._config_entry.options.get(CONF_JSON_DATA_IN_DESC, False))

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass update state from existing coordinator data."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()


class IcaShoppingListEntity(IcaEntity, TodoListEntity):
    """A ICA shopping list TodoListEntity."""

    _attr_icon = "mdi:cart"

    def __init__(
        self,
        coordinator: IcaCoordinator,
        config_entry: IcaConfigEntry,
        shopping_list_id: str,
        shopping_list_name: str,
    ) -> None:
        """Initialize IcaShoppingListEntity."""
        super().__init__(coordinator, config_entry)
        self._attr_supported_features = (
            TodoListEntityFeature.CREATE_TODO_ITEM
            | TodoListEntityFeature.UPDATE_TODO_ITEM
            | TodoListEntityFeature.DELETE_TODO_ITEM
        )
        if self._json_data_in_description:
            self._attr_supported_features |= (
                TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
            )
        self.offline_id = shopping_list_id
        self._attr_unique_id = f"{config_entry.entry_id}-{shopping_list_id}"
        self._attr_name = shopping_list_name
        self._attr_todo_items: list[TodoItem] | None = None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Identity of the ICA list behind this entity."""
        shopping_list = self.coordinator.get_shopping_list(self.offline_id)
        return {
            "offline_id": self.offline_id,
            "config_entry_id": self._config_entry.entry_id,
            "comment": (shopping_list or {}).get("commentText"),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        items = []
        if shopping_list := self.coordinator.get_shopping_list(self.offline_id):
            for row in shopping_list["rows"]:
                # Don't modify the cached row, it is persisted as-is
                task = dict(row)
                if task.get("offerId") and (
                    offer := self.coordinator.get_offer_info(task["offerId"])
                ):
                    task["offer"] = offer
                    task["due"] = offer.get("validTo")
                items.append(
                    TodoItem(
                        summary=self._display_summary(task),
                        uid=task["offlineId"],
                        status=TodoItemStatus.COMPLETED
                        if task.get("isStrikedOver")
                        else TodoItemStatus.NEEDS_ACTION,
                        description=self.generate_item_description(task)
                        if self._json_data_in_description
                        else None,
                        due=parse_aware_datetime(
                            task.get("due"), dt_util.get_default_time_zone()
                        ),
                    )
                )
        self._attr_todo_items = items
        super()._handle_coordinator_update()

    def _display_summary(self, task) -> str:
        """'2 st Gurka' style summary, so the quantity from ICA is visible in HA."""
        name = task.get("productName") or ""
        quantity = task.get("quantity")
        if not quantity:
            return name
        parts = [
            self.coordinator.format_quantity(quantity),
            task.get("unit") or "",
            name,
        ]
        return " ".join(p for p in parts if p)

    @staticmethod
    def generate_item_description(item: dict) -> str | None:
        if not item:
            return None
        keys = (
            "quantity",
            "unit",
            "articleGroupId",
            "offerId",
            "due",
            "sourceId",
            "productEan",
            "recipes",
        )
        result = {key: item[key] for key in keys if item.get(key)}
        return json.dumps(result) if result else None

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a To-do item."""
        ti = self.coordinator.parse_summary(item.summary)
        ti.pop("summary", None)
        ti["sourceId"] = -1
        ti["isStrikedOver"] = False
        ti["offlineId"] = str(uuid.uuid4())
        await self.async_create_shopping_list_items([IcaShoppingListEntry(ti)])

    async def async_create_shopping_list_items(
        self,
        items: list[IcaShoppingListEntry],
        conflict_mode: ConflictMode = ConflictMode.APPEND,
    ) -> IcaShoppingList:
        """A non HA-native function that batches together mutiple item creations"""
        sync = IcaShoppingListSync(offlineId=self.offline_id, createdRows=items)
        return await self.coordinator.sync_shopping_list(
            sync, conflict_mode=conflict_mode
        )

    async def async_generate_sync_request(
        self, rows: list[str], conflict_mode: ConflictMode
    ) -> IcaShoppingListSync | None:
        """Generates a sync request for updates to a shopping list.

        Returns None when there is nothing to change.
        """
        persisted_list = self.coordinator.get_shopping_list(self.offline_id)
        if not persisted_list:
            raise ServiceValidationError(
                f"Shopping list '{self.entity_id}' has not been loaded"
            )

        # Sort by 'latestChange' to find the most recent match in case of multiple matches
        persisted_rows = sorted(
            persisted_list.get("rows") or [],
            key=lambda r: r.get("latestChange", ""),
            reverse=True,
        )
        sync = IcaShoppingListSync(offlineId=self.offline_id)

        for row_input in rows:
            row = self._parse_row_input(row_input)

            persisted_row: IcaShoppingListEntry | None = None
            if conflict_mode == ConflictMode.APPEND:
                # In APPEND-mode, we overwrite any previous 'offlineId'
                row["offlineId"] = str(uuid.uuid4())
            else:
                persisted_row = self._find_matching_row(row, persisted_rows)
                if persisted_row and conflict_mode == ConflictMode.MERGE:
                    row = merge_shopping_list_entries(base=persisted_row, other=row)
                    # Assign 'offlineId' on the row that is to be updated
                    row["offlineId"] = persisted_row["offlineId"]

            row["latestChange"] = utc_timestamp()
            if persisted_row is None:
                # Easier traceability if the 'offlineId' is created here and not by ICA
                row["offlineId"] = row.get("offlineId") or str(uuid.uuid4())
                sync.setdefault("createdRows", []).append(row)
            elif conflict_mode == ConflictMode.IGNORE:
                _LOGGER.debug(
                    "Ignored update due to conflict mode 'ignore'. New: %s. Persisted: %s",
                    row,
                    persisted_row,
                )
            else:
                sync.setdefault("changedRows", []).append(row)

        if not sync.get("createdRows") and not sync.get("changedRows"):
            _LOGGER.debug("No changes detected, skipping sync")
            return None

        _LOGGER.debug("Built sync: %s", sync)
        return sync

    def _parse_row_input(self, row_input: str) -> IcaShoppingListEntry:
        """A row is either a JSON object or text like '2 st Gurka'."""
        try:
            row = json.loads(row_input, strict=False)
        except ValueError:
            row = None
        if isinstance(row, dict):
            return row

        row = self.coordinator.parse_summary(row_input)
        row.pop("summary", None)
        # Do like ICA, and assume "st" as default unit
        row.setdefault("unit", "st")
        return row

    @staticmethod
    def _find_matching_row(
        row: IcaShoppingListEntry, persisted_rows: list[IcaShoppingListEntry]
    ) -> IcaShoppingListEntry | None:
        """Match on 'offlineId' if present, otherwise on the (singular) 'productName'."""
        if offline_id := row.get("offlineId"):
            offline_id = str(offline_id).casefold()
            if match := next(
                (
                    r
                    for r in persisted_rows
                    if str(r.get("offlineId", "")).casefold() == offline_id
                ),
                None,
            ):
                return match

        if product_name := row.get("productName"):
            return next(
                (
                    r
                    for r in persisted_rows
                    if product_names_match(r.get("productName"), product_name)
                ),
                None,
            )
        return None

    def _changed_row(self, item: TodoItem) -> IcaShoppingListEntry:
        """Build a changed row; the summary shown in HA includes quantity/unit, so parse it back."""
        ti = self.coordinator.parse_summary(item.summary)
        return IcaShoppingListEntry(
            offlineId=item.uid,
            isStrikedOver=item.status == TodoItemStatus.COMPLETED,
            productName=ti["productName"],
            # Always send quantity/unit so a rename can also clear them
            quantity=ti.get("quantity"),
            unit=ti.get("unit"),
            latestChange=utc_timestamp(),
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a To-do item."""
        sync = IcaShoppingListSync(
            offlineId=self.offline_id, changedRows=[self._changed_row(item)]
        )
        await self.coordinator.sync_shopping_list(sync)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete a To-do item."""
        sync = IcaShoppingListSync(offlineId=self.offline_id, deletedRows=uids)
        await self.coordinator.sync_shopping_list(sync)


class IcaBaseItemListEntity(IcaEntity, TodoListEntity):
    """A list of Favorite Items in the ICA account."""

    _attr_icon = "mdi:cart"
    _attr_translation_key = "baseitems"

    def __init__(
        self, coordinator: IcaCoordinator, config_entry: IcaConfigEntry
    ) -> None:
        """Initialize IcaBaseItemListEntity."""
        super().__init__(coordinator, config_entry)
        self._attr_supported_features = (
            TodoListEntityFeature.CREATE_TODO_ITEM
            | TodoListEntityFeature.UPDATE_TODO_ITEM
            | TodoListEntityFeature.DELETE_TODO_ITEM
        )
        if self._json_data_in_description:
            self._attr_supported_features |= (
                TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
            )
        self._attr_unique_id = f"{config_entry.entry_id}-baseitems"
        self._attr_todo_items: list[TodoItem] | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_todo_items = [
            TodoItem(
                summary=baseitem["text"],
                uid=baseitem["id"],
                status=TodoItemStatus.NEEDS_ACTION,
                description=(
                    baseitem.get("articleEan")
                    if self._json_data_in_description
                    else None
                ),
            )
            for baseitem in self.coordinator.get_baseitems()
        ]
        super()._handle_coordinator_update()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a To-do item."""
        await self.coordinator.async_lookup_and_add_baseitem(item.summary)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a To-do item."""
        if item.status == TodoItemStatus.COMPLETED:
            # Completed items are to be removed directly
            await self.async_delete_todo_items([item.uid])
            return

        sync = [dict(x) for x in self.coordinator.get_baseitems()]
        index = index_of(sync, "id", item.uid)
        if index < 0:
            raise ServiceValidationError(f"Favorite item '{item.uid}' was not found")

        current = sync[index]
        changed = False
        if item.summary and current.get("text") != item.summary:
            current["text"] = item.summary
            changed = True
        if item.description and current.get("articleEan") != item.description:
            current["articleEan"] = item.description
            changed = True
        if changed:
            await self.coordinator.sync_baseitems(sync)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete a To-do item."""
        sync = [x for x in self.coordinator.get_baseitems() if x["id"] not in uids]
        if len(sync) != len(self.coordinator.get_baseitems()):
            await self.coordinator.sync_baseitems(sync)
