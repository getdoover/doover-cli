from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import click
from pydoover.models.control import DeviceType, Solution
from typer.testing import CliRunner

from doover_cli import app
from doover_cli.apps import device_type as device_type_app
from doover_cli.utils import crud
from doover_cli.utils.crud import LookupChoice

runner = CliRunner()


class FakeRenderer:
    def __init__(self, prompt_answers=None):
        self.prompt_answers = prompt_answers or {}
        self.prompt_fields_calls = []
        self.render_calls = []
        self.render_list_calls = []

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

    def render_list(self, data):
        self.render_list_calls.append(data)


def _resource_methods(**kwargs):
    return SimpleNamespace(**kwargs)


def test_device_type_list_passes_all_filters(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeDevicesClient:
        def types_list(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": []}

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        [
            "device-type",
            "list",
            "--archived",
            "true",
            "--id",
            "42",
            "--name",
            "Tracker",
            "--name-contains",
            "rack",
            "--name-icontains",
            "TRAC",
            "--ordering",
            "-stars",
            "--organisation",
            "17",
            "--page",
            "3",
            "--per-page",
            "25",
            "--search",
            "solar",
            "--stars",
            "5",
            "--stars-gt",
            "1",
            "--stars-gte",
            "2",
            "--stars-lt",
            "9",
            "--stars-lte",
            "8",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"] == {
        "archived": True,
        "id": 42,
        "name": "Tracker",
        "name__contains": "rack",
        "name__icontains": "TRAC",
        "ordering": "-stars",
        "organisation": "17",
        "page": 3,
        "per_page": 25,
        "search": "solar",
        "stars": 5,
        "stars__gt": 1,
        "stars__gte": 2,
        "stars__lt": 9,
        "stars__lte": 8,
    }
    assert renderer.render_list_calls == [{"results": []}]


def test_device_type_create_builds_payload(monkeypatch, tmp_path):
    captured = {}
    renderer = FakeRenderer()
    installer = tmp_path / "installer.sh"
    installer.write_text("#!/bin/sh\necho ok\n")

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(
                post=lambda payload: (
                    captured.setdefault("payload", payload),
                    {"id": 123},
                )[-1],
            )

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )
    monkeypatch.setattr(
        "doover_cli.utils.crud.commands.prompt_model_values",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("interactive prompt should not be used")
        ),
    )

    result = runner.invoke(
        app,
        [
            "device-type",
            "create",
            "--name",
            "Tracker",
            "--solution-id",
            "7",
            "--config",
            '{"mode":"auto"}',
            "--config-schema",
            '{"type":"object"}',
            "--device-extra-config-schema",
            '{"extra":true}',
            "--installer",
            str(installer),
            "--installer-info",
            "install.sh",
            "--copy-command",
            "scp installer.sh",
            "--description",
            "Field tracker",
            "--logo-url",
            "https://example.com/logo.png",
            "--extra-info",
            "beta",
            "--stars",
            "4",
            "--default-icon",
            "router",
        ],
    )

    assert result.exit_code == 0
    assert isinstance(captured["payload"], DeviceType)
    assert captured["payload"].to_version(
        "DeviceTypeSerializerDetailRequest",
        method="POST",
    ) == {
        "name": "Tracker",
        "solution_id": 7,
        "config": {"mode": "auto"},
        "config_schema": {"type": "object"},
        "device_extra_config_schema": {"extra": True},
        "installer": installer,
        "installer_info": "install.sh",
        "copy_command": "scp installer.sh",
        "description": "Field tracker",
        "logo_url": "https://example.com/logo.png",
        "extra_info": "beta",
        "stars": 4,
        "default_icon": "router",
    }
    assert renderer.render_calls == [{"id": 123}]


