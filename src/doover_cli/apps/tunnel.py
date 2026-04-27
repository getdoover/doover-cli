from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import typer
from pydoover.models.control import Device, Tunnel

from ..utils.api import (
    ProfileAnnotation,
)
from ..utils.crud import (
    LookupChoice,
    build_create_command,
    build_update_command,
    prompt_resource,
    resource_autocomplete,
)
from ..utils.crud.lookup import resolve_resource_lookup
from ..utils.crud.prompting import (
    build_prompt_field_for_spec,
    normalize_prompted_value,
)
from ..utils.crud.schema import get_model_field_specs
from ..utils.crud.values import (
    build_request_payload,
    collect_changed_model_values,
    extract_model_values,
    normalize_model_values,
)
from ..utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from ..renderer import RendererBase


app = typer.Typer(no_args_is_help=True)
device_app = typer.Typer(no_args_is_help=True)

_TUNNEL_LABEL_ATTRS = ("name",)
_DEVICE_LABEL_ATTRS = ("display_name", "name")


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


def _tunnel_autocomplete() -> object:
    return resource_autocomplete(
        Tunnel,
        archived=None,
        ordering="name",
        label_attrs=_TUNNEL_LABEL_ATTRS,
        searchable_attrs=_TUNNEL_LABEL_ATTRS,
    )


