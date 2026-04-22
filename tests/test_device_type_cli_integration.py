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


def test_root_help_lists_device_type_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "device-type" in result.stdout


def test_device_type_help_lists_subcommands():
    result = runner.invoke(app, ["device-type", "--help"])

    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "create" in result.stdout
    assert "update" in result.stdout


def test_device_type_generated_help_routes_through_root_cli():
    create_result = runner.invoke(app, ["device-type", "create", "--help"])
    update_result = runner.invoke(app, ["device-type", "update", "--help"])

    assert create_result.exit_code == 0
    assert "--name" in _strip_ansi(create_result.stdout)
    assert update_result.exit_code == 0
    assert "Device type ID or exact name to update." in _strip_ansi(
        update_result.stdout
    )


def test_device_type_list_happy_path_runs_through_root_app(monkeypatch):
    renderer = FakeRenderer()
    captured = {}

    class FakeDevicesClient:
        def types_list(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": []}

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "list"])

    assert result.exit_code == 0
    assert captured["kwargs"]["archived"] is None
    assert renderer.render_list_calls == [{"results": []}]
