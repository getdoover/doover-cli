import re
from contextlib import nullcontext
from types import SimpleNamespace

from pydoover.models.control import Application, ApplicationInstallationSolution, Device
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


class FakeAppInstallsClient:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"results": []}

    def retrieve(self, app_install_id):
        self.calls.append(("retrieve", app_install_id))
        return SimpleNamespace(
            id=int(app_install_id),
            name="tracker",
            display_name="Tracker",
            application=SimpleNamespace(id=17),
            device=SimpleNamespace(id=23),
            version="1.0.0",
            deployment_config={"mode": "auto"},
            config_profiles=[SimpleNamespace(id=31), SimpleNamespace(id=32)],
            solution=SimpleNamespace(id=44),
        )

    def create(self, body):
        self.calls.append(("create", body))
        return {"id": 55, **body}

    def partial(self, app_install_id, body):
        self.calls.append(("partial", app_install_id, body))
        return {"id": int(app_install_id), **body}

    def archive(self, app_install_id):
        self.calls.append(("archive", app_install_id))
        return {"id": int(app_install_id), "archived": True}

    def unarchive(self, app_install_id):
        self.calls.append(("unarchive", app_install_id))
        return {"id": int(app_install_id), "archived": False}

    def delete(self, app_install_id):
        self.calls.append(("delete", app_install_id))

    def deployments_create(self, parent_lookup_app_install):
        self.calls.append(("deployments_create", parent_lookup_app_install))
        return {"created": True}

    def deployments_list(self, **kwargs):
        self.calls.append(("deployments_list", kwargs))
        return {"results": []}

    def deployments_retrieve(self, **kwargs):
        self.calls.append(("deployments_retrieve", kwargs))
        return {"id": int(kwargs["id"])}

    def sync_config_profiles(self, app_install_id, body):
        self.calls.append(("sync_config_profiles", app_install_id, body))
        return {"id": int(app_install_id), **body}


def _fake_state(monkeypatch, renderer=None, client=None):
    renderer = renderer or FakeRenderer()
    app_installs = FakeAppInstallsClient()

    class FakeApplicationsClient:
        def installs_list(self, **kwargs):
            app_installs.calls.append(("applications.installs_list", kwargs))
            return {"results": []}

        def retrieve(self, application_id):
            return SimpleNamespace(
                id=int(application_id),
                display_name="Tracker App",
                name="tracker-app",
                config_schema={
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "title": "Mode"},
                        "retries": {"type": "integer"},
                        "enabled": {"type": "boolean"},
                    },
                },
            )

    class FakeDevicesClient:
        def app_installs_list(self, **kwargs):
            app_installs.calls.append(("devices.app_installs_list", kwargs))
            return {"results": []}

    class FakeControlClient:
        def __init__(self):
            self.app_installs = app_installs
            self.applications = FakeApplicationsClient()
            self.devices = FakeDevicesClient()

        def get_control_methods(self, model_cls):
            if model_cls is Application:
                return SimpleNamespace(
                    list=lambda **kwargs: SimpleNamespace(
                        results=[
                            SimpleNamespace(id=17, display_name="Tracker App", name="tracker-app")
                        ],
                        count=1,
                        next=None,
                    )
                )
            if model_cls is Device:
                return SimpleNamespace(
                    list=lambda **kwargs: SimpleNamespace(
                        results=[
                            SimpleNamespace(id=23, display_name="Tracker Device", name="tracker-device")
                        ],
                        count=1,
                        next=None,
                    )
                )
            if model_cls is ApplicationInstallationSolution:
                return SimpleNamespace(
                    list=lambda **kwargs: SimpleNamespace(
                        results=[SimpleNamespace(id=44, name="Default Solution")],
                        count=1,
                        next=None,
                    )
                )
            raise AssertionError(f"Unexpected model: {model_cls}")

    fake_client = client or FakeControlClient()
    monkeypatch.setattr(
        "doover_cli.apps.app_install.get_state",
        lambda: (fake_client, renderer),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state",
        lambda: (fake_client, renderer),
    )
    monkeypatch.setattr(
        "doover_cli.apps.device.get_state",
        lambda: (fake_client, renderer),
    )
    return fake_client, renderer, app_installs


