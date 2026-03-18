import dbm
import subprocess
from types import SimpleNamespace

import click
import pytest
from pydoover.cloud.api import Forbidden
from typer.testing import CliRunner

import doover_cli
from doover_cli import app
from doover_cli.utils import sentry as sentry_utils
from doover_cli.utils.shell_commands import run as shell_run
from doover_cli.utils.state import state

runner = CliRunner()


class FakeConfigManager:
    def __init__(self, profile):
        self.current_profile = profile
        self.current = SimpleNamespace(
            token="token",
            base_url="https://my.doover.com",
        )
        self.entries = {}

    def create(self, entry):
        self.entries[self.current_profile] = entry
        self.current = entry

    def read(self):
        return None

    def write(self):
        return None


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.delenv("DOOVER_SENTRY_ENABLED", raising=False)
    monkeypatch.delenv("DOOVER_SENTRY_DSN", raising=False)
    monkeypatch.delenv("DOOVER_SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.setattr(sentry_utils, "_initialized", False)

    state.agent_query = None
    state.agent_id = None
    state.agent = None
    state.debug = False
    state.json = False
    state.config_manager = None
    state._api = None


def test_init_sentry_disabled(monkeypatch):
    init_calls = []

    monkeypatch.setenv("DOOVER_SENTRY_ENABLED", "0")
    monkeypatch.setattr(
        sentry_utils.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    sentry_utils.init_sentry()

    assert init_calls == []
    assert sentry_utils._initialized is False


def test_init_sentry_uses_override_dsn_and_default_environment(monkeypatch):
    init_calls = []

    monkeypatch.setenv("DOOVER_SENTRY_DSN", "https://example.com/123")
    monkeypatch.setattr(
        sentry_utils.metadata,
        "version",
        lambda name: "9.9.9",
    )
    monkeypatch.setattr(
        sentry_utils.sentry_sdk,
        "init",
        lambda **kwargs: init_calls.append(kwargs),
    )

    sentry_utils.init_sentry()

    assert len(init_calls) == 1
    kwargs = init_calls[0]
    assert kwargs["dsn"] == "https://example.com/123"
    assert kwargs["environment"] == "production"
    assert kwargs["release"] == "doover-cli@9.9.9"


def test_before_send_drops_click_exit_and_abort():
    event = {"test": "event"}

    assert (
        sentry_utils._before_send(
            event,
            {"exc_info": (None, click.exceptions.Exit(1), None)},
        )
        is None
    )
    assert (
        sentry_utils._before_send(
            event,
            {"exc_info": (None, click.Abort(), None)},
        )
        is None
    )
    assert (
        sentry_utils._before_send(
            event,
            {"exc_info": (None, RuntimeError("boom"), None)},
        )
        == event
    )


def test_main_captures_unhandled_exception_and_flushes(monkeypatch):
    init_calls = []
    capture_calls = []
    flush_calls = []

    monkeypatch.setattr(doover_cli.sentry_utils, "init_sentry", lambda: init_calls.append(True))
    monkeypatch.setattr(
        doover_cli.sentry_utils,
        "current_command_path",
        lambda: "app publish",
    )
    monkeypatch.setattr(
        doover_cli.sentry_utils,
        "_capture_exception",
        lambda exc, **kwargs: capture_calls.append((exc, kwargs)),
    )
    monkeypatch.setattr(
        doover_cli.sentry_utils,
        "flush_sentry",
        lambda: flush_calls.append(True),
    )

    def raise_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(doover_cli, "app", raise_error)

    with pytest.raises(RuntimeError):
        doover_cli.main()

    assert init_calls == [True]
    assert len(capture_calls) == 1
    exc, kwargs = capture_calls[0]
    assert str(exc) == "boom"
    assert kwargs == {"handled": False, "command": "app publish"}
    assert flush_calls == [True]


def test_main_does_not_capture_click_exit(monkeypatch):
    capture_calls = []
    flush_calls = []

    monkeypatch.setattr(doover_cli.sentry_utils, "init_sentry", lambda: None)
    monkeypatch.setattr(
        doover_cli.sentry_utils,
        "_capture_exception",
        lambda exc, **kwargs: capture_calls.append((exc, kwargs)),
    )
    monkeypatch.setattr(
        doover_cli.sentry_utils,
        "flush_sentry",
        lambda: flush_calls.append(True),
    )
    monkeypatch.setattr(
        doover_cli,
        "app",
        lambda: (_ for _ in ()).throw(click.exceptions.Exit(0)),
    )

    with pytest.raises(click.exceptions.Exit):
        doover_cli.main()

    assert capture_calls == []
    assert flush_calls == [True]


def test_main_does_not_capture_click_abort(monkeypatch):
    capture_calls = []
    flush_calls = []

    monkeypatch.setattr(doover_cli.sentry_utils, "init_sentry", lambda: None)
    monkeypatch.setattr(
        doover_cli.sentry_utils,
        "_capture_exception",
        lambda exc, **kwargs: capture_calls.append((exc, kwargs)),
    )
    monkeypatch.setattr(
        doover_cli.sentry_utils,
        "flush_sentry",
        lambda: flush_calls.append(True),
    )
    monkeypatch.setattr(
        doover_cli,
        "app",
        lambda: (_ for _ in ()).throw(click.Abort()),
    )

    with pytest.raises(click.Abort):
        doover_cli.main()

    assert capture_calls == []
    assert flush_calls == [True]


def test_login_reports_handled_exception(monkeypatch):
    capture_calls = []

    monkeypatch.setattr(doover_cli, "ConfigManager", FakeConfigManager)
    monkeypatch.setattr(
        "doover_cli.login.setup_api",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("nope")),
    )
    monkeypatch.setattr(
        "doover_cli.login.capture_handled_exception",
        lambda exc, **kwargs: capture_calls.append((exc, kwargs)),
    )

    result = runner.invoke(
        app,
        [
            "login",
            "--username",
            "user@example.com",
            "--password",
            "secret",
            "--base-url",
            "https://my.doover.com",
            "--profile-name",
            "default",
        ],
    )

    assert result.exit_code == 1
    assert len(capture_calls) == 1
    assert capture_calls[0][1]["command"] == "login"


def test_configure_token_reports_handled_exception(monkeypatch):
    capture_calls = []

    class DummyApi:
        def get_agent(self, agent_id):
            raise Forbidden()

    monkeypatch.setattr(doover_cli, "ConfigManager", FakeConfigManager)
    monkeypatch.setattr("doover_cli.login.setup_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "doover_cli.login.capture_handled_exception",
        lambda exc, **kwargs: capture_calls.append((exc, kwargs)),
    )
    state.agent_id = "agent-1"
    state._api = DummyApi()

    result = runner.invoke(
        app,
        [
            "configure-token",
            "--token",
            "token",
            "--agent-id",
            "agent-1",
            "--base-url",
            "https://my.doover.com",
            "--profile",
            "default",
            "--expiry",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert len(capture_calls) == 1
    assert capture_calls[0][1]["command"] == "login.configure_token"


def test_report_compose_reports_handled_exception(monkeypatch):
    capture_calls = []

    class FakeGenerator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def generate(self):
            raise RuntimeError("generation failed")

    monkeypatch.setattr(doover_cli, "ConfigManager", FakeConfigManager)
    monkeypatch.setattr(
        "doover_cli.report.importlib",
        SimpleNamespace(
            import_module=lambda package_path: SimpleNamespace(generator=FakeGenerator)
        ),
    )
    monkeypatch.setattr(
        "doover_cli.report.capture_handled_exception",
        lambda exc, **kwargs: capture_calls.append((exc, kwargs)),
    )

    result = runner.invoke(app, ["report", "compose"])

    assert result.exit_code == 1
    assert len(capture_calls) == 1
    assert capture_calls[0][1]["command"] == "report.compose"


def test_dbm_to_json_reports_handled_exception(monkeypatch, tmp_path):
    capture_calls = []
    dbm_error_type = dbm.error[0] if isinstance(dbm.error, tuple) else dbm.error

    monkeypatch.setattr(
        "doover_cli.dda_logs.capture_handled_exception",
        lambda exc, **kwargs: capture_calls.append((exc, kwargs)),
    )
    monkeypatch.setattr(
        dbm,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(dbm_error_type("bad dbm")),
    )

    result = runner.invoke(
        app,
        [
            "dda-logs",
            "dbm-to-json",
            str(tmp_path / "input.dbm"),
            str(tmp_path / "output.json"),
        ],
    )

    assert result.exit_code == 1
    assert len(capture_calls) == 1
    assert capture_calls[0][1]["command"] == "dda-logs.dbm-to-json"


def test_shell_run_reports_handled_exception(monkeypatch, tmp_path):
    capture_calls = []

    monkeypatch.setattr(
        "doover_cli.utils.shell_commands.capture_handled_exception",
        lambda exc, **kwargs: capture_calls.append((exc, kwargs)),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(returncode=1, cmd="bad-command")
        ),
    )

    with pytest.raises(click.exceptions.Exit):
        shell_run("bad-command", cwd=tmp_path)

    assert len(capture_calls) == 1
    assert capture_calls[0][1]["command"] == "shell.run"
