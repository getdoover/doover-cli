from typing import Annotated

import typer
from typer import Typer

from doover_cli.api import DooverCLIAuthClient

from .registry import register_credential_helper, registry_host

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
    if state.config_manager is not None:
        state.config_manager.current_profile = profile_name
    state.profile_name = profile_name
    state._session = None

    environment = "staging" if staging else "production"
    print(
        f"Successfully logged into Doover ({environment}). You can now run `doover ... --profile {profile_name}`."
    )

    # Point docker at our credential helper so `docker pull`/`push` against the
    # doover registry just work, with no `docker login` and no credentials
    # written to disk. Best-effort: failing to edit the user's docker config is
    # not a reason to fail the login.
    try:
        # Register the registry that belongs to the environment just logged into,
        # so a staging login makes staging images pullable rather than production's.
        if register_credential_helper(registry_host(auth.control_base_url)):
            print(
                "Configured docker to use your Doover login for "
                f"{registry_host(auth.control_base_url)} images."
            )
    except Exception:
        if state.debug:
            raise
