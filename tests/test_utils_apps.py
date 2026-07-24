import json

import pytest
import typer
from pydoover.models.control import Application
from pydoover.models.control._base import _MODEL_REGISTRY

from doover_cli.utils import apps as apps_utils
from doover_cli.utils.apps import LocalApplication, get_app_config


def test_local_application_does_not_replace_control_application_registry():
    assert _MODEL_REGISTRY["Application"] is Application


def test_get_app_config_returns_local_application_and_resolves_paths(tmp_path):
    src_dir = tmp_path / "src" / "tracker_app"
    src_dir.mkdir(parents=True)
    readme = tmp_path / "README.md"
    readme.write_text("Long description from file")
    config_path = tmp_path / "doover_config.json"
    config_path.write_text(
        json.dumps(
            {
                "tracker-app": {
                    "id": 101,
                    "key": "tracker-app",
                    "name": "tracker-app",
                    "display_name": "Tracker App",
                    "description": "A tracker app",
                    "long_description": "README.md",
                    "type": "DEV",
                    "visibility": "PRI",
                    "allow_many": False,
                    "depends_on": [],
                    "organisation_id": 17,
                    "container_registry_profile_id": 22,
                    "image_name": "ghcr.io/getdoover/tracker-app:main",
                    "build_args": "--platform linux/amd64",
                    "generate_ui": False,
                    "config_schema": {"type": "object"},
                    "staging_config": {"id": 404},
                }
            }
        )
    )

    app_config = get_app_config(tmp_path)

    assert isinstance(app_config, LocalApplication)
    assert app_config.long_description == "Long description from file"
    assert app_config.organisation.id == 17
    assert app_config.container_registry_profile.id == 22
    assert app_config.src_directory == src_dir
    assert app_config.staging_config == {"id": 404}
    assert app_config.generate_ui is False


def test_get_app_config_caches_explicit_app_name(monkeypatch, tmp_path):
    config_path = tmp_path / "doover_config.json"
    config_path.write_text(
        json.dumps(
            {
                "vega_level_sensor": {
                    "name": "vega_level_sensor",
                    "type": "DEV",
                    "config_schema": {"type": "object"},
                },
                "farm_water_dashboard": {
                    "name": "farm_water_dashboard",
                    "type": "DEV",
                    "config_schema": {"type": "object"},
                },
            }
        )
    )

    def fail_select(*args, **kwargs):
        raise AssertionError("questionary.select should not be called")

    monkeypatch.setattr(apps_utils.questionary, "select", fail_select)

    explicit_config = get_app_config(tmp_path, app_name="farm_water_dashboard")
    cached_config = get_app_config(tmp_path)

    assert explicit_config.name == "farm_water_dashboard"
    assert cached_config.name == "farm_water_dashboard"


def test_get_app_config_rejects_unknown_explicit_app_name(
    monkeypatch, tmp_path, capsys
):
    config_path = tmp_path / "doover_config.json"
    config_path.write_text(
        json.dumps(
            {
                "vega_level_sensor": {
                    "name": "vega_level_sensor",
                    "type": "DEV",
                    "config_schema": {"type": "object"},
                },
                "farm_water_dashboard": {
                    "name": "farm_water_dashboard",
                    "type": "DEV",
                    "config_schema": {"type": "object"},
                },
            }
        )
    )

    def fail_select(*args, **kwargs):
        raise AssertionError("questionary.select should not be called")

    monkeypatch.setattr(apps_utils.questionary, "select", fail_select)

    with pytest.raises(typer.Exit) as exc:
        get_app_config(tmp_path, app_name="missing_app")

    assert exc.value.exit_code == 1
    output = capsys.readouterr().out
    assert "Application configuration 'missing_app' was not found" in output


def test_get_app_config_rejects_unknown_explicit_app_name_with_single_app(
    tmp_path, capsys
):
    config_path = tmp_path / "doover_config.json"
    config_path.write_text(
        json.dumps(
            {
                "tracker-app": {
                    "name": "tracker-app",
                    "type": "DEV",
                    "config_schema": {"type": "object"},
                },
            }
        )
    )

    with pytest.raises(typer.Exit) as exc:
        get_app_config(tmp_path, app_name="missing_app")

    assert exc.value.exit_code == 1
    output = capsys.readouterr().out
    assert "Application configuration 'missing_app' was not found" in output
    assert "Available applications: tracker-app." in output


def test_local_application_custom_deployment_folder(tmp_path):
    deployment_dir = tmp_path / "my_deploy"
    deployment_dir.mkdir()
    (deployment_dir / "artifact.txt").write_text("payload")

    app_config = LocalApplication(
        id=101,
        name="tracker-app",
        display_name="Tracker App",
        description="A tracker app",
        type="DEV",
        visibility="PRI",
        depends_on=[],
        organisation=17,
        container_registry_profile=22,
        image_name="ghcr.io/getdoover/tracker-app:main",
        config_schema={"type": "object"},
        base_path=tmp_path,
        deployment_folder="my_deploy",
    )

    payload = app_config.to_request_payload(include_deployment_data=True)
    assert isinstance(payload["deployment_data"], str)
    assert payload["deployment_data"]

    # Verify it persists in config dict
    config = app_config.to_config_dict()
    assert config["deployment_folder"] == "my_deploy"


