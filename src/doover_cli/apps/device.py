from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from pydoover.models.control import Device

from ..utils.crud import (
    build_create_command,
    build_update_command,
    parse_optional_bool,
    prompt_resource,
    resource_autocomplete,
)
from ..utils.api import ProfileAnnotation
from ..utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from ..renderer import RendererBase


app = typer.Typer(no_args_is_help=True)
_DEVICE_LABEL_ATTRS = ("display_name", "name")


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


def _device_autocomplete(*, archived: bool | None) -> object:
    return resource_autocomplete(
        Device,
        archived=archived,
        ordering="display_name",
        label_attrs=_DEVICE_LABEL_ATTRS,
        searchable_attrs=_DEVICE_LABEL_ATTRS,
    )


def _resolve_device_id(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    action: str,
    lookup: str | None,
    archived: bool | None,
) -> int:
    return prompt_resource(
        Device,
        client,
        renderer,
        action=action,
        lookup=lookup,
        archived=archived,
        ordering="display_name",
        label_attrs=_DEVICE_LABEL_ATTRS,
        searchable_attrs=_DEVICE_LABEL_ATTRS,
    )


def _resolve_output_path(
    output: Path | None,
    *,
    default_filename: str,
) -> Path:
    path = (output or Path(default_filename)).expanduser().resolve()
    if path.exists():
        raise typer.BadParameter(
            f"Output file already exists: {path}",
            param_hint="output",
        )
    return path


def _write_installer_download(output_path: Path, installer_data: object) -> None:
    if isinstance(installer_data, bytes):
        content = installer_data
    elif isinstance(installer_data, str):
        content = installer_data.encode("utf-8")
    else:
        content = str(installer_data).encode("utf-8")

    output_path.write_bytes(content)


