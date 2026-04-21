import re
from contextlib import nullcontext
from types import SimpleNamespace

from pydoover.models.control import Device, DeviceType, Group, Location
from typer.testing import CliRunner

from doover_cli import app
from doover_cli.utils.crud import LookupChoice

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


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


def test_device_list_passes_all_filters(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeDevicesClient:
        def list(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": []}

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        [
            "device",
            "list",
            "--application",
            "17",
            "--archived",
            "true",
            "--display-name",
            "Tracker 1",
            "--display-name-contains",
            "ack",
            "--display-name-icontains",
            "TRACK",
            "--group",
            "88",
            "--group-tree",
            "root",
            "--id",
            "42",
            "--id",
            "84",
            "--name",
            "tracker-1",
            "--name-contains",
            "rack",
            "--name-icontains",
            "TRAC",
            "--ordering",
            "-display_name",
            "--organisation",
            "org-1",
            "--page",
            "3",
            "--per-page",
            "25",
            "--search",
            "solar",
            "--type",
            "device-type-7",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"] == {
        "application": "17",
        "archived": True,
        "display_name": "Tracker 1",
        "display_name__contains": "ack",
        "display_name__icontains": "TRACK",
        "group": "88",
        "group_tree": "root",
        "id": [42, 84],
        "name": "tracker-1",
        "name__contains": "rack",
        "name__icontains": "TRAC",
        "ordering": "-display_name",
        "organisation": "org-1",
        "page": 3,
        "per_page": 25,
        "search": "solar",
        "type": "device-type-7",
    }
    assert renderer.render_list_calls == [{"results": []}]


def test_device_create_builds_payload(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is Device
            return _resource_methods(
                post=lambda payload: (
                    captured.setdefault("payload", payload),
                    {"id": 123},
                )[-1],
            )

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
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
            "device",
            "create",
            "--name",
            "tracker-1",
            "--display-name",
            "Tracker 1",
            "--type-id",
            "7",
            "--group-id",
            "8",
            "--fa-icon",
            "router",
            "--notes",
            "Field device",
            "--extra-config",
            '{"mode":"auto"}',
            "--fixed-location",
            '{"latitude": 1.5, "longitude": 2.5}',
            "--solution-config",
            '{"profile":"solar"}',
        ],
    )

    assert result.exit_code == 0
    assert isinstance(captured["payload"], Device)
    assert captured["payload"].to_version(
        "DeviceSerializerDetailRequest",
        method="POST",
    ) == {
        "name": "tracker-1",
        "display_name": "Tracker 1",
        "type_id": 7,
        "group_id": 8,
        "fa_icon": "router",
        "notes": "Field device",
        "extra_config": {"mode": "auto"},
        "fixed_location": {"latitude": 1.5, "longitude": 2.5},
        "solution_config": {"profile": "solar"},
    }
    assert renderer.render_calls == [{"id": 123}]


def test_device_create_prompts_for_missing_required_fields(monkeypatch):
    captured = {}
    renderer = FakeRenderer(
        prompt_answers={
            "display_name": "Prompted Tracker",
            "type": "Field Type (9)",
            "group": "Main Group (11)",
            "fixed_location": '{"latitude": 1.5, "longitude": 2.5}',
        }
    )

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            if model_cls is DeviceType:
                return _resource_methods(
                    list=lambda **kwargs: (
                        captured.setdefault("type_list_kwargs", kwargs),
                        SimpleNamespace(
                            results=[SimpleNamespace(id=9, display_name="Field Type")],
                            count=1,
                            next=None,
                        ),
                    )[-1]
                )
            if model_cls is Group:
                return _resource_methods(
                    list=lambda **kwargs: (
                        captured.setdefault("group_list_kwargs", kwargs),
                        SimpleNamespace(
                            results=[SimpleNamespace(id=11, display_name="Main Group")],
                            count=1,
                            next=None,
                        ),
                    )[-1]
                )
            if model_cls is Device:
                return _resource_methods(
                    post=lambda payload: (
                        captured.setdefault("payload", payload),
                        {"id": 456},
                    )[-1],
                )
            raise AssertionError(f"Unexpected model: {model_cls}")

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "create"])

    assert result.exit_code == 0
    assert captured["type_list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["group_list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    prompted_fields = renderer.prompt_fields_calls[0]
    type_field = next(field for field in prompted_fields if field.key == "type")
    group_field = next(field for field in prompted_fields if field.key == "group")
    assert type_field.kind == "resource"
    assert group_field.kind == "resource"
    assert type_field.resource_lookup_choices == [
        LookupChoice(
            id=9,
            label="Field Type (9)",
            search_values=("Field Type (9)", "9", "Field Type"),
            field_values={"display_name": "Field Type", "name": None},
        )
    ]
    assert group_field.resource_lookup_choices == [
        LookupChoice(
            id=11,
            label="Main Group (11)",
            search_values=("Main Group (11)", "11", "Main Group"),
            field_values={"display_name": "Main Group", "name": None},
        )
    ]
    assert captured["payload"].to_version(
        "DeviceSerializerDetailRequest",
        method="POST",
    ) == {
        "display_name": "Prompted Tracker",
        "type_id": 9,
        "group_id": 11,
        "fixed_location": {"latitude": 1.5, "longitude": 2.5},
    }
    assert renderer.render_calls == [{"id": 456}]


def test_device_get_renders_response(monkeypatch):
    renderer = FakeRenderer()

    class FakeDevicesClient:
        def retrieve(self, device_id):
            assert device_id == "55"
            return {"id": 55, "display_name": "Tracker"}

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "get", "55"])

    assert result.exit_code == 0
    assert renderer.render_calls == [{"id": 55, "display_name": "Tracker"}]


