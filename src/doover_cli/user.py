from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any

import typer
from pydoover.models.control import Organisation

from .utils.api import ProfileAnnotation
from .utils.crud import parse_optional_bool, prompt_resource, resource_autocomplete
from .utils.crud.lookup import load_control_model_choices
from .utils.crud.prompting import Field
from .utils.state import state

if TYPE_CHECKING:
    from pydoover.api import ControlClient
    from .renderer import RendererBase


users_app = typer.Typer(no_args_is_help=True)
org_app = typer.Typer(no_args_is_help=True)
org_users_app = typer.Typer(no_args_is_help=True)
org_pending_users_app = typer.Typer(no_args_is_help=True)
org_roles_app = typer.Typer(no_args_is_help=True)

org_app.add_typer(org_users_app, name="users", help="Manage organisation users.")
org_users_app.add_typer(
    org_pending_users_app,
    name="pending",
    help="Manage pending organisation users.",
)
org_app.add_typer(org_roles_app, name="roles", help="Manage organisation roles.")

_ORGANISATION_COMPLETION = resource_autocomplete(
    Organisation,
    archived=False,
    ordering="name",
    label_attrs=("name",),
    searchable_attrs=("name",),
)


def get_state() -> tuple["ControlClient", "RendererBase"]:
    session = state.session
    return session.get_control_client(), state.renderer


def _json_value(value: str, option_name: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"{option_name} must be valid JSON.",
            param_hint=option_name,
        ) from exc


