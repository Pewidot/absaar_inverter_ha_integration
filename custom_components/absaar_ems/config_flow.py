"""Config flow for Absaar Inverter integration."""
import asyncio
import logging
import voluptuous as vol
import requests
import urllib3

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    BASE_URL,
    CONF_CONNECTION_TYPE,
    CONF_DATALOGGER_PASSWORD,
    CONF_DATALOGGER_URL,
    CONF_DATALOGGER_USERNAME,
    CONF_IP_CHECK_INTERVAL,
    CONF_LISTENER_IP,
    CONF_POLL_DELAY,
    CONF_SERIAL,
    CONNECTION_TYPE_CLOUD,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_DATALOGGER_PASSWORD,
    DEFAULT_DATALOGGER_USERNAME,
    DEFAULT_IP_CHECK_INTERVAL,
    DEFAULT_POLL_DELAY,
    DEFAULT_PORT,
    DOMAIN,
)

urllib3.disable_warnings()

_LOGGER = logging.getLogger(__name__)

STEP_CLOUD_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_LOCAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1024, max=65535)
        ),
        vol.Optional(CONF_SERIAL, default=""): str,
        vol.Optional(CONF_POLL_DELAY, default=DEFAULT_POLL_DELAY): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=60)
        ),
        vol.Optional(CONF_DATALOGGER_URL, default=""): str,
        vol.Optional(
            CONF_DATALOGGER_USERNAME, default=DEFAULT_DATALOGGER_USERNAME
        ): str,
        vol.Optional(
            CONF_DATALOGGER_PASSWORD, default=DEFAULT_DATALOGGER_PASSWORD
        ): str,
        vol.Optional(CONF_LISTENER_IP, default=""): str,
        vol.Optional(
            CONF_IP_CHECK_INTERVAL, default=DEFAULT_IP_CHECK_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
    }
)


async def validate_credentials(hass: HomeAssistant, username: str, password: str) -> dict:
    """Validate the user credentials by attempting to login."""
    url = f"{BASE_URL}/dn/userLogin"
    headers = {
        "User-Agent": "okhttp-okgo/jeasonlzy",
        "Content-Type": "application/json;charset=utf-8",
    }
    payload = {"username": username, "password": password}

    try:
        response = await hass.async_add_executor_job(
            lambda: requests.post(url, headers=headers, json=payload, verify=False, timeout=10)
        )
        data = response.json()

        if response.status_code == 200 and "token" in data:
            return {"token": data["token"], "user_id": data["userId"]}
        else:
            _LOGGER.error("Login failed: %s", data)
            return None
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Error during login: %s", e)
        return None


async def _port_is_free(port: int) -> bool:
    """Check that the local listener port can be bound."""
    try:
        server = await asyncio.start_server(lambda r, w: None, "0.0.0.0", port)
    except OSError:
        return False
    server.close()
    await server.wait_closed()
    return True


class AbsaarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Absaar Inverter."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Let the user pick between cloud and local connection."""
        return self.async_show_menu(
            step_id="user",
            menu_options=[CONNECTION_TYPE_CLOUD, CONNECTION_TYPE_LOCAL],
        )

    async def async_step_cloud(self, user_input=None) -> FlowResult:
        """Configure a cloud (mini-ems.com) connection."""
        errors = {}

        if user_input is not None:
            result = await validate_credentials(
                self.hass,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )

            if result:
                # Same unique ID as pre-2.0.0 entries so upgrades stay compatible
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Absaar ({user_input[CONF_USERNAME]})",
                    data={
                        **user_input,
                        CONF_CONNECTION_TYPE: CONNECTION_TYPE_CLOUD,
                    },
                )
            else:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="cloud",
            data_schema=STEP_CLOUD_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_local(self, user_input=None) -> FlowResult:
        """Configure a local (direct TCP) connection."""
        errors = {}

        if user_input is not None:
            port = user_input[CONF_PORT]

            await self.async_set_unique_id(f"local_{port}")
            self._abort_if_unique_id_configured()

            if not await _port_is_free(port):
                errors["base"] = "port_in_use"
            else:
                return self.async_create_entry(
                    title=f"Absaar Local (port {port})",
                    data={
                        **user_input,
                        CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL,
                    },
                )

        return self.async_show_form(
            step_id="local",
            data_schema=STEP_LOCAL_DATA_SCHEMA,
            errors=errors,
        )