def test_device_type_create_prompts_for_missing_required_fields(monkeypatch, tmp_path):
    captured = {}
    installer = tmp_path / "prompt-installer.sh"
    installer.write_text("#!/bin/sh\necho prompt\n")
    renderer = FakeRenderer(
        prompt_answers={
            "name": "Prompted Tracker",
            "solution": "Field Ops (9)",
            "config": '{"mode":"prompt"}',
            "config_schema": None,
            "device_extra_config_schema": None,
            "installer": str(installer),
            "installer_info": "install.sh",
            "copy_command": None,
            "description": "Prompt description",
            "logo_url": None,
            "extra_info": None,
            "stars": 7,
            "default_icon": None,
        }
    )

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            if model_cls is Solution:
                return _resource_methods(
                    list=lambda **kwargs: (
                        captured.setdefault("solution_list_kwargs", kwargs),
                        SimpleNamespace(
                            results=[SimpleNamespace(id=9, display_name="Field Ops")],
                            count=1,
                            next=None,
                        ),
                    )[-1]
                )
            if model_cls is DeviceType:
                return _resource_methods(
                    post=lambda payload: (
                        captured.setdefault("payload", payload),
                        {"id": 456},
                    )[-1],
                )
            raise AssertionError(f"Unexpected model: {model_cls}")

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "create"])

    assert result.exit_code == 0
    assert captured["solution_list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    prompted_fields = renderer.prompt_fields_calls[0]
    solution_field = next(field for field in prompted_fields if field.key == "solution")
    assert solution_field.kind == "resource"
    assert solution_field.resource_lookup_choices == [
        LookupChoice(
            id=9,
            label="Field Ops (9)",
            search_values=("Field Ops (9)", "9", "Field Ops"),
            field_values={"display_name": "Field Ops", "name": None},
        )
    ]
    assert captured["payload"].to_version(
        "DeviceTypeSerializerDetailRequest",
        method="POST",
    ) == {
        "name": "Prompted Tracker",
        "solution_id": 9,
        "config": {"mode": "prompt"},
        "installer": installer,
        "installer_info": "install.sh",
        "description": "Prompt description",
        "stars": 7,
    }
    assert renderer.render_calls == [{"id": 456}]


def test_device_type_get_renders_response(monkeypatch):
    renderer = FakeRenderer()

    class FakeDevicesClient:
        def types_retrieve(self, device_type_id):
            assert device_type_id == "55"
            return {"id": 55, "name": "Tracker"}

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "get", "55"])

    assert result.exit_code == 0
    assert renderer.render_calls == [{"id": 55, "name": "Tracker"}]


def test_device_type_get_accepts_name_lookup(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[
                            SimpleNamespace(id=160631245057827589, name="a test thing that needs to be tested"),
                        ],
                        count=1,
                        next=None,
                    ),
                )[-1]
            )

        class devices:
            @staticmethod
            def types_retrieve(device_type_id):
                captured["device_type_id"] = device_type_id
                return {"id": 160631245057827589}

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        [
            "device-type",
            "get",
            "a test thing that needs to be tested (160631245057827589)",
        ],
    )

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": False,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["device_type_id"] == "160631245057827589"
    assert renderer.render_calls == [{"id": 160631245057827589}]


def test_device_type_create_help_lists_generated_options():
    result = runner.invoke(app, ["device-type", "create", "--help"])

    assert result.exit_code == 0
    assert "--name" in result.stdout
    assert "--solution-id" in result.stdout
    assert "--config-schema" in result.stdout
    assert "--installer" in result.stdout


def test_device_type_update_with_options_patches_payload(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(
                get=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("interactive fetch should not be used")
                ),
                patch=lambda device_type_id, payload: (
                    captured.setdefault("device_type_id", device_type_id),
                    captured.setdefault("payload", payload),
                    {"id": 55},
                )[-1],
                put=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("PATCH should be used when available")
                ),
            )

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        [
            "device-type",
            "update",
            "55",
            "--name",
            "Updated Tracker",
            "--solution-id",
            "7",
            "--config",
            '{"mode":"manual"}',
        ],
    )

    assert result.exit_code == 0
    assert captured["device_type_id"] == "55"
    assert captured["payload"] == {
        "name": "Updated Tracker",
        "solution_id": 7,
        "config": {"mode": "manual"},
    }
    assert renderer.render_calls == [{"id": 55}]


