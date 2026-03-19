from pathlib import Path
from typing import Annotated

import typer

from .utils.api import ProfileAnnotation, exit_for_unsupported_control_command

app = typer.Typer(no_args_is_help=True)


@app.command()
def upload_installer_tar(
    ctx: typer.Context,
    device_type_id: Annotated[int, typer.Argument(help="Device type ID to upload to")],
    installer_fp: Annotated[
        Path, typer.Argument(help="Path to the installer directory.")
    ] = Path(),
    _profile: ProfileAnnotation = None,
):
    """Compress and upload an installer to the Doover 2.0 Control Plane API."""
    _ = (ctx, device_type_id, installer_fp, _profile)
    exit_for_unsupported_control_command("device-type.upload-installer-tar")


@app.command()
def upload_installer(
    ctx: typer.Context,
    device_type_id: Annotated[int, typer.Argument(help="Device type ID to upload to")],
    installer_fp: Annotated[
        Path, typer.Argument(help="Path to the installer script.")
    ] = Path(),
    _profile: ProfileAnnotation = None,
):
    """Upload an installer to the Doover 2.0 Control Plane API."""
    _ = (ctx, device_type_id, installer_fp, _profile)
    exit_for_unsupported_control_command("device-type.upload-installer")
