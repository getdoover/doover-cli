import re
from contextlib import nullcontext

from typer.testing import CliRunner

from doover_cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class FakeRenderer:
    def __init__(self):
        self.render_calls = []
        self.render_list_calls = []

    def loading(self, _message):
        return nullcontext()

    def prompt_fields(self, fields):
        return {field.key: field.default for field in fields}

    def render(self, data):
        self.render_calls.append(data)

    def render_list(self, data):
        self.render_list_calls.append(data)


def test_root_help_lists_device_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "device" in result.stdout


def test_device_help_lists_subcommands():
    result = runner.invoke(app, ["device", "--help"])

    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "create" in result.stdout
    assert "update" in result.stdout
    assert "installer-info" in result.stdout
    assert "installer-tarball" in result.stdout
    assert "installer-zip" in result.stdout


def test_device_generated_help_routes_through_root_cli():
    create_result = runner.invoke(app, ["device", "create", "--help"])
    update_result = runner.invoke(app, ["device", "update", "--help"])

    assert create_result.exit_code == 0
    create_output = _strip_ansi(create_result.stdout)
    assert "--display-name" in create_output
    assert "--type-id" in create_output
    assert "--group-id" in create_output
    assert "--fixed-location" in create_output
    assert update_result.exit_code == 0
    assert "Device ID to update." in _strip_ansi(update_result.stdout)


def test_device_list_happy_path_runs_through_root_app(monkeypatch):
    renderer = FakeRenderer()
    captured = {}

    class FakeDevicesClient:
        def list(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": []}

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "list"])

    assert result.exit_code == 0
    assert captured["kwargs"]["archived"] is None
    assert renderer.render_list_calls == [{"results": []}]
