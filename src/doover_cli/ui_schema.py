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
            help="Validate the UI schema before exporting.",
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
    """Export the application UI schema to the doover config json file."""
    root_fp = get_app_directory(app_fp)
    app_config = get_app_config(root_fp, app_name=app_name)
    export_command = app_config.export_ui_command or "export-ui"
    if export_command == "NO_EXPORT":
        print("App requested no ui export. Skipping...")
        return

    # A Rust app's `export` writes both schemas in one run, so this is the same
    # command the config export uses. Running it again rather than skipping is
    # what keeps `ui-schema validate --export` an actual check of the source
    # instead of a check of whatever was committed.
    run_schema_export(
        root_fp,
        app_config.export_ui_command,
        "export-ui",
        app_name=app_config.name,
        cwd=app_fp,
    )

    print("Exporting UI schema...")

    if validate_ is True:
        print("Validating UI schema...")
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
            help="Regenerate the schema from the Python before validating. "
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
    """Validate application UI schema is valid JSON."""
    root_fp = get_app_directory(app_fp)
    config_file = root_fp / "doover_config.json"

    if export_ is True:
        targets = [app_name] if app_name else app_names_in_config(root_fp) or [None]
        with preserve_file(config_file):
            for target in targets:
                ctx.invoke(
                    export, ctx, app_fp=root_fp, validate_=False, app_name=target
                )
            _validate_ui_file(config_file)
    else:
        _validate_ui_file(config_file)


def _validate_ui_file(config_file: Path):
    if not config_file.exists():
        raise FileNotFoundError(
            "doover_config.json not found. Please ensure there is a doover_config.json file in the application directory."
        )
    data = json.loads(config_file.read_text())

    for k, v in data.items():
        if not isinstance(v, dict):
            continue

        schema = v.get("ui_schema")
        # An explicit null says the same thing as no key at all: this app has no
        # UI. Several do -- the three core device apps among them -- and an
        # exporter that writes null is how they say so, so treating it as a
        # malformed schema failed the check on every one of them.
        if schema is None:
            continue

        if not isinstance(schema, (dict, list)):
            rich.print(
                f"[red]UI schema for {k} is not valid JSON (got {type(schema).__name__}).[/red]"
            )
            raise typer.Exit(1)

        rich.print(f"[green]UI schema for {k} is valid.[/green]")
