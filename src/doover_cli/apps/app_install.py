from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import typer
from pydoover.models.control import (
    Application,
    ApplicationInstallation,
    ApplicationInstallationSolution,
    Device,
)

from ..utils import parsers
from ..utils.api import ProfileAnnotation
from ..utils.crud import (
    Field,
    LookupChoice,
    parse_optional_bool,
    prompt_resource,
    resource_autocomplete,
)
from ..utils.crud.lookup import load_control_model_choices, resolve_resource_lookup
from ..utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from ..renderer import RendererBase


app = typer.Typer(no_args_is_help=True)
device_app = typer.Typer(no_args_is_help=True)
application_app = typer.Typer(no_args_is_help=True)

_APP_INSTALL_LABEL_ATTRS = ("display_name", "name")
_APPLICATION_LABEL_ATTRS = ("display_name", "name")
_DEVICE_LABEL_ATTRS = ("display_name", "name")


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


def _app_install_autocomplete(*, archived: bool | None) -> object:
    return resource_autocomplete(
        ApplicationInstallation,
        archived=archived,
        ordering="display_name",
        label_attrs=_APP_INSTALL_LABEL_ATTRS,
        searchable_attrs=_APP_INSTALL_LABEL_ATTRS,
    )


def _application_autocomplete() -> object:
    return resource_autocomplete(
        Application,
        archived=False,
        ordering="name",
        label_attrs=_APPLICATION_LABEL_ATTRS,
        searchable_attrs=_APPLICATION_LABEL_ATTRS,
    )


def _device_autocomplete() -> object:
    return resource_autocomplete(
        Device,
        archived=False,
        ordering="display_name",
        label_attrs=_DEVICE_LABEL_ATTRS,
        searchable_attrs=_DEVICE_LABEL_ATTRS,
    )


def _solution_autocomplete() -> object:
    return resource_autocomplete(
        ApplicationInstallationSolution,
        archived=False,
        ordering="name",
        label_attrs=("name",),
        searchable_attrs=("name",),
    )


def _resolve_app_install_id(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    action: str,
    lookup: str | None,
    archived: bool | None,
) -> int:
    return prompt_resource(
        ApplicationInstallation,
        client,
        renderer,
        action=action,
        lookup=lookup,
        archived=archived,
        ordering="display_name",
        label_attrs=_APP_INSTALL_LABEL_ATTRS,
        searchable_attrs=_APP_INSTALL_LABEL_ATTRS,
    )


def _resolve_application_id(
    client: "ControlClient",
    renderer: "RendererBase",
    lookup: str | int | None,
) -> int | None:
    return _resolve_resource_id(
        Application,
        client,
        renderer,
        lookup,
        label_attrs=_APPLICATION_LABEL_ATTRS,
        action="select",
    )


def _resolve_application_context_id(
    client: "ControlClient",
    renderer: "RendererBase",
    lookup: str | None,
    *,
    action: str,
) -> int:
    return prompt_resource(
        Application,
        client,
        renderer,
        action=action,
        lookup=lookup,
        archived=False,
        ordering="name",
        label_attrs=_APPLICATION_LABEL_ATTRS,
        searchable_attrs=_APPLICATION_LABEL_ATTRS,
    )


def _resolve_device_id(
    client: "ControlClient",
    renderer: "RendererBase",
    lookup: str | int | None,
) -> int | None:
    return _resolve_resource_id(
        Device,
        client,
        renderer,
        lookup,
        label_attrs=_DEVICE_LABEL_ATTRS,
        action="select",
    )


def _resolve_device_context_id(
    client: "ControlClient",
    renderer: "RendererBase",
    lookup: str | None,
    *,
    action: str,
) -> int:
    return prompt_resource(
        Device,
        client,
        renderer,
        action=action,
        lookup=lookup,
        archived=False,
        ordering="display_name",
        label_attrs=_DEVICE_LABEL_ATTRS,
        searchable_attrs=_DEVICE_LABEL_ATTRS,
    )


def _resolve_solution_id(
    client: "ControlClient",
    renderer: "RendererBase",
    lookup: str | int | None,
) -> int | None:
    return _resolve_resource_id(
        ApplicationInstallationSolution,
        client,
        renderer,
        lookup,
        label_attrs=("name",),
        action="select",
    )


def _resolve_resource_id(
    model_cls: type[Any],
    client: "ControlClient",
    renderer: "RendererBase",
    lookup: str | int | None,
    *,
    label_attrs: tuple[str, ...],
    action: str,
) -> int | None:
    if lookup is None:
        return None
    if isinstance(lookup, int):
        return lookup

    stripped = lookup.strip()
    if not stripped:
        return None
    if stripped.lstrip("-").isdigit():
        return int(stripped)

    return prompt_resource(
        model_cls,
        client,
        renderer,
        action=action,
        lookup=stripped,
        archived=False,
        ordering=label_attrs[0],
        label_attrs=label_attrs,
        searchable_attrs=label_attrs,
    )


def _parse_json_option(
    value: str | dict[str, Any] | list[Any] | None, option_name: str
) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value

    parsed = parsers.maybe_json(value)
    if isinstance(parsed, str):
        raise typer.BadParameter(
            f"{option_name} must be valid JSON.",
            param_hint=option_name,
        )
    return parsed


def _get_resource_id(value: Any, output_id: str = "id") -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    if isinstance(value, dict):
        raw_id = value.get(output_id, value.get("id"))
        return int(raw_id) if raw_id is not None else None
    raw_id = getattr(value, output_id, getattr(value, "id", None))
    return int(raw_id) if raw_id is not None else None


def _get_resource_ids(value: Any) -> list[int] | None:
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return []
        value = parsers.maybe_json(value)
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, (list, tuple)):
        value = [value]

    ids: list[int] = []
    for item in value:
        item_id = _get_resource_id(item)
        if item_id is not None:
            ids.append(item_id)
    return ids


def _omit_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _current_install_payload(install: Any) -> dict[str, Any]:
    payload = {
        "name": getattr(install, "name", None),
        "display_name": getattr(install, "display_name", None),
        "application_id": _get_resource_id(getattr(install, "application", None)),
        "device_id": _get_resource_id(getattr(install, "device", None)),
        "version": getattr(install, "version", None),
        "deployment_config": getattr(install, "deployment_config", None),
        "config_profile_ids": _get_resource_ids(
            getattr(install, "config_profiles", None)
        ),
        "solution_id": _get_resource_id(getattr(install, "solution", None)),
    }
    return _omit_none(payload)


def _collect_changed_payload(
    current_payload: dict[str, Any],
    updated_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in updated_payload.items()
        if current_payload.get(key) != value
    }


