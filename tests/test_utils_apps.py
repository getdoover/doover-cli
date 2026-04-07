import json

from doover_cli.utils.apps import LocalApplication, get_app_config


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


def test_local_application_save_to_disk_persists_local_fields(tmp_path):
    config_path = tmp_path / "doover_config.json"
    config_path.write_text(json.dumps({"tracker-app": {}}))

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
        build_args="--platform linux/amd64",
        config_schema={"type": "object"},
        staging_config={"id": 404},
        base_path=tmp_path,
    )

    app_config.save_to_disk()

    saved = json.loads(config_path.read_text())["tracker-app"]
    assert saved["id"] == 101
    assert saved["organisation_id"] == 17
    assert saved["container_registry_profile_id"] == 22
    assert saved["build_args"] == "--platform linux/amd64"
    assert saved["staging_config"] == {"id": 404}


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
