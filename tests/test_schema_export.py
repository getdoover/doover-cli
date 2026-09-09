"""How an app's schemas get regenerated, per language.

The schema in doover_config.json is generated from source at publish time, so
the export has to work for both languages a repo can be written in. Python runs
a console script under uv; Rust runs the binary's own `export` subcommand, which
writes the config and UI schemas together.
"""

import pytest

from doover_cli.utils import apps as apps_utils


@pytest.fixture
def calls(monkeypatch):
    """Record what would have been run, without running it."""
    recorded = {"run": [], "uv": []}
    monkeypatch.setattr(
        apps_utils, "run", lambda cmd, cwd=None: recorded["run"].append((cmd, cwd))
    )
    monkeypatch.setattr(
        apps_utils,
        "call_with_uv",
        lambda *a, **kw: recorded["uv"].append((a, kw)),
    )
    return recorded


class TestDetectLanguage:
    def test_cargo_toml_means_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").touch()
        assert apps_utils.detect_language(tmp_path) == "rs"

    def test_pyproject_means_python(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        assert apps_utils.detect_language(tmp_path) == "py"

    def test_neither_is_unknown(self, tmp_path):
        assert apps_utils.detect_language(tmp_path) is None


class TestRunSchemaExport:
    def test_python_app_runs_its_console_script_under_uv(self, tmp_path, calls):
        (tmp_path / "pyproject.toml").touch()

        apps_utils.run_schema_export(tmp_path, None, "export-config", app_name="foo")

        assert calls["run"] == []
        assert calls["uv"][0][0] == ("export-config",)

    def test_python_app_honours_a_configured_command(self, tmp_path, calls):
        (tmp_path / "pyproject.toml").touch()

        apps_utils.run_schema_export(
            tmp_path, "export-config-processor", "export-config"
        )

        assert calls["uv"][0][0] == ("export-config-processor",)

    def test_rust_app_runs_its_export_subcommand(self, tmp_path, calls):
        (tmp_path / "Cargo.toml").touch()

        apps_utils.run_schema_export(
            tmp_path,
            None,
            "export-config",
            app_name="foo",
            rust_default=apps_utils.RUST_EXPORT_COMMAND,
        )

        assert calls["uv"] == []
        cmd, cwd = calls["run"][0]
        assert cmd.startswith("cargo run --quiet -- export doover_config.json")
        assert cmd.endswith("--app-name foo")
        assert cwd == tmp_path

    def test_rust_app_without_an_app_name_leaves_the_flag_off(self, tmp_path, calls):
        (tmp_path / "Cargo.toml").touch()

        apps_utils.run_schema_export(
            tmp_path, None, "export-config", rust_default=apps_utils.RUST_EXPORT_COMMAND
        )

        assert "--app-name" not in calls["run"][0][0]

    def test_a_rust_app_runs_nothing_for_a_second_schema_kind(self, tmp_path, calls):
        """The UI and notification exporters, which pass no rust_default.

        A doover-rs binary has one `export` that writes every schema it has, so
        the config exporter already ran it. Inventing the same command again is
        what hung doover-device-runtime for 75 minutes: its binary is a
        supervisor that accepts any argv, so `export` started it supervising.
        """
        (tmp_path / "Cargo.toml").touch()

        apps_utils.run_schema_export(tmp_path, None, "export-ui", app_name="foo")

        assert calls["run"] == []
        assert calls["uv"] == []

    def test_a_rust_app_still_honours_an_explicit_command(self, tmp_path, calls):
        """An app that really does have a second exporter says so."""
        (tmp_path / "Cargo.toml").touch()

        apps_utils.run_schema_export(
            tmp_path, "cargo run --bin exporter -- ui", "export-ui", app_name="foo"
        )

        assert calls["run"][0][0].startswith("cargo run --bin exporter -- ui")

    def test_a_python_app_is_unaffected_by_the_rust_default(self, tmp_path, calls):
        (tmp_path / "pyproject.toml").touch()

        apps_utils.run_schema_export(tmp_path, None, "export-ui", app_name="foo")

        assert calls["uv"][0][0] == ("export-ui",)

    def test_a_configured_rust_command_wins(self, tmp_path, calls):
        """A workspace with several binaries names the one to run itself."""
        (tmp_path / "Cargo.toml").touch()

        apps_utils.run_schema_export(
            tmp_path,
            "cargo run --bin doover-tunnels -- export",
            "export-config",
            app_name="doover_tunnels",
        )

        assert calls["run"][0][0] == (
            "cargo run --bin doover-tunnels -- export --app-name doover_tunnels"
        )

    def test_an_app_name_already_in_the_command_is_not_repeated(self, tmp_path, calls):
        (tmp_path / "Cargo.toml").touch()

        apps_utils.run_schema_export(
            tmp_path,
            "cargo run -- export --app-name explicit",
            "export-config",
            app_name="ignored",
        )

        assert calls["run"][0][0].count("--app-name") == 1
        assert calls["run"][0][0].endswith("explicit")


class TestNoExport:
    """`export_config_command: NO_EXPORT` -- an app that holds no config of its
    own. Publishing one used to require giving it an exporter that wrote
    nothing; `export_ui_command` has always had this escape hatch."""

    def _repo(self, tmp_path, **entry):
        import json

        (tmp_path / "doover_config.json").write_text(
            json.dumps({"foo": {"type": "DEV", "name": "foo", **entry}})
        )
        (tmp_path / "Cargo.toml").touch()
        return tmp_path

    def test_config_export_is_skipped(self, tmp_path, calls, capsys):
        from typer.testing import CliRunner

        from doover_cli import app

        repo = self._repo(tmp_path, export_config_command="NO_EXPORT")
        result = CliRunner().invoke(
            app, ["config-schema", "export", str(repo), "--app-name", "foo"]
        )

        assert result.exit_code == 0, result.output
        assert calls["run"] == []
        assert calls["uv"] == []

    def test_config_export_runs_without_it(self, tmp_path, calls):
        from typer.testing import CliRunner

        from doover_cli import app

        repo = self._repo(tmp_path)
        result = CliRunner().invoke(
            app, ["config-schema", "export", str(repo), "--app-name", "foo"]
        )

        assert result.exit_code == 0, result.output
        assert calls["run"], "the Rust exporter should have run"
        assert "--app-name foo" in calls["run"][0][0]


class TestUiSchemaValidation:
    def _config(self, tmp_path, value):
        import json

        entry = {"type": "DEV", "name": "foo"}
        if value is not ...:
            entry["ui_schema"] = value
        (tmp_path / "doover_config.json").write_text(json.dumps({"foo": entry}))
        return tmp_path / "doover_config.json"

    @pytest.mark.parametrize("value", [None, ...], ids=["explicit null", "absent"])
    def test_an_app_with_no_ui_passes(self, tmp_path, value):
        """A null ui_schema is how an app says it has no UI -- the three core
        device apps all ship one."""
        from doover_cli.ui_schema import _validate_ui_file

        _validate_ui_file(self._config(tmp_path, value))

    def test_a_malformed_ui_schema_still_fails(self, tmp_path):
        import typer

        from doover_cli.ui_schema import _validate_ui_file

        with pytest.raises(typer.Exit):
            _validate_ui_file(self._config(tmp_path, "not a schema"))
