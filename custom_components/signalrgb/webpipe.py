"""QWebChannel client for SignalRGB's local "WebPipe" WebSocket.

The SignalRGB desktop UI drives its core through a QWebChannel published on
ws://127.0.0.1:16036. A client sends Init once and receives every published
object with its properties and methods (~25 MB, mostly device LED maps), then
keeps the socket open: after each Idle message the server pushes batched
property updates.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import itertools
import json
from typing import Any

import aiohttp

from .const import LOGGER

# QWebChannel message types
MSG_SIGNAL = 1
MSG_PROPERTY_UPDATE = 2
MSG_INIT = 3
MSG_IDLE = 4
MSG_INVOKE = 6
MSG_CONNECT_SIGNAL = 7
MSG_SET_PROPERTY = 9
MSG_RESPONSE = 10

INIT_TIMEOUT = 60
CALL_TIMEOUT = 10


class WebPipeError(Exception):
    """Raised when the WebPipe channel fails or rejects a request."""


class QObjectProxy:
    """Client-side view of one published QObject."""

    def __init__(self, channel: WebPipe, object_id: str, data: dict[str, Any]) -> None:
        self.channel = channel
        self.id = object_id
        self.methods: dict[str, int] = {}
        self.signals: dict[str, int] = {}
        self.prop_index: dict[str, int] = {}
        self.props: dict[str, Any] = {}
        self.load(data)

    def load(self, data: dict[str, Any]) -> None:
        """Load method and property metadata published for this object."""
        for name, index in data.get("methods", []):
            self.methods[name] = index
        for name, index in data.get("signals", []):
            self.signals[name] = index
        for index, name, _notify, value in data.get("properties", []):
            self.prop_index[name] = index
            self.props[name] = self.channel.unwrap(value)

    def get(self, name: str, default: Any = None) -> Any:
        """Return the last known value of a property."""
        return self.props.get(name, default)

    async def call(self, signature: str, *args: Any) -> Any:
        """Invoke a method by its full signature, e.g. "goForward()"."""
        if signature not in self.methods:
            raise WebPipeError(f"{self.id} has no method {signature}")
        return await self.channel.invoke(self.id, self.methods[signature], list(args))

    async def set(self, name: str, value: Any) -> None:
        """Write a property."""
        if name not in self.prop_index:
            raise WebPipeError(f"{self.id} has no property {name}")
        await self.channel.send(
            {
                "type": MSG_SET_PROPERTY,
                "object": self.id,
                "property": self.prop_index[name],
                "value": value,
            }
        )
        self.props[name] = value

    async def connect_signal(self, name: str, callback: Callable[[list[Any]], None]) -> None:
        """Call callback with the signal's arguments whenever the object emits it."""
        if name not in self.signals:
            raise WebPipeError(f"{self.id} has no signal {name}")
        await self.channel.connect_signal(self.id, self.signals[name], callback)

    def __repr__(self) -> str:
        return f"<QObject {self.id}>"


