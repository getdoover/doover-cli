import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree as RichTree
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Static, Tree

from .formatters import format_channel_info


class ChannelViewMode(str, Enum):
    PLAIN = "plain"
    OVERVIEW = "overview"
    SIMPLE = "simple"
    INTERACTIVE = "interactive"


@dataclass(frozen=True)
class TreeNodeData:
    path: tuple[str, ...]
    value: Any


def resolve_channel_view(
    channel_name: str, requested_mode: ChannelViewMode | None
) -> ChannelViewMode:
    if requested_mode is not None:
        return requested_mode
    if channel_name == "ui_state":
        return ChannelViewMode.OVERVIEW
    return ChannelViewMode.PLAIN


def render_channel(channel, *, mode: ChannelViewMode, console: Console | None = None) -> None:
    console = console or Console()

    if mode == ChannelViewMode.PLAIN:
        console.print(format_channel_info(channel), soft_wrap=True)
        return

    if mode == ChannelViewMode.OVERVIEW:
        console.print(build_channel_overview(channel))
        return

    if mode == ChannelViewMode.SIMPLE:
        ChannelSimpleApp(channel).run()
        return

    ChannelExplorerApp(channel.to_dict(), channel_name=channel.name).run()


def build_channel_overview(channel) -> Group:
    aggregate = channel.aggregate
    attachments = aggregate.attachments if aggregate is not None else []
    aggregate_data = aggregate.data if aggregate is not None else None
    aggregate_title = "Aggregate Data"
    if channel.name == "ui_state":
        aggregate_title = "UI State"

    metadata = Panel(
        _build_metadata_table(channel),
        title=f"Channel: {channel.name}",
        border_style="cyan",
    )
    aggregate_panel = Panel(
        _build_value_tree("aggregate.data", aggregate_data),
        title=aggregate_title,
        subtitle=_build_aggregate_subtitle(aggregate, attachments),
        border_style="green",
    )

    renderables: list[Any] = [metadata, aggregate_panel]

    if channel.aggregate_schema is not None or channel.message_schema is not None:
        renderables.append(
            Panel(
                _build_schema_table(channel),
                title="Schemas",
                border_style="magenta",
            )
        )

    return Group(*renderables)


def _build_metadata_table(channel) -> Table:
    aggregate = channel.aggregate
    attachments = aggregate.attachments if aggregate is not None else []
    aggregate_data = aggregate.data if aggregate is not None else None

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    table.add_row("Type", channel.__class__.__name__)
    table.add_row("Channel Key", f"{channel.owner_id}:{channel.name}")
    table.add_row("Agent ID", str(channel.owner_id))
    table.add_row("Private", str(channel.is_private))
    table.add_row("Aggregate Keys", _count_entries(aggregate_data))
    table.add_row("Attachments", str(len(attachments)))
    table.add_row("Last Updated", _format_timestamp(aggregate.last_updated if aggregate else None))
    return table


def _build_schema_table(channel) -> Table:
    table = Table(box=None, show_header=True, header_style="bold")
    table.add_column("Schema")
    table.add_column("Status")
    table.add_column("Summary")

    aggregate_schema = channel.aggregate_schema
    message_schema = channel.message_schema

    table.add_row(
        "Aggregate",
        "present" if aggregate_schema is not None else "missing",
        _summarize_schema(aggregate_schema),
    )
    table.add_row(
        "Message",
        "present" if message_schema is not None else "missing",
        _summarize_schema(message_schema),
    )
    return table


def _build_aggregate_subtitle(aggregate, attachments: list[Any]) -> str:
    last_updated = _format_timestamp(aggregate.last_updated if aggregate else None)
    return f"Last updated: {last_updated} | attachments: {len(attachments)}"


def _build_value_tree(label: str, value: Any) -> RichTree:
    root = RichTree(Text(label, style="bold"))
    _add_value_to_rich_tree(root, value, name=None)
    return root


def _add_value_to_rich_tree(node: RichTree, value: Any, *, name: str | None) -> None:
    if isinstance(value, dict):
        items = list(value.items())
        if name is not None:
            child = node.add(Text.assemble((name, "bold cyan"), ("  "), (f"{{{len(items)} keys}}", "dim")))
        else:
            child = node
        if not items:
            child.add(Text("{}", style="dim"))
            return
        for key, item in items:
            _add_value_to_rich_tree(child, item, name=str(key))
        return

    if isinstance(value, list):
        if name is not None:
            child = node.add(Text.assemble((name, "bold yellow"), ("  "), (f"[{len(value)} items]", "dim")))
        else:
            child = node
        if not value:
            child.add(Text("[]", style="dim"))
            return
        for index, item in enumerate(value):
            _add_value_to_rich_tree(child, item, name=f"[{index}]")
        return

    leaf_label = _leaf_label(name or "value", value)
    node.add(leaf_label)


