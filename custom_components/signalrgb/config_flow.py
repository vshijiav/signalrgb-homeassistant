"""Config flow for SignalRGB integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .client import SignalRGBClient
from .const import DEFAULT_PORT, DOMAIN, LOGGER
from .webpipe import WebPipeError

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class SignalRGBConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SignalRGB."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        client = SignalRGBClient(
            async_get_clientsession(self.hass), user_input[CONF_HOST], user_input[CONF_PORT]
        )
        try:
            LOGGER.debug("Testing connection to SignalRGB WebPipe at %s", client.url)
            await client.connect()
        except WebPipeError as err:
            LOGGER.error("Failed to connect to SignalRGB WebPipe at %s: %s", client.url, err)
            errors["base"] = "cannot_connect"
        except Exception as err:  # pylint: disable=broad-except # noqa: BLE001
            LOGGER.exception("Unexpected error while setting up SignalRGB: %s", err)
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)
        finally:
            await client.close()

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)