def _resolve_tunnel_id(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    action: str,
    lookup: str | None,
) -> int:
    return prompt_resource(
        Tunnel,
        client,
        renderer,
        action=action,
        lookup=lookup,
        archived=None,
        ordering="name",
        label_attrs=_TUNNEL_LABEL_ATTRS,
        searchable_attrs=_TUNNEL_LABEL_ATTRS,
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


def _choice_for_tunnel(resource: Any) -> LookupChoice | None:
    raw_id = _resource_value(resource, "id")
    if raw_id is None:
        return None
    resource_id = int(raw_id)
    name_value = _resource_value(resource, "name") or f"Tunnel {resource_id}"
    label = f"{name_value} ({resource_id})"
    search_values = [label, str(resource_id), str(name_value)]
    return LookupChoice(
        id=resource_id,
        label=label,
        search_values=tuple(dict.fromkeys(search_values)),
        field_values={"name": name_value},
    )


def _load_device_tunnel_choices(
    client: "ControlClient",
    *,
    device_id: str,
) -> list[LookupChoice]:
    page_num = 1
    choices: list[LookupChoice] = []

    while True:
        page = client.devices.tunnels_list(
            parent_lookup_device=str(device_id),
            ordering="name",
            page=page_num,
            per_page=100,
        )
        for resource in _page_results(page):
            choice = _choice_for_tunnel(resource)
            if choice is not None:
                choices.append(choice)

        count = _page_count(page)
        if not _page_next(page) or (count is not None and len(choices) >= count):
            break
        page_num += 1

    return choices


def _prompt_tunnel_values(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    method: str,
    initial_values: dict[str, Any],
) -> dict[str, Any]:
    """Prompt for Tunnel fields, skipping `device` since it comes from the URL."""
    specs = [
        spec for spec in get_model_field_specs(Tunnel, method) if spec.name != "device"
    ]
    prompted_values = dict(initial_values)
    prompt_fields = [
        build_prompt_field_for_spec(client, spec, prompted_values.get(spec.name))
        for spec in specs
    ]
    prompted_answers = renderer.prompt_fields(prompt_fields)
    for spec, field in zip(specs, prompt_fields):
        prompted_values[spec.name] = normalize_prompted_value(
            spec, field, prompted_answers.get(spec.name)
        )
    return prompted_values


def _resolve_device_tunnel_id(
    client: "ControlClient",
    renderer: "RendererBase",
    *,
    device_id: str,
    action: str,
    lookup: str | None,
) -> int:
    model_label = "tunnel"
    if lookup is not None and lookup.strip().lstrip("-").isdigit():
        return int(lookup.strip())

    choices = _load_device_tunnel_choices(client, device_id=device_id)
    if lookup is not None:
        return resolve_resource_lookup(choices, lookup, model_label=model_label)

    from ..utils.crud import Field

    field = Field(
        key="resource_id",
        label=f"Tunnel to {action}",
        kind="resource",
        required=True,
        resource_model_cls=Tunnel,
        resource_model_label=model_label,
        resource_lookup_choices=choices,
        match_middle=True,
        allow_blank=False,
    )
    prompted = renderer.prompt_fields([field])
    prompt_value = prompted.get("resource_id")
    if prompt_value is None:
        raise typer.BadParameter(
            "Please provide a tunnel ID or name.",
            param_hint="tunnel",
        )
    return resolve_resource_lookup(choices, str(prompt_value), model_label=model_label)


# ---------------------------------------------------------------------------
# Top-level: doover tunnel ...
# ---------------------------------------------------------------------------


@app.command(name="list")
def list_(
    ordering: Annotated[
        str | None,
        typer.Option(
            help="Sort expression passed directly to the API, for example name or -name.",
        ),
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    _profile: ProfileAnnotation = None,
):
    """List tunnels across all devices you can access."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading tunnels..."):
        response = client.tunnels.list(
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
        )

    renderer.render_list(response)


@app.command()
def get(
    tunnel: Annotated[
        str | None,
        typer.Argument(
            help="Tunnel ID or exact name to retrieve.",
            autocompletion=_tunnel_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Get a tunnel by ID or name."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_tunnel_id(
        client,
        renderer,
        action="get",
        lookup=tunnel,
    )

    with renderer.loading("Loading tunnel..."):
        response = client.tunnels.retrieve(str(resolved_id))

    renderer.render(response)


create = build_create_command(
    model_cls=Tunnel,
    command_help="Create a tunnel.",
    get_state=lambda: get_state(),
)
app.command()(create)


update = build_update_command(
    model_cls=Tunnel,
    command_help="Update a tunnel.",
    get_state=lambda: get_state(),
    resource_id_param_name="tunnel",
    resource_id_help="Tunnel ID or exact name to update.",
)
app.command()(update)


@app.command()
def delete(
    tunnel: Annotated[
        str | None,
        typer.Argument(
            help="Tunnel ID or exact name to delete.",
            autocompletion=_tunnel_autocomplete(),
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Delete without confirmation.")
    ] = False,
    _profile: ProfileAnnotation = None,
):
    """Permanently delete a tunnel."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_tunnel_id(
        client,
        renderer,
        action="delete",
        lookup=tunnel,
    )

    if not yes:
        typer.confirm(f"Permanently delete tunnel {resolved_id}?", abort=True)

    with renderer.loading("Deleting tunnel..."):
        client.tunnels.delete(str(resolved_id))

    print(f"Deleted tunnel {resolved_id}.")


@app.command()
def activate(
    tunnel: Annotated[
        str | None,
        typer.Argument(
            help="Tunnel ID or exact name to activate.",
            autocompletion=_tunnel_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Activate a tunnel (open the underlying connection on the device)."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_tunnel_id(
        client,
        renderer,
        action="activate",
        lookup=tunnel,
    )

    with renderer.loading("Activating tunnel..."):
        response = client.tunnels.activate(str(resolved_id), body={})

    renderer.render(response)


@app.command()
def deactivate(
    tunnel: Annotated[
        str | None,
        typer.Argument(
            help="Tunnel ID or exact name to deactivate.",
            autocompletion=_tunnel_autocomplete(),
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Deactivate a tunnel (close the underlying connection on the device)."""
    _ = _profile
    client, renderer = get_state()

    resolved_id = _resolve_tunnel_id(
        client,
        renderer,
        action="deactivate",
        lookup=tunnel,
    )

    with renderer.loading("Deactivating tunnel..."):
        response = client.tunnels.deactivate(str(resolved_id), body={})

    renderer.render(response)


# ---------------------------------------------------------------------------
# Device-scoped: doover device tunnels ...
# ---------------------------------------------------------------------------


@device_app.command(name="list")
def device_list(
    device_id: Annotated[
        str | None,
        typer.Argument(help="Device ID or exact display name/name."),
    ] = None,
    ordering: Annotated[
        str | None,
        typer.Option(help="Sort expression passed directly to the API."),
    ] = None,
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    _profile: ProfileAnnotation = None,
):
    """List tunnels for a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client, renderer, device_id, action="list tunnels for"
    )

    with renderer.loading("Loading tunnels..."):
        response = client.devices.tunnels_list(
            parent_lookup_device=str(resolved_device_id),
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
        )

    renderer.render_list(response)


@device_app.command(name="get")
def device_get(
    device_id: Annotated[
        str | None, typer.Argument(help="Device ID or exact display name/name.")
    ] = None,
    tunnel: Annotated[
        str | None,
        typer.Argument(help="Tunnel ID or exact name to retrieve."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Get a tunnel on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client, renderer, device_id, action="get tunnel from"
    )
    resolved_id = _resolve_device_tunnel_id(
        client,
        renderer,
        device_id=str(resolved_device_id),
        action="get",
        lookup=tunnel,
    )

    with renderer.loading("Loading tunnel..."):
        response = client.devices.tunnels_retrieve(
            id=str(resolved_id),
            parent_lookup_device=str(resolved_device_id),
        )

    renderer.render(response)


@device_app.command(name="create")
def device_create(
    device_id: Annotated[
        str | None, typer.Argument(help="Device ID or exact display name/name.")
    ] = None,
    name: Annotated[
        str | None, typer.Option(help="Tunnel name. Required by the API.")
    ] = None,
    hostname: Annotated[
        str | None, typer.Option(help="Target hostname or IP. Required by the API.")
    ] = None,
    port: Annotated[
        int | None, typer.Option(help="Target port. Required by the API.")
    ] = None,
    protocol: Annotated[
        str | None,
        typer.Option(help="Protocol. One of: tcp, rtsp, http, https. Required."),
    ] = None,
    username: Annotated[str | None, typer.Option(help="Optional username.")] = None,
    password: Annotated[str | None, typer.Option(help="Optional password.")] = None,
    timeout: Annotated[
        int | None, typer.Option(help="Tunnel timeout in seconds.")
    ] = None,
    ip_restricted: Annotated[
        bool | None,
        typer.Option(
            "--ip-restricted/--no-ip-restricted",
            help="Restrict the tunnel to your current IP / whitelist.",
        ),
    ] = None,
    disable_tls_verification: Annotated[
        bool | None,
        typer.Option(
            "--disable-tls-verification/--verify-tls",
            help="Disable TLS verification on the tunnel target.",
        ),
    ] = None,
    is_favourite: Annotated[
        bool | None,
        typer.Option(
            "--favourite/--no-favourite",
            help="Mark this tunnel as a favourite.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Create a tunnel on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client, renderer, device_id, action="create a tunnel on"
    )

    provided = {
        key: value
        for key, value in {
            "name": name,
            "hostname": hostname,
            "port": port,
            "protocol": protocol,
            "username": username,
            "password": password,
            "timeout": timeout,
            "ip_restricted": ip_restricted,
            "disable_tls_verification": disable_tls_verification,
            "is_favourite": is_favourite,
        }.items()
        if value is not None
    }
    values = normalize_model_values(Tunnel, "POST", provided)

    missing_required = any(
        spec.required and spec.name != "device" and values.get(spec.name) is None
        for spec in get_model_field_specs(Tunnel, "POST")
    )
    if missing_required:
        values = _prompt_tunnel_values(
            client, renderer, method="POST", initial_values=values
        )

    values = {
        key: value
        for key, value in values.items()
        if value is not None and key != "device"
    }
    payload = build_request_payload(Tunnel, "POST", values)
    payload.pop("device_id", None)

    with renderer.loading("Creating tunnel..."):
        response = client.devices.tunnels_create(
            parent_lookup_device=str(resolved_device_id),
            body=payload,
        )

    renderer.render(response)


@device_app.command(name="update")
def device_update(
    device_id: Annotated[
        str | None, typer.Argument(help="Device ID or exact display name/name.")
    ] = None,
    tunnel: Annotated[
        str | None,
        typer.Argument(help="Tunnel ID or exact name to update."),
    ] = None,
    name: Annotated[str | None, typer.Option(help="Tunnel name.")] = None,
    hostname: Annotated[str | None, typer.Option(help="Target hostname or IP.")] = None,
    port: Annotated[int | None, typer.Option(help="Target port.")] = None,
    username: Annotated[str | None, typer.Option(help="Username.")] = None,
    password: Annotated[str | None, typer.Option(help="Password.")] = None,
    timeout: Annotated[int | None, typer.Option(help="Timeout in seconds.")] = None,
    ip_restricted: Annotated[
        bool | None,
        typer.Option("--ip-restricted/--no-ip-restricted", help="IP restriction."),
    ] = None,
    disable_tls_verification: Annotated[
        bool | None,
        typer.Option(
            "--disable-tls-verification/--verify-tls",
            help="Disable TLS verification.",
        ),
    ] = None,
    is_favourite: Annotated[
        bool | None,
        typer.Option("--favourite/--no-favourite", help="Mark as favourite."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Update a tunnel on a device. Protocol and device cannot be changed after creation."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client, renderer, device_id, action="update tunnel on"
    )
    resolved_id = _resolve_device_tunnel_id(
        client,
        renderer,
        device_id=str(resolved_device_id),
        action="update",
        lookup=tunnel,
    )

    provided = {
        key: value
        for key, value in {
            "name": name,
            "hostname": hostname,
            "port": port,
            "username": username,
            "password": password,
            "timeout": timeout,
            "ip_restricted": ip_restricted,
            "disable_tls_verification": disable_tls_verification,
            "is_favourite": is_favourite,
        }.items()
        if value is not None
    }
    normalized = normalize_model_values(Tunnel, "PATCH", provided)

    if normalized:
        values_to_submit = normalized
    else:
        with renderer.loading("Loading current tunnel..."):
            current = client.devices.tunnels_retrieve(
                id=str(resolved_id),
                parent_lookup_device=str(resolved_device_id),
            )
        current_values = extract_model_values(Tunnel, "PATCH", current)
        prompted = _prompt_tunnel_values(
            client, renderer, method="PATCH", initial_values=current_values
        )
        values_to_submit = collect_changed_model_values(
            Tunnel, "PATCH", current_values, prompted
        )

    if not values_to_submit:
        print("No changes submitted.")
        return

    payload = build_request_payload(Tunnel, "PATCH", values_to_submit)
    payload.pop("device_id", None)

    with renderer.loading("Updating tunnel..."):
        response = client.devices.tunnels_partial(
            id=str(resolved_id),
            parent_lookup_device=str(resolved_device_id),
            body=payload,
        )

    renderer.render(response)


@device_app.command(name="delete")
def device_delete(
    device_id: Annotated[
        str | None, typer.Argument(help="Device ID or exact display name/name.")
    ] = None,
    tunnel: Annotated[
        str | None,
        typer.Argument(help="Tunnel ID or exact name to delete."),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Delete without confirmation.")
    ] = False,
    _profile: ProfileAnnotation = None,
):
    """Permanently delete a tunnel on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client, renderer, device_id, action="delete tunnel on"
    )
    resolved_id = _resolve_device_tunnel_id(
        client,
        renderer,
        device_id=str(resolved_device_id),
        action="delete",
        lookup=tunnel,
    )

    if not yes:
        typer.confirm(f"Permanently delete tunnel {resolved_id}?", abort=True)

    with renderer.loading("Deleting tunnel..."):
        client.tunnels.delete(str(resolved_id))

    print(f"Deleted tunnel {resolved_id}.")


@device_app.command(name="activate")
def device_activate(
    device_id: Annotated[
        str | None, typer.Argument(help="Device ID or exact display name/name.")
    ] = None,
    tunnel: Annotated[
        str | None,
        typer.Argument(help="Tunnel ID or exact name to activate."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Activate a tunnel on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client, renderer, device_id, action="activate tunnel on"
    )
    resolved_id = _resolve_device_tunnel_id(
        client,
        renderer,
        device_id=str(resolved_device_id),
        action="activate",
        lookup=tunnel,
    )

    with renderer.loading("Activating tunnel..."):
        response = client.tunnels.activate(str(resolved_id), body={})

    renderer.render(response)


@device_app.command(name="deactivate")
def device_deactivate(
    device_id: Annotated[
        str | None, typer.Argument(help="Device ID or exact display name/name.")
    ] = None,
    tunnel: Annotated[
        str | None,
        typer.Argument(help="Tunnel ID or exact name to deactivate."),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Deactivate a tunnel on a device."""
    _ = _profile
    client, renderer = get_state()
    resolved_device_id = _resolve_device_context_id(
        client, renderer, device_id, action="deactivate tunnel on"
    )
    resolved_id = _resolve_device_tunnel_id(
        client,
        renderer,
        device_id=str(resolved_device_id),
        action="deactivate",
        lookup=tunnel,
    )

    with renderer.loading("Deactivating tunnel..."):
        response = client.tunnels.deactivate(str(resolved_id), body={})

    renderer.render(response)