class WebPipe:
    """One QWebChannel connection."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        on_update: Callable[[set[str]], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        self._session = session
        self._url = url
        self._on_update = on_update
        self._on_disconnect = on_disconnect
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._signal_handlers: dict[tuple[str, int], list[Callable[[list[Any]], None]]] = {}
        self.objects: dict[str, QObjectProxy] = {}

    @property
    def connected(self) -> bool:
        """Return True while the socket is open and being read."""
        return (
            self._ws is not None
            and not self._ws.closed
            and self._reader is not None
            and not self._reader.done()
        )

    async def connect(self) -> None:
        """Open the socket and load all published objects."""
        try:
            self._ws = await self._session.ws_connect(self._url, max_msg_size=0, autoping=True)
            await self.send({"type": MSG_INIT, "id": 0})
            async with asyncio.timeout(INIT_TIMEOUT):
                while True:
                    msg = await self._ws.receive()
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        raise WebPipeError(f"WebPipe closed during init ({msg.type.name})")
                    # The init payload is ~25 MB; parse it off the event loop.
                    data = await asyncio.get_running_loop().run_in_executor(
                        None, json.loads, msg.data
                    )
                    if data.get("type") == MSG_RESPONSE and data.get("id") == 0:
                        break
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            await self.close()
            raise WebPipeError(f"Cannot connect to {self._url}: {err}") from err
        except WebPipeError:
            await self.close()
            raise

        for name, obj in data["data"].items():
            self.objects[name] = QObjectProxy(self, name, obj)
        self._reader = asyncio.create_task(self._read_loop())
        await self.send({"type": MSG_IDLE})

    async def close(self) -> None:
        """Close the socket."""
        reader, self._reader = self._reader, None
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def send(self, msg: dict[str, Any]) -> None:
        """Send one channel message."""
        if self._ws is None or self._ws.closed:
            raise WebPipeError("WebPipe is not connected")
        await self._ws.send_str(json.dumps(msg, ensure_ascii=False))

    async def invoke(self, object_id: str, method: int, args: list[Any]) -> Any:
        """Invoke a method and wait for its return value."""
        call_id = next(self._ids)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        try:
            await self.send(
                {
                    "type": MSG_INVOKE,
                    "object": object_id,
                    "method": method,
                    "args": args,
                    "id": call_id,
                }
            )
            async with asyncio.timeout(CALL_TIMEOUT):
                return await future
        except TimeoutError as err:
            raise WebPipeError(f"No response from SignalRGB for {object_id}.{method}") from err
        finally:
            self._pending.pop(call_id, None)

    async def connect_signal(
        self, object_id: str, signal: int, callback: Callable[[list[Any]], None]
    ) -> None:
        """Subscribe to a signal of a published object."""
        handlers = self._signal_handlers.setdefault((object_id, signal), [])
        if not handlers:
            await self.send({"type": MSG_CONNECT_SIGNAL, "object": object_id, "signal": signal})
        handlers.append(callback)

    def unwrap(self, value: Any) -> Any:
        """Turn published QObject references into proxies, recursively."""
        if isinstance(value, dict):
            if value.get("__QObject*__"):
                object_id = value["id"]
                if "data" in value:
                    if object_id in self.objects:
                        self.objects[object_id].load(value["data"])
                    else:
                        self.objects[object_id] = QObjectProxy(self, object_id, value["data"])
                return self.objects.get(object_id, object_id)
            return {key: self.unwrap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.unwrap(item) for item in value]
        return value

    def __getitem__(self, name: str) -> QObjectProxy:
        return self.objects[name]

    async def _read_loop(self) -> None:
        if self._ws is None:
            return
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                data = json.loads(msg.data)
                try:
                    self._handle_message(data)
                except Exception:  # noqa: BLE001 - one bad message must not drop the channel
                    LOGGER.exception("Error handling WebPipe message type %s", data.get("type"))
                if data.get("type") == MSG_PROPERTY_UPDATE:
                    # The server sends the next batch of updates only after Idle
                    await self.send({"type": MSG_IDLE})
        except aiohttp.ClientError, ConnectionError, WebPipeError:
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(WebPipeError("WebPipe connection closed"))
            if self._ws is not None and not self._ws.closed:
                await self._ws.close()
            self._on_disconnect()

    def _handle_message(self, data: dict[str, Any]) -> None:
        kind = data.get("type")
        if kind == MSG_RESPONSE:
            future = self._pending.get(data.get("id"))
            if future is not None and not future.done():
                future.set_result(self.unwrap(data.get("data")))
        elif kind == MSG_PROPERTY_UPDATE:
            self._apply_updates(data.get("data", []))
        elif kind == MSG_SIGNAL:
            args = self.unwrap(data.get("args", []))
            for handler in self._signal_handlers.get((data.get("object"), data.get("signal")), []):
                handler(args)

    def _apply_updates(self, updates: list[dict[str, Any]]) -> None:
        changed: set[str] = set()
        for update in updates:
            object_id = update.get("object")
            obj = self.objects.get(object_id) if isinstance(object_id, str) else None
            if obj is None:
                continue
            names = {index: name for name, index in obj.prop_index.items()}
            for index, value in update.get("properties", {}).items():
                name = names.get(int(index))
                if name is not None:
                    obj.props[name] = self.unwrap(value)
                    changed.add(f"{obj.id}.{name}")
        if changed:
            self._on_update(changed)
