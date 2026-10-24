"""Switch entities: on/off parameters of the running effect and effect rotation."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SignalRGBConfigEntry
from .entity import SignalRGBEntity
from .param_entity import KIND_SWITCH, SignalRGBParamEntity, async_setup_param_entities
from .webpipe import WebPipeError


async def async_setup_entry(
    hass: HomeAssistant, entry: SignalRGBConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SignalRGB switch entities."""
    async_add_entities([SignalRGBAutoAdvance(entry)])
    async_setup_param_entities(hass, entry, KIND_SWITCH, SignalRGBParamSwitch, async_add_entities)


class SignalRGBParamSwitch(SignalRGBParamEntity, SwitchEntity):
    """An on/off parameter of the running effect."""

    def __init__(self, entry: SignalRGBConfigEntry, name: str, label: str) -> None:
        """Initialize the switch entity."""
        super().__init__(entry, KIND_SWITCH, name, label)

    @property
    def is_on(self) -> bool | None:
        """Current parameter value."""
        value = self.param_value()
        return None if value is None else bool(value)

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable the parameter."""
        await self._set(True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable the parameter."""
        await self._set(False)

    async def _set(self, value: bool) -> None:
        try:
            await self._client.set_effect_param(self._param_name, value)
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err


class SignalRGBAutoAdvance(SignalRGBEntity, SwitchEntity):
    """Rotate effects on SignalRGB's timer."""

    _attr_name = "Effect Rotation"
    _attr_icon = "mdi:timer-sync-outline"

    def __init__(self, entry: SignalRGBConfigEntry) -> None:
        """Initialize the rotation switch."""
        super().__init__(entry.runtime_data, entry, "auto_advance")

    @property
    def is_on(self) -> bool:
        """True while effects rotate."""
        return self._client.auto_advance

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Start rotating effects."""
        await self._set(True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Stop rotating effects."""
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self._client.set_auto_advance(enabled)
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err
