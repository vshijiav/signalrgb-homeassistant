"""Entities for the parameters of the running SignalRGB effect.

Every effect declares its own parameters (speed, colors, modes, ...). One entity
exists per parameter name and kind; it is created the first time an effect with
that parameter runs, and is unavailable while the running effect lacks it.
"""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SignalRGBConfigEntry
from .entity import SignalRGBEntity
from .webpipe import QObjectProxy

KIND_NUMBER = "number"
KIND_SWITCH = "switch"
KIND_SELECT = "select"
KIND_TEXT = "text"

UNIQUE_ID_PREFIX = "param_"
NAME_PREFIX = "Effect "

COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
COLOR_RE = re.compile(COLOR_PATTERN)


def param_kind(param: QObjectProxy) -> str | None:
    """Map a parameter to the entity kind that controls it.

    The value decides before the editor name: hue parameters use
    PropColorslider.qml but hold a 0-360 number, not a color.
    """
    editor = param.get("editor") or ""
    value = param.get("value")
    if "Combo" in editor:
        return KIND_SELECT
    if "Boolean" in editor or isinstance(value, bool):
        return KIND_SWITCH
    if (
        isinstance(value, (int, float))
        and param.get("min") is not None
        and param.get("max") is not None
    ):
        return KIND_NUMBER
    if isinstance(value, str):
        return KIND_TEXT
    return None


def is_color_param(param: QObjectProxy | None) -> bool:
    """True when the parameter currently holds a #rrggbb color.

    Decided by the value, so a pattern is only enforced on values that satisfy
    it; Home Assistant refuses to write a state that breaks the pattern.
    """
    value = param.get("value") if param is not None else None
    return isinstance(value, str) and COLOR_RE.fullmatch(value) is not None


class SignalRGBParamEntity(SignalRGBEntity):
    """Base for an entity bound to one parameter of the running effect."""

    _attr_icon = "mdi:tune-variant"

    def __init__(self, entry: SignalRGBConfigEntry, kind: str, name: str, label: str) -> None:
        """Initialize the parameter entity."""
        self._kind = kind
        self._param_name = name
        self._label = label or name
        super().__init__(entry.runtime_data, entry, f"{UNIQUE_ID_PREFIX}{kind}_{name}")

    @property
    def param(self) -> QObjectProxy | None:
        """The parameter object if the running effect has it."""
        param = self._client.effect_param(self._param_name)
        if param is None or param_kind(param) != self._kind:
            return None
        return param

    @property
    def available(self) -> bool:
        """Available while the running effect has this parameter."""
        return super().available and self.param is not None

    @property
    def name(self) -> str:
        """Parameter label as the effect names it."""
        param = self.param
        if param is not None and param.get("label"):
            self._label = param.get("label")
        return f"{NAME_PREFIX}{self._label}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which effect parameter this controls."""
        return {"parameter": self._param_name, "effect": self._client.current_effect}

    def param_value(self) -> Any:
        """Current value, or None when the parameter is absent."""
        param = self.param
        return param.get("value") if param is not None else None

    async def async_added_to_hass(self) -> None:
        """Hide right away if the running effect lacks this parameter."""
        await super().async_added_to_hass()
        self._sync_hidden()

    @callback
    def _handle_client_update(self) -> None:
        super()._handle_client_update()
        self._sync_hidden()

    @callback
    def _sync_hidden(self) -> None:
        """Hide this entity while the running effect lacks the parameter.

        Only touches entities hidden by the integration, so a user's own
        hide/unhide choice is left alone. Nothing changes while disconnected.
        """
        if not self._client.connected or self.registry_entry is None:
            return
        hidden_by = self.registry_entry.hidden_by
        if self.param is None and hidden_by is None:
            new_hidden_by: er.RegistryEntryHider | None = er.RegistryEntryHider.INTEGRATION
        elif self.param is not None and hidden_by is er.RegistryEntryHider.INTEGRATION:
            new_hidden_by = None
        else:
            return
        er.async_get(self.hass).async_update_entity(self.entity_id, hidden_by=new_hidden_by)


def async_setup_param_entities(
    hass: HomeAssistant,
    entry: SignalRGBConfigEntry,
    kind: str,
    factory: Callable[[SignalRGBConfigEntry, str, str], Entity],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add entities for parameters of this kind now and whenever a new one appears.

    Parameters seen under earlier effects are re-added from the entity registry
    too, so they keep being hidden and unhidden as effects change.
    """
    client = entry.runtime_data
    known: set[str] = set()
    restored = []

    prefix = f"{entry.entry_id}_{UNIQUE_ID_PREFIX}{kind}_"
    for reg_entry in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if reg_entry.unique_id.startswith(prefix):
            name = reg_entry.unique_id.removeprefix(prefix)
            label = (reg_entry.original_name or name).removeprefix(NAME_PREFIX)
            known.add(name)
            restored.append(factory(entry, name, label))
    if restored:
        async_add_entities(restored)

    @callback
    def add_new_params() -> None:
        new_entities = []
        for param in client.effect_params:
            name = param.get("name")
            if name and name not in known and param_kind(param) == kind:
                known.add(name)
                new_entities.append(factory(entry, name, param.get("label") or name))
        if new_entities:
            async_add_entities(new_entities)

    add_new_params()
    entry.async_on_unload(client.add_listener(add_new_params))
