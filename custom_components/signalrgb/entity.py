"""Base entity for SignalRGB."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .client import SignalRGBClient
from .const import DOMAIN, MANUFACTURER, MODEL


class SignalRGBEntity(Entity):
    """Entity updated by WebPipe pushes instead of polling."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, client: SignalRGBClient, config_entry: ConfigEntry, key: str) -> None:
        """Initialize the entity."""
        self._client = client
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"{MODEL} {config_entry.data['host']}",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def available(self) -> bool:
        """Return True while the WebPipe channel is connected."""
        return self._client.connected

    async def async_added_to_hass(self) -> None:
        """Subscribe to client updates."""
        self.async_on_remove(self._client.add_listener(self._handle_client_update))

    @callback
    def _handle_client_update(self) -> None:
        self.async_write_ha_state()
