from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import questionary
import typer
from pydoover.models.control import ControlModel, ControlPage
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from ._base import RendererBase, TreeNode, normalize_render_data
from ..utils import parsers
from ..utils.crud import parse_optional_bool
from ..utils.crud.lookup import resolve_resource_lookup


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
        self._render_rows([data])

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
            return self._resource_label(value) or str(getattr(value, "id", "") or "")
        if isinstance(value, list):
            return ", ".join(self._plain_text_value(item) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))
        return str(value)

    def _render_resource(self, value: ControlModel) -> Text:
        label = self._resource_label(value)
        if not label:
            label = str(
                getattr(value, "id", "")
                or (getattr(value, "_model_name", None) or type(value).__name__)
            )
        return Text(label, style="bold blue")

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
        if node.style:
            return Text(node.label, style=node.style)
        return node.label
