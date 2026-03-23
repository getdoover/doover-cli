from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

from pydoover.models.control import DeviceType, Solution

from doover_cli.utils.crud.commands import (
    build_create_command,
    build_update_command,
)


class FakeRenderer:
    def __init__(self, prompt_answers=None):
        self.prompt_answers = prompt_answers or {}
        self.prompt_fields_calls = []
        self.render_calls = []

    def loading(self, _message):
        return nullcontext()

    def prompt_fields(self, fields):
        self.prompt_fields_calls.append(fields)
        return {
            field.key: self.prompt_answers.get(field.key, field.default)
            for field in fields
        }

    def render(self, data):
        self.render_calls.append(data)


def _resource_methods(**kwargs):
    return SimpleNamespace(**kwargs)


def test_create_callback_signature_includes_generated_options():
    callback = build_create_command(
        model_cls=DeviceType,
        command_help="Create a device type.",
        get_state=lambda: (None, None),
    )

    signature = callback.__signature__
    assert "name" in signature.parameters
    assert "installer" in signature.parameters

    installer_annotation = signature.parameters["installer"].annotation
    assert get_args(installer_annotation)[0] == Path | None


def test_update_callback_signature_includes_resource_id_argument():
    callback = build_update_command(
        model_cls=DeviceType,
        command_help="Update a device type.",
        get_state=lambda: (None, None),
        resource_id_param_name="device_type_id",
        resource_id_type=int,
        resource_id_help="Device type ID to update.",
    )

    signature = callback.__signature__
    assert "device_type_id" in signature.parameters
    assert "name" in signature.parameters


def test_create_callback_prompts_only_when_required_fields_missing(monkeypatch, tmp_path):
    renderer = FakeRenderer(
        {
            "name": "Prompted Tracker",
            "solution": "Field Ops (9)",
            "installer": str(tmp_path / "installer.sh"),
        }
    )
    captured = {}

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            if model_cls is Solution:
                return _resource_methods(
                    list=lambda **kwargs: SimpleNamespace(
                        results=[SimpleNamespace(id=9, display_name="Field Ops")],
                        count=1,
                        next=None,
                    )
                )
            if model_cls is DeviceType:
                return _resource_methods(
                    post=lambda payload: (
                        captured.setdefault("payload", payload),
                        {"id": 1},
                    )[-1]
                )
            raise AssertionError(f"Unexpected model {model_cls}")

    callback = build_create_command(
        model_cls=DeviceType,
        command_help="Create a device type.",
        get_state=lambda: (FakeControlClient(), renderer),
    )

    callback(ctx=None, _profile=None)

    assert captured["payload"].name == "Prompted Tracker"
    assert renderer.prompt_fields_calls


def test_update_callback_fetches_current_values_and_uses_patch(monkeypatch):
    renderer = FakeRenderer(
        {
            "name": "Updated Tracker",
            "solution": "Field Ops (11)",
        }
    )
    captured = {}

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            if model_cls is Solution:
                return _resource_methods(
                    list=lambda **kwargs: SimpleNamespace(
                        results=[
                            SimpleNamespace(id=9, display_name="Existing Solution"),
                            SimpleNamespace(id=11, display_name="Field Ops"),
                        ],
                        count=2,
                        next=None,
                    )
                )
            if model_cls is DeviceType:
                return _resource_methods(
                    get=lambda device_type_id: (
                        captured.setdefault("get_id", device_type_id),
                        SimpleNamespace(name="Tracker", solution=SimpleNamespace(id=9)),
                    )[-1],
                    patch=lambda device_type_id, payload: (
                        captured.setdefault("patch_id", device_type_id),
                        captured.setdefault("payload", payload),
                        {"id": 55},
                    )[-1],
                    put=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        AssertionError("PATCH should be preferred")
                    ),
                )
            raise AssertionError(f"Unexpected model {model_cls}")

    callback = build_update_command(
        model_cls=DeviceType,
        command_help="Update a device type.",
        get_state=lambda: (FakeControlClient(), renderer),
        resource_id_param_name="device_type_id",
        resource_id_type=int,
        resource_id_help="Device type ID to update.",
    )

    callback(ctx=None, device_type_id=55, _profile=None)

    assert captured["get_id"] == "55"
    assert captured["patch_id"] == "55"
    assert captured["payload"]["name"] == "Updated Tracker"
    assert captured["payload"]["solution_id"] == 11


def test_update_callback_prints_when_nothing_changes(capsys):
    renderer = FakeRenderer(
        {
            "name": "Tracker",
        }
    )

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            if model_cls is Solution:
                return _resource_methods(
                    list=lambda **kwargs: SimpleNamespace(
                        results=[],
                        count=0,
                        next=None,
                    )
                )
            assert model_cls is DeviceType
            return _resource_methods(
                get=lambda device_type_id: SimpleNamespace(name="Tracker"),
                patch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("No patch should be sent")
                ),
                put=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("No put should be sent")
                ),
            )

    callback = build_update_command(
        model_cls=DeviceType,
        command_help="Update a device type.",
        get_state=lambda: (FakeControlClient(), renderer),
        resource_id_param_name="device_type_id",
        resource_id_type=int,
        resource_id_help="Device type ID to update.",
    )

    callback(ctx=None, device_type_id=55, _profile=None)

    assert capsys.readouterr().out.strip() == "No changes submitted."
