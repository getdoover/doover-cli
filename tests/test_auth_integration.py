from datetime import datetime, timedelta, timezone
from typer.testing import CliRunner

from doover_cli import app
from doover_cli.api.auth import DooverCLIAuthClient

runner = CliRunner()


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


def test_login_command_writes_default_profile(monkeypatch):
    responses = iter(
        [
            FakeResponse(
                {
                    "user_code": "ABCD-EFGH",
                    "device_code": "device-code",
                    "expires_in": 10,
                    "interval": 1,
                }
            ),
            FakeResponse(
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "refresh_token_id": "refresh-token-id",
                    "expires_in": 600,
                }
            ),
        ]
    )

    monkeypatch.setattr(
        "doover_cli.api.auth.requests.get",
        lambda url, timeout: FakeResponse(
            {
                "device_authorization_endpoint": "https://auth.doover.com/device",
                "token_endpoint": "https://auth.doover.com/token",
            }
        ),
    )
    monkeypatch.setattr(
        "doover_cli.api.auth.requests.post",
        lambda url, params, timeout: next(responses),
    )
    monkeypatch.setattr("doover_cli.api.auth.webbrowser.open", lambda *args, **kwargs: None)
    monkeypatch.setattr("doover_cli.api.auth.time.sleep", lambda seconds: None)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0
    assert "Successfully logged into Doover (production)" in result.stdout

    manager = DooverCLIAuthClient.from_profile_name("default")._config_manager
    assert manager is not None
    profile = manager.get("default")
    assert profile is not None
    assert profile.token == "access-token"
    assert profile.refresh_token == "refresh-token"
    assert profile.data_base_url == "https://data.doover.com/api"


def test_login_then_channel_get_uses_profile_backed_session(monkeypatch):
    auth = DooverCLIAuthClient(
        token="stored-token",
        token_expires=datetime.now(timezone.utc) + timedelta(minutes=5),
        refresh_token="refresh-token",
        refresh_token_id="refresh-token-id",
        control_base_url="https://api.doover.com",
        data_base_url="https://data.doover.com/api",
        auth_server_url="https://auth.doover.com",
        auth_server_client_id="client-id",
    )

    from pydoover.api.auth import ConfigManager

    manager = ConfigManager("default")
    auth.persist_profile("default", manager)

    captured = {}

    class FakeAggregate:
        def __init__(self):
            self.data = {"value": 1}

        def to_dict(self):
            return {"data": self.data, "attachments": [], "last_updated": None}

    class FakeChannel:
        def __init__(self):
            self.name = "test-channel"
            self.owner_id = 123
            self.is_private = False
            self.message_schema = None
            self.aggregate_schema = None
            self.aggregate = FakeAggregate()

        def to_dict(self):
            return {
                "name": self.name,
                "owner_id": self.owner_id,
                "is_private": self.is_private,
            }

    class FakeDataClient:
        def __init__(self, auth):
            captured["token"] = auth.token
            captured["data_base_url"] = auth.data_base_url

        def fetch_channel(self, agent_id, channel_name, include_aggregate=True):
            captured["agent_id"] = agent_id
            captured["channel_name"] = channel_name
            captured["include_aggregate"] = include_aggregate
            return FakeChannel()

    monkeypatch.setattr("doover_cli.api.session.DataClient", FakeDataClient)

    result = runner.invoke(app, ["channel", "get", "test-channel", "--agent", "123"])

    assert result.exit_code == 0
    assert "Channel Name: test-channel" in result.stdout
    assert captured == {
        "token": "stored-token",
        "data_base_url": "https://data.doover.com/api",
        "agent_id": 123,
        "channel_name": "test-channel",
        "include_aggregate": True,
    }


def test_login_staging_custom_profile_writes_requested_profile(monkeypatch):
    monkeypatch.setattr(
        "doover_cli.login.DooverCLIAuthClient.device_login",
        lambda staging: DooverCLIAuthClient(
            token="staging-token",
            token_expires=datetime.now(timezone.utc) + timedelta(minutes=5),
            refresh_token="refresh-token",
            refresh_token_id="refresh-token-id",
            control_base_url="https://api.staging.udoover.com",
            data_base_url="https://data.staging.udoover.com/api",
            auth_server_url="https://auth.staging.udoover.com",
            auth_server_client_id="client-id",
        ),
    )

    result = runner.invoke(app, ["login", "--staging", "--profile", "custom"])

    assert result.exit_code == 0
    assert "--profile custom" in result.stdout

    from pydoover.api.auth import ConfigManager

    profile = ConfigManager("custom").get("custom")
    assert profile is not None
    assert profile.token == "staging-token"
    assert profile.control_base_url == "https://api.staging.udoover.com"
