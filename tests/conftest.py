"""Pytest configuration: a fake SignalRGB WebPipe (QWebChannel) server."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from pathlib import Path
import sys
from typing import Any

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
import pytest

# Add the project root directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))


class FakeObject:
    """A published QObject: named properties and methods with handlers."""

    def __init__(
        self,
        object_id: str,
        props: dict[str, Any],
        methods: dict[str, Any] | None = None,
        signals=(),
    ):
        self.id = object_id
        self.props = props
        self.methods = methods or {}
        self.signals = list(signals)

    def publish(self) -> dict[str, Any]:
        """Serialize as QWebChannel object data (with nested objects inlined)."""
        return {
            "methods": [[name, index] for index, name in enumerate(self.methods)],
            "signals": [[name, index] for index, name in enumerate(self.signals)],
            "properties": [
                [index, name, [1, index], encode(value)]
                for index, (name, value) in enumerate(self.props.items())
            ],
        }


def encode(value: Any) -> Any:
    """Encode values the way QWebChannel does, inlining QObjects."""
    if isinstance(value, FakeObject):
        return {"__QObject*__": True, "id": value.id, "data": value.publish()}
    if isinstance(value, list):
        return [encode(item) for item in value]
    return value


class FakeSignalRGB:
    """Minimal SignalRGB WebPipe: lighting, layout, devices and an effect timer."""

    def __init__(self) -> None:
        self.sockets: list[web.WebSocketResponse] = []
        self.calls: list[tuple[str, str, list[Any]]] = []
        self.connected_signals: list[tuple[str, int]] = []
        self._params_generation = 0
        self.params = self._make_params()
        self.model = FakeObject(
            "{model-aurora}",
            {},
            {"itemList()": lambda: self.params},
            signals=["modelReset", "rowsInserted", "rowsRemoved"],
        )
        self.active = FakeObject(
            "{effect-aurora}",
            {"name": "Aurora", "description": "Northern lights", "properties": self.model},
        )
        self.timer = FakeObject(
            "{timer}",
            {"active": False, "paused": False, "interval": 300000, "intervalSeconds": 300},
            {
                "start()": self._timer_start,
                "stop()": self._timer_stop,
                "SetInterval(int)": self._timer_interval,
            },
        )
        self.lighting = FakeObject(
            "lighting",
            {
                "currentEffect": "Aurora",
                "allEffectNames": ["Aurora", "Rainbow", "aurora borealis", "Aurora"],
                "active": self.active,
                "effectTimer": self.timer,
            },
            {
                "setAlwaysEffect(QString)": self._set_effect,
                "goForward()": lambda: self._set_effect("Rainbow"),
                "goBackward()": lambda: self._set_effect("Aurora"),
                "goCrazy()": lambda: self._set_effect("Rainbow"),
            },
        )
        self.layout = FakeObject(
            "layout",
            {"layouts": ["Desk", "Full"], "current": "Desk"},
            {"loadLayout(QString)": self._load_layout},
        )
        self.endpoints = [
            FakeObject("{ep-kbd}", {"Uid": "kbd", "Name": "Keyboard", "Brightness": 80}),
            FakeObject("{ep-fan}", {"Uid": "fan", "Name": "Fan", "Brightness": 100}),
        ]
        self.devices = FakeObject("devices", {"lightingEndpoints": self.endpoints})
        self.roots = [self.lighting, self.layout, self.devices]
        self.objects = {
            obj.id: obj
            for obj in [
                *self.roots,
                self.active,
                self.model,
                self.timer,
                *self.endpoints,
                *self.params,
            ]
        }

    def _make_params(self) -> list[FakeObject]:
        gen = self._params_generation
        return [
            FakeObject(
                f"{{p-speed-{gen}}}",
                {
                    "name": "speed",
                    "label": "Speed",
                    "editor": "PropSlider.qml",
                    "value": 40,
                    "min": 0,
                    "max": 100,
                    "step": 1,
                },
            ),
            FakeObject(
                f"{{p-color-{gen}}}",
                {
                    "name": "frontColor",
                    "label": "Front",
                    "editor": "PropColorpicker.qml",
                    "value": "#00ffff",
                },
            ),
            FakeObject(
                f"{{p-cycle-{gen}}}",
                {"name": "cycle", "label": "Cycle", "editor": "PropBoolean.qml", "value": False},
            ),
            FakeObject(
                f"{{p-mode-{gen}}}",
                {
                    "name": "mode",
                    "label": "Mode",
                    "editor": "PropCombo.qml",
                    "value": "Custom",
                    "options": ["Custom", "Rainbow"],
                },
            ),
        ]

    # Handlers that change state and push updates ------------------------------

    async def _set_effect(self, name: str) -> None:
        await self.set_prop(self.lighting, "currentEffect", name)

    async def _load_layout(self, name: str) -> None:
        await self.set_prop(self.layout, "current", name)

    async def _timer_start(self) -> None:
        await self.set_prop(self.timer, "active", True)

    async def _timer_stop(self) -> None:
        await self.set_prop(self.timer, "active", False)

    async def _timer_interval(self, ms: int) -> None:
        await self.set_prop(self.timer, "interval", ms)
        await self.set_prop(self.timer, "intervalSeconds", ms // 1000)

    async def rebuild_params(self) -> None:
        """Replace the parameter objects, as SignalRGB does while an effect loads."""
        self._params_generation += 1
        self.params = self._make_params()
        self.objects.update({param.id: param for param in self.params})
        await self.emit(self.model, "modelReset")

    async def set_prop(self, obj: FakeObject, name: str, value: Any) -> None:
        """Change a property and push the update to every client."""
        obj.props[name] = value
        index = list(obj.props).index(name)
        await self.broadcast(
            {
                "type": 2,
                "data": [
                    {"object": obj.id, "properties": {str(index): encode(value)}, "signals": {}}
                ],
            }
        )

    async def emit(self, obj: FakeObject, signal: str) -> None:
        """Emit a signal to clients that connected to it."""
        index = obj.signals.index(signal)
        if (obj.id, index) in self.connected_signals:
            await self.broadcast({"type": 1, "object": obj.id, "signal": index, "args": []})

    async def broadcast(self, msg: dict[str, Any]) -> None:
        for ws in self.sockets:
            if not ws.closed:
                await ws.send_str(json.dumps(msg))

    # QWebChannel protocol ------------------------------------------------------

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                break
            await self._dispatch(ws, json.loads(msg.data))
        return ws

    async def _dispatch(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> None:
        kind = data.get("type")
        if kind == 3:  # Init
            payload = {obj.id: obj.publish() for obj in self.roots}
            await ws.send_str(json.dumps({"type": 10, "id": data["id"], "data": payload}))
        elif kind == 6:  # Invoke
            obj = self.objects[data["object"]]
            name = list(obj.methods)[data["method"]]
            self.calls.append((obj.id, name, data["args"]))
            result = obj.methods[name](*data["args"])
            if hasattr(result, "__await__"):
                result = await result
            await ws.send_str(json.dumps({"type": 10, "id": data["id"], "data": encode(result)}))
        elif kind == 7:  # Connect to signal
            self.connected_signals.append((data["object"], data["signal"]))
        elif kind == 9:  # Set property
            obj = self.objects[data["object"]]
            await self.set_prop(obj, list(obj.props)[data["property"]], data["value"])


@pytest.fixture
async def fake_signalrgb() -> AsyncIterator[tuple[FakeSignalRGB, TestServer]]:
    """Run a fake WebPipe on a random localhost port."""
    fake = FakeSignalRGB()
    app = web.Application()
    app.router.add_get("/", fake.handle)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    yield fake, server
    await server.close()
