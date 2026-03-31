from datetime import datetime, timedelta, timezone

import pytest
import typer

from pydoover.api.auth import ConfigManager

from doover_cli.api.auth import DooverCLIAuthClient
from doover_cli.api.session import DooverCLISession


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


def test_device_login_returns_populated_auth_client(monkeypatch):
    open_calls = []
    sleep_calls = []
    post_calls = []

    def fake_get(url, timeout):
        assert url == "https://auth.doover.com/.well-known/openid-configuration"
        assert timeout == 60.0
        return FakeResponse(
            {
                "device_authorization_endpoint": "https://auth.doover.com/device",
                "token_endpoint": "https://auth.doover.com/token",
            }
        )

    responses = iter(
        [
            FakeResponse(
                {
                    "user_code": "ABCD-EFGH",
                    "device_code": "device-code",
                    "expires_in": 10,
                    "interval": 2,
                }
            ),
            FakeResponse({"error": "authorization_pending"}, ok=False),
            FakeResponse(
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "refresh_token_id": "refresh-token-id",
                    "expires_in": 300,
                }
            ),
        ]
    )

    def fake_post(url, params, timeout):
        post_calls.append((url, params, timeout))
        return next(responses)

    monkeypatch.setattr("doover_cli.api.auth.requests.get", fake_get)
    monkeypatch.setattr("doover_cli.api.auth.requests.post", fake_post)
    monkeypatch.setattr(
        "doover_cli.api.auth.webbrowser.open",
        lambda *args, **kwargs: open_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "doover_cli.api.auth.time.sleep", lambda seconds: sleep_calls.append(seconds)
    )

    client = DooverCLIAuthClient.device_login()

    assert client.token == "access-token"
    assert client.refresh_token == "refresh-token"
    assert client.refresh_token_id == "refresh-token-id"
    assert client.control_base_url == "https://api.doover.com"
    assert client.data_base_url == "https://data.doover.com/api"
    assert client.auth_server_url == "https://auth.doover.com"
    assert client.auth_server_client_id == "08a9ae8c-0668-428b-a691-f7eaa526aca0"
    assert client.token_expires is not None
    assert open_calls
    assert sleep_calls == [2, 2]
    assert post_calls[0][0] == "https://auth.doover.com/device"
    assert post_calls[1][0] == "https://auth.doover.com/token"


def test_persist_profile_round_trip_with_config_manager():
    manager = ConfigManager("default")
    auth = DooverCLIAuthClient(
        token="token-1",
        token_expires=datetime.now(timezone.utc) + timedelta(minutes=5),
        refresh_token="refresh-1",
        refresh_token_id="refresh-id-1",
        control_base_url="https://api.doover.com",
        data_base_url="https://data.doover.com/api",
        auth_server_url="https://auth.doover.com",
        auth_server_client_id="client-id",
    )

    auth.persist_profile("default", manager)

    reloaded = ConfigManager("default")
    profile = reloaded.get("default")

    assert profile is not None
    assert profile.token == "token-1"
    assert profile.refresh_token == "refresh-1"
    assert profile.refresh_token_id == "refresh-id-1"
    assert profile.control_base_url == "https://api.doover.com"
    assert profile.data_base_url == "https://data.doover.com/api"


def test_refresh_access_token_persists_updated_profile(monkeypatch):
    manager = ConfigManager("default")
    auth = DooverCLIAuthClient(
        token="old-token",
        token_expires=datetime.now(timezone.utc) - timedelta(minutes=5),
        refresh_token="refresh-1",
        refresh_token_id="refresh-id-1",
        control_base_url="https://api.doover.com",
        data_base_url="https://data.doover.com/api",
        auth_server_url="https://auth.doover.com",
        auth_server_client_id="client-id",
        config_manager=manager,
        profile_name="default",
    )
    auth.persist_profile()

    def fake_refresh(self):
        self._set_access_token(
            "new-token",
            token_expires=datetime.now(timezone.utc) + timedelta(minutes=30),
        )

    monkeypatch.setattr(
        "doover_cli.api.auth.Doover2AuthClient.refresh_access_token",
        fake_refresh,
    )

    auth.refresh_access_token()

    reloaded = ConfigManager("default")
    profile = reloaded.get("default")
    assert profile is not None
    assert profile.token == "new-token"


def test_session_from_profile_builds_reusable_data_client():
    manager = ConfigManager("default")
    auth = DooverCLIAuthClient(
        token="token-1",
        token_expires=datetime.now(timezone.utc) + timedelta(minutes=5),
        refresh_token="refresh-1",
        refresh_token_id="refresh-id-1",
        control_base_url="https://api.doover.com",
        data_base_url="https://data.doover.com/api",
        auth_server_url="https://auth.doover.com",
        auth_server_client_id="client-id",
    )
    auth.persist_profile("default", manager)

    session = DooverCLISession.from_profile("default", config_manager=manager)
    client = session.get_data_client()

    assert client.auth.token == "token-1"
    assert client.base_url == "https://data.doover.com/api"
    assert session.get_data_client() is client


def test_session_from_env_uses_explicit_data_api_base_url(monkeypatch):
    monkeypatch.setenv("DOOVER_API_TOKEN", "token-1")
    monkeypatch.setenv("DOOVER_DATA_API_BASE_URL", "https://data.example.com/api")

    session = DooverCLISession.from_env()
    client = session.get_data_client()

    assert client.auth.token == "token-1"
    assert client.base_url == "https://data.example.com/api"


def test_session_require_agent_id_rejects_missing_value():
    auth = DooverCLIAuthClient(
        token="token", data_base_url="https://data.doover.com/api"
    )
    session = DooverCLISession(config_manager=None, profile_name=None, auth=auth)

    with pytest.raises(typer.BadParameter):
        session.require_agent_id(None)
