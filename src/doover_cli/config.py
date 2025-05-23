import json
import os
from pathlib import Path

from typer import Argument, Typer
from typing_extensions import Annotated

from .utils.state import state

app = Typer(no_args_is_help=True)


@app.command()
def deploy(
    config_file: Annotated[
        Path,
        Argument(
            help="Deployment config file to use. This is usually a doover_config.json file."
        ),
    ],
):
    """Deploy a doover config file to the site."""
    if not config_file.exists():
        print("Config file not found.")
        return

    parent_dir = os.path.dirname(config_file)

    with open(config_file, "r") as config_file:
        data = json.loads(config_file.read())

    print("Read config file.")

    proc_deploy_data = data.get("processor_deployments")
    if proc_deploy_data:
        for processor_data in proc_deploy_data.get("processors", []):
            processor = state.api.create_processor(
                processor_data["name"], state.agent_id
            )
            processor.update_from_package(
                os.path.join(parent_dir, processor_data["processor_package_dir"])
            )
            processor.update()
            print(
                f"Created or updated processor {processor.name} with processor data length: {len(processor.aggregate)}"
            )

        for task_data in proc_deploy_data.get("tasks", []):
            processor = state.api.get_channel_named(
                task_data["processor_name"], state.agent_id
            )
            task = state.api.create_task(
                task_data["name"], state.agent_id, processor.id
            )
            task.publish(task_data["task_config"])
            print(f"Created or updated task {task.name}, and deployed new config.")

            for subscription in task_data.get("subscriptions", []):
                channel = state.api.create_channel(
                    subscription["channel_name"], state.agent_id
                )
                if subscription["is_active"] is True:
                    task.subscribe_to_channel(channel.id)
                    print(
                        f"Added {channel.name} as a subscription to task {task.name}."
                    )
                else:
                    task.unsubscribe_from_channel(channel.id)
                    print(
                        f"Removed {channel.name} as a subscription from task {task.name}."
                    )

    file_deploy_data = data.get("file_deployments")
    if file_deploy_data:
        for entry in file_deploy_data.get("files", []):
            channel = state.api.create_channel(entry["name"], state.agent_id)
            mime_type = entry.get("mime_type", None)
            channel.update_from_file(
                os.path.join(parent_dir, entry["file_dir"]), mime_type
            )
            print(f"Published file to {channel.name}")

    for entry in data.get("deployment_channel_messages", []):
        channel = state.api.create_channel(entry["channel_name"], state.agent_id)
        save_log = entry.get("save_log", True)
        channel.publish(entry["channel_message"], save_log=save_log)
        print(f"Published message to {channel.name}")

    print("Successfully deployed config.")
