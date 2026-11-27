"""Cloud login errors: retry when offline, stop and reauth when rejected."""

import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
import requests
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.absaar.api import (
    AbsaarAPI,
    AbsaarAuthError,
    AbsaarConnectionError,
)
from custom_components.absaar.const import DOMAIN

CLOUD_DATA = {
    "stations": [
        {
            "power_id": "test-station",
            "power_name": "Test station",
            "dailyPowerGeneration": 1.2,
            "totalPowerGeneration": 100.5,
            "collectors": [],
        }
    ]
}


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return result


@pytest.fixture
def send():
    with patch("requests.sessions.Session.send", autospec=True) as mocked:
        yield mocked


@pytest.fixture
def cloud_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test-user",
            "password": "old-password",
            "connection_type": "cloud",
        },
        unique_id="test-user",
        title="Absaar (test-user)",
    )
    entry.add_to_hass(hass)
    return entry


def reauth_flows(hass):
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_REAUTH
    ]


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (response({"code": 500, "msg": "wrong password"}), AbsaarAuthError),
        (response({"code": 401}, status=401), AbsaarAuthError),
        (response({"msg": "maintenance"}, status=502), AbsaarConnectionError),
        (response(b"<html>gateway</html>"), AbsaarConnectionError),
        (requests.exceptions.ConnectionError("offline"), AbsaarConnectionError),
        (requests.exceptions.Timeout("slow"), AbsaarConnectionError),
    ],
)
def test_authenticate_distinguishes_rejection_from_connection(send, reply, error):
    send.side_effect = [reply]
    api = AbsaarAPI("test-user", "test-password")
    with pytest.raises(error):
        api.authenticate()
    assert api.token is None


def test_poll_with_rejected_password_stops_after_login(send):
    send.side_effect = [response({"code": 500, "msg": "wrong password"})]
    api = AbsaarAPI("test-user", "old-password")
    with pytest.raises(AbsaarAuthError):
        api.fetch_all_data()
    assert send.call_count == 1


def test_expired_token_with_rejected_password_raises_auth_error(send):
    send.side_effect = [
        response({"code": 401}, status=401),
        response({"code": 500, "msg": "wrong password"}),
    ]
    api = AbsaarAPI("test-user", "old-password")
    api.token = "expired-token"
    with pytest.raises(AbsaarAuthError):
        api.get_stations()
    assert send.call_count == 2


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (AbsaarAuthError("rejected"), ConfigEntryState.SETUP_ERROR),
        (AbsaarConnectionError("offline"), ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_login_failure(hass, cloud_entry, error, state):
    with patch("custom_components.absaar.AbsaarAPI") as api:
        api.return_value.authenticate.side_effect = error
        await hass.config_entries.async_setup(cloud_entry.entry_id)
        await hass.async_block_till_done()
    assert cloud_entry.state is state
    assert len(reauth_flows(hass)) == (
        1 if state is ConfigEntryState.SETUP_ERROR else 0
    )
    api.return_value.fetch_all_data.assert_not_called()


async def test_poll_rejected_password_stops_polling_and_starts_reauth(
    hass, cloud_entry
):
    with patch("custom_components.absaar.AbsaarAPI") as api:
        fetch = api.return_value.fetch_all_data
        fetch.return_value = deepcopy(CLOUD_DATA)
        assert await hass.config_entries.async_setup(cloud_entry.entry_id)
        await hass.async_block_till_done()
        assert fetch.call_count == 1

        fetch.side_effect = AbsaarAuthError("rejected")
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=3))
        await hass.async_block_till_done()
        assert fetch.call_count == 2
        assert len(reauth_flows(hass)) == 1

        # No further logins with the rejected password.
        for minutes in (6, 9, 30):
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
            await hass.async_block_till_done()
        assert fetch.call_count == 2
        assert await hass.config_entries.async_unload(cloud_entry.entry_id)


async def test_poll_connection_error_keeps_polling_without_reauth(hass, cloud_entry):
    with patch("custom_components.absaar.AbsaarAPI") as api:
        fetch = api.return_value.fetch_all_data
        fetch.return_value = deepcopy(CLOUD_DATA)
        assert await hass.config_entries.async_setup(cloud_entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][cloud_entry.entry_id]["coordinator"]

        fetch.side_effect = AbsaarConnectionError("offline")
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=3))
        await hass.async_block_till_done()
        assert not coordinator.last_update_success

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
        await hass.async_block_till_done()
        assert fetch.call_count == 3
        assert reauth_flows(hass) == []
        assert await hass.config_entries.async_unload(cloud_entry.entry_id)


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (AbsaarAuthError("rejected"), "invalid_auth"),
        (AbsaarConnectionError("offline"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_reauth_flow_errors(hass, cloud_entry, side_effect, error):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": cloud_entry.entry_id},
        data=cloud_entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    with patch(
        "custom_components.absaar.config_flow.validate_credentials",
        new=AsyncMock(side_effect=side_effect),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new-password"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert cloud_entry.data["password"] == "old-password"


async def test_reauth_flow_updates_password_and_reloads(hass, cloud_entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": cloud_entry.entry_id},
        data=cloud_entry.data,
    )
    with (
        patch(
            "custom_components.absaar.config_flow.validate_credentials",
            new=AsyncMock(return_value={"user_id": "test-user"}),
        ) as validate,
        patch("custom_components.absaar.async_setup_entry", return_value=True) as setup,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new-password"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    validate.assert_awaited_once_with(hass, "test-user", "new-password")
    assert cloud_entry.data == {
        "username": "test-user",
        "password": "new-password",
        "connection_type": "cloud",
    }
    assert cloud_entry.unique_id == "test-user"
    assert len(setup.mock_calls) == 1
