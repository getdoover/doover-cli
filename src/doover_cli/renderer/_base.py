from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ContextManager

from pydoover.models.control import Agent, Agents, ControlModel, ControlPage

if TYPE_CHECKING:
    from ..utils.crud import Field


class EmptyEnterable:
    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@dataclass(slots=True)
class TreeNode:
    element: ControlModel
    children: list["TreeNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        output = self.element.to_dict()
        output["children"] = [child.to_dict() for child in self.children]
        return output


def format_tree_label(element: ControlModel) -> str:
    """Derive a human-readable label for a ``TreeNode``'s element.

    Tree display is distinct from the single-record detail view: device-type
    agents render as ``"DisplayName (name | id) type (Archived)"``; other
    agents fall back to ``"DisplayName (id)"``; groups/organisations use
    their ``name``; the root ``Agents`` container labels as ``"Agents"``.
    """
    if isinstance(element, Agents):
        return "Agents"
    if isinstance(element, Agent):
        agent_type = getattr(element, "type", None) or "device"
        if agent_type in {"device", "dict"}:
            return _format_device_tree_label(element)
        return _format_generic_agent_tree_label(element)

    name = getattr(element, "name", None) or getattr(element, "display_name", None)
    if name:
        return str(name)
    resource_id = getattr(element, "id", None)
    if resource_id is not None:
        return str(resource_id)
    return getattr(element, "_model_name", None) or type(element).__name__


def _format_device_tree_label(agent: Agent) -> str:
    display_name = str(
        getattr(agent, "display_name", None)
        or getattr(agent, "name", None)
        or getattr(agent, "id", None)
        or "Device"
    )
    name = str(getattr(agent, "name", "") or "")
    agent_id = str(getattr(agent, "id", "") or "")
    agent_type = getattr(agent, "type", "") or "device"
    if agent_type == "dict":
        agent_type = "device"
    archived = " (Archived)" if getattr(agent, "archived", False) else ""
    return f"{display_name} ({name} | {agent_id}) {agent_type}{archived}"


def _format_generic_agent_tree_label(agent: Agent) -> str:
    label = str(
        getattr(agent, "display_name", None)
        or getattr(agent, "name", None)
        or getattr(agent, "id", None)
        or "Agent"
    )
    agent_id = getattr(agent, "id", None)
    if agent_id is not None:
        label = f"{label} ({agent_id})"
    return label


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
