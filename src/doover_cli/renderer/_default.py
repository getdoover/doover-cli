from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import questionary
import typer
from pydoover.models.control import Agent, Agents, ControlModel, ControlPage
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from ._base import RendererBase, TreeNode, format_tree_label, normalize_render_data
from ..colours import ENTITY_COLOURS
from ..utils import parsers
from ..utils.crud import parse_optional_bool
from ..utils.crud.lookup import resolve_resource_lookup


_RESOURCE_DEFAULT_STYLE = "bold blue"


def _style_for_resource(value: ControlModel) -> str:
    """Pick a colour for a ControlModel value based on its entity type."""
    model_name = getattr(value, "_model_name", None) or type(value).__name__
    style = ENTITY_COLOURS.get(model_name.lower(), _RESOURCE_DEFAULT_STYLE)
    if getattr(value, "archived", False):
        return "dim " + style
    return style

def _style_for_key(key: str | None) -> str | None:
    """Pick a colour for a raw (non-ControlModel) value based on its field key."""
    if key is None:
        return None
    return ENTITY_COLOURS.get(key)


def _style_for_tree_node(element: ControlModel) -> str | None:
    """Pick a colour for a TreeNode based on its element's entity type.

    Unlike ``_style_for_resource``, tree nodes don't fall back to a default
    style — the root ``Agents`` container and non-device ``Agent``s render
    plain. Archived elements get a ``"dim "`` prefix.
    """
    if isinstance(element, Agents):
        return None
    if isinstance(element, Agent):
        agent_type = getattr(element, "type", None) or "device"
        if agent_type not in {"device", "dict"}:
            return None
        style = ENTITY_COLOURS["device"]
    else:
        model_name = getattr(element, "_model_name", None) or type(element).__name__
        style = ENTITY_COLOURS.get(model_name.lower())
        if style is None:
            return None
    if getattr(element, "archived", False):
        return "dim " + style
    return style


