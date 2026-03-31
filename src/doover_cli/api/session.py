import os

import typer

from pydoover.api import DataClient, ControlClient
from pydoover.api.auth import ConfigManager

from .auth import DooverCLIAuthClient


class DooverCLISession:
    def __init__(
        self,
        *,
        config_manager: ConfigManager | None,
        profile_name: str | None,
        auth: DooverCLIAuthClient,
        control_client=None,
    ):
        self.config_manager = config_manager
        self.profile_name = profile_name
        self.auth = auth
        self.control_client = control_client
        self._data_client: DataClient | None = None
        self._control_client: ControlClient | None = None

    @classmethod
    def from_profile(
        cls,
        profile_name: str,
        *,
        config_manager: ConfigManager | None = None,
        timeout: float = 60.0,
    ) -> "DooverCLISession":
        manager = config_manager or ConfigManager(profile_name)
        manager.current_profile = profile_name
        auth = DooverCLIAuthClient.from_profile_name(
            profile_name,
            config_manager=manager,
            timeout=timeout,
        )
        return cls(
            config_manager=manager,
            profile_name=profile_name,
            auth=auth,
        )

    @classmethod
    def from_env(cls, *, timeout: float = 60.0) -> "DooverCLISession":
        token = os.environ.get("DOOVER_API_TOKEN")
        if not token:
            raise RuntimeError("DOOVER_API_TOKEN is not set.")

        data_base_url = os.environ.get("DOOVER_DATA_API_BASE_URL")
        if not data_base_url:
            raise RuntimeError(
                "DOOVER_DATA_API_BASE_URL is required when DOOVER_API_TOKEN is set."
            )

        auth = DooverCLIAuthClient(
            token=token,
            data_base_url=data_base_url,
            timeout=timeout,
        )
        return cls(
            config_manager=None,
            profile_name=None,
            auth=auth,
        )

    def get_data_client(self) -> DataClient:
        if self._data_client is None:
            self._data_client = DataClient(auth=self.auth)
        return self._data_client

    def get_control_client(self) -> ControlClient:
        if self._control_client is None:
            self._control_client = ControlClient(auth=self.auth)
        return self._control_client

    def require_agent_id(self, agent_id: int | str | None) -> int:
        if agent_id is None:
            raise typer.BadParameter(
                "Please provide --agent with an integer Doover agent ID.",
                param_hint="--agent",
            )

        try:
            return int(agent_id)
        except (TypeError, ValueError) as exc:
            raise typer.BadParameter(
                "Please provide --agent with an integer Doover agent ID.",
                param_hint="--agent",
            ) from exc

    def resolve_agent_query(self, agent_query: str | None):
        if agent_query is None:
            return None
        raise NotImplementedError()
        # self.get_control_client().agents
