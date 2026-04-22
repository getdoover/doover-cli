from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ContextManager

from pydoover.models.control import ControlModel, ControlPage

if TYPE_CHECKING:
    from ..utils.crud import Field


class EmptyEnterable:
    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@dataclass(slots=True)
class TreeNode:
    label: str
    children: list["TreeNode"] = field(default_factory=list)
    style: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "children": [child.to_dict() for child in self.children],
            "style": self.style,
        }


class RendererBase:
    def loading(self, message: str) -> ContextManager[Any]:
        raise NotImplementedError()

    def prompt_fields(self, fields: list["Field"]) -> dict[str, Any]:
        raise NotImplementedError()

    def render_list(self, data: list[Any] | ControlPage[Any]) -> None:
        raise NotImplementedError()

    def render(self, data: dict[str, Any] | ControlModel) -> None:
        raise NotImplementedError()

    def tree(self, data: TreeNode) -> None:
        raise NotImplementedError()


def normalize_render_data(data: Any) -> Any:
    if isinstance(data, ControlPage):
        return data.to_dict()
    if isinstance(data, ControlModel):
        return data.to_dict()
    if isinstance(data, list):
        return [normalize_render_data(item) for item in data]
    return data
