from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Annotated, Any, Callable

import typer

from ..api import ProfileAnnotation
from .lookup import humanize_model_name, prompt_resource, resource_autocomplete
from .prompting import prompt_model_values
from .schema import ModelVersionFieldSpec, get_model_field_specs, get_update_method
from .values import (
    build_model_instance,
    build_request_payload,
    collect_changed_model_values,
    extract_model_values,
    normalize_model_values,
)

from pathlib import Path


if TYPE_CHECKING:

    def _build_runtime_annotated(annotation_type: Any, option_info: Any) -> Any: ...
else:
    # Typer inspects runtime annotations, so these Annotated wrappers need to be
    # created dynamically after the option metadata exists.
    def _build_runtime_annotated(annotation_type: Any, option_info: Any) -> Any:
        return Annotated[annotation_type, option_info]


def _get_option_type_for_spec(spec: ModelVersionFieldSpec) -> Any:
    if spec.name == "installer":
        return Path | None
    if spec.field.type in {"integer", "SnowflakeId"}:
        return int | None
    if spec.field.type == "resource" and (spec.output_id or "").endswith("_id"):
        return int | None
    return str | None




def _get_option_help_for_spec(spec: ModelVersionFieldSpec, *, update: bool) -> str:
    from .prompting import humanize_field_name

    label = humanize_field_name(spec.output_id or spec.name)
    if update:
        return f"{label}. Leave unset; with no flags, the CLI will prompt you."
    if spec.required:
        return f"{label}. Required by the API."
    return f"{label}. Leave unset to omit it."


def _build_option_info_for_spec(
    spec: ModelVersionFieldSpec,
    *,
    update: bool,
) -> Any:
    option_info = typer.Option(
        *spec.option_names,
        help=_get_option_help_for_spec(spec, update=update),
        show_default=False,
    )
    if spec.name == "installer":
        option_info.exists = True
        option_info.file_okay = True
        option_info.dir_okay = False
    return option_info


def _get_lookup_label_attrs(model_cls: type[Any]) -> tuple[str, ...]:
    field_names = set(getattr(model_cls, "_field_defs", {}))
    label_attrs = [
        field_name
        for field_name in ("display_name", "name")
        if field_name in field_names
    ]
    return tuple(label_attrs or ("display_name", "name"))


def _get_lookup_ordering(model_cls: type[Any]) -> str | None:
    label_attrs = _get_lookup_label_attrs(model_cls)
    return label_attrs[0] if label_attrs else None


def _build_option_parameters(
    specs: list[ModelVersionFieldSpec],
    *,
    update: bool,
) -> tuple[list[inspect.Parameter], dict[str, Any]]:
    parameters: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}

    for spec in specs:
        option_info = _build_option_info_for_spec(spec, update=update)
        annotation = _build_runtime_annotated(
            _get_option_type_for_spec(spec), option_info
        )
        annotations[spec.name] = annotation
        parameters.append(
            inspect.Parameter(
                spec.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None,
                annotation=annotation,
            )
        )

    return parameters, annotations


def build_create_command(
    *,
    model_cls: type[Any],
    command_help: str,
    get_state: Callable[[], tuple[Any, Any]],
):
    specs = get_model_field_specs(model_cls, "POST")

    def callback(**kwargs: Any):
        _ = kwargs.pop("_profile", None)
        kwargs.pop("ctx", None)

        client, renderer = get_state()
        methods = client.get_control_methods(model_cls)
        values = normalize_model_values(model_cls, "POST", kwargs)

        if any(spec.required and values.get(spec.name) is None for spec in specs):
            values = prompt_model_values(
                client,
                renderer,
                model_cls,
                "POST",
                values,
            )

        model_instance = build_model_instance(model_cls, "POST", values)

        with renderer.loading(f"Creating {humanize_model_name(model_cls.__name__)}..."):
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

    option_parameters, option_annotations = _build_option_parameters(
        specs, update=False
    )
    parameters.extend(option_parameters)
    annotations.update(option_annotations)

    callback.__name__ = "create"
    callback.__doc__ = command_help
    callback.__annotations__ = annotations
    # Typer reads __signature__ to discover the generated options for these
    # callback factories, so we patch it after assembling the dynamic params.
    setattr(callback, "__signature__", inspect.Signature(parameters=parameters))
    return callback


def build_update_command(
    *,
    model_cls: type[Any],
    command_help: str,
    get_state: Callable[[], tuple[Any, Any]],
    resource_id_param_name: str,
    resource_id_help: str,
):
    update_method = get_update_method(model_cls)
    specs = get_model_field_specs(model_cls, update_method)
    label_attrs = _get_lookup_label_attrs(model_cls)
    lookup_ordering = _get_lookup_ordering(model_cls)

    def callback(**kwargs: Any):
        _ = kwargs.pop("_profile", None)
        kwargs.pop("ctx", None)
        resource_id = kwargs.pop(resource_id_param_name)

        client, renderer = get_state()
        resource_id = prompt_resource(
            model_cls,
            client,
            renderer,
            action="update",
            lookup=str(resource_id),
            archived=False,
            ordering=lookup_ordering,
            label_attrs=label_attrs,
            searchable_attrs=label_attrs,
        )

        methods = client.get_control_methods(model_cls)
        provided_values = {
            spec.name: kwargs.get(spec.name)
            for spec in specs
            if kwargs.get(spec.name) is not None
        }
        normalized_values = normalize_model_values(
            model_cls,
            update_method,
            provided_values,
        )

        current_values: dict[str, Any] = {}
        # PUT requires a full document, and the prompt-only flow needs the
        # current resource to supply sensible defaults before asking questions.
        requires_current_resource = update_method == "PUT" or not normalized_values
        if requires_current_resource:
            with renderer.loading(
                f"Loading current {humanize_model_name(model_cls.__name__)}..."
            ):
                current_resource = methods.get(str(resource_id))

            current_values = extract_model_values(
                model_cls,
                update_method,
                current_resource,
            )

        if normalized_values:
            changed_values = collect_changed_model_values(
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
            prompted_values = prompt_model_values(
                client,
                renderer,
                model_cls,
                update_method,
                current_values,
            )
            changed_values = collect_changed_model_values(
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

        payload = build_request_payload(model_cls, update_method, values_to_submit)
        with renderer.loading(f"Updating {humanize_model_name(model_cls.__name__)}..."):
            response = (
                methods.patch(str(resource_id), payload)
                if update_method == "PATCH"
                else methods.put(str(resource_id), payload)
            )

        renderer.render(response)

    resource_argument = _build_runtime_annotated(
        str,
        typer.Argument(
            help=resource_id_help,
            autocompletion=resource_autocomplete(
                model_cls,
                archived=False,
                ordering=lookup_ordering,
                label_attrs=label_attrs,
                searchable_attrs=label_attrs,
            ),
        ),
    )
    parameters = [
        inspect.Parameter(
            "ctx",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=typer.Context,
        ),
        inspect.Parameter(
            resource_id_param_name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=resource_argument,
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
        resource_id_param_name: resource_argument,
        "_profile": ProfileAnnotation,
        "return": None,
    }

    option_parameters, option_annotations = _build_option_parameters(specs, update=True)
    parameters.extend(option_parameters)
    annotations.update(option_annotations)

    callback.__name__ = "update"
    callback.__doc__ = command_help
    callback.__annotations__ = annotations
    setattr(callback, "__signature__", inspect.Signature(parameters=parameters))
    return callback