def _build_app_install_payload(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    name: str | None,
    display_name: str | None,
    application: str | int | None,
    device: str | int | None,
    version: str | None,
    deployment_config: str | dict[str, Any] | list[Any] | None,
    config_profile_ids: list[int] | None,
    solution: str | int | None,
    include_empty_config_profiles: bool = False,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "display_name": display_name,
        "application_id": _resolve_application_id(client, renderer, application),
        "device_id": _resolve_device_id(client, renderer, device),
        "version": version,
        "deployment_config": _parse_json_option(
            deployment_config,
            "--deployment-config",
        ),
        "config_profile_ids": (
            config_profile_ids
            if config_profile_ids or include_empty_config_profiles
            else None
        ),
        "solution_id": _resolve_solution_id(client, renderer, solution),
    }
    return _omit_none(payload)


def _resource_prompt_field(
    client: "ControlClient",
    *,
    model_cls: type[Any],
    key: str,
    label: str,
    default: Any,
    required: bool,
    ordering: str,
    label_attrs: tuple[str, ...],
    searchable_attrs: tuple[str, ...] | None = None,
) -> Field:
    try:
        choices = load_control_model_choices(
            client,
            model_cls,
            archived=False,
            ordering=ordering,
            label_attrs=label_attrs,
            searchable_attrs=searchable_attrs or label_attrs,
        )
    except KeyError:
        return Field(
            key=key,
            label=label,
            kind="text",
            required=required,
            default=default,
            allow_blank=not required,
        )

    return Field(
        key=key,
        label=label,
        kind="resource",
        required=required,
        default=default,
        resource_model_cls=model_cls,
        resource_model_label=label.lower(),
        resource_lookup_choices=choices,
        match_middle=True,
        allow_blank=not required,
    )


def _prompt_create_values(
    client: "ControlClient",
    renderer: "RendererBase",
    values: dict[str, Any],
    *,
    include_application: bool = True,
    include_device: bool = True,
) -> dict[str, Any]:
    fields: list[Field] = [
        Field(
            key="display_name",
            label="Display name",
            kind="text",
            required=True,
            default=values.get("display_name"),
            allow_blank=False,
        ),
        Field(
            key="name",
            label="Name",
            kind="text",
            required=False,
            default=values.get("name"),
        ),
        Field(
            key="version",
            label="Version",
            kind="text",
            required=False,
            default=values.get("version"),
        ),
        Field(
            key="deployment_config",
            label="Deployment config",
            kind="json",
            required=False,
            default=values.get("deployment_config"),
        ),
        Field(
            key="config_profile_ids",
            label="Config profile ids",
            kind="text",
            required=False,
            default=",".join(str(i) for i in (values.get("config_profile_ids") or [])),
        ),
        _resource_prompt_field(
            client,
            model_cls=ApplicationInstallationSolution,
            key="solution",
            label="Solution",
            default=values.get("solution"),
            required=False,
            ordering="name",
            label_attrs=("name",),
        ),
    ]
    if include_device:
        fields.insert(
            2 if include_application else 1,
            _resource_prompt_field(
                client,
                model_cls=Device,
                key="device",
                label="Device",
                default=values.get("device"),
                required=True,
                ordering="display_name",
                label_attrs=_DEVICE_LABEL_ATTRS,
            ),
        )
    if include_application:
        fields.insert(
            1,
            _resource_prompt_field(
                client,
                model_cls=Application,
                key="application",
                label="Application",
                default=values.get("application"),
                required=True,
                ordering="name",
                label_attrs=_APPLICATION_LABEL_ATTRS,
            ),
        )
    prompted = renderer.prompt_fields(fields)
    merged = {**values, **prompted}
    merged["config_profile_ids"] = _get_resource_ids(merged.get("config_profile_ids"))
    return merged


def _prompt_update_values(
    client: "ControlClient",
    renderer: "RendererBase",
    current_payload: dict[str, Any],
    *,
    include_application: bool = True,
    include_device: bool = True,
) -> dict[str, Any]:
    fields: list[Field] = [
        Field("name", "Name", "text", False, current_payload.get("name")),
        Field(
            "display_name",
            "Display name",
            "text",
            False,
            current_payload.get("display_name"),
        ),
        Field("version", "Version", "text", False, current_payload.get("version")),
        Field(
            "deployment_config",
            "Deployment config",
            "json",
            False,
            current_payload.get("deployment_config"),
        ),
        Field(
            "config_profile_ids",
            "Config profile ids",
            "text",
            False,
            ",".join(str(i) for i in current_payload.get("config_profile_ids", [])),
        ),
        _resource_prompt_field(
            client,
            model_cls=ApplicationInstallationSolution,
            key="solution",
            label="Solution",
            default=current_payload.get("solution_id"),
            required=False,
            ordering="name",
            label_attrs=("name",),
        ),
    ]
    if include_device:
        fields.insert(
            3 if include_application else 2,
            _resource_prompt_field(
                client,
                model_cls=Device,
                key="device",
                label="Device",
                default=current_payload.get("device_id"),
                required=False,
                ordering="display_name",
                label_attrs=_DEVICE_LABEL_ATTRS,
            ),
        )
    if include_application:
        fields.insert(
            2,
            _resource_prompt_field(
                client,
                model_cls=Application,
                key="application",
                label="Application",
                default=current_payload.get("application_id"),
                required=False,
                ordering="name",
                label_attrs=_APPLICATION_LABEL_ATTRS,
            ),
        )
    prompted = renderer.prompt_fields(fields)
    prompted["config_profile_ids"] = _get_resource_ids(
        prompted.get("config_profile_ids")
    )
    return prompted


def _install_list_kwargs(
    *,
    archived: str | None,
    display_name: str | None,
    display_name_contains: str | None,
    display_name_icontains: str | None,
    id: int | None,
    name: str | None,
    name_contains: str | None,
    name_icontains: str | None,
    ordering: str | None,
    organisation: str | None,
    organisation_isnull: str | None,
    page: int | None,
    per_page: int | None,
    search: str | None,
    solution: str | None,
    status: str | None,
    template: str | None,
    version: str | None,
    version_contains: str | None,
    version_icontains: str | None,
) -> dict[str, Any]:
    return {
        "archived": parse_optional_bool(archived, "--archived"),
        "display_name": display_name,
        "display_name__contains": display_name_contains,
        "display_name__icontains": display_name_icontains,
        "id": id,
        "name": name,
        "name__contains": name_contains,
        "name__icontains": name_icontains,
        "ordering": ordering,
        "organisation": organisation,
        "organisation__isnull": parse_optional_bool(
            organisation_isnull,
            "--organisation-isnull",
        ),
        "page": page,
        "per_page": per_page,
        "search": search,
        "solution": solution,
        "status": status,
        "template": template,
        "version": version,
        "version__contains": version_contains,
        "version__icontains": version_icontains,
    }


def _page_results(page: Any) -> list[Any]:
    if isinstance(page, dict):
        return list(page.get("results") or [])
    return list(getattr(page, "results", []) or [])


def _page_next(page: Any) -> Any:
    if isinstance(page, dict):
        return page.get("next")
    return getattr(page, "next", None)


