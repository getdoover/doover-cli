import ast
import hashlib
import json
import re
from types import SimpleNamespace
from pathlib import Path

import pytest
import requests
from typer.testing import CliRunner

from doover_cli import app
from doover_cli import processor_test


runner = CliRunner()


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def fail_request(*_args, **_kwargs):
        raise AssertionError("processor testing CLI tests must not make HTTP requests")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_request)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _normalise_cli_text(text: str) -> str:
    return " ".join(_strip_ansi(text).split())


def _write_processor_project(tmp_path: Path) -> Path:
    project = tmp_path / "pump-project"
    project.mkdir()
    (project / "doover_config.json").write_text(
        json.dumps(
            {
                "pump_monitor": {
                    "id": 42,
                    "key": "pump_monitor",
                    "name": "pump_monitor",
                    "display_name": "Pump Monitor",
                    "description": "Processor used by CLI tests.",
                    "type": "INT",
                    "visibility": "PRI",
                    "config_schema": {"type": "object", "properties": {}},
                    "depends_on": [],
                    "image_name": "ghcr.io/getdoover/pump-monitor:test",
                    "entrypoint": "fixture_processor:FixtureProcessor",
                }
            }
        )
    )
    (project / "fixture_processor.py").write_text(
        """
from pydoover.processor import Application


class FixtureProcessor(Application):
    async def on_ingestion_endpoint(self, event):
        print("relay ingestion handled")
        await self.api.update_channel_aggregate(
            "status",
            {"payload": event.payload},
        )

    async def on_manual_invoke(self, event):
        print("manual invoke handled")
        await self.api.update_channel_aggregate("status", event.payload)
""".lstrip()
    )
    return project


def _constant_value(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"missing top-level constant {name}")


def _import_statements(
    tree: ast.Module,
) -> list[tuple[str, str | None, tuple[str, ...]]]:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.append(("import", None, tuple(alias.name for alias in node.names)))
        elif isinstance(node, ast.ImportFrom):
            imports.append(
                (
                    "from",
                    node.module,
                    tuple(alias.name for alias in node.names),
                )
            )
    return imports


def test_processor_test_help_exposes_v1_command_set_only():
    result = runner.invoke(app, ["processor", "test", "--help"])

    assert result.exit_code == 0, result.output
    stdout = _strip_ansi(result.stdout)
    for command in ("run", "promote", "clone", "snapshot"):
        assert command in stdout
    assert "generate" not in stdout


def test_run_save_generates_sandboxed_live_message_create_file_contract(
    monkeypatch, tmp_path
):
    project = _write_processor_project(tmp_path)
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "message-create",
            "--app-install",
            "123",
            "--agent",
            "456",
            "--channel",
            "telemetry",
            "--latest",
            "--mode",
            "sandboxed-live",
            "--writes",
            "record",
            "--save",
            "latest_telemetry",
            "--output",
            "summary",
        ],
    )

    assert result.exit_code == 0, result.output
    generated = project / "tests" / "doover" / "pump_monitor" / "latest_telemetry.py"
    assert generated.exists()

    source = generated.read_text()
    tree = ast.parse(source)

    assert _import_statements(tree) == [
        ("from", "pydoover.testing", ("ProcessorTest",))
    ]
    assert "doover_cli" not in source
    assert "pytest" not in source
    assert "assert " not in source
    assert "async def run()" in source
    assert "env = test.Environment()" in source
    assert "env.data_client = test.processor.DataClient()" in source
    assert "snapshot = await env.data_client.reads.use_live_snapshot(" in source
    assert "latest_messages=[CHANNEL]" in source
    assert "env.auth = test.auth.cli_user_for_reads()" in source
    assert "with env:" in source
    assert "result = await test.run(event)" in source
    assert "return result" in source

    assert _constant_value(tree, "APP_NAME") == "pump_monitor"
    assert _constant_value(tree, "APP_INSTALL_ID") == 123
    assert _constant_value(tree, "AGENT_ID") == 456
    assert _constant_value(tree, "APP_KEY") == "pump_monitor"
    assert _constant_value(tree, "CHANNEL") == "telemetry"
    assert "telemetry" in _constant_value(tree, "SNAPSHOT_CHANNELS")


