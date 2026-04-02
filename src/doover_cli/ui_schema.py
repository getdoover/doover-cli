import json

from pathlib import Path
from typing import Annotated

import rich
import typer

from .utils.apps import get_app_directory, call_with_uv, get_app_config

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
):
    """Export the application UI schema to the doover config json file."""
    root_fp = get_app_directory(app_fp)
    app_config = get_app_config(root_fp)
    export_command = app_config.export_ui_command or "export-ui"
    if export_command == "NO_EXPORT":
        print("App requested no ui export. Skipping...")
        return

    call_with_uv(
        export_command,
        in_shell=True,
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
            "--export",
            help="Export the UI schema before validating.",
        ),
    ] = True,
):
    """Validate application UI schema is valid JSON."""
    root_fp = get_app_directory(app_fp)

    if export_ is True:
        ctx.invoke(export, ctx, app_fp=root_fp, validate_=False)

    config_file = root_fp / "doover_config.json"
    if not config_file.exists():
        raise FileNotFoundError(
            "doover_config.json not found. Please ensure there is a doover_config.json file in the application directory."
        )
    data = json.loads(config_file.read_text())

    for k, v in data.items():
        if not isinstance(v, dict):
            continue

        try:
            schema = v["ui_schema"]
        except KeyError:
            continue

        if not isinstance(schema, (dict, list)):
            rich.print(
                f"[red]UI schema for {k} is not valid JSON (got {type(schema).__name__}).[/red]"
            )
            raise typer.Exit(1)

        rich.print(f"[green]UI schema for {k} is valid.[/green]")
