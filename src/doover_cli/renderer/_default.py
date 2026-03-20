from pydoover.models.control import ControlModel, ControlPage
from typing import Any
import json
from ._base import RendererBase, normalize_render_data

from rich.console import Console
from rich import print_json



class DefaultRenderer(RendererBase):
    
    def __init__(self):
        super().__init__()
        self.console = Console()
    
    def loading(self, message: str):
        return self.console.status(message)
    
    def render_list(self, data: list[Any] | ControlPage[Any]) -> None:
        print_json(json.dumps(normalize_render_data(data), indent=4))
    
    def render(self, data: dict[str, Any] | ControlModel) -> None:
        print_json(json.dumps(normalize_render_data(data), indent=4))
        
    
