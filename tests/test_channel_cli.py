from datetime import datetime, timezone

from typer.testing import CliRunner

from pydoover.models.aggregate import Aggregate
from pydoover.models.channel import Channel

from doover_cli import app
from doover_cli.utils.channel_views import ChannelViewMode

runner = CliRunner()


def _sample_channel(name: str = "ui_state") -> Channel:
    return Channel(
        name=name,
        owner_id=157338390533018379,
        is_private=False,
        aggregate_schema=None,
        message_schema=None,
        aggregate=Aggregate(
            data={"status": "online"},
            attachments=[],
            last_updated=datetime(2026, 3, 19, 1, 2, 3, tzinfo=timezone.utc),
        ),
    )


class FakeDataClient:
    def __init__(self, channel: Channel):
        self.channel = channel
        self.calls = []

    def fetch_channel(self, agent_id, channel_name, include_aggregate):
        self.calls.append((agent_id, channel_name, include_aggregate))
        return self.channel


def test_channel_get_defaults_ui_state_to_overview(monkeypatch):
    client = FakeDataClient(_sample_channel())
    captured = {}

    monkeypatch.setattr(
        "doover_cli.channel._get_data_client_and_agent_id",
        lambda: (client, 157338390533018379),
    )

    def fake_render_channel(channel, *, mode, console=None):
        captured["channel_name"] = channel.name
        captured["mode"] = mode

    monkeypatch.setattr("doover_cli.channel.render_channel", fake_render_channel)

    result = runner.invoke(app, ["channel", "get", "ui_state", "--agent", "157338390533018379"])

    assert result.exit_code == 0
    assert captured["channel_name"] == "ui_state"
    assert captured["mode"] == ChannelViewMode.OVERVIEW
    assert client.calls == [(157338390533018379, "ui_state", True)]


def test_channel_get_honors_requested_view(monkeypatch):
    client = FakeDataClient(_sample_channel())
    captured = {}

    monkeypatch.setattr(
        "doover_cli.channel._get_data_client_and_agent_id",
        lambda: (client, 157338390533018379),
    )

    def fake_render_channel(channel, *, mode, console=None):
        captured["mode"] = mode

    monkeypatch.setattr("doover_cli.channel.render_channel", fake_render_channel)

    result = runner.invoke(
        app,
        [
            "channel",
            "get",
            "ui_state",
            "--agent",
            "157338390533018379",
            "--view",
            "simple",
        ],
    )

    assert result.exit_code == 0
    assert captured["mode"] == ChannelViewMode.SIMPLE
