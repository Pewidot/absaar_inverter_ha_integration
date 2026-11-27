"""Config flow for Absaar Inverter integration."""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .api import AbsaarAPI, AbsaarAuthError, AbsaarConnectionError
from .const import (
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


STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def validate_credentials(
    hass: HomeAssistant, username: str, password: str
) -> dict:
    """Validate the user credentials by attempting to login.

    Raises AbsaarAuthError for rejected credentials and AbsaarConnectionError
    when the cloud cannot be reached.
    """
    api = AbsaarAPI(username, password)
    await hass.async_add_executor_job(api.authenticate)
    return {"token": api.token, "user_id": api.user_id}


async def _credential_errors(hass: HomeAssistant, username: str, password: str) -> dict:
    """Try the credentials and return form errors (empty when they work)."""
    try:
        await validate_credentials(hass, username, password)
    except AbsaarAuthError:
        return {"base": "invalid_auth"}
    except AbsaarConnectionError:
        return {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected error while validating Absaar credentials")
        return {"base": "unknown"}
    return {}


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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> "AbsaarOptionsFlow":
        """Return the options flow handler."""
        return AbsaarOptionsFlow(config_entry)

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
            errors = await _credential_errors(
                self.hass,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )

            if not errors:
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

        return self.async_show_form(
            step_id="cloud",
            data_schema=STEP_CLOUD_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Start reauth after the cloud rejected the stored password."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> FlowResult:
        """Ask for a new password for the same cloud username."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        username = entry.data[CONF_USERNAME]
        errors = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            errors = await _credential_errors(self.hass, username, password)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PASSWORD: password}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"username": username},
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


class AbsaarOptionsFlow(config_entries.OptionsFlow):
    """Adjust local-connection settings without re-creating the entry.

    Needed in practice because the datalogger's IP can change (DHCP) —
    re-creating the entry would orphan the entities' statistics.
    """

    def __init__(self, config_entry) -> None:
        """Initialize the options flow."""
        self._entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Show and store the adjustable local settings."""
        if (
            self._entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_CLOUD)
            != CONNECTION_TYPE_LOCAL
        ):
            return self.async_abort(reason="cloud_has_no_options")

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def current(key, default):
            return self._entry.options.get(key, self._entry.data.get(key, default))

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DATALOGGER_URL,
                    default=current(CONF_DATALOGGER_URL, ""),
                ): str,
                vol.Optional(
                    CONF_DATALOGGER_USERNAME,
                    default=current(
                        CONF_DATALOGGER_USERNAME, DEFAULT_DATALOGGER_USERNAME
                    ),
                ): str,
                vol.Optional(
                    CONF_DATALOGGER_PASSWORD,
                    default=current(
                        CONF_DATALOGGER_PASSWORD, DEFAULT_DATALOGGER_PASSWORD
                    ),
                ): str,
                vol.Optional(
                    CONF_LISTENER_IP,
                    default=current(CONF_LISTENER_IP, ""),
                ): str,
                vol.Optional(
                    CONF_POLL_DELAY,
                    default=current(CONF_POLL_DELAY, DEFAULT_POLL_DELAY),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Optional(
                    CONF_IP_CHECK_INTERVAL,
                    default=current(CONF_IP_CHECK_INTERVAL, DEFAULT_IP_CHECK_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