def _page_count(page: Any) -> int | None:
    if isinstance(page, dict):
        count = page.get("count")
    else:
        count = getattr(page, "count", None)
    return int(count) if count is not None else None


def _resource_value(resource: Any, key: str) -> Any:
    if isinstance(resource, dict):
        return resource.get(key)
    return getattr(resource, key, None)


def _choice_for_app_install(resource: Any) -> LookupChoice | None:
    resource_id = _get_resource_id(resource)
    if resource_id is None:
        return None

    field_values = {
        field_name: _resource_value(resource, field_name)
        for field_name in _APP_INSTALL_LABEL_ATTRS
    }
    label_text = next(
        (
            field_values[field_name]
            for field_name in _APP_INSTALL_LABEL_ATTRS
            if field_values.get(field_name)
        ),
        f"Application installation {resource_id}",
    )
    search_values = [f"{label_text} ({resource_id})", str(resource_id)]
    search_values.extend(
        value for value in field_values.values() if isinstance(value, str) and value
    )
    return LookupChoice(
        id=resource_id,
        label=f"{label_text} ({resource_id})",
        search_values=tuple(dict.fromkeys(search_values)),
        field_values=field_values,
    )


def _load_device_app_install_choices(
    client: "ControlClient",
    *,
    device_id: str,
    archived: bool | None,
) -> list[LookupChoice]:
    page_num = 1
    choices: list[LookupChoice] = []

    while True:
        page = client.devices.app_installs_list(
            parent_lookup_device=str(device_id),
            archived=archived,
            ordering="display_name",
            page=page_num,
            per_page=100,
        )
        for resource in _page_results(page):
            choice = _choice_for_app_install(resource)
            if choice is not None:
                choices.append(choice)

        count = _page_count(page)
        if not _page_next(page) or (count is not None and len(choices) >= count):
            break
        page_num += 1

    return choices


def _load_application_app_install_choices(
    client: "ControlClient",
    *,
    application_id: str,
    archived: bool | None,
) -> list[LookupChoice]:
    page_num = 1
    choices: list[LookupChoice] = []

    while True:
        page = client.applications.installs_list(
            parent_lookup_application=str(application_id),
            archived=archived,
            ordering="display_name",
            page=page_num,
            per_page=100,
        )
        for resource in _page_results(page):
            choice = _choice_for_app_install(resource)
            if choice is not None:
                choices.append(choice)

        count = _page_count(page)
        if not _page_next(page) or (count is not None and len(choices) >= count):
            break
        page_num += 1

    return choices


def _resolve_device_app_install_id(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    device_id: str,
    action: str,
    lookup: str | None,
    archived: bool | None,
) -> int:
    model_label = "application installation"
    if lookup is not None and lookup.strip().lstrip("-").isdigit():
        return int(lookup.strip())

    choices = _load_device_app_install_choices(
        client,
        device_id=device_id,
        archived=archived,
    )
    if lookup is not None:
        return resolve_resource_lookup(choices, lookup, model_label=model_label)

    field = Field(
        key="resource_id",
        label=f"Application installation to {action}",
        kind="resource",
        required=True,
        resource_model_cls=ApplicationInstallation,
        resource_model_label=model_label,
        resource_lookup_choices=choices,
        match_middle=True,
        allow_blank=False,
    )
    prompted = renderer.prompt_fields([field])
    prompt_value = prompted.get("resource_id")
    if prompt_value is None:
        raise typer.BadParameter(
            "Please provide an application installation ID or name.",
            param_hint="app_install",
        )
    return resolve_resource_lookup(choices, str(prompt_value), model_label=model_label)


