from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import typer

from .lookup import (
    LookupChoice,
    humanize_model_name,
    load_control_model_choices,
    resolve_control_model_class,
    resolve_resource_lookup,
)
from .schema import ModelVersionFieldSpec, get_model_field_specs
from .values import coerce_cli_value


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
    resource_lookup_choices: list[LookupChoice] | None = None
    match_middle: bool = False
    allow_blank: bool = True
    exists: bool | None = None
    file_okay: bool | None = None
    dir_okay: bool | None = None


def humanize_field_name(name: str) -> str:
    return name.replace("_", " ").capitalize()


def resolve_field_kind(
    spec: ModelVersionFieldSpec,
) -> Literal["text", "int", "bool", "json", "path", "resource"]:
    if spec.name == "installer":
        return "path"
    if spec.field.type in {"integer", "SnowflakeId"}:
        return "int"
    if spec.field.type == "boolean":
        return "bool"
    if spec.field.type == "json":
        return "json"
    if spec.field.type == "Location":
        return "json"
    if spec.field.type == "resource":
        return "resource"
    return "text"


def build_prompt_field_for_spec(
    client: Any,
    spec: ModelVersionFieldSpec,
    default: Any,
) -> Field:
    label = (
        "Installer file path"
        if spec.name == "installer"
        else humanize_field_name(spec.output_id or spec.name)
    )
    kind = resolve_field_kind(spec)
    resource_model_cls = None
    resource_lookup_choices = None
    resource_model_label = None
    match_middle = False

    # Resource fields need lookup choices up front so renderers can validate
    # and autocomplete against the same set of values the command will accept.
    if kind == "resource" and spec.field.ref:
        resource_model_cls = resolve_control_model_class(spec.field.ref)
        resource_model_label = humanize_model_name(resource_model_cls.__name__)
        try:
            resource_lookup_choices = load_control_model_choices(
                client,
                resource_model_cls,
                archived=False,
                ordering="display_name",
                label_attrs=("display_name", "name"),
                searchable_attrs=("display_name", "name"),
                model_label=resource_model_label,
            )
            match_middle = True
        except Exception:
            resource_lookup_choices = None

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


def normalize_prompted_value(
    spec: ModelVersionFieldSpec,
    field: Field,
    raw_value: Any,
) -> Any:
    if raw_value is None:
        return None
    if field.kind == "resource" and field.resource_lookup_choices is not None:
        return resolve_resource_lookup(
            field.resource_lookup_choices,
            str(raw_value),
            model_label=field.resource_model_label or "resource",
        )
    return coerce_cli_value(spec, raw_value)


def prompt_model_values(
    client: Any,
    renderer: Any,
    model_cls: type[Any],
    method: str,
    initial_values: dict[str, Any],
) -> dict[str, Any]:
    specs = get_model_field_specs(model_cls, method)
    prompted_values = dict(initial_values)
    prompt_fields = [
        build_prompt_field_for_spec(
            client,
            spec,
            prompted_values.get(spec.name),
        )
        for spec in specs
    ]
    prompted_answers = renderer.prompt_fields(prompt_fields)

    for spec, field in zip(specs, prompt_fields):
        prompted_values[spec.name] = normalize_prompted_value(
            spec,
            field,
            prompted_answers.get(spec.name),
        )

    return prompted_values


def prompt_path(
    renderer: Any,
    *,
    label: str,
    value: str | Path | None = None,
    required: bool = True,
    exists: bool | None = None,
    file_okay: bool | None = None,
    dir_okay: bool | None = None,
    param_hint: str = "path",
) -> Path:
    if value is None:
        field = Field(
            key="path",
            label=label,
            kind="path",
            required=required,
            exists=exists,
            file_okay=file_okay,
            dir_okay=dir_okay,
            allow_blank=not required,
        )
        prompted = renderer.prompt_fields([field])
        value = prompted.get("path")

    if value is None:
        raise typer.BadParameter(f"{label} is required.", param_hint=param_hint)

    path = Path(value).expanduser().resolve()

    if exists is True and not path.exists():
        raise typer.BadParameter(
            f"{label} does not exist: {path}",
            param_hint=param_hint,
        )
    if exists is False and path.exists():
        raise typer.BadParameter(
            f"{label} already exists: {path}",
            param_hint=param_hint,
        )
    if file_okay is True and path.exists() and not path.is_file():
        raise typer.BadParameter(
            f"{label} must be a file: {path}",
            param_hint=param_hint,
        )
    if dir_okay is True and path.exists() and not path.is_dir():
        raise typer.BadParameter(
            f"{label} must be a directory: {path}",
            param_hint=param_hint,
        )
    if file_okay is False and path.exists() and path.is_file():
        raise typer.BadParameter(
            f"{label} cannot be a file: {path}",
            param_hint=param_hint,
        )
    if dir_okay is False and path.exists() and path.is_dir():
        raise typer.BadParameter(
            f"{label} cannot be a directory: {path}",
            param_hint=param_hint,
        )

    return path
