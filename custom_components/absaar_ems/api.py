"""API client for Absaar Inverter."""
import logging
import requests
import urllib3

from .const import BASE_URL

urllib3.disable_warnings()

_LOGGER = logging.getLogger(__name__)


class AbsaarAPI:
    """API client for Absaar EMS."""

    def __init__(self, username: str, password: str):
        """Initialize the API client."""
        self.username = username
        self.password = password
        self.token = None
        self.user_id = None

    def authenticate(self) -> bool:
        """Authenticate with the API and obtain token."""
        url = f"{BASE_URL}/dn/userLogin"
        headers = {
            "User-Agent": "okhttp-okgo/jeasonlzy",
            "Content-Type": "application/json;charset=utf-8",
        }
        payload = {"username": self.username, "password": self.password}

        try:
            response = requests.post(
                url, headers=headers, json=payload, verify=False, timeout=10
            )
            data = response.json()

            if response.status_code == 200 and "token" in data:
                self.token = data["token"]
                self.user_id = data["userId"]
                _LOGGER.debug("Successfully authenticated with Absaar API")
                return True
            else:
                _LOGGER.error("Authentication failed: %s", data)
                return False
        except requests.exceptions.RequestException as e:
            _LOGGER.error("Error during authentication: %s", e)
            return False

    def _request(self, url: str, payload: dict, use_json: bool = True) -> dict | None:
        """Make an authenticated API request, re-authenticating on 401."""
        if not self.token:
            if not self.authenticate():
                return None

        headers = {"Authorization": str(self.token)}
        kwargs = {"json": payload} if use_json else {"data": payload}

        try:
            response = requests.post(
                url, headers=headers, verify=False, timeout=10, **kwargs
            )
            data = response.json()

            if response.status_code == 401 or data.get("code") == 401:
                _LOGGER.debug("Token expired, re-authenticating")
                if not self.authenticate():
                    _LOGGER.error("Re-authentication failed")
                    return None
                headers = {"Authorization": str(self.token)}
                response = requests.post(
                    url, headers=headers, verify=False, timeout=10, **kwargs
                )
                data = response.json()

            if response.status_code == 200 and data.get("code") == 200:
                return data
            else:
                _LOGGER.error("API request to %s failed: %s", url, data)
                return None
        except requests.exceptions.RequestException as e:
            _LOGGER.error("Error during API request to %s: %s", url, e)
            return None

    def get_stations(self) -> dict | None:
        """Fetch station list."""
        url = f"{BASE_URL}/dn/power/station/listApp"
        payload = {"userId": str(self.user_id)}
        return self._request(url, payload, use_json=False)

    def get_collectors(self, power_id: str) -> dict | None:
        """Fetch collector list for a station."""
        url = f"{BASE_URL}/dn/power/collector/listByApp"
        payload = {"powerId": str(power_id)}
        return self._request(url, payload)

    def get_inverter_data(self, power_id: str, inverter_id: str) -> dict | None:
        """Fetch inverter data."""
        url = f"{BASE_URL}/dn/power/inverterData/inverterDatalist"
        payload = {"powerId": power_id, "inverterId": inverter_id}
        return self._request(url, payload)

    def fetch_all_data(self) -> dict:
        """Fetch all data from the API with fresh authentication."""
        # Re-authenticate every fetch cycle to ensure fresh token
        if not self.authenticate():
            _LOGGER.error("Authentication failed during data fetch")
            raise ConnectionError("Failed to authenticate with Absaar API")

        stations_data = self.get_stations()

        if not stations_data or "rows" not in stations_data:
            _LOGGER.error("No stations found")
            raise ConnectionError("No station data received from Absaar API")

        all_data = {"stations": []}

        for station in stations_data.get("rows", []):
            power_id = station["powerId"]
            station_info = {
                "power_id": power_id,
                "power_name": station["powerName"],
                "dailyPowerGeneration": station.get("dailyPowerGeneration", 0),
                "totalPowerGeneration": station.get("totalPowerGeneration", 0),
                "collectors": [],
            }

            collectors = self.get_collectors(power_id)
            if collectors and "rows" in collectors:
                for collector in collectors.get("rows", []):
                    inverter_id = collector["inverterId"]
                    inverter_data = self.get_inverter_data(power_id, inverter_id)

                    if inverter_data and "rows" in inverter_data and inverter_data["rows"]:
                        collector_info = {
                            "inverter_id": inverter_id,
                            "collector_name": collector.get("collectorName", "Unknown"),
                            "data": inverter_data["rows"][0],
                        }
                        station_info["collectors"].append(collector_info)

            all_data["stations"].append(station_info)

        return all_data