def _leaf_label(name: str, value: Any) -> Text:
    return Text.assemble(
        (name, "bold white"),
        (": ", "dim"),
        (_preview_value(value), _value_style(value)),
    )


def _preview_value(value: Any, *, limit: int = 96) -> str:
    if isinstance(value, str):
        rendered = json.dumps(value)
    elif value is None:
        rendered = "null"
    else:
        rendered = str(value).lower() if isinstance(value, bool) else str(value)

    if len(rendered) <= limit:
        return rendered
    return f"{rendered[: limit - 1]}…"


def _value_style(value: Any) -> str:
    if value is None:
        return "magenta"
    if isinstance(value, bool):
        return "green"
    if isinstance(value, (int, float)):
        return "cyan"
    if isinstance(value, str):
        return "yellow"
    return "white"


def _count_entries(value: Any) -> str:
    if isinstance(value, dict):
        return str(len(value))
    if isinstance(value, list):
        return str(len(value))
    if value is None:
        return "0"
    return "1"


def _summarize_schema(schema: Any) -> str:
    if schema is None:
        return "-"
    if isinstance(schema, dict):
        keys = sorted(schema.keys())
        if not keys:
            return "empty object"
        preview = ", ".join(keys[:4])
        if len(keys) > 4:
            preview += ", ..."
        return f"{len(keys)} top-level keys: {preview}"
    if isinstance(schema, list):
        return f"list with {len(schema)} entries"
    return type(schema).__name__