def _resolve_application_app_install_id(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    application_id: str,
    action: str,
    lookup: str | None,
    archived: bool | None,
) -> int:
    model_label = "application installation"
    if lookup is not None and lookup.strip().lstrip("-").isdigit():
        return int(lookup.strip())

    choices = _load_application_app_install_choices(
        client,
        application_id=application_id,
        archived=archived,
    )
    if lookup is not None:
        return resolve_resource_lookup(choices, lookup, model_label=model_label)

    field = Field(
        key="resource_id",
        label=f"Application installation to {action}",
        kind="resource",
        required=True,
        resource_model_cls=ApplicationInstallation,
        resource_model_label=model_label,
        resource_lookup_choices=choices,
        match_middle=True,
        allow_blank=False,
    )
    prompted = renderer.prompt_fields([field])
    prompt_value = prompted.get("resource_id")
    if prompt_value is None:
        raise typer.BadParameter(
            "Please provide an application installation ID or name.",
            param_hint="app_install",
        )
    return resolve_resource_lookup(choices, str(prompt_value), model_label=model_label)


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
    device: Annotated[
        str | None, typer.Option(help="Filter by device identifier.")
    ] = None,
    display_name: Annotated[
        str | None, typer.Option(help="Filter by exact display name.")
    ] = None,
    display_name_contains: Annotated[
        str | None,
        typer.Option(
            "--display-name-contains", help="Filter by display name substring."
        ),
    ] = None,
    display_name_icontains: Annotated[
        str | None,
        typer.Option(
            "--display-name-icontains",
            help="Filter by case-insensitive display name substring.",
        ),
    ] = None,
    id: Annotated[int | None, typer.Option(help="Filter by app install ID.")] = None,
    name: Annotated[str | None, typer.Option(help="Filter by exact name.")] = None,
    name_contains: Annotated[
        str | None, typer.Option("--name-contains", help="Filter by name substring.")
    ] = None,
    name_icontains: Annotated[
        str | None,
        typer.Option(
            "--name-icontains", help="Filter by case-insensitive name substring."
        ),
    ] = None,
    ordering: Annotated[
        str | None, typer.Option(help="Sort expression passed directly to the API.")
    ] = None,
    organisation: Annotated[
        str | None, typer.Option(help="Filter by organisation identifier.")
    ] = None,
    organisation_isnull: Annotated[
        str | None,
        typer.Option(
            "--organisation-isnull",
            help="Filter by whether organisation is null. Accepted values: true, false, 1, 0, yes, no.",
        ),
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    solution: Annotated[
        str | None, typer.Option(help="Filter by solution identifier.")
    ] = None,
    status: Annotated[
        str | None, typer.Option(help="Filter by install status.")
    ] = None,
    template: Annotated[
        str | None, typer.Option(help="Filter by template identifier.")
    ] = None,
    version: Annotated[
        str | None, typer.Option(help="Filter by exact version.")
    ] = None,
    version_contains: Annotated[
        str | None,
        typer.Option("--version-contains", help="Filter by version substring."),
    ] = None,
    version_icontains: Annotated[
        str | None,
        typer.Option(
            "--version-icontains", help="Filter by case-insensitive version substring."
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """List application installations."""
    _ = _profile
    client, renderer = get_state()
    kwargs = _install_list_kwargs(
        archived=archived,
        display_name=display_name,
        display_name_contains=display_name_contains,
        display_name_icontains=display_name_icontains,
        id=id,
        name=name,
        name_contains=name_contains,
        name_icontains=name_icontains,
        ordering=ordering,
        organisation=organisation,
        organisation_isnull=organisation_isnull,
        page=page,
        per_page=per_page,
        search=search,
        solution=solution,
        status=status,
        template=template,
        version=version,
        version_contains=version_contains,
        version_icontains=version_icontains,
    )

    with renderer.loading("Loading application installations..."):
        response = client.app_installs.list(
            application=application,
            device=device,
            **kwargs,
        )

    renderer.render_list(response)


@app.command()
def get(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name to retrieve.",
            autocompletion=_app_install_autocomplete(archived=False),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Get an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="get",
        lookup=app_install,
        archived=False,
    )

    with renderer.loading("Loading application installation..."):
        response = client.app_installs.retrieve(str(resolved_id))

    renderer.render(response)


@app.command()
def create(
    display_name: Annotated[
        str | None,
        typer.Option("--display-name", help="Display name. Required by the API."),
    ] = None,
    name: Annotated[str | None, typer.Option(help="Install name.")] = None,
    application: Annotated[
        str | None,
        typer.Option(
            help="Application ID or exact display name/name.",
            autocompletion=_application_autocomplete(),
        ),
    ] = None,
    device: Annotated[
        str | None,
        typer.Option(
            help="Device ID or exact display name/name.",
            autocompletion=_device_autocomplete(),
        ),
    ] = None,
    version: Annotated[str | None, typer.Option(help="Application version.")] = None,
    deployment_config: Annotated[
        str | None, typer.Option("--deployment-config", help="Deployment config JSON.")
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to set multiple config profiles.",
        ),
    ] = None,
    solution: Annotated[
        str | None,
        typer.Option(
            help="Solution ID or exact name.",
            autocompletion=_solution_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Create an application installation."""
    _ = _profile
    client, renderer = get_state()
    values = {
        "display_name": display_name,
        "name": name,
        "application": application,
        "device": device,
        "version": version,
        "deployment_config": deployment_config,
        "config_profile_ids": config_profile_ids,
        "solution": solution,
    }

    if not values["display_name"] or not values["application"] or not values["device"]:
        values = _prompt_create_values(client, renderer, values)

    payload = _build_app_install_payload(client, renderer, **values)
    for key, option_name in (
        ("display_name", "--display-name"),
        ("application_id", "--application"),
        ("device_id", "--device"),
    ):
        if payload.get(key) is None:
            raise typer.BadParameter(
                f"{option_name} is required.", param_hint=option_name
            )

    with renderer.loading("Creating application installation..."):
        response = client.app_installs.create(body=payload)

    renderer.render(response)


@app.command()
def update(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name to update.",
            autocompletion=_app_install_autocomplete(archived=False),
        ),
    ] = None,
    display_name: Annotated[
        str | None, typer.Option("--display-name", help="Display name.")
    ] = None,
    name: Annotated[str | None, typer.Option(help="Install name.")] = None,
    application: Annotated[
        str | None,
        typer.Option(
            help="Application ID or exact display name/name.",
            autocompletion=_application_autocomplete(),
        ),
    ] = None,
    device: Annotated[
        str | None,
        typer.Option(
            help="Device ID or exact display name/name.",
            autocompletion=_device_autocomplete(),
        ),
    ] = None,
    version: Annotated[str | None, typer.Option(help="Application version.")] = None,
    deployment_config: Annotated[
        str | None, typer.Option("--deployment-config", help="Deployment config JSON.")
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to replace config profiles.",
        ),
    ] = None,
    solution: Annotated[
        str | None,
        typer.Option(
            help="Solution ID or exact name.",
            autocompletion=_solution_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Update an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="update",
        lookup=app_install,
        archived=False,
    )

    provided = {
        "display_name": display_name,
        "name": name,
        "application": application,
        "device": device,
        "version": version,
        "deployment_config": deployment_config,
        "config_profile_ids": config_profile_ids,
        "solution": solution,
    }
    provided = {key: value for key, value in provided.items() if value is not None}

    if not provided:
        with renderer.loading("Loading current application installation..."):
            current_install = client.app_installs.retrieve(str(resolved_id))
        current_payload = _current_install_payload(current_install)
        prompted = _prompt_update_values(client, renderer, current_payload)
        updated_payload = _build_app_install_payload(
            client,
            renderer,
            name=prompted.get("name"),
            display_name=prompted.get("display_name"),
            application=prompted.get("application"),
            device=prompted.get("device"),
            version=prompted.get("version"),
            deployment_config=prompted.get("deployment_config"),
            config_profile_ids=prompted.get("config_profile_ids"),
            solution=prompted.get("solution"),
            include_empty_config_profiles=True,
        )
        payload = _collect_changed_payload(current_payload, updated_payload)
    else:
        payload = _build_app_install_payload(
            client,
            renderer,
            name=provided.get("name"),
            display_name=provided.get("display_name"),
            application=provided.get("application"),
            device=provided.get("device"),
            version=provided.get("version"),
            deployment_config=provided.get("deployment_config"),
            config_profile_ids=provided.get("config_profile_ids"),
            solution=provided.get("solution"),
            include_empty_config_profiles="config_profile_ids" in provided,
        )

    if not payload:
        print("No changes submitted.")
        return

    with renderer.loading("Updating application installation..."):
        response = client.app_installs.partial(str(resolved_id), body=payload)

    renderer.render(response)


@app.command()
def archive(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name to archive.",
            autocompletion=_app_install_autocomplete(archived=False),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Archive an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="archive",
        lookup=app_install,
        archived=False,
    )

    with renderer.loading("Archiving application installation..."):
        response = client.app_installs.archive(str(resolved_id))

    renderer.render(response)


@app.command()
def unarchive(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name to unarchive.",
            autocompletion=_app_install_autocomplete(archived=True),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Unarchive an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="unarchive",
        lookup=app_install,
        archived=True,
    )

    with renderer.loading("Unarchiving application installation..."):
        response = client.app_installs.unarchive(str(resolved_id))

    renderer.render(response)


@app.command()
def delete(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name to delete.",
            autocompletion=_app_install_autocomplete(archived=None),
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Delete without confirmation.")
    ] = False,
    _profile: ProfileAnnotation = None,
):
    """Permanently delete an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="delete",
        lookup=app_install,
        archived=None,
    )

    if not yes:
        typer.confirm(
            f"Permanently delete app install {resolved_id}?",
            abort=True,
        )

    with renderer.loading("Deleting application installation..."):
        client.app_installs.delete(str(resolved_id))

    print(f"Deleted app install {resolved_id}.")


@app.command()
def deploy(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name to deploy.",
            autocompletion=_app_install_autocomplete(archived=False),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Create a deployment for an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="deploy",
        lookup=app_install,
        archived=False,
    )

    with renderer.loading("Creating application deployment..."):
        response = client.app_installs.deployments_create(str(resolved_id))

    renderer.render(response)


@app.command()
def deployments(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name.",
            autocompletion=_app_install_autocomplete(archived=False),
        ),
    ] = None,
    ordering: Annotated[
        str | None, typer.Option(help="Sort expression passed directly to the API.")
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    _profile: ProfileAnnotation = None,
):
    """List deployments for an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="list deployments for",
        lookup=app_install,
        archived=False,
    )

    with renderer.loading("Loading application deployments..."):
        response = client.app_installs.deployments_list(
            parent_lookup_app_install=str(resolved_id),
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
        )

    renderer.render_list(response)


@app.command()
def deployment(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name.",
            autocompletion=_app_install_autocomplete(archived=False),
        ),
    ],
    deployment_id: Annotated[str, typer.Argument(help="Deployment ID to retrieve.")],
    _profile: ProfileAnnotation = None,
):
    """Get a deployment for an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="get deployment for",
        lookup=app_install,
        archived=False,
    )

    with renderer.loading("Loading application deployment..."):
        response = client.app_installs.deployments_retrieve(
            id=str(deployment_id),
            parent_lookup_app_install=str(resolved_id),
        )

    renderer.render(response)


@app.command()
def sync_config_profiles(
    app_install: Annotated[
        str | None,
        typer.Argument(
            help="Application install ID or exact display name/name to sync.",
            autocompletion=_app_install_autocomplete(archived=False),
        ),
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to replace config profiles.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Sync config profiles for an application installation."""
    _ = _profile
    client, renderer = get_state()
    resolved_id = _resolve_app_install_id(
        client,
        renderer,
        action="sync config profiles for",
        lookup=app_install,
        archived=False,
    )

    with renderer.loading("Loading current application installation..."):
        current_install = client.app_installs.retrieve(str(resolved_id))
    payload = _current_install_payload(current_install)
    if config_profile_ids is not None:
        payload["config_profile_ids"] = config_profile_ids

    with renderer.loading("Syncing config profiles..."):
        response = client.app_installs.sync_config_profiles(
            str(resolved_id),
            body=payload,
        )

    renderer.render(response)


@device_app.command(name="list")
def device_list(
    device_id: Annotated[
        str | None,
        typer.Argument(help="Device ID or exact display name/name."),
    ] = None,
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
        str | None, typer.Option(help="Filter by exact display name.")
    ] = None,
    display_name_contains: Annotated[
        str | None,
        typer.Option(
            "--display-name-contains", help="Filter by display name substring."
        ),
    ] = None,
    display_name_icontains: Annotated[
        str | None,
        typer.Option(
            "--display-name-icontains",
            help="Filter by case-insensitive display name substring.",
        ),
    ] = None,
    id: Annotated[int | None, typer.Option(help="Filter by app install ID.")] = None,
    name: Annotated[str | None, typer.Option(help="Filter by exact name.")] = None,
    name_contains: Annotated[
        str | None, typer.Option("--name-contains", help="Filter by name substring.")
    ] = None,
    name_icontains: Annotated[
        str | None,
        typer.Option(
            "--name-icontains", help="Filter by case-insensitive name substring."
        ),
    ] = None,
    ordering: Annotated[
        str | None, typer.Option(help="Sort expression passed directly to the API.")
    ] = None,
    organisation: Annotated[
        str | None, typer.Option(help="Filter by organisation identifier.")
    ] = None,
    organisation_isnull: Annotated[
        str | None,
        typer.Option(
            "--organisation-isnull",
            help="Filter by whether organisation is null. Accepted values: true, false, 1, 0, yes, no.",
        ),
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    solution: Annotated[
        str | None, typer.Option(help="Filter by solution identifier.")
    ] = None,
    status: Annotated[
        str | None, typer.Option(help="Filter by install status.")
    ] = None,
    template: Annotated[
        str | None, typer.Option(help="Filter by template identifier.")
    ] = None,
    version: Annotated[
        str | None, typer.Option(help="Filter by exact version.")
    ] = None,
    version_contains: Annotated[
        str | None,
        typer.Option("--version-contains", help="Filter by version substring."),
    ] = None,
    version_icontains: Annotated[
        str | None,
        typer.Option(
            "--version-icontains",
            help="Filter by case-insensitive version substring.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """List application installations on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client,
        renderer,
        device_id,
        action="list app installs for",
    )
    list_for_device(
        device_id=str(resolved_device_id),
        client=client,
        renderer=renderer,
        application=application,
        archived=archived,
        display_name=display_name,
        display_name_contains=display_name_contains,
        display_name_icontains=display_name_icontains,
        id=id,
        name=name,
        name_contains=name_contains,
        name_icontains=name_icontains,
        ordering=ordering,
        organisation=organisation,
        organisation_isnull=organisation_isnull,
        page=page,
        per_page=per_page,
        search=search,
        solution=solution,
        status=status,
        template=template,
        version=version,
        version_contains=version_contains,
        version_icontains=version_icontains,
    )


@device_app.command(name="create")
def device_create(
    device_id: Annotated[
        str | None,
        typer.Argument(help="Device ID or exact display name/name."),
    ] = None,
    display_name: Annotated[
        str | None,
        typer.Option("--display-name", help="Display name. Required by the API."),
    ] = None,
    name: Annotated[str | None, typer.Option(help="Install name.")] = None,
    application: Annotated[
        str | None,
        typer.Option(
            help="Application ID or exact display name/name.",
            autocompletion=_application_autocomplete(),
        ),
    ] = None,
    version: Annotated[str | None, typer.Option(help="Application version.")] = None,
    deployment_config: Annotated[
        str | None, typer.Option("--deployment-config", help="Deployment config JSON.")
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to set multiple config profiles.",
        ),
    ] = None,
    solution: Annotated[
        str | None,
        typer.Option(
            help="Solution ID or exact name.",
            autocompletion=_solution_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Create an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client,
        renderer,
        device_id,
        action="create an app install on",
    )
    values = {
        "display_name": display_name,
        "name": name,
        "application": application,
        "device": str(resolved_device_id),
        "version": version,
        "deployment_config": deployment_config,
        "config_profile_ids": config_profile_ids,
        "solution": solution,
    }

    if not values["display_name"] or not values["application"]:
        values = _prompt_create_values(
            client,
            renderer,
            values,
            include_device=False,
        )
        values["device"] = str(resolved_device_id)

    payload = _build_app_install_payload(client, renderer, **values)
    for key, option_name in (
        ("display_name", "--display-name"),
        ("application_id", "--application"),
        ("device_id", "device_id"),
    ):
        if payload.get(key) is None:
            raise typer.BadParameter(
                f"{option_name} is required.", param_hint=option_name
            )

    with renderer.loading("Creating application installation..."):
        response = client.app_installs.create(body=payload)

    renderer.render(response)


def _resolve_device_scoped_app_install(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    device_id: str,
    app_install: str | None,
    action: str,
    archived: bool | None = False,
) -> int:
    return _resolve_device_app_install_id(
        client,
        renderer,
        device_id=device_id,
        action=action,
        lookup=app_install,
        archived=archived,
    )


@device_app.command(name="get")
def device_get(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Get an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="get app install from")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="get",
    )

    with renderer.loading("Loading application installation..."):
        response = client.app_installs.retrieve(str(resolved_id))

    renderer.render(response)


@device_app.command(name="update")
def device_update(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to update."),
    ] = None,
    display_name: Annotated[
        str | None, typer.Option("--display-name", help="Display name.")
    ] = None,
    name: Annotated[str | None, typer.Option(help="Install name.")] = None,
    application: Annotated[
        str | None,
        typer.Option(
            help="Application ID or exact display name/name.",
            autocompletion=_application_autocomplete(),
        ),
    ] = None,
    version: Annotated[str | None, typer.Option(help="Application version.")] = None,
    deployment_config: Annotated[
        str | None, typer.Option("--deployment-config", help="Deployment config JSON.")
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to replace config profiles.",
        ),
    ] = None,
    solution: Annotated[
        str | None,
        typer.Option(
            help="Solution ID or exact name.",
            autocompletion=_solution_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Update an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="update app install on")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="update",
    )

    provided = {
        "display_name": display_name,
        "name": name,
        "application": application,
        "version": version,
        "deployment_config": deployment_config,
        "config_profile_ids": config_profile_ids,
        "solution": solution,
    }
    provided = {key: value for key, value in provided.items() if value is not None}

    if not provided:
        with renderer.loading("Loading current application installation..."):
            current_install = client.app_installs.retrieve(str(resolved_id))
        current_payload = _current_install_payload(current_install)
        prompted = _prompt_update_values(
            client,
            renderer,
            current_payload,
            include_device=False,
        )
        prompted["device"] = str(resolved_device_id)
        updated_payload = _build_app_install_payload(
            client,
            renderer,
            name=prompted.get("name"),
            display_name=prompted.get("display_name"),
            application=prompted.get("application"),
            device=prompted.get("device"),
            version=prompted.get("version"),
            deployment_config=prompted.get("deployment_config"),
            config_profile_ids=prompted.get("config_profile_ids"),
            solution=prompted.get("solution"),
            include_empty_config_profiles=True,
        )
        payload = _collect_changed_payload(current_payload, updated_payload)
    else:
        payload = _build_app_install_payload(
            client,
            renderer,
            name=provided.get("name"),
            display_name=provided.get("display_name"),
            application=provided.get("application"),
            device=str(resolved_device_id),
            version=provided.get("version"),
            deployment_config=provided.get("deployment_config"),
            config_profile_ids=provided.get("config_profile_ids"),
            solution=provided.get("solution"),
            include_empty_config_profiles="config_profile_ids" in provided,
        )
        payload.pop("device_id", None)

    if not payload:
        print("No changes submitted.")
        return

    with renderer.loading("Updating application installation..."):
        response = client.app_installs.partial(str(resolved_id), body=payload)

    renderer.render(response)


@device_app.command(name="archive")
def device_archive(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to archive."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Archive an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="archive app install on")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="archive",
    )

    with renderer.loading("Archiving application installation..."):
        response = client.app_installs.archive(str(resolved_id))

    renderer.render(response)


@device_app.command(name="unarchive")
def device_unarchive(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to unarchive."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Unarchive an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="unarchive app install on")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="unarchive",
        archived=True,
    )

    with renderer.loading("Unarchiving application installation..."):
        response = client.app_installs.unarchive(str(resolved_id))

    renderer.render(response)


@device_app.command(name="delete")
def device_delete(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to delete."),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Delete without confirmation.")
    ] = False,
    _profile: ProfileAnnotation = None,
):
    """Permanently delete an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="delete app install on")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="delete",
        archived=None,
    )

    if not yes:
        typer.confirm(
            f"Permanently delete app install {resolved_id}?",
            abort=True,
        )

    with renderer.loading("Deleting application installation..."):
        client.app_installs.delete(str(resolved_id))

    print(f"Deleted app install {resolved_id}.")


@device_app.command(name="deploy")
def device_deploy(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to deploy."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Create a deployment for an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="deploy app install on")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="deploy",
    )

    with renderer.loading("Creating application deployment..."):
        response = client.app_installs.deployments_create(str(resolved_id))

    renderer.render(response)


@device_app.command(name="sync-config-profiles")
def device_sync_config_profiles(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to sync."),
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to replace config profiles.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Sync config profiles for an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="sync app install config profiles on")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="sync config profiles for",
    )

    with renderer.loading("Loading current application installation..."):
        current_install = client.app_installs.retrieve(str(resolved_id))
    payload = _current_install_payload(current_install)
    payload["device_id"] = int(resolved_device_id)
    if config_profile_ids is not None:
        payload["config_profile_ids"] = config_profile_ids

    with renderer.loading("Syncing config profiles..."):
        response = client.app_installs.sync_config_profiles(
            str(resolved_id),
            body=payload,
        )

    renderer.render(response)


@device_app.command(name="deployments")
def device_deployments(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name."),
    ] = None,
    ordering: Annotated[
        str | None, typer.Option(help="Sort expression passed directly to the API.")
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    _profile: ProfileAnnotation = None,
):
    """List deployments for an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="list app install deployments on")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="list deployments for",
    )

    with renderer.loading("Loading application deployments..."):
        response = client.app_installs.deployments_list(
            parent_lookup_app_install=str(resolved_id),
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
        )

    renderer.render_list(response)


