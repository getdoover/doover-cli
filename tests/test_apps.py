from contextlib import nullcontext
from types import SimpleNamespace

from typer.testing import CliRunner

from doover_cli import app
from doover_cli.apps import apps as apps_app

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


class FakeAppConfig:
    def __init__(
        self,
        *,
        app_id=None,
        name="tracker-app",
        image_name="ghcr.io/getdoover/tracker-app:main",
    ):
        self.id = app_id
        self.name = name
        self.build_args = "--platform linux/amd64"
        self.image_name = image_name
        self.type = "DEV"
        self.staging_config = {}
        self.save_calls = 0
        self._payload = {
            "id": app_id,
            "name": name,
            "display_name": "Tracker App",
            "description": "A tracker app",
            "long_description": "Long description",
            "type": "DEV",
            "visibility": "PRI",
            "allow_many": False,
            "config_schema": {"type": "object"},
            "depends_on": [],
            "organisation_id": 17,
            "container_registry_profile_id": 22,
            "image_name": image_name,
            "lambda_config": {"mode": "manual"},
            "icon_url": "https://example.com/icon.png",
            "banner_url": "https://example.com/banner.png",
        }

    def to_request_payload(self, *, include_deployment_data, is_staging, method="POST"):
        payload = dict(self._payload)
        if include_deployment_data:
            payload["deployment_data"] = "staging-data" if is_staging else "from-config"
        return payload

    def to_dict(self, *, include_deployment_data, is_staging, include_cloud_only):
        return self.to_request_payload(
            include_deployment_data=include_deployment_data,
            is_staging=is_staging,
        )

    def save_to_disk(self):
        self.save_calls += 1


def test_app_list_passes_all_filters(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeApplicationsClient:
        def list(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": []}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        [
            "app",
            "list",
            "--allow-many",
            "true",
            "--approx-installs",
            "5",
            "--approx-installs-gt",
            "4",
            "--approx-installs-gte",
            "5",
            "--approx-installs-lt",
            "9",
            "--approx-installs-lte",
            "10",
            "--archived",
            "false",
            "--container-registry-profile",
            "22",
            "--description",
            "tracker",
            "--description-contains",
            "rack",
            "--description-icontains",
            "TRACK",
            "--display-name",
            "Tracker App",
            "--display-name-contains",
            "acker",
            "--display-name-icontains",
            "TRACKER",
            "--id",
            "42",
            "--name",
            "tracker-app",
            "--name-contains",
            "track",
            "--name-icontains",
            "TRACK",
            "--ordering",
            "-stars",
            "--organisation",
            "17",
            "--page",
            "2",
            "--per-page",
            "25",
            "--search",
            "solar",
            "--stars",
            "3",
            "--stars-gt",
            "2",
            "--stars-gte",
            "3",
            "--stars-lt",
            "5",
            "--stars-lte",
            "4",
            "--type",
            "DEV",
            "--visibility",
            "PRI",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"] == {
        "allow_many": True,
        "approx_installs": 5,
        "approx_installs__gt": 4,
        "approx_installs__gte": 5,
        "approx_installs__lt": 9,
        "approx_installs__lte": 10,
        "archived": False,
        "container_registry_profile": "22",
        "description": "tracker",
        "description__contains": "rack",
        "description__icontains": "TRACK",
        "display_name": "Tracker App",
        "display_name__contains": "acker",
        "display_name__icontains": "TRACKER",
        "id": 42,
        "name": "tracker-app",
        "name__contains": "track",
        "name__icontains": "TRACK",
        "ordering": "-stars",
        "organisation": "17",
        "page": 2,
        "per_page": 25,
        "search": "solar",
        "stars": 3,
        "stars__gt": 2,
        "stars__gte": 3,
        "stars__lt": 5,
        "stars__lte": 4,
        "type": "DEV",
        "visibility": "PRI",
    }
    assert renderer.render_list_calls == [{"results": []}]


def test_app_get_renders_response(monkeypatch):
    renderer = FakeRenderer()

    class FakeApplicationsClient:
        @staticmethod
        def retrieve(application_id):
            assert application_id == "55"
            return {"id": 55, "name": "tracker-app"}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["app", "get", "55"])

    assert result.exit_code == 0
    assert renderer.render_calls == [{"id": 55, "name": "tracker-app"}]


