"""SignalRGB control over the local WebPipe channel.

Effects are applied with lighting.setAlwaysEffect(), the same call the SignalRGB
UI makes. Brightness and power are per-device: every lighting endpoint (devices
and the components on their channels) has a writable Brightness, so "off" sets
all of them to 0 and "on" restores the remembered levels.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import aiohttp

from .const import LOGGER
from .webpipe import QObjectProxy, WebPipe, WebPipeError

RECONNECT_DELAYS = (5, 10, 30, 60)


class SignalRGBClient:
    """Live view of a SignalRGB instance, kept current by WebPipe pushes."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._session = session
        self._pipe: WebPipe | None = None
        self._listeners: list[Callable[[], None]] = []
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closing = False
        # Parameter objects of the running effect, re-fetched when the effect changes
        self._params: list[QObjectProxy] = []
        self._params_effect_id: str | None = None
        self._params_task: asyncio.Task[None] | None = None
        self._params_debounce: asyncio.TimerHandle | None = None
        self._watched_models: set[str] = set()

    @property
    def url(self) -> str:
        """WebSocket URL of the WebPipe (or a relay in front of it)."""
        return f"ws://{self.host}:{self.port}/"

    @property
    def connected(self) -> bool:
        """Return True while the channel is live."""
        return self._pipe is not None and self._pipe.connected

    # Connection ------------------------------------------------------------

    async def connect(self) -> None:
        """Connect and load the channel; raises WebPipeError on failure."""
        pipe = WebPipe(self._session, self.url, self._handle_update, self._handle_disconnect)
        await pipe.connect()
        self._pipe = pipe
        self._watched_models = set()
        LOGGER.info("Connected to SignalRGB WebPipe at %s", self.url)
        await self._refresh_params()
        self._notify()

    async def close(self) -> None:
        """Close the channel and stop reconnecting."""
        self._closing = True
        if self._params_debounce is not None:
            self._params_debounce.cancel()
        for task in (self._reconnect_task, self._params_task):
            if task is not None:
                task.cancel()
        if self._pipe is not None:
            await self._pipe.close()

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call listener on every state change; returns an unsubscribe function."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _handle_update(self, _changed: set[str]) -> None:
        active = self.active_effect
        active_id = active.id if active is not None else None
        if active_id != self._params_effect_id and (
            self._params_task is None or self._params_task.done()
        ):
            self._params_task = asyncio.create_task(self._refresh_params())
        self._notify()

    def _handle_params_changed(self, _args: list[Any]) -> None:
        # SignalRGB rebuilds the parameter objects while an effect loads, so the
        # ones fetched earlier go stale; re-fetch once the burst of changes settles.
        if self._params_debounce is not None:
            self._params_debounce.cancel()
        self._params_debounce = asyncio.get_running_loop().call_later(
            0.3, lambda: asyncio.create_task(self._refresh_params())
        )

    async def _refresh_params(self) -> None:
        active = self.active_effect
        self._params_effect_id = active.id if active is not None else None
        params: list[QObjectProxy] = []
        model = active.get("properties") if active is not None else None
        if isinstance(model, QObjectProxy):
            try:
                if model.id not in self._watched_models:
                    self._watched_models.add(model.id)
                    for signal in ("modelReset", "rowsInserted", "rowsRemoved"):
                        await model.connect_signal(signal, self._handle_params_changed)
                items = await model.call("itemList()")
                params = [item for item in items or [] if isinstance(item, QObjectProxy)]
            except WebPipeError as err:
                LOGGER.debug("Could not fetch effect parameters: %s", err)
        self._params = params
        self._notify()
        # The effect may have changed again while fetching
        current = self.active_effect
        if current is not None and current.id != self._params_effect_id:
            self._params_task = asyncio.create_task(self._refresh_params())

    def _handle_disconnect(self) -> None:
        self._notify()
        if self._closing or (self._reconnect_task is not None and not self._reconnect_task.done()):
            return
        LOGGER.warning("Lost connection to SignalRGB WebPipe at %s", self.url)
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        attempt = 0
        while not self._closing:
            delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
            await asyncio.sleep(delay)
            try:
                await self.connect()
                return
            except WebPipeError as err:
                attempt += 1
                LOGGER.debug("Reconnect to %s failed: %s", self.url, err)

    def _obj(self, name: str) -> QObjectProxy:
        if self._pipe is None or not self._pipe.connected:
            raise WebPipeError(f"Not connected to SignalRGB at {self.url}")
        return self._pipe[name]

    # Effects ---------------------------------------------------------------

    @property
    def current_effect(self) -> str | None:
        """Name of the running effect."""
        return self._obj("lighting").get("currentEffect") if self.connected else None

    @property
    def active_effect(self) -> QObjectProxy | None:
        """The running effect object (name, description, properties, presets)."""
        if not self.connected:
            return None
        active = self._obj("lighting").get("active")
        return active if isinstance(active, QObjectProxy) else None

    @property
    def effect_list(self) -> list[str]:
        """Installed effect names, as SignalRGB displays them."""
        if not self.connected:
            return []
        return sorted(set(self._obj("lighting").get("allEffectNames") or []), key=str.casefold)

    async def apply_effect(self, name: str) -> None:
        """Run an installed effect by its displayed name."""
        # An unknown name makes SignalRGB fall back to a default effect, so check first.
        if name not in self.effect_list:
            raise WebPipeError(f"Effect '{name}' is not installed")
        await self._obj("lighting").call("setAlwaysEffect(QString)", name)

    async def next_effect(self) -> None:
        """Advance to the next effect in SignalRGB's queue."""
        await self._obj("lighting").call("goForward()")

    async def previous_effect(self) -> None:
        """Go back to the previous effect."""
        await self._obj("lighting").call("goBackward()")

    async def random_effect(self) -> None:
        """Jump to a random effect."""
        await self._obj("lighting").call("goCrazy()")

    async def get_presets(self) -> list[str]:
        """Saved presets of the running effect."""
        active = self.active_effect
        if active is None:
            return []
        presets = await active.call("AvailablePresets()")
        return [str(preset) for preset in presets or []]

    async def apply_preset(self, preset: str) -> None:
        """Load a saved preset of the running effect."""
        active = self.active_effect
        if active is None:
            raise WebPipeError("No effect is running")
        await active.call("loadState(QString)", preset)

    @property
    def effect_params(self) -> list[QObjectProxy]:
        """Parameter objects of the running effect (name, label, editor, value, ...)."""
        return self._params if self.connected else []

    def effect_param(self, name: str) -> QObjectProxy | None:
        """Parameter of the running effect by its property name."""
        return next((param for param in self.effect_params if param.get("name") == name), None)

    async def set_effect_param(self, name: str, value: Any) -> None:
        """Change a parameter of the running effect live."""
        param = self.effect_param(name)
        if param is None:
            raise WebPipeError(f"The running effect has no parameter '{name}'")
        await param.set("value", value)
        self._notify()

    # Automatic effect rotation ----------------------------------------------

    @property
    def _effect_timer(self) -> QObjectProxy | None:
        timer = self._obj("lighting").get("effectTimer") if self.connected else None
        return timer if isinstance(timer, QObjectProxy) else None

    @property
    def auto_advance(self) -> bool:
        """True while SignalRGB rotates effects on a timer."""
        timer = self._effect_timer
        return bool(timer and timer.get("active") and not timer.get("paused"))

    @property
    def auto_advance_interval(self) -> int | None:
        """Seconds between automatic effect changes."""
        timer = self._effect_timer
        return timer.get("intervalSeconds") if timer else None

    async def set_auto_advance(self, enabled: bool) -> None:
        """Start or stop rotating effects on a timer."""
        timer = self._effect_timer
        if timer is None:
            raise WebPipeError("SignalRGB has no effect timer")
        await timer.call("start()" if enabled else "stop()")

    async def set_auto_advance_interval(self, seconds: int) -> None:
        """Set seconds between automatic effect changes."""
        timer = self._effect_timer
        if timer is None:
            raise WebPipeError("SignalRGB has no effect timer")
        # SetInterval takes milliseconds (SignalRGB clamps it to at least 10 s)
        await timer.call("SetInterval(int)", int(seconds) * 1000)

    # Layouts ---------------------------------------------------------------

    @property
    def layouts(self) -> list[str]:
        """Saved layout names."""
        return list(self._obj("layout").get("layouts") or []) if self.connected else []

    @property
    def current_layout(self) -> str | None:
        """Name of the loaded layout."""
        return self._obj("layout").get("current") if self.connected else None

    async def set_layout(self, name: str) -> None:
        """Load a saved layout."""
        if name not in self.layouts:
            raise WebPipeError(f"Layout '{name}' does not exist")
        await self._obj("layout").call("loadLayout(QString)", name)

    # Brightness and power --------------------------------------------------

    @property
    def endpoints(self) -> list[QObjectProxy]:
        """Every lighting endpoint: devices plus the components on their channels."""
        if not self.connected:
            return []
        return [
            ep
            for ep in self._obj("devices").get("lightingEndpoints") or []
            if isinstance(ep, QObjectProxy)
        ]

    @property
    def brightness_levels(self) -> dict[str, int]:
        """Brightness (0-100) per endpoint UID."""
        return {ep.get("Uid"): int(ep.get("Brightness") or 0) for ep in self.endpoints}

    @property
    def brightness(self) -> int:
        """Highest endpoint brightness, 0-100."""
        return max(self.brightness_levels.values(), default=0)

    @property
    def is_on(self) -> bool:
        """True when any endpoint is lit."""
        return self.brightness > 0

    async def set_brightness(self, level: int) -> None:
        """Set every endpoint to the same brightness, 0-100."""
        level = max(0, min(100, level))
        for endpoint in self.endpoints:
            await endpoint.set("Brightness", level)
        self._notify()

    async def restore_brightness(self, levels: dict[str, int], default: int) -> None:
        """Set endpoints to remembered levels; endpoints not in the map get default."""
        for endpoint in self.endpoints:
            level = levels.get(endpoint.get("Uid")) or default
            await endpoint.set("Brightness", max(1, min(100, int(level))))
        self._notify()

    def effect_attributes(self) -> dict[str, Any]:
        """Details of the running effect for entity attributes."""
        active = self.active_effect
        if active is None:
            return {}
        return {
            "effect_name": active.get("name"),
            "effect_description": active.get("description"),
            "effect_publisher": active.get("publisher"),
            "effect_uses_audio": active.get("uses_audio"),
            "effect_uses_video": active.get("uses_video"),
            "effect_uses_meters": active.get("uses_meters"),
            "effect_image": active.get("image"),
        }
