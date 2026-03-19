from typing import Annotated

import typer
from typer import Typer

from doover_cli.api import DooverCLIAuthClient

from .utils.sentry import capture_handled_exception
from .utils.state import state

app = Typer(no_args_is_help=True)


@app.command()
def login(
    staging: Annotated[
        bool, typer.Option(help="Whether to login to the staging site")
    ] = False,
    profile: Annotated[
        str | None,
        typer.Option(help="Profile name to store credentials under."),
    ] = None,
):
    """Login to your Doover account with device authorization."""
    profile_name = profile or ("staging" if staging else "default")

    try:
        auth = DooverCLIAuthClient.device_login(staging=staging)
    except Exception as exc:
        print("Login failed. Please try again.")
        if state.debug:
            raise
        capture_handled_exception(
            exc,
            command="login",
            message="Login failed. Please try again.",
        )
        raise typer.Exit(1) from exc

    auth.persist_profile(profile_name, state.config_manager)
    state.config_manager.current_profile = profile_name
    state.profile_name = profile_name
    state._session = None

    environment = "staging" if staging else "production"
    print(
        f"Successfully logged into Doover ({environment}). You can now run `doover ... --profile {profile_name}`."
    )
