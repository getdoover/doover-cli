"""Tests for `doover app migrate`.

The assertions are written against the two repos this was built from --
warning-manager and analog-level-sensor -- because between them they cover every
shape the migration has to handle: a single container app with a staging
override, and a container app sharing a config with a lambda processor.
"""

import json
import subprocess
from types import SimpleNamespace

import pytest
import typer

from doover_cli.apps.migrate import (
    WORKFLOW_TEMPLATE,
    DEFAULT_WORKFLOW_REF,
    REGISTRY_PROFILE_IDS,
    migrate,
    migrate_config,
    migrate_entry,
)


def _entry(**kwargs):
    return {"type": "DEV", "name": "my_app", **kwargs}


class TestMigrateEntry:
    def test_image_moves_to_the_doover_registry(self):
        migrated = migrate_entry(_entry(image_name="spaneng/my-app:main"), "my_app")
        assert migrated["image_name"] == "registry.doover.com/apps/my_app:main"

    def test_image_tag_is_preserved(self):
        migrated = migrate_entry(
            _entry(image_name="ghcr.io/getdoover/my-app:v2"), "my_app"
        )
        assert migrated["image_name"] == "registry.doover.com/apps/my_app:v2"

    def test_untagged_image_gets_the_default_tag(self):
        migrated = migrate_entry(_entry(image_name="spaneng/my-app"), "my_app")
        assert migrated["image_name"] == "registry.doover.com/apps/my_app:main"

    def test_generated_schemas_are_dropped(self):
        """The Python is the source of truth; a committed copy is stale."""
        migrated = migrate_entry(
            _entry(config_schema={"type": "object"}, ui_schema={}), "my_app"
        )
        assert "config_schema" not in migrated
        assert "ui_schema" not in migrated

    def test_retired_and_obsolete_fields_are_dropped(self):
        migrated = migrate_entry(
            _entry(
                key=None,
                code_repo_id=None,
                repo_branch="main",
                lambda_arn="arn:aws:lambda:...",
                container_registry_profile_id=167096593252662276,
            ),
            "my_app",
        )
        for field in (
            "key",
            "code_repo_id",
            "repo_branch",
            "lambda_arn",
            "container_registry_profile_id",
        ):
            assert field not in migrated

    def test_legacy_org_spelling_is_renamed(self):
        migrated = migrate_entry(_entry(owner_org_id=123), "my_app")
        assert migrated["organisation_id"] == 123
        assert "owner_org_id" not in migrated

    def test_canonical_org_wins_over_the_legacy_spelling(self):
        migrated = migrate_entry(
            _entry(owner_org_id=123, organisation_id=456), "my_app"
        )
        assert migrated["organisation_id"] == 456

    def test_explicit_null_org_is_kept(self):
        """Null clears the owning org -- a real instruction, unlike the noise fields."""
        migrated = migrate_entry(_entry(organisation_id=None), "my_app")
        assert "organisation_id" in migrated
        assert migrated["organisation_id"] is None

    def test_staging_config_keeps_only_the_id(self):
        """Both environments run the same image, so staging overrides nothing else."""
        migrated = migrate_entry(
            _entry(
                image_name="spaneng/my-app:main",
                staging_config={
                    "id": 192511730373402881,
                    "image_name": "registry.staging.udoover.com/apps/my_app:main",
                    "organisation_id": None,
                    "container_registry_profile_id": "192511156613587204",
                },
            ),
            "my_app",
        )
        assert migrated["staging_config"] == {"id": 192511730373402881}

    def test_staging_config_is_dropped_when_it_says_nothing(self):
        migrated = migrate_entry(
            _entry(staging_config={"organisation_id": None}), "my_app"
        )
        assert "staging_config" not in migrated

    def test_processor_without_an_image_keeps_none(self):
        """A lambda has no image, so there is nothing to point at a registry."""
        migrated = migrate_entry(
            {
                "type": "PRO",
                "name": "my_app_processor",
                "image_name": None,
                "lambda_config": {"Runtime": "python3.13"},
            },
            "my_app_processor",
        )
        assert "image_name" not in migrated
        assert migrated["lambda_config"] == {"Runtime": "python3.13"}

    def test_unrecognised_fields_are_kept(self):
        migrated = migrate_entry(_entry(something_new="keep me"), "my_app")
        assert migrated["something_new"] == "keep me"

    def test_name_defaults_to_the_config_key(self):
        migrated = migrate_entry({"type": "DEV"}, "my_app")
        assert migrated["name"] == "my_app"

    def test_is_idempotent(self):
        once = migrate_entry(
            _entry(image_name="spaneng/my-app:main", config_schema={}), "my_app"
        )
        assert migrate_entry(once, "my_app") == once