def _format_timestamp(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "Unknown"
    local_time = timestamp.astimezone(timezone.utc)
    return local_time.strftime("%Y-%m-%d %H:%M:%S %Z")


def _build_channel_summary_text(channel) -> str:
    aggregate = channel.aggregate
    attachments = aggregate.attachments if aggregate is not None else []
    aggregate_data = aggregate.data if aggregate is not None else None

    lines = [
        f"Name: {channel.name}",
        f"Type: {channel.__class__.__name__}",
        f"Channel Key: {channel.owner_id}:{channel.name}",
        f"Agent ID: {channel.owner_id}",
        f"Private: {channel.is_private}",
        f"Aggregate Keys: {_count_entries(aggregate_data)}",
        f"Attachments: {len(attachments)}",
        f"Last Updated: {_format_timestamp(aggregate.last_updated if aggregate else None)}",
        f"Aggregate Schema: {_summarize_schema(channel.aggregate_schema)}",
        f"Message Schema: {_summarize_schema(channel.message_schema)}",
    ]
    return "\n".join(lines)


class ChannelSimpleApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    Horizontal {
        height: 1fr;
    }

    #aggregate-tree {
        width: 2fr;
        border: round $accent;
    }

    #summary {
        width: 38;
        min-width: 30;
        overflow: auto;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("e", "expand_selected", "Expand"),
        Binding("c", "collapse_selected", "Collapse"),
        Binding("E", "expand_all", "Expand all"),
        Binding("C", "collapse_all", "Collapse all"),
    ]

    def __init__(self, channel) -> None:
        super().__init__()
        self.channel = channel
        self.aggregate_data = channel.aggregate.data if channel.aggregate is not None else None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            yield Tree(
                f"{self.channel.name}.aggregate",
                data=TreeNodeData(path=(self.channel.name, "aggregate"), value=self.aggregate_data),
                id="aggregate-tree",
            )
            yield Static(id="summary")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one("#aggregate-tree", Tree)
        tree.show_root = True
        tree.root.expand()
        self._populate_tree(tree.root, self.aggregate_data, path=(self.channel.name, "aggregate"))
        tree.cursor_line = 0
        self.query_one("#summary", Static).update(
            Panel(
                _build_channel_summary_text(self.channel),
                title=f"Channel: {self.channel.name}",
                border_style="green",
            )
        )

    def action_expand_selected(self) -> None:
        node = self._selected_node()
        if node.allow_expand:
            node.expand()

    def action_collapse_selected(self) -> None:
        node = self._selected_node()
        if node.allow_expand:
            node.collapse()

    def action_expand_all(self) -> None:
        self._selected_node().expand_all()

    def action_collapse_all(self) -> None:
        self._selected_node().collapse_all()

    def _selected_node(self):
        tree = self.query_one("#aggregate-tree", Tree)
        return tree.cursor_node or tree.root

    def _populate_tree(self, node, value: Any, *, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_path = (*path, str(key))
                if isinstance(item, (dict, list)):
                    child = node.add(
                        self._branch_label(str(key), item),
                        data=TreeNodeData(path=child_path, value=item),
                        expand=True,
                    )
                    self._populate_tree(child, item, path=child_path)
                else:
                    node.add_leaf(
                        self._leaf_tree_label(str(key), item),
                        data=TreeNodeData(path=child_path, value=item),
                    )
            return

        if isinstance(value, list):
            for index, item in enumerate(value):
                label = f"[{index}]"
                child_path = (*path, label)
                if isinstance(item, (dict, list)):
                    child = node.add(
                        self._branch_label(label, item),
                        data=TreeNodeData(path=child_path, value=item),
                        expand=True,
                    )
                    self._populate_tree(child, item, path=child_path)
                else:
                    node.add_leaf(
                        self._leaf_tree_label(label, item),
                        data=TreeNodeData(path=child_path, value=item),
                    )

    def _branch_label(self, key: str, value: Any) -> Text:
        if isinstance(value, dict):
            suffix = f"{{{len(value)} keys}}"
            style = "bold cyan"
        else:
            suffix = f"[{len(value)} items]"
            style = "bold yellow"
        return Text.assemble((key, style), ("  "), (suffix, "dim"))

    def _leaf_tree_label(self, key: str, value: Any) -> Text:
        return _leaf_label(key, value)


class ChannelExplorerApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    Horizontal {
        height: 1fr;
    }

    Tree {
        width: 1fr;
        border: round $accent;
    }

    #details {
        width: 1fr;
        border: round $success;
        padding: 1;
        overflow: auto;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("e", "expand_selected", "Expand"),
        Binding("c", "collapse_selected", "Collapse"),
        Binding("E", "expand_all", "Expand all"),
        Binding("C", "collapse_all", "Collapse all"),
    ]

    def __init__(self, payload: dict[str, Any], *, channel_name: str) -> None:
        super().__init__()
        self.payload = payload
        self.channel_name = channel_name

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            yield Tree(
                f"{self.channel_name} channel",
                data=TreeNodeData(path=(self.channel_name,), value=self.payload),
                id="payload-tree",
            )
            yield Static(id="details")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one("#payload-tree", Tree)
        tree.show_root = True
        tree.root.expand()
        self._populate_tree(tree.root, self.payload, path=(self.channel_name,))
        tree.cursor_line = 0
        self._update_details(tree.root.data)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[TreeNodeData]) -> None:
        self._update_details(event.node.data)

    def on_tree_node_selected(self, event: Tree.NodeSelected[TreeNodeData]) -> None:
        self._update_details(event.node.data)

    def action_expand_selected(self) -> None:
        node = self._selected_node()
        if node.allow_expand:
            node.expand()

    def action_collapse_selected(self) -> None:
        node = self._selected_node()
        if node.allow_expand:
            node.collapse()

    def action_expand_all(self) -> None:
        self._selected_node().expand_all()

    def action_collapse_all(self) -> None:
        self._selected_node().collapse_all()

    def _selected_node(self):
        tree = self.query_one("#payload-tree", Tree)
        return tree.cursor_node or tree.root

    def _populate_tree(self, node, value: Any, *, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_path = (*path, str(key))
                if isinstance(item, (dict, list)):
                    child = node.add(
                        self._branch_label(str(key), item),
                        data=TreeNodeData(path=child_path, value=item),
                        expand=False,
                    )
                    self._populate_tree(child, item, path=child_path)
                else:
                    node.add_leaf(
                        self._leaf_tree_label(str(key), item),
                        data=TreeNodeData(path=child_path, value=item),
                    )
            return

        if isinstance(value, list):
            for index, item in enumerate(value):
                label = f"[{index}]"
                child_path = (*path, label)
                if isinstance(item, (dict, list)):
                    child = node.add(
                        self._branch_label(label, item),
                        data=TreeNodeData(path=child_path, value=item),
                        expand=False,
                    )
                    self._populate_tree(child, item, path=child_path)
                else:
                    node.add_leaf(
                        self._leaf_tree_label(label, item),
                        data=TreeNodeData(path=child_path, value=item),
                    )

    def _branch_label(self, key: str, value: Any) -> Text:
        if isinstance(value, dict):
            suffix = f"{{{len(value)} keys}}"
            style = "bold cyan"
        else:
            suffix = f"[{len(value)} items]"
            style = "bold yellow"
        return Text.assemble((key, style), ("  "), (suffix, "dim"))

    def _leaf_tree_label(self, key: str, value: Any) -> Text:
        return _leaf_label(key, value)

    def _update_details(self, data: TreeNodeData | None) -> None:
        details = self.query_one("#details", Static)
        if data is None:
            details.update("No selection")
            return

        path = " / ".join(data.path)
        payload = json.dumps(data.value, indent=2, sort_keys=True)
        details.update(
            Panel(
                Syntax(payload, "json", theme="monokai", line_numbers=False),
                title=path,
                subtitle=type(data.value).__name__,
                border_style="green",
            )
        )
