from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from .. import parsers
from .schema import ModelVersionFieldSpec, get_model_field_specs

_MISSING = object()


def _raise_location_error(spec: ModelVersionFieldSpec, message: str) -> None:
    raise typer.BadParameter(
        f"{spec.option_names[0]} {message}",
        param_hint=spec.option_names[0],
    )


def _coerce_location_number(spec: ModelVersionFieldSpec, key: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        _raise_location_error(spec, f"must use numeric {key} values.")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            _raise_location_error(spec, f"must use numeric {key} values.")
    _raise_location_error(spec, f"must use numeric {key} values.")


def _normalize_location_value(spec: ModelVersionFieldSpec, raw_value: Any) -> dict[str, float | None]:
    if isinstance(raw_value, str):
        raw_value = parsers.maybe_json(raw_value)
    elif hasattr(raw_value, "latitude") and hasattr(raw_value, "longitude"):
        raw_value = {
            "latitude": getattr(raw_value, "latitude"),
            "longitude": getattr(raw_value, "longitude"),
        }

    if not isinstance(raw_value, dict):
        _raise_location_error(
            spec,
            'must be a JSON object like {"latitude": 1.23, "longitude": 4.56}.',
        )

    unsupported_keys = sorted(set(raw_value) - {"latitude", "longitude"})
    if unsupported_keys:
        joined_keys = ", ".join(unsupported_keys)
        _raise_location_error(
            spec,
            f"does not accept unsupported keys: {joined_keys}. Use only latitude and longitude.",
        )

    missing_keys = [key for key in ("latitude", "longitude") if key not in raw_value]
    if missing_keys:
        joined_keys = ", ".join(missing_keys)
        _raise_location_error(spec, f"must include both latitude and longitude. Missing: {joined_keys}.")

    return {
        "latitude": _coerce_location_number(spec, "latitude", raw_value.get("latitude")),
        "longitude": _coerce_location_number(spec, "longitude", raw_value.get("longitude")),
    }


def parse_optional_bool(value: str | None, option_name: str) -> bool | None:
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


def coerce_cli_value(spec: ModelVersionFieldSpec, raw_value: Any) -> Any:
    if raw_value is None:
        return None
    if spec.field.type == "json" and isinstance(raw_value, (dict, list)):
        return raw_value
    if spec.field.type == "Location":
        return _normalize_location_value(spec, raw_value)

    # Resource fields arrive from multiple paths: CLI strings, prompt answers,
    # dict payloads, and hydrated model instances.
    if spec.field.type == "resource":
        if isinstance(raw_value, dict):
            raw_value = raw_value.get(
                "id", raw_value.get(spec.output_id or "", raw_value)
            )
        else:
            raw_value = getattr(raw_value, "id", raw_value)
        if raw_value is None:
            return None

    if isinstance(raw_value, (Path, int, bool, dict, list)):
        return raw_value
    if not isinstance(raw_value, str):
        return raw_value

    stripped = raw_value.strip()

    # Installer values need to stay as paths so Typer validation and request
    # serialization both work consistently.
    if spec.name == "installer":
        return Path(stripped)
    if spec.field.type == "json":
        return parsers.maybe_json(raw_value)
    if spec.field.type in {"integer", "SnowflakeId"}:
        return int(stripped)
    if spec.field.type == "boolean":
        return parse_optional_bool(raw_value, spec.option_names[0])
    if spec.field.type == "resource":
        if stripped.lstrip("-").isdigit():
            return int(stripped)
        return stripped
    return stripped


def normalize_model_values(
    model_cls: type[Any],
    method: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    normalized_values: dict[str, Any] = {}

    for spec in get_model_field_specs(model_cls, method):
        if spec.name not in values:
            continue
        normalized_values[spec.name] = coerce_cli_value(spec, values.get(spec.name))

    return normalized_values


def extract_model_values(
    model_cls: type[Any],
    method: str,
    source: Any,
) -> dict[str, Any]:
    extracted_values: dict[str, Any] = {}

    for spec in get_model_field_specs(model_cls, method):
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

        extracted_values[spec.name] = coerce_cli_value(spec, raw_value)

    return extracted_values


def build_request_payload(
    model_cls: type[Any],
    method: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    for spec in get_model_field_specs(model_cls, method):
        if spec.name not in values:
            continue
        payload[spec.output_id or spec.name] = values[spec.name]

    return payload


def values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Path):
        left = str(left)
    if isinstance(right, Path):
        right = str(right)
    return left == right


def collect_changed_model_values(
    model_cls: type[Any],
    method: str,
    current_values: dict[str, Any],
    updated_values: dict[str, Any],
) -> dict[str, Any]:
    normalized_current = normalize_model_values(model_cls, method, current_values)
    normalized_updated = normalize_model_values(model_cls, method, updated_values)
    changed_values: dict[str, Any] = {}

    for spec in get_model_field_specs(model_cls, method):
        if spec.name not in normalized_updated:
            continue
        if values_equal(
            normalized_current.get(spec.name),
            normalized_updated.get(spec.name),
        ):
            continue
        changed_values[spec.name] = normalized_updated.get(spec.name)

    return changed_values


def build_model_instance(
    model_cls: type[Any],
    method: str,
    values: dict[str, Any],
) -> Any:
    model_kwargs = {}

    for spec in get_model_field_specs(model_cls, method):
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