def test_local_application_default_deployment_folder_not_in_config(tmp_path):
    app_config = LocalApplication(
        id=101,
        name="tracker-app",
        display_name="Tracker App",
        description="A tracker app",
        type="DEV",
        visibility="PRI",
        depends_on=[],
        organisation=17,
        container_registry_profile=22,
        image_name="ghcr.io/getdoover/tracker-app:main",
        config_schema={"type": "object"},
        base_path=tmp_path,
    )

    # Default "deployment" folder name should not appear in config
    config = app_config.to_config_dict()
    assert "deployment_folder" not in config


def test_local_application_to_request_payload_uses_control_shape(tmp_path):
    deployment_dir = tmp_path / "deployment"
    deployment_dir.mkdir()
    (deployment_dir / "artifact.txt").write_text("payload")

    app_config = LocalApplication(
        id=101,
        name="tracker-app",
        display_name="Tracker App",
        description="A tracker app",
        type="DEV",
        visibility="PRI",
        allow_many=False,
        depends_on=[],
        organisation=17,
        container_registry_profile=22,
        image_name="ghcr.io/getdoover/tracker-app:main",
        config_schema={"type": "object"},
        staging_config={
            "image_name": "ghcr.io/getdoover/tracker-app:staging",
            "id": 404,
            "build_args": "ignored-local-only",
        },
        base_path=tmp_path,
    )

    payload = app_config.to_request_payload(
        include_deployment_data=True,
        is_staging=True,
    )

    assert payload["organisation_id"] == 17
    assert payload["container_registry_profile_id"] == 22
    assert payload["image_name"] == "ghcr.io/getdoover/tracker-app:staging"
    assert "id" not in payload
    assert "build_args" not in payload
    assert isinstance(payload["deployment_data"], str)
    assert payload["deployment_data"]


def test_from_config_requires_only_name(tmp_path):
    """`name` is the upsert key, so it is the one field the CLI insists on.
    Everything else is optional here; the control plane still rejects a create
    that is missing something it requires."""
    payload = LocalApplication.from_config({"name": "tracker-app"}, tmp_path)

    assert payload.to_request_payload() == {"name": "tracker-app"}


def test_from_config_only_publishes_fields_the_file_declares(tmp_path):
    """doover_config.json is a patch: a field it omits must not be published as
    the attribute's default, or every publish would clobber the cloud."""
    app_config = LocalApplication.from_config(
        {"name": "tracker-app", "display_name": "Tracker App"}, tmp_path
    )

    payload = app_config.to_request_payload()

    assert payload["display_name"] == "Tracker App"
    # Omitted => absent, rather than sent as the False/None fallback the
    # constructor applied. organisation_id is the one that bites: publishing used
    # to null out the app's owning org on every run.
    for field in ("allow_many", "organisation_id", "container_registry_profile_id"):
        assert field not in payload, field


def test_from_config_distinguishes_explicit_null_from_omitted(tmp_path):
    """Omitting a field and setting it to null are different instructions: null
    means clear it, and `to_version` drops Nones so it has to be restored."""
    declared = LocalApplication.from_config(
        {"name": "tracker-app", "organisation_id": None, "icon_url": None}, tmp_path
    ).to_request_payload()

    assert declared["organisation_id"] is None
    assert declared["icon_url"] is None

    omitted = LocalApplication.from_config({"name": "tracker-app"}, tmp_path)
    assert "organisation_id" not in omitted.to_request_payload()


def test_from_config_accepts_legacy_organisation_spelling(tmp_path):
    app_config = LocalApplication.from_config(
        {"name": "tracker-app", "owner_org_id": 17}, tmp_path
    )

    assert app_config.to_request_payload()["organisation_id"] == 17


def test_from_config_normalises_legacy_spelling_of_an_explicit_null(tmp_path):
    app_config = LocalApplication.from_config(
        {"name": "tracker-app", "owner_org_id": None}, tmp_path
    )

    assert app_config.to_request_payload()["organisation_id"] is None


def test_retired_fields_are_never_published(tmp_path):
    """lambda_arn and stars are cloud-owned; a stale committed lambda_arn used to
    be publishable and could repoint the app at the wrong function."""
    app_config = LocalApplication.from_config(
        {
            "name": "tracker-app",
            "lambda_arn": "arn:aws:lambda:ap-southeast-2:1:function:stale",
            "stars": 99,
            "repo_branch": "main",
            "code_repo_id": 5,
        },
        tmp_path,
    )

    payload = app_config.to_request_payload()

    for field in ("lambda_arn", "stars", "repo_branch", "code_repo_id"):
        assert field not in payload, field
