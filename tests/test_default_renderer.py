from types import SimpleNamespace

from rich.console import Console
from rich.text import Text

from doover_cli.colours import (
    DEVICE_COLOUR,
    ENTITY_COLOURS,
    GROUP_COLOUR,
    ORGANISATION_COLOUR,
)
from doover_cli.renderer._base import TreeNode
from doover_cli.renderer._default import DefaultRenderer
from doover_cli.utils.crud import Field, LookupChoice
from pydoover.models.control import (
    Agent,
    Agents,
    Device,
    DeviceType,
    Group,
    Organisation,
    Solution,
)
from pydoover.models.control._base import ControlField, ControlModel, ControlPage


class ExampleModel(ControlModel):
    _model_name = "ExampleModel"
    _field_defs = {
        "gamma": ControlField(type="string", nullable=True),
        "alpha": ControlField(type="string", nullable=True),
        "omega": ControlField(type="string", nullable=True),
        "beta": ControlField(type="string", nullable=True),
    }


def test_render_list_preserves_control_model_field_order():
    console = Console(record=True, width=120)
    renderer = DefaultRenderer(console=console)
    page = ControlPage(
        count=1,
        results=[
            ExampleModel(
                alpha="A",
                beta="B",
                gamma="G",
                omega="O",
            )
        ],
    )

    renderer.render_list(page)

    output = console.export_text()
    header_line = next(
        line for line in output.splitlines() if "gamma" in line and "alpha" in line
    )
    assert (
        header_line.index("gamma")
        < header_line.index("alpha")
        < header_line.index("omega")
        < header_line.index("beta")
    )
    assert "Count: 1" in output


def test_render_list_omits_columns_that_do_not_fit_terminal_width():
    console = Console(record=True, width=30)
    renderer = DefaultRenderer(console=console)
    page = ControlPage(
        count=1,
        results=[
            ExampleModel(
                alpha="A",
                beta="B",
                gamma="G",
                omega="O",
            )
        ],
    )

    renderer.render_list(page)

    output = console.export_text()
    header_line = next(
        line for line in output.splitlines() if "gamma" in line and "alpha" in line
    )
    assert "omega" in header_line
    assert "beta" not in header_line
    assert "Showing 3 of 4 columns." in output
    assert "Omitted: beta" in output


def test_render_single_record_shows_every_field_vertically():
    console = Console(record=True, width=40)
    renderer = DefaultRenderer(console=console)

    renderer.render(
        ExampleModel(
            alpha="A",
            beta="B",
            gamma="G",
            omega="O",
        )
    )

    output = console.export_text()
    # All four fields must appear — no "Showing N of M columns" truncation
    # like the horizontal list view produces at this width.
    for field_name in ("gamma", "alpha", "omega", "beta"):
        assert field_name in output, f"{field_name} missing from detail output"
    assert "Showing" not in output
    assert "Omitted" not in output

    # Each field should be on its own line (vertical layout).
    lines = [line for line in output.splitlines() if line.strip()]
    gamma_line = next(line for line in lines if "gamma" in line)
    alpha_line = next(line for line in lines if "alpha" in line)
    assert "alpha" not in gamma_line
    assert "gamma" not in alpha_line

    # Field order from _field_defs is preserved top to bottom.
    order = [lines.index(next(line for line in lines if name in line))
             for name in ("gamma", "alpha", "omega", "beta")]
    assert order == sorted(order)


def test_render_single_record_pretty_prints_nested_dicts():
    class WithNested(ControlModel):
        _model_name = "WithNested"
        _field_defs = {
            "id": ControlField(type="string", nullable=True),
            "config": ControlField(type="json", nullable=True),
        }

    console = Console(record=True, width=120)
    renderer = DefaultRenderer(console=console)

    renderer.render(
        WithNested(
            id="42",
            config={"version": "1.2.3", "tier": "prod"},
        )
    )

    output = console.export_text()
    # Pretty-printed JSON uses multiple lines with indentation.
    assert '"version": "1.2.3"' in output
    assert '"tier": "prod"' in output
    # Outer field name has no JSON syntax wrapping it.
    assert "config" in output


def test_render_formats_resource_values_prettily():
    console = Console(record=True, width=120)
    renderer = DefaultRenderer(console=console)
    organisation = Organisation(id=1, name="Acme Farms")
    solution = Solution(id=2, display_name="Soil Monitor", organisation=organisation)
    device_type = DeviceType(
        id=3,
        name="Tracker",
        organisation=organisation,
        solution=solution,
    )

    renderer.render(device_type)

    output = console.export_text()
    assert "Acme Farms" in output
    assert "Soil Monitor" in output
    assert "Organisation:" not in output
    assert "Solution:" not in output


def test_render_resource_value_colours_by_entity_type():
    renderer = DefaultRenderer(console=Console(record=True, width=120))

    organisation = renderer._render_value(Organisation(id=1, name="Acme Farms"))
    group = renderer._render_value(Group(id=2, name="Field Ops"))
    device = renderer._render_value(Device(id=3, name="Pump", archived=False))
    archived_device = renderer._render_value(Device(id=4, name="Old Pump", archived=True))

    assert isinstance(organisation, Text)
    assert str(organisation.style) == ORGANISATION_COLOUR
    assert str(group.style) == GROUP_COLOUR
    assert str(device.style) == DEVICE_COLOUR
    assert str(archived_device.style) == "dim " + DEVICE_COLOUR


