from types import SimpleNamespace

import pytest
from pydoover.models.control import Solution
from pydoover.models.control._base import ControlField, ControlModel

from doover_cli.utils.crud.lookup import LookupChoice
from doover_cli.utils.crud.prompting import (
    Field,
    build_prompt_field_for_spec,
    humanize_field_name,
    humanize_model_name,
    normalize_prompted_value,
    prompt_path,
    prompt_model_values,
    resolve_field_kind,
)
from doover_cli.utils.crud.schema import get_model_field_specs


class ExamplePromptModel(ControlModel):
    _model_name = "ExamplePromptModel"
    _field_defs = {
        "name": ControlField(type="string", nullable=True),
        "solution": ControlField(type="resource", ref="Solution", nullable=True),
        "count": ControlField(type="integer", nullable=True),
        "enabled": ControlField(type="boolean", nullable=True),
        "config": ControlField(type="json", nullable=True),
        "installer": ControlField(type="string", nullable=True),
    }
    _versions = {
        "ExamplePromptRequest": {
            "methods": ["POST"],
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


class FakeRenderer:
    def __init__(self, prompt_answers):
        self.prompt_answers = prompt_answers
        self.calls = []

    def prompt_fields(self, fields):
        self.calls.append(fields)
        return {
            field.key: self.prompt_answers.get(field.key, field.default)
            for field in fields
        }


class FakeControlClient:
    def get_control_methods(self, model_cls):
        assert model_cls is Solution
        return SimpleNamespace(
            list=lambda **kwargs: SimpleNamespace(
                results=[SimpleNamespace(id=11, display_name="Field Ops")],
                count=1,
                next=None,
            )
        )


def test_humanize_helpers_and_field_kind_resolution():
    specs = {
        spec.name: spec for spec in get_model_field_specs(ExamplePromptModel, "POST")
    }

    assert humanize_field_name("solution_id") == "Solution id"
    assert humanize_model_name("DeviceType") == "device type"
    assert resolve_field_kind(specs["solution"]) == "resource"
    assert resolve_field_kind(specs["count"]) == "int"
    assert resolve_field_kind(specs["enabled"]) == "bool"
    assert resolve_field_kind(specs["config"]) == "json"
    assert resolve_field_kind(specs["installer"]) == "path"


def test_build_prompt_field_for_spec_sets_installer_and_resource_details():
    specs = {
        spec.name: spec for spec in get_model_field_specs(ExamplePromptModel, "POST")
    }
    client = FakeControlClient()

    installer_field = build_prompt_field_for_spec(client, specs["installer"], None)
    assert installer_field.label == "Installer file path"
    assert installer_field.kind == "path"
    assert installer_field.exists is True

    solution_field = build_prompt_field_for_spec(client, specs["solution"], 11)
    assert solution_field.kind == "resource"
    assert solution_field.resource_model_cls is Solution
    assert solution_field.resource_lookup_choices == [
        LookupChoice(
            id=11,
            label="Field Ops (11)",
            search_values=("Field Ops (11)", "11", "Field Ops"),
            field_values={"display_name": "Field Ops", "name": None},
        )
    ]


def test_normalize_prompted_value_resolves_resource_ids():
    spec = next(
        spec
        for spec in get_model_field_specs(ExamplePromptModel, "POST")
        if spec.name == "solution"
    )
    field = Field(
        key="solution",
        label="Solution",
        kind="resource",
        required=False,
        resource_model_label="solution",
        resource_lookup_choices=[
            LookupChoice(
                id=11,
                label="Field Ops (11)",
                search_values=("Field Ops (11)", "11", "Field Ops"),
            )
        ],
    )

    assert normalize_prompted_value(spec, field, "Field Ops (11)") == 11


def test_prompt_model_values_uses_defaults_and_normalizes_answers():
    client = FakeControlClient()
    renderer = FakeRenderer(
        {
            "name": "Tracker",
            "solution": "Field Ops (11)",
            "config": '{"mode":"auto"}',
        }
    )

    prompted = prompt_model_values(
        client,
        renderer,
        ExamplePromptModel,
        "POST",
        {"count": 5},
    )

    assert prompted["name"] == "Tracker"
    assert prompted["solution"] == 11
    assert prompted["config"] == {"mode": "auto"}
    assert prompted["count"] == 5
    assert renderer.calls[0][0].label == "Name"


def test_prompt_path_prompts_and_validates_existing_file(tmp_path):
    installer = tmp_path / "installer.sh"
    installer.write_text("#!/bin/sh\necho ok\n")
    renderer = FakeRenderer({"path": str(installer)})

    prompted = prompt_path(
        renderer,
        label="Installer file path",
        exists=True,
        file_okay=True,
        dir_okay=False,
        param_hint="installer_fp",
    )

    assert prompted == installer.resolve()
    assert renderer.calls[0][0].kind == "path"


def test_prompt_path_rejects_wrong_path_type(tmp_path):
    renderer = FakeRenderer({"path": str(tmp_path)})

    with pytest.raises(Exception) as exc_info:
        prompt_path(
            renderer,
            label="Installer file path",
            exists=True,
            file_okay=True,
            dir_okay=False,
            param_hint="installer_fp",
        )

    assert "must be a file" in str(exc_info.value)
