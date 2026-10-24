"""Constants for the SignalRGB integration."""

from logging import getLogger

from homeassistant.const import Platform

DOMAIN = "signalrgb"

LOGGER = getLogger(__package__)

# Port of the LAN relay in front of SignalRGB's localhost-only WebPipe (16036)
DEFAULT_PORT = 16046
DEFAULT_NAME = "SignalRGB"

# Device info
MANUFACTURER = "WhirlwindFX"
MODEL = "SignalRGB"

# Icon
ICON = "mdi:led-strip-variant"

# Platforms
PLATFORMS = [
    Platform.LIGHT,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.TEXT,
]
