from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from pydoover.api.auth import ConfigManager

    from doover_cli.api import DooverCLISession


class Context(typer.Context):
    session: "DooverCLISession"
    config_manager: "ConfigManager"
    profile_name: str
    agent_id: int
