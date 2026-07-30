"""Tests for application discovery.

The output is a contract: CI builds its matrix from it, and coding agents read it
to work out what a repo contains. So the assertions are about the shapes a repo can
legitimately take, each of which exists in the wild today:

  * one app, one config           (4-20ma-sensor)
  * several apps in one config    (analog-level-sensor: device + processor)
  * self-contained app dirs       (cameras/, docker_device_bridges/)
  * an app that deploys someone else's image and holds no source (cameras/rtsp_to_web_app)
"""

import json

from doover_cli.utils.apps import discover_apps


def _write(path, apps):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(apps))


def _device(**kwargs):
    return {"type": "DEV", **kwargs}


class TestDiscoverApps:
    def test_single_app_at_the_root(self, tmp_path):
        _write(tmp_path / "doover_config.json", {"foo": _device(name="foo")})
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "Dockerfile").touch()

        apps = discover_apps(tmp_path)
        assert len(apps) == 1
        assert apps[0]["dir"] == "."
        assert apps[0]["language"] == "py"
        assert apps[0]["builds_image"] is True

    def test_several_apps_in_one_config(self, tmp_path):
        """A device app and its processor, the analog-level-sensor shape."""
        _write(
            tmp_path / "doover_config.json",
            {
                "foo": _device(name="foo"),
                "foo_processor": {"type": "PRO", "name": "foo_processor"},
            },
        )
        (tmp_path / "pyproject.toml").touch()

        apps = discover_apps(tmp_path)
        assert {a["name"] for a in apps} == {"foo", "foo_processor"}
        assert {a["type"] for a in apps} == {"DEV", "PRO"}

    def test_self_contained_app_directories(self, tmp_path):
        """The cameras/ and docker_device_bridges/ shape: a config per app dir."""
        for name in ("first", "second"):
            _write(tmp_path / name / "doover_config.json", {name: _device(name=name)})
            (tmp_path / name / "pyproject.toml").touch()

        apps = discover_apps(tmp_path)
        assert sorted(a["dir"] for a in apps) == ["first", "second"]

    def test_language_is_per_directory(self, tmp_path):
        """A monorepo may hold a Rust app beside a Python one."""
        _write(tmp_path / "py_app" / "doover_config.json", {"a": _device(name="a")})
        (tmp_path / "py_app" / "pyproject.toml").touch()
        _write(tmp_path / "rs_app" / "doover_config.json", {"b": _device(name="b")})
        (tmp_path / "rs_app" / "Cargo.toml").touch()

        langs = {a["name"]: a["language"] for a in discover_apps(tmp_path)}
        assert langs == {"a": "py", "b": "rs"}

    def test_an_app_that_deploys_someone_elses_image_is_not_built(
        self, tmp_path, capsys
    ):
        """No Dockerfile and no source: still a DEV app, so `type` cannot tell them
        apart -- and CI must not try to build it, nor warn about a language it
        does not need."""
        _write(
            tmp_path / "doover_config.json",
            {
                "rtsp": _device(
                    name="rtsp", image_name="ghcr.io/spaneng/rtsptoweb:master"
                )
            },
        )
        (tmp_path / "docker-compose.yml").touch()

        apps = discover_apps(tmp_path)
        assert apps[0]["builds_image"] is False
        assert apps[0]["language"] is None
        assert "warning" not in capsys.readouterr().err

    def test_a_buildable_app_with_no_manifest_warns(self, tmp_path, capsys):
        """A Dockerfile but no pyproject/Cargo is genuinely ambiguous, and the
        message has to name the file since an agent only sees stdout/stderr."""
        _write(tmp_path / "doover_config.json", {"foo": _device(name="foo")})
        (tmp_path / "Dockerfile").touch()

        apps = discover_apps(tmp_path)
        assert apps[0]["builds_image"] is True
        assert apps[0]["language"] is None
        err = capsys.readouterr().err
        assert "doover_config.json" in err and "Cargo.toml" in err

    def test_no_build_sentinel_is_respected(self, tmp_path):
        _write(
            tmp_path / "doover_config.json",
            {"foo": _device(name="foo", build_args="NO_BUILD")},
        )
        (tmp_path / "Dockerfile").touch()
        (tmp_path / "pyproject.toml").touch()

        assert discover_apps(tmp_path)[0]["builds_image"] is False

    def test_widgets_are_reported(self, tmp_path):
        _write(
            tmp_path / "doover_config.json",
            {"foo": _device(name="foo", build_widget_command="npm run build")},
        )
        (tmp_path / "pyproject.toml").touch()

        assert discover_apps(tmp_path)[0]["widget"] is True

    def test_noise_directories_are_skipped(self, tmp_path):
        """Otherwise a vendored copy inside .venv or node_modules becomes an app."""
        _write(tmp_path / "doover_config.json", {"foo": _device(name="foo")})
        (tmp_path / "pyproject.toml").touch()
        for noise in (".venv", "node_modules", "target", ".git"):
            _write(
                tmp_path / noise / "doover_config.json", {"junk": _device(name="junk")}
            )

        assert [a["name"] for a in discover_apps(tmp_path)] == ["foo"]

    def test_entries_without_a_type_are_ignored(self, tmp_path):
        """Only `type` marks an app entry; other top-level keys are config."""
        _write(
            tmp_path / "doover_config.json",
            {"foo": _device(name="foo"), "some_settings": {"colour": "red"}},
        )
        (tmp_path / "pyproject.toml").touch()

        assert [a["name"] for a in discover_apps(tmp_path)] == ["foo"]

    def test_an_unreadable_config_does_not_stop_the_others(self, tmp_path, capsys):
        _write(tmp_path / "good" / "doover_config.json", {"good": _device(name="good")})
        (tmp_path / "good" / "pyproject.toml").touch()
        (tmp_path / "bad").mkdir()
        (tmp_path / "bad" / "doover_config.json").write_text("{not json")

        apps = discover_apps(tmp_path)
        assert [a["name"] for a in apps] == ["good"]
        assert "could not read" in capsys.readouterr().err

    def test_empty_repository_returns_nothing(self, tmp_path):
        assert discover_apps(tmp_path) == []
