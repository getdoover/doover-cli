import time
from pathlib import Path

import typer
from pydoover.cloud.api.channel import Task, Processor
from typing_extensions import Annotated
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydoover.cloud.api import NotFound, Message

from typer import Argument, Option, Typer

from doover_cli.utils import parsers
from doover_cli.utils.formatters import format_channel_info
from .utils.state import state

app = Typer(no_args_is_help=True)


@app.command()
def get(channel_name: Annotated[str, Argument(help="Channel name to get info for")]):
    """Get channel info"""
    try:
        channel = state.api.get_channel(channel_name)
    except NotFound:
        try:
            channel = state.api.get_channel_named(channel_name, state.agent_id)
        except NotFound as e:
            print("Channel not found. Is it owned by this agent?")
            if state.debug:
                raise e
            raise typer.Exit(1)

    print(format_channel_info(channel))


@app.command()
def create(channel_name: Annotated[str, Argument(help="Channel name to create")]):
    """Create new channel"""
    channel = state.api.create_channel(channel_name, state.agent_id)
    print(f"Channel created successfully. ID: {channel.id}")
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
):
    """Create new task channel."""
    processor = state.api.get_channel_named(processor_name, state.agent_id)
    task = state.api.create_task(task_name, state.agent_id, processor.id)
    print(f"Task created successfully. ID: {task.id}")
    print(format_channel_info(task))


def run_for_single_message(
    task, package_path, agent, dry_run, msg_obj, *args, **kwargs
):
    if dry_run:
        return "Dry run successful. Task not invoked."
    msg_dict = msg_obj.to_dict() if msg_obj else None
    task.invoke_locally(
        package_path, msg_dict, {"deployment_config": agent.deployment_config}
    )
    output = (
        f"Task invoked successfully. Message ID: {msg_obj.id if msg_obj else None}."
    )
    if kwargs:
        output = output + f" Extra kwargs: {kwargs}"
    return output


@app.command()
def invoke_local_task(
    task_name: Annotated[
        str, Argument(parser=parsers.task_name, help="Task channel name to create.")
    ],
    package_path: Annotated[
        Path,
        Option(
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Path to the processor package to publish",
        ),
    ],
    channel_name: Annotated[
        str, Argument(help="Take the last message from this channel to start the task")
    ] = None,
    csv_file: Annotated[
        Path,
        Option(
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Path to a CSV export of messages to run the task on.",
        ),
    ] = None,
    parallel_processes: Annotated[
        str, Option(help="Number of parallel processes to run the task with.")
    ] = None,
    dry_run: Annotated[
        bool, Option(help="Whether to run the task without invoking it")
    ] = False,
):
    """Invoke a task locally."""
    task = state.api.get_channel_named(task_name, state.agent_id)
    if not isinstance(task, Task):
        print("That wasn't a task channel. Try again?")
        return
    print(format_channel_info(task))

    agent = state.api.get_agent(state.agent_id)

    if csv_file is not None:
        messages = Message.from_csv_export(state.api, csv_file)
        print(f"Loaded {len(messages)} messages from CSV export.")

        if not parallel_processes or parallel_processes == 1:
            for msg in messages:
                print(
                    f"\nRunning task for message: {msg.id}, with timestamp: {msg.timestamp}. {messages.index(msg) + 1}/{len(messages)}\n"
                )
                run_for_single_message(task, package_path, agent, dry_run, msg)
        else:
            with ThreadPoolExecutor(max_workers=parallel_processes) as executor:
                futures = [
                    executor.submit(
                        run_for_single_message,
                        msg,
                        task_num=messages.index(msg),
                        total_tasks=len(messages),
                    )
                    for msg in messages
                ]
                for future in as_completed(futures):
                    print(future.result())

    else:
        msg_obj = None
        if channel_name:
            channel = state.api.get_channel_named(channel_name, state.agent_id)
            msg_obj = channel.last_message

        if not msg_obj:
            print("No message found. running task without a message.")
        else:
            print(
                f"\nRunning task for message: {msg_obj.id}, with timestamp: {msg_obj.timestamp}\n"
            )
        run_for_single_message(task, package_path, agent, dry_run, msg_obj)


@app.command()
def create_processor(
    processor_name: Annotated[
        str, Argument(parser=parsers.processor_name, help="Processor name.")
    ],
):
    """Create new processor channel."""
    processor = state.api.create_processor(processor_name, state.agent_id)
    print(f"Processor created successfully. ID: {processor.id}")
    print(format_channel_info(processor))


@app.command()
def publish(
    channel_name: Annotated[str, Argument(help="Channel name to publish to")],
    message: Annotated[
        str, Argument(help="Message to publish", parser=parsers.maybe_json)
    ],
):
    """Publish to a doover channel."""
    try:
        channel = state.api.get_channel_named(channel_name, state.agent_id)
    except NotFound:
        print("Channel name was incorrect. Is it owned by this agent?")
        return

    if isinstance(message, dict):
        print("Successfully loaded message as JSON.")

    channel.publish(message)
    print("Successfully published message.")


@app.command()
def publish_file(
    channel_name: Annotated[str, Argument(help="Channel name to publish to")],
    file_path: Annotated[Path, Argument(help="Path to the file to publish")],
):
    """Publish file to a processor channel."""
    if not file_path.exists():
        print("File path was incorrect.")
        return

    try:
        channel = state.api.get_channel_named(channel_name, state.agent_id)
    except NotFound:
        print("Channel name was incorrect. Is it owned by this agent?")
        return

    channel.update_from_file(file_path)
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
):
    """Publish processor package to a processor channel."""
    if not package_path.exists():
        print("Package path was incorrect.")
        return

    try:
        channel = state.api.get_channel_named(processor_name, state.agent_id)
    except NotFound:
        print("Channel name was incorrect. Is it owned by this agent?")
        return

    if not isinstance(channel, Processor):
        print("Channel name is not a processor. Try a different name?")
        return

    channel.update_from_package(package_path)
    print("Successfully published new package.")


@app.command()
def follow(
    channel_name: Annotated[str, Argument(help="Channel name to publish to")],
    poll_rate: Annotated[
        int, Argument(help="Frequency to check for new messages (in seconds)")
    ] = 5,
):
    """Follow aggregate of a doover channel"""
    channel = state.api.get_channel_named(channel_name, state.agent_id)
    print(format_channel_info(channel))

    while True:
        old_aggregate = channel.aggregate
        channel.update()
        if channel.aggregate != old_aggregate:
            print(channel.aggregate)

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
):
    """Add a channel to a task's subscriptions."""
    task = state.api.get_channel_named(task_name, state.agent_id)
    if not isinstance(task, Task):
        print("That wasn't a task channel. Try again?")
        return

    channel = state.api.get_channel_named(channel_name, state.agent_id)
    task.subscribe_to_channel(channel.id)
    print(f"Successfully added {channel_name} to {task.name}'s subscriptions.")


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
):
    """Remove a channel to a task's subscriptions."""
    task = state.api.get_channel_named(task_name, state.agent_id)
    if not isinstance(task, Task):
        print("That wasn't a task channel. Try again?")
        return

    channel = state.api.get_channel_named(channel_name, state.agent_id)
    task.unsubscribe_from_channel(channel.id)
    print(f"Successfully removed {channel_name} from {task.name}'s subscriptions.")
