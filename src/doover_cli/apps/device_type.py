import tarfile
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Annotated

import typer
from pydoover.models.control import DeviceType

from ..utils.crud import (
    build_create_command,
    build_update_command,
    parse_optional_bool,
    prompt_path,
    prompt_resource,
    resource_autocomplete,
)
from ..utils.api import ProfileAnnotation
from ..utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from ..renderer import RendererBase


app = typer.Typer(no_args_is_help=True)


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


def _upload_device_type_installer(
    *,
    device_type_id: int,
    installer_fp: Path,
) -> DeviceType:
    client, _ = get_state()
    return client.devices.types_partial(
        str(device_type_id),
        body={"installer": installer_fp},
    )


@app.command(name="list")
def list_(
    archived: Annotated[
        str | None,
        typer.Option(
            help="Filter by archived status. Accepted values: true, false, 1, 0, yes, no."
        ),
    ] = None,
    id: Annotated[int | None, typer.Option(help="Filter by device type ID.")] = None,
    name: Annotated[
        str | None, typer.Option(help="Filter by exact device type name.")
    ] = None,
    name_contains: Annotated[
        str | None,
        typer.Option(
            "--name-contains",
            help="Filter by case-sensitive name substring.",
        ),
    ] = None,
    name_icontains: Annotated[
        str | None,
        typer.Option(
            "--name-icontains",
            help="Filter by case-insensitive name substring.",
        ),
    ] = None,
    ordering: Annotated[
        str | None,
        typer.Option(
            help="Sort expression passed directly to the API, for example name, -name, stars, or -stars."
        ),
    ] = None,
    organisation: Annotated[
        str | None, typer.Option(help="Filter by organisation identifier.")
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    stars: Annotated[
        int | None, typer.Option(help="Filter by exact stars value.")
    ] = None,
    stars_gt: Annotated[
        int | None,
        typer.Option("--stars-gt", help="Filter by stars greater than this value."),
    ] = None,
    stars_gte: Annotated[
        int | None,
        typer.Option(
            "--stars-gte",
            help="Filter by stars greater than or equal to this value.",
        ),
    ] = None,
    stars_lt: Annotated[
        int | None,
        typer.Option("--stars-lt", help="Filter by stars less than this value."),
    ] = None,
    stars_lte: Annotated[
        int | None,
        typer.Option(
            "--stars-lte",
            help="Filter by stars less than or equal to this value.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """List device types."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading device types..."):
        time.sleep(0.05)
        list_response = client.devices.types_list(
            archived=parse_optional_bool(archived, "--archived"),
            id=id,
            name=name,
            name__contains=name_contains,
            name__icontains=name_icontains,
            ordering=ordering,
            organisation=organisation,
            page=page,
            per_page=per_page,
            search=search,
            stars=stars,
            stars__gt=stars_gt,
            stars__gte=stars_gte,
            stars__lt=stars_lt,
            stars__lte=stars_lte,
        )

    renderer.render_list(list_response)


@app.command()
def get(
    device_type_id: Annotated[
        str | None,
        typer.Argument(
            help="Device type ID or exact name to retrieve.",
            autocompletion=resource_autocomplete(
                DeviceType,
                archived=False,
                ordering="name",
            ),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Get a device type."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = prompt_resource(
        DeviceType,
        client,
        renderer,
        action="get",
        lookup=device_type_id,
        archived=False,
        ordering="name",
    )

    with renderer.loading("Loading device type..."):
        response = client.devices.types_retrieve(str(resolved_id))

    renderer.render(response)


create = build_create_command(
    model_cls=DeviceType,
    command_help="Create a device type.",
    get_state=lambda: get_state(),
)
app.command()(create)


update = build_update_command(
    model_cls=DeviceType,
    command_help="Update a device type.",
    get_state=lambda: get_state(),
    resource_id_param_name="device_type_id",
    resource_id_type=int,
    resource_id_help="Device type ID to update.",
)
app.command()(update)


@app.command()
def archive(
    device_type_id: Annotated[
        str | None,
        typer.Argument(
            help="Device type ID or exact name to archive.",
            autocompletion=resource_autocomplete(
                DeviceType,
                archived=False,
                ordering="name",
            ),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Archive a device type."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = prompt_resource(
        DeviceType,
        client,
        renderer,
        action="archive",
        lookup=device_type_id,
        archived=False,
        ordering="name",
    )

    with renderer.loading("Archiving device type..."):
        response = client.devices.types_archive(str(resolved_id))

    renderer.render(response)


@app.command()
def unarchive(
    device_type_id: Annotated[
        str | None,
        typer.Argument(
            help="Device type ID or exact name to unarchive.",
            autocompletion=resource_autocomplete(
                DeviceType,
                archived=True,
                ordering="name",
            ),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Unarchive a device type."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = prompt_resource(
        DeviceType,
        client,
        renderer,
        action="unarchive",
        lookup=device_type_id,
        archived=True,
        ordering="name",
    )

    with renderer.loading("Unarchiving device type..."):
        response = client.devices.types_unarchive(str(resolved_id))

    renderer.render(response)


@app.command()
def upload_installer_tar(
    device_type_id: Annotated[
        str | None,
        typer.Argument(
            help="Device type ID or exact name.",
            autocompletion=resource_autocomplete(
                DeviceType,
                archived=False,
                ordering="name",
            ),
        ),
    ] = None,
    installer_fp: Annotated[
        Path | None, typer.Argument(help="Path to the installer directory.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Compress and upload an installer to the Doover 2.0 Control Plane API."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = prompt_resource(
        DeviceType,
        client,
        renderer,
        action="update",
        lookup=device_type_id,
        archived=False,
        ordering="name",
    )
    installer_dir = prompt_path(
        renderer,
        label="Installer directory path",
        value=installer_fp,
        exists=True,
        file_okay=False,
        dir_okay=True,
        param_hint="installer_fp",
    )

    with NamedTemporaryFile(suffix=".tar.gz") as temp_tar:
        temp_tar_path = Path(temp_tar.name)
        with tarfile.open(temp_tar_path, mode="w:gz") as archive:
            archive.add(installer_dir, arcname=installer_dir.name)

        with renderer.loading("Uploading installer tarball..."):
            response = _upload_device_type_installer(
                device_type_id=resolved_id,
                installer_fp=temp_tar_path,
            )

    renderer.render(response)


@app.command()
def upload_installer(
    device_type_id: Annotated[
        str | None,
        typer.Argument(
            help="Device type ID or exact name.",
            autocompletion=resource_autocomplete(
                DeviceType,
                archived=False,
                ordering="name",
            ),
        ),
    ] = None,
    installer_fp: Annotated[
        Path | None, typer.Argument(help="Path to the installer script.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Upload an installer to the Doover 2.0 Control Plane API."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = prompt_resource(
        DeviceType,
        client,
        renderer,
        action="update",
        lookup=device_type_id,
        archived=False,
        ordering="name",
    )
    installer_path = prompt_path(
        renderer,
        label="Installer file path",
        value=installer_fp,
        exists=True,
        file_okay=True,
        dir_okay=False,
        param_hint="installer_fp",
    )

    with renderer.loading("Uploading installer..."):
        response = client.devices.types_partial(
            str(resolved_id),
            body={"installer": installer_path},
        )

    renderer.render(response)
