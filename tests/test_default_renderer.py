from types import SimpleNamespace

from rich.console import Console
from rich.text import Text

from doover_cli.renderer._base import TreeNode
from doover_cli.renderer._default import DefaultRenderer
from doover_cli.utils.crud import Field, LookupChoice
from pydoover.models.control import DeviceType, Organisation, Solution
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


def test_render_resource_value_uses_bold_blue_text():
    renderer = DefaultRenderer(console=Console(record=True, width=120))
    organisation = Organisation(id=1, name="Acme Farms")

    rendered = renderer._render_value(organisation)

    assert isinstance(rendered, Text)
    assert rendered.plain == "Acme Farms"
    assert str(rendered.style) == "bold blue"


def test_tree_renders_rich_tree():
    console = Console(record=True, width=120)
    renderer = DefaultRenderer(console=console)

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

    output = console.export_text()
    assert "Agents" in output
    assert "Operations" in output
    assert "Pump Controller (42)" in output
    assert "type: device" in output


def test_tree_label_style_renders_as_text():
    rendered = DefaultRenderer._render_tree_label(TreeNode("Pump", style="green"))

    assert isinstance(rendered, Text)
    assert rendered.plain == "Pump"
    assert str(rendered.style) == "green"


class FakeQuestion:
    def __init__(self, answer):
        self.answer = answer

    def unsafe_ask(self):
        return self.answer


def test_prompt_fields_opens_editor_for_existing_json(monkeypatch):
    renderer = DefaultRenderer(console=Console(record=True, width=120))
    captured = {}

    def fake_edit(text, extension=None, require_save=None):
        captured["text"] = text
        captured["extension"] = extension
        captured["require_save"] = require_save
        return '{\n  "mode": "auto"\n}\n'

    monkeypatch.setattr("doover_cli.renderer._default.typer.edit", fake_edit)

    values = renderer.prompt_fields(
        [
            Field(
                key="config",
                label="Config",
                kind="json",
                required=False,
                default={"mode": "manual"},
            )
        ]
    )

    assert captured == {
        "text": '{\n  "mode": "manual"\n}\n',
        "extension": ".json",
        "require_save": False,
    }
    assert values == {"config": {"mode": "auto"}}


def test_prompt_fields_skips_optional_json_when_not_configuring(monkeypatch):
    renderer = DefaultRenderer(console=Console(record=True, width=120))

    def fake_confirm(message, default=None):
        assert message == "Config: configure JSON value?"
        assert default is False
        return FakeQuestion(False)

    monkeypatch.setattr("doover_cli.renderer._default.questionary.confirm", fake_confirm)

    values = renderer.prompt_fields(
        [
            Field(
                key="config",
                label="Config",
                kind="json",
                required=False,
                default=None,
                json_template={},
            )
        ]
    )

    assert values == {"config": None}


def test_prompt_fields_seeds_optional_json_editor_from_template(monkeypatch):
    renderer = DefaultRenderer(console=Console(record=True, width=120))
    captured = {}

    def fake_confirm(message, default=None):
        return FakeQuestion(True)

    def fake_edit(text, extension=None, require_save=None):
        captured["text"] = text
        return '{\n  "mode": "auto"\n}\n'

    monkeypatch.setattr("doover_cli.renderer._default.questionary.confirm", fake_confirm)
    monkeypatch.setattr("doover_cli.renderer._default.typer.edit", fake_edit)

    values = renderer.prompt_fields(
        [
            Field(
                key="config",
                label="Config",
                kind="json",
                required=False,
                default=None,
                json_template={},
            )
        ]
    )

    assert captured["text"] == "{}\n"
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