def test_render_detail_colours_raw_values_by_field_key():
    class MixedRecord(ControlModel):
        _model_name = "MixedRecord"
        _field_defs = {
            "id": ControlField(type="string", nullable=True),
            "organisation": ControlField(type="string", nullable=True),
            "group": ControlField(type="string", nullable=True),
            "device": ControlField(type="string", nullable=True),
            "application": ControlField(type="string", nullable=True),
            "notes": ControlField(type="string", nullable=True),
        }

    renderer = DefaultRenderer(console=Console(record=True, width=120))
    record = MixedRecord(
        id="42",
        organisation="Acme",
        group="Field Ops",
        device="Pump-01",
        application="Platform Interface",
        notes="just some notes",
    )

    # id (not an entity) — no colouring
    assert renderer._render_detail_value("42", key="id") == "42"
    # notes (not in ENTITY_COLOURS) — no colouring
    assert renderer._render_detail_value("just some notes", key="notes") == (
        "just some notes"
    )

    # Entity-keyed fields — styled per ENTITY_COLOURS
    org_value = renderer._render_detail_value("Acme", key="organisation")
    group_value = renderer._render_detail_value("Field Ops", key="group")
    device_value = renderer._render_detail_value("Pump-01", key="device")
    application_value = renderer._render_detail_value(
        "Platform Interface", key="application"
    )

    assert isinstance(org_value, Text)
    assert str(org_value.style) == ORGANISATION_COLOUR
    assert str(group_value.style) == GROUP_COLOUR
    assert str(device_value.style) == DEVICE_COLOUR
    assert str(application_value.style) == ENTITY_COLOURS["application"]

    # End-to-end: render the record and verify styles are applied in output.
    console = Console(record=True, width=120, force_terminal=True)
    DefaultRenderer(console=console).render(record)
    ansi = console.export_text(styles=True)
    # Rich uses SGR 33 for yellow, 31 for red, 32 for green, 34 for blue
    assert "\x1b[33m" in ansi  # organisation
    assert "\x1b[31m" in ansi  # group
    assert "\x1b[32m" in ansi  # device
    assert "\x1b[34m" in ansi  # application


def test_tree_renders_rich_tree():
    console = Console(record=True, width=120)
    renderer = DefaultRenderer(console=console)

    renderer.tree(
        TreeNode(
            Agents(),
            children=[
                TreeNode(
                    Group(name="Operations"),
                    children=[
                        TreeNode(
                            Agent(
                                id=42,
                                name="pump-controller",
                                display_name="Pump Controller",
                                type="device",
                            ),
                        )
                    ],
                )
            ],
        )
    )

    output = console.export_text()
    assert "Agents" in output
    assert "Operations" in output
    assert "Pump Controller (pump-controller | 42) device" in output


def test_tree_label_style_renders_as_text():
    rendered = DefaultRenderer._render_tree_label(
        TreeNode(Device(id=42, name="Pump", archived=False))
    )

    assert isinstance(rendered, Text)
    assert rendered.plain == "Pump"
    assert str(rendered.style) == DEVICE_COLOUR


def test_tree_label_dims_archived_device():
    rendered = DefaultRenderer._render_tree_label(
        TreeNode(Device(id=42, name="Pump", archived=True))
    )

    assert isinstance(rendered, Text)
    assert str(rendered.style) == "dim " + DEVICE_COLOUR


def test_tree_label_plain_for_agents_root_and_non_device_agents():
    root = DefaultRenderer._render_tree_label(TreeNode(Agents()))
    assert root == "Agents"

    service_agent = DefaultRenderer._render_tree_label(
        TreeNode(Agent(id=1, name="svc", display_name="Service", type="service"))
    )
    # Non-device agents aren't styled — plain string comes back.
    assert service_agent == "Service (1)"


class FakeQuestion:
    def __init__(self, answer):
        self.answer = answer

    def unsafe_ask(self):
        return self.answer


def test_prompt_fields_uses_text_prompt_for_json(monkeypatch):
    renderer = DefaultRenderer(console=Console(record=True, width=120))
    captured = {}

    def fake_text(message, default=None, validate=None):
        captured["message"] = message
        captured["default"] = default
        assert validate is not None
        assert validate('{"mode":"auto"}') is True
        return FakeQuestion('{"mode":"auto"}')

    monkeypatch.setattr("doover_cli.renderer._default.questionary.text", fake_text)

    values = renderer.prompt_fields(
        [Field(key="config", label="Config", kind="json", required=False, default=None)]
    )

    assert captured == {"message": "Config", "default": ""}
    assert values == {"config": {"mode": "auto"}}


def test_prompt_fields_uses_autocomplete_for_resource(monkeypatch):
    renderer = DefaultRenderer(console=Console(record=True, width=120))
    captured = {}

    def fake_autocomplete(
        message, choices, default=None, match_middle=None, validate=None
    ):
        captured["message"] = message
        captured["choices"] = choices
        captured["default"] = default
        captured["match_middle"] = match_middle
        assert validate is not None
        assert validate("Field Ops (11)") is True
        return FakeQuestion("Field Ops (11)")

    monkeypatch.setattr(
        "doover_cli.renderer._default.questionary.autocomplete",
        fake_autocomplete,
    )

    values = renderer.prompt_fields(
        [
            Field(
                key="solution",
                label="Solution",
                kind="resource",
                required=True,
                default=SimpleNamespace(id=9),
                resource_model_label="solution",
                resource_lookup_choices=[
                    LookupChoice(
                        id=9,
                        label="Existing Solution (9)",
                        search_values=(
                            "Existing Solution (9)",
                            "9",
                            "Existing Solution",
                        ),
                    ),
                    LookupChoice(
                        id=11,
                        label="Field Ops (11)",
                        search_values=("Field Ops (11)", "11", "Field Ops"),
                    ),
                ],
                match_middle=True,
            )
        ]
    )

    assert captured == {
        "message": "Solution",
        "choices": ["Existing Solution (9)", "Field Ops (11)"],
        "default": "Existing Solution (9)",
        "match_middle": True,
    }
    assert values == {"solution": "Field Ops (11)"}
