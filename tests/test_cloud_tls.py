"""Exercise TLS settings at the Requests session boundary without network I/O."""

import json
from unittest.mock import patch

import pytest
import requests

from custom_components.absaar.api import AbsaarAPI
from custom_components.absaar.config_flow import validate_credentials
from custom_components.absaar.const import BASE_URL


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    return result


@pytest.fixture
def send():
    # Keep the real Requests preparation and TLS defaults; replace only I/O.
    with patch("requests.sessions.Session.send", autospec=True) as mocked:
        yield mocked


def assert_verified(send):
    assert send.call_count
    for call in send.call_args_list:
        assert call.kwargs["verify"] is True
        assert call.args[1].url.startswith(BASE_URL + "/")


def test_login_and_data_requests_verify_tls(send):
    send.side_effect = [
        response({"token": "test-token", "userId": "test-user"}),
        response({"code": 200, "rows": []}),
        response({"code": 200, "rows": []}),
        response({"code": 200, "rows": []}),
    ]
    api = AbsaarAPI("test-user", "test-password")
    assert api.authenticate()
    assert api.get_stations() == {"code": 200, "rows": []}
    assert api.get_collectors("test-station") == {"code": 200, "rows": []}
    assert api.get_inverter_data("test-station", "test-inverter") == {
        "code": 200,
        "rows": [],
    }
    assert send.call_count == 4
    assert_verified(send)


def test_reauthentication_and_retry_verify_tls(send):
    send.side_effect = [
        response({"code": 401}, status=401),
        response({"token": "replacement-token", "userId": "test-user"}),
        response({"code": 200, "rows": []}),
    ]
    api = AbsaarAPI("test-user", "test-password")
    api.token = "expired-token"
    api.user_id = "test-user"
    assert api.get_stations() == {"code": 200, "rows": []}
    assert send.call_count == 3
    assert send.call_args_list[0].args[1].headers["Authorization"] == "expired-token"
    assert (
        send.call_args_list[2].args[1].headers["Authorization"] == "replacement-token"
    )
    assert_verified(send)


async def test_setup_login_verifies_tls(hass, send):
    send.return_value = response({"token": "test-token", "userId": "test-user"})
    assert await validate_credentials(hass, "test-user", "test-password") == {
        "token": "test-token",
        "user_id": "test-user",
    }
    assert send.call_count == 1
    assert_verified(send)


@pytest.mark.parametrize("stage", ["login", "data", "retry"])
def test_certificate_error_never_retries_without_verification(send, stage):
    error = requests.exceptions.SSLError("certificate verify failed")
    api = AbsaarAPI("test-user", "test-password")
    if stage == "login":
        send.side_effect = error
        assert not api.authenticate()
        assert api.token is None
    else:
        api.token = "test-token"
        api.user_id = "test-user"
        send.side_effect = (
            [
                response({"code": 401}, status=401),
                response({"token": "replacement-token", "userId": "test-user"}),
                error,
            ]
            if stage == "retry"
            else error
        )
        assert api.get_stations() is None
    assert send.call_count == (3 if stage == "retry" else 1)
    assert_verified(send)


async def test_setup_rejects_certificate_error(hass, send):
    send.side_effect = requests.exceptions.SSLError("certificate verify failed")
    assert await validate_credentials(hass, "test-user", "test-password") is None
    assert send.call_count == 1
    assert_verified(send)
