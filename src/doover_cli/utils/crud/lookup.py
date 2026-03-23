from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import click
import typer
from pydoover.models import control as control_models

from ...api import ControlClientUnavailableError
from ..api import setup_session


@dataclass(frozen=True)
class LookupChoice:
    id: int
    label: str
    search_values: tuple[str, ...]
    field_values: dict[str, Any] = field(default_factory=dict)


def resolve_control_model_class(ref: str) -> type[Any]:
    try:
        model_cls = getattr(control_models, ref)
    except AttributeError as exc:
        raise RuntimeError(f"Unable to resolve control model class for {ref!r}.") from exc
    if not isinstance(model_cls, type):
        raise RuntimeError(f"Resolved control model {ref!r} is not a class.")
    return model_cls


def _dedupe_strings(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def load_control_model_choices(
    client: Any,
    model_cls: type[Any],
    *,
    archived: bool | None = None,
    ordering: str | None = "name",
    per_page: int = 100,
    label_attrs: tuple[str, ...] = ("display_name", "name"),
    searchable_attrs: tuple[str, ...] | None = None,
    id_attr: str = "id",
    model_label: str | None = None,
    list_kwargs: dict[str, Any] | None = None,
) -> list[LookupChoice]:
    page_num = 1
    choices: list[LookupChoice] = []
    methods = client.get_control_methods(model_cls)
    search_fields = tuple(dict.fromkeys(searchable_attrs or label_attrs))
    base_list_kwargs = dict(list_kwargs or {})

    while True:
        page_kwargs = {
            **base_list_kwargs,
            "page": page_num,
            "per_page": per_page,
        }
        if archived is not None:
            page_kwargs["archived"] = archived
        if ordering is not None:
            page_kwargs["ordering"] = ordering

        page = methods.list(**page_kwargs)

        for resource in page.results:
            resource_id = int(getattr(resource, id_attr))
            field_values = {
                field_name: getattr(resource, field_name, None)
                for field_name in search_fields
            }
            label_text = next(
                (field_values[field_name] for field_name in label_attrs if field_values.get(field_name)),
                None,
            )
            if label_text is None:
                fallback_label = (model_label or humanize_model_name(model_cls.__name__)).capitalize()
                label_text = f"{fallback_label} {resource_id}"

            search_values = [f"{label_text} ({resource_id})", str(resource_id)]
            search_values.extend(
                value
                for value in field_values.values()
                if isinstance(value, str) and value
            )
            choices.append(
                LookupChoice(
                    id=resource_id,
                    label=f"{label_text} ({resource_id})",
                    search_values=_dedupe_strings(search_values),
                    field_values=field_values,
                )
            )

        if not page.next or len(choices) >= page.count:
            break
        page_num += 1

    return choices


def get_control_lookup_completion_client(
    ctx: click.Context | None = None,
) -> Any:
    profile_name = "default"
    if ctx is not None:
        profile_name = ctx.params.get("_profile") or ctx.params.get("profile") or profile_name

    session = setup_session(profile_name)
    return session.get_control_client()


def resolve_resource_lookup(
    choices: list[LookupChoice],
    lookup: str,
    *,
    model_label: str,
) -> int:
    stripped = lookup.strip()
    if not stripped:
        raise typer.BadParameter(f"Please provide a {model_label} ID or name.")

    if stripped.lstrip("-").isdigit():
        return int(stripped)

    exact_label_match = next(
        (choice.id for choice in choices if choice.label == stripped),
        None,
    )
    if exact_label_match is not None:
        return exact_label_match

    # Matching against normalized search values keeps prompt answers and direct
    # CLI lookups aligned with the same resolution behavior.
    lowered_lookup = stripped.casefold()
    matches = [
        choice
        for choice in choices
        if any(candidate.casefold() == lowered_lookup for candidate in choice.search_values)
    ]

    unique_matches = {choice.id: choice for choice in matches}
    if len(unique_matches) == 1:
        return next(iter(unique_matches.values())).id

    if len(unique_matches) > 1:
        matching_labels = ", ".join(
            sorted(choice.label for choice in unique_matches.values())
        )
        raise typer.BadParameter(
            f"Multiple {model_label}s match '{lookup}'. Use an ID or one of: {matching_labels}."
        )

    raise typer.BadParameter(
        f"No {model_label} found matching '{lookup}'. Use an ID or an exact {model_label} name."
    )


def validate_control_lookup(
    choices: list[LookupChoice],
    value: str,
    *,
    model_label: str,
) -> bool | str:
    try:
        resolve_resource_lookup(choices, value, model_label=model_label)
    except typer.BadParameter as exc:
        return str(exc)
    return True


def resource_autocomplete(
    model_cls: type[Any],
    *,
    archived: bool | None = None,
    ordering: str | None = "name",
    label_attrs: tuple[str, ...] = ("display_name", "name"),
    searchable_attrs: tuple[str, ...] | None = None,
    id_attr: str = "id",
    list_kwargs: dict[str, Any] | None = None,
) -> Callable[[click.Context, list[str], str], list[tuple[str, str] | str]]:
    model_label = humanize_model_name(model_cls.__name__)

    def autocomplete(
        ctx: click.Context,
        _args: list[str],
        incomplete: str,
    ) -> list[tuple[str, str] | str]:
        try:
            client = get_control_lookup_completion_client(ctx)
            choices = load_control_model_choices(
                client,
                model_cls,
                archived=archived,
                ordering=ordering,
                label_attrs=label_attrs,
                searchable_attrs=searchable_attrs,
                id_attr=id_attr,
                model_label=model_label,
                list_kwargs=list_kwargs,
            )
        # Shell completion should fail closed for expected connectivity/session
        # issues, but unexpected errors should still surface during testing.
        except (ControlClientUnavailableError, RuntimeError, OSError):
            return []

        lowered_incomplete = incomplete.casefold().strip()
        completion_items: list[tuple[str, str] | str] = []

        for choice in choices:
            if lowered_incomplete and not any(
                lowered_incomplete in value.casefold()
                for value in choice.search_values
            ):
                continue
            completion_items.append((choice.label, f"ID {choice.id}"))

        return completion_items

    return autocomplete


def prompt_resource(
    model_cls: type[Any],
    client: Any,
    renderer: Any,
    *,
    action: str,
    lookup: str | None = None,
    archived: bool | None = None,
    ordering: str | None = "name",
    label_attrs: tuple[str, ...] = ("display_name", "name"),
    searchable_attrs: tuple[str, ...] | None = None,
    id_attr: str = "id",
    list_kwargs: dict[str, Any] | None = None,
) -> int:
    from .prompting import Field

    model_label = humanize_model_name(model_cls.__name__)
    if lookup is None:
        field = Field(
            key="resource_id",
            label=f"{model_label.capitalize()} to {action}",
            kind="resource",
            required=True,
            resource_model_cls=model_cls,
            resource_model_label=model_label,
            resource_lookup_choices=load_control_model_choices(
                client,
                model_cls,
                archived=archived,
                ordering=ordering,
                label_attrs=label_attrs,
                searchable_attrs=searchable_attrs,
                id_attr=id_attr,
                model_label=model_label,
                list_kwargs=list_kwargs,
            ),
            match_middle=True,
        )
        prompted = renderer.prompt_fields([field])
        prompt_value = prompted.get("resource_id")
        if prompt_value is None:
            raise typer.BadParameter(
                f"Please provide a {model_label} ID or name.",
                param_hint="resource_id",
            )
        return resolve_resource_lookup(
            field.resource_lookup_choices or [],
            str(prompt_value),
            model_label=model_label,
        )

    stripped_lookup = lookup.strip()
    if stripped_lookup.lstrip("-").isdigit():
        return int(stripped_lookup)

    choices = load_control_model_choices(
        client,
        model_cls,
        archived=archived,
        ordering=ordering,
        label_attrs=label_attrs,
        searchable_attrs=searchable_attrs,
        id_attr=id_attr,
        model_label=model_label,
        list_kwargs=list_kwargs,
    )
    return resolve_resource_lookup(
        choices,
        lookup,
        model_label=model_label,
    )


def humanize_model_name(name: str) -> str:
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()
