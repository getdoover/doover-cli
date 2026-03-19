from pydoover.api.auth import ConfigManager

from doover_cli.api import DooverCLISession

from .api import setup_session


class State:
    def __init__(self):
        self.agent_id: int | None = None
        self.profile_name: str = "default"

        self.debug: bool = False
        self.json: bool = False

        self.config_manager: ConfigManager | None = None
        self._session: DooverCLISession | None = None

    @property
    def session(self):
        if self._session is None:
            self._session = setup_session(self.profile_name, self.config_manager)
        return self._session


# dirty big global variable but it's OK.
state = State()
