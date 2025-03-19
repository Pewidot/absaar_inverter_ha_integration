import logging
import requests
import json
import voluptuous as vol
from datetime import timedelta
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://mini-ems.com:8081"
SCAN_INTERVAL = timedelta(minutes=2)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)

def login(username, password):
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

def get_stations(user_id, token):
    url = f"{BASE_URL}/dn/power/station/listApp"
    headers = {"Authorization": token}
    payload = {"userId": user_id}

    try:
        response = requests.post(url, headers=headers, data=payload, verify=False)
        return response.json()
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Error fetching stations: %s", e)
        return None

def get_collectors(power_id, token):
    url = f"{BASE_URL}/dn/power/collector/listByApp"
    headers = {"Authorization": token}
    payload = {"powerId": power_id}

    try:
        response = requests.post(url, headers=headers, json=payload, verify=False)
        return response.json()
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Error fetching collectors: %s", e)
        return None

def get_inverter_data(power_id, inverter_id, token):
    url = f"{BASE_URL}/dn/power/inverterData/inverterDatalist"
    headers = {"Authorization": token}
    payload = {"powerId": power_id, "inverterId": inverter_id}

    try:
        response = requests.post(url, headers=headers, json=payload, verify=False)
        return response.json()
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Error fetching inverter data: %s", e)
        return None
def setup_platform(hass, config, add_entities, discovery_info=None):
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
        collectors = get_collectors(power_id, token)
        if not collectors or "rows" not in collectors:
            _LOGGER.warning("No collectors found for station %s", station["powerName"])
            continue

        for collector in collectors.get("rows", []):
            inverter_id = collector["inverterId"]
            inverter_data = get_inverter_data(power_id, inverter_id, token)
            if not inverter_data or "rows" not in inverter_data or not inverter_data["rows"]:
                _LOGGER.warning("No inverter data found for %s", collector["collectorName"])
                continue

            inverter = inverter_data["rows"][0]

            # Hauptsensor für Inverter-Leistung
            entities.append(AbsaarInverterSensor(f"{station['powerName']} Leistung", power_id, inverter_id, token, "acPower", "W"))

            # Weitere Sensoren für wichtige Werte
            for key, unit in [
                ("acVoltage", "V"),
                ("acFrequency", "Hz"),
                ("dcPower", "W"),
                ("pv1Voltage", "V"),
                ("pv1Electric", "A"),
                ("pv1Power", "W"),
                ("pv2Voltage", "V"),
                ("pv2Electric", "A"),
                ("pv2Power", "W"),
                ("temperature", "°C"),
                ("batteryVoltage", "V"),
                ("batteryCurrent", "A"),
                ("batteryPower", "W"),
                ("loadPower", "W"),
                ("controllerTemperature", "°C"),
            ]:
                entities.append(AbsaarInverterSensor(f"{station['powerName']} {key}", power_id, inverter_id, token, key, unit))

    add_entities(entities, True)

class AbsaarInverterSensor(SensorEntity):
    def __init__(self, name, power_id, inverter_id, token, sensor_key, unit):
        self._name = name
        self._power_id = power_id
        self._inverter_id = inverter_id
        self._token = token
        self._sensor_key = sensor_key  # Welcher Wert abgefragt wird (z.B. "acPower")
        self._unit = unit  # Einheit des Wertes (z.B. "W")
        self._state = None
        self._attributes = {}

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def extra_state_attributes(self):
        return self._attributes

    def update(self):
        data = get_inverter_data(self._power_id, self._inverter_id, self._token)

        if not data or "rows" not in data or not data["rows"]:
            _LOGGER.warning("No inverter data received for ID %s", self._inverter_id)
            self._state = "No Data"
            return

        inverter = data["rows"][0]  
        self._state = inverter.get(self._sensor_key, 0.0)  

        self._attributes = {
            "power_id": self._power_id,
            "inverter_id": self._inverter_id,
            "equipment_model": inverter.get("equipmentModel", ""),
            "run_status": inverter.get("runStatus", "unknown"),
        }