def test_root_help_lists_app_install_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "app-install" in result.stdout


def test_app_install_help_lists_subcommands():
    result = runner.invoke(app, ["app-install", "--help"])

    assert result.exit_code == 0
    output = _strip_ansi(result.stdout)
    for command in [
        "list",
        "get",
        "create",
        "update",
        "archive",
        "unarchive",
        "delete",
        "deploy",
        "deployments",
        "deployment",
        "sync-config-profiles",
    ]:
        assert command in output


def test_app_install_list_passes_filters(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "app-install",
            "list",
            "--application",
            "17",
            "--archived",
            "false",
            "--device",
            "23",
            "--display-name",
            "Tracker",
            "--display-name-contains",
            "rack",
            "--display-name-icontains",
            "TRACK",
            "--id",
            "55",
            "--name",
            "tracker",
            "--name-contains",
            "track",
            "--name-icontains",
            "TRACK",
            "--ordering",
            "-display_name",
            "--organisation",
            "9",
            "--organisation-isnull",
            "no",
            "--page",
            "2",
            "--per-page",
            "25",
            "--search",
            "solar",
            "--solution",
            "44",
            "--status",
            "deployed",
            "--template",
            "71",
            "--version",
            "1.0.0",
            "--version-contains",
            "1.0",
            "--version-icontains",
            "MAIN",
        ],
    )

    assert result.exit_code == 0
    assert app_installs.calls == [
        (
            "list",
            {
                "application": "17",
                "archived": False,
                "device": "23",
                "display_name": "Tracker",
                "display_name__contains": "rack",
                "display_name__icontains": "TRACK",
                "id": 55,
                "name": "tracker",
                "name__contains": "track",
                "name__icontains": "TRACK",
                "ordering": "-display_name",
                "organisation": "9",
                "organisation__isnull": False,
                "page": 2,
                "per_page": 25,
                "search": "solar",
                "solution": "44",
                "status": "deployed",
                "template": "71",
                "version": "1.0.0",
                "version__contains": "1.0",
                "version__icontains": "MAIN",
            },
        )
    ]
    assert renderer.render_list_calls == [{"results": []}]


def test_app_install_get_renders_response(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(app, ["app-install", "get", "55"])

    assert result.exit_code == 0
    assert app_installs.calls[0] == ("retrieve", "55")
    assert renderer.render_calls[0].id == 55


def test_app_install_create_builds_payload(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "app-install",
            "create",
            "--display-name",
            "Tracker",
            "--name",
            "tracker",
            "--application",
            "17",
            "--device",
            "23",
            "--version",
            "1.0.0",
            "--deployment-config",
            '{"mode":"auto"}',
            "--config-profile-id",
            "31",
            "--config-profile-id",
            "32",
            "--solution",
            "44",
        ],
    )

    assert result.exit_code == 0
    assert app_installs.calls[0] == (
        "create",
        {
            "name": "tracker",
            "display_name": "Tracker",
            "application_id": 17,
            "device_id": 23,
            "version": "1.0.0",
            "deployment_config": {"mode": "auto"},
            "config_profile_ids": [31, 32],
            "solution_id": 44,
        },
    )
    assert renderer.render_calls[0]["id"] == 55


