import json
import mimetypes
import time
from pathlib import Path

import typer
from pydoover.api import NotFoundError
from pydoover.models.attachment import File
from typer import Argument, Typer
from typing_extensions import Annotated

from .utils import parsers
from .utils.api import AgentAnnotation, ProfileAnnotation, exit_for_unsupported_control_command
from .utils.formatters import format_channel_info
from .utils.sentry import capture_handled_exception
from .utils.state import state

app = Typer(no_args_is_help=True)


def _get_data_client_and_agent_id() -> tuple[object, int]:
    session = state.session
    return session.get_data_client(), session.require_agent_id(state.agent_id)


def _coerce_aggregate_payload(message) -> dict:
    if isinstance(message, dict):
        return message
    return {"value": message}


@app.command()
def get(
    channel_name: Annotated[str, Argument(help="Channel name to get info for")],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Get channel info."""
    client, agent_id = _get_data_client_and_agent_id()

    try:
        channel = client.fetch_channel(agent_id, channel_name, include_aggregate=True)
    except NotFoundError as exc:
        print("Channel not found. Is it owned by this agent?")
        if state.debug:
            raise
        capture_handled_exception(
            exc,
            command="channel.get",
            message="Channel not found. Is it owned by this agent?",
        )
        raise typer.Exit(1) from exc

    print(format_channel_info(channel))


@app.command()
def create(
    channel_name: Annotated[str, Argument(help="Channel name to create")],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Create new channel."""
    client, agent_id = _get_data_client_and_agent_id()
    channel_id = client.create_channel(agent_id, channel_name)
    channel = client.fetch_channel(agent_id, channel_name, include_aggregate=True)
    print(f"Channel created successfully. ID: {channel_id}")
    print(format_channel_info(channel))


@app.command()
def create_task(
    task_name: Annotated[
        str, Argument(parser=parsers.task_name, help="Task channel name to create.")
    ],
    processor_name: Annotated[
        str,
        Argument(
            parser=parsers.processor_name,
            help="Processor name for this task to trigger.",
        ),
    ],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Create new task channel."""
    _ = (task_name, processor_name, _profile, _agent)
    exit_for_unsupported_control_command("channel.create-task")


@app.command()
def invoke_local_task(
    task_name: Annotated[
        str, Argument(parser=parsers.task_name, help="Task channel name to create.")
    ],
    package_path: Annotated[Path, typer.Option(help="Path to the processor package.")],
    channel_name: Annotated[
        str | None, Argument(help="Take the last message from this channel to start the task")
    ] = None,
    csv_file: Annotated[
        Path | None,
        typer.Option(help="Path to a CSV export of messages to run the task on."),
    ] = None,
    parallel_processes: Annotated[
        str | None, typer.Option(help="Number of parallel processes to run the task with.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option(help="Whether to run the task without invoking it")
    ] = False,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Invoke a task locally."""
    _ = (
        task_name,
        package_path,
        channel_name,
        csv_file,
        parallel_processes,
        dry_run,
        _profile,
        _agent,
    )
    exit_for_unsupported_control_command("channel.invoke-local-task")


@app.command()
def create_processor(
    processor_name: Annotated[
        str, Argument(parser=parsers.processor_name, help="Processor name.")
    ],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Create new processor channel."""
    _ = (processor_name, _profile, _agent)
    exit_for_unsupported_control_command("channel.create-processor")


@app.command()
def publish(
    channel_name: Annotated[str, Argument(help="Channel name to publish to")],
    message: Annotated[
        str, Argument(help="Message to publish", parser=parsers.maybe_json)
    ],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Publish to a Doover channel aggregate."""
    client, agent_id = _get_data_client_and_agent_id()
    payload = _coerce_aggregate_payload(message)

    try:
        client.update_channel_aggregate(
            agent_id,
            channel_name,
            data=payload,
            replace=False,
            log_update=True,
        )
    except NotFoundError as exc:
        print("Channel name was incorrect. Is it owned by this agent?")
        if state.debug:
            raise
        capture_handled_exception(
            exc,
            command="channel.publish",
            message="Channel name was incorrect. Is it owned by this agent?",
        )
        raise typer.Exit(1) from exc

    if isinstance(message, dict):
        print("Successfully loaded message as JSON.")
    print("Successfully published message.")


@app.command()
def publish_file(
    channel_name: Annotated[str, Argument(help="Channel name to publish to")],
    file_path: Annotated[Path, Argument(help="Path to the file to publish")],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Publish a file to a channel aggregate."""
    client, agent_id = _get_data_client_and_agent_id()
    mime_type, _ = mimetypes.guess_type(file_path)
    attachment = File(
        filename=file_path.name,
        content_type=mime_type or "application/octet-stream",
        size=file_path.stat().st_size,
        data=file_path.read_bytes(),
    )

    try:
        client.update_channel_aggregate(
            agent_id,
            channel_name,
            data={"output_type": attachment.content_type},
            replace=True,
            files=[attachment],
            log_update=True,
        )
    except NotFoundError as exc:
        print("Channel name was incorrect. Is it owned by this agent?")
        if state.debug:
            raise
        capture_handled_exception(
            exc,
            command="channel.publish-file",
            message="Channel name was incorrect. Is it owned by this agent?",
        )
        raise typer.Exit(1) from exc

    print("Successfully published new file.")


@app.command()
def publish_processor(
    processor_name: Annotated[
        str,
        Argument(
            parser=parsers.processor_name, help="Processor channel name to publish to"
        ),
    ],
    package_path: Annotated[Path, Argument(help="Path to the package to publish")],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Publish processor package to a processor channel."""
    _ = (processor_name, package_path, _profile, _agent)
    exit_for_unsupported_control_command("channel.publish-processor")


@app.command()
def follow(
    channel_name: Annotated[str, Argument(help="Channel name to follow")],
    poll_rate: Annotated[
        int, Argument(help="Frequency to check for new messages (in seconds)")
    ] = 5,
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Follow aggregate of a Doover channel."""
    client, agent_id = _get_data_client_and_agent_id()
    channel = client.fetch_channel(agent_id, channel_name, include_aggregate=True)
    print(format_channel_info(channel))

    old_aggregate = channel.aggregate.to_dict() if channel.aggregate else None
    while True:
        aggregate = client.fetch_channel_aggregate(agent_id, channel_name)
        new_aggregate = aggregate.to_dict()
        if new_aggregate != old_aggregate:
            old_aggregate = new_aggregate
            if state.json:
                print(json.dumps(new_aggregate, indent=4))
            else:
                print(json.dumps(aggregate.data, indent=4))
        time.sleep(poll_rate)


@app.command()
def subscribe(
    task_name: Annotated[
        str,
        Argument(help="Task name to add the subscription to", parser=parsers.task_name),
    ],
    channel_name: Annotated[
        str, Argument(help="Channel name to add the subscription to")
    ],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Add a channel to a task's subscriptions."""
    _ = (task_name, channel_name, _profile, _agent)
    exit_for_unsupported_control_command("channel.subscribe")


@app.command()
def unsubscribe(
    task_name: Annotated[
        str,
        Argument(
            parser=parsers.task_name, help="Task name to remove the subscription from"
        ),
    ],
    channel_name: Annotated[
        str, Argument(help="Channel name to remove the subscription from")
    ],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Remove a channel from a task's subscriptions."""
    _ = (task_name, channel_name, _profile, _agent)
    exit_for_unsupported_control_command("channel.unsubscribe")