def test_device_get_accepts_display_name_lookup(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is Device
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[
                            SimpleNamespace(
                                id=160631245057827589,
                                display_name="Field Tracker Alpha",
                            ),
                        ],
                        count=1,
                        next=None,
                    ),
                )[-1]
            )

        class devices:
            @staticmethod
            def retrieve(device_id):
                captured["device_id"] = device_id
                return {"id": 160631245057827589}

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        ["device", "get", "Field Tracker Alpha (160631245057827589)"],
    )

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["device_id"] == "160631245057827589"
    assert renderer.render_calls == [{"id": 160631245057827589}]


def test_device_update_with_options_patches_payload(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is Device
            return _resource_methods(
                get=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("interactive fetch should not be used")
                ),
                patch=lambda device_id, payload: (
                    captured.setdefault("device_id", device_id),
                    captured.setdefault("payload", payload),
                    {"id": 55},
                )[-1],
                put=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("PATCH should be used when available")
                ),
            )

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        [
            "device",
            "update",
            "55",
            "--display-name",
            "Updated Tracker",
            "--fixed-location",
            '{"latitude": 3.5, "longitude": 4.5}',
            "--solution-config",
            '{"mode":"manual"}',
        ],
    )

    assert result.exit_code == 0
    assert captured["device_id"] == "55"
    assert captured["payload"] == {
        "display_name": "Updated Tracker",
        "fixed_location": {"latitude": 3.5, "longitude": 4.5},
        "solution_config": {"mode": "manual"},
    }
    assert renderer.render_calls == [{"id": 55}]


def test_device_update_without_options_fetches_and_prompts(monkeypatch):
    captured = {}
    renderer = FakeRenderer(
        prompt_answers={
            "display_name": "Updated Tracker",
            "type": "New Type (11)",
            "group": "Backup Group (12)",
            "fixed_location": '{"latitude": 3.5, "longitude": 4.5}',
        }
    )

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            if model_cls is DeviceType:
                return _resource_methods(
                    list=lambda **kwargs: (
                        captured.setdefault("type_list_kwargs", kwargs),
                        SimpleNamespace(
                            results=[
                                SimpleNamespace(id=9, display_name="Current Type"),
                                SimpleNamespace(id=11, display_name="New Type"),
                            ],
                            count=2,
                            next=None,
                        ),
                    )[-1]
                )
            if model_cls is Group:
                return _resource_methods(
                    list=lambda **kwargs: (
                        captured.setdefault("group_list_kwargs", kwargs),
                        SimpleNamespace(
                            results=[
                                SimpleNamespace(id=10, display_name="Main Group"),
                                SimpleNamespace(id=12, display_name="Backup Group"),
                            ],
                            count=2,
                            next=None,
                        ),
                    )[-1]
                )
            if model_cls is Device:
                return _resource_methods(
                    get=lambda device_id: (
                        captured.setdefault("retrieved_device_id", device_id),
                        SimpleNamespace(
                            display_name="Tracker",
                            type=SimpleNamespace(id=9, display_name="Current Type"),
                            group=SimpleNamespace(id=10, display_name="Main Group"),
                            fixed_location=Location(latitude=1.5, longitude=2.5),
                        ),
                    )[-1],
                    patch=lambda device_id, payload: (
                        captured.setdefault("patched_device_id", device_id),
                        captured.setdefault("payload", payload),
                        {"id": 55, "display_name": "Updated Tracker"},
                    )[-1],
                    put=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        AssertionError("PATCH should be used when available")
                    ),
                )
            raise AssertionError(f"Unexpected model: {model_cls}")

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "update", "55"])

    assert result.exit_code == 0
    assert captured["retrieved_device_id"] == "55"
    assert captured["type_list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["group_list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    prompted_fields = renderer.prompt_fields_calls[0]
    assert (
        next(field for field in prompted_fields if field.key == "display_name").default
        == "Tracker"
    )
    assert next(
        field for field in prompted_fields if field.key == "type"
    ).default == 9
    assert next(
        field for field in prompted_fields if field.key == "group"
    ).default == 10
    assert next(
        field for field in prompted_fields if field.key == "fixed_location"
    ).default == {"latitude": 1.5, "longitude": 2.5}
    assert captured["patched_device_id"] == "55"
    assert captured["payload"] == {
        "display_name": "Updated Tracker",
        "type_id": 11,
        "group_id": 12,
        "fixed_location": {"latitude": 3.5, "longitude": 4.5},
    }
    assert renderer.render_calls == [{"id": 55, "display_name": "Updated Tracker"}]


def test_device_archive_prompts_with_renderer_when_id_missing(monkeypatch):
    captured = {}
    renderer = FakeRenderer(prompt_answers={"resource_id": "Field Tracker (27)"})

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is Device
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[
                            SimpleNamespace(id=12, display_name="Alpha Sensor"),
                            SimpleNamespace(id=27, display_name="Field Tracker"),
                        ],
                        count=2,
                        next=None,
                    ),
                )[-1]
            )

        class devices:
            @staticmethod
            def archive(device_id):
                captured["archived_id"] = device_id
                return {"id": int(device_id), "archived": True}

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "archive"])

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    field = renderer.prompt_fields_calls[0][0]
    assert field.label == "Device to archive"
    assert field.resource_lookup_choices[1].label == "Field Tracker (27)"
    assert field.match_middle is True
    assert captured["archived_id"] == "27"
    assert renderer.render_calls == [{"id": 27, "archived": True}]