def test_generate_ad_hoc_sandboxed_live_source_uses_collected_snapshot():
    source = processor_test.generate_test_file(
        "message-create",
        app_name="pump_monitor",
        app_key="pump_monitor",
        app_install="123",
        agent_id=456,
        channel="telemetry",
        body=None,
        content_type="application/json",
        request_data=None,
        manual_payload=None,
        report_fixture=None,
        mode="sandboxed-live",
        writes="record",
        live_snapshot={
            "agent_id": 456,
            "app_key": "pump_monitor",
            "processor_info": {
                "deployment_config": {"sensor_maximum_metres": 10},
            },
            "channels": {},
            "messages": {},
        },
        command="doover processor test run message-create",
    )

    tree = ast.parse(source)
    assert _import_statements(tree) == [
        ("from", "pydoover.testing", ("ProcessorSnapshot", "ProcessorTest"))
    ]
    assert _constant_value(tree, "LIVE_SNAPSHOT")["processor_info"][
        "deployment_config"
    ] == {"sensor_maximum_metres": 10}
    assert "use_fixtures(\n        ProcessorSnapshot.from_dict(LIVE_SNAPSHOT)" in source
    assert "use_live_snapshot(" not in source


def test_collect_live_snapshot_fetches_install_config_channels_and_latest_message(
    monkeypatch,
):
    class FakeControl:
        app_installs = SimpleNamespace()

    def retrieve_install(install_id: str):
        assert install_id == "123"
        return SimpleNamespace(
            id=123,
            display_name="Pump Install",
            application={"id": 42},
            organisation={"id": 789},
            device={"id": 456},
            deployment_config={"sensor_maximum_metres": 10},
        )

    class FakeData:
        def __init__(self):
            self.fetched_channels = []
            self.fetched_messages = []

        def fetch_channel(
            self,
            agent_id,
            channel_name,
            *,
            include_aggregate,
            organisation_id=None,
        ):
            self.fetched_channels.append(
                (agent_id, channel_name, include_aggregate, organisation_id)
            )
            return {
                "name": channel_name,
                "owner_id": agent_id,
                "is_private": False,
                "aggregate": {
                    "data": {"value": 12},
                    "attachments": [],
                    "last_updated": None,
                },
            }

        def list_messages(
            self,
            agent_id,
            channel_name,
            *,
            before,
            limit,
            organisation_id=None,
        ):
            self.fetched_messages.append(
                (agent_id, channel_name, before, limit, organisation_id)
            )
            return [
                {
                    "id": 1000,
                    "author_id": agent_id,
                    "channel": {"agent_id": agent_id, "name": channel_name},
                    "data": {"distance": 12},
                    "attachments": [],
                }
            ]

    fake_control = FakeControl()
    fake_control.app_installs.retrieve = retrieve_install
    fake_data = FakeData()
    fake_session = SimpleNamespace(
        get_control_client=lambda: fake_control,
        get_data_client=lambda: fake_data,
    )
    monkeypatch.setattr(processor_test.state, "_session", fake_session)

    snapshot = processor_test._collect_live_snapshot(
        app_name="pump_monitor",
        app_key="pump_monitor",
        app_install="123",
        agent_id=None,
        channels=["deployment_config", "telemetry"],
        latest_messages=["telemetry"],
    )

    assert snapshot["agent_id"] == 456
    assert snapshot["organisation_id"] == 789
    assert snapshot["app_install_id"] == 123
    assert snapshot["processor_info"]["deployment_config"] == {
        "APP_ID": "123",
        "APP_DISPLAY_NAME": "Pump Install",
        "dv_proc_config": {"inv_targets": []},
        "sensor_maximum_metres": 10,
    }
    assert snapshot["channels"]["telemetry"]["aggregate"]["data"] == {"value": 12}
    assert snapshot["messages"]["telemetry"][0]["data"] == {"distance": 12}
    assert fake_data.fetched_channels == [(456, "telemetry", True, 789)]
    assert len(fake_data.fetched_messages) == 1
    assert fake_data.fetched_messages[0][:2] == (456, "telemetry")
    assert fake_data.fetched_messages[0][2] is not None
    assert fake_data.fetched_messages[0][3:] == (1, 789)


