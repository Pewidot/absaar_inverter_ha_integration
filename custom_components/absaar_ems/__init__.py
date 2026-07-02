"""The Absaar Inverter integration."""
import logging
from datetime import timedelta

import homeassistant.util.dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
from .api import AbsaarAPI
from .local import AbsaarLocalHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
SCAN_INTERVAL = timedelta(minutes=2)

# Guard against the spurious morning "daily generation" spike. When the
# inverter powers back up around sunrise it briefly re-reports the *previous*
# day's daily total before its internal register resets (observed ~05:30,
# cleared ~06:05). Because the daily sensor is TOTAL_INCREASING, that jump
# would otherwise be counted as real production on the Energy Dashboard.
#
# _POWER_MARGIN: headroom over the currently measured AC power when deciding
#   how much energy could plausibly have been produced since the last reading.
# _MIN_DAILY_STEP_KWH: always-allowed absolute step, so metering quantisation
#   of real (small) increments is never mistaken for the spike.
# _DATA_TIME_KEYS: candidate field names for the inverter data timestamp used
#   by the secondary "not dated today" check (auto-detected; no-op if absent).
_POWER_MARGIN = 4.0
_MIN_DAILY_STEP_KWH = 0.1
_DATA_TIME_KEYS = (
    "collectTime",
    "dataTime",
    "updateTime",
    "createTime",
    "uploadTime",
    "reportTime",
    "gmtModified",
    "gmtCreate",
    "time",
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Absaar Inverter from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Entries created before 2.0.0 have no connection_type and are cloud.
    connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_CLOUD)

    if connection_type == CONNECTION_TYPE_LOCAL:
        hub = AbsaarLocalHub(
            hass,
            entry.entry_id,
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
            serial=entry.data.get(CONF_SERIAL, ""),
            poll_delay=entry.data.get(CONF_POLL_DELAY, DEFAULT_POLL_DELAY),
            datalogger_url=entry.data.get(CONF_DATALOGGER_URL, ""),
            datalogger_username=entry.data.get(
                CONF_DATALOGGER_USERNAME, DEFAULT_DATALOGGER_USERNAME
            ),
            datalogger_password=entry.data.get(
                CONF_DATALOGGER_PASSWORD, DEFAULT_DATALOGGER_PASSWORD
            ),
            listener_ip=entry.data.get(CONF_LISTENER_IP, ""),
            ip_check_interval=entry.data.get(
                CONF_IP_CHECK_INTERVAL, DEFAULT_IP_CHECK_INTERVAL
            ),
        )
        try:
            await hub.async_start()
        except OSError as err:
            raise ConfigEntryNotReady(
                f"Cannot listen on TCP port {hub.port}: {err}"
            ) from err

        hass.data[DOMAIN][entry.entry_id] = {"hub": hub}
    else:
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]

        # Create API instance
        api = AbsaarAPI(username, password)

        # Authenticate
        if not await hass.async_add_executor_job(api.authenticate):
            _LOGGER.error("Failed to authenticate with Absaar API")
            return False

        # Create coordinator
        coordinator = AbsaarDataUpdateCoordinator(hass, api)

        # Fetch initial data
        await coordinator.async_config_entry_first_refresh()

        hass.data[DOMAIN][entry.entry_id] = {
            "coordinator": coordinator,
            "api": api,
        }

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        stored = hass.data[DOMAIN].pop(entry.entry_id)
        hub = stored.get("hub")
        if hub is not None:
            await hub.async_stop()

    return unload_ok


class AbsaarDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Absaar data."""

    def __init__(self, hass: HomeAssistant, api: AbsaarAPI) -> None:
        """Initialize."""
        self.api = api
        # Per-station last accepted daily value: power_id -> {"value", "time"}.
        self._daily_guard: dict[str, dict] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            data = await self.hass.async_add_executor_job(self.api.fetch_all_data)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        return self._sanitize_daily_generation(data)

    def _sanitize_daily_generation(self, data: dict) -> dict:
        """Drop the spurious morning spike in dailyPowerGeneration.

        Genuine resets (decreases toward 0 at midnight and at the ~06:05
        register reset) are always accepted. An *increase* is only accepted if
        it is physically achievable given the AC power currently being produced
        over the elapsed interval (B), and if the freshest inverter data isn't
        dated to a previous day (C). Otherwise the previous value is held.
        """
        now = dt_util.utcnow()
        today = dt_util.now().date()

        for station in data.get("stations", []):
            power_id = station.get("power_id")
            raw = station.get("dailyPowerGeneration")
            prev = self._daily_guard.get(power_id)

            if raw is None:
                # No fresh value this cycle; keep whatever we last exposed.
                if prev is not None:
                    station["dailyPowerGeneration"] = prev["value"]
                continue

            try:
                raw = float(raw)
            except (TypeError, ValueError):
                if prev is not None:
                    station["dailyPowerGeneration"] = prev["value"]
                continue

            # Cold start, or a reset/decrease (midnight rollover and the ~06:05
            # inverter register reset both look like a drop) -> always trust.
            if prev is None or raw <= prev["value"]:
                self._daily_guard[power_id] = {"value": raw, "time": now}
                station["dailyPowerGeneration"] = raw
                continue

            delta = raw - prev["value"]

            # (C) Freshest inverter data is from a previous day -> any positive
            # daily value is yesterday's carryover, not today's production.
            data_time = self._latest_data_time(station)
            stale_by_date = data_time is not None and data_time.date() < today

            # (B) Reject an increase larger than the produced power could
            # physically account for over the elapsed interval.
            power_w = self._total_ac_power(station)
            elapsed_h = max((now - prev["time"]).total_seconds(), 0.0) / 3600.0
            max_plausible = max(
                (power_w / 1000.0) * elapsed_h * _POWER_MARGIN, _MIN_DAILY_STEP_KWH
            )

            if stale_by_date or delta > max_plausible:
                _LOGGER.debug(
                    "absaar: holding dailyPowerGeneration for %s at %.3f kWh "
                    "(rejected %.3f: +%.3f kWh with %.0f W over %.2fh, "
                    "stale_by_date=%s)",
                    power_id, prev["value"], raw, delta, power_w, elapsed_h,
                    stale_by_date,
                )
                # Keep prev frozen; a genuine reset (decrease) will clear it.
                station["dailyPowerGeneration"] = prev["value"]
            else:
                self._daily_guard[power_id] = {"value": raw, "time": now}
                station["dailyPowerGeneration"] = raw

        return data

    @staticmethod
    def _total_ac_power(station: dict) -> float:
        """Sum the current AC power (W) across a station's collectors."""
        total = 0.0
        for collector in station.get("collectors", []):
            value = (collector.get("data") or {}).get("acPower")
            try:
                total += float(value)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _latest_data_time(station: dict):
        """Return the newest parseable inverter data timestamp, or None."""
        latest = None
        for collector in station.get("collectors", []):
            payload = collector.get("data") or {}
            for key in _DATA_TIME_KEYS:
                value = payload.get(key)
                if not value:
                    continue
                parsed = dt_util.parse_datetime(str(value))
                if parsed is None:
                    continue
                if latest is None or parsed > latest:
                    latest = parsed
        return latest