def test_device_unarchive_prompts_with_renderer_when_id_missing(monkeypatch):
    captured = {}
    renderer = FakeRenderer(prompt_answers={"resource_id": "Archived Delta (91)"})

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            assert model_cls is Device
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
            def unarchive(device_id):
                captured["unarchived_id"] = device_id
                return {"id": int(device_id), "archived": False}

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "unarchive"])

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": True,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["unarchived_id"] == "91"
    assert renderer.render_calls == [{"id": 91, "archived": False}]


def test_device_installer_info_renders_response(monkeypatch):
    renderer = FakeRenderer()

    class FakeDevicesClient:
        def installer_info(self, device_id):
            assert device_id == "55"
            return {"version": "1.2.3"}

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "installer-info", "55"])

    assert result.exit_code == 0
    assert renderer.render_calls == [{"version": "1.2.3"}]


def test_device_installer_writes_default_output(monkeypatch, tmp_path):
    renderer = FakeRenderer()
    monkeypatch.chdir(tmp_path)

    class FakeDevicesClient:
        def installer(self, device_id):
            assert device_id == "42"
            return "#!/bin/sh\necho hi\n"

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "installer", "42"])

    assert result.exit_code == 0
    output_path = tmp_path / "device-installer-42.sh"
    assert output_path.read_text(encoding="utf-8") == "#!/bin/sh\necho hi\n"
    assert f"Saved installer to {output_path.resolve()}" in _strip_ansi(result.stdout)


def test_device_installer_writes_explicit_output(monkeypatch, tmp_path):
    renderer = FakeRenderer()
    output_path = tmp_path / "installer.sh"

    class FakeDevicesClient:
        def installer(self, device_id):
            assert device_id == "42"
            return "#!/bin/sh\necho hi\n"

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        ["device", "installer", "42", "--output", str(output_path)],
    )

    assert result.exit_code == 0
    assert output_path.read_text(encoding="utf-8") == "#!/bin/sh\necho hi\n"


def test_device_installer_tarball_writes_default_output(monkeypatch, tmp_path):
    renderer = FakeRenderer()
    monkeypatch.chdir(tmp_path)

    class FakeDevicesClient:
        def installer_tarball(self, device_id):
            assert device_id == "42"
            return b"tarball-bytes"

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "installer-tarball", "42"])

    assert result.exit_code == 0
    output_path = tmp_path / "device-installer-42.tar.gz"
    assert output_path.read_bytes() == b"tarball-bytes"
    assert (
        f"Saved installer tarball to {output_path.resolve()}"
        in _strip_ansi(result.stdout)
    )


def test_device_installer_zip_writes_default_output(monkeypatch, tmp_path):
    renderer = FakeRenderer()
    monkeypatch.chdir(tmp_path)

    class FakeDevicesClient:
        def installer_zip(self, device_id):
            assert device_id == "42"
            return b"zip-bytes"

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["device", "installer-zip", "42"])

    assert result.exit_code == 0
    output_path = tmp_path / "device-installer-42.zip"
    assert output_path.read_bytes() == b"zip-bytes"
    assert f"Saved installer zip to {output_path.resolve()}" in _strip_ansi(result.stdout)


def test_device_installer_downloads_fail_when_output_exists(monkeypatch, tmp_path):
    renderer = FakeRenderer()
    output_path = tmp_path / "installer.sh"
    output_path.write_text("existing", encoding="utf-8")

    class FakeDevicesClient:
        def installer(self, device_id):
            raise AssertionError("Installer should not be downloaded when file exists")

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        ["device", "installer", "42", "--output", str(output_path)],
    )

    assert result.exit_code != 0
    assert "Output file already exists" in _strip_ansi(result.output)
