import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, ContextManager

import typer
from pydoover.models.control import ControlModel, ControlPage

from ._base import RendererBase, EmptyEnterable, normalize_render_data
from ..utils import parsers
from ..utils.crud import _parse_optional_bool

if TYPE_CHECKING:
    from ..utils.crud import Field



class BasicRenderer(RendererBase):
    
    def loading(self, message: str) -> ContextManager[Any]:
        print(message)
        return EmptyEnterable()

    def prompt_fields(self, fields: list["Field"]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field in fields:
            if field.kind == "resource" and field.resource_lookup_choices:
                print(f"{field.label} choices:")
                for choice in field.resource_lookup_choices:
                    print(f"- {choice['label']}")

            values[field.key] = self._prompt_field(field)
        return values
    
    def render_list(self, data: list[Any] | ControlPage[Any]) -> None:
        print(json.dumps(normalize_render_data(data), indent=4))
    
    def render(self, data: dict[str, Any] | ControlModel) -> None:
        print(json.dumps(normalize_render_data(data), indent=4))

    def _prompt_field(self, field: "Field") -> Any:
        default = self._stringify_default(field.default)

        if field.kind == "bool":
            if field.required:
                return typer.confirm(
                    field.label,
                    default=bool(field.default) if field.default is not None else False,
                )
            answer = typer.prompt(field.label, default=default, show_default=bool(default))
            stripped = answer.strip()
            if not stripped:
                return None
            return _parse_optional_bool(stripped, field.label)

        answer = typer.prompt(field.label, default=default, show_default=bool(default))
        return self._coerce_field_value(field, answer)

    @staticmethod
    def _stringify_default(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        value_id = getattr(value, "id", None)
        if value_id is not None:
            return str(value_id)
        return str(value)

    def _coerce_field_value(self, field: "Field", answer: str) -> Any:
        stripped = answer.strip()
        if not stripped:
            if field.required:
                raise typer.BadParameter(f"{field.label} is required.")
            return None

        if field.kind == "int":
            if not stripped.lstrip("-").isdigit():
                raise typer.BadParameter(f"Please enter a valid {field.label.lower()}.")
            return int(stripped)
        if field.kind == "json":
            return parsers.maybe_json(stripped)
        if field.kind == "path":
            return Path(stripped)
        if field.kind == "resource":
            if stripped.lstrip("-").isdigit():
                return int(stripped)
            return stripped
        return stripped