def test_app_install_create_with_no_schema_prompts_when_required_fields_missing(
    monkeypatch,
):
    renderer = FakeRenderer(
        {
            "display_name": "Prompted Tracker",
            "application": "Tracker App (17)",
            "device": "Tracker Device (23)",
            "name": "prompted",
            "deployment_config": '{"mode":"manual"}',
            "config_profile_ids": "31,32",
            "solution": "Default Solution (44)",
        }
    )
    _, _, app_installs = _fake_state(monkeypatch, renderer=renderer)

    result = runner.invoke(app, ["app-install", "create", "--no-schema"])

    assert result.exit_code == 0
    prompted_fields = renderer.prompt_fields_calls[0]
    application_field = next(field for field in prompted_fields if field.key == "application")
    device_field = next(field for field in prompted_fields if field.key == "device")
    solution_field = next(field for field in prompted_fields if field.key == "solution")
    assert application_field.kind == "resource"
    assert application_field.resource_lookup_choices == [
        LookupChoice(
            id=17,
            label="Tracker App (17)",
            search_values=("Tracker App (17)", "17", "Tracker App", "tracker-app"),
            field_values={"display_name": "Tracker App", "name": "tracker-app"},
        )
    ]
    assert device_field.kind == "resource"
    assert device_field.resource_lookup_choices == [
        LookupChoice(
            id=23,
            label="Tracker Device (23)",
            search_values=(
                "Tracker Device (23)",
                "23",
                "Tracker Device",
                "tracker-device",
            ),
            field_values={"display_name": "Tracker Device", "name": "tracker-device"},
        )
    ]
    assert solution_field.kind == "resource"
    assert solution_field.resource_lookup_choices == [
        LookupChoice(
            id=44,
            label="Default Solution (44)",
            search_values=("Default Solution (44)", "44", "Default Solution"),
            field_values={"name": "Default Solution"},
        )
    ]
    assert app_installs.calls[0][1]["display_name"] == "Prompted Tracker"
    assert app_installs.calls[0][1]["application_id"] == 17
    assert app_installs.calls[0][1]["device_id"] == 23
    assert app_installs.calls[0][1]["deployment_config"] == {"mode": "manual"}
    assert app_installs.calls[0][1]["config_profile_ids"] == [31, 32]
    assert app_installs.calls[0][1]["solution_id"] == 44


def test_app_install_create_prompts_deployment_config_from_app_schema_by_default(
    monkeypatch,
):
    renderer = FakeRenderer(
        {
            "mode": "manual",
            "retries": "3",
            "enabled": True,
        }
    )
    _, _, app_installs = _fake_state(monkeypatch, renderer=renderer)

    result = runner.invoke(
        app,
        [
            "app-install",
            "create",
            "--display-name",
            "Tracker",
            "--application",
            "17",
            "--device",
            "23",
        ],
    )

    assert result.exit_code == 0
    assert [field.key for field in renderer.prompt_fields_calls[0]] == [
        "mode",
        "retries",
        "enabled",
    ]
    assert app_installs.calls[0] == (
        "create",
        {
            "display_name": "Tracker",
            "application_id": 17,
            "device_id": 23,
            "deployment_config": {
                "mode": "manual",
                "retries": 3,
                "enabled": True,
            },
        },
    )


