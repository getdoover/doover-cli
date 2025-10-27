import shutil
import uuid
from pathlib import Path
from typing import Annotated

import requests
import typer

from .utils.api import ProfileAnnotation
from .utils.state import state

BASE_URL = "https://api.staging.udoover.com"

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
    state.api.client.do_refresh_token()
    fp = Path(f"/tmp/{uuid.uuid4()}")
    shutil.make_archive(
        base_name=str(fp), format="gztar", root_dir=installer_fp.resolve()
    )
    resp = requests.patch(
        f"{state.config_manager.current.base_url}/devices/types/{device_type_id}/",
        files={"installer": open(f"{fp}.tar.gz", "rb")},
        headers={"Authorization": f"Bearer {state.api.access_token.token}"},
    )
    resp.raise_for_status()
    print("Successfully uploaded installer.")


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
    state.api.client.do_refresh_token()
    resp = requests.patch(
        f"{state.config_manager.current.base_url}/devices/types/{device_type_id}/",
        files={"installer": installer_fp.read_text()},
        headers={"Authorization": f"Bearer {state.api.access_token.token}"},
    )
    resp.raise_for_status()
    print("Successfully uploaded installer.")
