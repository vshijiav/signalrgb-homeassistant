"""The SignalRGB integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .client import SignalRGBClient
from .const import DOMAIN, LOGGER, PLATFORMS
from .webpipe import WebPipeError

# This integration only supports configuration via config entries
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SignalRGBConfigEntry = ConfigEntry[SignalRGBClient]


async def async_setup(_hass: HomeAssistant, _config: dict[str, Any]) -> bool:
    """Set up the SignalRGB component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SignalRGBConfigEntry) -> bool:
    """Set up SignalRGB from a config entry."""
    LOGGER.debug("Setting up SignalRGB integration for %s", entry.data[CONF_HOST])

    client = SignalRGBClient(
        async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT]
    )
    try:
        await client.connect()
    except WebPipeError as err:
        LOGGER.warning("Cannot reach SignalRGB WebPipe at %s — will retry: %s", client.url, err)
        raise ConfigEntryNotReady(f"Cannot connect to SignalRGB: {err}") from err

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    LOGGER.info("SignalRGB integration setup completed for %s", entry.data[CONF_HOST])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SignalRGBConfigEntry) -> bool:
    """Unload a config entry."""
    LOGGER.debug("Unloading SignalRGB integration for %s", entry.data[CONF_HOST])

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.close()
        LOGGER.info("SignalRGB integration unloaded for %s", entry.data[CONF_HOST])
    else:
        LOGGER.warning("Failed to unload SignalRGB integration for %s", entry.data[CONF_HOST])

    return bool(unload_ok)
