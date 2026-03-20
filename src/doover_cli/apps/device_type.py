import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import questionary
import typer
from pydoover.models.control import DeviceType

from ..utils import parsers
from ..utils.crud import build_create_command_callback
from ..utils.api import ProfileAnnotation, exit_for_unsupported_control_command
from ..utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from ..renderer import RendererBase


app = typer.Typer(no_args_is_help=True)


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


def _parse_json_option(value: str | None) -> Any:
    if value is None:
        return None
    return parsers.maybe_json(value)


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
        default=_stringify_prompt_default(default),
        validate=lambda value: (
            True
            if value.strip().lstrip("-").isdigit()
            else "Please enter a valid solution ID."
        ),
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()
    return int(answer.strip())


def _build_device_type_payload(
    *,
    name: str | None,
    solution_id: int | None,
    config: str | None,
    config_schema: str | None,
    device_extra_config_schema: str | None,
    installer: Path | None,
    installer_info: str | None,
    copy_command: str | None,
    description: str | None,
    logo_url: str | None,
    extra_info: str | None,
    stars: int | None,
    default_icon: str | None,
    require_name: bool = False,
    require_solution_id: bool = False,
) -> dict[str, Any]:
    if require_name and name is None:
        raise typer.BadParameter("Missing required option --name.", param_hint="--name")
    if require_solution_id and solution_id is None:
        raise typer.BadParameter(
            "Missing required option --solution-id.",
            param_hint="--solution-id",
        )

    payload: dict[str, Any] = {}

    if name is not None:
        payload["name"] = name
    if solution_id is not None:
        payload["solution_id"] = solution_id
    if config is not None:
        payload["config"] = _parse_json_option(config)
    if config_schema is not None:
        payload["config_schema"] = _parse_json_option(config_schema)
    if device_extra_config_schema is not None:
        payload["device_extra_config_schema"] = _parse_json_option(
            device_extra_config_schema
        )
    if installer is not None:
        payload["installer"] = installer
    if installer_info is not None:
        payload["installer_info"] = installer_info
    if copy_command is not None:
        payload["copy_command"] = copy_command
    if description is not None:
        payload["description"] = description
    if logo_url is not None:
        payload["logo_url"] = logo_url
    if extra_info is not None:
        payload["extra_info"] = extra_info
    if stars is not None:
        payload["stars"] = stars
    if default_icon is not None:
        payload["default_icon"] = default_icon

    return payload


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


@app.command()
def update(
    device_type_id: Annotated[int, typer.Argument(help="Device type ID to update.")],
    name: Annotated[str, typer.Option(help="Device type name.")],
    solution_id: Annotated[
        int, typer.Option("--solution-id", help="Solution ID to attach the device type to.")
    ],
    config: Annotated[
        str | None, typer.Option(help="Device config JSON payload.")
    ] = None,
    config_schema: Annotated[
        str | None, typer.Option(help="Config schema JSON payload.")
    ] = None,
    device_extra_config_schema: Annotated[
        str | None,
        typer.Option(
            "--device-extra-config-schema",
            help="Device extra config schema JSON payload.",
        ),
    ] = None,
    installer: Annotated[
        Path | None, typer.Option(help="Path to an installer file to upload.")
    ] = None,
    installer_info: Annotated[
        str | None, typer.Option(help="Installer info string.")
    ] = None,
    copy_command: Annotated[
        str | None, typer.Option(help="Copy command string.")
    ] = None,
    description: Annotated[
        str | None, typer.Option(help="Device type description.")
    ] = None,
    logo_url: Annotated[str | None, typer.Option(help="Logo URL.")] = None,
    extra_info: Annotated[
        str | None, typer.Option(help="Extra info string.")
    ] = None,
    stars: Annotated[int | None, typer.Option(help="Stars count.")] = None,
    default_icon: Annotated[
        str | None, typer.Option(help="Default icon name.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Replace a device type."""
    _ = _profile
    client, renderer = get_state()
    payload = _build_device_type_payload(
        name=name,
        solution_id=solution_id,
        config=config,
        config_schema=config_schema,
        device_extra_config_schema=device_extra_config_schema,
        installer=installer,
        installer_info=installer_info,
        copy_command=copy_command,
        description=description,
        logo_url=logo_url,
        extra_info=extra_info,
        stars=stars,
        default_icon=default_icon,
        require_name=True,
        require_solution_id=True,
    )

    with renderer.loading("Updating device type..."):
        response = client.devices.types_update(str(device_type_id), payload)

    renderer.render(response)


@app.command()
def patch(
    device_type_id: Annotated[int, typer.Argument(help="Device type ID to patch.")],
    name: Annotated[str | None, typer.Option(help="Device type name.")] = None,
    solution_id: Annotated[
        int | None,
        typer.Option("--solution-id", help="Solution ID to attach the device type to."),
    ] = None,
    config: Annotated[
        str | None, typer.Option(help="Device config JSON payload.")
    ] = None,
    config_schema: Annotated[
        str | None, typer.Option(help="Config schema JSON payload.")
    ] = None,
    device_extra_config_schema: Annotated[
        str | None,
        typer.Option(
            "--device-extra-config-schema",
            help="Device extra config schema JSON payload.",
        ),
    ] = None,
    installer: Annotated[
        Path | None, typer.Option(help="Path to an installer file to upload.")
    ] = None,
    installer_info: Annotated[
        str | None, typer.Option(help="Installer info string.")
    ] = None,
    copy_command: Annotated[
        str | None, typer.Option(help="Copy command string.")
    ] = None,
    description: Annotated[
        str | None, typer.Option(help="Device type description.")
    ] = None,
    logo_url: Annotated[str | None, typer.Option(help="Logo URL.")] = None,
    extra_info: Annotated[
        str | None, typer.Option(help="Extra info string.")
    ] = None,
    stars: Annotated[int | None, typer.Option(help="Stars count.")] = None,
    default_icon: Annotated[
        str | None, typer.Option(help="Default icon name.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Patch a device type."""
    _ = _profile
    client, renderer = get_state()
    payload = _build_device_type_payload(
        name=name,
        solution_id=solution_id,
        config=config,
        config_schema=config_schema,
        device_extra_config_schema=device_extra_config_schema,
        installer=installer,
        installer_info=installer_info,
        copy_command=copy_command,
        description=description,
        logo_url=logo_url,
        extra_info=extra_info,
        stars=stars,
        default_icon=default_icon,
    )

    if not payload:
        raise typer.BadParameter(
            "Please provide at least one field to patch.",
            param_hint="device-type patch",
        )

    with renderer.loading("Patching device type..."):
        response = client.devices.types_partial(str(device_type_id), payload)

    renderer.render(response)


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
