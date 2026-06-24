from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any

import typer
from pydoover.api import NotFoundError

from .utils.state import state


processor_app = typer.Typer(no_args_is_help=True)
app = typer.Typer(no_args_is_help=True)
processor_app.add_typer(app, name="test", help="Run local processor tests.")

VALID_MODES = {"local", "sandboxed-live", "live-local"}
VALID_WRITES = {"record", "block", "allow"}
APP_TYPES = {"processor", "proc", "integration", "int", "report", "report_generator"}


def _version() -> str:
    try:
        return metadata.version("doover-cli")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def _find_doover_config(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        candidate = path / "doover_config.json"
        if candidate.exists():
            return candidate
    return None


def _load_doover_config() -> dict[str, Any]:
    config_path = _find_doover_config()
    if config_path is None:
        return {}
    with config_path.open() as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _is_processor_like(config: Any) -> bool:
    if not isinstance(config, dict):
        return False
    app_type = str(config.get("type") or "").lower()
    if app_type in APP_TYPES:
        return True
    return any(key in config for key in ("entrypoint", "image_name", "processor"))


def _resolve_app_name(app_name: str | None) -> str:
    data = _load_doover_config()
    if app_name:
        if not data:
            return app_name
        if app_name in data:
            return app_name
        for key, config in data.items():
            if not isinstance(config, dict):
                continue
            if app_name in {config.get("name"), config.get("display_name")}:
                return key
        available = ", ".join(data.keys())
        raise typer.BadParameter(
            f"App {app_name!r} was not found in doover_config.json. Available: {available}",
            param_hint="--app-name",
        )
    if not data:
        return "processor_app"
    if len(data) == 1:
        return next(iter(data.keys()))
    candidates = [key for key, config in data.items() if _is_processor_like(config)]
    if len(candidates) == 1:
        return candidates[0]
    raise typer.BadParameter(
        "Multiple processor-like apps found in doover_config.json; pass --app-name.",
        param_hint="--app-name",
    )


def _load_app_config(app_name: str | None = None) -> tuple[str, dict[str, Any]]:
    resolved = _resolve_app_name(app_name)
    data = _load_doover_config()
    return resolved, data.get(resolved) or {}


def _app_config_key(app_name: str, app_config: dict[str, Any]) -> str:
    return app_config.get("app_key") or app_config.get("key") or app_name


def _python_literal(value: Any) -> str:
    return repr(value)


def _serialise_platform_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _serialise_platform_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialise_platform_value(item) for item in value]
    if hasattr(value, "to_dict"):
        return _serialise_platform_value(value.to_dict())
    return value


