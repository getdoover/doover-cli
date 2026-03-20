from contextlib import nullcontext
from types import SimpleNamespace

from typer.testing import CliRunner

from doover_cli import app

runner = CliRunner()


class FakeRenderer:
    def __init__(self):
        self.render_calls = []
        self.render_list_calls = []

    def loading(self, _message):
        return nullcontext()

    def render(self, data):
        self.render_calls.append(data)

    def render_list(self, data):
        self.render_list_calls.append(data)


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

    class FakeDevicesClient:
        def types_create(self, payload):
            captured["payload"] = payload
            return {"id": 123}

    class FakeControlClient:
        devices = FakeDevicesClient()

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )
    monkeypatch.setattr(
        "doover_cli.apps.device_type._prompt_create_fields",
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
    assert captured["payload"] == {
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
    renderer = FakeRenderer()
    installer = tmp_path / "prompt-installer.sh"
    installer.write_text("#!/bin/sh\necho prompt\n")

    class FakePage:
        def __init__(self, results):
            self.results = results
            self.count = len(results)
            self.next = None

    class FakeSolutionsClient:
        def list(self, **kwargs):
            captured["solution_list_kwargs"] = kwargs
            return FakePage([SimpleNamespace(id=9, display_name="Field Ops")])

    class FakeDevicesClient:
        def types_create(self, payload):
            captured["payload"] = payload
            return {"id": 456}

    class FakeControlClient:
        devices = FakeDevicesClient()
        solutions = FakeSolutionsClient()

    class FakeQuestion:
        def __init__(self, answer):
            self.answer = answer

        def unsafe_ask(self):
            return self.answer

    text_answers = iter(
        [
            "Prompted Tracker",
            '{"mode":"prompt"}',
            "",
            "",
            str(installer),
            "install.sh",
            "",
            "Prompt description",
            "",
            "",
            "7",
            "",
        ]
    )

    monkeypatch.setattr(
        "doover_cli.apps.device_type.get_state",
        lambda: (FakeControlClient(), renderer),
    )
    monkeypatch.setattr(
        "doover_cli.apps.device_type.questionary.text",
        lambda *args, **kwargs: FakeQuestion(next(text_answers)),
    )

    def fake_select(*args, **kwargs):
        captured["select_kwargs"] = kwargs
        return FakeQuestion(9)

    monkeypatch.setattr(
        "doover_cli.apps.device_type.questionary.select",
        fake_select,
    )

    result = runner.invoke(app, ["device-type", "create"])

    assert result.exit_code == 0
    assert captured["solution_list_kwargs"] == {
        "archived": False,
        "ordering": "display_name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["select_kwargs"]["use_search_filter"] is True
    assert captured["select_kwargs"]["use_jk_keys"] is False
    assert captured["payload"] == {
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
