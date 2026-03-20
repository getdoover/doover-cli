import os
from typing import Annotated

import typer
from pydoover.api.auth import ConfigManager
from typer import Option

from doover_cli.api import ControlClientUnavailableError, DooverCLISession


def setup_session(
    profile_name: str,
    config_manager: ConfigManager | None = None,
) -> DooverCLISession:
    if os.environ.get("DOOVER_API_TOKEN"):
        return DooverCLISession.from_env()

    manager = config_manager or ConfigManager(profile_name)
    manager.current_profile = profile_name
    return DooverCLISession.from_profile(profile_name, config_manager=manager)


def profile_callback(value: str | None):
    from .state import state

    profile_name = value or "default"
    state.profile_name = profile_name
    state._session = None
    if state.config_manager is not None:
        state.config_manager.current_profile = profile_name
    return profile_name


def agent_callback(value: str | None):
    from .state import state

    if value is None:
        state.agent_id = None
        return value

    try:
        state.agent_id = int(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "Please provide --agent with an integer Doover agent ID.",
            param_hint="--agent",
        ) from exc
    return value


ProfileAnnotation = Annotated[
    str,
    Option(
        help="Config profile to use for this request.",
        callback=profile_callback,
    ),
]
AgentAnnotation = Annotated[
    str,
    Option(
        "--agent",
        help="Doover agent ID to use for this request.",
        callback=agent_callback,
    ),
]


def exit_for_unsupported_control_command(command_name: str) -> None:
    try:
        raise ControlClientUnavailableError(command_name)
    except ControlClientUnavailableError as exc:
        from .sentry import capture_handled_exception

        print(exc)
        capture_handled_exception(
            exc,
            command=command_name,
            message=str(exc),
        )
        raise typer.Exit(1) from exc