class TestMigrateConfig:
    def test_non_app_entries_pass_through(self):
        """`type` marks an app entry, matching get_app_config."""
        data = {"my_app": _entry(), "some_other_key": {"hello": "world"}}
        assert migrate_config(data)["some_other_key"] == {"hello": "world"}


def _write_config(root, data, *, builds_image=True):
    (root / "doover_config.json").write_text(json.dumps(data, indent=4) + "\n")
    if builds_image:
        # discover_apps decides whether the shared workflow would publish this
        # repo at all, and it reads the filesystem rather than the config.
        (root / "Dockerfile").touch()
        (root / "pyproject.toml").touch()


def _write_workflow(root, name, content):
    path = root / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestMigrateCommand:
    def test_rewrites_config_and_replaces_workflows(self, tmp_path):
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})
        _write_workflow(
            tmp_path, "build-image.yml", "uses: docker/build-push-action@v6"
        )
        _write_workflow(tmp_path, "run-tests.yml", "run: uv run pytest tests")

        migrate(tmp_path, registry_profile=False, trusted_publisher=False)

        data = json.loads((tmp_path / "doover_config.json").read_text())
        assert data["my_app"]["image_name"] == "registry.doover.com/apps/my_app:main"

        workflows = tmp_path / ".github" / "workflows"
        assert not (workflows / "build-image.yml").exists()
        assert not (workflows / "run-tests.yml").exists()
        assert (workflows / "doover-app.yml").read_text() == WORKFLOW_TEMPLATE.format(
            ref=DEFAULT_WORKFLOW_REF
        )

    def test_unrelated_workflows_are_left_alone(self, tmp_path):
        """Only files that are both named and shaped like the legacy ones go."""
        _write_config(tmp_path, {"my_app": _entry()})
        _write_workflow(tmp_path, "release-docs.yml", "run: mkdocs build")
        # Name matches, content doesn't: someone else's workflow that happens to
        # share a name.
        _write_workflow(tmp_path, "run-tests.yml", "run: cargo insta test")

        migrate(tmp_path, registry_profile=False, trusted_publisher=False)

        workflows = tmp_path / ".github" / "workflows"
        assert (workflows / "release-docs.yml").exists()
        assert (workflows / "run-tests.yml").exists()

    def test_workflow_ref_is_configurable(self, tmp_path):
        _write_config(tmp_path, {"my_app": _entry()})

        migrate(
            tmp_path,
            workflow_ref="getdoover/workflows/.github/workflows/app.yml@v1",
            registry_profile=False,
            trusted_publisher=False,
        )

        content = (tmp_path / ".github" / "workflows" / "doover-app.yml").read_text()
        assert "app.yml@v1" in content

    def test_no_workflows_leaves_ci_alone(self, tmp_path):
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})
        _write_workflow(
            tmp_path, "build-image.yml", "uses: docker/build-push-action@v6"
        )

        migrate(
            tmp_path, workflows=False, registry_profile=False, trusted_publisher=False
        )

        workflows = tmp_path / ".github" / "workflows"
        assert (workflows / "build-image.yml").exists()
        assert not (workflows / "doover-app.yml").exists()

    def test_dry_run_writes_nothing(self, tmp_path):
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})
        path = _write_workflow(tmp_path, "build-image.yml", "run: uv run pytest")
        before = (tmp_path / "doover_config.json").read_text()

        migrate(tmp_path, dry_run=True, registry_profile=False, trusted_publisher=False)

        assert (tmp_path / "doover_config.json").read_text() == before
        assert path.exists()
        assert not (tmp_path / ".github" / "workflows" / "doover-app.yml").exists()

    def test_migrates_every_config_in_a_monorepo(self, tmp_path):
        for name in ("first", "second"):
            app_dir = tmp_path / name
            app_dir.mkdir()
            _write_config(
                app_dir, {name: _entry(name=name, image_name=f"spaneng/{name}")}
            )

        migrate(tmp_path, registry_profile=False, trusted_publisher=False)

        for name in ("first", "second"):
            data = json.loads((tmp_path / name / "doover_config.json").read_text())
            assert data[name]["image_name"] == f"registry.doover.com/apps/{name}:main"

    def test_running_twice_changes_nothing(self, tmp_path):
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})
        migrate(tmp_path, registry_profile=False, trusted_publisher=False)
        after_first = (tmp_path / "doover_config.json").read_text()

        migrate(tmp_path, registry_profile=False, trusted_publisher=False)

        assert (tmp_path / "doover_config.json").read_text() == after_first

    def test_a_processor_only_repo_moves_onto_the_shared_workflow(self, tmp_path):
        """The ewon shape: a repo of processors, released by a hand-rolled
        workflow. The shared workflow publishes package apps, so it replaces it."""
        _write_config(
            tmp_path,
            {"my_processor": {"type": "PRO", "name": "my_processor"}},
            builds_image=False,
        )
        _write_workflow(tmp_path, "deploy.yml", "run: doover app publish")
        _write_workflow(tmp_path, "run-tests.yml", "run: uv run pytest")

        migrate(tmp_path, registry_profile=False, trusted_publisher=False)

        workflows = tmp_path / ".github" / "workflows"
        assert not (workflows / "deploy.yml").exists()
        assert not (workflows / "run-tests.yml").exists()
        assert (workflows / "doover-app.yml").exists()

    def test_a_workflow_a_survivor_still_calls_is_kept(self, tmp_path):
        """Deleting a reusable workflow out from under its caller breaks the
        caller rather than retiring it."""
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})
        _write_workflow(
            tmp_path, "nightly-soak.yml", "uses: ./.github/workflows/run-tests.yml"
        )
        _write_workflow(tmp_path, "run-tests.yml", "run: uv run pytest")
        _write_workflow(tmp_path, "run-linting.yml", "run: ruff check")

        migrate(tmp_path, registry_profile=False, trusted_publisher=False)

        workflows = tmp_path / ".github" / "workflows"
        assert (workflows / "run-tests.yml").exists()
        # Nothing surviving calls this one, so it goes.
        assert not (workflows / "run-linting.yml").exists()

    def test_exits_when_there_is_no_config(self, tmp_path):
        with pytest.raises(typer.Exit):
            migrate(tmp_path, registry_profile=False, trusted_publisher=False)