def test_app_get_accepts_name_lookup(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[SimpleNamespace(id=99, name="tracker-app")],
                        count=1,
                        next=None,
                    ),
                )[-1]
            )

        class applications:
            @staticmethod
            def retrieve(application_id):
                captured["application_id"] = application_id
                return {"id": 99}

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["app", "get", "tracker-app (99)"])

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": False,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["application_id"] == "99"
    assert renderer.render_calls == [{"id": 99}]


def test_app_update_help_lists_generated_options():
    result = runner.invoke(app, ["app", "update", "--help"])

    assert result.exit_code == 0
    assert "--display-name" in result.stdout
    assert "--organisation-id" in result.stdout
    assert "--container-registry-profile-" in result.stdout


def test_app_update_with_options_patches_payload(monkeypatch):
    captured = {}
    renderer = FakeRenderer()

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            return _resource_methods(
                get=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("interactive fetch should not be used")
                ),
                patch=lambda application_id, payload: (
                    captured.setdefault("application_id", application_id),
                    captured.setdefault("payload", payload),
                    {"id": 55},
                )[-1],
                put=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("PATCH should be used")
                ),
            )

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(
        app,
        [
            "app",
            "update",
            "55",
            "--display-name",
            "Updated Tracker",
            "--description",
            "Updated description",
            "--organisation-id",
            "17",
            "--container-registry-profile-id",
            "22",
        ],
    )

    assert result.exit_code == 0
    assert captured["application_id"] == "55"
    assert captured["payload"] == {
        "display_name": "Updated Tracker",
        "description": "Updated description",
        "organisation_id": 17,
        "container_registry_profile_id": 22,
    }
    assert renderer.render_calls == [{"id": 55}]


def test_app_archive_prompts_when_id_missing(monkeypatch):
    captured = {}
    renderer = FakeRenderer(prompt_answers={"resource_id": "Tracker App (27)"})

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[SimpleNamespace(id=27, display_name="Tracker App")],
                        count=1,
                        next=None,
                    ),
                )[-1]
            )

        class applications:
            @staticmethod
            def archive(application_id):
                captured["application_id"] = application_id
                return {"id": 27, "archived": True}

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["app", "archive"])

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": False,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["application_id"] == "27"
    assert renderer.render_calls == [{"id": 27, "archived": True}]


def test_app_unarchive_prompts_when_id_missing(monkeypatch):
    captured = {}
    renderer = FakeRenderer(prompt_answers={"resource_id": "Tracker App (27)"})

    class FakeControlClient:
        def get_control_methods(self, model_cls):
            return _resource_methods(
                list=lambda **kwargs: (
                    captured.setdefault("list_kwargs", kwargs),
                    SimpleNamespace(
                        results=[SimpleNamespace(id=27, display_name="Tracker App")],
                        count=1,
                        next=None,
                    ),
                )[-1]
            )

        class applications:
            @staticmethod
            def unarchive(application_id):
                captured["application_id"] = application_id
                return {"id": 27, "archived": False}

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state",
        lambda: (FakeControlClient(), renderer),
    )

    result = runner.invoke(app, ["app", "unarchive"])

    assert result.exit_code == 0
    assert captured["list_kwargs"] == {
        "archived": True,
        "ordering": "name",
        "page": 1,
        "per_page": 100,
    }
    assert captured["application_id"] == "27"
    assert renderer.render_calls == [{"id": 27, "archived": False}]


