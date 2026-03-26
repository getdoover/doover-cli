from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass(frozen=True)
class ModelVersionFieldSpec:
    name: str
    field: Any
    required: bool
    output_id: str | None
    option_names: tuple[str, ...]


def _to_option_name(name: str) -> str:
    return f"--{name.replace('_', '-')}"


def _dedupe_preserving_order(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def get_request_version_name(model_cls: type[Any], method: str) -> str:
    method = method.upper()

    # Prefer explicit request serializers when a model exposes multiple versions
    # for the same HTTP method.
    matching_versions = [
        version_name
        for version_name, version in model_cls._versions.items()
        if method in (version.get("methods") or [])
    ]
    if not matching_versions:
        raise RuntimeError(
            f"No {method} request version found for {model_cls.__name__}."
        )

    request_versions = [name for name in matching_versions if name.endswith("Request")]
    if request_versions:
        return request_versions[0]
    return matching_versions[0]


def get_update_method(model_cls: type[Any]) -> str:
    for method in ("PATCH", "PUT"):
        try:
            get_request_version_name(model_cls, method)
        except RuntimeError:
            continue
        return method

    raise RuntimeError(
        f"No PATCH or PUT request version found for {model_cls.__name__}."
    )


@lru_cache(maxsize=None)
def _get_field_specs_cache(
    model_cls: type[Any],
    method: str,
) -> tuple[ModelVersionFieldSpec, ...]:
    version_name = get_request_version_name(model_cls, method)
    version = model_cls._versions[version_name]
    specs: list[ModelVersionFieldSpec] = []

    for field_name, config in (version.get("fields") or {}).items():
        output_id = config.get("output_id")
        option_names: list[str] = []
        if output_id:
            option_names.append(_to_option_name(output_id))
        option_names.append(_to_option_name(field_name))
        specs.append(
            ModelVersionFieldSpec(
                name=field_name,
                field=model_cls._field_defs[field_name],
                required=bool(config.get("required")),
                output_id=output_id,
                option_names=_dedupe_preserving_order(option_names),
            )
        )

    return tuple(specs)


def get_model_field_specs(
    model_cls: type[Any],
    method: str,
) -> list[ModelVersionFieldSpec]:
    return list(_get_field_specs_cache(model_cls, method.upper()))