def test_app_install_create_falls_back_when_solution_lookup_unavailable(monkeypatch):
    renderer = FakeRenderer(
        {
            "resource_id": "Tracker Device (23)",
            "display_name": "Prompted Tracker",
            "application": "Tracker App (17)",
            "device": "Tracker Device (23)",
            "solution": "44",
        }
    )

    class FakeApplicationsClient:
        def installs_list(self, **kwargs):
            return {"results": []}

    class FakeDevicesClient:
        def app_installs_list(self, **kwargs):
            return {"results": []}

    app_installs = FakeAppInstallsClient()

    class FakeControlClient:
        def __init__(self):
            self.app_installs = app_installs
            self.applications = FakeApplicationsClient()
            self.devices = FakeDevicesClient()

        def get_control_methods(self, model_cls):
            if model_cls is Application:
                return SimpleNamespace(
                    list=lambda **kwargs: SimpleNamespace(
                        results=[
                            SimpleNamespace(
                                id=17,
                                display_name="Tracker App",
                                name="tracker-app",
                            )
                        ],
                        count=1,
                        next=None,
                    )
                )
            if model_cls is Device:
                return SimpleNamespace(
                    list=lambda **kwargs: SimpleNamespace(
                        results=[
                            SimpleNamespace(
                                id=23,
                                display_name="Tracker Device",
                                name="tracker-device",
                            )
                        ],
                        count=1,
                        next=None,
                    )
                )
            if model_cls is ApplicationInstallationSolution:
                raise KeyError("No control methods found for model 'ApplicationInstallationSolution'.")
            raise AssertionError(f"Unexpected model: {model_cls}")

    _fake_state(monkeypatch, renderer=renderer, client=FakeControlClient())

    result = runner.invoke(app, ["device", "app-installs", "create", "--no-schema"])

    assert result.exit_code == 0
    prompted_fields = renderer.prompt_fields_calls[1]
    solution_field = next(field for field in prompted_fields if field.key == "solution")
    assert solution_field.kind == "text"
    assert solution_field.resource_lookup_choices is None
    assert app_installs.calls[0][1]["solution_id"] == 44


def test_app_install_update_with_flags_sends_partial_payload(monkeypatch):
    _, _, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "app-install",
            "update",
            "55",
            "--display-name",
            "Updated",
            "--application",
            "18",
            "--config-profile-id",
            "40",
            "--no-schema",
        ],
    )

    assert result.exit_code == 0
    assert app_installs.calls[0] == (
        "partial",
        "55",
        {
            "display_name": "Updated",
            "application_id": 18,
            "config_profile_ids": [40],
        },
    )


def test_app_install_update_with_no_schema_prompts_and_submits_changes(monkeypatch):
    renderer = FakeRenderer(
        {
            "display_name": "Updated Tracker",
            "name": "tracker",
            "application": 17,
            "device": 23,
            "version": "1.0.0",
            "deployment_config": {"mode": "auto"},
            "config_profile_ids": "31,32",
            "solution": 44,
        }
    )
    _, _, app_installs = _fake_state(monkeypatch, renderer=renderer)

    result = runner.invoke(app, ["app-install", "update", "55", "--no-schema"])

    assert result.exit_code == 0
    assert app_installs.calls[0] == ("retrieve", "55")
    assert app_installs.calls[1] == (
        "partial",
        "55",
        {"display_name": "Updated Tracker"},
    )


def test_app_install_update_uses_application_config_schema_by_default(monkeypatch):
    renderer = FakeRenderer(
        {
            "display_name": "Tracker",
            "name": "tracker",
            "application": 17,
            "device": 23,
            "version": "1.0.0",
            "config_profile_ids": "31,32",
            "solution": 44,
            "mode": "manual",
            "retries": "5",
            "enabled": True,
        }
    )
    _, _, app_installs = _fake_state(monkeypatch, renderer=renderer)

    result = runner.invoke(app, ["app-install", "update", "55"])

    assert result.exit_code == 0
    assert app_installs.calls[0] == ("retrieve", "55")
    assert [field.key for field in renderer.prompt_fields_calls[0]] == [
        "name",
        "display_name",
        "application",
        "version",
        "device",
        "config_profile_ids",
        "solution",
    ]
    assert [field.key for field in renderer.prompt_fields_calls[1]] == [
        "mode",
        "retries",
        "enabled",
    ]
    assert app_installs.calls[1] == (
        "partial",
        "55",
        {
            "deployment_config": {
                "mode": "manual",
                "retries": 5,
                "enabled": True,
            }
        },
    )


