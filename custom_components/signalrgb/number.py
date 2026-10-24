"""Number entities: slider parameters of the running effect and effect rotation interval."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SignalRGBConfigEntry
from .entity import SignalRGBEntity
from .param_entity import KIND_NUMBER, SignalRGBParamEntity, async_setup_param_entities
from .webpipe import WebPipeError


async def async_setup_entry(
    hass: HomeAssistant, entry: SignalRGBConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SignalRGB number entities."""
    async_add_entities([SignalRGBAutoAdvanceInterval(entry)])
    async_setup_param_entities(hass, entry, KIND_NUMBER, SignalRGBParamNumber, async_add_entities)


class SignalRGBParamNumber(SignalRGBParamEntity, NumberEntity):
    """A slider parameter of the running effect."""

    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: SignalRGBConfigEntry, name: str, label: str) -> None:
        """Initialize the number entity."""
        super().__init__(entry, KIND_NUMBER, name, label)

    @property
    def native_value(self) -> float | None:
        """Current parameter value."""
        return self.param_value()

    @property
    def native_min_value(self) -> float:
        """Lower bound declared by the effect."""
        param = self.param
        return float(param.get("min")) if param is not None else 0

    @property
    def native_max_value(self) -> float:
        """Upper bound declared by the effect."""
        param = self.param
        return float(param.get("max")) if param is not None else 100

    @property
    def native_step(self) -> float:
        """Step declared by the effect."""
        param = self.param
        step = param.get("step") if param is not None else None
        return float(step) if step else 1

    async def async_set_native_value(self, value: float) -> None:
        """Change the parameter live."""
        if float(self.native_step).is_integer():
            value = round(value)
        try:
            await self._client.set_effect_param(self._param_name, value)
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err


class SignalRGBAutoAdvanceInterval(SignalRGBEntity, NumberEntity):
    """Seconds between automatic effect changes."""

    _attr_name = "Effect Rotation Interval"
    _attr_icon = "mdi:timer-sync-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 10
    _attr_native_max_value = 86400
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, entry: SignalRGBConfigEntry) -> None:
        """Initialize the interval entity."""
        super().__init__(entry.runtime_data, entry, "auto_advance_interval")

    @property
    def native_value(self) -> int | None:
        """Current interval."""
        return self._client.auto_advance_interval

    async def async_set_native_value(self, value: float) -> None:
        """Change the interval."""
        try:
            await self._client.set_auto_advance_interval(int(value))
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err