def test_save_local_uses_untracked_tree_and_snapshot_command_writes_beside_test(
    monkeypatch, tmp_path
):
    project = _write_processor_project(tmp_path)
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "aggregate-update",
            "--app-install",
            "123",
            "--agent",
            "456",
            "--channel",
            "status",
            "--mode",
            "sandboxed-live",
            "--writes",
            "block",
            "--save-local",
            "latest_status",
            "--output",
            "summary",
        ],
    )

    assert result.exit_code == 0, result.output
    generated = (
        project / ".local" / "tests" / "doover" / "pump_monitor" / "latest_status.py"
    )
    assert generated.exists()
    assert not (
        project / "tests" / "doover" / "pump_monitor" / "latest_status.py"
    ).exists()

    snapshot = (
        project
        / ".local"
        / "tests"
        / "doover"
        / "pump_monitor"
        / "snapshots"
        / "latest_status.snapshot.json"
    )
    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "snapshot",
            "--app-install",
            "123",
            "--agent",
            "456",
            "--channel",
            "status",
            "--output",
            str(snapshot.relative_to(project)),
        ],
    )

    assert result.exit_code == 0, result.output
    assert snapshot.exists()
    assert (
        project / ".local" / "tests" / "doover" / "pump_monitor" / "snapshots"
    ).is_dir()

    second = runner.invoke(
        app,
        [
            "processor",
            "test",
            "snapshot",
            "--app-install",
            "123",
            "--agent",
            "456",
            "--channel",
            "status",
            "--output",
            str(snapshot.relative_to(project)),
        ],
    )

    assert second.exit_code != 0
    assert "already exists" in second.output


def test_run_saved_python_file_executes_async_run_entrypoint(monkeypatch, tmp_path):
    project = _write_processor_project(tmp_path)
    test_file = project / "tests" / "doover" / "pump_monitor" / "saved_case.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
import types


async def run():
    return types.SimpleNamespace(
        status="success",
        invocation_type="manual_invoke",
        summary={"writes": 0},
    )