def test_app_install_archive_unarchive_and_delete(monkeypatch):
    _, _, app_installs = _fake_state(monkeypatch)

    archive_result = runner.invoke(app, ["app-install", "archive", "55"])
    unarchive_result = runner.invoke(app, ["app-install", "unarchive", "55"])
    delete_prompt_result = runner.invoke(
        app, ["app-install", "delete", "55"], input="n\n"
    )
    delete_result = runner.invoke(app, ["app-install", "delete", "55", "--yes"])

    assert archive_result.exit_code == 0
    assert unarchive_result.exit_code == 0
    assert delete_prompt_result.exit_code != 0
    assert delete_result.exit_code == 0
    assert ("archive", "55") in app_installs.calls
    assert ("unarchive", "55") in app_installs.calls
    assert app_installs.calls.count(("delete", "55")) == 1
    assert "Deleted app install 55." in delete_result.stdout


def test_app_install_deployment_commands(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    deploy_result = runner.invoke(app, ["app-install", "deploy", "55"])
    deployments_result = runner.invoke(
        app,
        [
            "app-install",
            "deployments",
            "55",
            "--ordering",
            "-created_at",
            "--page",
            "2",
            "--per-page",
            "5",
            "--search",
            "done",
        ],
    )
    deployment_result = runner.invoke(app, ["app-install", "deployment", "55", "99"])

    assert deploy_result.exit_code == 0
    assert deployments_result.exit_code == 0
    assert deployment_result.exit_code == 0
    assert ("deployments_create", "55") in app_installs.calls
    assert (
        "deployments_list",
        {
            "parent_lookup_app_install": "55",
            "ordering": "-created_at",
            "page": 2,
            "per_page": 5,
            "search": "done",
        },
    ) in app_installs.calls
    assert (
        "deployments_retrieve",
        {"id": "99", "parent_lookup_app_install": "55"},
    ) in app_installs.calls
    assert renderer.render_calls[-1] == {"id": 99}


def test_app_install_sync_config_profiles(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "app-install",
            "sync-config-profiles",
            "55",
            "--config-profile-id",
            "40",
            "--config-profile-id",
            "41",
        ],
    )

    assert result.exit_code == 0
    assert app_installs.calls[-1] == (
        "sync_config_profiles",
        "55",
        {
            "name": "tracker",
            "display_name": "Tracker",
            "application_id": 17,
            "device_id": 23,
            "version": "1.0.0",
            "deployment_config": {"mode": "auto"},
            "config_profile_ids": [40, 41],
            "solution_id": 44,
        },
    )
    assert renderer.render_calls[-1]["config_profile_ids"] == [40, 41]


def test_nested_app_installs_list(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(app, ["app", "installs", "list", "10", "--archived", "true"])

    assert result.exit_code == 0
    assert app_installs.calls == [
        (
            "applications.installs_list",
            {
                "parent_lookup_application": "10",
                "device": None,
                "archived": True,
                "display_name": None,
                "display_name__contains": None,
                "display_name__icontains": None,
                "id": None,
                "name": None,
                "name__contains": None,
                "name__icontains": None,
                "ordering": None,
                "organisation": None,
                "organisation__isnull": None,
                "page": None,
                "per_page": None,
                "search": None,
                "solution": None,
                "status": None,
                "template": None,
                "version": None,
                "version__contains": None,
                "version__icontains": None,
            },
        )
    ]
    assert renderer.render_list_calls == [{"results": []}]


def test_nested_app_installs_help_lists_subcommands():
    result = runner.invoke(app, ["app", "installs", "--help"])

    assert result.exit_code == 0
    output = _strip_ansi(result.stdout)
    for command in [
        "list",
        "get",
        "create",
        "update",
        "archive",
        "unarchive",
        "delete",
        "deploy",
        "deployments",
        "deployment",
        "sync-config-profiles",
    ]:
        assert command in output


def test_nested_app_installs_create_uses_application_context(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "app",
            "installs",
            "create",
            "10",
            "--display-name",
            "Tracker",
            "--device",
            "20",
        ],
    )

    assert result.exit_code == 0
    assert app_installs.calls[0] == (
        "create",
        {
            "display_name": "Tracker",
            "application_id": 10,
            "device_id": 20,
        },
    )
    assert renderer.render_calls[0]["id"] == 55


