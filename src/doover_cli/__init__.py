from typing import Annotated, Optional

import typer

from pydoover.cloud.api import ConfigManager

from .apps import app as apps_app
from .config_schema import app as config_schema_app
from .simulator import app as simulators_app
from .agent import app as agents_app
from .channel import app as channels_app
from .doover_config import app as doover_config_app
from .grpc import app as grpc_app
from .login import app as login_app
from .report import app as reports_app
from .tunnel import app as tunnels_app
from .utils.state import state

app = typer.Typer(no_args_is_help=True)
app.add_typer(
    apps_app, name="app", help="Manage applications and their configurations."
)
app.add_typer(
    config_schema_app, name="config-schema", help="Manage application config schemas."
)
app.add_typer(
    simulators_app, name="simulator", help="Manage simulators and their configurations."
)
app.add_typer(agents_app, name="agent", help="Manage agents and their configurations.")
app.add_typer(
    channels_app, name="channel", help="Manage channels and their configurations."
)
app.add_typer(
    doover_config_app, name="doover-config", help="Manage doover configuration files."
)
app.add_typer(login_app)
app.add_typer(reports_app, name="report", help="Generate and manage reports.")
app.add_typer(tunnels_app, name="tunnel", help="Manage SSH tunnels for remote access.")
app.add_typer(grpc_app, name="grpc", help="Interact with running gRPC servers.")


def version_callback(value: bool):
    if value:
        from importlib import metadata

        version = metadata.version("doover-cli")
        print(f"Doover CLI: {version}")
        raise typer.Exit()


@app.callback()
def load_ctx(
    debug: Annotated[
        bool, typer.Option(help="Enable debug output, including error messages")
    ] = False,
    json: Annotated[
        bool, typer.Option(help="Set flag to output results in json format")
    ] = False,
    version: Annotated[
        Optional[bool], typer.Option("--version", callback=version_callback)
    ] = None,
):
    state.agent_query = None
    state.config_manager = ConfigManager("default")
    state.debug = debug
    state.json = json

    # return ctx.invoke(ctx.obj, *args, **kwargs)


def main():
    """
    Main entry point for the Doover CLI.
    """
    app()