@device_app.command(name="deployment")
def device_deployment(
    device_id: Annotated[str | None, typer.Argument(help="Device ID or exact display name/name.")],
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name."),
    ],
    deployment_id: Annotated[str, typer.Argument(help="Deployment ID to retrieve.")],
    _profile: ProfileAnnotation = None,
):
    """Get a deployment for an application installation on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(client, renderer, device_id, action="get app install deployment on")
    resolved_id = _resolve_device_scoped_app_install(
        client,
        renderer,
        device_id=str(resolved_device_id),
        app_install=app_install,
        action="get deployment for",
    )

    with renderer.loading("Loading application deployment..."):
        response = client.app_installs.deployments_retrieve(
            id=str(deployment_id),
            parent_lookup_app_install=str(resolved_id),
        )

    renderer.render(response)


@application_app.command(name="list")
def application_list(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    archived: Annotated[
        str | None,
        typer.Option(
            help="Filter by archived status. Accepted values: true, false, 1, 0, yes, no."
        ),
    ] = None,
    device: Annotated[
        str | None, typer.Option(help="Filter by device identifier.")
    ] = None,
    display_name: Annotated[
        str | None, typer.Option(help="Filter by exact display name.")
    ] = None,
    display_name_contains: Annotated[
        str | None,
        typer.Option(
            "--display-name-contains", help="Filter by display name substring."
        ),
    ] = None,
    display_name_icontains: Annotated[
        str | None,
        typer.Option(
            "--display-name-icontains",
            help="Filter by case-insensitive display name substring.",
        ),
    ] = None,
    id: Annotated[int | None, typer.Option(help="Filter by app install ID.")] = None,
    name: Annotated[str | None, typer.Option(help="Filter by exact name.")] = None,
    name_contains: Annotated[
        str | None, typer.Option("--name-contains", help="Filter by name substring.")
    ] = None,
    name_icontains: Annotated[
        str | None,
        typer.Option(
            "--name-icontains", help="Filter by case-insensitive name substring."
        ),
    ] = None,
    ordering: Annotated[
        str | None, typer.Option(help="Sort expression passed directly to the API.")
    ] = None,
    organisation: Annotated[
        str | None, typer.Option(help="Filter by organisation identifier.")
    ] = None,
    organisation_isnull: Annotated[
        str | None,
        typer.Option(
            "--organisation-isnull",
            help="Filter by whether organisation is null. Accepted values: true, false, 1, 0, yes, no.",
        ),
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    solution: Annotated[
        str | None, typer.Option(help="Filter by solution identifier.")
    ] = None,
    status: Annotated[
        str | None, typer.Option(help="Filter by install status.")
    ] = None,
    template: Annotated[
        str | None, typer.Option(help="Filter by template identifier.")
    ] = None,
    version: Annotated[
        str | None, typer.Option(help="Filter by exact version.")
    ] = None,
    version_contains: Annotated[
        str | None,
        typer.Option("--version-contains", help="Filter by version substring."),
    ] = None,
    version_icontains: Annotated[
        str | None,
        typer.Option(
            "--version-icontains",
            help="Filter by case-insensitive version substring.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """List installations for an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="list installs for",
    )
    list_for_application(
        application_id=str(resolved_application_id),
        client=client,
        renderer=renderer,
        archived=archived,
        device=device,
        display_name=display_name,
        display_name_contains=display_name_contains,
        display_name_icontains=display_name_icontains,
        id=id,
        name=name,
        name_contains=name_contains,
        name_icontains=name_icontains,
        ordering=ordering,
        organisation=organisation,
        organisation_isnull=organisation_isnull,
        page=page,
        per_page=per_page,
        search=search,
        solution=solution,
        status=status,
        template=template,
        version=version,
        version_contains=version_contains,
        version_icontains=version_icontains,
    )


