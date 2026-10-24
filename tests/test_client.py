"""Tests for the WebPipe client against a fake SignalRGB."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import aiohttp
import pytest

from custom_components.signalrgb.client import SignalRGBClient
from custom_components.signalrgb.param_entity import (
    KIND_NUMBER,
    KIND_SELECT,
    KIND_SWITCH,
    KIND_TEXT,
    is_color_param,
    param_kind,
)
from custom_components.signalrgb.webpipe import WebPipeError


async def wait_for(predicate: Callable[[], bool], limit: float = 2) -> None:
    """Wait until predicate() is true (pushed updates arrive asynchronously)."""
    async with asyncio.timeout(limit):
        while not predicate():  # noqa: ASYNC110 - polling client state, no event to await
            await asyncio.sleep(0.01)


@pytest.fixture
async def client(fake_signalrgb):
    """A client connected to the fake WebPipe."""
    _fake, server = fake_signalrgb
    async with aiohttp.ClientSession() as session:
        client = SignalRGBClient(session, server.host, server.port)
        await client.connect()
        yield client
        await client.close()


async def test_connect_reads_state(client):
    """Initial state comes from the init message."""
    assert client.connected
    assert client.current_effect == "Aurora"
    assert client.effect_list == ["Aurora", "aurora borealis", "Rainbow"]
    assert client.layouts == ["Desk", "Full"]
    assert client.current_layout == "Desk"
    assert client.brightness == 100
    assert client.is_on
    assert client.effect_attributes()["effect_name"] == "Aurora"


async def test_connect_failure_raises(allow_localhost_sockets):
    """An unreachable WebPipe raises WebPipeError."""
    async with aiohttp.ClientSession() as session:
        client = SignalRGBClient(session, "127.0.0.1", 1)
        with pytest.raises(WebPipeError):
            await client.connect()


async def test_apply_effect_and_push(fake_signalrgb, client):
    """Applying an effect calls setAlwaysEffect and the pushed update is seen."""
    fake, _server = fake_signalrgb
    updates = []
    client.add_listener(lambda: updates.append(client.current_effect))

    await client.apply_effect("Rainbow")
    await wait_for(lambda: client.current_effect == "Rainbow")

    assert ("lighting", "setAlwaysEffect(QString)", ["Rainbow"]) in fake.calls
    assert "Rainbow" in updates


async def test_unknown_effect_is_rejected(fake_signalrgb, client):
    """Unknown names never reach SignalRGB, which would fall back to a default effect."""
    fake, _server = fake_signalrgb
    with pytest.raises(WebPipeError):
        await client.apply_effect("No Such Effect")
    assert not [call for call in fake.calls if call[1] == "setAlwaysEffect(QString)"]


async def test_effect_navigation(fake_signalrgb, client):
    """Next/previous/random map to goForward/goBackward/goCrazy."""
    fake, _server = fake_signalrgb
    await client.next_effect()
    await client.previous_effect()
    await client.random_effect()
    navigation = [call[1] for call in fake.calls if call[0] == "lighting"]
    assert navigation == ["goForward()", "goBackward()", "goCrazy()"]


async def test_layout(fake_signalrgb, client):
    """Layouts load by name; unknown names are rejected."""
    await client.set_layout("Full")
    await wait_for(lambda: client.current_layout == "Full")
    with pytest.raises(WebPipeError):
        await client.set_layout("Missing")


async def test_brightness_off_and_restore(fake_signalrgb, client):
    """Off sets every endpoint to 0; restore brings back each device's own level."""
    fake, _server = fake_signalrgb
    levels = client.brightness_levels
    assert levels == {"kbd": 80, "fan": 100}

    await client.set_brightness(0)
    await wait_for(lambda: all(ep.props["Brightness"] == 0 for ep in fake.endpoints))
    assert not client.is_on

    await client.restore_brightness(levels, default=100)
    await wait_for(lambda: fake.endpoints[0].props["Brightness"] == 80)
    assert client.brightness_levels == {"kbd": 80, "fan": 100}


async def test_set_brightness_clamps(fake_signalrgb, client):
    """Levels outside 0-100 are clamped."""
    fake, _server = fake_signalrgb
    await client.set_brightness(150)
    await wait_for(lambda: all(ep.props["Brightness"] == 100 for ep in fake.endpoints))


async def test_effect_params(fake_signalrgb, client):
    """Parameters of the running effect are listed and written live."""
    fake, _server = fake_signalrgb
    assert [param.get("name") for param in client.effect_params] == [
        "speed",
        "frontColor",
        "cycle",
        "mode",
    ]

    await client.set_effect_param("speed", 70)
    await wait_for(lambda: fake.params[0].props["value"] == 70)
    assert client.effect_param("speed").get("value") == 70

    with pytest.raises(WebPipeError):
        await client.set_effect_param("missing", 1)


async def test_effect_params_follow_rebuild(fake_signalrgb, client):
    """When SignalRGB rebuilds the parameter objects, writes go to the new ones."""
    fake, _server = fake_signalrgb
    old_id = client.effect_param("speed").id

    await fake.rebuild_params()
    await wait_for(lambda: client.effect_param("speed").id != old_id)

    await client.set_effect_param("speed", 55)
    await wait_for(lambda: fake.params[0].props["value"] == 55)


async def test_auto_advance(fake_signalrgb, client):
    """Rotation interval is given in seconds and sent to SignalRGB in milliseconds."""
    fake, _server = fake_signalrgb
    assert not client.auto_advance
    assert client.auto_advance_interval == 300

    await client.set_auto_advance(True)
    await wait_for(lambda: client.auto_advance)

    await client.set_auto_advance_interval(60)
    await wait_for(lambda: client.auto_advance_interval == 60)
    assert ("{timer}", "SetInterval(int)", [60000]) in fake.calls


class Param:
    """Stand-in for a parameter object."""

    def __init__(self, props):
        self.props = props

    def get(self, name, default=None):
        return self.props.get(name, default)


async def test_param_kind(fake_signalrgb):
    """SignalRGB editors map to the entity kind that controls them."""
    fake, _server = fake_signalrgb
    kinds = [param_kind(Param(param.props)) for param in fake.params]
    assert kinds == [KIND_NUMBER, KIND_TEXT, KIND_SWITCH, KIND_SELECT]


def test_hue_param_is_a_number():
    """Hue parameters use a "Color" editor but hold a number, not a #rrggbb color."""
    hue = Param(
        {"name": "hueBase", "editor": "PropColorslider.qml", "value": 0, "min": 0, "max": 360}
    )
    assert param_kind(hue) == KIND_NUMBER
    assert not is_color_param(hue)
    assert is_color_param(Param({"editor": "PropColorpicker.qml", "value": "#00ff7f"}))
    assert not is_color_param(Param({"editor": "PropColorpicker.qml", "value": "#fff"}))


async def test_failing_listener_keeps_connection(fake_signalrgb, client):
    """An entity that raises while updating must not drop the channel."""

    def broken_listener():
        raise ValueError("entity rejected its state")

    client.add_listener(broken_listener)
    await client.apply_effect("Rainbow")
    await wait_for(lambda: client.current_effect == "Rainbow")
    await asyncio.sleep(0.1)
    assert client.connected
