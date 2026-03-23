from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from pydoover.models.control._base import ControlField, ControlModel

from doover_cli.utils.crud.schema import get_model_field_specs
from doover_cli.utils.crud.values import (
    build_model_instance,
    build_request_payload,
    coerce_cli_value,
    collect_changed_model_values,
    extract_model_values,
    normalize_model_values,
    parse_optional_bool,
)


class ExampleValueModel(ControlModel):
    _model_name = "ExampleValueModel"
    _field_defs = {
        "name": ControlField(type="string", nullable=True),
        "solution": ControlField(type="resource", ref="Solution", nullable=True),
        "count": ControlField(type="integer", nullable=True),
        "enabled": ControlField(type="boolean", nullable=True),
        "config": ControlField(type="json", nullable=True),
        "installer": ControlField(type="string", nullable=True),
    }
    _versions = {
        "ExampleValueRequest": {
            "methods": ["POST", "PATCH"],
            "fields": {
                "name": {"required": True},
                "solution": {"required": False, "output_id": "solution_id"},
                "count": {"required": False},
                "enabled": {"required": False},
                "config": {"required": False},
                "installer": {"required": False},
            },
        }
    }


def test_parse_optional_bool_accepts_expected_values():
    assert parse_optional_bool("true", "--flag") is True
    assert parse_optional_bool("No", "--flag") is False
    assert parse_optional_bool(None, "--flag") is None


def test_parse_optional_bool_rejects_invalid_values():
    with pytest.raises(typer.BadParameter):
        parse_optional_bool("maybe", "--flag")


def test_coerce_cli_value_handles_json_integer_boolean_resource_and_paths(tmp_path):
    specs = {spec.name: spec for spec in get_model_field_specs(ExampleValueModel, "POST")}
    installer = tmp_path / "installer.sh"

    assert coerce_cli_value(specs["config"], '{"mode":"auto"}') == {"mode": "auto"}
    assert coerce_cli_value(specs["count"], "8") == 8
    assert coerce_cli_value(specs["enabled"], "yes") is True
    assert coerce_cli_value(specs["solution"], "7") == 7
    assert coerce_cli_value(specs["solution"], {"id": 9}) == 9
    assert coerce_cli_value(specs["solution"], SimpleNamespace(id=11)) == 11
    assert coerce_cli_value(specs["installer"], str(installer)) == installer


def test_normalize_extract_and_build_payload_use_output_ids(tmp_path):
    installer = tmp_path / "installer.sh"
    normalized = normalize_model_values(
        ExampleValueModel,
        "POST",
        {
            "name": "Tracker",
            "solution": "5",
            "config": '{"mode":"auto"}',
            "installer": str(installer),
        },
    )

    assert normalized == {
        "name": "Tracker",
        "solution": 5,
        "config": {"mode": "auto"},
        "installer": installer,
    }

    extracted = extract_model_values(
        ExampleValueModel,
        "POST",
        {
            "name": "Tracker",
            "solution_id": 5,
            "config": {"mode": "auto"},
        },
    )
    assert extracted["solution"] == 5

    payload = build_request_payload(ExampleValueModel, "POST", normalized)
    assert payload["solution_id"] == 5
    assert payload["installer"] == installer


def test_collect_changed_model_values_handles_paths_and_only_returns_changes(tmp_path):
    installer = tmp_path / "installer.sh"

    changed = collect_changed_model_values(
        ExampleValueModel,
        "PATCH",
        {"name": "Tracker", "installer": str(installer)},
        {"name": "Tracker", "installer": installer, "config": {"mode": "manual"}},
    )

    assert changed == {"config": {"mode": "manual"}}


def test_build_model_instance_enforces_required_fields():
    with pytest.raises(typer.BadParameter):
        build_model_instance(ExampleValueModel, "POST", {})

    model = build_model_instance(
        ExampleValueModel,
        "POST",
        {"name": "Tracker", "count": 3},
    )
    assert model.name == "Tracker"
    assert model.count == 3
