from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from pydoover.cloud.api import Client
    from .config import ConfigManager


class Context(typer.Context):
    api: "Client"
    config_manager: "ConfigManager"
    agent_query: str
    agent_id: str
    agent: str
