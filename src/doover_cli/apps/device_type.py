import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import questionary
import typer
from pydoover.models.control import DeviceType

from ..utils import parsers
from ..utils.crud import build_create_command_callback, build_update_command_callback
from ..utils.api import ProfileAnnotation, exit_for_unsupported_control_command
from ..utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from ..renderer import RendererBase


app = typer.Typer(no_args_is_help=True)


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


def _parse_optional_bool(value: str | None, option_name: str) -> bool | None:
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False

    raise typer.BadParameter(
        f"{option_name} must be one of: true, false, 1, 0, yes, no."
    )


def _load_solution_choices(client: "ControlClient") -> list[questionary.Choice]:
    page_num = 1
    choices: list[questionary.Choice] = []

    while True:
        page = client.solutions.list(
            archived=False,
            ordering="display_name",
            page=page_num,
            per_page=100,
        )

        for solution in page.results:
            choices.append(
                questionary.Choice(
                    title=f"{solution.display_name} ({solution.id})",
                    value=solution.id,
                )
            )

        if not page.next or len(choices) >= page.count:
            break
        page_num += 1

    return choices


def _prompt_solution_id(client: "ControlClient", default: int | None = None) -> int:
    choices = _load_solution_choices(client)

    if choices:
        default_choice = next(
            (choice for choice in choices if choice.value == default),
            None,
        )
        answer = questionary.select(
            "Solution",
            choices=choices,
            default=default_choice,
            use_search_filter=True,
            use_jk_keys=False,
            instruction="Choose the solution for this device type.",
        ).unsafe_ask()
        if answer is None:
            raise typer.Abort()
        return int(answer)

    answer = questionary.text(
        "Solution ID",
        default="" if default is None else str(default),
        validate=lambda value: (
            True
            if value.strip().lstrip("-").isdigit()
            else "Please enter a valid solution ID."
        ),
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()
    return int(answer.strip())


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
            archived=_parse_optional_bool(archived, "--archived"),
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
    device_type_id: Annotated[int, typer.Argument(help="Device type ID to retrieve.")],
    _profile: ProfileAnnotation = None,
):
    """Get a device type."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading device type..."):
        response = client.devices.types_retrieve(str(device_type_id))

    renderer.render(response)


create = build_create_command_callback(
    model_cls=DeviceType,
    command_help="Create a device type.",
    get_state=lambda: get_state(),
    submit_callback=lambda client, model_instance: client.devices.types_create(
        model_instance
    ),
    resource_prompt_resolvers={"Solution": _prompt_solution_id},
)
app.command()(create)


update = build_update_command_callback(
    model_cls=DeviceType,
    command_help="Update a device type.",
    get_state=lambda: get_state(),
    retrieve_callback=lambda client, device_type_id: client.devices.types_retrieve(
        str(device_type_id)
    ),
    submit_callback=lambda client, device_type_id, payload, method: (
        client.devices.types_partial(str(device_type_id), payload)
        if method == "PATCH"
        else client.devices.types_update(str(device_type_id), payload)
    ),
    resource_id_param_name="device_type_id",
    resource_id_type=int,
    resource_id_help="Device type ID to update.",
    resource_prompt_resolvers={"Solution": _prompt_solution_id},
)
app.command()(update)


@app.command()
def archive(
    device_type_id: Annotated[int, typer.Argument(help="Device type ID to archive.")],
    _profile: ProfileAnnotation = None,
):
    """Archive a device type."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Archiving device type..."):
        response = client.devices.types_archive(str(device_type_id))

    renderer.render(response)


@app.command()
def unarchive(
    device_type_id: Annotated[int, typer.Argument(help="Device type ID to unarchive.")],
    _profile: ProfileAnnotation = None,
):
    """Unarchive a device type."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Unarchiving device type..."):
        response = client.devices.types_unarchive(str(device_type_id))

    renderer.render(response)


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
