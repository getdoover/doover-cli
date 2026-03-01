from pydoover.cloud.api import Client, ConfigManager, Agent

from .api import setup_api


class State:
    def __init__(self):
        self.agent_query: str | None = None
        self.agent_id: str | None = None
        self.agent: str | None = None

        self.debug: bool = False
        self.json: bool = False

        self.config_manager: ConfigManager | None = None
        self._api: Client | None = None

    @property
    def api(self):
        """Allows lazy loading of the API client.

        This means commands are free to use `state.api`, but it is not loaded until that is called.

        Loading can take time, especially if logging in is required.
        """
        if self._api is None:
            self._api, agent = setup_api(self.agent_query, self.config_manager)
            self.agent = agent
            if isinstance(agent, int):
                self.agent_id = agent
            elif isinstance(agent, Agent):
                self.agent_id = agent.id
            # self.agent_id = self.api.agent_id = agent.id
        return self._api


# dirty big global variable but it's OK.
state = State()
