import json

from pathlib import Path
from typing import Annotated

import rich
import typer

from .utils.apps import (
    app_names_in_config,
    get_app_directory,
    get_app_config,
    preserve_file,
    run_schema_export,
)

app = typer.Typer(no_args_is_help=True)


@app.command()
def export(
    ctx: typer.Context,
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    validate_: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Validate the notification schema before exporting.",
        ),
    ] = True,
    app_name: Annotated[
        str | None,
        typer.Option(
            help="Application name in doover_config.json. Required to pick one "
            "non-interactively when the repo defines multiple apps.",
        ),
    ] = None,
):
    """Export the application notification schema to the doover config json file."""
    root_fp = get_app_directory(app_fp)
    app_config = get_app_config(root_fp, app_name=app_name)
    export_command = app_config.export_notification_command or "export-notifications"
    if export_command == "NO_EXPORT":
        print("App requested no notification export. Skipping...")
        return

    print("Exporting notification schema...")
    run_schema_export(
        root_fp,
        app_config.export_notification_command,
        "export-notifications",
        optional=True,
        app_name=app_config.name,
        cwd=app_fp,
    )

    if validate_ is True:
        print("Validating notification schema...")
        ctx.invoke(validate, ctx, app_fp=app_fp, export_=False)


@app.command()
def validate(
    ctx: typer.Context,
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    export_: Annotated[
        bool,
        typer.Option(
            "--export/--no-export",
            help="Regenerate the schema from the source before validating. "
            "The export is transient -- doover_config.json is restored "
            "afterwards, so validation never writes to the working tree.",
        ),
    ] = True,
    app_name: Annotated[
        str | None,
        typer.Option(
            help="Application name in doover_config.json. Required to pick one "
            "non-interactively when the repo defines multiple apps.",
        ),
    ] = None,
):
    """Validate the application notification schema."""
    root_fp = get_app_directory(app_fp)
    config_file = root_fp / "doover_config.json"

    if export_ is True:
        targets = [app_name] if app_name else app_names_in_config(root_fp) or [None]
        with preserve_file(config_file):
            for target in targets:
                ctx.invoke(
                    export, ctx, app_fp=root_fp, validate_=False, app_name=target
                )
            _validate_notification_file(config_file)
    else:
        _validate_notification_file(config_file)


#: Every event a topic is built from has to survive being a topic segment, and
#: the policy decides which half of the hierarchy it lands in. Both are checked
#: here because a bad one is only otherwise discovered when a device in the
#: field tries to send the notification.
_VALID_POLICIES = ("default", "opt-in")


def _validate_notification_file(config_file: Path):
    if not config_file.exists():
        raise FileNotFoundError(
            "doover_config.json not found. Please ensure there is a "
            "doover_config.json file in the application directory."
        )
    data = json.loads(config_file.read_text())

    for k, v in data.items():
        if not isinstance(v, dict):
            continue

        schema = v.get("notification_schema")
        # An explicit null says the same thing as no key: this app declares no
        # notifications. Most apps do not, and an exporter that writes null is
        # how they say so.
        if schema is None:
            continue

        if not isinstance(schema, dict):
            rich.print(
                f"[red]Notification schema for {k} is not a JSON object "
                f"(got {type(schema).__name__}).[/red]"
            )
            raise typer.Exit(1)

        for event, entry in schema.items():
            if not isinstance(entry, dict):
                rich.print(
                    f"[red]Notification {event!r} for {k} is not a JSON object.[/red]"
                )
                raise typer.Exit(1)
            policy = entry.get("policy")
            if policy is not None and policy not in _VALID_POLICIES:
                rich.print(
                    f"[red]Notification {event!r} for {k} has policy {policy!r}; "
                    f"expected one of {', '.join(_VALID_POLICIES)}.[/red]"
                )
                raise typer.Exit(1)

        rich.print(
            f"[green]Notification schema for {k} is valid "
            f"({len(schema)} notification{'' if len(schema) == 1 else 's'}).[/green]"
        )
