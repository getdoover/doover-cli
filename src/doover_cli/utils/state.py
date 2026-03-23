from doover_cli.renderer import RendererBase, Renderer, setup_renderer
from pydoover.api.auth import ConfigManager

from doover_cli.api import DooverCLISession

from .api import setup_session


class State:
    def __init__(self):
        self.agent_id: int | None = None
        self.profile_name: str = "default"

        self.debug: bool = False
        self.json: bool = False
        self.renderer_name: Renderer | None = None
        self._renderer: RendererBase | None = None

        self.config_manager: ConfigManager | None = None
        self._session: DooverCLISession | None = None

    @property
    def session(self) -> DooverCLISession:
        if self._session is None:
            self._session = setup_session(self.profile_name, self.config_manager)
        return self._session
    
    @property
    def renderer(self) -> RendererBase:
        if self._renderer is None:
            self._renderer = setup_renderer(self.renderer_name or Renderer.default)
            
        return self._renderer


# dirty big global variable but it's OK.
state = State()