""".lstrip()
    )
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            str(test_file.relative_to(project)),
            "--output",
            "summary",
        ],
    )

    assert result.exit_code == 0, result.output
    stdout = _strip_ansi(result.stdout).lower()
    assert "success" in stdout
    assert "manual_invoke" in stdout


def test_live_writes_are_rejected_until_passthrough_is_implemented(
    monkeypatch, tmp_path
):
    project = _write_processor_project(tmp_path)
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "message-create",
            "--app-install",
            "123",
            "--agent",
            "456",
            "--channel",
            "telemetry",
            "--mode",
            "live-local",
            "--writes",
            "allow",
            "--allow-live-writes",
        ],
    )

    assert result.exit_code != 0
    result_output = _normalise_cli_text(result.output)
    assert "Allowed live writes" in result_output
    assert "--writes block" in result_output

    sandbox_result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "aggregate-update",
            "--app-install",
            "123",
            "--agent",
            "456",
            "--channel",
            "status",
            "--mode",
            "sandboxed-live",
            "--writes",
            "allow",
            "--allow-live-writes",
        ],
    )

    assert sandbox_result.exit_code != 0
    sandbox_output = _normalise_cli_text(sandbox_result.output)
    assert "Allowed live writes" in sandbox_output
    assert "--writes block" in sandbox_output

    old_name_result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "manual-invoke",
            "--mode",
            "live",
        ],
    )

    assert old_name_result.exit_code != 0
    assert "live-local" in old_name_result.output


def test_run_save_resolves_app_name_alias_and_request_data(monkeypatch, tmp_path):
    project = _write_processor_project(tmp_path)
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "aggregate-update",
            "--app-name",
            "Pump Monitor",
            "--app-install",
            "123",
            "--agent",
            "456",
            "--channel",
            "status",
            "--request-data",
            '{"state": "requested"}',
            "--mode",
            "sandboxed-live",
            "--save",
            "display_name_case",
        ],
    )

    assert result.exit_code == 0, result.output
    generated = project / "tests" / "doover" / "pump_monitor" / "display_name_case.py"
    tree = ast.parse(generated.read_text())
    assert _constant_value(tree, "APP_NAME") == "pump_monitor"
    assert _constant_value(tree, "APP_KEY") == "pump_monitor"
    assert _constant_value(tree, "REQUEST_DATA") == {"state": "requested"}


def test_run_save_includes_manual_payload_in_generated_hash(monkeypatch, tmp_path):
    project = _write_processor_project(tmp_path)
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "manual-invoke",
            "--manual",
            '{"state": "running"}',
            "--mode",
            "local",
            "--save",
            "manual_payload",
        ],
    )

    assert result.exit_code == 0, result.output
    generated = project / "tests" / "doover" / "pump_monitor" / "manual_payload.py"
    source = generated.read_text()
    tree = ast.parse(source)

    assert _constant_value(tree, "PAYLOAD") == {"state": "running"}
    body = source.split("\n\n", 1)[1]
    digest = re.search(r"Generated-Content-SHA256: ([0-9a-f]{16})", source)
    assert digest is not None
    assert digest.group(1) == hashlib.sha256(body.encode()).hexdigest()[:16]


def test_snapshot_file_option_takes_precedence_over_local_fixtures(
    monkeypatch, tmp_path
):
    project = _write_processor_project(tmp_path)
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "manual-invoke",
            "--mode",
            "local",
            "--snapshot",
            "baseline",
            "--save",
            "snapshot_case",
        ],
    )

    assert result.exit_code == 0, result.output
    generated = project / "tests" / "doover" / "pump_monitor" / "snapshot_case.py"
    source = generated.read_text()
    assert 'use_snapshot_file(\n        "snapshots/baseline.snapshot.json"' in source
    assert "use_fixtures()" not in source
    assert "__file__" in source


def test_promote_copies_local_generated_test_to_tracked_tree_without_overwrite(
    monkeypatch, tmp_path
):
    project = _write_processor_project(tmp_path)
    source = project / ".local" / "tests" / "doover" / "pump_monitor" / "case.py"
    source.parent.mkdir(parents=True)
    source.write_text("async def run():\n    return 'local'\n")
    destination = project / "tests" / "doover" / "pump_monitor" / "case.py"
    destination.parent.mkdir(parents=True)
    destination.write_text("async def run():\n    return 'tracked'\n")
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "promote",
            str(source.relative_to(project)),
            "--to",
            str((project / "tests" / "doover" / "pump_monitor").relative_to(project)),
        ],
    )

    assert result.exit_code != 0
    assert destination.read_text() == "async def run():\n    return 'tracked'\n"

    destination.unlink()
    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "promote",
            str(source.relative_to(project)),
            "--to",
            str((project / "tests" / "doover" / "pump_monitor").relative_to(project)),
        ],
    )

    assert result.exit_code == 0, result.output
    assert destination.read_text() == source.read_text()


def test_clone_creates_named_copy_next_to_existing_test_without_overwrite(
    monkeypatch, tmp_path
):
    project = _write_processor_project(tmp_path)
    source = project / "tests" / "doover" / "pump_monitor" / "base_case.py"
    source.parent.mkdir(parents=True)
    source.write_text("async def run():\n    return 'base'\n")
    destination = project / "tests" / "doover" / "pump_monitor" / "copied_case.py"
    destination.write_text("async def run():\n    return 'existing'\n")
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "clone",
            str(source.relative_to(project)),
            "--to",
            "copied_case",
        ],
    )

    assert result.exit_code != 0
    assert destination.read_text() == "async def run():\n    return 'existing'\n"

    destination.unlink()
    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "clone",
            str(source.relative_to(project)),
            "--to",
            "copied_case",
        ],
    )

    assert result.exit_code == 0, result.output
    assert destination.read_text() == source.read_text()


def test_ingestion_relay_run_mode_dispatches_local_handler_without_generating_files(
    monkeypatch, tmp_path
):
    project = _write_processor_project(tmp_path)
    body = project / "webhook.json"
    body.write_text('{"device": "pump-7", "value": 12.5}')
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        [
            "processor",
            "test",
            "run",
            "ingestion",
            "--relay",
            "--app-install",
            "123",
            "--agent",
            "456",
            "--body",
            str(body.relative_to(project)),
            "--content-type",
            "application/json",
            "--mode",
            "local",
            "--writes",
            "record",
            "--output",
            "summary",
        ],
    )

    assert result.exit_code == 0, result.output
    stdout = _strip_ansi(result.stdout).lower()
    assert "ingestion" in stdout
    assert "relay" in stdout
    assert not (project / "tests" / "doover" / "pump_monitor").exists()
    assert not (project / ".local" / "tests" / "doover" / "pump_monitor").exists()
