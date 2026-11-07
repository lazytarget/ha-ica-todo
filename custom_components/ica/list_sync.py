"""One-way sync of another to-do list (e.g. Mealie) into an ICA shopping list.

Every open item in the source list gets its own row in the ICA list. When the
item is checked off or deleted in the source, that row is deleted from ICA.
Rows added in ICA by other means are never touched, and a synced row that was
deleted in ICA is not added again while the source item stays open.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store

from .const import (
    CONF_LIST_SYNC_SOURCE,
    CONF_LIST_SYNC_TARGET,
    CONF_LIST_SYNCS,
    DOMAIN,
    entry_cache_key,
)
from .icatypes import IcaShoppingList, IcaShoppingListEntry, IcaShoppingListSync
from .utils import utc_timestamp

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import IcaCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Changes in the source often come in bursts, e.g. a whole recipe at once
SYNC_COOLDOWN_SECONDS = 2


class SyncedItem(TypedDict):
    row_id: str  # offlineId of the ICA row that was created for the source item
    summary: str  # The source summary the row was last synced from


class ListSyncPair(TypedDict):
    source_entity_id: str
    target_list_id: str  # offlineId of the ICA list


def pair_key(pair: ListSyncPair) -> str:
    # ICA returns offlineId in upper case - compare case-insensitively
    return f"{pair[CONF_LIST_SYNC_SOURCE]}|{str(pair[CONF_LIST_SYNC_TARGET]).lower()}"


def configured_pairs(entry: ConfigEntry) -> list[ListSyncPair]:
    return [
        ListSyncPair(
            source_entity_id=x[CONF_LIST_SYNC_SOURCE],
            target_list_id=x[CONF_LIST_SYNC_TARGET],
        )
        for x in entry.options.get(CONF_LIST_SYNCS) or []
        if x.get(CONF_LIST_SYNC_SOURCE) and x.get(CONF_LIST_SYNC_TARGET)
    ]


_TRAILING_NONE_RE = re.compile(r"(?:\s+None)+$")


def clean_summary(summary: str | None) -> str:
    """The item text without a trailing " None".

    Mealie shows recipe items with an empty note as e.g. "6 ägg None".
    """
    return _TRAILING_NONE_RE.sub("", (summary or "").strip())


def plan_list_sync(
    shopping_list: IcaShoppingList,
    source_items: list[dict[str, Any]],
    synced: dict[str, SyncedItem],
    parse_summary: Callable[[str], dict],
    new_row_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> tuple[IcaShoppingListSync | None, dict[str, SyncedItem]]:
    """The changes that bring the ICA list in line with the open source items.

    Returns the sync request (None when there is nothing to change) and the
    synced items to remember afterwards.
    """
    open_items = {
        str(item["uid"]): summary
        for item in source_items
        if item.get("uid") and (summary := clean_summary(item.get("summary")))
    }
    rows = {
        str(row["offlineId"]).lower(): row
        for row in shopping_list.get("rows") or []
        if row.get("offlineId")
    }

    created: list[IcaShoppingListEntry] = []
    changed: list[IcaShoppingListEntry] = []
    deleted: list[str] = []
    remembered: dict[str, SyncedItem] = {}

    for uid, item in synced.items():
        row = rows.get(str(item["row_id"]).lower())
        if uid not in open_items:
            # Checked off or deleted in the source
            if row:
                deleted.append(row["offlineId"])
            continue
        summary = open_items[uid]
        if row and summary != item["summary"]:
            ti = parse_summary(summary)
            changed.append(
                IcaShoppingListEntry(
                    offlineId=row["offlineId"],
                    isStrikedOver=bool(row.get("isStrikedOver")),
                    productName=ti["productName"],
                    # Always send quantity/unit so an edit can also clear them
                    quantity=ti.get("quantity"),
                    unit=ti.get("unit"),
                    latestChange=utc_timestamp(),
                )
            )
        # A row that is gone was deleted in ICA - keep the item so it is not re-added
        remembered[uid] = SyncedItem(row_id=item["row_id"], summary=summary)

    for uid, summary in open_items.items():
        if uid in synced:
            continue
        ti = parse_summary(summary)
        ti.pop("summary", None)
        ti["sourceId"] = -1
        ti["isStrikedOver"] = False
        ti["offlineId"] = new_row_id()
        created.append(IcaShoppingListEntry(ti))
        remembered[uid] = SyncedItem(row_id=ti["offlineId"], summary=summary)

    if not (created or changed or deleted):
        return None, remembered
    sync = IcaShoppingListSync(offlineId=shopping_list["offlineId"])
    if created:
        sync["createdRows"] = created
    if changed:
        sync["changedRows"] = changed
    if deleted:
        sync["deletedRows"] = deleted
    return sync, remembered


def _storage_key(entry: ConfigEntry) -> str:
    return f"{DOMAIN}.{entry_cache_key(entry)}.list_sync"


async def async_remove_list_sync_store(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await Store(hass, STORAGE_VERSION, _storage_key(entry)).async_remove()


class ListSyncManager:
    """Keeps the ICA lists of a config entry fed from their source to-do lists."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator: IcaCoordinator
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.pairs = configured_pairs(entry)
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, _storage_key(entry))
        # Synced items per pair, see `pair_key`
        self._synced: dict[str, dict[str, SyncedItem]] = {}
        self._lock = asyncio.Lock()
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=SYNC_COOLDOWN_SECONDS,
            immediate=False,
            function=self._async_scheduled_sync,
        )

    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        keys = {pair_key(pair) for pair in self.pairs}
        self._synced = {k: v for k, v in (data.get("pairs") or {}).items() if k in keys}
        if len(self._synced) != len(data.get("pairs") or {}):
            # Forget the items of removed pairs
            await self._async_save()

        entry = self.entry
        entry.async_on_unload(self._debouncer.async_cancel)
        entry.async_on_unload(
            async_track_state_change_event(
                self.hass,
                sorted({pair[CONF_LIST_SYNC_SOURCE] for pair in self.pairs}),
                self._async_schedule_sync,
            )
        )
        # Catches what the source state (its count of open items) does not show,
        # e.g. an edited item, at the latest after the next ICA refresh
        entry.async_on_unload(
            self.coordinator.async_add_listener(self._async_schedule_sync)
        )
        # The source lists may be set up after ICA
        entry.async_on_unload(async_at_started(self.hass, self._async_on_started))

    async def _async_on_started(self, _hass: HomeAssistant) -> None:
        self._async_schedule_sync()

    @callback
    def _async_schedule_sync(self, *_args) -> None:
        self._debouncer.async_schedule_call()

    async def _async_scheduled_sync(self) -> None:
        await self.async_sync_all(raise_on_error=False)

    async def async_sync_all(self, raise_on_error: bool = True) -> dict[str, int]:
        """Sync all pairs now. Returns the number of created, changed and deleted rows."""
        counts = {"created": 0, "changed": 0, "deleted": 0}
        async with self._lock:
            for pair in self.pairs:
                try:
                    sync = await self._async_sync_pair(pair)
                except Exception:
                    if raise_on_error:
                        raise
                    _LOGGER.exception(
                        "Could not sync %s into ICA list %s",
                        pair[CONF_LIST_SYNC_SOURCE],
                        pair[CONF_LIST_SYNC_TARGET],
                    )
                    continue
                if sync:
                    counts["created"] += len(sync.get("createdRows") or [])
                    counts["changed"] += len(sync.get("changedRows") or [])
                    counts["deleted"] += len(sync.get("deletedRows") or [])
        return counts

    async def _async_sync_pair(self, pair: ListSyncPair) -> IcaShoppingListSync | None:
        source = pair[CONF_LIST_SYNC_SOURCE]
        source_items = await self._async_get_open_items(source)
        if source_items is None:
            # Never delete rows just because the source is down
            return None

        target = str(pair[CONF_LIST_SYNC_TARGET]).lower()
        shopping_list = next(
            (
                x
                for x in self.coordinator.snapshot()["shopping_lists"]
                if str(x.get("offlineId")).lower() == target
            ),
            None,
        )
        if shopping_list is None:
            _LOGGER.warning(
                "Not syncing %s: the ICA list %s is not tracked",
                source,
                pair[CONF_LIST_SYNC_TARGET],
            )
            return None

        key = pair_key(pair)
        synced = self._synced.get(key, {})
        sync, remembered = plan_list_sync(
            shopping_list, source_items, synced, self.coordinator.parse_summary
        )
        if sync:
            _LOGGER.debug("Syncing %s into ICA list %s: %s", source, target, sync)
            await self.coordinator.sync_shopping_list(sync)
        if remembered != synced:
            # Only after a successful sync, so failed rows are tried again
            self._synced[key] = remembered
            await self._async_save()
        return sync

    async def _async_get_open_items(self, entity_id: str) -> list[dict] | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug("Not syncing %s: it is not available", entity_id)
            return None
        try:
            response = await self.hass.services.async_call(
                "todo",
                "get_items",
                {"status": ["needs_action"]},
                target={"entity_id": entity_id},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug("Not syncing %s: %s", entity_id, err)
            return None
        return list(((response or {}).get(entity_id) or {}).get("items") or [])

    async def _async_save(self) -> None:
        await self._store.async_save({"pairs": self._synced})
