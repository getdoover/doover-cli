import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import click
import questionary
import typer
from pydoover.models.control import DeviceType

from ..utils import parsers
from ..utils.crud import build_create_command_callback, build_update_command_callback
from ..utils.api import (
    ProfileAnnotation,
    exit_for_unsupported_control_command,
    setup_session,
)
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


def _load_device_type_choices(
    client: "ControlClient", *, archived: bool
) -> list[dict[str, Any]]:
    page_num = 1
    choices: list[dict[str, Any]] = []

    while True:
        page = client.devices.types_list(
            archived=archived,
            ordering="name",
            page=page_num,
            per_page=100,
        )

        for device_type in page.results:
            device_type_id = int(device_type.id)
            name = getattr(device_type, "name", None)
            display_name = getattr(device_type, "display_name", None)
            label = (
                display_name
                or name
                or f"Device type {device_type_id}"
            )
            choices.append(
                {
                    "id": device_type_id,
                    "name": name,
                    "display_name": display_name,
                    "label": f"{label} ({device_type_id})",
                }
            )

        if not page.next or len(choices) >= page.count:
            break
        page_num += 1

    return choices


def _get_device_type_completion_client(
    ctx: click.Context | None = None,
) -> "ControlClient":
    profile_name = "default"
    if ctx is not None:
        profile_name = (
            ctx.params.get("_profile")
            or ctx.params.get("profile")
            or profile_name
        )

    session = setup_session(profile_name)
    return session.get_control_client()


def _resolve_device_type_lookup_from_choices(
    choices: list[dict[str, Any]],
    lookup: str,
) -> int:
    stripped = lookup.strip()
    if not stripped:
        raise typer.BadParameter("Please provide a device type ID or name.")

    if stripped.lstrip("-").isdigit():
        return int(stripped)

    exact_label_match = next(
        (choice["id"] for choice in choices if choice["label"] == stripped),
        None,
    )
    if exact_label_match is not None:
        return exact_label_match

    lowered_lookup = stripped.casefold()
    matches = [
        choice
        for choice in choices
        if any(
            candidate is not None and candidate.casefold() == lowered_lookup
            for candidate in (
                choice["name"],
                choice["display_name"],
                choice["label"],
            )
        )
    ]

    unique_matches = {choice["id"]: choice for choice in matches}
    if len(unique_matches) == 1:
        return next(iter(unique_matches.values()))["id"]

    if len(unique_matches) > 1:
        matching_labels = ", ".join(
            sorted(choice["label"] for choice in unique_matches.values())
        )
        raise typer.BadParameter(
            f"Multiple device types match '{lookup}'. Use an ID or one of: {matching_labels}."
        )

    raise typer.BadParameter(
        f"No device type found matching '{lookup}'. Use an ID or an exact device type name."
    )


def _complete_device_type_lookup(
    ctx: click.Context,
    _param: click.Parameter | None,
    incomplete: str,
    *,
    archived: bool,
) -> list[click.shell_completion.CompletionItem]:
    try:
        client = _get_device_type_completion_client(ctx)
        choices = _load_device_type_choices(client, archived=archived)
    except Exception:
        return []

    lowered_incomplete = incomplete.casefold().strip()
    completion_items: list[click.shell_completion.CompletionItem] = []

    for choice in choices:
        searchable_values = (
            choice["label"],
            choice["name"],
            choice["display_name"],
            str(choice["id"]),
        )
        if lowered_incomplete and not any(
            value is not None and lowered_incomplete in value.casefold()
            for value in searchable_values
        ):
            continue

        completion_items.append(
            click.shell_completion.CompletionItem(
                choice["label"],
                help=f"ID {choice['id']}",
            )
        )

    return completion_items


def _complete_active_device_type_lookup(
    ctx: click.Context,
    param: click.Parameter | None,
    incomplete: str,
) -> list[click.shell_completion.CompletionItem]:
    return _complete_device_type_lookup(
        ctx,
        param,
        incomplete,
        archived=False,
    )


def _complete_archived_device_type_lookup(
    ctx: click.Context,
    param: click.Parameter | None,
    incomplete: str,
) -> list[click.shell_completion.CompletionItem]:
    return _complete_device_type_lookup(
        ctx,
        param,
        incomplete,
        archived=True,
    )


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


