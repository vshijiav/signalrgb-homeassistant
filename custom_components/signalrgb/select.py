"""Support for SignalRGB layout and preset selection."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SignalRGBConfigEntry
from .const import LOGGER
from .entity import SignalRGBEntity
from .param_entity import KIND_SELECT, SignalRGBParamEntity, async_setup_param_entities
from .webpipe import WebPipeError


async def async_setup_entry(
    hass: HomeAssistant, entry: SignalRGBConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SignalRGB select entities based on a config entry."""
    async_add_entities(
        [SignalRGBEffectSelect(entry), SignalRGBLayoutSelect(entry), SignalRGBPresetSelect(entry)]
    )
    async_setup_param_entities(hass, entry, KIND_SELECT, SignalRGBParamSelect, async_add_entities)


class SignalRGBEffectSelect(SignalRGBEntity, SelectEntity):
    """The running effect, selectable from the installed effects."""

    _attr_name = "Effect"
    _attr_icon = "mdi:creation"

    def __init__(self, entry: SignalRGBConfigEntry) -> None:
        """Initialize the effect select entity."""
        super().__init__(entry.runtime_data, entry, "effect")

    @property
    def options(self) -> list[str]:
        """Return the installed effects."""
        options = self._client.effect_list
        current = self._client.current_effect
        if current and current not in options:
            options = [*options, current]
        return options

    @property
    def current_option(self) -> str | None:
        """Return the running effect."""
        return self._client.current_effect

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Details of the running effect."""
        return self._client.effect_attributes()

    async def async_select_option(self, option: str) -> None:
        """Run the selected effect."""
        try:
            await self._client.apply_effect(option)
        except WebPipeError as err:
            raise HomeAssistantError(f"Failed to apply effect: {err}") from err


class SignalRGBParamSelect(SignalRGBParamEntity, SelectEntity):
    """A drop-down parameter of the running effect."""

    def __init__(self, entry: SignalRGBConfigEntry, name: str, label: str) -> None:
        """Initialize the parameter select entity."""
        super().__init__(entry, KIND_SELECT, name, label)

    @property
    def options(self) -> list[str]:
        """Options declared by the effect."""
        param = self.param
        return [str(option) for option in (param.get("options") or [])] if param is not None else []

    @property
    def current_option(self) -> str | None:
        """Current parameter value."""
        value = self.param_value()
        return None if value is None else str(value)

    async def async_select_option(self, option: str) -> None:
        """Change the parameter live."""
        try:
            await self._client.set_effect_param(self._param_name, option)
        except WebPipeError as err:
            raise HomeAssistantError(f"SignalRGB: {err}") from err


class SignalRGBLayoutSelect(SignalRGBEntity, SelectEntity):
    """Switch between saved SignalRGB layouts."""

    _attr_name = "Layout"
    _attr_icon = "mdi:view-grid-outline"

    def __init__(self, entry: SignalRGBConfigEntry) -> None:
        """Initialize the layout select entity."""
        super().__init__(entry.runtime_data, entry, "layout")

    @property
    def options(self) -> list[str]:
        """Return the saved layouts."""
        return sorted(self._client.layouts)

    @property
    def current_option(self) -> str | None:
        """Return the loaded layout."""
        return self._client.current_layout

    async def async_select_option(self, option: str) -> None:
        """Load a layout."""
        try:
            await self._client.set_layout(option)
        except WebPipeError as err:
            raise HomeAssistantError(f"Failed to select layout: {err}") from err


class SignalRGBPresetSelect(SignalRGBEntity, SelectEntity):
    """Apply a saved preset of the running effect."""

    _attr_name = "Effect Preset"
    _attr_icon = "mdi:playlist-star"

    def __init__(self, entry: SignalRGBConfigEntry) -> None:
        """Initialize the preset select entity."""
        super().__init__(entry.runtime_data, entry, "preset")
        self._presets: list[str] = []
        self._current_preset: str | None = None
        self._effect_seen: str | None = None

    @property
    def available(self) -> bool:
        """Only available when the running effect has presets."""
        return super().available and bool(self._presets)

    @property
    def options(self) -> list[str]:
        """Return presets of the running effect."""
        return self._presets

    @property
    def current_option(self) -> str | None:
        """Return the preset last applied from Home Assistant."""
        return self._current_preset

    async def async_added_to_hass(self) -> None:
        """Load presets for the running effect."""
        await super().async_added_to_hass()
        await self._refresh_presets()

    @callback
    def _handle_client_update(self) -> None:
        active = self._client.active_effect
        effect_id = active.id if active is not None else None
        if effect_id != self._effect_seen:
            # Preset lists are fetched with a call, so re-fetch when the effect changes
            self.hass.async_create_task(self._refresh_presets())
        self.async_write_ha_state()

    async def _refresh_presets(self) -> None:
        active = self._client.active_effect
        self._effect_seen = active.id if active is not None else None
        try:
            self._presets = await self._client.get_presets()
        except WebPipeError as err:
            LOGGER.debug("Could not fetch presets: %s", err)
            self._presets = []
        if self._current_preset not in self._presets:
            self._current_preset = None
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Apply the selected preset."""
        if option not in self._presets:
            raise HomeAssistantError(f"Preset {option} not found")
        try:
            await self._client.apply_preset(option)
        except WebPipeError as err:
            raise HomeAssistantError(f"Failed to apply preset: {err}") from err
        self._current_preset = option
        self.async_write_ha_state()
