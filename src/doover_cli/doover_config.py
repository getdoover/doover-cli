from pathlib import Path

from typer import Argument, Typer
from typing_extensions import Annotated

from .utils.api import (
    AgentAnnotation,
    ProfileAnnotation,
    exit_for_unsupported_control_command,
)

app = Typer(no_args_is_help=True)


@app.command()
def deploy(
    config_file: Annotated[
        Path,
        Argument(
            help="Deployment config file to use. This is usually a doover_config.json file."
        ),
    ],
    _profile: ProfileAnnotation = None,
    _agent: AgentAnnotation = None,
):
    """Deploy a doover config file to the site."""
    _ = (config_file, _profile, _agent)
    exit_for_unsupported_control_command("doover-config.deploy")