class _FakeApplications:
    def __init__(self):
        self.patched = []

    def partial(self, app_id, body):
        self.patched.append((app_id, body))


class _FakeClient:
    def __init__(self):
        self.applications = _FakeApplications()


@pytest.fixture
def fake_control(monkeypatch):
    """Stand in for a logged-in control plane, on production by default."""
    from doover_cli.apps import apps as apps_module

    client = _FakeClient()
    monkeypatch.setattr(apps_module, "get_state", lambda: (client, None))
    monkeypatch.setattr(apps_module, "_resolve_staging", lambda staging: False)
    monkeypatch.setattr(
        apps_module, "_resolve_application_id", lambda c, config, staging: 42
    )
    return client


@pytest.fixture
def fake_publishers(monkeypatch, tmp_path):
    """A control plane with no publishers registered, and a git remote to
    register one for."""
    from doover_cli.apps import migrate as migrate_module

    calls = {"get": [], "post": [], "patch": [], "existing": []}

    def request(
        session,
        method,
        *,
        publisher_id=None,
        params=None,
        body=None,
        organisation_id=None,
    ):
        if method == "GET":
            calls["get"].append(organisation_id)
            return {"results": list(calls["existing"])}
        if method == "PATCH":
            calls["patch"].append((publisher_id, body))
            return {"id": publisher_id}
        calls["post"].append((body, organisation_id))
        return {"id": 999}

    monkeypatch.setattr(migrate_module, "_publisher_request", request)
    monkeypatch.setattr(
        migrate_module, "_github_repository", lambda root: ("getdoover", "my-app")
    )
    # The publisher endpoint is reached through the session's auth rather than
    # the control client, so it needs standing in for separately.
    monkeypatch.setattr(
        migrate_module, "state", SimpleNamespace(session=object()), raising=False
    )
    return calls


