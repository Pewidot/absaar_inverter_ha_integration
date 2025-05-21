import logging
import requests
import voluptuous as vol
from datetime import timedelta
from cachetools import TTLCache, cached
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

# Disable warnings about unsecure HTTPS requests
import urllib3

urllib3.disable_warnings()

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://mini-ems.com:8081"
SCAN_INTERVAL = timedelta(minutes=2)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)

# Cache data long enough for the calls from one scan but short enough to be
# updated on the next scan
stations_cache = TTLCache(maxsize=100, ttl=60)
collectors_cache = TTLCache(maxsize=100, ttl=60)
inverters_cache = TTLCache(maxsize=100, ttl=60)


def login(username, password):
    """Login to API and get authentication token"""
    url = f"{BASE_URL}/dn/userLogin"
    headers = {
        "User-Agent": "okhttp-okgo/jeasonlzy",
        "Content-Type": "application/json;charset=utf-8",
    }
    payload = {"username": username, "password": password}

    try:
        response = requests.post(url, headers=headers, json=payload, verify=False)
        data = response.json()
        if response.status_code == 200 and "token" in data:
            return data["token"], data["userId"]
        else:
            _LOGGER.error("Login failed: %s", data)
            return None, None
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Error during login: %s", e)
        return None, None


@cached(stations_cache)
def get_stations(user_id, token):
    """Fetch station list"""
    url = f"{BASE_URL}/dn/power/station/listApp"
    headers = {"Authorization": str(token)}
    payload = {"userId": str(user_id)}

    try:
        response = requests.post(url, headers=headers, data=payload, verify=False)
        return response.json()
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Error fetching stations: %s", e)
        return None


@cached(collectors_cache)
def get_collectors(power_id, token):
    """Fetch collector list"""
    url = f"{BASE_URL}/dn/power/collector/listByApp"
    headers = {"Authorization": str(token)}
    payload = {"powerId": str(power_id)}

    try:
        response = requests.post(url, headers=headers, json=payload, verify=False)
        return response.json()
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Error fetching collectors: %s", e)
        return None


@cached(inverters_cache)
def get_inverter_data(power_id, inverter_id, token):
    """Fetch inverter data"""
    url = f"{BASE_URL}/dn/power/inverterData/inverterDatalist"
    headers = {"Authorization": token}
    payload = {"powerId": power_id, "inverterId": inverter_id}

    try:
        response = requests.post(url, headers=headers, json=payload, verify=False)
        return response.json()
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Error fetching inverter data: %s", e)
        return None


user_id = ""


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the sensor platform"""
    username = config[CONF_USERNAME]
    password = config[CONF_PASSWORD]

    token, user_id = login(username, password)
    if not token:
        _LOGGER.error("Authentication failed")
        return

    stations = get_stations(user_id, token)
    if not stations or "rows" not in stations:
        _LOGGER.error("No stations found")
        return

    entities = []
    for station in stations.get("rows", []):
        power_id = station["powerId"]

        # Hole dailyPowerGeneration aus den Stations-Daten
        daily_power = station["dailyPowerGeneration"]
        # Create the sensor for total production
        total_power = station["totalPowerGeneration"]
        entities.append(AbsaarStationSensor(f"{station['powerName']} totalPowerGeneration", power_id, token, total_power, "kWh"))

        # Erstelle den Sensor f++r die t+ñgliche Produktion
        entities.append(AbsaarStationSensor(f"{station['powerName']} dailyPowerGeneration", power_id, token, daily_power, "kWh"))

        collectors = get_collectors(power_id, token)
        if not collectors or "rows" not in collectors:
            _LOGGER.warning("No collectors found for station %s", station["powerName"])
            continue

        for collector in collectors.get("rows", []):
            inverter_id = collector["inverterId"]

            # Hauptsensor f++r Inverter-Leistung
            entities.append(AbsaarInverterSensor(f"{station['powerName']} Power", power_id, inverter_id, token, "acPower", "W"))

            # Weitere Sensoren f++r wichtige Werte
            for key, unit in [
                ("acVoltage", "V"),
                ("acFrequency", "Hz"),
                ("pv1Power", "W"),
                ("pv2Power", "W"),
                ("temperature", "°C"),
                ("pv1Voltage", "V"),
                ("pv1Electric", "A"),
                ("pv2Voltage", "V"),
                ("pv2Electric", "A"),
                ("acElectric", "A"),
                ("inPower", "W"),
            ]:
                entities.append(AbsaarInverterSensor(f"{station['powerName']} {key}", power_id, inverter_id, token, key, unit))

    add_entities(entities, True)


class AbsaarInverterSensor(SensorEntity):
    """Sensor for inverter data"""

    def __init__(self, name, power_id, inverter_id, token, sensor_key, unit):
        self._power_id = power_id
        self._inverter_id = inverter_id
        self._token = token
        self._sensor_key = sensor_key
        self._power_id = power_id
        self._inverter_id = inverter_id
        self._token = token
        self._sensor_key = sensor_key

        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = self._infer_device_class(unit)
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_extra_state_attributes = {}

    def _infer_device_class(self, unit):
        return {
            "W": "power",
            "V": "voltage",
            "A": "current",
            "°C": "temperature",
            "Hz": "frequency"
        }.get(unit)

    def update(self):
        data = get_inverter_data(self._power_id, self._inverter_id, self._token)

        if not data or "rows" not in data or not data["rows"]:
            _LOGGER.warning("No inverter data received for ID %s", self._inverter_id)
            self._attr_native_value = None
            self._attr_available = False
            return

        inverter = data["rows"][0]
        self._attr_native_value = inverter.get(self._sensor_key, 0.0)


class AbsaarStationSensor(SensorEntity):
    """Sensor for station data (e.g. daily or total energy production)"""

    def __init__(self, name, power_id, token, value, unit):
        self._power_id = power_id
        self._token = token
        # Set attributes for HA's base class to pick up
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_native_value = value
        self._attr_device_class = SensorDeviceClass.ENERGY if unit == "kWh" else None
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING if unit == "kWh" else None
        self._attr_extra_state_attributes = {}

    def update(self):
        data = get_stations(user_id, self._token)

        if not data or "rows" not in data or not data["rows"]:
            _LOGGER.warning("No station data received for ID %s", self._power_id)
            self._attr_native_value = None
            self._attr_available = False
            return

        station = data["rows"][0]
        self._attr_native_value = station.get("dailyPowerGeneration", 0.0)