def _maybe_payload(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _custom_data_payload(custom_data: str | None) -> dict[str, Any]:
    if custom_data is None:
        return {}
    return {"custom_data": _json_value(custom_data, "--custom-data")}


def _group_assignment(value: str) -> dict[str, int]:
    parsed: Any
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        separators = (":", ",")
        for separator in separators:
            if separator in value:
                group_id, role_id = (part.strip() for part in value.split(separator, 1))
                break
        else:
            raise typer.BadParameter(
                "Group assignments must be JSON objects or GROUP_ID:ROLE_ID pairs.",
                param_hint="--add-to-group",
            )
        parsed = {"group_id": group_id, "role_id": role_id}

    if not isinstance(parsed, dict):
        raise typer.BadParameter(
            "Group assignments must be JSON objects or GROUP_ID:ROLE_ID pairs.",
            param_hint="--add-to-group",
        )

    try:
        return {
            "group_id": int(parsed["group_id"]),
            "role_id": int(parsed["role_id"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise typer.BadParameter(
            "Group assignments must include integer group_id and role_id values.",
            param_hint="--add-to-group",
        ) from exc


def _group_assignments(values: list[str] | None) -> list[dict[str, int]] | None:
    if not values:
        return None
    return [_group_assignment(value) for value in values]


def _pending_user_payload(
    *,
    email: str,
    organisation_id: int,
    message: str | None,
) -> dict[str, Any]:
    return _maybe_payload(
        email=email,
        organisation_id=organisation_id,
        message=message,
    )


def _resolve_organisation_id(
    client: "ControlClient",
    renderer: "RendererBase",
    lookup: str | None,
) -> int:
    choices = load_control_model_choices(
        client,
        Organisation,
        archived=False,
        ordering="name",
        label_attrs=("name",),
        searchable_attrs=("name",),
        model_label="organisation",
    )
    if lookup is None:
        if not choices:
            raise typer.BadParameter(
                "No organisations are available for this account.",
                param_hint="organisation",
            )
        if len(choices) == 1:
            return choices[0].id

    return prompt_resource(
        Organisation,
        client,
        renderer,
        action="use",
        lookup=lookup,
        archived=False,
        ordering="name",
        label_attrs=("name",),
        searchable_attrs=("name",),
    )


def _resolve_org_context(
    lookup: str | None,
) -> tuple[int, "ControlClient", "RendererBase"]:
    client, renderer = get_state()
    return _resolve_organisation_id(client, renderer, lookup), client, renderer


def _prompt_required_text(
    renderer: "RendererBase",
    *,
    label: str,
    value: str | None,
    param_hint: str,
) -> str:
    if value is None:
        prompted = renderer.prompt_fields(
            [
                Field(
                    key=param_hint,
                    label=label,
                    kind="text",
                    required=True,
                    allow_blank=False,
                )
            ]
        )
        value = prompted.get(param_hint)
    if value is None or not str(value).strip():
        raise typer.BadParameter(f"{label} is required.", param_hint=param_hint)
    return str(value).strip()


def _prompt_required_int(
    renderer: "RendererBase",
    *,
    label: str,
    value: int | None,
    param_hint: str,
) -> int:
    if value is None:
        prompted = renderer.prompt_fields(
            [
                Field(
                    key=param_hint,
                    label=label,
                    kind="int",
                    required=True,
                    allow_blank=False,
                )
            ]
        )
        value = prompted.get(param_hint)
    if value is None or str(value).strip() == "":
        raise typer.BadParameter(f"{label} is required.", param_hint=param_hint)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(
            f"{label} must be an integer.",
            param_hint=param_hint,
        ) from exc


def _prompt_optional_text(
    renderer: "RendererBase",
    *,
    label: str,
    value: str | None,
    param_hint: str,
) -> str | None:
    if value is None:
        prompted = renderer.prompt_fields(
            [
                Field(
                    key=param_hint,
                    label=label,
                    kind="text",
                    required=False,
                    allow_blank=True,
                )
            ]
        )
        value = prompted.get(param_hint)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _create_pending_user(
    *,
    organisation_lookup: str | None,
    email: str | None,
    message: str | None,
) -> tuple["RendererBase", Any]:
    organisation_id, client, renderer = _resolve_org_context(organisation_lookup)
    email = _prompt_required_text(
        renderer,
        label="Email",
        value=email,
        param_hint="email",
    )
    message = _prompt_optional_text(
        renderer,
        label="Message",
        value=message,
        param_hint="message",
    )
    with renderer.loading("Inviting pending user..."):
        response = client.organisations.pending_users.create(
            body=_pending_user_payload(
                email=email,
                organisation_id=organisation_id,
                message=message,
            ),
            organisation_id=organisation_id,
        )
    return renderer, response


OrganisationArgument = Annotated[
    str | None,
    typer.Argument(
        help="Organisation ID or exact name. If omitted, the CLI will assume the only available organisation or prompt you to choose one.",
        autocompletion=_ORGANISATION_COMPLETION,
    ),
]


@users_app.command(name="list")
def list_users(
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
    """List users."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading users..."):
        response = client.users.list(
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
        )

    renderer.render_list(response)


@users_app.command()
def get(
    user_id: Annotated[str, typer.Argument(help="User ID to retrieve.")],
    _profile: ProfileAnnotation = None,
):
    """Get a user."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading user..."):
        response = client.users.retrieve(str(user_id))

    renderer.render(response)


@users_app.command()
def me(_profile: ProfileAnnotation = None):
    """Get the current user."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Loading current user..."):
        response = client.users.me()

    renderer.render(response)


@users_app.command()
def update(
    user_id: Annotated[str, typer.Argument(help="User ID to update.")],
    custom_data: Annotated[
        str | None,
        typer.Option(
            "--custom-data",
            help="JSON value for the user's custom_data field.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Update a user."""
    _ = _profile
    payload = _custom_data_payload(custom_data)
    if not payload:
        print("No changes submitted.")
        return

    client, renderer = get_state()
    with renderer.loading("Updating user..."):
        response = client.users.partial(str(user_id), body=payload)

    renderer.render(response)


@users_app.command()
def sync(
    user_id: Annotated[str, typer.Argument(help="User ID to sync.")],
    custom_data: Annotated[
        str | None,
        typer.Option(
            "--custom-data",
            help="Optional JSON value for the user's custom_data field.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Sync a user."""
    _ = _profile
    client, renderer = get_state()

    with renderer.loading("Syncing user..."):
        response = client.users.sync(str(user_id), body=_custom_data_payload(custom_data))

    renderer.render(response)


@org_users_app.command(name="list")
def list_org_users(
    organisation: OrganisationArgument = None,
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
    """List organisation users."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)

    with renderer.loading("Loading organisation users..."):
        response = client.organisations.users.list(
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
            organisation_id=organisation_id,
        )

    renderer.render_list(response)


@org_users_app.command(name="get")
def get_org_user(
    organisation: OrganisationArgument = None,
    user: Annotated[str, typer.Argument(help="Organisation user ID or email.")] = None,
    _profile: ProfileAnnotation = None,
):
    """Get an organisation user."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    user = _prompt_required_text(
        renderer,
        label="Organisation user ID or email",
        value=user,
        param_hint="user",
    )

    with renderer.loading("Loading organisation user..."):
        response = client.organisations.users.retrieve(
            str(user),
            organisation_id=organisation_id,
        )

    renderer.render(response)


@org_users_app.command(name="add")
def add_org_user(
    organisation: OrganisationArgument = None,
    email: Annotated[
        str,
        typer.Argument(help="Email address of the user to add to the organisation."),
    ] = None,
    role_id: Annotated[
        int,
        typer.Option("--role-id", help="Organisation role ID to assign."),
    ] = None,
    add_to_group: Annotated[
        list[str] | None,
        typer.Option(
            "--add-to-group",
            help="Group assignment as GROUP_ID:ROLE_ID or JSON. Repeat for multiple groups.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Add a user to the current organisation."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    email = _prompt_required_text(
        renderer,
        label="Email",
        value=email,
        param_hint="email",
    )
    role_id = _prompt_required_int(
        renderer,
        label="Role ID",
        value=role_id,
        param_hint="role_id",
    )
    payload = _maybe_payload(
        user_email=email,
        role_id=role_id,
        add_to_group=_group_assignments(add_to_group),
    )

    with renderer.loading("Adding organisation user..."):
        response = client.organisations.users.create(
            body=payload,
            organisation_id=organisation_id,
        )

    renderer.render(response)


@org_users_app.command(name="update")
def update_org_user(
    organisation: OrganisationArgument = None,
    user: Annotated[str, typer.Argument(help="Organisation user ID or email.")] = None,
    email: Annotated[
        str | None,
        typer.Option("--email", help="Updated email address for the organisation user."),
    ] = None,
    role_id: Annotated[
        int | None,
        typer.Option("--role-id", help="Updated organisation role ID."),
    ] = None,
    add_to_group: Annotated[
        list[str] | None,
        typer.Option(
            "--add-to-group",
            help="Group assignment as GROUP_ID:ROLE_ID or JSON. Repeat for multiple groups.",
        ),
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Update an organisation user."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    user = _prompt_required_text(
        renderer,
        label="Organisation user ID or email",
        value=user,
        param_hint="user",
    )
    payload = _maybe_payload(
        user_email=email,
        role_id=role_id,
        add_to_group=_group_assignments(add_to_group),
    )
    if not payload:
        print("No changes submitted.")
        return
    with renderer.loading("Updating organisation user..."):
        response = client.organisations.users.partial(
            str(user),
            body=payload,
            organisation_id=organisation_id,
        )

    renderer.render(response)


@org_users_app.command(name="remove")
def remove_org_user(
    organisation: OrganisationArgument = None,
    user: Annotated[str, typer.Argument(help="Organisation user ID or email.")] = None,
    _profile: ProfileAnnotation = None,
):
    """Remove a user from the current organisation."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    user = _prompt_required_text(
        renderer,
        label="Organisation user ID or email",
        value=user,
        param_hint="user",
    )

    with renderer.loading("Removing organisation user..."):
        client.organisations.users.delete(str(user), organisation_id=organisation_id)

    renderer.render({"removed": True, "user": str(user)})


@org_users_app.command(name="groups")
def list_org_user_groups(
    organisation: OrganisationArgument = None,
    user: Annotated[str, typer.Argument(help="Organisation user ID or email.")] = None,
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
    """List organisation group permissions for a user."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    user = _prompt_required_text(
        renderer,
        label="Organisation user ID or email",
        value=user,
        param_hint="user",
    )

    with renderer.loading("Loading organisation user groups..."):
        response = client.organisations.users.groups_list(
            parent_lookup_user=str(user),
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
            organisation_id=organisation_id,
        )

    renderer.render_list(response)


@org_pending_users_app.command(name="list")
def list_pending_users(
    organisation: OrganisationArgument = None,
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
    """List pending users."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)

    with renderer.loading("Loading pending users..."):
        response = client.organisations.pending_users.list(
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
            organisation_id=organisation_id,
        )

    renderer.render_list(response)


@org_pending_users_app.command(name="get")
def get_pending_user(
    organisation: OrganisationArgument = None,
    pending_user_id: Annotated[str, typer.Argument(help="Pending user ID.")] = None,
    _profile: ProfileAnnotation = None,
):
    """Get a pending user."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    pending_user_id = _prompt_required_text(
        renderer,
        label="Pending user ID",
        value=pending_user_id,
        param_hint="pending_user_id",
    )

    with renderer.loading("Loading pending user..."):
        response = client.organisations.pending_users.retrieve(
            str(pending_user_id),
            organisation_id=organisation_id,
        )

    renderer.render(response)


@org_pending_users_app.command(name="add")
def add_pending_user(
    organisation: OrganisationArgument = None,
    email: Annotated[
        str, typer.Argument(help="Email address to invite to the organisation.")
    ] = None,
    message: Annotated[
        str | None, typer.Option("--message", help="Optional invitation message.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Add a pending organisation user."""
    _ = _profile
    renderer, response = _create_pending_user(
        organisation_lookup=organisation,
        email=email,
        message=message,
    )
    renderer.render(response)


@org_pending_users_app.command(name="approve")
def approve_pending_user(
    organisation: OrganisationArgument = None,
    pending_user_id: Annotated[str, typer.Argument(help="Pending user ID.")] = None,
    _profile: ProfileAnnotation = None,
):
    """Approve a pending user."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    pending_user_id = _prompt_required_text(
        renderer,
        label="Pending user ID",
        value=pending_user_id,
        param_hint="pending_user_id",
    )

    with renderer.loading("Approving pending user..."):
        response = client.organisations.pending_users.approve(
            str(pending_user_id),
            body={},
            organisation_id=organisation_id,
        )

    renderer.render(response)


@org_pending_users_app.command(name="reject")
def reject_pending_user(
    organisation: OrganisationArgument = None,
    pending_user_id: Annotated[str, typer.Argument(help="Pending user ID.")] = None,
    _profile: ProfileAnnotation = None,
):
    """Reject a pending user."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    pending_user_id = _prompt_required_text(
        renderer,
        label="Pending user ID",
        value=pending_user_id,
        param_hint="pending_user_id",
    )

    with renderer.loading("Rejecting pending user..."):
        response = client.organisations.pending_users.reject(
            str(pending_user_id),
            body={},
            organisation_id=organisation_id,
        )

    renderer.render(response)


@org_pending_users_app.command(name="delete")
def delete_pending_user(
    organisation: OrganisationArgument = None,
    pending_user_id: Annotated[str, typer.Argument(help="Pending user ID.")] = None,
    _profile: ProfileAnnotation = None,
):
    """Delete a pending user."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    pending_user_id = _prompt_required_text(
        renderer,
        label="Pending user ID",
        value=pending_user_id,
        param_hint="pending_user_id",
    )

    with renderer.loading("Deleting pending user..."):
        client.organisations.pending_users.delete(
            str(pending_user_id),
            organisation_id=organisation_id,
        )

    renderer.render({"deleted": True, "pending_user_id": str(pending_user_id)})


@org_roles_app.command(name="list")
def list_roles(
    organisation: OrganisationArgument = None,
    archived: Annotated[
        str | None,
        typer.Option(
            help="Filter by archived status. Accepted values: true, false, 1, 0, yes, no."
        ),
    ] = None,
    id: Annotated[int | None, typer.Option(help="Filter by role ID.")] = None,
    name: Annotated[str | None, typer.Option(help="Filter by exact role name.")] = None,
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
    page: Annotated[int | None, typer.Option(help="Page number to request.")] = None,
    per_page: Annotated[
        int | None, typer.Option("--per-page", help="Number of records per page.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Full-text search term.")] = None,
    _profile: ProfileAnnotation = None,
):
    """List organisation roles."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)

    with renderer.loading("Loading organisation roles..."):
        response = client.organisations.roles.list(
            archived=parse_optional_bool(archived, "--archived"),
            id=id,
            name=name,
            name__contains=name_contains,
            name__icontains=name_icontains,
            ordering=ordering,
            page=page,
            per_page=per_page,
            search=search,
            organisation_id=organisation_id,
        )

    renderer.render_list(response)


@org_roles_app.command(name="get")
def get_role(
    organisation: OrganisationArgument = None,
    role_id: Annotated[str, typer.Argument(help="Organisation role ID.")] = None,
    _profile: ProfileAnnotation = None,
):
    """Get an organisation role."""
    _ = _profile
    organisation_id, client, renderer = _resolve_org_context(organisation)
    role_id = _prompt_required_text(
        renderer,
        label="Organisation role ID",
        value=role_id,
        param_hint="role_id",
    )

    with renderer.loading("Loading organisation role..."):
        response = client.organisations.roles.retrieve(
            str(role_id),
            organisation_id=organisation_id,
        )

    renderer.render(response)


@org_app.command(name="invite")
def invite(
    organisation: OrganisationArgument = None,
    email: Annotated[
        str, typer.Argument(help="Email address to invite to the organisation.")
    ] = None,
    message: Annotated[
        str | None, typer.Option("--message", help="Optional invitation message.")
    ] = None,
    _profile: ProfileAnnotation = None,
):
    """Invite a pending organisation user."""
    _ = _profile
    renderer, response = _create_pending_user(
        organisation_lookup=organisation,
        email=email,
        message=message,
    )
    renderer.render(response)
