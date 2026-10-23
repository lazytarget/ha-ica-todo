import asyncio
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)


class BackgroundWorker:
    """Handles a queue for sending Home Assistant events."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        send_interval: int = 60,
    ) -> None:
        self._hass: HomeAssistant = hass
        self._send_interval: int = send_interval
        self._config_entry = config_entry
        self._shutdown: bool = False
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._queue_send_remover: Callable[[], None] | None = None
        self._schedule_next_send()

    def _schedule_next_send(self) -> None:
        """Schedule the next send."""
        if not self._shutdown:
            if self._queue_send_remover:
                self._queue_send_remover()
            self._queue_send_remover = async_call_later(
                self._hass, self._send_interval, self._async_send_queue
            )

    async def shutdown(self) -> None:
        """Stops the background worker."""
        _LOGGER.debug(
            "ICA - SHUTDOWN QUEUE: empty=%s, loaded=%s",
            self._queue.empty(),
            self._config_entry.state == ConfigEntryState.LOADED,
        )
        if self._queue_send_remover:
            self._queue_send_remover()
        self._shutdown = True
        await self._async_send_queue(None)

    async def _async_send_queue(self, _) -> None:
        """Sends the existing items in the queue."""
        _LOGGER.debug(
            "ICA - SENDING QUEUE: empty=%s, loaded=%s",
            self._queue.empty(),
            self._config_entry.state == ConfigEntryState.LOADED,
        )
        while not self._queue.empty():
            (event_type, event_data) = self._queue.get_nowait()
            self.fire_event(event_type, event_data)
        self._schedule_next_send()

    async def fire_or_queue_event(self, event_type, event_data) -> None:
        """Queues or fires an event immediately as long as the integration is fully loaded."""
        _LOGGER.debug("ICA - FIRE/QUEUE: %s", event_type)
        if self._config_entry.state == ConfigEntryState.LOADED:
            self.fire_event(event_type, event_data)
        else:
            await self._queue.put((event_type, event_data))

    async def queue_event(self, event_type, event_data) -> None:
        """Queues a event to be fired in the next send interval."""
        _LOGGER.debug("ICA - QUEUING: %s", event_type)
        await self._queue.put((event_type, event_data))

    def fire_event(self, event_type, event_data) -> None:
        """Immediately tells Home Assistant to fire an event."""
        _LOGGER.debug("ICA - FIRING EVENT: %s", event_type)
        self._hass.bus.async_fire(event_type, event_data)