def _resource_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("id")
    elif hasattr(value, "id"):
        value = getattr(value, "id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resource_field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _collect_live_snapshot(
    *,
    app_name: str,
    app_key: str,
    app_install: str | None,
    agent_id: int | None,
    channels: list[str],
    latest_messages: list[str],
) -> dict[str, Any]:
    if not app_install:
        raise typer.BadParameter(
            "sandboxed-live tests need --app-install so deployment config can be fetched.",
            param_hint="--app-install",
        )

    session = state.session
    control_client = session.get_control_client()
    data_client = session.get_data_client()

    try:
        install = control_client.app_installs.retrieve(str(app_install))
    except Exception as exc:
        raise typer.BadParameter(
            f"Failed to fetch app install {app_install!r} for sandboxed-live snapshot: {exc}",
            param_hint="--app-install",
        ) from exc

    install_id = _resource_id(install) or (
        int(app_install) if app_install.isdigit() else None
    )
    resolved_agent_id = agent_id or _resource_id(_resource_field(install, "device"))
    if resolved_agent_id is None:
        raise typer.BadParameter(
            "sandboxed-live tests need --agent because the app install did not include an associated device.",
            param_hint="--agent",
        )

    organisation_id = _resource_id(_resource_field(install, "organisation"))
    application = _resource_field(install, "application")
    display_name = (
        _resource_field(install, "display_name")
        or _resource_field(install, "name")
        or app_name
    )
    deployment_config = _serialise_platform_value(
        _resource_field(install, "deployment_config")
    )
    if not isinstance(deployment_config, dict):
        deployment_config = {}
    deployment_config = {
        "APP_ID": str(install_id or app_key),
        "APP_DISPLAY_NAME": display_name,
        "dv_proc_config": {"inv_targets": []},
        **deployment_config,
    }

    snapshot: dict[str, Any] = {
        "agent_id": resolved_agent_id,
        "organisation_id": organisation_id,
        "app_key": app_key,
        "app_id": install_id,
        "app_install_id": install_id,
        "app": {
            "local_name": app_name,
            "app_key": app_key,
            "app_id": install_id,
            "app_install_id": install_id,
            "display_name": display_name,
            "application_id": _resource_id(application),
        },
        "processor_info": {
            "deployment_config": deployment_config,
            "tag_values": {},
            "ui_state": {},
            "ui_cmds": {},
            "connection_data": {},
            "token": "test-processor-token",
        },
        "channels": {},
        "messages": {},
    }

    special_channels = {"deployment_config", "tag_values", "ui_state", "ui_cmds"}
    for channel_name in dict.fromkeys(channels):
        if not channel_name or channel_name == "deployment_config":
            continue
        try:
            channel = data_client.fetch_channel(
                resolved_agent_id,
                channel_name,
                include_aggregate=True,
                organisation_id=organisation_id,
            )
        except NotFoundError as exc:
            if channel_name in special_channels:
                continue
            raise typer.BadParameter(
                f"Failed to fetch sandboxed-live channel {channel_name!r}: channel was not found for agent {resolved_agent_id}.",
                param_hint="--channel",
            ) from exc
        except Exception as exc:
            raise typer.BadParameter(
                f"Failed to fetch sandboxed-live channel {channel_name!r}: {exc}",
                param_hint="--channel",
            ) from exc

        channel_payload = _serialise_platform_value(channel)
        snapshot["channels"][channel_name] = channel_payload
        if channel_name in {"tag_values", "ui_state", "ui_cmds"}:
            aggregate_data = (channel_payload.get("aggregate") or {}).get("data")
            if isinstance(aggregate_data, dict):
                snapshot["processor_info"][channel_name] = aggregate_data

    for channel_name in dict.fromkeys(latest_messages):
        try:
            messages = data_client.list_messages(
                resolved_agent_id,
                channel_name,
                before=datetime.now(timezone.utc),
                limit=1,
                organisation_id=organisation_id,
            )
        except NotFoundError as exc:
            raise typer.BadParameter(
                f"Failed to fetch latest sandboxed-live message for {channel_name!r}: channel was not found for agent {resolved_agent_id}.",
                param_hint="--channel",
            ) from exc
        except Exception as exc:
            raise typer.BadParameter(
                f"Failed to fetch latest sandboxed-live message for {channel_name!r}: {exc}",
                param_hint="--channel",
            ) from exc

        if not messages:
            raise typer.BadParameter(
                f"No live messages were found on channel {channel_name!r} for agent {resolved_agent_id}.",
                param_hint="--latest",
            )
        snapshot["messages"][channel_name] = [
            _serialise_platform_value(message) for message in messages
        ]

    return snapshot


def _app_install_constant(app_install: str | None) -> str:
    if app_install is None:
        return "APP_INSTALL_ID = None\n"
    if app_install.isdigit():
        return f"APP_INSTALL_ID = {int(app_install)}\n"
    return f"APP_INSTALL_ID = {_python_literal(app_install)}  # replace with stable install ID when available\n"


