import json
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable

import questionary
import typer

from .. import parsers
from ..api import ProfileAnnotation


@dataclass(frozen=True)
class ModelVersionFieldSpec:
    name: str
    field: Any
    required: bool
    output_id: str | None
    option_names: tuple[str, ...]


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


def _stringify_prompt_default(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    value_id = getattr(value, "id", None)
    if value_id is not None:
        return str(value_id)
    return str(value)


def _prompt_optional_text(message: str, default: Any = None) -> str | None:
    answer = questionary.text(
        message,
        default=_stringify_prompt_default(default),
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()

    stripped = answer.strip()
    if not stripped:
        return None
    return stripped


def _prompt_required_text(message: str, default: Any = None) -> str:
    answer = questionary.text(
        message,
        default=_stringify_prompt_default(default),
        validate=lambda value: bool(value.strip()) or "This field is required.",
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()
    return answer.strip()


def _prompt_optional_int(message: str, default: int | None = None) -> int | None:
    answer = questionary.text(
        message,
        default=_stringify_prompt_default(default),
        validate=lambda value: (
            True
            if not value.strip()
            else (
                True
                if value.strip().lstrip("-").isdigit()
                else "Please enter an integer or leave this blank."
            )
        ),
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()

    stripped = answer.strip()
    if not stripped:
        return None
    return int(stripped)


def _prompt_required_int(message: str, default: int | None = None) -> int:
    answer = questionary.text(
        message,
        default=_stringify_prompt_default(default),
        validate=lambda value: (
            True
            if value.strip().lstrip("-").isdigit()
            else "Please enter an integer."
        ),
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()
    return int(answer.strip())


def _prompt_optional_boolean(message: str, default: bool | None = None) -> bool | None:
    answer = questionary.text(
        message,
        default=_stringify_prompt_default(default),
        validate=lambda value: (
            True
            if not value.strip()
            else (
                True
                if value.strip().lower() in {"true", "false", "1", "0", "yes", "no"}
                else "Please enter true/false or leave this blank."
            )
        ),
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()

    stripped = answer.strip()
    if not stripped:
        return None
    return _parse_optional_bool(stripped, message)


def _prompt_required_boolean(message: str, default: bool | None = None) -> bool:
    answer = questionary.text(
        message,
        default=_stringify_prompt_default(default),
        validate=lambda value: (
            True
            if value.strip().lower() in {"true", "false", "1", "0", "yes", "no"}
            else "Please enter true or false."
        ),
    ).unsafe_ask()
    if answer is None:
        raise typer.Abort()
    parsed = _parse_optional_bool(answer, message)
    if parsed is None:
        raise typer.BadParameter(f"{message} is required.")
    return parsed


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
    if isinstance(raw_value, (Path, int, bool)):
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


def _prompt_value_for_spec(
    client: Any,
    spec: ModelVersionFieldSpec,
    default: Any,
    resource_prompt_resolvers: dict[str, Callable[[Any, Any], Any]],
) -> Any:
    label = (
        "Installer file path"
        if spec.name == "installer"
        else _humanize_field_name(spec.output_id or spec.name)
    )

    if spec.field.type == "resource":
        default_id = getattr(default, "id", default)
        resolver = resource_prompt_resolvers.get(spec.field.ref or "")
        if resolver is not None:
            return resolver(client, default_id)
        if spec.required:
            return _prompt_required_int(label, default_id)
        return _prompt_optional_int(label, default_id)

    if spec.field.type in {"integer", "SnowflakeId"}:
        if spec.required:
            return _prompt_required_int(label, default)
        return _prompt_optional_int(label, default)

    if spec.field.type == "boolean":
        if spec.required:
            return _prompt_required_boolean(label, default)
        return _prompt_optional_boolean(label, default)

    if spec.field.type == "json":
        if spec.required:
            return parsers.maybe_json(_prompt_required_text(label, default))
        raw_value = _prompt_optional_text(label, default)
        if raw_value is None:
            return None
        return parsers.maybe_json(raw_value)

    if spec.name == "installer":
        installer_input = _prompt_optional_text(label, default)
        return Path(installer_input) if installer_input is not None else None

    if spec.required:
        return _prompt_required_text(label, default)
    return _prompt_optional_text(label, default)


def _prompt_model_values(
    client: Any,
    model_cls: type[Any],
    method: str,
    initial_values: dict[str, Any],
    resource_prompt_resolvers: dict[str, Callable[[Any, Any], Any]],
) -> dict[str, Any]:
    _, specs = _get_model_version_field_specs(model_cls, method)
    prompted_values = dict(initial_values)

    for spec in specs:
        prompted_values[spec.name] = _prompt_value_for_spec(
            client,
            spec,
            prompted_values.get(spec.name),
            resource_prompt_resolvers,
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


def build_create_command_callback(
    *,
    model_cls: type[Any],
    command_help: str,
    get_state: Callable[[], tuple[Any, Any]],
    submit_callback: Callable[[Any, Any], Any],
    resource_prompt_resolvers: dict[str, Callable[[Any, Any], Any]] | None = None,
):
    _, specs = _get_model_version_field_specs(model_cls, "POST")
    use_resource_prompt_resolvers = resource_prompt_resolvers or {}

    def callback(**kwargs: Any):
        _ = kwargs.pop("_profile", None)
        kwargs.pop("ctx", None)

        client, renderer = get_state()
        values = _normalize_model_values(model_cls, "POST", kwargs)

        if any(spec.required and values.get(spec.name) is None for spec in specs):
            values = _prompt_model_values(
                client,
                model_cls,
                "POST",
                values,
                use_resource_prompt_resolvers,
            )

        model_instance = _build_model_instance(model_cls, "POST", values)

        with renderer.loading(f"Creating {_humanize_model_name(model_cls.__name__)}..."):
            response = submit_callback(client, model_instance)

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


__all__ = ["build_create_command_callback"]
