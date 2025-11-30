import json

from pathlib import Path
from typing import Annotated

import rich
import typer
import jsf

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
            help="Validate the configuration before exporting.",
        ),
    ] = True,
    config_fp: Annotated[
        Path,
        typer.Option(
            help="Path to the configuration file to export to.",
            exists=False,
            file_okay=True,
        ),
    ] = None,
):
    """Export the application configuration to the doover config json file."""
    if config_fp is None:
        root_fp = get_app_directory(app_fp)
        app_config = get_app_config(root_fp)
        call_with_uv(
            app_config.export_config_command or "export-config",
            in_shell=True,
            cwd=app_fp,
        )
    else:
        config = get_app_config(app_fp)
        call_with_uv(config.src_directory / "app_config.py", in_shell=True)

    print("Exporting application configuration...")

    if validate_ is True:
        print("Validating application configuration...")
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
            help="Export the configuration before validating.",
        ),
    ] = True,
):
    """Validate application config is a valid JSON schema."""
    root_fp = get_app_directory(app_fp)

    if export_ is True:
        ctx.invoke(export, ctx, app_fp=root_fp, validate_=False)

    config_file = root_fp / "doover_config.json"
    if not config_file.exists():
        raise FileNotFoundError(
            "doover_config.json not found. Please ensure there is a doover_config.json file in the application directory."
        )
    data = json.loads(config_file.read_text())

    import jsonschema

    for k, v in data.items():
        if not isinstance(v, dict):
            continue

        try:
            schema = v["config_schema"]
        except KeyError:
            continue

        try:
            jsonschema.validate(instance={}, schema=schema)
        except jsonschema.exceptions.SchemaError as e:
            raise e
        except jsonschema.exceptions.ValidationError:
            pass

        rich.print(f"[green]Schema for {k} is valid.[/green]")


@app.command()
def generate(
    ctx: typer.Context,
    output_fp: Annotated[
        Path, typer.Argument(help="Path to the output directory.")
    ] = None,
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    export_: Annotated[
        bool,
        typer.Option(
            "--export",
            help="Export the configuration before generating the sample config.",
        ),
    ] = True,
):
    """Generate a sample config for an application. This uses default values and sample values where possible."""
    root_fp = get_app_directory(app_fp)

    if export_ is True:
        print("Exporting application configuration...")
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
            schema = v["config_schema"]
        except KeyError:
            continue

        output = jsf.JSF(schema).generate(use_defaults=True, use_examples=True)
        output = json.dumps(output, indent=4)
        if output_fp:
            output_fp.write_text(output)
        else:
            print(output)
