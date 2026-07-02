"""Sensor platform for Absaar Inverter integration."""
import logging

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# key, name, unit, device_class for local (direct TCP) mode
LOCAL_SENSOR_DEFINITIONS = [
    ("ac_power", "AC Power", "W", SensorDeviceClass.POWER),
    ("ac_voltage", "AC Voltage", "V", SensorDeviceClass.VOLTAGE),
    ("ac_frequency", "AC Frequency", "Hz", SensorDeviceClass.FREQUENCY),
    ("pv1_power", "PV1 Power", "W", SensorDeviceClass.POWER),
    ("pv2_power", "PV2 Power", "W", SensorDeviceClass.POWER),
    ("pv_total_power", "PV Total Power", "W", SensorDeviceClass.POWER),
    ("pv1_voltage", "PV1 Voltage", "V", SensorDeviceClass.VOLTAGE),
    ("pv2_voltage", "PV2 Voltage", "V", SensorDeviceClass.VOLTAGE),
    ("pv1_current", "PV1 Current", "A", SensorDeviceClass.CURRENT),
    ("pv2_current", "PV2 Current", "A", SensorDeviceClass.CURRENT),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Absaar sensors from a config entry."""
    stored = hass.data[DOMAIN][config_entry.entry_id]

    if "hub" in stored:
        _setup_local_entities(stored["hub"], config_entry, async_add_entities)
        return

    coordinator = stored["coordinator"]

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


def _setup_local_entities(
    hub, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the entities for a local (direct TCP) connection."""
    entities = [
        AbsaarLocalSensor(
            hub,
            config_entry,
            key,
            name,
            unit,
            device_class,
            SensorStateClass.MEASUREMENT,
        )
        for key, name, unit, device_class in LOCAL_SENSOR_DEFINITIONS
    ]
    entities.append(
        AbsaarLocalEnergySensor(
            hub,
            config_entry,
            "total_energy",
            "Total Energy",
            "kWh",
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
        )
    )
    entities.append(AbsaarLocalStatusSensor(hub, config_entry))
    async_add_entities(entities)


class AbsaarLocalSensor(SensorEntity):
    """Sensor fed by the local TCP hub (push, no polling)."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hub,
        config_entry: ConfigEntry,
        key: str,
        name: str,
        unit: str,
        device_class: SensorDeviceClass,
        state_class: SensorStateClass,
    ):
        """Initialize the sensor."""
        self._hub = hub
        self._entry = config_entry
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{config_entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class

    async def async_added_to_hass(self):
        """Subscribe to hub updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._hub.signal, self._handle_update)
        )

    @callback
    def _handle_update(self):
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Measurements are only meaningful while the inverter is connected."""
        return self._hub.online

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._hub.data.get(self._key)

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "Absaar",
            "model": "Inverter (local)",
        }


class AbsaarLocalEnergySensor(AbsaarLocalSensor, RestoreSensor):
    """Lifetime energy counter; survives restarts and inverter downtime.

    The inverter is unpowered at night, so unlike the live measurements the
    total must stay available with its last known value (the Energy Dashboard
    derives the daily production from it).
    """

    def __init__(self, *args):
        """Initialize the sensor."""
        super().__init__(*args)
        self._restored = None

    async def async_added_to_hass(self):
        """Restore the last known total after a restart."""
        await super().async_added_to_hass()
        if self._hub.data.get(self._key) is None:
            last = await self.async_get_last_sensor_data()
            if last is not None and last.native_value is not None:
                try:
                    self._restored = float(last.native_value)
                except (TypeError, ValueError):
                    self._restored = None

    @property
    def native_value(self):
        """Return the live total, falling back to the restored value."""
        live = self._hub.data.get(self._key)
        return live if live is not None else self._restored

    @property
    def available(self) -> bool:
        """Available as soon as any total is known."""
        return self.native_value is not None


class AbsaarLocalStatusSensor(SensorEntity):
    """Connection status of the inverter datalogger."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hub, config_entry: ConfigEntry):
        """Initialize the sensor."""
        self._hub = hub
        self._entry = config_entry
        self._attr_name = "Status"
        self._attr_unique_id = f"{config_entry.entry_id}_status"

    async def async_added_to_hass(self):
        """Subscribe to hub updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._hub.signal, self._handle_update)
        )

    @callback
    def _handle_update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return online/offline."""
        return "online" if self._hub.online else "offline"

    @property
    def extra_state_attributes(self):
        """Expose serial and last packet time."""
        return {
            "serial": self._hub.serial or None,
            "last_seen": self._hub.last_seen.isoformat() if self._hub.last_seen else None,
        }

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "Absaar",
            "model": "Inverter (local)",
        }
