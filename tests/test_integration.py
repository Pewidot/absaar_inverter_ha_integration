"""Exercise installation, UI flows and existing config entries in Home Assistant."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.absaar.const import DOMAIN

CLOUD_DATA = {
    "stations": [
        {
            "power_id": "test-station",
            "power_name": "Test station",
            "dailyPowerGeneration": 1.2,
            "totalPowerGeneration": 100.5,
            "collectors": [
                {
                    "inverter_id": "test-inverter",
                    "collector_name": "Test inverter",
                    "data": {"acPower": 400, "acVoltage": 230},
                }
            ],
        }
    ]
}


async def test_integration_loads_under_existing_domain(hass):
    assert DOMAIN == "absaar"
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == DOMAIN
    assert integration.file_path.name == DOMAIN
    assert integration.manifest["config_flow"] is True


@pytest.mark.parametrize("mode", ["cloud", "local"])
async def test_connection_menu(hass, mode):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"cloud", "local"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": mode}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == mode


@pytest.mark.parametrize("valid", [True, False])
async def test_cloud_credentials_flow(hass, valid):
    with (
        patch(
            "custom_components.absaar.config_flow.validate_credentials",
            new=AsyncMock(return_value={"user_id": "test-user"} if valid else None),
        ),
        patch("custom_components.absaar.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "cloud"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "test-user", "password": "test-password"}
        )
        await hass.async_block_till_done()
    if valid:
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["result"].domain == DOMAIN
        assert result["result"].unique_id == "test-user"
        assert result["data"]["connection_type"] == "cloud"
    else:
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.parametrize("port_available", [True, False])
async def test_local_setup_flow(hass, port_available):
    with (
        patch(
            "custom_components.absaar.config_flow._port_is_free",
            new=AsyncMock(return_value=port_available),
        ),
        patch("custom_components.absaar.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "local"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"port": 15444}
        )
        await hass.async_block_till_done()
    if port_available:
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["connection_type"] == "local"
        assert result["result"].unique_id == "local_15444"
    else:
        assert result["errors"] == {"base": "port_in_use"}


async def test_legacy_cloud_entry_keeps_sensor_identifiers(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "test-user", "password": "test-password"},
        unique_id="test-user",
    )
    entry.add_to_hass(hass)
    with patch("custom_components.absaar.AbsaarAPI") as api:
        api.return_value.authenticate.return_value = True
        api.return_value.fetch_all_data.return_value = deepcopy(CLOUD_DATA)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        energy = registry.async_get_entity_id(
            "sensor", DOMAIN, "test-station_totalPowerGeneration"
        )
        power = registry.async_get_entity_id("sensor", DOMAIN, "test-inverter_acPower")
        assert hass.states.get(energy).state == "100.5"
        assert hass.states.get(power).state == "400"
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_local_entry_updates_and_retains_energy_offline(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"connection_type": "local", "port": 15444, "serial": "TEST000001"},
        unique_id="local_15444",
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.absaar.AbsaarLocalHub.async_start", new=AsyncMock()),
        patch("custom_components.absaar.AbsaarAPI") as api,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        hub = hass.data[DOMAIN][entry.entry_id]["hub"]
        hub.data.update({"ac_power": 350, "total_energy": 100.0})
        hub._set_online(True)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        power = registry.async_get_entity_id("sensor", DOMAIN, "TEST000001_ac_power")
        energy = registry.async_get_entity_id(
            "sensor", DOMAIN, "TEST000001_total_energy"
        )
        assert hass.states.get(power).state == "350"
        assert hass.states.get(energy).state == "100.0"
        hub._set_online(False)
        await hass.async_block_till_done()
        assert hass.states.get(power).state == "unavailable"
        assert hass.states.get(energy).state == "100.0"
        api.assert_not_called()
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_local_options_keep_entry_and_serial(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"connection_type": "local", "port": 15444, "serial": "TEST000001"},
        unique_id="local_15444",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"poll_delay": 10, "ip_check_interval": 600}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["poll_delay"] == 10
    assert entry.data["serial"] == "TEST000001"
    assert entry.unique_id == "local_15444"