class TestTrustedPublisher:
    def test_registers_the_repo_and_links_the_app(
        self, tmp_path, fake_control, fake_publishers
    ):
        _write_config(
            tmp_path,
            {"my_app": _entry(image_name="spaneng/my-app:main", organisation_id=7)},
        )

        migrate(tmp_path, workflows=False, registry_profile=False)

        assert fake_publishers["post"] == [
            (
                {
                    "provider": "GH",
                    "repository_owner": "getdoover",
                    "repository_name": "my-app",
                    # Matching is on the workflow filename, so it must be the one
                    # the migration writes.
                    "workflow": "doover-app.yml",
                },
                7,
            )
        ]
        assert fake_control.applications.patched == [("42", {"publisher_id": "999"})]

    def test_an_existing_publisher_is_reused(
        self, tmp_path, fake_control, fake_publishers, monkeypatch
    ):
        fake_publishers["existing"].append(
            {
                "id": 123,
                "provider": "GH",
                "repository_owner": "getdoover",
                "repository_name": "my-app",
                "workflow": ".github/workflows/doover-app.yml",
            }
        )
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})

        migrate(tmp_path, workflows=False, registry_profile=False)

        assert fake_publishers["post"] == []
        assert fake_control.applications.patched == [("42", {"publisher_id": "123"})]

    def test_a_publisher_for_a_deleted_workflow_is_moved_not_duplicated(
        self, tmp_path, fake_control, fake_publishers
    ):
        """The ewon shape: trust was granted to deploy.yml, which the migration
        renames. Leaving it behind would orphan the trust for every app on it."""
        fake_publishers["existing"].append(
            {
                "id": 197158785976905729,
                "provider": "GH",
                "repository_owner": "getdoover",
                "repository_name": "my-app",
                "workflow": "deploy.yml",
            }
        )
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})

        migrate(tmp_path, workflows=False, registry_profile=False)

        assert fake_publishers["patch"] == [
            (197158785976905729, {"workflow": "doover-app.yml"})
        ]
        assert fake_publishers["post"] == []

    def test_a_publisher_whose_workflow_still_exists_is_left_alone(
        self, tmp_path, fake_control, fake_publishers
    ):
        """A repo may publish different apps from different workflows, so an
        unrelated live workflow is not this migration's to repoint."""
        _write_workflow(tmp_path, "other-app.yml", "run: doover app publish")
        fake_publishers["existing"].append(
            {
                "id": 555,
                "provider": "GH",
                "repository_owner": "getdoover",
                "repository_name": "my-app",
                "workflow": "other-app.yml",
            }
        )
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})

        migrate(tmp_path, workflows=False, registry_profile=False)

        assert fake_publishers["patch"] == []
        assert len(fake_publishers["post"]) == 1

    def test_one_publisher_covers_every_app_in_the_repo(
        self, tmp_path, fake_control, fake_publishers
    ):
        """They publish from the same workflow, so a second would state the same
        trust twice."""
        _write_config(
            tmp_path,
            {
                "my_app": _entry(image_name="spaneng/my-app:main"),
                "my_processor": {"type": "PRO", "name": "my_processor"},
            },
        )

        migrate(tmp_path, workflows=False, registry_profile=False)

        assert len(fake_publishers["post"]) == 1
        assert len(fake_control.applications.patched) == 2

    def test_a_repo_with_no_github_remote_is_skipped(
        self, tmp_path, fake_control, monkeypatch
    ):
        from doover_cli.apps import migrate as migrate_module

        monkeypatch.setattr(migrate_module, "_github_repository", lambda root: None)
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})

        migrate(tmp_path, workflows=False, registry_profile=False)

        assert fake_control.applications.patched == []