@app.command(name="list")
def list_(
    application: Annotated[
        str | None, typer.Option(help="Filter by application identifier.")
    ] = None,
    archived: Annotated[
        str | None,
        typer.Option(
            help="Filter by archived status. Accepted values: true, false, 1, 0, yes, no."
        ),
    ] = None,
    display_name: Annotated[
        str | None, typer.Option(help="Filter by exact device display name.")
    ] = None,
    display_name_contains: Annotated[
        str | None,
        typer.Option(
            "--display-name-contains",
            help="Filter by case-sensitive display name substring.",
        ),
    ] = None,
    display_name_icontains: Annotated[
        str | None,
        typer.Option(
            "--display-name-icontains",
            help="Filter by case-insensitive display name substring.",
        ),
    ] = None,
    group: Annotated[str | None, typer.Option(help="Filter by group identifier.")] = None,
    group_tree: Annotated[
        str | None, typer.Option(help="Filter by group tree identifier.")
    ] = None,
    id: Annotated[
        list[int] | None,
        typer.Option(
            "--id",
            help="Filter by device ID. Repeat to match multiple IDs.",
        ),
    ] = None,
    name: Annotated[
        str | None, typer.Option(help="Filter by exact device name.")
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
            help="Sort expression passed directly to the API, for example display_name or -display_name."
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
    type: Annotated[str | None, typer.Option(help="Filter by device type identifier.")] = None,
    _profile: ProfileAnnotation = None,
):
    """List devices."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading devices..."):
        list_response = client.devices.list(
            application=application,
            archived=parse_optional_bool(archived, "--archived"),
            display_name=display_name,
            display_name__contains=display_name_contains,
            display_name__icontains=display_name_icontains,
            group=group,
            group_tree=group_tree,
            id=id or None,
            name=name,
            name__contains=name_contains,
            name__icontains=name_icontains,
            ordering=ordering,
            organisation=organisation,
            page=page,
            per_page=per_page,
            search=search,
            type=type,
        )

    renderer.render_list(list_response)


@app.command()
def get(
    device_id: Annotated[
        str | None,
        typer.Argument(
            help="Device ID or exact display name/name to retrieve.",
            autocompletion=_device_autocomplete(archived=False),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Get a device."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_device_id(
        client,
        renderer,
        action="get",
        lookup=device_id,
        archived=False,
    )

    with renderer.loading("Loading device..."):
        response = client.devices.retrieve(str(resolved_id))

    renderer.render(response)


create = build_create_command(
    model_cls=Device,
    command_help="Create a device.",
    get_state=lambda: get_state(),
)
app.command()(create)


update = build_update_command(
    model_cls=Device,
    command_help="Update a device.",
    get_state=lambda: get_state(),
    resource_id_param_name="device_id",
    resource_id_help="Device ID or exact display name/name to update.",
)
app.command()(update)


@app.command()
def archive(
    device_id: Annotated[
        str | None,
        typer.Argument(
            help="Device ID or exact display name/name to archive.",
            autocompletion=_device_autocomplete(archived=False),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Archive a device."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_device_id(
        client,
        renderer,
        action="archive",
        lookup=device_id,
        archived=False,
    )

    with renderer.loading("Archiving device..."):
        response = client.devices.archive(str(resolved_id))

    renderer.render(response)


@app.command()
def unarchive(
    device_id: Annotated[
        str | None,
        typer.Argument(
            help="Device ID or exact display name/name to unarchive.",
            autocompletion=_device_autocomplete(archived=True),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Unarchive a device."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_device_id(
        client,
        renderer,
        action="unarchive",
        lookup=device_id,
        archived=True,
    )

    with renderer.loading("Unarchiving device..."):
        response = client.devices.unarchive(str(resolved_id))

    renderer.render(response)


@app.command()
def installer_info(
    device_id: Annotated[
        str | None,
        typer.Argument(
            help="Device ID or exact display name/name.",
            autocompletion=_device_autocomplete(archived=False),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Show installer metadata for a device."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_device_id(
        client,
        renderer,
        action="show installer info for",
        lookup=device_id,
        archived=False,
    )

    with renderer.loading("Loading installer info..."):
        response = client.devices.installer_info(str(resolved_id))

    renderer.render(response)


@app.command()
def installer(
    device_id: Annotated[
        str | None,
        typer.Argument(
            help="Device ID or exact display name/name.",
            autocompletion=_device_autocomplete(archived=False),
        ),
    ] = None,
    output: Annotated[
        Path | None, typer.Option(help="Path to save the installer to.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Download the installer package for a device."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_device_id(
        client,
        renderer,
        action="download installer for",
        lookup=device_id,
        archived=False,
    )
    output_path = _resolve_output_path(
        output,
        default_filename=f"device-installer-{resolved_id}.sh",
    )

    with renderer.loading("Downloading installer..."):
        response = client.devices.installer_download(str(resolved_id))

    _write_installer_download(output_path, response)
    print(f"Saved installer to {output_path}")


@app.command()
def installer_tarball(
    device_id: Annotated[
        str | None,
        typer.Argument(
            help="Device ID or exact display name/name.",
            autocompletion=_device_autocomplete(archived=False),
        ),
    ] = None,
    output: Annotated[
        Path | None, typer.Option(help="Path to save the installer tarball to.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Download the installer tarball for a device."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_device_id(
        client,
        renderer,
        action="download installer tarball for",
        lookup=device_id,
        archived=False,
    )
    output_path = _resolve_output_path(
        output,
        default_filename=f"device-installer-{resolved_id}.tar.gz",
    )

    with renderer.loading("Downloading installer tarball..."):
        response = client.devices.installer_tarball(str(resolved_id))

    output_path.write_bytes(response)
    print(f"Saved installer tarball to {output_path}")


@app.command()
def installer_zip(
    device_id: Annotated[
        str | None,
        typer.Argument(
            help="Device ID or exact display name/name.",
            autocompletion=_device_autocomplete(archived=False),
        ),
    ] = None,
    output: Annotated[
        Path | None, typer.Option(help="Path to save the installer zip to.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Download the installer zip for a device."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_device_id(
        client,
        renderer,
        action="download installer zip for",
        lookup=device_id,
        archived=False,
    )
    output_path = _resolve_output_path(
        output,
        default_filename=f"device-installer-{resolved_id}.zip",
    )

    with renderer.loading("Downloading installer zip..."):
        response = client.devices.installer_zip(str(resolved_id))

    output_path.write_bytes(response)
    print(f"Saved installer zip to {output_path}")