def _resolve_application_scoped_app_install(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    application_id: str,
    app_install: str | None,
    action: str,
    archived: bool | None = False,
) -> int:
    return _resolve_application_app_install_id(
        client,
        renderer,
        application_id=application_id,
        action=action,
        lookup=app_install,
        archived=archived,
    )


@application_app.command(name="create")
def application_create(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    display_name: Annotated[
        str | None,
        typer.Option("--display-name", help="Display name. Required by the API."),
    ] = None,
    name: Annotated[str | None, typer.Option(help="Install name.")] = None,
    device: Annotated[
        str | None,
        typer.Option(
            help="Device ID or exact display name/name.",
            autocompletion=_device_autocomplete(),
        ),
    ] = None,
    version: Annotated[str | None, typer.Option(help="Application version.")] = None,
    deployment_config: Annotated[
        str | None, typer.Option("--deployment-config", help="Deployment config JSON.")
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to set multiple config profiles.",
        ),
    ] = None,
    solution: Annotated[
        str | None,
        typer.Option(
            help="Solution ID or exact name.",
            autocompletion=_solution_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Create an application installation for an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="create an install for",
    )
    values = {
        "display_name": display_name,
        "name": name,
        "application": str(resolved_application_id),
        "device": device,
        "version": version,
        "deployment_config": deployment_config,
        "config_profile_ids": config_profile_ids,
        "solution": solution,
    }

    if not values["display_name"] or not values["device"]:
        values = _prompt_create_values(
            client,
            renderer,
            values,
            include_application=False,
        )
        values["application"] = str(resolved_application_id)

    payload = _build_app_install_payload(client, renderer, **values)
    for key, option_name in (
        ("display_name", "--display-name"),
        ("application_id", "application_id"),
        ("device_id", "--device"),
    ):
        if payload.get(key) is None:
            raise typer.BadParameter(
                f"{option_name} is required.", param_hint=option_name
            )

    with renderer.loading("Creating application installation..."):
        response = client.app_installs.create(body=payload)

    renderer.render(response)


@application_app.command(name="get")
def application_get(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Get an application installation for an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="get install from",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="get",
    )

    with renderer.loading("Loading application installation..."):
        response = client.app_installs.retrieve(str(resolved_id))

    renderer.render(response)


@application_app.command(name="update")
def application_update(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to update."),
    ] = None,
    display_name: Annotated[
        str | None, typer.Option("--display-name", help="Display name.")
    ] = None,
    name: Annotated[str | None, typer.Option(help="Install name.")] = None,
    device: Annotated[
        str | None,
        typer.Option(
            help="Device ID or exact display name/name.",
            autocompletion=_device_autocomplete(),
        ),
    ] = None,
    version: Annotated[str | None, typer.Option(help="Application version.")] = None,
    deployment_config: Annotated[
        str | None, typer.Option("--deployment-config", help="Deployment config JSON.")
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to replace config profiles.",
        ),
    ] = None,
    solution: Annotated[
        str | None,
        typer.Option(
            help="Solution ID or exact name.",
            autocompletion=_solution_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Update an application installation for an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="update install on",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="update",
    )

    provided = {
        "display_name": display_name,
        "name": name,
        "device": device,
        "version": version,
        "deployment_config": deployment_config,
        "config_profile_ids": config_profile_ids,
        "solution": solution,
    }
    provided = {key: value for key, value in provided.items() if value is not None}

    if not provided:
        with renderer.loading("Loading current application installation..."):
            current_install = client.app_installs.retrieve(str(resolved_id))
        current_payload = _current_install_payload(current_install)
        prompted = _prompt_update_values(
            client,
            renderer,
            current_payload,
            include_application=False,
        )
        prompted["application"] = str(resolved_application_id)
        updated_payload = _build_app_install_payload(
            client,
            renderer,
            name=prompted.get("name"),
            display_name=prompted.get("display_name"),
            application=prompted.get("application"),
            device=prompted.get("device"),
            version=prompted.get("version"),
            deployment_config=prompted.get("deployment_config"),
            config_profile_ids=prompted.get("config_profile_ids"),
            solution=prompted.get("solution"),
            include_empty_config_profiles=True,
        )
        payload = _collect_changed_payload(current_payload, updated_payload)
    else:
        payload = _build_app_install_payload(
            client,
            renderer,
            name=provided.get("name"),
            display_name=provided.get("display_name"),
            application=str(resolved_application_id),
            device=provided.get("device"),
            version=provided.get("version"),
            deployment_config=provided.get("deployment_config"),
            config_profile_ids=provided.get("config_profile_ids"),
            solution=provided.get("solution"),
            include_empty_config_profiles="config_profile_ids" in provided,
        )
        payload.pop("application_id", None)

    if not payload:
        print("No changes submitted.")
        return

    with renderer.loading("Updating application installation..."):
        response = client.app_installs.partial(str(resolved_id), body=payload)

    renderer.render(response)


@application_app.command(name="archive")
def application_archive(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to archive."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Archive an application installation for an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="archive install on",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="archive",
    )

    with renderer.loading("Archiving application installation..."):
        response = client.app_installs.archive(str(resolved_id))

    renderer.render(response)


@application_app.command(name="unarchive")
def application_unarchive(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to unarchive."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Unarchive an application installation for an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="unarchive install on",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="unarchive",
        archived=True,
    )

    with renderer.loading("Unarchiving application installation..."):
        response = client.app_installs.unarchive(str(resolved_id))

    renderer.render(response)


@application_app.command(name="delete")
def application_delete(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to delete."),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Delete without confirmation.")
    ] = False,
    _profile: ProfileAnnotation = None,
):
    """Permanently delete an application installation for an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="delete install from",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="delete",
        archived=None,
    )

    if not yes:
        typer.confirm(
            f"Permanently delete app install {resolved_id}?",
            abort=True,
        )

    with renderer.loading("Deleting application installation..."):
        client.app_installs.delete(str(resolved_id))

    print(f"Deleted app install {resolved_id}.")


@application_app.command(name="deploy")
def application_deploy(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to deploy."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Create a deployment for an application installation on an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="deploy install on",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="deploy",
    )

    with renderer.loading("Creating application deployment..."):
        response = client.app_installs.deployments_create(str(resolved_id))

    renderer.render(response)


@application_app.command(name="sync-config-profiles")
def application_sync_config_profiles(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name to sync."),
    ] = None,
    config_profile_ids: Annotated[
        list[int] | None,
        typer.Option(
            "--config-profile-id",
            help="Config profile ID. Repeat to replace config profiles.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Sync config profiles for an application installation on an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="sync install config profiles on",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="sync config profiles for",
    )

    with renderer.loading("Loading current application installation..."):
        current_install = client.app_installs.retrieve(str(resolved_id))
    payload = _current_install_payload(current_install)
    payload["application_id"] = int(resolved_application_id)
    if config_profile_ids is not None:
        payload["config_profile_ids"] = config_profile_ids

    with renderer.loading("Syncing config profiles..."):
        response = client.app_installs.sync_config_profiles(
            str(resolved_id),
            body=payload,
        )

    renderer.render(response)


@application_app.command(name="deployments")
def application_deployments(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ] = None,
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name."),
    ] = None,
    ordering: Annotated[
        str | None, typer.Option(help="Sort expression passed directly to the API.")
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    _profile: ProfileAnnotation = None,
):
    """List deployments for an application installation on an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="list install deployments on",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="list deployments for",
    )

    with renderer.loading("Loading application deployments..."):
        response = client.app_installs.deployments_list(
            parent_lookup_app_install=str(resolved_id),
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
        )

    renderer.render_list(response)


