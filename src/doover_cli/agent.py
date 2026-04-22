from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Annotated, Any

import typer
from pydoover.models.control import Agent, Agents, Group
from typer import Typer

from .colours import ARCHIVED_DEVICE_COLOUR, ENTITY_COLOURS
from .renderer import TreeNode
from .renderer._base import normalize_render_data
from .utils.api import ProfileAnnotation
from .utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from .renderer import RendererBase

app = Typer(no_args_is_help=True)


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


@app.command(name="list")
def list_(
    tree: Annotated[
        bool,
        typer.Option(
            "--tree",
            help="Show agents grouped into a tree instead of a table.",
        ),
    ] = False,
    include_archived: Annotated[
        bool,
        typer.Option(
            "--include-archived",
            help="Include archived agents and groups.",
        ),
    ] = False,
    _profile: ProfileAnnotation = None,
):
    """List available agents."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading agents..."):
        response = client.agents.retrieve(include_archived=include_archived)

    if tree:
        renderer.tree(build_agents_tree(response))
        return

    renderer.render_list(response.agents)


def build_agents_tree(response: Agents) -> TreeNode:
    group_entries = _flatten_groups(response.groups or [])
    groups = [group for group, _parent_id in group_entries]
    agents = list(response.agents or [])
    root = TreeNode("Agents")
    groups_by_id = {
        group_id: group
        for group in groups
        if (group_id := _resource_id(group)) is not None
    }
    group_ids = set(groups_by_id)
    group_ids_by_name = {
        str(group_name): group_id
        for group_id, group in groups_by_id.items()
        if (group_name := _field_value(group, "name"))
    }
    groups_by_parent_id: dict[int | None, list[Group]] = defaultdict(list)
    agents_by_group_id, agents_by_unknown_group = _group_agents(
        agents,
        group_ids=group_ids,
        group_ids_by_name=group_ids_by_name,
    )

    for group, inferred_parent_id in group_entries:
        parent_id = _resource_id(_field_value(group, "parent"))
        if parent_id is None:
            parent_id = inferred_parent_id
        if parent_id not in group_ids:
            parent_id = None
        groups_by_parent_id[parent_id].append(group)

    for siblings in groups_by_parent_id.values():
        siblings.sort(key=_group_sort_key)
    for grouped_agents in agents_by_group_id.values():
        grouped_agents.sort(key=_agent_sort_key)
    for grouped_agents in agents_by_unknown_group.values():
        grouped_agents.sort(key=_agent_sort_key)

    root.children.extend(
        _build_group_branch(group, groups_by_parent_id, agents_by_group_id)
        for group in groups_by_parent_id[None]
    )

    for group_name in sorted(name for name in agents_by_unknown_group if name):
        root.children.append(
            TreeNode(
                group_name,
                children=[
                    _build_agent_node(agent)
                    for agent in agents_by_unknown_group[group_name]
                ],
                style=ENTITY_COLOURS["group"],
            )
        )

    if "" in agents_by_unknown_group:
        root.children.append(
            TreeNode(
                "Ungrouped",
                children=[
                    _build_agent_node(agent) for agent in agents_by_unknown_group[""]
                ],
                style=ENTITY_COLOURS["group"],
            )
        )

    if not root.children and agents:
        root.children.extend(
            _build_agent_node(agent) for agent in sorted(agents, key=_agent_sort_key)
        )

    return root


def _flatten_groups(groups: list[Group]) -> list[tuple[Group, int | None]]:
    flattened: list[tuple[Group, int | None]] = []

    def visit(group: Group, parent_id: int | None, path: set[int]) -> None:
        group_id = _resource_id(group)
        flattened.append((group, parent_id))

        if group_id is not None:
            if group_id in path:
                return
            path = {*path, group_id}

        for child in _field_value(group, "children", []) or []:
            visit(child, group_id, path)

    for group in groups:
        visit(group, None, set())

    return flattened


def _build_group_branch(
    group: Group,
    groups_by_parent_id: dict[int | None, list[Group]],
    agents_by_group_id: dict[int, list[Agent]],
) -> TreeNode:
    group_id = _resource_id(group)
    children = [
        _build_group_branch(child, groups_by_parent_id, agents_by_group_id)
        for child in groups_by_parent_id.get(group_id, [])
    ]
    if group_id is not None:
        children.extend(
            _build_agent_node(agent) for agent in agents_by_group_id.get(group_id, [])
        )
    return TreeNode(_group_label(group), children=children, style=ENTITY_COLOURS["group"])


def _build_agent_node(agent: Agent) -> TreeNode:
    if _is_device_agent(agent):
        return TreeNode(
            _format_device_label(agent),
            style=(
                ARCHIVED_DEVICE_COLOUR
                if _field_value(agent, "archived", False)
                else ENTITY_COLOURS["device"]
            ),
        )

    label = str(
        _field_value(agent, "display_name")
        or _field_value(agent, "name")
        or _field_value(agent, "id", "Agent")
    )
    agent_id = _field_value(agent, "id")
    if agent_id is not None:
        label = f"{label} ({agent_id})"

    return TreeNode(
        label,
        children=[
            _value_to_tree_node(key, value) for key, value in _agent_fields(agent).items()
        ],
    )


def _format_device_label(agent: Agent) -> str:
    display_name = str(
        _field_value(agent, "display_name")
        or _field_value(agent, "name")
        or _field_value(agent, "id", "Device")
    )
    name = str(_field_value(agent, "name", "") or "")
    agent_id = str(_field_value(agent, "id", "") or "")
    agent_type = "device" if _agent_type(agent) == "dict" else _agent_type(agent)
    archived = " (Archived)" if _field_value(agent, "archived", False) else ""
    return f"{display_name} ({name} | {agent_id}) {agent_type}{archived}"


def _agent_fields(agent: Agent) -> dict[str, Any]:
    normalized = normalize_render_data(agent)
    if not isinstance(normalized, dict):
        return {"value": normalized}

    ordered: dict[str, Any] = {}
    for field_name in getattr(agent, "_field_defs", {}):
        if field_name in normalized:
            ordered[field_name] = normalized[field_name]
    for key, value in normalized.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _value_to_tree_node(key: str, value: Any) -> TreeNode:
    style = ENTITY_COLOURS["organisation"] if key == "organisation" else None
    if isinstance(value, dict):
        return TreeNode(
            key,
            children=[
                _value_to_tree_node(child_key, child_value)
                for child_key, child_value in value.items()
            ],
            style=style,
        )
    if isinstance(value, list):
        return TreeNode(
            key,
            children=[
                _value_to_tree_node(f"[{index}]", item)
                for index, item in enumerate(value)
            ],
            style=style,
        )
    return TreeNode(f"{key}: {value}", style=style)


def _group_agents(
    agents: list[Agent],
    *,
    group_ids: set[int],
    group_ids_by_name: dict[str, int],
) -> tuple[dict[int, list[Agent]], dict[str, list[Agent]]]:
    by_id: dict[int, list[Agent]] = defaultdict(list)
    by_unknown_label: dict[str, list[Agent]] = defaultdict(list)

    for agent in agents:
        group_value = _field_value(agent, "group")
        group_id = _resource_id(group_value)
        if group_id in group_ids:
            by_id[group_id].append(agent)
            continue

        group_label = str(group_value or "")
        if (named_group_id := group_ids_by_name.get(group_label)) is not None:
            by_id[named_group_id].append(agent)
            continue

        by_unknown_label[group_label].append(agent)

    return by_id, by_unknown_label


def _field_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)

    value = getattr(item, key, default)
    if value is not None:
        return value

    normalized = normalize_render_data(item)
    if isinstance(normalized, dict):
        return normalized.get(key, default)
    return default


def _resource_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return _coerce_int(value.get("id"))
    return _coerce_int(getattr(value, "id", value))


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _group_label(group: Group) -> str:
    return str(_field_value(group, "name") or _field_value(group, "id") or "Unnamed")


def _agent_type(agent: Agent) -> str:
    return str(_field_value(agent, "type", "") or "device")


def _is_device_agent(agent: Agent) -> bool:
    return _agent_type(agent) in {"device", "dict"}


def _group_sort_key(group: Group) -> tuple[str, int]:
    return (_group_label(group).casefold(), _resource_id(group) or 0)


def _agent_sort_key(agent: Agent) -> tuple[str, str, int]:
    return (
        str(_field_value(agent, "display_name", "") or "").casefold(),
        str(_field_value(agent, "name", "") or "").casefold(),
        _resource_id(agent) or 0,
    )