class TestGithubRepository:
    """Parsing the remote, which is where the publisher's identity comes from."""

    def test_reads_the_origin_remote(self, tmp_path):
        from doover_cli.apps.migrate import _github_repository

        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:getdoover/ewon.git"],
            cwd=tmp_path,
            check=True,
        )

        assert _github_repository(tmp_path) == ("getdoover", "ewon")

    def test_https_remotes_parse_too(self, tmp_path):
        from doover_cli.apps.migrate import _github_repository

        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/getdoover/ewon"],
            cwd=tmp_path,
            check=True,
        )

        assert _github_repository(tmp_path) == ("getdoover", "ewon")

    def test_a_non_github_remote_is_not_a_publisher(self, tmp_path):
        from doover_cli.apps.migrate import _github_repository

        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@gitlab.com:acme/thing.git"],
            cwd=tmp_path,
            check=True,
        )

        assert _github_repository(tmp_path) is None


class TestRegistryProfilePatch:
    def test_points_the_app_at_the_doover_registry(self, tmp_path, fake_control):
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})

        migrate(tmp_path, workflows=False, trusted_publisher=False)

        assert fake_control.applications.patched == [
            ("42", {"container_registry_profile_id": REGISTRY_PROFILE_IDS[False]})
        ]

    def test_uses_the_staging_profile_on_staging(
        self, tmp_path, fake_control, monkeypatch
    ):
        from doover_cli.apps import apps as apps_module

        monkeypatch.setattr(apps_module, "_resolve_staging", lambda staging: True)
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})

        migrate(tmp_path, workflows=False, trusted_publisher=False)

        assert fake_control.applications.patched == [
            ("42", {"container_registry_profile_id": REGISTRY_PROFILE_IDS[True]})
        ]

    def test_apps_without_an_image_are_skipped(self, tmp_path, fake_control):
        """A processor pulls no image, so no registry profile applies to it."""
        _write_config(
            tmp_path,
            {"my_app_processor": {"type": "PRO", "name": "my_app_processor"}},
        )

        migrate(tmp_path, workflows=False, trusted_publisher=False)

        assert fake_control.applications.patched == []

    def test_runs_even_when_the_files_are_already_migrated(
        self, tmp_path, fake_control
    ):
        """The control plane is the other half, and each environment is separate."""
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})
        migrate(
            tmp_path, workflows=False, registry_profile=False, trusted_publisher=False
        )

        migrate(tmp_path, workflows=False, trusted_publisher=False)

        assert len(fake_control.applications.patched) == 1

    def test_dry_run_patches_nothing(self, tmp_path, fake_control):
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})

        migrate(tmp_path, workflows=False, dry_run=True, trusted_publisher=False)

        assert fake_control.applications.patched == []

    def test_a_failed_patch_does_not_undo_the_file_migration(
        self, tmp_path, fake_control, monkeypatch
    ):
        from doover_cli.apps import apps as apps_module

        def boom(*args, **kwargs):
            raise RuntimeError("not logged in")

        monkeypatch.setattr(apps_module, "get_state", boom)
        _write_config(tmp_path, {"my_app": _entry(image_name="spaneng/my-app:main")})

        migrate(tmp_path, workflows=False, trusted_publisher=False)

        data = json.loads((tmp_path / "doover_config.json").read_text())
        assert data["my_app"]["image_name"] == "registry.doover.com/apps/my_app:main"