def _generated_hash(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _generated_path(app_name: str, test_name: str, *, local: bool) -> Path:
    root = Path(".local/tests/doover") if local else Path("tests/doover")
    return root / app_name / f"{test_name}.py"


def _event_block(
    invocation_type: str,
    *,
    channel: str | None,
    body: str | None,
    content_type: str | None,
    report_fixture: str | None,
) -> str:
    if invocation_type == "message-create":
        return """    event = await test.events.message_create(
        channel=CHANNEL,
        message_source=\"latest\",
    )
"""
    if invocation_type == "aggregate-update":
        return """    event = await test.events.aggregate_update(
        channel=CHANNEL,
        request_data=REQUEST_DATA,
    )
"""
    if invocation_type == "ingestion":
        body_arg = "body_path=BODY_PATH," if body else "body={},"
        return f"""    event = await test.events.ingestion(
        {body_arg}
        content_type=CONTENT_TYPE,
    )
"""
    if invocation_type == "deployment":
        return "    event = await test.events.deployment()\n"
    if invocation_type == "schedule":
        return "    event = await test.events.schedule()\n"
    if invocation_type == "manual-invoke":
        return "    event = await test.events.manual_invoke(payload=PAYLOAD)\n"
    if invocation_type == "report":
        if report_fixture:
            return """    report_payload = await test.files.json(REPORT_FIXTURE_PATH)
    event = await test.events.manual_invoke(payload=report_payload)
"""
        return "    event = await test.events.manual_invoke(payload=PAYLOAD)\n"
    if invocation_type == "ingestion-relay":
        return "    event = await test.events.ingestion(body={}, content_type=CONTENT_TYPE)\n"
    raise typer.BadParameter(
        f"Unsupported processor invocation type: {invocation_type}"
    )


def generate_test_file(
    invocation_type: str,
    *,
    app_name: str,
    app_key: str,
    app_install: str | None,
    agent_id: int | None,
    channel: str | None,
    body: str | None,
    content_type: str | None,
    request_data: dict[str, Any] | None,
    manual_payload: dict[str, Any] | None,
    report_fixture: str | None,
    mode: str,
    writes: str,
    snapshot_name: str | None = None,
    live_snapshot: dict[str, Any] | None = None,
    command: str,
) -> str:
    snapshot_channels = ["deployment_config", "tag_values", "ui_state", "ui_cmds"]
    if channel and channel not in snapshot_channels:
        snapshot_channels.append(channel)
    constants = [
        f"APP_NAME = {_python_literal(app_name)}",
        _app_install_constant(app_install).rstrip(),
        f"AGENT_ID = {agent_id if agent_id is not None else 0}",
        f"APP_KEY = {_python_literal(app_key)}  # platform app key from doover_config.json",
        f"SNAPSHOT_CHANNELS = {_python_literal(snapshot_channels)}",
    ]
    if channel:
        constants.append(f"CHANNEL = {_python_literal(channel)}")
    if body:
        constants.append(f"BODY_PATH = {_python_literal(body)}")
    if content_type:
        constants.append(f"CONTENT_TYPE = {_python_literal(content_type)}")
    if invocation_type == "aggregate-update":
        constants.append(f"REQUEST_DATA = {_python_literal(request_data or {})}")
    if invocation_type in {"manual-invoke", "report"}:
        constants.append(f"PAYLOAD = {_python_literal(manual_payload or {})}")
    if report_fixture:
        constants.append(f"REPORT_FIXTURE_PATH = {_python_literal(report_fixture)}")
    if live_snapshot is not None:
        constants.append(f"LIVE_SNAPSHOT = {_python_literal(live_snapshot)}")

    if writes == "block":
        write_line = "    env.data_client.writes.block()"
    elif writes == "allow":
        write_line = "    env.data_client.writes.allow(confirm=True)"
    else:
        write_line = "    env.data_client.writes.capture()"

    if snapshot_name:
        read_block = f"""    env.data_client.base_dir = __import__(\"pathlib\").Path(__file__).parent
    snapshot = await env.data_client.reads.use_snapshot_file(
        \"snapshots/{snapshot_name}.snapshot.json\"
    )
    env.data_client.reads.delegate_missing(False)
"""
        auth_line = ""
    elif live_snapshot is not None:
        read_block = """    snapshot = env.data_client.reads.use_fixtures(
        ProcessorSnapshot.from_dict(LIVE_SNAPSHOT)
    )
    env.data_client.reads.delegate_missing(False)
"""
        auth_line = "    env.auth = test.auth.cli_user_for_reads()\n"
    elif mode == "local":
        read_block = """    snapshot = env.data_client.reads.use_fixtures()
    snapshot.agent_id = AGENT_ID
    snapshot.app_install_id = APP_INSTALL_ID
    snapshot.app_key = APP_KEY
"""
        auth_line = ""
    elif mode == "live-local":
        read_block = "    env.data_client.reads.use_live()\n"
        auth_line = "    env.auth = test.auth.cli_user()\n"
    else:
        latest_line = (
            "        latest_messages=[CHANNEL],\n"
            if invocation_type == "message-create"
            else ""
        )
        read_block = f"""    snapshot = await env.data_client.reads.use_live_snapshot(
        agent_id=AGENT_ID,
        app_install_id=APP_INSTALL_ID,
        app_key=APP_KEY,
        channels=SNAPSHOT_CHANNELS,
{latest_line}    )
    env.data_client.reads.delegate_missing(False)
"""
        auth_line = "    env.auth = test.auth.cli_user_for_reads()\n"

    test_imports = (
        "ProcessorSnapshot, ProcessorTest"
        if live_snapshot is not None
        else "ProcessorTest"
    )
    body_text = f"""from pydoover.testing import {test_imports}


{chr(10).join(constants)}


async def run():
    test = ProcessorTest(
        APP_NAME,
        app_install=APP_INSTALL_ID,
    )

{_event_block(invocation_type, channel=channel, body=body, content_type=content_type, report_fixture=report_fixture)}
    env = test.Environment()
    env.data_client = test.processor.DataClient()
{read_block}{write_line}
{auth_line}
    with env:
        result = await test.run(event)

    return result
"""
    header = f"""# Generated by doover-cli {_version()}
# Command:
#   {command}
# Generated-Content-SHA256: {_generated_hash(body_text)}

"""
    return header + body_text


async def _run_file(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise typer.BadParameter(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("pydoover.testing"):
            raise typer.BadParameter(
                "Processor tests require pydoover.testing. Install a pydoover version "
                "that includes the processor testing API."
            ) from exc
        raise
    run = getattr(module, "run", None)
    if run is None:
        raise typer.BadParameter(f"{path} does not define async run()")
    return await run()


async def _run_source(source: str):
    namespace = {
        "__name__": "_doover_processor_test_generated",
        "__file__": str(Path.cwd() / "<generated-processor-test>"),
    }
    try:
        exec(compile(source, namespace["__file__"], "exec"), namespace)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("pydoover.testing"):
            raise typer.BadParameter(
                "Processor tests require pydoover.testing. Install a pydoover version "
                "that includes the processor testing API."
            ) from exc
        raise
    run = namespace.get("run")
    if run is None:
        raise typer.BadParameter("Generated processor test does not define async run()")
    return await run()


def _validate_mode_and_writes(
    mode: str,
    writes: str,
    *,
    allow_live_writes: bool,
) -> None:
    if mode not in VALID_MODES:
        raise typer.BadParameter(
            f"Unsupported mode {mode!r}. Expected one of: {', '.join(sorted(VALID_MODES))}.",
            param_hint="--mode",
        )
    if writes not in VALID_WRITES:
        raise typer.BadParameter(
            f"Unsupported writes policy {writes!r}. Expected one of: {', '.join(sorted(VALID_WRITES))}.",
            param_hint="--writes",
        )
    if writes == "allow":
        raise typer.BadParameter(
            "Allowed live writes are not implemented in v1; use --writes record or --writes block.",
            param_hint="--allow-live-writes",
        )


def _parse_json_option(value: str | None, *, param_hint: str) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"{param_hint} must be valid JSON: {exc.msg}",
            param_hint=param_hint,
        ) from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter(
            f"{param_hint} must be a JSON object", param_hint=param_hint
        )
    return parsed


async def _run_ingestion_once(
    *,
    app_name: str,
    app_key: str,
    app_install: str | None,
    agent_id: int | None,
    body: bytes,
    content_type: str,
    mode: str,
    writes: str,
):
    try:
        from pydoover.testing import ProcessorSnapshot, ProcessorTest
    except ModuleNotFoundError as exc:
        raise typer.BadParameter(
            "Processor tests require pydoover.testing. Install a pydoover version "
            "that includes the processor testing API."
        ) from exc

    app_install_id: int | str | None = app_install
    if app_install and app_install.isdigit():
        app_install_id = int(app_install)

    test = ProcessorTest(app_name, app_install=app_install_id)
    event = await test.events.ingestion(body=body, content_type=content_type)

    env = test.Environment()
    env.data_client = test.processor.DataClient()
    if mode == "local":
        snapshot = env.data_client.reads.use_fixtures()
        snapshot.agent_id = agent_id or 0
        snapshot.app_install_id = (
            app_install_id if isinstance(app_install_id, int) else None
        )
        snapshot.app_key = app_key
    elif mode == "sandboxed-live":
        live_snapshot = _collect_live_snapshot(
            app_name=app_name,
            app_key=app_key,
            app_install=app_install,
            agent_id=agent_id,
            channels=["deployment_config", "tag_values", "ui_state", "ui_cmds"],
            latest_messages=[],
        )
        env.data_client.reads.use_fixtures(ProcessorSnapshot.from_dict(live_snapshot))
        env.data_client.reads.delegate_missing(False)
        env.auth = test.auth.cli_user_for_reads()
    else:
        env.data_client.reads.use_live()
        env.auth = test.auth.cli_user()

    if writes == "block":
        env.data_client.writes.block()
    elif writes == "allow":
        env.data_client.writes.allow(confirm=True)
    else:
        env.data_client.writes.capture()

    with env:
        return await test.run(event)


def _read_body(body_path: str | None) -> bytes:
    if body_path is None:
        return b"{}"
    return Path(body_path).read_bytes()


def _serve_ingestion_relay(
    *,
    app_name: str,
    app_key: str,
    app_install: str | None,
    agent_id: int | None,
    mode: str,
    writes: str,
    port: int,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            content_type = self.headers.get("Content-Type") or "application/json"
            body = self.rfile.read(length)
            result = asyncio.run(
                _run_ingestion_once(
                    app_name=app_name,
                    app_key=app_key,
                    app_install=app_install,
                    agent_id=agent_id,
                    body=body,
                    content_type=content_type,
                    mode=mode,
                    writes=writes,
                )
            )
            payload = json.dumps(_normalise_result(result), default=str).encode()
            status_code = 200 if getattr(result, "status", "error") != "error" else 500
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            typer.echo(format % args)

    server = HTTPServer(("127.0.0.1", port), Handler)
    typer.echo(f"Ingestion relay listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("Ingestion relay stopped")
    finally:
        server.server_close()


def _normalise_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_summary"):
        return result.to_summary()
    if isinstance(result, dict):
        return result
    if hasattr(result, "__dict__"):
        return vars(result)
    return {"result": repr(result)}


def _render_result(result: Any, output: str) -> None:
    summary = _normalise_result(result)
    requested = {part.strip() for part in output.split(",") if part.strip()}
    if not requested:
        requested = {"logs", "summary"}
    if "all" in requested or "json" in requested:
        typer.echo(json.dumps(summary, indent=2, default=str))
        return
    if "logs" in requested:
        for record in getattr(result, "logs", []) or []:
            typer.echo(
                record.getMessage() if hasattr(record, "getMessage") else str(record)
            )
            if getattr(record, "exc_info", None) and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                typer.echo(f"{type(exc).__name__}: {exc}")
    if "writes" in requested:
        writes = getattr(result, "writes", None)
        if hasattr(writes, "to_dicts"):
            typer.echo(json.dumps(writes.to_dicts(), indent=2, default=str))
        elif writes is not None:
            typer.echo(json.dumps(writes, indent=2, default=str))
    if "summary" in requested:
        typer.echo(json.dumps(summary, indent=2, default=str))


@app.command("run")
def run(
    target: Annotated[str, typer.Argument(help="Saved test file or invocation type.")],
    app_name: Annotated[str | None, typer.Option("--app-name")] = None,
    app_install: Annotated[str | None, typer.Option("--app-install")] = None,
    agent_id: Annotated[int | None, typer.Option("--agent")] = None,
    channel: Annotated[str | None, typer.Option("--channel")] = None,
    latest: Annotated[bool, typer.Option("--latest")] = False,
    body: Annotated[str | None, typer.Option("--body")] = None,
    content_type: Annotated[str, typer.Option("--content-type")] = "application/json",
    request_data_json: Annotated[str | None, typer.Option("--request-data")] = None,
    manual_payload_json: Annotated[str | None, typer.Option("--manual")] = None,
    report_fixture: Annotated[str | None, typer.Option("--report-fixture")] = None,
    mode: Annotated[str, typer.Option("--mode")] = "sandboxed-live",
    writes: Annotated[str, typer.Option("--writes")] = "record",
    allow_live_writes: Annotated[bool, typer.Option("--allow-live-writes")] = False,
    allow_unpublished: Annotated[bool, typer.Option("--allow-unpublished")] = False,
    save: Annotated[str | None, typer.Option("--save")] = None,
    save_local: Annotated[str | None, typer.Option("--save-local")] = None,
    snapshot_name: Annotated[str | None, typer.Option("--snapshot")] = None,
    relay: Annotated[bool, typer.Option("--relay")] = False,
    port: Annotated[int, typer.Option("--port")] = 8877,
    output: Annotated[str, typer.Option("--output")] = "logs,summary",
):
    _ = allow_unpublished
    _validate_mode_and_writes(mode, writes, allow_live_writes=allow_live_writes)
    path = Path(target)
    if path.exists() or path.suffix == ".py":
        result = asyncio.run(_run_file(path))
        _render_result(result, output)
        return

    resolved_app_name, app_config = _load_app_config(app_name)
    app_key = _app_config_key(resolved_app_name, app_config)
    request_data = _parse_json_option(request_data_json, param_hint="--request-data")
    manual_payload = _parse_json_option(manual_payload_json, param_hint="--manual")
    if target == "message-create" and not latest:
        raise typer.BadParameter(
            "message-create tests require --latest in v1.",
            param_hint="--latest",
        )
    if relay and target == "ingestion" and not save and not save_local:
        result = asyncio.run(
            _run_ingestion_once(
                app_name=resolved_app_name,
                app_key=app_key,
                app_install=app_install,
                agent_id=agent_id,
                body=_read_body(body),
                content_type=content_type,
                mode=mode,
                writes=writes,
            )
        )
        _render_result(result, output)
        return
    if target == "ingestion-relay":
        _serve_ingestion_relay(
            app_name=resolved_app_name,
            app_key=app_key,
            app_install=app_install,
            agent_id=agent_id,
            mode=mode,
            writes=writes,
            port=port,
        )
        return

    destination: Path | None = None
    if save and save_local:
        raise typer.BadParameter("Use only one of --save or --save-local.")
    if save:
        destination = _generated_path(resolved_app_name, save, local=False)
    elif save_local:
        destination = _generated_path(resolved_app_name, save_local, local=True)

    live_snapshot = None
    if destination is None and mode == "sandboxed-live" and snapshot_name is None:
        snapshot_channels = ["deployment_config", "tag_values", "ui_state", "ui_cmds"]
        if channel and channel not in snapshot_channels:
            snapshot_channels.append(channel)
        live_snapshot = _collect_live_snapshot(
            app_name=resolved_app_name,
            app_key=app_key,
            app_install=app_install,
            agent_id=agent_id,
            channels=snapshot_channels,
            latest_messages=[channel] if target == "message-create" and channel else [],
        )

    command = " ".join(["doover", *sys.argv[1:]])
    generated = generate_test_file(
        target,
        app_name=resolved_app_name,
        app_key=app_key,
        app_install=app_install,
        agent_id=agent_id,
        channel=channel,
        body=body,
        content_type=content_type,
        request_data=request_data,
        manual_payload=manual_payload,
        report_fixture=report_fixture,
        mode=mode,
        writes=writes,
        snapshot_name=snapshot_name,
        live_snapshot=live_snapshot,
        command=command,
    )

    if destination is not None:
        if destination.exists():
            raise typer.BadParameter(
                f"{destination} already exists; use clone instead."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if snapshot_name:
            (destination.parent / "snapshots").mkdir(parents=True, exist_ok=True)
        destination.write_text(generated)
        typer.echo(str(destination))
        return

    result = asyncio.run(_run_source(generated))
    _render_result(result, output)


@app.command("promote")
def promote(
    source: Annotated[Path, typer.Argument()],
    to: Annotated[Path | None, typer.Option("--to")] = None,
):
    if not source.exists():
        raise typer.BadParameter(f"{source} does not exist")
    if to is None:
        parts = source.parts
        try:
            local_index = parts.index(".local")
            destination = Path(*parts[:local_index], *parts[local_index + 1 :])
        except ValueError:
            destination = Path("tests/doover") / source.name
    else:
        destination = to / source.name if to.suffix != ".py" else to
    if destination.exists():
        raise typer.BadParameter(f"{destination} already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    typer.echo(str(destination))


@app.command("clone")
def clone(
    source: Annotated[Path, typer.Argument()],
    to: Annotated[str | None, typer.Argument()] = None,
    to_option: Annotated[str | None, typer.Option("--to")] = None,
):
    if not source.exists():
        raise typer.BadParameter(f"{source} does not exist")
    target = to_option or to
    if target is None:
        raise typer.BadParameter("Provide a clone name.")
    destination = source.with_name(
        f"{target}.py" if not target.endswith(".py") else target
    )
    if destination.exists():
        raise typer.BadParameter(f"{destination} already exists")
    shutil.copy2(source, destination)
    typer.echo(str(destination))


@app.command("snapshot")
def snapshot(
    output: Annotated[Path, typer.Option("--output")],
    app_install: Annotated[str | None, typer.Option("--app-install")] = None,
    agent_id: Annotated[int | None, typer.Option("--agent")] = None,
    channel: Annotated[list[str] | None, typer.Option("--channel")] = None,
    app_name: Annotated[str | None, typer.Option("--app-name")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
):
    if output.exists() and not force:
        raise typer.BadParameter(f"{output} already exists; pass --force to overwrite.")
    resolved_app_name, app_config = _load_app_config(app_name)
    app_install_id = int(app_install) if app_install and app_install.isdigit() else None
    owner_agent_id = agent_id or 0
    payload = {
        "schema_version": 1,
        "source": {
            "mode": "fixture",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "doover_cli_version": _version(),
            "profile": None,
            "command": " ".join(["doover", *sys.argv[1:]]),
        },
        "app": {
            "local_name": resolved_app_name,
            "app_key": app_config.get("app_key")
            or app_config.get("key")
            or resolved_app_name,
            "app_id": app_config.get("id"),
            "app_install_id": app_install_id,
            "app_install_name": None if app_install_id else app_install,
            "type": app_config.get("type"),
        },
        "owner": {
            "agent_id": owner_agent_id,
            "organisation_id": app_config.get("organisation_id") or 0,
            "is_org_processor": False,
        },
        "processor_info": {
            "deployment_config": {
                "APP_ID": str(
                    app_config.get("id") or app_install_id or resolved_app_name
                ),
                "APP_DISPLAY_NAME": app_config.get("display_name") or resolved_app_name,
                "dv_proc_config": {"inv_targets": []},
            },
            "tag_values": {resolved_app_name: {}},
            "ui_state": {},
            "ui_cmds": {resolved_app_name: {}},
            "connection_data": {},
        },
        "channels": {
            name: {
                "id": {"agent_id": owner_agent_id, "name": name},
                "aggregate": {"data": {}, "attachments": [], "last_updated": None},
            }
            for name in (channel or [])
        },
        "messages": {},
        "timeseries": {},
        "files": {},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2))
    typer.echo(str(output))
