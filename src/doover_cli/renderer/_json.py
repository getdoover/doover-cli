from ._base import RendererBase, EmptyEnterable, normalize_render_data
from pydoover.models.control import ControlModel, ControlPage
from typing import Any, ContextManager
import json



class JsonRenderer(RendererBase):
    
    def loading(self, message: str) -> ContextManager[Any]:
        return EmptyEnterable()
    
    def render_list(self, data: list[Any] | ControlPage[Any]) -> None:
        print(json.dumps(normalize_render_data(data), indent=4))
    
    def render(self, data: dict[str, Any] | ControlModel) -> None:
        print(json.dumps(normalize_render_data(data), indent=4))
