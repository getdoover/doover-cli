from pydoover.models.control import Solution
from pydoover.models.control._base import ControlField, ControlModel

from doover_cli.utils.crud.schema import (
    get_model_field_specs,
    get_request_version_name,
    get_update_method,
)


class ExampleCrudModel(ControlModel):
    _model_name = "ExampleCrudModel"
    _field_defs = {
        "name": ControlField(type="string", nullable=True),
        "solution": ControlField(type="resource", ref="Solution", nullable=True),
        "installer": ControlField(type="string", nullable=True),
    }
    _versions = {
        "ExampleCrudSerializerDetail": {
            "methods": ["POST"],
            "fields": {
                "name": {"required": True},
            },
        },
        "ExampleCrudSerializerDetailRequest": {
            "methods": ["POST"],
            "fields": {
                "name": {"required": True},
                "solution": {"required": False, "output_id": "solution_id"},
                "installer": {"required": False},
            },
        },
        "ExampleCrudPatchRequest": {
            "methods": ["PATCH"],
            "fields": {
                "name": {"required": False},
            },
        },
    }


class PutOnlyCrudModel(ControlModel):
    _model_name = "PutOnlyCrudModel"
    _field_defs = {
        "name": ControlField(type="string", nullable=True),
    }
    _versions = {
        "PutOnlyCrudRequest": {
            "methods": ["PUT"],
            "fields": {
                "name": {"required": True},
            },
        }
    }


class NoUpdateCrudModel(ControlModel):
    _model_name = "NoUpdateCrudModel"
    _field_defs = {
        "name": ControlField(type="string", nullable=True),
    }
    _versions = {
        "NoUpdateCrudRequest": {
            "methods": ["POST"],
            "fields": {
                "name": {"required": True},
            },
        }
    }


def test_get_request_version_name_prefers_request_versions():
    assert get_request_version_name(ExampleCrudModel, "post") == "ExampleCrudSerializerDetailRequest"


def test_get_update_method_prefers_patch_and_falls_back_to_put():
    assert get_update_method(ExampleCrudModel) == "PATCH"
    assert get_update_method(PutOnlyCrudModel) == "PUT"


def test_get_update_method_raises_when_no_update_version_exists():
    try:
        get_update_method(NoUpdateCrudModel)
    except RuntimeError as exc:
        assert str(exc) == "No PATCH or PUT request version found for NoUpdateCrudModel."
    else:
        raise AssertionError("Expected RuntimeError")


def test_get_model_field_specs_includes_output_ids_and_deduped_options():
    specs = get_model_field_specs(ExampleCrudModel, "POST")

    assert [spec.name for spec in specs] == ["name", "solution", "installer"]
    assert specs[0].required is True
    assert specs[1].output_id == "solution_id"
    assert specs[1].option_names == ("--solution-id", "--solution")
    assert specs[2].option_names == ("--installer",)


def test_resource_specs_keep_control_field_reference():
    specs = get_model_field_specs(ExampleCrudModel, "POST")

    assert specs[1].field.ref == Solution.__name__
