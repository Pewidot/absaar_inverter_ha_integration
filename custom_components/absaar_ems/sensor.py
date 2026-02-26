"""Sensor platform for Absaar Inverter integration."""
import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Absaar sensors from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []

    # Get data from coordinator
    data = coordinator.data

    if not data or "stations" not in data:
        _LOGGER.warning("No station data available")
        return

    for station in data["stations"]:
        power_id = station["power_id"]
        power_name = station["power_name"]

        # Station-level sensors
        entities.append(
            AbsaarStationSensor(
                coordinator,
                power_id,
                power_name,
                "dailyPowerGeneration",
                "Daily Power Generation",
                "kWh",
            )
        )
        entities.append(
            AbsaarStationSensor(
                coordinator,
                power_id,
                power_name,
                "totalPowerGeneration",
                "Total Power Generation",
                "kWh",
            )
        )

        # Inverter sensors
        for collector in station.get("collectors", []):
            inverter_id = collector["inverter_id"]
            collector_name = collector["collector_name"]

            # Define sensors with their keys and units
            sensor_definitions = [
                ("acPower", "AC Power", "W", SensorDeviceClass.POWER),
                ("acVoltage", "AC Voltage", "V", SensorDeviceClass.VOLTAGE),
                ("acFrequency", "AC Frequency", "Hz", SensorDeviceClass.FREQUENCY),
                ("acElectric", "AC Current", "A", SensorDeviceClass.CURRENT),
                ("pv1Power", "PV1 Power", "W", SensorDeviceClass.POWER),
                ("pv2Power", "PV2 Power", "W", SensorDeviceClass.POWER),
                ("pv1Voltage", "PV1 Voltage", "V", SensorDeviceClass.VOLTAGE),
                ("pv2Voltage", "PV2 Voltage", "V", SensorDeviceClass.VOLTAGE),
                ("pv1Electric", "PV1 Current", "A", SensorDeviceClass.CURRENT),
                ("pv2Electric", "PV2 Current", "A", SensorDeviceClass.CURRENT),
                ("inPower", "Input Power", "W", SensorDeviceClass.POWER),
                ("temperature", "Temperature", "°C", SensorDeviceClass.TEMPERATURE),
            ]

            for sensor_key, sensor_name, unit, device_class in sensor_definitions:
                entities.append(
                    AbsaarInverterSensor(
                        coordinator,
                        power_id,
                        power_name,
                        inverter_id,
                        collector_name,
                        sensor_key,
                        sensor_name,
                        unit,
                        device_class,
                    )
                )

    async_add_entities(entities)


class AbsaarStationSensor(CoordinatorEntity, SensorEntity):
    """Sensor for station-level data."""

    def __init__(
        self,
        coordinator,
        power_id: str,
        power_name: str,
        sensor_key: str,
        sensor_name: str,
        unit: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._power_id = power_id
        self._power_name = power_name
        self._sensor_key = sensor_key
        self._attr_name = f"{power_name} {sensor_name}"
        self._attr_unique_id = f"{power_id}_{sensor_key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "stations" not in self.coordinator.data:
            return None

        for station in self.coordinator.data["stations"]:
            if station["power_id"] == self._power_id:
                return station.get(self._sensor_key)

        return None

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self._power_id)},
            "name": f"Absaar {self._power_name}",
            "manufacturer": "Absaar",
            "model": "EMS Station",
        }


class AbsaarInverterSensor(CoordinatorEntity, SensorEntity):
    """Sensor for inverter data."""

    def __init__(
        self,
        coordinator,
        power_id: str,
        power_name: str,
        inverter_id: str,
        collector_name: str,
        sensor_key: str,
        sensor_name: str,
        unit: str,
        device_class: SensorDeviceClass,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._power_id = power_id
        self._power_name = power_name
        self._inverter_id = inverter_id
        self._collector_name = collector_name
        self._sensor_key = sensor_key
        self._attr_name = f"{power_name} {sensor_name}"
        self._attr_unique_id = f"{inverter_id}_{sensor_key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or "stations" not in self.coordinator.data:
            return None

        for station in self.coordinator.data["stations"]:
            if station["power_id"] == self._power_id:
                for collector in station.get("collectors", []):
                    if collector["inverter_id"] == self._inverter_id:
                        return collector.get("data", {}).get(self._sensor_key)

        return None

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self._inverter_id)},
            "name": f"Absaar {self._collector_name}",
            "manufacturer": "Absaar",
            "model": "Inverter",
            "via_device": (DOMAIN, self._power_id),
        }