def test_nested_app_installs_create_prompt_omits_application_field(monkeypatch):
    renderer = FakeRenderer(
        {
            "display_name": "Tracker",
            "device": "Tracker Device (23)",
        }
    )
    _, _, app_installs = _fake_state(monkeypatch, renderer=renderer)

    result = runner.invoke(app, ["app", "installs", "create", "10"])

    assert result.exit_code == 0
    prompted_fields = renderer.prompt_fields_calls[0]
    assert {field.key for field in prompted_fields}
    assert "application" not in {field.key for field in prompted_fields}
    assert "device" in {field.key for field in prompted_fields}
    assert app_installs.calls[0][1]["application_id"] == 10


def test_nested_app_installs_deploy_uses_application_context(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(app, ["app", "installs", "deploy", "10", "55"])

    assert result.exit_code == 0
    assert ("deployments_create", "55") in app_installs.calls
    assert renderer.render_calls[-1] == {"created": True}


def test_nested_device_app_installs_list(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(
        app, ["device", "app-installs", "list", "20", "--application", "10"]
    )

    assert result.exit_code == 0
    assert app_installs.calls == [
        (
            "devices.app_installs_list",
            {
                "parent_lookup_device": "20",
                "application": "10",
                "archived": None,
                "display_name": None,
                "display_name__contains": None,
                "display_name__icontains": None,
                "id": None,
                "name": None,
                "name__contains": None,
                "name__icontains": None,
                "ordering": None,
                "organisation": None,
                "organisation__isnull": None,
                "page": None,
                "per_page": None,
                "search": None,
                "solution": None,
                "status": None,
                "template": None,
                "version": None,
                "version__contains": None,
                "version__icontains": None,
            },
        )
    ]
    assert renderer.render_list_calls == [{"results": []}]


def test_nested_device_app_installs_help_lists_subcommands():
    result = runner.invoke(app, ["device", "app-installs", "--help"])

    assert result.exit_code == 0
    output = _strip_ansi(result.stdout)
    for command in [
        "list",
        "get",
        "create",
        "update",
        "archive",
        "unarchive",
        "delete",
        "deploy",
        "deployments",
        "deployment",
        "sync-config-profiles",
    ]:
        assert command in output


def test_nested_device_app_installs_create_uses_device_context(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(
        app,
        [
            "device",
            "app-installs",
            "create",
            "20",
            "--display-name",
            "Tracker",
            "--application",
            "10",
        ],
    )

    assert result.exit_code == 0
    assert app_installs.calls[0] == (
        "create",
        {
            "display_name": "Tracker",
            "application_id": 10,
            "device_id": 20,
        },
    )
    assert renderer.render_calls[0]["id"] == 55


def test_nested_device_app_installs_create_prompt_omits_device_field(monkeypatch):
    renderer = FakeRenderer(
        {
            "resource_id": "Tracker Device (23)",
            "display_name": "Tracker",
            "application": "Tracker App (17)",
        }
    )
    _, _, app_installs = _fake_state(monkeypatch, renderer=renderer)

    result = runner.invoke(app, ["device", "app-installs", "create"])

    assert result.exit_code == 0
    prompted_fields = renderer.prompt_fields_calls[1]
    assert "device" not in {field.key for field in prompted_fields}
    assert "application" in {field.key for field in prompted_fields}
    assert app_installs.calls[0][1]["device_id"] == 23


def test_nested_device_app_installs_deploy_uses_device_context(monkeypatch):
    _, renderer, app_installs = _fake_state(monkeypatch)

    result = runner.invoke(app, ["device", "app-installs", "deploy", "20", "55"])

    assert result.exit_code == 0
    assert ("deployments_create", "55") in app_installs.calls
    assert renderer.render_calls[-1] == {"created": True}
