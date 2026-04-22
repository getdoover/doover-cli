import json
from typing import TYPE_CHECKING, Any, ContextManager

from pydoover.models.control import ControlModel, ControlPage

from ._base import RendererBase, EmptyEnterable, TreeNode, normalize_render_data
from ._basic import BasicRenderer

if TYPE_CHECKING:
    from ..utils.crud import Field


class JsonRenderer(RendererBase):
    def loading(self, message: str) -> ContextManager[Any]:
        return EmptyEnterable()

    def prompt_fields(self, fields: list["Field"]) -> dict[str, Any]:
        return BasicRenderer().prompt_fields(fields)

    def render_list(self, data: list[Any] | ControlPage[Any]) -> None:
        print(json.dumps(normalize_render_data(data), indent=4))

    def render(self, data: dict[str, Any] | ControlModel) -> None:
        print(json.dumps(normalize_render_data(data), indent=4))

    def tree(self, data: TreeNode) -> None:
        print(json.dumps(data.to_dict(), indent=4))