def test_device_type_update_without_options_fetches_and_prompts(monkeypatch):
    captured = {}
    renderer = FakeRenderer(
        prompt_answers={
            "name": "Updated Tracker",
            "solution": "Field Ops (11)",
            "config": '{"mode":"manual"}',
            "config_schema": {"type": "object"},
        }
    )

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            if model_cls is Solution:
                return _resource_methods(
                    list=lambda **kwargs: (
                        captured.setdefault("solution_list_kwargs", kwargs),
                        SimpleNamespace(
                            results=[
                                SimpleNamespace(id=9, display_name="Existing Solution"),
                                SimpleNamespace(id=11, display_name="Field Ops"),
                            ],
                            count=2,
                            next=None,
                        ),
                    )[-1]
                )
            if model_cls is DeviceType:
                return _resource_methods(
                    get=lambda device_type_id: (
                        captured.setdefault("retrieved_device_type_id", device_type_id),
                        SimpleNamespace(
                            name="Tracker",
                            config={"mode": "auto"},
                            config_schema={"type": "object"},
                            solution=SimpleNamespace(id=9, display_name="Existing Solution"),
                        ),
                    )[-1],
                    patch=lambda device_type_id, payload: (
                        captured.setdefault("patched_device_type_id", device_type_id),
                        captured.setdefault("payload", payload),
                        {"id": 55, "name": "Updated Tracker"},
                    )[-1],
                    put=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        AssertionError("PATCH should be used when available")
                    ),
                )
            raise AssertionError(f"Unexpected model: {model_cls}")

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "update", "55"])

    assert result.exit_code == 0
    assert captured["retrieved_device_type_id"] == "55"
    assert captured["solution_list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    prompted_fields = renderer.prompt_fields_calls[0]
    assert next(field for field in prompted_fields if field.key == "name").default == "Tracker"
    assert next(field for field in prompted_fields if field.key == "config").default == {"mode": "auto"}
    assert next(field for field in prompted_fields if field.key == "solution").default == 9
    assert captured["patched_device_type_id"] == "55"
    assert captured["payload"] == {
        "name": "Updated Tracker",
        "config": {"mode": "manual"},
        "solution_id": 11,
    }
    assert renderer.render_calls == [{"id": 55, "name": "Updated Tracker"}]


def test_device_type_archive_prompts_with_renderer_when_id_missing(monkeypatch):
    captured = {}
    renderer = FakeRenderer(prompt_answers={"resource_id": "Beta Tracker (27)"})

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[
                            SimpleNamespace(id=12, name="Alpha Sensor"),
                            SimpleNamespace(id=27, name="Beta Tracker"),
                        ],
                        count=2,
                        next=None,
                    ),
                )[-1]
            )

        class devices:
            @staticmethod
            def types_archive(device_type_id):
                captured["archived_id"] = device_type_id
                return {"id": int(device_type_id), "archived": True}

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "archive"])

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": False,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    field = renderer.prompt_fields_calls[0][0]
    assert field.label == "Device type to archive"
    assert field.resource_lookup_choices[1].label == "Beta Tracker (27)"
    assert field.match_middle is True
    assert captured["archived_id"] == "27"
    assert renderer.render_calls == [{"id": 27, "archived": True}]


def test_device_type_unarchive_prompts_with_renderer_when_id_missing(monkeypatch):
    captured = {}
    renderer = FakeRenderer(prompt_answers={"resource_id": "Archived Delta (91)"})

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[SimpleNamespace(id=91, display_name="Archived Delta")],
                        count=1,
                        next=None,
                    ),
                )[-1]
            )

        class devices:
            @staticmethod
            def types_unarchive(device_type_id):
                captured["unarchived_id"] = device_type_id
                return {"id": int(device_type_id), "archived": False}

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "unarchive"])

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": True,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["unarchived_id"] == "91"
    assert renderer.render_calls == [{"id": 91, "archived": False}]


