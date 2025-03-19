import logging
import requests
import json
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

DOMAIN = "absaar"

async def async_setup_entry(hass, config_entry):
    hass.data.setdefault(DOMAIN, {})
    return True
