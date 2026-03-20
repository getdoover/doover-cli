from rich.console import Console
from rich.text import Text

from doover_cli.renderer._default import DefaultRenderer
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
    header_line = next(line for line in output.splitlines() if "gamma" in line and "alpha" in line)
    assert header_line.index("gamma") < header_line.index("alpha") < header_line.index("omega") < header_line.index("beta")
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
    header_line = next(line for line in output.splitlines() if "gamma" in line and "alpha" in line)
    assert "omega" in header_line
    assert "beta" not in header_line
    assert "Showing 3 of 4 columns." in output
    assert "Omitted: beta" in output


def test_render_formats_resource_values_prettily():
    console = Console(record=True, width=120)
    renderer = DefaultRenderer(console=console)
    organisation = Organisation(id="1", name="Acme Farms")
    solution = Solution(id="2", display_name="Soil Monitor", organisation=organisation)
    device_type = DeviceType(
        id="3",
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
    organisation = Organisation(id="1", name="Acme Farms")

    rendered = renderer._render_value(organisation)

    assert isinstance(rendered, Text)
    assert rendered.plain == "Acme Farms"
    assert str(rendered.style) == "bold blue"