def test_device_type_archive_accepts_name_lookup(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[
                            SimpleNamespace(id=12, name="Alpha Sensor"),
                            SimpleNamespace(id=27, name="Beta Tracker"),
                        ],
                        count=2,
                        next=None,
                    ),
                )[-1]
            )

        class devices:
            @staticmethod
            def types_archive(device_type_id):
                captured["archived_id"] = device_type_id
                return {"id": int(device_type_id), "archived": True}

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "archive", "Beta Tracker"])

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": False,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["archived_id"] == "27"
    assert renderer.render_calls == [{"id": 27, "archived": True}]


def test_upload_installer_prompts_for_device_type_and_file(monkeypatch, tmp_path):
    installer = tmp_path / "installer.sh"
    installer.write_text("#!/bin/sh\necho ok\n")
    renderer = FakeRenderer(
        prompt_answers={
            "resource_id": "Tracker (42)",
            "path": str(installer),
        }
    )
    captured = {}

    class FakeDevicesClient:
        def types_list(self, **kwargs):
            captured["types_list_kwargs"] = kwargs
            return SimpleNamespace(
                results=[SimpleNamespace(id=42, name="Tracker")],
                count=1,
                next=None,
            )

        def types_partial(self, device_type_id, body):
            captured["types_partial"] = {
                "id": device_type_id,
                "body": body,
            }
            return {"id": int(device_type_id), "installer": "uploaded"}

    class FakeControlClient:
        devices = FakeDevicesClient()

        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(list=self.devices.types_list)

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "upload-installer"])

    assert result.exit_code == 0
    assert captured["types_list_kwargs"] == {
        "archived": False,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["types_partial"]["id"] == "42"
    assert captured["types_partial"]["body"]["installer"] == installer.resolve()
    assert renderer.render_calls == [{"id": 42, "installer": "uploaded"}]


def test_upload_installer_tar_prompts_for_device_type_and_directory(monkeypatch, tmp_path):
    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    (installer_dir / "install.sh").write_text("#!/bin/sh\necho ok\n")
    renderer = FakeRenderer(
        prompt_answers={
            "resource_id": "Tracker (42)",
            "path": str(installer_dir),
        }
    )
    captured = {}

    class FakeDevicesClient:
        def types_list(self, **kwargs):
            captured["types_list_kwargs"] = kwargs
            return SimpleNamespace(
                results=[SimpleNamespace(id=42, name="Tracker")],
                count=1,
                next=None,
            )

        def types_partial(self, device_type_id, body):
            installer_path = body["installer"]
            captured["types_partial"] = {
                "id": device_type_id,
                "installer_name": installer_path.name,
                "installer_exists": installer_path.exists(),
            }
            return {"id": int(device_type_id), "installer": "uploaded"}

    class FakeControlClient:
        devices = FakeDevicesClient()

        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(list=self.devices.types_list)

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device-type", "upload-installer-tar"])

    assert result.exit_code == 0
    assert captured["types_list_kwargs"] == {
        "archived": False,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["types_partial"]["id"] == "42"
    assert captured["types_partial"]["installer_name"].endswith(".tar.gz")
    assert captured["types_partial"]["installer_exists"] is True
    assert renderer.render_calls == [{"id": 42, "installer": "uploaded"}]


def test_resource_autocomplete_returns_matching_labels(monkeypatch):
    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is DeviceType
            return _resource_methods(
                list=lambda **kwargs: (
                    kwargs
                    == {
                        "archived": False,
                        "ordering": "name",
                        "page": 1,
                        "per_page": 100,
                    },
                    SimpleNamespace(
                        results=[
                            SimpleNamespace(id=12, name="Alpha Sensor"),
                            SimpleNamespace(id=27, name="Beta Tracker"),
                        ],
                        count=2,
                        next=None,
                    ),
                )[-1]
            )

    monkeypatch.setattr(
        "doover_cli.utils.crud.lookup.get_control_lookup_completion_client",
        lambda ctx: FakeControlClient(),
    )

    items = crud.resource_autocomplete(
        DeviceType,
        archived=False,
        ordering="name",
    )(
        click.Context(click.Command("archive")),
        [],
        "beta",
    )

    assert items == [("Beta Tracker (27)", "ID 27")]
