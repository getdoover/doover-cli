from contextlib import nullcontext

from typer.testing import CliRunner

from doover_cli import app
from doover_cli.colours import (
    ARCHIVED_DEVICE_COLOUR,
    DEVICE_COLOUR,
    GROUP_COLOUR,
    ORGANISATION_COLOUR,
)
from doover_cli.agent import build_agents_tree
from doover_cli.renderer._base import TreeNode
from doover_cli.renderer._basic import BasicRenderer
from pydoover.models.control import Agent, Agents, Group, Organisation

runner = CliRunner()


class FakeRenderer:
    def __init__(self):
        self.render_list_calls = []
        self.tree_calls = []

    def loading(self, _message):
        return nullcontext()

    def prompt_fields(self, fields):
        return {field.key: field.default for field in fields}

    def render(self, data):
        raise AssertionError("render() should not be called")

    def render_list(self, data):
        self.render_list_calls.append(data)

    def tree(self, data):
        self.tree_calls.append(data)


def _agents_response() -> Agents:
    organisation = Organisation(id=1, name="Acme Farms")
    root_group = Group(
        id=10,
        name="Operations",
        organisation=organisation,
        archived=False,
        parent=None,
        children=[],
        shared=False,
    )
    child_group = Group(
        id=11,
        name="Irrigation",
        organisation=organisation,
        archived=False,
        parent={"id": 10, "name": "Operations"},
        children=[],
        shared=False,
    )
    return Agents(
        groups=[root_group, child_group],
        agents=[
            Agent(
                organisation="Acme Farms",
                id=101,
                name="pump-controller",
                display_name="Pump Controller",
                group="Irrigation",
                archived=False,
                connection_determination="online",
                type="device",
            ),
            Agent(
                organisation="Acme Farms",
                id=202,
                name="solar-monitor",
                display_name="Solar Monitor",
                group="Field Team",
                archived=True,
                connection_determination="offline",
                type="device",
            ),
        ],
        organisation_users=[],
        superusers=[],
        sharing="organisation",
    )


def test_agent_list_renders_agents_table(monkeypatch):
    renderer = FakeRenderer()
    captured = {}

    class FakeAgentsClient:
        def retrieve(self, include_archived=False):
            captured["include_archived"] = include_archived
            return _agents_response()

    class FakeControlClient:
        agents = FakeAgentsClient()

    monkeypatch.setattr(
        "doover_cli.agent.get_state", lambda: (FakeControlClient(), renderer)
    )

    result = runner.invoke(app, ["agent", "list"])

    assert result.exit_code == 0
    assert captured == {"include_archived": False}
    assert len(renderer.render_list_calls) == 1
    assert len(renderer.render_list_calls[0]) == 2
    assert renderer.tree_calls == []


def test_agent_list_tree_uses_renderer_tree(monkeypatch):
    renderer = FakeRenderer()

    class FakeAgentsClient:
        def retrieve(self, include_archived=False):
            assert include_archived is False
            return _agents_response()

    class FakeControlClient:
        agents = FakeAgentsClient()

    monkeypatch.setattr(
        "doover_cli.agent.get_state", lambda: (FakeControlClient(), renderer)
    )

    result = runner.invoke(app, ["agent", "list", "--tree"])

    assert result.exit_code == 0
    assert renderer.render_list_calls == []
    assert len(renderer.tree_calls) == 1
    assert renderer.tree_calls[0].label == "Agents"


def test_agent_list_include_archived_passes_pydoover_option(monkeypatch):
    renderer = FakeRenderer()
    captured = {}

    class FakeAgentsClient:
        def retrieve(self, include_archived=False):
            captured["include_archived"] = include_archived
            return _agents_response()

    class FakeControlClient:
        agents = FakeAgentsClient()

    monkeypatch.setattr(
        "doover_cli.agent.get_state", lambda: (FakeControlClient(), renderer)
    )

    result = runner.invoke(app, ["agent", "list", "--include-archived"])

    assert result.exit_code == 0
    assert captured == {"include_archived": True}