@application_app.command(name="deployment")
def application_deployment(
    application_id: Annotated[
        str | None,
        typer.Argument(help="Application ID or exact display name/name."),
    ],
    app_install: Annotated[
        str | None,
        typer.Argument(help="Application install ID or exact display name/name."),
    ],
    deployment_id: Annotated[str, typer.Argument(help="Deployment ID to retrieve.")],
    _profile: ProfileAnnotation = None,
):
    """Get a deployment for an application installation on an application."""
    _ = _profile
    client, renderer = get_state()
    resolved_application_id = _resolve_application_context_id(
        client,
        renderer,
        application_id,
        action="get install deployment on",
    )
    resolved_id = _resolve_application_scoped_app_install(
        client,
        renderer,
        application_id=str(resolved_application_id),
        app_install=app_install,
        action="get deployment for",
    )

    with renderer.loading("Loading application deployment..."):
        response = client.app_installs.deployments_retrieve(
            id=str(deployment_id),
            parent_lookup_app_install=str(resolved_id),
        )

    renderer.render(response)


def list_for_application(
    *,
    application_id: str,
    client: "ControlClient",
    renderer: "RendererBase",
    archived: str | None = None,
    device: str | None = None,
    display_name: str | None = None,
    display_name_contains: str | None = None,
    display_name_icontains: str | None = None,
    id: int | None = None,
    name: str | None = None,
    name_contains: str | None = None,
    name_icontains: str | None = None,
    ordering: str | None = None,
    organisation: str | None = None,
    organisation_isnull: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    search: str | None = None,
    solution: str | None = None,
    status: str | None = None,
    template: str | None = None,
    version: str | None = None,
    version_contains: str | None = None,
    version_icontains: str | None = None,
) -> None:
    kwargs = _install_list_kwargs(
        archived=archived,
        display_name=display_name,
        display_name_contains=display_name_contains,
        display_name_icontains=display_name_icontains,
        id=id,
        name=name,
        name_contains=name_contains,
        name_icontains=name_icontains,
        ordering=ordering,
        organisation=organisation,
        organisation_isnull=organisation_isnull,
        page=page,
        per_page=per_page,
        search=search,
        solution=solution,
        status=status,
        template=template,
        version=version,
        version_contains=version_contains,
        version_icontains=version_icontains,
    )
    with renderer.loading("Loading application installations..."):
        response = client.applications.installs_list(
            parent_lookup_application=str(application_id),
            device=device,
            **kwargs,
        )
    renderer.render_list(response)


