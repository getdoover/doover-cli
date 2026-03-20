from datetime import datetime, timezone

from rich.console import Console

from pydoover.models.aggregate import Aggregate
from pydoover.models.channel import Channel

from doover_cli.utils.channel_views import (
    ChannelViewMode,
    _build_channel_summary_text,
    build_channel_overview,
    resolve_channel_view,
)


def _sample_channel(name: str = "ui_state") -> Channel:
    return Channel(
        name=name,
        owner_id=157338390533018379,
        is_private=False,
        aggregate_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        message_schema=None,
        aggregate=Aggregate(
            data={
                "status": "online",
                "temperature": 21.7,
                "alarms": ["high_temp"],
                "controls": {"enabled": True, "mode": "auto"},
            },
            attachments=[],
            last_updated=datetime(2026, 3, 19, 1, 2, 3, tzinfo=timezone.utc),
        ),
    )


def _render_text(renderable) -> str:
    console = Console(record=True, width=140, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_resolve_channel_view_defaults_ui_state_to_overview():
    assert resolve_channel_view("ui_state", None) == ChannelViewMode.OVERVIEW


def test_resolve_channel_view_defaults_other_channels_to_plain():
    assert resolve_channel_view("telemetry", None) == ChannelViewMode.PLAIN


def test_build_channel_overview_includes_ui_state_content():
    text = _render_text(build_channel_overview(_sample_channel()))

    assert "UI State" in text
    assert "temperature" in text
    assert "21.7" in text
    assert "controls" in text
    assert "2026-03-19 01:02:03 UTC" in text


def test_build_channel_summary_text_includes_compact_channel_metadata():
    text = _build_channel_summary_text(_sample_channel())

    assert "Name: ui_state" in text
    assert "Channel Key: 157338390533018379:ui_state" in text
    assert "Aggregate Keys: 4" in text
    assert "Aggregate Schema: 2 top-level keys: properties, type" in text