def test_build_agents_tree_groups_agents_and_preserves_fields():
    tree = build_agents_tree(_agents_response())

    assert tree.label == "Agents"
    assert [child.label for child in tree.children] == ["Operations", "Field Team"]

    operations = tree.children[0]
    assert operations.style == GROUP_COLOUR
    assert [child.label for child in operations.children] == ["Irrigation"]

    irrigation = operations.children[0]
    assert irrigation.style == GROUP_COLOUR
    pump = irrigation.children[0]
    assert pump.label == "Pump Controller (pump-controller | 101) device"
    assert pump.children == []
    assert pump.style == DEVICE_COLOUR

    field_team = tree.children[1]
    assert field_team.style == GROUP_COLOUR
    solar = field_team.children[0]
    assert solar.label == "Solar Monitor (solar-monitor | 202) device (Archived)"
    assert solar.children == []
    assert solar.style == ARCHIVED_DEVICE_COLOUR


def test_build_agents_tree_colours_organisation_fields_for_non_device_agents():
    response = _agents_response()
    response.agents[0].type = "service"

    tree = build_agents_tree(response)
    pump = tree.children[0].children[0].children[0]

    assert (
        TreeNode("organisation: Acme Farms", style=ORGANISATION_COLOUR)
        in pump.children
    )


def test_build_agents_tree_attaches_agents_by_numeric_group_id():
    response = _agents_response()
    response.agents[0].group = "11"

    tree = build_agents_tree(response)

    assert [child.label for child in tree.children] == ["Operations", "Field Team"]
    assert tree.children[0].children[0].children[0].label == (
        "Pump Controller (pump-controller | 101) device"
    )


def test_build_agents_tree_handles_raw_dict_groups_and_dict_type_devices():
    tree = build_agents_tree(
        Agents(
            groups=[
                {
                    "id": 1,
                    "name": "Root",
                    "organisation": {"id": 100, "name": "Org"},
                    "archived": False,
                    "parent": None,
                    "children": [],
                    "shared": False,
                },
                {
                    "id": 2,
                    "name": "Child",
                    "organisation": {"id": 100, "name": "Org"},
                    "archived": False,
                    "parent": {"id": 1, "name": "Root"},
                    "children": [],
                    "shared": False,
                },
            ],
            agents=[
                Agent(
                    organisation="Org",
                    id=101,
                    name="test-doovit",
                    display_name="test-doovit",
                    group="2",
                    archived=False,
                    connection_determination="Online",
                    type="dict",
                )
            ],
            organisation_users=[],
            superusers=[],
            sharing="organisation",
        )
    )

    child = tree.children[0].children[0]
    assert child.label == "Child"
    assert child.children[0].label == "test-doovit (test-doovit | 101) device"
    assert child.children[0].children == []
    assert child.children[0].style == DEVICE_COLOUR


def test_build_agents_tree_indexes_nested_group_children():
    response = _agents_response()
    root_group, child_group = response.groups
    response.groups = [root_group]
    root_group.children = [child_group]
    child_group.parent = None
    response.agents[0].group = "11"

    tree = build_agents_tree(response)

    assert [child.label for child in tree.children] == ["Operations", "Field Team"]
    assert tree.children[0].children[0].label == "Irrigation"
    assert tree.children[0].children[0].children[0].label == (
        "Pump Controller (pump-controller | 101) device"
    )


def test_basic_renderer_tree_uses_plain_indented_lines(capsys):
    renderer = BasicRenderer()

    renderer.tree(
        TreeNode(
            "Agents",
            children=[
                TreeNode(
                    "Operations",
                    children=[
                        TreeNode(
                            "Pump Controller (42)",
                            children=[TreeNode("type: device")],
                        )
                    ],
                )
            ],
        )
    )

    assert capsys.readouterr().out == (
        "Agents\n"
        "- Operations\n"
        "  - Pump Controller (42)\n"
        "    - type: device\n"
    )
