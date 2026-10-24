"""Text entities: color and free-text parameters of the running effect."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SignalRGBConfigEntry
from .param_entity import (
    COLOR_PATTERN,
    KIND_TEXT,
    SignalRGBParamEntity,
    async_setup_param_entities,
    is_color_param,
)
from .webpipe import WebPipeError


async def async_setup_entry(
    hass: HomeAssistant, entry: SignalRGBConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SignalRGB text entities."""
    async_setup_param_entities(hass, entry, KIND_TEXT, SignalRGBParamText, async_add_entities)


class SignalRGBParamText(SignalRGBParamEntity, TextEntity):
    """A color (#rrggbb) or text parameter of the running effect."""

    def __init__(self, entry: SignalRGBConfigEntry, name: str, label: str) -> None:
        """Initialize the text entity."""
        super().__init__(entry, KIND_TEXT, name, label)

    @property
    def _is_color(self) -> bool:
        return is_color_param(self.param)

    @property
    def pattern(self) -> str | None:
        """Require #rrggbb for color parameters."""
        return COLOR_PATTERN if self._is_color else None

    @property
    def native_max(self) -> int:
        """Colors are seven characters."""
        return 7 if self._is_color else 255

    @property
    def icon(self) -> str:
        """Palette icon for colors."""
        return "mdi:palette" if self._is_color else "mdi:tune-variant"

    @property
    def native_value(self) -> str | None:
        """Current parameter value."""
        value = self.param_value()
        return None if value is None else str(value)

    async def async_set_value(self, value: str) -> None:
        """Change the parameter live."""
        try:
            await self._client.set_effect_param(self._param_name, value)
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err
