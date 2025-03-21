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
        
        # ✅ Hole dailyPowerGeneration aus den Stations-Daten
        daily_power = station["dailyPowerGeneration"]
        # ✅ Create the sensor for total production
        total_power = station["totalPowerGeneration"]
        entities.append(AbsaarStationSensor(f"{station['powerName']} totalPowerGeneration", power_id, token, total_power, "kWh"))

        
        # ✅ Erstelle den Sensor für die tägliche Produktion
        entities.append(AbsaarStationSensor(f"{station['powerName']} dailyPowerGeneration", power_id, token, daily_power, "kWh"))
        
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
            entities.append(AbsaarInverterSensor(f"{station['powerName']} Power", power_id, inverter_id, token, "acPower", "W"))

            # Weitere Sensoren für wichtige Werte
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
        self._name = name
        self._power_id = power_id
        self._inverter_id = inverter_id
        self._token = token
        self._sensor_key = sensor_key
        self._unit = unit
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

class AbsaarStationSensor(SensorEntity):
    """Sensor for station data (daily production)"""
    def __init__(self, name, power_id, token, value, unit):
        self._name = name
        #self._userid = userid
        self._power_id = power_id
        self._token = token
        self._state = value
        self._unit = unit
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
        data = get_stations(user_id, self._token)

        if not data or "rows" not in data or not data["rows"]:
            _LOGGER.warning("No station data received for ID %s", self._power_id)
            self._state = "No Data"
            return

        station = data["rows"][0]
        self._state = station.get("dailyPowerGeneration", 0.0)