def test_app_publish_updates_existing_application(monkeypatch, tmp_path):
    captured = {}
    renderer = FakeRenderer()
    app_config = FakeAppConfig(app_id=101)

    class FakeApplicationsClient:
        @staticmethod
        def partial(application_id, body):
            captured["partial"] = (application_id, body)
            return {"id": int(application_id), "published": True}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_directory", lambda root=None: tmp_path
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_config", lambda root_fp: app_config
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state", lambda: (FakeControlClient(), renderer)
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.export_config_command",
        lambda ctx, app_fp, validate_: captured.setdefault(
            "exported", (app_fp, validate_)
        ),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._build_container",
        lambda root_fp, **kwargs: captured.setdefault("build", (root_fp, kwargs)),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._push_container",
        lambda image_name: captured.setdefault("push", image_name),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.typer.confirm",
        lambda message, abort=True: captured.setdefault("confirm", message) or True,
    )

    result = runner.invoke(app, ["app", "publish", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["exported"] == (tmp_path, True)
    assert captured["build"] == (
        tmp_path,
        {
            "buildx": True,
            "build_args": "--platform linux/amd64",
            "image_name": "ghcr.io/getdoover/tracker-app:main",
        },
    )
    assert captured["push"] == "ghcr.io/getdoover/tracker-app:main"
    assert captured["partial"][0] == "101"
    assert captured["partial"][1]["organisation_id"] == 17
    assert captured["partial"][1]["container_registry_profile_id"] == 22
    assert "build ghcr.io/getdoover/tracker-app:main" in captured["confirm"]
    assert renderer.render_calls == [{"id": 101, "published": True}]


def test_app_publish_creates_then_updates_when_missing(monkeypatch, tmp_path):
    captured = {}
    renderer = FakeRenderer()
    app_config = FakeAppConfig(app_id=None)

    class FakeApplicationsClient:
        @staticmethod
        def list(**kwargs):
            captured["list_kwargs"] = kwargs
            return SimpleNamespace(results=[], count=0, next=None)

        @staticmethod
        def create(body):
            captured["create_body"] = body
            return SimpleNamespace(id=202)

        @staticmethod
        def partial(application_id, body):
            captured["partial"] = (application_id, body)
            return {"id": 202}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_directory", lambda root=None: tmp_path
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_config", lambda root_fp: app_config
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state", lambda: (FakeControlClient(), renderer)
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.export_config_command",
        lambda ctx, app_fp, validate_: None,
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._build_container", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("doover_cli.apps.apps._push_container", lambda image_name: None)
    monkeypatch.setattr(
        "doover_cli.apps.apps.typer.confirm",
        lambda *args, **kwargs: True,
    )

    result = runner.invoke(app, ["app", "publish", str(tmp_path)])

    assert result.exit_code == 0
    if "list_kwargs" in captured:
        assert captured["list_kwargs"] == {
            "name": "tracker-app",
            "archived": False,
            "page": 1,
            "per_page": 100,
        }
    assert captured["create_body"]["name"] == "tracker-app"
    assert captured["partial"][0] == "202"
    assert app_config.id == 202
    assert app_config.save_calls == 1
    assert renderer.render_calls == [{"id": 202}]


def test_app_publish_skip_container_avoids_build_and_push(monkeypatch, tmp_path):
    captured = {}
    renderer = FakeRenderer()
    app_config = FakeAppConfig(app_id=101)

    class FakeApplicationsClient:
        @staticmethod
        def partial(application_id, body):
            captured["partial"] = (application_id, body)
            return {"id": 101}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_directory", lambda root=None: tmp_path
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_config", lambda root_fp: app_config
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state", lambda: (FakeControlClient(), renderer)
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.export_config_command",
        lambda ctx, app_fp, validate_: None,
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._build_container",
        lambda *args, **kwargs: captured.setdefault("build_called", True),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._push_container",
        lambda *args, **kwargs: captured.setdefault("push_called", True),
    )

    result = runner.invoke(app, ["app", "publish", str(tmp_path), "--skip-container"])

    assert result.exit_code == 0
    assert "build_called" not in captured
    assert "push_called" not in captured
    assert captured["partial"][0] == "101"


def test_app_publish_rejects_fix_me_values(monkeypatch, tmp_path):
    renderer = FakeRenderer()
    app_config = FakeAppConfig(app_id=101)
    app_config._payload["organisation_id"] = "FIX-ME"

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_directory", lambda root=None: tmp_path
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_config", lambda root_fp: app_config
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state",
        lambda: (_resource_methods(applications=None), renderer),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.export_config_command",
        lambda ctx, app_fp, validate_: None,
    )

    result = runner.invoke(app, ["app", "publish", str(tmp_path), "--skip-container"])

    assert result.exit_code == 2


def test_app_publish_honours_explicit_staging(monkeypatch, tmp_path):
    captured = {}
    renderer = FakeRenderer()
    app_config = FakeAppConfig(app_id=101)
    app_config.staging_config["id"] = 404

    class FakeApplicationsClient:
        @staticmethod
        def partial(application_id, body):
            captured["body"] = body
            return {"id": 101}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_directory", lambda root=None: tmp_path
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_config", lambda root_fp: app_config
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state", lambda: (FakeControlClient(), renderer)
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.export_config_command",
        lambda ctx, app_fp, validate_: None,
    )

    result = runner.invoke(
        app, ["app", "publish", str(tmp_path), "--skip-container", "--staging"]
    )

    assert result.exit_code == 0
    assert captured["body"]["deployment_data"] == "staging-data"
    assert renderer.render_calls == [{"id": 101}]


