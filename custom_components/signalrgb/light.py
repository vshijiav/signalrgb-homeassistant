"""Support for SignalRGB lights."""

# pylint: disable=abstract-method

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from . import SignalRGBConfigEntry
from .const import DOMAIN, LOGGER
from .entity import SignalRGBEntity
from .webpipe import WebPipeError

STORAGE_VERSION = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: SignalRGBConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SignalRGB light based on a config entry."""
    store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.brightness"
    )
    saved = await store.async_load() or {}
    async_add_entities([SignalRGBLight(entry, store, saved)])


class SignalRGBLight(SignalRGBEntity, LightEntity):
    """All SignalRGB lighting as one light.

    Power and brightness act on every device's own brightness; the effect is
    SignalRGB's running effect.
    """

    _attr_name = None
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(
        self, entry: SignalRGBConfigEntry, store: Store[dict[str, Any]], saved: dict[str, Any]
    ) -> None:
        """Initialize the light."""
        super().__init__(entry.runtime_data, entry, "light")
        self._store = store
        # Per-device levels captured at turn-off, restored at turn-on
        self._saved_levels: dict[str, int] = saved.get("levels", {})

    @property
    def is_on(self) -> bool:
        """Return true if any device is lit."""
        return self._client.is_on

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return round(self._client.brightness * 255 / 100)

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        return self._client.current_effect

    @property
    def effect_list(self) -> list[str]:
        """Return the list of installed effects."""
        return self._client.effect_list

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of the running effect."""
        return self._client.effect_attributes()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally with a brightness or effect."""
        try:
            if ATTR_EFFECT in kwargs:
                await self._client.apply_effect(kwargs[ATTR_EFFECT])

            if ATTR_BRIGHTNESS in kwargs:
                await self._client.set_brightness(
                    max(1, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255))
                )
            elif not self._client.is_on:
                LOGGER.debug("Restoring %s saved device levels", len(self._saved_levels))
                await self._client.restore_brightness(self._saved_levels, default=100)
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off by dimming every device to 0."""
        if self._client.is_on:
            self._saved_levels = {
                uid: level for uid, level in self._client.brightness_levels.items() if level > 0
            }
            await self._store.async_save({"levels": self._saved_levels})
        try:
            await self._client.set_brightness(0)
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err
