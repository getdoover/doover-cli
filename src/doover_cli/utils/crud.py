import json
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

import click
import typer
from pydoover.models import control as control_models

from . import parsers
from .api import ProfileAnnotation, setup_session

_MISSING = object()


@dataclass(frozen=True)
class ModelVersionFieldSpec:
    name: str
    field: Any
    required: bool
    output_id: str | None
    option_names: tuple[str, ...]


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: Literal["text", "int", "bool", "json", "path", "resource"]
    required: bool
    default: Any = None
    help: str | None = None
    choices: list[Any] | None = None
    resource_model_cls: type[Any] | None = None
    resource_model_label: str | None = None
    resource_lookup_choices: list[dict[str, Any]] | None = None
    match_middle: bool = False
    allow_blank: bool = True
    exists: bool | None = None
    file_okay: bool | None = None
    dir_okay: bool | None = None


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


def _to_option_name(name: str) -> str:
    return f"--{name.replace('_', '-')}"


def _humanize_field_name(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _humanize_model_name(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()


def _get_model_version_name(model_cls: type[Any], method: str) -> str:
    method = method.upper()
    matching_versions = [
        version_name
        for version_name, version in model_cls._versions.items()
        if method in (version.get("methods") or [])
    ]
    if not matching_versions:
        raise RuntimeError(f"No {method} request version found for {model_cls.__name__}.")

    request_versions = [name for name in matching_versions if name.endswith("Request")]
    if request_versions:
        return request_versions[0]
    return matching_versions[0]


def _resolve_update_method(model_cls: type[Any]) -> str:
    for method in ("PATCH", "PUT"):
        try:
            _get_model_version_name(model_cls, method)
        except RuntimeError:
            continue
        return method

    raise RuntimeError(
        f"No PATCH or PUT request version found for {model_cls.__name__}."
    )


def _get_model_version_field_specs(
    model_cls: type[Any],
    method: str,
) -> tuple[str, list[ModelVersionFieldSpec]]:
    version_name = _get_model_version_name(model_cls, method)
    version = model_cls._versions[version_name]
    specs: list[ModelVersionFieldSpec] = []

    for field_name, config in (version.get("fields") or {}).items():
        output_id = config.get("output_id")
        option_names = []
        if output_id:
            option_names.append(_to_option_name(output_id))
        option_names.append(_to_option_name(field_name))
        specs.append(
            ModelVersionFieldSpec(
                name=field_name,
                field=model_cls._field_defs[field_name],
                required=bool(config.get("required")),
                output_id=output_id,
                option_names=tuple(dict.fromkeys(option_names)),
            )
        )

    return version_name, specs


def _coerce_cli_value(spec: ModelVersionFieldSpec, raw_value: Any) -> Any:
    if raw_value is None:
        return None
    if spec.field.type == "json" and isinstance(raw_value, (dict, list)):
        return raw_value
    if spec.field.type == "resource":
        if isinstance(raw_value, dict):
            raw_value = raw_value.get("id", raw_value.get(spec.output_id or "", raw_value))
        else:
            raw_value = getattr(raw_value, "id", raw_value)
        if raw_value is None:
            return None
    if isinstance(raw_value, (Path, int, bool, dict, list)):
        return raw_value
    if not isinstance(raw_value, str):
        return raw_value

    stripped = raw_value.strip()

    if spec.name == "installer":
        return Path(stripped)
    if spec.field.type == "json":
        return parsers.maybe_json(raw_value)
    if spec.field.type in {"integer", "SnowflakeId"}:
        return int(stripped)
    if spec.field.type == "boolean":
        return _parse_optional_bool(raw_value, spec.option_names[0])
    if spec.field.type == "resource":
        if stripped.lstrip("-").isdigit():
            return int(stripped)
        return stripped
    return stripped


def _resolve_control_model_class(ref: str) -> type[Any]:
    try:
        model_cls = getattr(control_models, ref)
    except AttributeError as exc:
        raise RuntimeError(f"Unable to resolve control model class for {ref!r}.") from exc
    if not isinstance(model_cls, type):
        raise RuntimeError(f"Resolved control model {ref!r} is not a class.")
    return model_cls


def _resolve_field_kind(spec: ModelVersionFieldSpec) -> Literal["text", "int", "bool", "json", "path", "resource"]:
    if spec.name == "installer":
        return "path"
    if spec.field.type in {"integer", "SnowflakeId"}:
        return "int"
    if spec.field.type == "boolean":
        return "bool"
    if spec.field.type == "json":
        return "json"
    if spec.field.type == "resource":
        return "resource"
    return "text"


def _build_prompt_field_for_spec(
    client: Any,
    spec: ModelVersionFieldSpec,
    default: Any,
) -> Field:
    label = (
        "Installer file path"
        if spec.name == "installer"
        else _humanize_field_name(spec.output_id or spec.name)
    )
    kind = _resolve_field_kind(spec)
    resource_model_cls = None
    resource_lookup_choices = None
    resource_model_label = None
    match_middle = False

    if kind == "resource" and spec.field.ref:
        resource_model_cls = _resolve_control_model_class(spec.field.ref)
        resource_model_label = _humanize_model_name(resource_model_cls.__name__)
        resource_lookup_choices = _load_control_model_choices(
            client,
            resource_model_cls,
            archived=False,
            ordering="display_name",
            label_attrs=("display_name", "name"),
            searchable_attrs=("display_name", "name"),
            model_label=resource_model_label,
        )
        match_middle = True

    return Field(
        key=spec.name,
        label=label,
        kind=kind,
        required=spec.required,
        default=default,
        resource_model_cls=resource_model_cls,
        resource_model_label=resource_model_label,
        resource_lookup_choices=resource_lookup_choices,
        match_middle=match_middle,
        allow_blank=not spec.required,
        exists=True if spec.name == "installer" else None,
        file_okay=True if spec.name == "installer" else None,
        dir_okay=False if spec.name == "installer" else None,
    )


def _normalize_prompted_value(
    spec: ModelVersionFieldSpec,
    field: Field,
    raw_value: Any,
) -> Any:
    if raw_value is None:
        return None
    if field.kind == "resource" and field.resource_lookup_choices is not None:
        return _resolve_resource_lookup_from_choices(
            field.resource_lookup_choices,
            raw_value,
            model_label=field.resource_model_label or "resource",
        )
    return _coerce_cli_value(spec, raw_value)


def _prompt_model_values(
    client: Any,
    renderer: Any,
    model_cls: type[Any],
    method: str,
    initial_values: dict[str, Any],
) -> dict[str, Any]:
    _, specs = _get_model_version_field_specs(model_cls, method)
    prompted_values = dict(initial_values)
    prompt_fields = [
        _build_prompt_field_for_spec(
            client,
            spec,
            prompted_values.get(spec.name),
        )
        for spec in specs
    ]
    prompted_answers = renderer.prompt_fields(prompt_fields)

    for spec, field in zip(specs, prompt_fields):
        prompted_values[spec.name] = _normalize_prompted_value(
            spec,
            field,
            prompted_answers.get(spec.name),
        )

    return prompted_values


def _normalize_model_values(
    model_cls: type[Any],
    method: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    _, specs = _get_model_version_field_specs(model_cls, method)
    normalized_values: dict[str, Any] = {}

    for spec in specs:
        if spec.name not in values:
            continue
        normalized_values[spec.name] = _coerce_cli_value(spec, values.get(spec.name))

    return normalized_values


def _extract_model_values(
    model_cls: type[Any],
    method: str,
    source: Any,
) -> dict[str, Any]:
    _, specs = _get_model_version_field_specs(model_cls, method)
    extracted_values: dict[str, Any] = {}

    for spec in specs:
        if isinstance(source, dict):
            raw_value = source.get(spec.name, _MISSING)
            if raw_value is _MISSING and spec.output_id:
                raw_value = source.get(spec.output_id, _MISSING)
        else:
            raw_value = getattr(source, spec.name, _MISSING)
            if raw_value is _MISSING and spec.output_id:
                raw_value = getattr(source, spec.output_id, _MISSING)

        if raw_value is _MISSING:
            continue

        extracted_values[spec.name] = _coerce_cli_value(spec, raw_value)

    return extracted_values


def _build_request_payload(
    model_cls: type[Any],
    method: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    _, specs = _get_model_version_field_specs(model_cls, method)
    payload: dict[str, Any] = {}

    for spec in specs:
        if spec.name not in values:
            continue
        payload[spec.output_id or spec.name] = values[spec.name]

    return payload


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Path):
        left = str(left)
    if isinstance(right, Path):
        right = str(right)
    return left == right


def _collect_changed_model_values(
    model_cls: type[Any],
    method: str,
    current_values: dict[str, Any],
    updated_values: dict[str, Any],
) -> dict[str, Any]:
    _, specs = _get_model_version_field_specs(model_cls, method)
    normalized_current = _normalize_model_values(model_cls, method, current_values)
    normalized_updated = _normalize_model_values(model_cls, method, updated_values)
    changed_values: dict[str, Any] = {}

    for spec in specs:
        if spec.name not in normalized_updated:
            continue
        if _values_equal(
            normalized_current.get(spec.name),
            normalized_updated.get(spec.name),
        ):
            continue
        changed_values[spec.name] = normalized_updated.get(spec.name)

    return changed_values


def _build_model_instance(
    model_cls: type[Any],
    method: str,
    values: dict[str, Any],
):
    _, specs = _get_model_version_field_specs(model_cls, method)
    model_kwargs = {}

    for spec in specs:
        value = values.get(spec.name)
        if value is None:
            if spec.required:
                raise typer.BadParameter(
                    f"Missing required option {spec.option_names[0]}.",
                    param_hint=spec.option_names[0],
                )
            continue
        model_kwargs[spec.name] = value

    return model_cls(**model_kwargs)


def _get_option_type_for_spec(spec: ModelVersionFieldSpec) -> Any:
    if spec.name == "installer":
        return Path | None
    if spec.field.type in {"integer", "SnowflakeId"}:
        return int | None
    if spec.field.type == "resource" and (spec.output_id or "").endswith("_id"):
        return int | None
    return str | None


def _get_option_help_for_spec(spec: ModelVersionFieldSpec) -> str:
    label = _humanize_field_name(spec.output_id or spec.name)
    if spec.required:
        return f"{label}. Required by the API."
    return f"{label}. Leave unset to omit it."


def _get_update_option_help_for_spec(spec: ModelVersionFieldSpec) -> str:
    label = _humanize_field_name(spec.output_id or spec.name)
    return f"{label}. Leave unset; with no flags, the CLI will prompt you."


def _load_control_model_choices(
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
) -> list[dict[str, Any]]:
    page_num = 1
    choices: list[dict[str, Any]] = []
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
                label_prefix = model_label or _humanize_model_name(model_cls.__name__)
                label_text = f"{label_prefix.capitalize()} {resource_id}"

            search_values = [f"{label_text} ({resource_id})", str(resource_id)]
            search_values.extend(
                value
                for value in field_values.values()
                if isinstance(value, str) and value
            )
            choice = {
                "id": resource_id,
                "label": f"{label_text} ({resource_id})",
                "search_values": tuple(dict.fromkeys(search_values)),
            }
            choice.update(field_values)
            choices.append(choice)

        if not page.next or len(choices) >= page.count:
            break
        page_num += 1

    return choices


def _get_control_lookup_completion_client(
    ctx: click.Context | None = None,
) -> Any:
    profile_name = "default"
    if ctx is not None:
        profile_name = ctx.params.get("_profile") or ctx.params.get("profile") or profile_name

    session = setup_session(profile_name)
    return session.get_control_client()


def _resolve_resource_lookup_from_choices(
    choices: list[dict[str, Any]],
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
            isinstance(candidate, str) and candidate.casefold() == lowered_lookup
            for candidate in choice["search_values"]
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
            f"Multiple {model_label}s match '{lookup}'. Use an ID or one of: {matching_labels}."
        )

    raise typer.BadParameter(
        f"No {model_label} found matching '{lookup}'. Use an ID or an exact {model_label} name."
    )


def _validate_control_lookup(
    choices: list[dict[str, Any]],
    value: str,
    *,
    model_label: str,
) -> bool | str:
    try:
        _resolve_resource_lookup_from_choices(
            choices,
            value,
            model_label=model_label,
        )
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
    model_label = _humanize_model_name(model_cls.__name__)

    def autocomplete(
        ctx: click.Context,
        _args: list[str],
        incomplete: str,
    ) -> list[tuple[str, str] | str]:
        try:
            client = _get_control_lookup_completion_client(ctx)
            choices = _load_control_model_choices(
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
        except Exception:
            return []

        lowered_incomplete = incomplete.casefold().strip()
        completion_items: list[tuple[str, str] | str] = []

        for choice in choices:
            if lowered_incomplete and not any(
                lowered_incomplete in value.casefold()
                for value in choice["search_values"]
                if isinstance(value, str)
            ):
                continue
            completion_items.append((choice["label"], f"ID {choice['id']}"))

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
    model_label = _humanize_model_name(model_cls.__name__)
    if lookup is None:
        field = Field(
            key="resource_id",
            label=f"{model_label.capitalize()} to {action}",
            kind="resource",
            required=True,
            resource_model_cls=model_cls,
            resource_model_label=model_label,
            resource_lookup_choices=_load_control_model_choices(
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
        return _normalize_prompted_value(
            ModelVersionFieldSpec(
                name="resource_id",
                field=type("FieldDef", (), {"type": "resource"})(),
                required=True,
                output_id="id",
                option_names=("--id",),
            ),
            field,
            prompted.get("resource_id"),
        )

    stripped_lookup = lookup.strip()
    if stripped_lookup.lstrip("-").isdigit():
        return int(stripped_lookup)

    choices = _load_control_model_choices(
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
    return _resolve_resource_lookup_from_choices(
        choices,
        lookup,
        model_label=model_label,
    )


def build_create_command_callback(
    *,
    model_cls: type[Any],
    command_help: str,
    get_state: Callable[[], tuple[Any, Any]],
):
    _, specs = _get_model_version_field_specs(model_cls, "POST")

    def callback(**kwargs: Any):
        _ = kwargs.pop("_profile", None)
        kwargs.pop("ctx", None)

        client, renderer = get_state()
        methods = client.get_control_methods(model_cls)
        values = _normalize_model_values(model_cls, "POST", kwargs)

        if any(spec.required and values.get(spec.name) is None for spec in specs):
            values = _prompt_model_values(
                client,
                renderer,
                model_cls,
                "POST",
                values,
            )

        model_instance = _build_model_instance(model_cls, "POST", values)

        with renderer.loading(f"Creating {_humanize_model_name(model_cls.__name__)}..."):
            response = methods.post(model_instance)

        renderer.render(response)

    parameters = [
        inspect.Parameter(
            "ctx",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=typer.Context,
        ),
        inspect.Parameter(
            "_profile",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=None,
            annotation=ProfileAnnotation,
        ),
    ]
    annotations: dict[str, Any] = {
        "ctx": typer.Context,
        "_profile": ProfileAnnotation,
        "return": None,
    }

    for spec in specs:
        option_info = typer.Option(
            *spec.option_names,
            help=_get_option_help_for_spec(spec),
            show_default=False,
        )
        if spec.name == "installer":
            option_info.exists = True
            option_info.file_okay = True
            option_info.dir_okay = False

        annotation = Annotated[_get_option_type_for_spec(spec), option_info]
        annotations[spec.name] = annotation
        parameters.append(
            inspect.Parameter(
                spec.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None,
                annotation=annotation,
            )
        )

    callback.__name__ = "create"
    callback.__doc__ = command_help
    callback.__annotations__ = annotations
    callback.__signature__ = inspect.Signature(parameters=parameters)
    return callback


def build_update_command_callback(
    *,
    model_cls: type[Any],
    command_help: str,
    get_state: Callable[[], tuple[Any, Any]],
    resource_id_param_name: str,
    resource_id_type: type[Any],
    resource_id_help: str,
):
    update_method = _resolve_update_method(model_cls)
    _, specs = _get_model_version_field_specs(model_cls, update_method)

    def callback(**kwargs: Any):
        _ = kwargs.pop("_profile", None)
        kwargs.pop("ctx", None)
        resource_id = kwargs.pop(resource_id_param_name)

        client, renderer = get_state()
        methods = client.get_control_methods(model_cls)
        provided_values = {
            spec.name: kwargs.get(spec.name)
            for spec in specs
            if kwargs.get(spec.name) is not None
        }
        normalized_values = _normalize_model_values(
            model_cls,
            update_method,
            provided_values,
        )

        current_values: dict[str, Any] = {}
        requires_current_resource = update_method == "PUT" or not normalized_values
        if requires_current_resource:
            with renderer.loading(
                f"Loading current {_humanize_model_name(model_cls.__name__)}..."
            ):
                current_resource = methods.get(str(resource_id))

            current_values = _extract_model_values(
                model_cls,
                update_method,
                current_resource,
            )
        if normalized_values:
            changed_values = _collect_changed_model_values(
                model_cls,
                update_method,
                current_values,
                normalized_values,
            )
            if update_method == "PATCH":
                values_to_submit = changed_values
            else:
                values_to_submit = {**current_values, **changed_values}
        else:
            prompted_values = _prompt_model_values(
                client,
                renderer,
                model_cls,
                update_method,
                current_values,
            )
            changed_values = _collect_changed_model_values(
                model_cls,
                update_method,
                current_values,
                prompted_values,
            )
            if update_method == "PATCH":
                values_to_submit = changed_values
            else:
                values_to_submit = prompted_values if changed_values else {}

        if not values_to_submit:
            print("No changes submitted.")
            return

        payload = _build_request_payload(model_cls, update_method, values_to_submit)
        with renderer.loading(f"Updating {_humanize_model_name(model_cls.__name__)}..."):
            response = (
                methods.patch(str(resource_id), payload)
                if update_method == "PATCH"
                else methods.put(str(resource_id), payload)
            )

        renderer.render(response)

    parameters = [
        inspect.Parameter(
            "ctx",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=typer.Context,
        ),
        inspect.Parameter(
            resource_id_param_name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[
                resource_id_type,
                typer.Argument(help=resource_id_help),
            ],
        ),
        inspect.Parameter(
            "_profile",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=None,
            annotation=ProfileAnnotation,
        ),
    ]
    annotations: dict[str, Any] = {
        "ctx": typer.Context,
        resource_id_param_name: Annotated[
            resource_id_type,
            typer.Argument(help=resource_id_help),
        ],
        "_profile": ProfileAnnotation,
        "return": None,
    }

    for spec in specs:
        option_info = typer.Option(
            *spec.option_names,
            help=_get_update_option_help_for_spec(spec),
            show_default=False,
        )
        if spec.name == "installer":
            option_info.exists = True
            option_info.file_okay = True
            option_info.dir_okay = False

        annotation = Annotated[_get_option_type_for_spec(spec), option_info]
        annotations[spec.name] = annotation
        parameters.append(
            inspect.Parameter(
                spec.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None,
                annotation=annotation,
            )
        )

    callback.__name__ = "update"
    callback.__doc__ = command_help
    callback.__annotations__ = annotations
    callback.__signature__ = inspect.Signature(parameters=parameters)
    return callback


__all__ = [
    "Field",
    "build_create_command_callback",
    "build_update_command_callback",
    "_load_control_model_choices",
    "_parse_optional_bool",
    "_resolve_resource_lookup_from_choices",
    "prompt_resource",
    "resource_autocomplete",
]
