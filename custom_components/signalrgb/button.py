"""Support for SignalRGB button controls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SignalRGBConfigEntry
from .client import SignalRGBClient
from .entity import SignalRGBEntity
from .webpipe import WebPipeError


@dataclass(frozen=True, kw_only=True)
class SignalRGBButtonEntityDescription(ButtonEntityDescription):
    """Class describing SignalRGB button entities."""

    press_fn: Callable[[SignalRGBClient], Awaitable[None]]


BUTTON_TYPES: Final[list[SignalRGBButtonEntityDescription]] = [
    SignalRGBButtonEntityDescription(
        key="next_effect",
        name="Next Effect",
        icon="mdi:skip-next",
        press_fn=lambda client: client.next_effect(),
    ),
    SignalRGBButtonEntityDescription(
        key="previous_effect",
        name="Previous Effect",
        icon="mdi:skip-previous",
        press_fn=lambda client: client.previous_effect(),
    ),
    SignalRGBButtonEntityDescription(
        key="random_effect",
        name="Random Effect",
        icon="mdi:shuffle-variant",
        press_fn=lambda client: client.random_effect(),
    ),
]


async def async_setup_entry(
    _hass: HomeAssistant, entry: SignalRGBConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SignalRGB button entities based on a config entry."""
    async_add_entities(SignalRGBButton(entry, description) for description in BUTTON_TYPES)


class SignalRGBButton(SignalRGBEntity, ButtonEntity):
    """Representation of a SignalRGB button entity."""

    entity_description: SignalRGBButtonEntityDescription

    def __init__(
        self, entry: SignalRGBConfigEntry, description: SignalRGBButtonEntityDescription
    ) -> None:
        """Initialize the button entity."""
        super().__init__(entry.runtime_data, entry, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self.entity_description.press_fn(self._client)
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err