def list_for_device(
    *,
    device_id: str,
    client: "ControlClient",
    renderer: "RendererBase",
    application: str | None = None,
    archived: str | None = None,
    display_name: str | None = None,
    display_name_contains: str | None = None,
    display_name_icontains: str | None = None,
    id: int | None = None,
    name: str | None = None,
    name_contains: str | None = None,
    name_icontains: str | None = None,
    ordering: str | None = None,
    organisation: str | None = None,
    organisation_isnull: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    search: str | None = None,
    solution: str | None = None,
    status: str | None = None,
    template: str | None = None,
    version: str | None = None,
    version_contains: str | None = None,
    version_icontains: str | None = None,
) -> None:
    kwargs = _install_list_kwargs(
        archived=archived,
        display_name=display_name,
        display_name_contains=display_name_contains,
        display_name_icontains=display_name_icontains,
        id=id,
        name=name,
        name_contains=name_contains,
        name_icontains=name_icontains,
        ordering=ordering,
        organisation=organisation,
        organisation_isnull=organisation_isnull,
        page=page,
        per_page=per_page,
        search=search,
        solution=solution,
        status=status,
        template=template,
        version=version,
        version_contains=version_contains,
        version_icontains=version_icontains,
    )
    with renderer.loading("Loading device application installations..."):
        response = client.devices.app_installs_list(
            parent_lookup_device=str(device_id),
            application=application,
            **kwargs,
        )
    renderer.render_list(response)