def _prompt_device_type_id(
    client: "ControlClient",
    *,
    action: str,
    archived: bool,
    default: int | None = None,
) -> int:
    choices = _load_device_type_choices(client, archived=archived)

    if choices:
        choice_labels = [choice["label"] for choice in choices]
        default_choice = next(
            (choice["label"] for choice in choices if choice["id"] == default),
            "",
        )
        answer = questionary.autocomplete(
            f"Device type to {action}",
            choices=choice_labels,
            default=default_choice,
            match_middle=True,
            validate=lambda value: _validate_device_type_lookup(choices, value),
        ).unsafe_ask()
        if answer is None:
            raise typer.Abort()
        return _resolve_device_type_lookup_from_choices(choices, answer)

    answer = questionary.text(
        "Device type ID",
        default=_stringify_prompt_default(default),
        validate=lambda value: (
            True
            if value.strip().lstrip("-").isdigit()
            else "Please enter a valid device type ID."
        ),
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()
    return int(answer.strip())


def _validate_device_type_lookup(
    choices: list[dict[str, Any]], value: str
) -> bool | str:
    try:
        _resolve_device_type_lookup_from_choices(choices, value)
    except typer.BadParameter as exc:
        return str(exc)
    return True


def _resolve_device_type_id(
    client: "ControlClient",
    lookup: str | None,
    *,
    action: str,
    archived: bool,
) -> int:
    if lookup is None:
        return _prompt_device_type_id(client, action=action, archived=archived)

    stripped_lookup = lookup.strip()
    if stripped_lookup.lstrip("-").isdigit():
        return int(stripped_lookup)

    choices = _load_device_type_choices(client, archived=archived)
    return _resolve_device_type_lookup_from_choices(choices, lookup)


def _prompt_create_fields(
    client: "ControlClient",
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
) -> dict[str, Any]:
    prompted_name = _prompt_required_text("Device type name", name)
    prompted_solution_id = _prompt_solution_id(client, solution_id)
    prompted_config = _prompt_optional_text("Config JSON", config)
    prompted_config_schema = _prompt_optional_text("Config schema JSON", config_schema)
    prompted_device_extra_config_schema = _prompt_optional_text(
        "Device extra config schema JSON",
        device_extra_config_schema,
    )
    installer_input = _prompt_optional_text("Installer file path", installer)
    prompted_installer_info = _prompt_optional_text("Installer info", installer_info)
    prompted_copy_command = _prompt_optional_text("Copy command", copy_command)
    prompted_description = _prompt_optional_text("Description", description)
    prompted_logo_url = _prompt_optional_text("Logo URL", logo_url)
    prompted_extra_info = _prompt_optional_text("Extra info", extra_info)
    prompted_stars = _prompt_optional_int("Stars", stars)
    prompted_default_icon = _prompt_optional_text("Default icon", default_icon)

    return {
        "name": prompted_name,
        "solution_id": prompted_solution_id,
        "config": prompted_config,
        "config_schema": prompted_config_schema,
        "device_extra_config_schema": prompted_device_extra_config_schema,
        "installer": Path(installer_input) if installer_input is not None else None,
        "installer_info": prompted_installer_info,
        "copy_command": prompted_copy_command,
        "description": prompted_description,
        "logo_url": prompted_logo_url,
        "extra_info": prompted_extra_info,
        "stars": prompted_stars,
        "default_icon": prompted_default_icon,
    }


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
    device_type_id: Annotated[
        str | None,
        typer.Argument(
            help="Device type ID or exact name to archive.",
            shell_complete=_complete_active_device_type_lookup,
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Archive a device type."""
    _ = _profile
    client, renderer = get_state()

    device_type_id = _resolve_device_type_id(
        client,
        device_type_id,
        action="archive",
        archived=False,
    )

    with renderer.loading("Archiving device type..."):
        response = client.devices.types_archive(str(device_type_id))

    renderer.render(response)


@app.command()
def unarchive(
    device_type_id: Annotated[
        str | None,
        typer.Argument(
            help="Device type ID or exact name to unarchive.",
            shell_complete=_complete_archived_device_type_lookup,
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Unarchive a device type."""
    _ = _profile
    client, renderer = get_state()

    device_type_id = _resolve_device_type_id(
        client,
        device_type_id,
        action="unarchive",
        archived=True,
    )

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
