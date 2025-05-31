import json

from pathlib import Path
from typing import Annotated

import typer
import jsf

from .utils.apps import get_app_directory, call_with_uv, get_app_config

app = typer.Typer(no_args_is_help=True)


@app.command()
def export(
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
):
    """Export the application configuration to the doover config json file."""
    config = get_app_config(app_fp)
    call_with_uv(config.src_directory / "app_config.py")


@app.command()
def validate(
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
):
    """Validate application config is a valid JSON schema."""
    root_fp = get_app_directory(app_fp)
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

        print(f"Schema for {k} is valid.")


@app.command()
def generate(
    app_fp: Annotated[
        Path, typer.Argument(help="Path to the application directory.")
    ] = Path(),
    output_fp: Annotated[
        Path, typer.Argument(help="Path to the output directory.")
    ] = None,
):
    """Generate a sample config for an application. This uses default values and sample values where possible."""
    root_fp = get_app_directory(app_fp)
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
        if output_fp:
            output_fp.write_text(output)
        else:
            print(output)