def test_app_publish_infers_staging_from_control_url(monkeypatch, tmp_path):
    captured = {}
    renderer = FakeRenderer()
    app_config = FakeAppConfig(app_id=101)
    app_config.staging_config["id"] = 404

    class FakeApplicationsClient:
        @staticmethod
        def partial(application_id, body):
            captured["application_id"] = application_id
            captured["body"] = body
            return {"id": 101}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_directory", lambda root=None: tmp_path
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_config", lambda root_fp: app_config
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state", lambda: (FakeControlClient(), renderer)
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.export_config_command",
        lambda ctx, app_fp, validate_: None,
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._control_base_url",
        lambda: "https://api.staging.udoover.com",
    )

    result = runner.invoke(app, ["app", "publish", str(tmp_path), "--skip-container"])

    assert result.exit_code == 0
    assert captured["body"]["deployment_data"] == "staging-data"
    assert captured["application_id"] == "404"


def test_app_publish_skips_build_when_requested_by_config(monkeypatch, tmp_path):
    captured = {}
    renderer = FakeRenderer()
    app_config = FakeAppConfig(app_id=101)
    app_config.build_args = "NO_BUILD"

    class FakeApplicationsClient:
        @staticmethod
        def partial(application_id, body):
            captured["partial"] = (application_id, body)
            return {"id": 101}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_directory", lambda root=None: tmp_path
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_config", lambda root_fp: app_config
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state", lambda: (FakeControlClient(), renderer)
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.export_config_command",
        lambda ctx, app_fp, validate_: None,
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._build_container",
        lambda *args, **kwargs: captured.setdefault("build_called", True),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._push_container",
        lambda *args, **kwargs: captured.setdefault("push_called", True),
    )

    result = runner.invoke(app, ["app", "publish", str(tmp_path)])

    assert result.exit_code == 0
    assert "build_called" not in captured
    assert "push_called" not in captured
    assert renderer.render_calls == [{"id": 101}]


def test_app_publish_processor_builds_package_and_releases_version(
    monkeypatch, tmp_path
):
    captured = {}
    renderer = FakeRenderer()
    app_config = FakeAppConfig(app_id=303)
    app_config.type = "PRO"
    package_fp = tmp_path / "package.zip"
    package_fp.write_bytes(b"zip-bytes")

    class FakeApplicationsClient:
        @staticmethod
        def processor_source(application_id, body):
            captured["application_id"] = application_id
            captured["body"] = body
            return {"id": 303}

        @staticmethod
        def processor_version(application_id, body):
            captured["version"] = (application_id, body)
            return {"id": 303, "versioned": True}

        @staticmethod
        def partial(application_id, body):
            captured["partial"] = (application_id, body)
            return {"id": 303}

    class FakeControlClient:
        applications = FakeApplicationsClient()

    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_directory", lambda root=None: tmp_path
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_app_config", lambda root_fp: app_config
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.get_state", lambda: (FakeControlClient(), renderer)
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.export_config_command",
        lambda ctx, app_fp, validate_: None,
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps.shell_run",
        lambda command, cwd=None: captured.setdefault("build_script", (command, cwd)),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._build_container",
        lambda *args, **kwargs: captured.setdefault("build_called", True),
    )
    monkeypatch.setattr(
        "doover_cli.apps.apps._push_container",
        lambda *args, **kwargs: captured.setdefault("push_called", True),
    )

    result = runner.invoke(app, ["app", "publish", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["build_script"] == ("./build.sh", tmp_path)
    assert captured["application_id"] == "303"
    assert captured["body"] == {"file": package_fp}
    assert captured["version"][0] == "303"
    assert "build_called" not in captured
    assert "push_called" not in captured
    assert renderer.render_calls == [{"id": 303, "versioned": True}]


def test_publish_processor_package_uses_package_zip(tmp_path):
    package_fp = tmp_path / "package.zip"
    package_fp.write_bytes(b"zip-bytes")
    captured = {}

    class FakeApplicationsClient:
        @staticmethod
        def processor_source(application_id, body):
            captured["application_id"] = application_id
            captured["body"] = body
            return {"id": 303}

    client = SimpleNamespace(applications=FakeApplicationsClient())

    response = apps_app._publish_processor_package(
        client,
        303,
        tmp_path,
    )

    assert response == {"id": 303}
    assert captured["application_id"] == "303"
    assert captured["body"] == {"file": package_fp}