class DefaultRenderer(RendererBase):
    _MAX_COLUMN_WIDTH = 30

    def __init__(self, console: Console | None = None):
        super().__init__()
        self.console = console or Console()

    def loading(self, message: str):
        return self.console.status(message)

    def prompt_fields(self, fields):
        values: dict[str, Any] = {}
        for field in fields:
            values[field.key] = self._prompt_field(field)
        return values

    def render_list(self, data: list[Any] | ControlPage[Any]) -> None:
        if isinstance(data, ControlPage):
            rows = list(data.results)
            caption = self._format_page_caption(data)
        else:
            rows = list(data)
            caption = None
        self._render_rows(rows, caption=caption)

    def render(self, data: dict[str, Any] | ControlModel) -> None:
        self._render_detail(data)

    def tree(self, data: TreeNode) -> None:
        tree = Tree(self._render_tree_label(data))
        self._add_tree_children(tree, data)
        self.console.print(tree)

    def _render_rows(self, items: list[Any], *, caption: str | None = None) -> None:
        if not items:
            self.console.print("[dim]No results[/dim]")
            if caption:
                self.console.print(f"[dim]{caption}[/dim]")
            return

        rows = [self._normalize_row(item) for item in items]
        columns = self._collect_columns(items, rows)

        if not columns:
            self.console.print_json(json.dumps(normalize_render_data(items), indent=4))
            return

        visible_columns = self._select_visible_columns(columns, rows)
        omitted_columns = columns[len(visible_columns) :]

        table = self._build_table(
            columns=visible_columns,
            rows=rows,
            caption=self._build_caption(caption, omitted_columns, len(columns)),
        )
        self.console.print(table)

    def _render_detail(self, data: dict[str, Any] | ControlModel) -> None:
        """Render a single record as a vertical field/value list.

        Unlike ``_render_rows`` (which lays out records as horizontal table
        rows and may omit columns that do not fit the terminal width), this
        shows every field on its own line so nothing is hidden.
        """
        row = self._normalize_row(data)
        if not row:
            self.console.print_json(json.dumps(normalize_render_data(data), indent=4))
            return

        ordered_keys = self._ordered_detail_keys(data, row)

        table = Table(
            show_header=False,
            box=None,
            pad_edge=False,
            padding=(0, 2),
        )
        table.add_column(no_wrap=True)
        table.add_column(overflow="fold")

        for key in ordered_keys:
            table.add_row(key, self._render_detail_value(row.get(key), key=key))

        self.console.print(table)

    @staticmethod
    def _ordered_detail_keys(
        data: dict[str, Any] | ControlModel,
        row: dict[str, Any],
    ) -> list[str]:
        if isinstance(data, ControlModel):
            ordered = [name for name in data._field_defs if name in row]
            for key in row:
                if key not in ordered:
                    ordered.append(key)
            return ordered
        return list(row.keys())

    def _render_detail_value(self, value: Any, *, key: str | None = None) -> str | Text:
        """Like ``_render_value`` but pretty-prints nested data.

        In the single-record detail view we have unlimited vertical space,
        so structured values (dicts, lists of dicts) are rendered as
        indented JSON instead of being compacted onto one line.

        Values are coloured by entity type (per ``colours.py``) when the
        value is a recognised ControlModel or when ``key`` names a known
        entity (``organisation``, ``group``, ``device``).
        """
        if value is None:
            return ""
        if isinstance(value, ControlModel):
            return self._render_resource(value)
        style = _style_for_key(key)
        if isinstance(value, list):
            if not value:
                return ""
            if any(isinstance(item, (dict, list)) for item in value):
                rendered = json.dumps(
                    normalize_render_data(value),
                    indent=2,
                    ensure_ascii=True,
                    default=str,
                )
                return Text(rendered, style=style) if style else rendered
            rendered_list = self._render_list(value)
            if style and isinstance(rendered_list, str):
                return Text(rendered_list, style=style)
            return rendered_list
        if isinstance(value, dict):
            rendered = json.dumps(value, indent=2, ensure_ascii=True, default=str)
            return Text(rendered, style=style) if style else rendered
        text = str(value)
        return Text(text, style=style) if style else text

    def _normalize_row(self, item: Any) -> dict[str, Any]:
        if isinstance(item, ControlModel):
            return {
                name: value
                for name in item._field_defs
                if (value := getattr(item, name, None)) is not None
            }
        row = normalize_render_data(item)
        if isinstance(row, dict):
            return row
        return {"value": row}

    def _collect_columns(
        self,
        items: list[Any],
        rows: list[dict[str, Any]],
    ) -> list[str]:
        columns: list[str] = []
        seen: set[str] = set()

        for item, row in zip(items, rows):
            if isinstance(item, ControlModel):
                ordered_keys = [name for name in item._field_defs if name in row]
            else:
                ordered_keys = list(row.keys())

            for key in ordered_keys:
                if key not in seen:
                    columns.append(key)
                    seen.add(key)

            for key in row.keys():
                if key not in seen:
                    columns.append(key)
                    seen.add(key)

        return columns

    def _select_visible_columns(
        self,
        columns: list[str],
        rows: list[dict[str, Any]],
    ) -> list[str]:
        visible: list[str] = []
        for column in columns:
            candidate = [*visible, column]
            if (
                not visible
                or self._estimate_table_width(candidate, rows) <= self.console.width
            ):
                visible = candidate
                continue
            break
        return visible or columns[:1]

    def _build_table(
        self,
        *,
        columns: list[str],
        rows: list[dict[str, Any]],
        caption: str | None = None,
    ) -> Table:
        table = Table(caption=caption)
        for column in columns:
            table.add_column(
                column,
                min_width=min(len(column), self._MAX_COLUMN_WIDTH),
                no_wrap=True,
                overflow="ellipsis",
                max_width=self._MAX_COLUMN_WIDTH,
            )

        for row in rows:
            table.add_row(*(self._render_value(row.get(column)) for column in columns))

        return table

    def _build_caption(
        self,
        caption: str | None,
        omitted_columns: list[str],
        total_columns: int,
    ) -> str | None:
        parts = [caption] if caption else []
        if omitted_columns:
            parts.append(
                "Showing "
                f"{total_columns - len(omitted_columns)} of {total_columns} columns. "
                f"Omitted: {', '.join(omitted_columns)}"
            )
        return "\n".join(parts) if parts else None

    def _format_page_caption(self, page: ControlPage[Any]) -> str:
        parts = [f"Count: {page.count}"]
        if page.previous:
            parts.append(f"Previous: {page.previous}")
        if page.next:
            parts.append(f"Next: {page.next}")
        return " | ".join(parts)

    def _estimate_table_width(
        self,
        columns: list[str],
        rows: list[dict[str, Any]],
    ) -> int:
        content_width = sum(
            self._estimate_column_width(column, rows) for column in columns
        )
        border_and_padding_width = (3 * len(columns)) + 1
        return content_width + border_and_padding_width

    def _estimate_column_width(self, column: str, rows: list[dict[str, Any]]) -> int:
        values = [self._plain_text_value(row.get(column)) for row in rows]
        widest_value = max((len(value) for value in values), default=0)
        return min(self._MAX_COLUMN_WIDTH, max(len(column), widest_value))

    def _render_value(self, value: Any) -> str | Text:
        if value is None:
            return ""
        if isinstance(value, ControlModel):
            return self._render_resource(value)
        if isinstance(value, list):
            return self._render_list(value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))
        return str(value)

    def _plain_text_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, ControlModel):
            return self._resource_display(value)
        if isinstance(value, list):
            return ", ".join(self._plain_text_value(item) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))
        return str(value)

    def _render_resource(self, value: ControlModel) -> Text:
        return Text(self._resource_display(value), style=_style_for_resource(value))

    def _resource_display(self, value: ControlModel) -> str:
        """Format a resource as ``<display_name or name> (<id>)``.

        Falls back to just the label or just the id when one is missing,
        and finally to the model name if neither is available.
        """
        label = self._resource_label(value)
        resource_id = getattr(value, "id", None)
        if label and resource_id is not None:
            return f"{label} ({resource_id})"
        if label:
            return label
        if resource_id is not None:
            return str(resource_id)
        return getattr(value, "_model_name", None) or type(value).__name__

    def _render_list(self, value: list[Any]) -> str | Text:
        if any(isinstance(item, ControlModel) for item in value):
            parts: list[str | Text] = []
            for index, item in enumerate(value):
                if index:
                    parts.append(", ")
                parts.append(self._render_value(item))
            return Text.assemble(*parts)
        return ", ".join(self._plain_text_value(item) for item in value)

    def _resource_label(self, value: ControlModel) -> str | None:
        for field_name in ("display_name", "name", "username", "email"):
            field_value = getattr(value, field_name, None)
            if field_value:
                return str(field_value)

        first_name = getattr(value, "first_name", None)
        last_name = getattr(value, "last_name", None)
        full_name = " ".join(part for part in (first_name, last_name) if part)
        if full_name:
            return full_name

        return None

    def _prompt_field(self, field) -> Any:
        default = self._stringify_default(field.default)

        if field.kind == "resource" and field.resource_lookup_choices:
            choice_labels = [choice.label for choice in field.resource_lookup_choices]
            default_choice = next(
                (
                    choice.label
                    for choice in field.resource_lookup_choices
                    if choice.id == getattr(field.default, "id", field.default)
                ),
                default,
            )
            answer = questionary.autocomplete(
                field.label,
                choices=choice_labels,
                default=default_choice,
                match_middle=field.match_middle,
                validate=lambda value: self._validate_resource_field(field, value),
            ).unsafe_ask()
            if answer is None:
                raise typer.Abort()
            return answer

        answer = questionary.text(
            field.label,
            default=default,
            validate=lambda value: self._validate_basic_field(field, value),
        ).unsafe_ask()
        if answer is None:
            raise typer.Abort()
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

    def _validate_basic_field(self, field, value: str) -> bool | str:
        stripped = value.strip()
        if not stripped:
            return True if not field.required else f"{field.label} is required."
        if field.kind == "int" and not stripped.lstrip("-").isdigit():
            return "Please enter an integer."
        if field.kind == "bool":
            try:
                parse_optional_bool(stripped, field.label)
            except typer.BadParameter as exc:
                return str(exc)
        if field.kind == "json":
            try:
                parsers.maybe_json(stripped)
            except Exception as exc:
                return str(exc)
        return True

    def _validate_resource_field(self, field, value: str) -> bool | str:
        try:
            resolve_resource_lookup(
                field.resource_lookup_choices or [],
                value,
                model_label=field.resource_model_label or "resource",
            )
        except typer.BadParameter as exc:
            return str(exc)
        return True

    def _coerce_field_value(self, field, answer: str) -> Any:
        stripped = answer.strip()
        if not stripped:
            return None
        if field.kind == "int":
            return int(stripped)
        if field.kind == "bool":
            return parse_optional_bool(stripped, field.label)
        if field.kind == "json":
            return parsers.maybe_json(stripped)
        if field.kind == "path":
            return Path(stripped)
        if field.kind == "resource" and stripped.lstrip("-").isdigit():
            return int(stripped)
        return stripped

    def _add_tree_children(self, branch: Tree, node: TreeNode) -> None:
        for child in node.children:
            child_branch = branch.add(self._render_tree_label(child))
            self._add_tree_children(child_branch, child)

    @staticmethod
    def _render_tree_label(node: TreeNode) -> str | Text:
        label = format_tree_label(node.element)
        style = _style_for_tree_node(node.element)
        if style:
            return Text(label, style=style)
        return label
